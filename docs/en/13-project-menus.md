# Menus, project files and the work log

[← Contents](README.md) · [한국어](../ko/13-project-menus.md)

Since v0.24 every save and load is in the **파일** (File) menu and every large
tool is in the **Tool** menu. The right panel starts with only the **LUT** and
**이미지 정보** (Image info) tabs; picking a tool in the **Tool** menu adds its
tab next to them.

## Tool menu

| Item | What it does |
|---|---|
| **Crop**, **세포질 ROI**, **입자 ROI**, **강도 측정**, **Coloc 2**, **라인 프로파일**, **스택**, **마커** | Checking an item opens its tab on the right (next to LUT · 이미지 정보, in menu order); unchecking it or pressing the tab's × hides it again. Hidden tabs keep their settings and results. |
| **Figure…** (`Ctrl+Shift+F`) | The [Figure window](11-figure.md). Saving the figure and its inset ROIs stays inside that window. |
| **작업 기록…** (Work log, `Ctrl+Shift+L`) | The [work log](#work-log) window |
| **설정…** (Settings; on macOS in the application menu, `⌘,`) | Mouse sensitivities, see [Settings](#settings) |

The open tabs are saved in the project and come back when it is opened.

## File menu

| Item | Shortcut | What it does |
|---|---|---|
| **새 프로젝트** (New project) | `Ctrl+N` | Close every image and start over (asks first when there are unsaved changes) |
| **불러오기 (파일)…** (Load files) | `Ctrl+O` | See [Loading](#loading) |
| **불러오기 (폴더)…** (Load folder) | `Ctrl+Shift+O` | Pair the images and exported files in a folder by image ID |
| **최근 프로젝트** (Recent projects) | | Projects recently opened or saved |
| **프로젝트 저장** (Save project) | `Ctrl+S` | Save the whole session as a `.cyproj` file (asks for a place the first time) |
| **프로젝트 다른 이름으로 저장…** (Save project as) | `Ctrl+Shift+S` | |
| **내보내기 ›** (Export) | | Saving each analysis separately (table below) |
| **모든 분석 결과 통합 저장 (이미지별 폴더)…** (Save all results, one folder per image) | `Ctrl+Shift+E` | Every TIFF, ROI and measurement CSV of each image in its own folder, plus `project.cyproj` at the top |
| **종료** (Quit) | `⌘Q` (macOS) | Asks first when there are unsaved changes |

### Export

| Menu | Items |
|---|---|
| **이미지 (TIFF / MP4)…** (Images, `Ctrl+E`) | An options window (current image only / all images, extent, composite / per-channel RGB, raw stack, time-series format), then the folder. See [LUT tab and image export](02-lut-export.md#image-export-tiff--mp4) |
| **Crop 영역 ROI ›** (Crop ROIs) | Current image / all images (folder): `<name>_crops.zip` (ImageJ rectangles) |
| **세포질 ROI ›** (Cell ROIs) | Which ROIs to write (cell, nucleus, cytosol checks), save ROIs (current / all images), measurement CSV (current image / measure all images + save) |
| **입자 ROI ›** (Particle ROIs) | Save particle ROIs, measurement CSV (current / all images) |
| **강도 측정 (논리 영역) ›** (Intensity, logic regions) | Measurement CSV (current / all images) |
| **라인 프로파일 ›** (Line profile) | CSV, plot (PNG / PDF / SVG / TIFF) |
| **Coloc 2 ›** | CSV (current image), CSVs of all images (folder), plot, PDF report |
| **스택 투영 ›** (Stack projection) | Current projection, 3D rotation series: an options window (full resolution, all timepoints, fps, rotation range), then the file name |
| **이미지 정보 ›** (Image info) | CSV, raw metadata |
| **LUT 프리셋…** (LUT preset) | The current image's LUTs as JSON |
| **작업 기록 (CSV)…** (Work log) | The whole work log |
| **이미지별 폴더에 나눠 저장** (One folder per image, check) | Every save into a folder: a `<name>_<image ID>/` subfolder per image |
| **측정·프로파일 저장 시 ROI와 ROI가 그려진 이미지(.png)도 함께** (Also ROIs and a PNG with them, check) | Next to measurement CSVs and line profiles: `<name>_RoiSet.zip`, `<name>_particles.zip`, `<name>_line.roi`, `<name>_image.png` |

## Loading

**불러오기 (파일)…** (Load files) works out what each chosen file is (several
can be chosen at once).

| File | What happens |
|---|---|
| `.cyproj` | Opens the project (the current work is closed; asks first about unsaved changes) |
| Images (`.tcf`, `.czi`, `.oir`, `.tif`) | Added to the list. Files already in the list are not opened again; TIFFs exported by this program are only linked to their original when it is open. |
| Cell ROIs (`<name>_RoiSet.zip`, `.roi`) | Loaded onto the image with the same image ID (else file name), or onto the image shown when none matches. If that image already has ROIs, you are asked once whether to replace them. |
| Particle ROIs (`<name>_particles.zip`) | As particle ROIs (with their settings when stored) |
| Crops (`<name>_crops.zip`) | As crop regions |
| Line (`<name>_line.roi`) | As the line-profile line |
| Bleach ROIs (`<name>_bleach_rois.zip`) | As bleach regions |
| LUT preset (`.json`) | Applied to every image |
| `image_groups.csv` | Restores groups |

**불러오기 (폴더)…** (Load folder) searches the folder and its subfolders and
pairs by the same rules: images already open get their ROIs, crops and lines;
originals that are not open are opened (when the original is missing, an
exported TIFF, raw stack first). The pairing rules are in
[Output files](12-output-files.md#loading-results-back). Files and folders can
also be dropped onto the window.

## Project files (`.cyproj`)

One project file holds the whole session; opening it lets you carry on
editing and analysing.

- The image list, how each image was read (TCF HT/FL alignment) and its image ID
- Per image: LUTs, crop regions, group, the Z and timepoint shown, the line
  profile line, the cell-ROI channel roles and the particle settings
- Cell and nucleus ROIs (pixel-exact, with the saturation / thresholds the
  detection used), particle ROIs loaded from files, loaded bleach ROIs,
  Coloc 2 results
- The settings of every tab (detection parameters, measurement choices, logic
  expressions, markers, export options, …) and which tabs were open
- The all-image results of the measurement tables
- The Figure window's table (image, region and channels per cell, insets, layout)
- The work log

Image files are not copied, only where they are: the path relative to the
project file and the absolute path are both stored, so the project and its
images can be moved or copied to another computer together. If an image still
cannot be found, the missing names are listed and you pick a folder; files
with the same name are looked for in it (and its subfolders), and images that
are still missing are left out. If an image ID differs from the saved one, you
are told that it may be a different file.

A `*` at the end of the window title means there are unsaved changes.

## Work log

Everything that shows in the status bar (detections, ROI edits, measurements,
loading, saving, grouping, …) is recorded with the time, the image and its ID.
View it with **Tool › 작업 기록…** and save it with **파일 › 내보내기 › 작업 기록
(CSV)…**. It is saved in the project, so reopening a project continues the log.

## Settings

**Tool › 설정…** sets the mouse sensitivities (1.0 = the default speed,
0.1–3.0×). They are remembered on the computer.

| Item | Default | Meaning |
|---|---|---|
| **확대/축소 드래그 (Cmd/Ctrl + 드래그)** (Zoom drag) | 0.6 | Drag up to zoom in, down to zoom out; smaller = slower |
| **T · Z 이동 (오른쪽 버튼 드래그)** (T/Z right-drag) | 1.0 | How fast right-dragging moves through T and Z |
| **휠 시간 이동 (타임시리즈)** (Wheel through time) | 1.0 | Timepoints per wheel notch |
