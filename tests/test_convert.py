import h5py
import nibabel as nib
import numpy as np
import pytest
from conftest import save_nifti

from converter.core import convert, detect_format


def roundtrip(src, via, tmp_path, **kw):
    mid = convert(src, via, tmp_path / "mid", log=lambda *a: None, **kw)
    back = convert(mid, "nifti", tmp_path / "back", log=lambda *a: None)
    return mid, nib.load(str(back))


@pytest.mark.parametrize("via", ["h5", "zarr"])
@pytest.mark.parametrize("dtype", [np.float32, np.uint8, np.uint16, np.int16])
def test_roundtrip_is_lossless(tmp_path, rng, via, dtype):
    data = (rng.random((20, 30, 40)) * 200).astype(dtype)
    src = save_nifti(tmp_path / "img.nii.gz", data)
    orig = nib.load(str(src))
    mid, back = roundtrip(src, via, tmp_path)
    assert mid.name == f"img{'.h5' if via == 'h5' else '.ome.zarr'}"
    assert back.get_data_dtype() == dtype
    np.testing.assert_array_equal(np.asarray(back.dataobj), data)
    np.testing.assert_allclose(back.header.get_zooms()[:3], orig.header.get_zooms()[:3], rtol=1e-5)
    np.testing.assert_allclose(back.affine, orig.affine, atol=1e-6)


def test_int64_labels_are_narrowed(tmp_path, rng):
    data = rng.integers(0, 3, (10, 12, 14)).astype(np.int64)
    src = save_nifti(tmp_path / "mask.nii.gz", data, dtype=np.int64)
    for via in ("h5", "zarr"):
        _, back = roundtrip(src, via, tmp_path / via)
        assert back.get_data_dtype() == np.uint8
        np.testing.assert_array_equal(np.asarray(back.dataobj), data)


def test_h5_refuses_values_that_dont_fit(tmp_path, rng):
    src = save_nifti(tmp_path / "big.nii.gz", rng.integers(0, 100_000, (8, 8, 8)).astype(np.int32))
    with pytest.raises(ValueError, match="don't fit"):
        convert(src, "h5", tmp_path, log=lambda *a: None)


def test_ilastik_h5_has_one_image(tmp_path, rng):
    src = save_nifti(tmp_path / "img.nii.gz", rng.random((20, 30, 40), dtype=np.float32))
    dst = convert(src, "h5", tmp_path / "out", log=lambda *a: None)
    images = []
    with h5py.File(dst) as f:
        f.visititems(lambda n, o: images.append(n) if isinstance(o, h5py.Dataset) and o.ndim >= 2 else None)
        assert images == ["DataSet/ResolutionLevel 0/TimePoint 0/Channel 0/Data"]
        assert f[images[0]].shape == (40, 30, 20)  # z, y, x
        assert "axistags" in f[images[0]].attrs
    assert not list((tmp_path / "out").glob("*.ims")), "temporary .ims left behind"


def test_full_imaris_layout_when_ilastik_off(tmp_path, rng):
    src = save_nifti(tmp_path / "img.nii.gz", rng.random((20, 30, 40), dtype=np.float32))
    dst = convert(src, "h5", tmp_path, ilastik=False, log=lambda *a: None)
    with h5py.File(dst) as f:
        assert "Thumbnail" in f


def test_refuses_to_overwrite_without_flag(tmp_path, rng):
    src = save_nifti(tmp_path / "img.nii.gz", rng.random((8, 8, 8), dtype=np.float32))
    convert(src, "zarr", tmp_path, log=lambda *a: None)
    with pytest.raises(FileExistsError):
        convert(src, "zarr", tmp_path, log=lambda *a: None)
    convert(src, "zarr", tmp_path, overwrite=True, log=lambda *a: None)


def test_detect_format():
    assert detect_format("a/b.nii.gz") == ("nifti", "b")
    assert detect_format("b.ome.zarr") == ("zarr", "b")
    assert detect_format("b.H5") == ("h5", "b")
    assert detect_format("b.ims") == ("h5", "b")


@pytest.mark.parametrize("blocked", [("symlink",), ("symlink", "link")])
def test_h5_reads_without_symlinks(tmp_path, rng, monkeypatch, blocked):
    """Windows without admin/Developer Mode can't symlink; reading must still work."""
    import os

    data = rng.random((10, 12, 14)).astype(np.float32)
    src = save_nifti(tmp_path / "img.nii.gz", data)
    h5 = convert(src, "h5", tmp_path / "mid", log=lambda *a: None)

    def refuse(*a, **k):
        raise OSError("not permitted")

    for name in blocked:
        monkeypatch.setattr(os, name, refuse)
    back = convert(h5, "nifti", tmp_path / "back", log=lambda *a: None)
    np.testing.assert_array_equal(np.asarray(nib.load(str(back)).dataobj), data)
