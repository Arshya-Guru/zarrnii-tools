"""GUI for building combined_fullres.nii.gz in patch folders, with zarrnii.

combined = 1 where lantern_pred_fullres > 0   (plaque; wins where both masks overlap)
           2 where vesselfm_abeta_fullres > 0 (vessel-related) and not plaque
           0 elsewhere

Run with:  pixi run mask [folder ...]
"""

from __future__ import annotations

import sys
import traceback
import warnings
from pathlib import Path

import dask.array as da
import numpy as np
from qtpy.QtCore import QObject, Qt, QThread, Signal
from qtpy.QtGui import QFontDatabase
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from converter.core import load

warnings.filterwarnings("ignore")

LANTERN = "lantern_pred_fullres.nii.gz"
VESSEL = "vesselfm_abeta_fullres.nii.gz"
COMBINED = "combined_fullres.nii.gz"


def is_patch_folder(path: Path) -> bool:
    return (path / LANTERN).exists() and (path / VESSEL).exists()


def find_patch_folders(path: Path) -> list[Path]:
    """The folder itself if it is a patch folder, else its patch subfolders."""
    if is_patch_folder(path):
        return [path]
    return sorted(p for p in path.iterdir() if p.is_dir() and is_patch_folder(p))


def build_combined(folder: Path, overwrite: bool = False, log=print) -> Path:
    dst = folder / COMBINED
    if dst.exists() and not overwrite:
        raise FileExistsError(f"{COMBINED} already exists (tick 'Overwrite' to rebuild it)")

    lantern = load(folder / LANTERN)
    vessel = load(folder / VESSEL)
    if lantern.data.shape != vessel.data.shape:
        raise ValueError(f"grid mismatch: {LANTERN} {lantern.data.shape} vs {VESSEL} {vessel.data.shape}")

    lantern_np = np.asarray(lantern.data)
    vessel_np = np.asarray(vessel.data)
    combined = np.zeros(lantern_np.shape, dtype=np.uint8)
    combined[vessel_np > 0] = 2
    combined[lantern_np > 0] = 1

    # Written on LANTERN's grid so the affine matches the inputs exactly.
    out = lantern.copy()
    out.ngff_image.data = da.from_array(combined, chunks=combined.shape)
    out.to_nifti(str(dst))

    counts = np.bincount(combined.ravel(), minlength=3)
    both = int(((lantern_np > 0) & (vessel_np > 0)).sum())
    log(f"label 1 (plaque): {counts[1]:,} voxels  ({both:,} also in VesselFM)")
    log(f"label 2 (vessel-related): {counts[2]:,} voxels")
    return dst


class Worker(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(int, int)

    def __init__(self, folders, overwrite):
        super().__init__()
        self.folders, self.overwrite = folders, overwrite

    def run(self):
        ok = 0
        for i, folder in enumerate(self.folders):
            self.log.emit(f"\n── [{i + 1}/{len(self.folders)}] {Path(folder).name}")
            try:
                dst = build_combined(Path(folder), self.overwrite, log=self.log.emit)
                self.log.emit(f"✔ saved {dst}")
                ok += 1
            except Exception as e:
                self.log.emit(f"✘ {type(e).__name__}: {e}")
                if not isinstance(e, (ValueError, FileExistsError)):
                    self.log.emit(traceback.format_exc())
            self.progress.emit(i + 1)
        self.finished.emit(ok, len(self.folders))


class FolderList(QListWidget):
    """Patch folders; dropping or adding a parent folder adds its patch subfolders."""

    def __init__(self, log):
        super().__init__()
        self._log = log
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def add_folder(self, path):
        path = Path(path)
        if not path.is_dir():
            return
        found = find_patch_folders(path)
        if not found:
            self._log(f"No patch folders (with {LANTERN} and {VESSEL}) in {path}")
        existing = set(self.paths())
        for p in found:
            if str(p) not in existing:
                self.addItem(str(p))

    def paths(self):
        return [self.item(i).text() for i in range(self.count())]

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            self.add_folder(u.toLocalFile().rstrip("/"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Combined Mask Builder — LANTERN + VesselFM")
        self.resize(820, 620)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        self.folders = FolderList(self.log_view.appendPlainText)
        add = QPushButton("Add folder…")
        add.clicked.connect(self.pick_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: [self.folders.takeItem(self.folders.row(i)) for i in self.folders.selectedItems()])
        clear = QPushButton("Clear")
        clear.clicked.connect(self.folders.clear)
        btns = QHBoxLayout()
        for b in (add, remove, clear):
            btns.addWidget(b)
        btns.addStretch()

        in_box = QGroupBox("1. Patch folders  (pick one patch, or a parent folder to add all its patches)")
        in_layout = QVBoxLayout(in_box)
        in_layout.addLayout(btns)
        in_layout.addWidget(self.folders)

        rule = QLabel(
            f"Writes <b>{COMBINED}</b> into each folder:<br>"
            f"&nbsp;&nbsp;1 = voxel is 1 in {LANTERN} (also where VesselFM overlaps)<br>"
            f"&nbsp;&nbsp;2 = voxel is labelled in {VESSEL} but not in LANTERN<br>"
            "&nbsp;&nbsp;0 = everything else"
        )
        rule.setTextFormat(Qt.RichText)
        rule_box = QGroupBox("2. Rule")
        QVBoxLayout(rule_box).addWidget(rule)

        self.overwrite = QCheckBox(f"Overwrite existing {COMBINED}")
        self.run_btn = QPushButton("Build combined masks")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.start)
        self.progress = QProgressBar()

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        for w in (in_box, rule_box, self.overwrite, self.run_btn, self.progress):
            top_layout.addWidget(w)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.log_view)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        central = QWidget()
        QVBoxLayout(central).addWidget(split)
        self.setCentralWidget(central)

    def pick_folder(self):
        paths = self.folders.paths()
        start = str(Path(paths[-1]).parent) if paths else str(Path.home() / "Documents")
        path = QFileDialog.getExistingDirectory(self, "Choose a patch folder (or its parent)", start)
        if path:
            self.folders.add_folder(path)

    def start(self):
        jobs = self.folders.paths()
        if not jobs:
            self.log_view.appendPlainText("Add at least one patch folder first.")
            return
        self.run_btn.setEnabled(False)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.log_view.appendPlainText(f"Building {COMBINED} in {len(jobs)} folder(s)")

        self.worker = Worker(jobs, self.overwrite.isChecked())
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.log.connect(self.log_view.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self._done)
        self.thread.start()

    def _done(self, ok, total):
        self.log_view.appendPlainText(f"\nDone: {ok}/{total} built.")
        self.run_btn.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    for a in sys.argv[1:]:
        win.folders.add_folder(a.rstrip("/"))
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
