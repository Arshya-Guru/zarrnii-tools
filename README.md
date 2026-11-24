# zarrnii-tools

Two point-and-click tools for light-sheet image patches, built on
[zarrnii](https://github.com/khanlab/zarrnii), plus a ready-made Python environment
for image processing. Works on **Windows** and **macOS**.

| Command | What it does |
|---|---|
| `pixi run app` | **Converter**: turn images into HDF5 (`.h5`), OME-Zarr (`.ome.zarr`) or NIfTI (`.nii.gz`), in any direction |
| `pixi run mask` | **Mask builder**: combine LANTERN and VesselFM masks into one 3-class mask, `combined_fullres.nii.gz` |

You don't need to know Python to use these. Follow the steps below in order.

---

## 1. Install pixi (one time only)

[pixi](https://pixi.sh) installs Python and all the libraries these tools need, in a
folder of their own. It won't touch anything else on your computer.

### On Windows

1. Open the Start menu, type **PowerShell** and open **Windows PowerShell**.
2. Paste this line and press Enter:

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm -useb https://pixi.sh/install.ps1 | iex"
   ```

3. **Close PowerShell and open a new one.** pixi only becomes available in new windows.
4. Check it worked:

   ```powershell
   pixi --version
   ```

   You should see something like `pixi 0.81.0`. If you get *"pixi is not recognized"*,
   see [Troubleshooting](#troubleshooting).

### On macOS

1. Open **Terminal**. Press ⌘ + Space, type *Terminal*, press Enter.
2. Paste this line and press Enter:

   ```bash
   curl -fsSL https://pixi.sh/install.sh | sh
   ```

3. **Close Terminal and open a new one.**
4. Check it worked:

   ```bash
   pixi --version
   ```

---

## 2. Download this project

Pick **one** of these.

### Option A: download a ZIP (easiest, no extra software)

1. On this project's GitHub page, click the green **Code** button, then **Download ZIP**.
2. Unzip it. On Windows, right-click the file and choose **Extract All…**. On macOS, double-click it.
3. Put the unzipped `zarrnii-tools` folder somewhere permanent, such as `Documents`.

### Option B: with git (makes updating easier later)

```bash
git clone https://github.com/Arshya-Guru/zarrnii-tools.git
```

If you don't have git yet: on Windows, install it with `winget install Git.Git` and then
open a new PowerShell window. On macOS, run `xcode-select --install`.

---

## 3. Open a terminal in the project folder

You need to be *inside* the project folder for the `pixi run …` commands to work.

- **Windows:** in File Explorer, open the `zarrnii-tools` folder, click the address bar,
  type `powershell` and press Enter. A PowerShell window opens already in that folder.
- **macOS:** in Terminal, type `cd ` (with a space after it), drag the `zarrnii-tools`
  folder from Finder into the Terminal window, and press Enter.

To check you're in the right place, run `pixi task list`. It should list `app` and `mask`.

---

## 4. Install the environment (one time only)

```bash
pixi install
```

The first time, this downloads Python, zarrnii, napari, ilastik-compatible HDF5 support
and so on. It takes **5–15 minutes** and needs about **4 GB** of free disk space.
Everything goes into a hidden `.pixi` folder inside the project. Delete that folder to
uninstall.

You can skip this step: the first `pixi run …` will do it for you automatically.

---

## 5. Use the tools

Every time you want to use them, open a terminal in the project folder (step 3) and run
one of these commands.

### Converter: `pixi run app`

```bash
pixi run app
```

1. **Add your images.** Click **Add files…** or drag files onto the window. For an OME-Zarr,
   which is a folder, use **Add .zarr folder…**. You can add many files at once. Click one
   to see its shape, data type and voxel size.
2. **Choose the output format:**
   - **HDF5 (.h5)**: the default. Opens in ilastik.
   - **OME-Zarr (.ome.zarr)**: best for big data and keeps all spatial metadata.
   - **NIfTI (.nii.gz)**: use this to convert `.h5` or `.ome.zarr` back.
3. **Pick where to save.** By default each output goes next to its input. Untick
   *Same folder as each input* to choose a folder.
4. Click **Convert**. Progress and any problems appear in the log at the bottom.

Options:

| Option | Meaning |
|---|---|
| ilastik-friendly .h5 | On by default. The `.h5` contains only the full-resolution image, so ilastik opens it without asking which images to stack. Untick it to get the full Imaris layout, with a thumbnail and lower-resolution copies. |
| Zarr format | v3 by default. Choose v2 for older software that can't read v3. |
| Read pyramid level | `0` = full resolution. Higher numbers read a smaller copy from `.h5`/`.zarr` files that contain one. |
| HDF5 gzip level | Compression, from 0 (none, fastest) to 9 (smallest file, slowest). |
| Overwrite existing outputs | Off by default, so nothing is ever replaced by accident. |

**Opening the `.h5` in ilastik:** if ilastik asks which dataset to use, choose
`DataSet/ResolutionLevel 0/TimePoint 0/Channel 0/Data`. The axes are z, y, x.

### Mask builder: `pixi run mask`

```bash
pixi run mask
```

1. Click **Add folder…** and pick either:
   - **one patch folder**, e.g. `mapt_sub-F6A2Te3_02_isocortex`, or
   - **the folder that contains the patches**, e.g. `layan-task1-3class`. Every patch
     folder inside it is added automatically.

   A patch folder is any folder containing both `lantern_pred_fullres.nii.gz` and
   `vesselfm_abeta_fullres.nii.gz`.
2. Click **Build combined masks**.

Each patch folder gets a `combined_fullres.nii.gz` on the same grid as the inputs:

| Label | Meaning | Rule |
|---|---|---|
| 0 | background | in neither mask |
| 1 | plaque | 1 in `lantern_pred_fullres`, **including** voxels VesselFM also marks |
| 2 | vessel-related | marked in `vesselfm_abeta_fullres` but **not** in LANTERN |

The log shows how many voxels got each label. An existing `combined_fullres.nii.gz` is
never replaced unless you tick **Overwrite**, so a mask you've edited by hand is safe.

**Viewing it as a coloured overlay in ilastik:** load the mask, right-click its row
→ **Edit properties** → set **Display Mode** to a colour-table mode. In the layer list
at bottom-left, move the mask above the raw image with the arrow buttons and drag its
opacity bar to about half. Make sure the raw image's opacity (`α`) isn't 0.

---

## Other commands

| Command | What it does |
|---|---|
| `pixi run napari` | Open the napari image viewer |
| `pixi run lab` | Open JupyterLab for notebooks |
| `pixi shell` | Open a terminal with the environment's Python active. Type `exit` to leave. |
| `pixi run python my_script.py` | Run your own script with all the libraries available |
| `pixi run test` | Run the automated tests |

The environment includes zarrnii, numpy, scipy, scikit-image, OpenCV, pandas,
matplotlib, nibabel, tifffile, imageio, zarr, dask, h5py, napari and JupyterLab. Add more
with `pixi add <package>`, or `pixi add --pypi <package>` for packages only on PyPI.

---

## Good to know

All reading and writing goes through zarrnii. The tools also work around a few zarrnii
issues so that conversions don't lose information:

- **Voxel sizes in `.h5` are correct.** zarrnii's own Imaris writer stores them 1000×
  too small.
- **Data types are preserved.** float32 stays float32 and uint8 stays uint8.
- **Label images are stored safely.** int64 labels, which napari often saves, are kept
  in the smallest integer type that fits.

Limits of the `.h5` (Imaris-style) format:

- **No origin offset.** An image that doesn't start at (0, 0, 0) comes back at (0, 0, 0).
  This affects the `*_context512` files. Use OME-Zarr if you need the position kept.
- **No orientation.** Everything reads back as RAS.
- **Integer range.** Integers must fit in uint8, uint16 or int16. Bigger values are
  refused with a message telling you to use OME-Zarr instead; they are never silently
  changed.

---

## Troubleshooting

**"pixi is not recognized" / "command not found: pixi"**
Close the terminal and open a new one. If that doesn't help, restart the computer.
If it still fails, install pixi again (step 1).

**Windows: "running scripts is disabled on this system"**
Use the exact install line from step 1. Its `-ExecutionPolicy ByPass` part is what
avoids this error.

**"could not find pixi.toml" / "no task named app"**
You're not in the project folder. Go back to step 3.

**The window doesn't appear**
Look for it behind other windows or in the taskbar or Dock. The first launch can take
up to a minute.

**"No space left on device" while converting**
Free some disk space. Converted copies of large volumes can be hundreds of MB each.

**Updating to a newer version**
If you used git, run `git pull` in the project folder. If you downloaded the ZIP,
download it again and replace the old folder. Then run `pixi install`.

---

## For developers

```
converter/core.py   conversion logic (zarrnii I/O + the fixes above)
converter/gui.py    the converter window  (pixi run app)
converter/mask.py   the mask builder      (pixi run mask)
tests/              pytest suite on synthetic data, no GUI display needed
```

Every push runs the tests on Windows and macOS with GitHub Actions
(`.github/workflows/tests.yml`).
