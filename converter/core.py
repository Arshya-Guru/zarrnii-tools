"""Format conversion between NIfTI, HDF5 (.h5) and OME-Zarr, via zarrnii.

HDF5 files are written with ``ZarrNii.to_imaris``, so their internal layout is
Imaris's (image at ``/DataSet/ResolutionLevel 0/TimePoint 0/Channel 0/Data``,
z, y, x order), just saved with a .h5 extension. Real Imaris .ims files are
accepted as input too.

All reading and writing goes through zarrnii. A few corrections are applied
around it so round trips are lossless:

* zarrnii's NIfTI reader always returns float64; we cast back to the dtype
  stored in the file when that is lossless (otherwise zarr/h5 outputs would
  double in size).
* ``ZarrNii.to_imaris`` labels its voxel sizes "um" but writes the internal
  millimetre values, so we hand it an image whose spacing is already in um.
* ``ZarrNii.to_imaris`` silently casts any dtype other than float/(u)int16 to
  uint8; we pick a safe dtype up front and refuse if the values don't fit.
* ``ZarrNii.to_imaris`` always appends ".ims", and ``ZarrNii.from_imaris``
  refuses any other extension, so .h5 files are written via a temporary .ims
  name and read through a temporary .ims symlink.
* For ilastik, an "ilastik-friendly" .h5 keeps only the full-resolution image
  (plus the metadata zarrnii needs to read it back), dropping the thumbnail
  and pyramid levels that otherwise make ilastik ask which datasets to stack.
* ``ZarrNii.to_nifti`` fails on 64-bit integers (nibabel refuses them); we
  store them in the smallest integer type that holds the values.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from zarrnii import ZarrNii

FORMATS = {
    "h5": ("HDF5 (.h5)", ".h5"),
    "zarr": ("OME-Zarr (.ome.zarr)", ".ome.zarr"),
    "nifti": ("NIfTI (.nii.gz)", ".nii.gz"),
}

# Longest suffixes first so ".ome.zarr" wins over ".zarr", ".nii.gz" over ".gz".
_INPUT_SUFFIXES = [
    (".ome.zarr.zip", "zarr"),
    (".ome.zarr", "zarr"),
    (".zarr", "zarr"),
    (".nii.gz", "nifti"),
    (".nii", "nifti"),
    (".h5", "h5"),
    (".hdf5", "h5"),
    (".ims", "h5"),
    (".ome.tiff", "tif"),
    (".ome.tif", "tif"),
    (".tiff", "tif"),
    (".tif", "tif"),
]


def detect_format(path: str | os.PathLike) -> tuple[str, str]:
    """Return (format key, stem) for an input path."""
    name = Path(path).name
    lower = name.lower()
    for suffix, fmt in _INPUT_SUFFIXES:
        if lower.endswith(suffix):
            return fmt, name[: -len(suffix)]
    if Path(path).is_dir():
        # A zarr store without the conventional suffix.
        return "zarr", name
    raise ValueError(f"Unrecognised file type: {name}")


def output_path(src: str | os.PathLike, fmt: str, out_dir: str | os.PathLike | None = None) -> Path:
    _, stem = detect_format(src)
    folder = Path(out_dir) if out_dir else Path(src).parent
    return folder / (stem + FORMATS[fmt][1])


@dataclass
class ImageInfo:
    shape: dict
    dtype: str
    voxel_um: dict
    channels: list
    orientation: str

    def summary(self) -> str:
        shape = " × ".join(f"{k}={v}" for k, v in self.shape.items())
        vox = " × ".join(f"{k}={v:.4g}" for k, v in self.voxel_um.items())
        chans = ", ".join(self.channels) if self.channels else str(self.shape.get("c", 1))
        return (
            f"shape: {shape}\n"
            f"dtype: {self.dtype}\n"
            f"voxel size (µm): {vox}\n"
            f"orientation: {self.orientation}\n"
            f"channels: {chans}"
        )


def _nifti_stored_dtype(path) -> np.dtype | None:
    """Dtype stored on disk, if casting zarrnii's float64 back to it is lossless."""
    import nibabel as nib

    hdr = nib.load(str(path)).header
    slope, inter = hdr.get_slope_inter()
    if (slope not in (None, 1.0)) or (inter not in (None, 0.0)):
        return None  # scaled data: the float values are the real ones
    return np.dtype(hdr.get_data_dtype())


_link_dir = None


def _as_ims_path(path: str) -> str:
    """A .ims-named path to ``path``, since zarrnii's Imaris reader requires one.

    The link must outlive the (lazy) dask array, so links are kept in one
    temp folder removed at exit. Windows only allows symlinks with admin
    rights or Developer Mode, so fall back to a hard link (same drive only),
    then to a copy.
    """
    global _link_dir
    if path.lower().endswith(".ims"):
        return path
    if _link_dir is None:
        _link_dir = tempfile.mkdtemp(prefix="zarrnii_h5_")
        atexit.register(shutil.rmtree, _link_dir, ignore_errors=True)
    link = os.path.join(_link_dir, f"{uuid.uuid4().hex}.ims")
    src = os.path.abspath(path)
    for make_link in (os.symlink, os.link, shutil.copyfile):
        try:
            make_link(src, link)
            return link
        except OSError:
            continue
    raise OSError(f"Could not create a temporary .ims alias for {path}")


def load(path: str | os.PathLike, level: int = 0) -> ZarrNii:
    """Load any supported image with zarrnii."""
    path = str(path)
    fmt, _ = detect_format(path)
    if fmt == "nifti":
        znii = ZarrNii.from_nifti(path)
        stored = _nifti_stored_dtype(path)
        if stored is not None and stored != znii.data.dtype:
            znii.ngff_image.data = znii.data.astype(stored)
        return znii
    if fmt == "zarr":
        return ZarrNii.from_ome_zarr(path, level=level)
    if fmt == "h5":
        return ZarrNii.from_imaris(_as_ims_path(path), level=level)
    return ZarrNii.from_file(path)


def describe(znii: ZarrNii) -> ImageInfo:
    shape = dict(zip(znii.dims, znii.data.shape))
    # zarrnii keeps spacing internally in millimetres.
    voxel_um = {ax: znii.scale[ax] * 1000.0 for ax in ("x", "y", "z")}
    try:
        channels = list(znii.list_channels() or [])
    except Exception:
        channels = []
    return ImageInfo(shape, str(znii.data.dtype), voxel_um, channels, znii.orientation)


def _imaris_dtype(znii: ZarrNii, log) -> np.dtype:
    """dtype to_imaris will store faithfully, or raise if none fits."""
    dt = znii.data.dtype
    if dt in (np.float32, np.uint16, np.int16, np.uint8):
        return dt
    if dt == np.float64:
        log("note: HDF5 (Imaris layout) stores floats as float32; float64 values will be rounded")
        return np.dtype(np.float32)
    if dt == np.bool_:
        return np.dtype(np.uint8)
    if np.issubdtype(dt, np.integer):
        cand, lo, hi = _smallest_int(znii, (np.uint8, np.uint16, np.int16))
        if cand is not None:
            if cand != dt:
                log(f"note: storing {dt} as {cand} (values {lo}..{hi} fit)")
            return cand
        raise ValueError(
            f"{dt} values {lo}..{hi} don't fit in uint8/uint16/int16, the integer "
            "types the HDF5 (Imaris) layout supports. Use OME-Zarr instead."
        )
    raise ValueError(f"HDF5 (Imaris layout) can't store dtype {dt}. Use OME-Zarr instead.")


def _smallest_int(znii: ZarrNii, candidates) -> tuple[np.dtype | None, int, int]:
    lo, hi = (int(v) for v in (znii.data.min().compute(), znii.data.max().compute()))
    for cand in candidates:
        info = np.iinfo(cand)
        if info.min <= lo and hi <= info.max:
            return np.dtype(cand), lo, hi
    return None, lo, hi


def _write_nifti(znii: ZarrNii, dst: Path, log) -> None:
    dt = znii.data.dtype
    if dt in (np.int64, np.uint64):
        cand, lo, hi = _smallest_int(znii, (np.uint8, np.int16, np.uint16, np.int32, np.uint32))
        if cand is None:
            raise ValueError(f"{dt} values {lo}..{hi} don't fit in a 32-bit integer for NIfTI")
        log(f"note: storing {dt} as {cand} (values {lo}..{hi} fit)")
        znii.ngff_image.data = znii.data.astype(cand)
    znii.to_nifti(str(dst))


_LEVEL0 = "DataSet/ResolutionLevel 0"


def _slim_copy(src: Path, dst: Path, voxel_um: dict) -> int:
    """Copy only level 0 + metadata of an Imaris-layout file. Returns channel count."""
    import json

    import h5py

    with h5py.File(src, "r") as fin, h5py.File(dst, "w") as fout:
        for k, v in fin.attrs.items():
            fout.attrs[k] = v
        for name in ("DataSetInfo", "DataSetTimes"):
            if name in fin:
                fin.copy(fin[name], fout, name=name)
        fout.create_group("DataSet")
        fin.copy(fin[_LEVEL0], fout["DataSet"], name="ResolutionLevel 0")
        for k, v in fin["DataSet"].attrs.items():
            fout["DataSet"].attrs[k] = v
        # vigra axistags, so ilastik reads the axes as z, y, x without guessing.
        axistags = json.dumps({"axes": [
            {"key": ax, "typeFlags": 2, "resolution": float(voxel_um[ax]), "description": ""}
            for ax in "zyx"
        ]})
        channels = [g for g in fout[_LEVEL0]["TimePoint 0"].values()]
        for ch in channels:
            ch["Data"].attrs["axistags"] = axistags
        return len(channels)


def _write_h5(znii: ZarrNii, dst: Path, compression: int, log, ilastik: bool = True) -> None:
    dtype = _imaris_dtype(znii, log)
    order = list(znii.axes_order.lower())  # e.g. ['x','y','z']
    spacing_um = tuple(znii.scale[ax] * 1000.0 for ax in order)
    origin_um = tuple(znii.translation[ax] * 1000.0 for ax in order)
    try:
        labels = list(znii.list_channels() or []) or None
    except Exception:
        labels = None
    # Spacing given without axes_units is taken as-is, so the numbers to_imaris
    # writes (labelled "um") really are micrometres.
    in_um = ZarrNii.from_darr(
        znii.data.astype(dtype),
        axes_order=znii.axes_order,
        orientation=znii.orientation,
        spacing=spacing_um,
        origin=origin_um,
        channel_labels=labels,
    )
    tmp = dst.with_name(dst.name + ".partial.ims")
    try:
        in_um.to_imaris(str(tmp), compression_opts=compression)
        if ilastik:
            voxel_um = dict(zip(order, spacing_um))
            n_channels = _slim_copy(tmp, dst, voxel_um)
            log(f"ilastik-friendly: kept only {_LEVEL0}/TimePoint 0/Channel 0/Data")
            if n_channels > 1:
                log(f"note: {n_channels} channels are stored as separate datasets; in ilastik "
                    "use the pattern 'DataSet/ResolutionLevel 0/TimePoint 0/Channel */Data' and stack along c")
        else:
            os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)
    if any(origin_um):
        log("note: the HDF5 layout stores no origin offset; the image will read back at origin 0")
    if znii.orientation != "RAS":
        log(f"note: the HDF5 layout stores no orientation; {znii.orientation} will read back as RAS")


def convert(
    src: str | os.PathLike,
    fmt: str,
    out_dir: str | os.PathLike | None = None,
    *,
    level: int = 0,
    zarr_format: int = 3,
    h5_compression: int = 6,
    ilastik: bool = True,
    overwrite: bool = False,
    log=print,
) -> Path:
    """Convert one image to ``fmt`` ('h5', 'zarr' or 'nifti'). Returns the output path."""
    dst = output_path(src, fmt, out_dir)
    if Path(src).resolve() == dst.resolve():
        raise ValueError("Output would overwrite the input file")
    if dst.exists():
        if not overwrite:
            raise FileExistsError(f"{dst.name} already exists (tick 'Overwrite' to replace it)")
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()

    dst.parent.mkdir(parents=True, exist_ok=True)

    log(f"reading {Path(src).name}")
    znii = load(src, level=level)
    log(describe(znii).summary())

    log(f"writing {dst.name}")
    if fmt == "h5":
        _write_h5(znii, dst, h5_compression, log, ilastik=ilastik)
    elif fmt == "zarr":
        znii.to_ome_zarr(str(dst), zarr_format=zarr_format)
    elif fmt == "nifti":
        _write_nifti(znii, dst, log)
    else:
        raise ValueError(f"Unknown output format: {fmt}")
    return dst
