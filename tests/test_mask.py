import nibabel as nib
import numpy as np
import pytest

from converter.mask import COMBINED, build_combined, find_patch_folders


def test_combined_rule(patch_folder):
    dst = build_combined(patch_folder, log=lambda *a: None)
    lantern_img = nib.load(str(patch_folder / "lantern_pred_fullres.nii.gz"))
    lantern = np.asarray(lantern_img.dataobj)
    vessel = np.asarray(nib.load(str(patch_folder / "vesselfm_abeta_fullres.nii.gz")).dataobj)
    out = nib.load(str(dst))
    combined = np.asarray(out.dataobj)

    assert out.get_data_dtype() == np.uint8
    np.testing.assert_allclose(out.affine, lantern_img.affine, atol=1e-6)
    assert np.all(combined[lantern > 0] == 1)  # plaque, including overlaps
    assert np.all(combined[(vessel > 0) & (lantern == 0)] == 2)
    assert np.all(combined[(vessel == 0) & (lantern == 0)] == 0)
    assert ((lantern > 0) & (vessel > 0)).any(), "fixture should contain overlaps"


def test_does_not_overwrite_edits(patch_folder):
    build_combined(patch_folder, log=lambda *a: None)
    with pytest.raises(FileExistsError):
        build_combined(patch_folder, log=lambda *a: None)
    build_combined(patch_folder, overwrite=True, log=lambda *a: None)


def test_find_patch_folders(patch_folder, tmp_path):
    (tmp_path / "not_a_patch").mkdir()
    assert find_patch_folders(tmp_path) == [patch_folder]
    assert find_patch_folders(patch_folder) == [patch_folder]
    assert (patch_folder / COMBINED).exists() is False
