import os
import sys
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

# GUI tests run without a display (CI machines, ssh sessions).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
warnings.filterwarnings("ignore")

VOXEL_MM = (0.004, 0.001625, 0.001625)


def save_nifti(path, data, affine=None, dtype=None):
    if affine is None:
        affine = np.diag([*VOXEL_MM, 1.0])
    nib.save(nib.Nifti1Image(data, affine, dtype=dtype or data.dtype), str(path))
    return path


@pytest.fixture
def rng():
    return np.random.default_rng(0)


@pytest.fixture
def patch_folder(tmp_path, rng):
    """A small fake patch folder laid out like the real ones."""
    folder = tmp_path / "sub-test_01_isocortex"
    folder.mkdir()
    shape = (16, 24, 32)
    save_nifti(folder / "abeta_fullres.nii.gz", rng.random(shape, dtype=np.float32) * 5000)
    lantern = (rng.random(shape) > 0.9).astype(np.uint8)
    vessel = (rng.random(shape) > 0.7).astype(np.uint8)
    save_nifti(folder / "lantern_pred_fullres.nii.gz", lantern)
    save_nifti(folder / "vesselfm_abeta_fullres.nii.gz", vessel)
    return folder
