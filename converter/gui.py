"""GUI for converting images between NIfTI, HDF5 (.h5) and OME-Zarr with zarrnii.

Run with:  pixi run app
"""

from __future__ import annotations

import sys
import traceback
import warnings
from pathlib import Path

from qtpy.QtCore import QObject, Qt, QThread, Signal
from qtpy.QtGui import QFontDatabase
from qtpy.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from converter.core import FORMATS, convert, describe, detect_format, load

warnings.filterwarnings("ignore")

FILE_FILTER = (
    "Images (*.nii *.nii.gz *.h5 *.hdf5 *.ims *.tif *.tiff *.zip);;"
    "NIfTI (*.nii *.nii.gz);;HDF5 (*.h5 *.hdf5 *.ims);;All files (*)"
)


class Worker(QObject):
    """Runs conversions (or a single info lookup) off the GUI thread."""

    log = Signal(str)
    progress = Signal(int)
    info = Signal(str, str)
    finished = Signal(int, int)

    def __init__(self, jobs=None, options=None, info_path=None):
        super().__init__()
        self.jobs, self.options, self.info_path = jobs or [], options or {}, info_path

    def run(self):
        if self.info_path:
            try:
                text = describe(load(self.info_path, level=self.options.get("level", 0))).summary()
            except Exception as e:
                text = f"Could not read file:\n{e}"
            self.info.emit(self.info_path, text)
            self.finished.emit(0, 0)
            return

        ok = 0
        for i, src in enumerate(self.jobs):
            self.log.emit(f"\n── [{i + 1}/{len(self.jobs)}] {src}")
            try:
                dst = convert(src, log=self.log.emit, **self.options)
                self.log.emit(f"✔ saved {dst}")
                ok += 1
            except Exception as e:
                self.log.emit(f"✘ {type(e).__name__}: {e}")
                if not isinstance(e, (ValueError, FileExistsError)):
                    self.log.emit(traceback.format_exc())
            self.progress.emit(i + 1)
        self.finished.emit(ok, len(self.jobs))


class FileList(QListWidget):
    """List of input paths that accepts dropped files and .zarr folders."""

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def add_paths(self, paths):
        existing = set(self.paths())
        for p in paths:
            if p and p not in existing:
                self.addItem(p)
                existing.add(p)

    def paths(self):
        return [self.item(i).text() for i in range(self.count())]

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        self.add_paths(u.toLocalFile().rstrip("/") for u in e.mimeData().urls())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ZarrNii Converter — NIfTI ⇄ HDF5 (.h5) ⇄ OME-Zarr")
        self.resize(900, 720)
        self.thread = None
        self.info_thread = None

        # Inputs
        self.files = FileList()
        self.files.currentTextChanged.connect(self.show_info)
        add_files = QPushButton("Add files…")
        add_files.clicked.connect(self.pick_files)
        add_zarr = QPushButton("Add .zarr folder…")
        add_zarr.clicked.connect(self.pick_zarr)
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda: [self.files.takeItem(self.files.row(i)) for i in self.files.selectedItems()])
        clear = QPushButton("Clear")
        clear.clicked.connect(self.files.clear)
        btns = QHBoxLayout()
        for b in (add_files, add_zarr, remove, clear):
            btns.addWidget(b)
        btns.addStretch()
        in_box = QGroupBox("1. Input images  (or drag and drop files / .zarr folders here)")
        in_layout = QVBoxLayout(in_box)
        in_layout.addLayout(btns)
        in_layout.addWidget(self.files)
        self.info_label = QLabel("Select a file to see its shape, dtype and voxel size.")
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.info_label.setStyleSheet("padding: 4px;")
        in_layout.addWidget(self.info_label)

        # Output format
        fmt_box = QGroupBox("2. Convert to")
        fmt_layout = QHBoxLayout(fmt_box)
        self.fmt_group = QButtonGroup(self)
        for key, (label, _) in FORMATS.items():
            rb = QRadioButton(label)
            rb.setProperty("fmt", key)
            rb.setChecked(key == "h5")
            self.fmt_group.addButton(rb)
            fmt_layout.addWidget(rb)
        fmt_layout.addStretch()

        # Output location & options
        opt_box = QGroupBox("3. Options")
        form = QFormLayout(opt_box)
        self.same_dir = QCheckBox("Same folder as each input")
        self.same_dir.setChecked(True)
        self.out_dir = QLineEdit()
        self.out_dir.setEnabled(False)
        browse = QPushButton("Choose…")
        browse.setEnabled(False)
        browse.clicked.connect(self.pick_out_dir)
        self.same_dir.toggled.connect(lambda on: (self.out_dir.setEnabled(not on), browse.setEnabled(not on)))
        out_row = QHBoxLayout()
        out_row.addWidget(self.same_dir)
        out_row.addWidget(self.out_dir, 1)
        out_row.addWidget(browse)
        form.addRow("Output folder:", out_row)

        self.zarr_format = QComboBox()
        self.zarr_format.addItem("v3 (default)", 3)
        self.zarr_format.addItem("v2 (older tools)", 2)
        form.addRow("Zarr format:", self.zarr_format)
        self.level = QSpinBox()
        self.level.setRange(0, 10)
        self.level.setToolTip("Resolution level to read from .h5 / .zarr pyramids (0 = full resolution)")
        form.addRow("Read pyramid level:", self.level)
        self.compression = QSpinBox()
        self.compression.setRange(0, 9)
        self.compression.setValue(6)
        form.addRow("HDF5 gzip level:", self.compression)
        self.ilastik = QCheckBox("ilastik-friendly .h5 (full-resolution image only, no thumbnail/pyramid)")
        self.ilastik.setChecked(True)
        self.ilastik.setToolTip(
            "Keeps only DataSet/ResolutionLevel 0/.../Data so ilastik opens the file without "
            "asking which images to stack. Turn off to keep the full Imaris layout."
        )
        form.addRow("", self.ilastik)
        self.overwrite = QCheckBox("Overwrite existing outputs")
        form.addRow("", self.overwrite)

        # Run
        self.run_btn = QPushButton("Convert")
        self.run_btn.setMinimumHeight(36)
        self.run_btn.clicked.connect(self.start)
        self.progress = QProgressBar()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        for w in (in_box, fmt_box, opt_box, self.run_btn, self.progress):
            top_layout.addWidget(w)
        split = QSplitter(Qt.Vertical)
        split.addWidget(top)
        split.addWidget(self.log_view)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        central = QWidget()
        QVBoxLayout(central).addWidget(split)
        self.setCentralWidget(central)

    # ---- pickers -------------------------------------------------------------

    def _start_dir(self):
        paths = self.files.paths()
        return str(Path(paths[-1]).parent) if paths else str(Path.home())

    def pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose images", self._start_dir(), FILE_FILTER)
        self.files.add_paths(paths)

    def pick_zarr(self):
        path = QFileDialog.getExistingDirectory(self, "Choose an OME-Zarr folder", self._start_dir())
        self.files.add_paths([path.rstrip("/")])

    def pick_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Output folder", self.out_dir.text() or self._start_dir())
        if path:
            self.out_dir.setText(path)

    # ---- info ----------------------------------------------------------------

    def show_info(self, path):
        if not path:
            return
        try:
            fmt, _ = detect_format(path)
        except ValueError as e:
            self.info_label.setText(str(e))
            return
        self.info_label.setText(f"{Path(path).name}  [{fmt}]\nreading…")
        if self.info_thread and self.info_thread.isRunning():
            return  # previous lookup still running; it will be replaced when it finishes
        self.info_worker = Worker(info_path=path, options={"level": self.level.value()})
        self.info_thread = self._spawn(self.info_worker)
        self.info_worker.info.connect(self._on_info)
        self.info_thread.start()

    def _on_info(self, path, text):
        current = self.files.currentItem()
        if current and current.text() == path:
            fmt, _ = detect_format(path)
            self.info_label.setText(f"{Path(path).name}  [{fmt}]\n{text}")
        elif current:
            self.show_info(current.text())

    # ---- convert -------------------------------------------------------------

    def _spawn(self, worker):
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        return thread

    def start(self):
        jobs = self.files.paths()
        if not jobs:
            self.log_view.appendPlainText("Add at least one input image first.")
            return
        if not self.same_dir.isChecked() and not self.out_dir.text():
            self.log_view.appendPlainText("Choose an output folder, or tick 'Same folder as each input'.")
            return
        options = dict(
            fmt=self.fmt_group.checkedButton().property("fmt"),
            out_dir=None if self.same_dir.isChecked() else self.out_dir.text(),
            level=self.level.value(),
            zarr_format=self.zarr_format.currentData(),
            h5_compression=self.compression.value(),
            ilastik=self.ilastik.isChecked(),
            overwrite=self.overwrite.isChecked(),
        )
        self.run_btn.setEnabled(False)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.log_view.appendPlainText(f"Converting {len(jobs)} image(s) to {FORMATS[options['fmt']][0]}")

        self.worker = Worker(jobs, options)
        self.thread = self._spawn(self.worker)
        self.worker.log.connect(self.log_view.appendPlainText)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self._done)
        self.thread.start()

    def _done(self, ok, total):
        self.log_view.appendPlainText(f"\nDone: {ok}/{total} converted.")
        self.run_btn.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.files.add_paths(a.rstrip("/") for a in sys.argv[1:])
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
