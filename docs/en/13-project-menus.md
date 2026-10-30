# Menus, project files and the work log

[← Manual index](README.md) · [한국어](../ko/13-project-menus.md)

The menu bar has three menus, **파일** (File), **Tool** and **View**. **Tool** holds one
submenu per feature: **LUT**, **마커** (Markers), **Crop**, **세포질 ROI**,
**입자 ROI**, **강도 측정**, **Coloc 2**, **라인 프로파일**, **FRAP 측정**, **스택**,
**이미지 정보** and **Figure**. Each feature menu opens that feature's tab and
holds the saves and loads that belong to it (for example
**Tool › FRAP 측정 › FRAP ROI 불러오기…**). Projects, loading with automatic detection and saving
everything at once are in the **파일** menu.

The right panel starts with only the **LUT** tab (with the marker settings
fixed at its bottom) and the **이미지 정보** (Image info) tab. Ticking a feature in the **View** menu (**Crop**, **세포질 ROI**, **입자 ROI**,
**강도 측정**, **Coloc 2**, **라인 프로파일**, **FRAP 측정**, **스택**) or **… 탭 열기**
(Open … tab) in a feature menu adds that tab next to them; unticking it or
pressing the tab's × hides it. **View › 모든 기능 탭 열기 / 닫기** (open / close
all feature tabs) does it for every feature tab at once. Settings and results stay while a tab is
hidden, and the open tabs are saved in the project.

## File menu

| Item | Shortcut | What it does |
|---|---|---|
| **새 프로젝트** (New project) | `Ctrl+N` | Closes every image and starts again (asks first about unsaved changes) |
| **불러오기 (자동 인식)…** (Load, detected automatically) | `Ctrl+O` | See [Loading](#loading) |
| **불러오기 (폴더)…** (Load folder) | `Ctrl+Shift+O` | Loads the images and exports in a folder, paired by image ID |
| **최근 프로젝트** (Recent projects) | | Asks whether to load everything or only the settings |
| **프로젝트에서 설정(파이프라인)만 불러오기…** (Load settings only) | | Keeps the open images; takes only the tab settings and batch choice of a project or batch settings file ([more](15-batch.md#loading-only-the-settings-pipeline-of-a-project)) |
| **프로젝트 저장** (Save project) | `Ctrl+S` | Saves all the work as a `.cyproj` file (asks where the first time) |
| **프로젝트 다른 이름으로 저장…** (Save project as) | `Ctrl+Shift+S` | |
| **모든 분석 결과 통합 저장 (이미지별 폴더)…** (Save all results) | `Ctrl+Shift+E` | One folder per image with its TIFFs, ROIs and measurement CSVs, and `project.cyproj` at the top |
| **일괄 분석 실행…** / **일괄 분석 결과 보기…** (Batch analysis / results) | `Ctrl+B` / `Ctrl+Shift+B` | Tick groups and analyses, run them at once, review and fix per image ([Batch analysis](15-batch.md)) |
| **일괄 분석 결과 저장 (폴더)…** (Save batch results) | | Only the batch's analyses and settings |
| **일괄 분석 설정 저장…** / **불러오기…** (Save / load batch settings) | | Analysis and group choice plus the settings of those tabs (JSON) |
| **이미지별 폴더에 나눠 저장** (check item) | | Every folder save: a subfolder `<name>_<image ID>/` per image |
| **측정·프로파일 저장 시 ROI와 ROI가 그려진 이미지(.png)도 함께** (check item) | | Next to measurement CSVs and line profiles also `<name>_RoiSet.zip`, `<name>_particles.zip`, `<name>_line.roi`, `<name>_image.png` |
| **작업 기록 보기…** (Work log) | `Ctrl+Shift+L` | The [work log](#work-log) window |
| **작업 기록 저장 (CSV)…** (Save work log) | | The whole work log |
| **설정…** (Settings; on macOS in the app menu, `⌘,`) | | Mouse sensitivity (see [Settings](#settings)) |
| **종료** (Quit) | `⌘Q` (macOS) | Asks first about unsaved changes |

## Feature menus (Tool)

All of them are under the **Tool** menu.

| Menu | Items |
|---|---|
| **LUT** | **이미지 내보내기 (TIFF / MP4)…** (Image export, `Ctrl+E`): an options window (current image only / all images, extent, composite / per-channel RGB, raw stack, time-series format), then the folder ([details](02-lut-export.md#image-export-tiff--mp4)). **LUT 프리셋 저장…** / **LUT 프리셋 불러오기…** (Save / load LUT preset, JSON; loading applies it to every image) |
| **마커** | **마커 설정 저장…** / **마커 설정 불러오기…** (Save / load marker settings: scale bar, time stamp, bleach ROI display; JSON) |
| **Crop** | **Crop 탭 열기**, **Crop 영역 ROI 저장** (current image / all images, `<name>_crops.zip`), **Crop 영역 ROI 불러오기…** |
| **세포질 ROI** | **세포질 ROI 탭 열기**, which ROIs to save (cell, nucleus, cytosol), **ROI 저장** (current image / all images), **ROI 불러오기…**, measurement CSVs (current image / measure all and save) |
| **입자 ROI** | **입자 ROI 탭 열기**, **입자 ROI 저장 (현재 이미지)…**, **입자 ROI 불러오기…**, measurement CSVs |
| **강도 측정** | **강도 측정 탭 열기**, measurement CSVs (current / all images) |
| **Coloc 2** | **Coloc 2 탭 열기**, CSV (current image), all images' CSVs (folder), plots, PDF report |
| **라인 프로파일** | **라인 프로파일 탭 열기**, CSV, graph (PNG / PDF / SVG / TIFF), **선 ROI 불러오기…** (load line ROI) |
| **FRAP 측정** | **FRAP 측정 탭 열기**, **요약 저장: 모든 이미지·그룹 CSV + 그래프 (폴더)…** (save summary), CSV, graph, **FRAP ROI 저장 / 불러오기…** ([FRAP 측정 tab](14-frap.md)) |
| **스택** | **스택 탭 열기**, save the current projection / 3D rotation series: an options window (full resolution, all timepoints, fps, rotation range), then the file name |
| **이미지 정보** | CSV, raw metadata (the tab is always open) |
| **Figure** | **Figure 창 열기…** (`Ctrl+Shift+F`). Saving the figure and inset ROIs stays inside the [Figure window](11-figure.md). |

A feature menu's load shows files of that kind first in the file chooser.
The chosen file is still recognised by its content, so a file of another
kind still goes where it belongs.

## Loading

**불러오기 (자동 인식)…** (Load files) works out what each chosen file is (several
can be chosen at once).

| File | What happens |
|---|---|
| `.cyproj` | Opens the project (the current work is closed; asks first about unsaved changes) |
| Images (`.tcf`, `.czi`, `.oir`, `.tif`) | Added to the list. Files already in the list are not opened again; TIFFs exported by this program are only linked to their original when it is open. |
| Cell ROIs (`<name>_RoiSet.zip`, `.roi`) | Loaded onto the image with the same image ID (else file name), or onto the image shown when none matches. If that image already has ROIs, you are asked once whether to replace them. |
| Particle ROIs (`<name>_particles.zip`) | As particle ROIs (with their settings when stored) |
| Crops (`<name>_crops.zip`) | As crop regions |
| Line (`<name>_line.roi`) | As the line-profile line |
| FRAP ROIs (`<name>_frap_rois.zip`) | As the FRAP tab's Bleach / Control / Background ROIs |
| Bleach ROIs (`<name>_bleach_rois.zip`) | As bleach regions |
| LUT preset (`.json`) | Applied to every image |
| Marker settings (`.json`) | Applied to the marker settings |
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
- The batch analysis choice (analyses, groups) and its results table
- The work log

Opening a project asks whether to load everything (images and results) or only
the settings (pipeline); see [Batch analysis](15-batch.md#loading-only-the-settings-pipeline-of-a-project).

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
View it with **파일 › 작업 기록 보기…** and save it with **파일 › 작업 기록 저장
(CSV)…**. It is saved in the project, so reopening a project continues the log.

## Settings

**파일 › 설정…** sets the mouse sensitivities (1.0 = the default speed,
0.1–3.0×). They are remembered on the computer.

| Item | Default | Meaning |
|---|---|---|
| **확대/축소 드래그 (Cmd/Ctrl + 드래그)** (Zoom drag) | 0.6 | Drag up to zoom in, down to zoom out; smaller = slower |
| **T · Z 이동 (오른쪽 버튼 드래그)** (T/Z right-drag) | 1.0 | How fast right-dragging moves through T and Z |
| **휠 시간 이동 (타임시리즈)** (Wheel through time) | 1.0 | Timepoints per wheel notch |
