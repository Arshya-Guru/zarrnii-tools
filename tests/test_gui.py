"""Drive both windows end to end without a display."""

import pytest
from conftest import save_nifti
from qtpy.QtWidgets import QApplication

from converter import gui, mask


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def run_to_end(app, window):
    window.start()
    while window.thread.isRunning():
        app.processEvents()
        window.thread.wait(50)
    app.processEvents()
    return window.log_view.toPlainText()


def test_converter_window(app, tmp_path, rng):
    src = save_nifti(tmp_path / "img.nii.gz", rng.random((8, 10, 12)).astype("float32"))
    w = gui.MainWindow()
    w.files.add_paths([str(src)])
    w.same_dir.setChecked(False)
    w.out_dir.setText(str(tmp_path / "out"))
    log = run_to_end(app, w)
    assert "Done: 1/1" in log, log
    assert (tmp_path / "out" / "img.h5").exists()


def test_mask_window_adds_patches_from_parent(app, patch_folder):
    w = mask.MainWindow()
    w.folders.add_folder(str(patch_folder.parent))
    assert w.folders.paths() == [str(patch_folder)]
    log = run_to_end(app, w)
    assert "Done: 1/1" in log, log
    assert (patch_folder / mask.COMBINED).exists()
