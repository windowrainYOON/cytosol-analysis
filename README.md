# cytosol-analysis

Microscopy image-based cytosol ROI determination and analysis.

## Reading raw files

`cytosol.io.read_image(path)` opens Tomocube `.TCF`, Zeiss `.czi`,
Olympus/Evident `.oir` and `.tif`/`.tiff` files and returns an `Image` with
`data` shaped `(C, Z, Y, X)`, channel names, voxel size in micrometers, the raw
metadata and `ranges`: per channel the value range the file can hold (0 to
the detector maximum), read from the metadata.

| Format | Reader | Notes |
|---|---|---|
| TCF (HDF5) | `h5py` | `modality='3D'` (default) or `'2DMIP'` gives refractive index (stored uint16 / 10000); `'3DFL'` / `'2DFLMIP'` gives fluorescence per channel. HT and FL have different XY pixel sizes and Z ranges (`Data/3DFL` `OffsetZ`). |
| CZI | `czifile` | `scene=` selects a scene in multi-scene files. |
| OIR | `oirfile` | |
| TIFF | `tifffile` | ImageJ hyperstacks and OME-TIFF keep T/Z/C, pixel size, channel names and colors (ImageJ LUTs, OME `Color`). A plain multi-page TIFF is a Z stack; an RGB TIFF gives channels R/G/B. |

Value range per format: CZI `ComponentBitCount`, OIR bits per sample,
OME-TIFF `SignificantBits` (else the TIFF `BitsPerSample` / stored integer
type), TCF fluorescence the stored integer type (uint8/uint16), and TCF RI the
`RIMin`–`RIMax` recorded in the file. Float TIFFs without metadata use 0 to
the data maximum.

```
pip install -r requirements.txt
python scripts/inspect_file.py FILE --out format-check/
```

`inspect_file.py` prints key metadata as JSON and writes preview PNGs
(mid-slice, MIP and XZ section for TCF; per-channel MIP and composite for CZI/OIR).

## Colored images with a scale bar

```
python scripts/render_image.py FILE --out figures/
```

Writes one PNG per channel plus a composite, at the original pixel size,
with a scale bar burned in. The bar length is picked automatically from the
pixel size in the file (about 20% of the width, rounded to 1/2/5/10/20/25/50…
µm) and channel colors come from the file itself: ZEN display colors for CZI,
the FluoView LUT for OIR, and the HTX channel colors for TCF (RI is gray).
For TCF both the HT (`3D`) and fluorescence (`3DFL`) volumes are rendered as
max projections by default.

Options: `--scale-um 10`, `--scale-position "upper left"`,
`--color 0=magenta --color DAPI-T3=#0050FF`, `--z mid` or `--z 12`,
`--modality 2DMIP`, `--no-labels`, `--low/--high` contrast percentiles.

From Python:

```python
from cytosol.io import read_image
from cytosol.render import render
render(read_image('cells.czi'), 'figures/', prefix='cells', scale_um=10,
       colors={'DAPI-T3': 'blue'})
```

## Cytosol Viewer (desktop app)

A GUI for working on a whole set of images at once:

- Add TCF / CZI / OIR / TIFF files with **파일 추가…** or by dragging files or folders
  onto the window. A TCF becomes one entry with HT and FL aligned on the HT
  grid (channels `RI`, `CH0…`): FL is resampled by pixel size around the shared
  image center plus a small automatic registration (at most 2 µm), and in Z
  from `3DFL/OffsetZ` (the center of the FL stack measured from the bottom of
  the HT volume). Turn off **TCF: HT와 FL을 정렬해 한 이미지로** to get HT and
  FL as two entries instead (`read_image(path, aligned=True)` from Python).
- **Time series** (TCF, CZI, OIR with a T axis, together with Z): a **T** slider
  under the image; each timepoint is read from the file when selected. Export
  writes every timepoint (RGB TIFFs become T-frame stacks with the time stamp
  on each frame, the raw stack a TZCYX hyperstack) unless
  **타임시리즈는 모든 시점 저장** is off.
- **마커 tab**: size marker (scale bar) and time-series marker (time stamp).
  Each has on/off, text on/off, font size, marker length/thickness, text-marker
  gap, edge margin, position and color; the time stamp also has the unit
  (auto, s, min, h, hh:mm:ss, mm:ss, frame), decimals, prefix, a time offset
  and an optional progress bar. Used by the preview and every TIFF export.
- **Per-channel LUT** with a live preview: show/hide, color, min/max (slider,
  number or histogram), gamma, `Auto` (0.5–99.8 percentile) and `Min/Max`
  (the current image's data min–max). The sliders and histogram span the
  file's value range from its metadata (e.g. 0–4095 for 12-bit, 0–255 for
  8-bit), shown under the histogram; the starting min/max is still the
  automatic percentile range.
- **Z**: MIP or any single slice.
- **Crop** regions per image: press `Crop 추가 (드래그)` and drag on the image;
  repeat for more regions. Each region is listed, numbered on the image, can be
  previewed alone, deleted, or copied to every image with the same pixel size.
- **Batch LUT**: `전체 이미지에 적용` on a channel copies its LUT to the same
  channel of every loaded image (matched by channel name; by index only between
  files of the same type and channel count). LUTs can be saved and loaded as JSON presets.
- **Batch TIFF export** (`모든 이미지` or `현재 이미지만`), with the current LUTs
  applied. Scope: the whole image (`<name>_full_*`) and/or every crop region as
  its own files (`<name>_crop1_*`, `<name>_crop2_*`, …). For each:
  - composite RGB with the LUTs and scale bar (8-bit, µm calibration),
  - optional per-channel RGB,
  - an ImageJ hyperstack of the original values for all Z, carrying the channel
    LUTs, display ranges and µm calibration, ready for measurement in Fiji.
- **이미지별 폴더에 나눠 저장** (on by default, shared with the ROI tab): each image's
  files go into their own subfolder `<chosen folder>/<name>/`.
- **모든 데이터 일괄 저장** (File menu, Ctrl+Shift+E): for every image, one folder
  `<name>/` holding its TIFFs, `<name>_RoiSet.zip` and `<name>_cell_rois.csv`, plus
  a combined `cell_rois.csv` at the top.

### 세포질 ROI tab (cell / cytosol ROIs)

1. **채널 역할**: pick the nucleus channel (or `없음` when there is none) and the
   background-signal channel, i.e. the dim channel that fills the cytoplasm when
   its LUT is pushed very bright.
2. **ROI 검출**: the background channel is saturated at `배경 포화값`
   (`자동` = median of the smoothed channel; tick `검출용 합성 이미지 보기` to see
   exactly what the detector sees and lower the value until each cell is one solid
   blob), merged with the nuclei, and split into cells by a watershed seeded from
   each in-focus nucleus, so every cell gets one nucleus. Touching nuclei are split
   first. Without a nucleus channel, cells are split along the dark cell-cell
   borders instead (as in the mito-tracking project's `cell_roi.py`).
   Cells cut by the image frame are, by default, cut again along a new border
   `안쪽 경계 여백` inside the frame, so no ROI runs along the frame
   (`제외` drops them, `그대로 두기` keeps them as they are). `모든 이미지` runs the
   same settings on every loaded image, matching channels by name.
3. **확인 · 수정**: click a cell to select it (or pick it in the list). With
   `더하기 (A)` / `빼기 (S)` drag a freehand area to add it to or remove it from
   the selected cell; `새 세포 (N)` turns the drawn area into a new cell.
   `Delete` deletes the selected cell, `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo,
   right-button drag pans in any tool. A cell is always one filled piece
   (ImageJ polygon ROIs cannot have holes), so cut from its border.
4. **ImageJ ROI 파일**: `ROI 저장…` writes a RoiSet `.zip` (ROI Manager › Open)
   or, when saved as `.roi`, one `.roi` file per ROI. Per cell: `cellNNN`
   (whole cell polygon), `nucNNN` (nucleus polygon) and `cytoNNN` (cell minus
   nucleus, a composite ROI). `ROI 불러오기…` reads `.zip` / `.roi` files back
   for editing. `모든 이미지 ROI 저장` writes one RoiSet per image plus
   `cell_rois.csv` with cell, nucleus and cytosol areas (with
   `이미지별 폴더에 나눠 저장`, each RoiSet and its own CSV go in `<name>/`).

From Python:

```python
from cytosol.cellroi import segment_cells, RoiParams
rois = segment_cells(bg_plane, nucleus_plane, pixel_um, RoiParams(edge_mode='trim'))
rois.save('cells_RoiSet.zip')
```

### Figure 만들기 (figure table)

`Figure 만들기…` (left panel, or `Figure` menu, `Ctrl+Shift+F`) opens a window
that lays images out as a table with row and column labels:

- **Table**: add, delete and reorder rows and columns; double-click a row or
  column header to edit its label (several lines allowed) and its color
  (right-click for insert/delete). `열 이름을 채널 이름/색으로` names the columns
  after the channels in the current row, in their LUT colors.
- **Cells** show a loaded image with its current LUTs (changes in the main window
  appear when you come back to the figure window): whole image or any crop region,
  the composite of visible channels or any set of channels. `파일…` puts a PNG/TIFF
  file (e.g. an earlier export) in a cell instead. `이 행을 채널별 + Merged로 채우기`
  fills a row with one column per channel plus the merged image.
- **Zoom insets**: drag `확대 영역 그리기` on the cell preview; the area gets a box.
  `표시 방식` chooses where the magnified copy goes: `이미지 안` puts it in the
  chosen corner of the same image at the chosen size; `다른 칸에 따로` shows it in
  its own table cell (`넣을 칸`: any cell, or a new column/row inserted next to the
  image; by default the free cell to the right, else a new column). `이 행 전체에 적용`
  copies the same insets to every same-sized cell of the row (or column); separate
  zoom cells keep the same offset, e.g. a zoom row under the image row.
- **Layout**: black or white background (labels switch to white/black), cell
  borders, cell width and aspect, gap, font and size, scale bars (one length for
  every cell, automatic or fixed, optional inset scale bars and a
  `(Scale bar = … µm)` caption).
- **Export** the whole table as PNG, TIFF (at the chosen DPI, default 300) or as
  PDF / SVG with editable text.

From Python: `cytosol.figure` (`FigureSpec`, `fill_row_by_channels`, `save_figure`).

Run from source: `python -m cytosol.app [files…]`

Build the macOS app: `./build_mac.sh` → `dist/Cytosol Viewer.app`
(set `PYTHON=/path/to/python3.10+` if the system python3 is older).
Package it: `./make_dmg.sh` → `~/Desktop/CytosolViewer.dmg`.

### Windows build

Every push to `main` (and `claude/**` branches) builds the Windows app on
GitHub Actions (`.github/workflows/build-windows.yml`): open the run under the
repository's **Actions → Build Windows app** and download the
`CytosolViewer-Windows` artifact. Unzip it anywhere and run
`Cytosol Viewer.exe`; keep the `_internal` folder next to it. Nothing needs to
be installed. The exe is not code-signed, so Windows SmartScreen asks once
(**추가 정보 → 실행**).

On a Windows PC with Python 3.12:
`powershell -ExecutionPolicy Bypass -File build_windows.ps1` →
`dist\Cytosol Viewer\Cytosol Viewer.exe` and `dist\CytosolViewer-Windows.zip`.
It uses its own `.venv-win` and `cytosol_viewer_win.spec`, so it does not touch
the macOS build files.

`"Cytosol Viewer.exe" --selftest OUT_DIR` (or `python -m cytosol.selftest OUT_DIR`)
runs export, ROI detection and figure export on a synthetic image and writes
`OUT_DIR\selftest.log`; the CI build runs it on the packaged exe.
