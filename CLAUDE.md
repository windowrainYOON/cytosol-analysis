# CLAUDE.md

Notes for Claude Code (and other contributors) working on this repository:
what the program is, where things live, the rules the owner set for changes,
and the history of the work so far.

## What this is

**Cytosol Viewer** is a PySide6 desktop app (macOS and Windows) for sets of
microscopy images: Tomocube TCF, Zeiss CZI, Olympus/Evident OIR and TIFF. It
shows channels with per-channel LUTs, finds cell / nucleus / cytosol ROIs and
particles (spots, condensates), measures them the way ImageJ/Fiji does
(Measure, Analyze Particles, Coloc 2, RGB Profiler), and exports TIFF / MP4,
ImageJ ROI files, CSV tables and paper figures. The UI text is Korean; the
owner writes in Korean, so reply in Korean.

- `cytosol_viewer.py`: app entry point (`--selftest OUT_DIR` runs the smoke
  test in a built app).
- `README.md`: technical description of every feature, plus the
  **Methods statement** (see rules below).
- `docs/ko/`, `docs/en/`: user manuals, one file per feature (01–13), same
  structure in both languages.

## Window structure (v0.26.0)

- **Panes** (`MainWindow.main_split`): left and right keep their width
  (stretch 0, defaults `LEFT_W` / `RIGHT_W`, widths remembered in
  `QSettings` `layout/*_width`), only the centre grows with the window.
  Pane contents follow the pane width: `flow.reflow` turns rows of 3+
  buttons / check boxes of every right tab into `FlowLayout`s and lets form
  rows wrap; use `FlowLayout` (or word-wrapping labels, `wrapped_check` for a
  long check box) in new panels instead of wide fixed rows.
- **Left**: image list with group folders (`image_tree.py`, `groups.py`;
  long names wrap, `WrapDelegate`), buttons 파일 추가… / 폴더 불러오기… / groups.
- **Centre**: `Canvas` (QGraphicsView in `app.py`) with the Z slider (left),
  T slider (below), toolbar (영역 확대, 화면 맞춤).
  - Zoom: `Cmd`/`Ctrl` + left-drag up/down (`ZOOM_DRAG_RATE` × sensitivity),
    `]` in / `[` out (`ZOOM_KEY_STEP`), `Shift`+drag rectangle zoom.
  - Mouse wheel (no modifier): moves T on time series (`MainWindow._wheel_t`),
    otherwise scrolls. `Ctrl`+wheel does nothing.
  - Right-drag: T (left/right) and Z (up/down). Middle-drag: pan.
- **Right tabs**: `LUT` (channel LUTs on top, `MarkerPanel` fixed below in a
  vertical splitter) and `이미지 정보` are always present. The other tabs
  live in `MainWindow.tab_pages` (crop_tab, roi_tab, particle_tab,
  intensity_tab, coloc_tab, profile_tab, frap_tab, stack_tab) and are shown / hidden
  by the "… 탭 열기" check action in each feature's menu (`tool_actions`,
  `show_tab`, `hide_tab`, `tab_open`, `tab_current`). Panels ask
  `win.tab_current('<name>')` to know whether they are the visible tab
  (don't compare `right_tabs.currentIndex()` to fixed numbers).
- **Menus** (`MainWindow._build_menus`): 파일, then Tool with the feature menus:
  - **파일**: 새 프로젝트, 불러오기 (자동 인식) / (폴더), 최근 프로젝트,
    프로젝트에서 설정(파이프라인)만 불러오기, 프로젝트 저장 / 다른 이름으로,
    일괄 분석 실행 / 결과 보기 / 결과 저장 / 설정 저장·불러오기, 모든 분석 결과
    통합 저장, the shared options `opt_per_image` and `opt_with_roi`, 작업 기록
    보기 / 저장, 설정, 종료. Opening a project from 불러오기 / 최근 프로젝트 goes
    through `open_project_dialog` (전체 or 설정만 → `open_project(path,
    settings_only=True)`, which only runs `_apply_project_settings`).
  - **일괄 분석** (`batch.py`, v0.38, owner request 2026-10-28): `BatchDialog`
    (groups + analysis check boxes from `batch.STEPS`), `MainWindow.run_batch`
    → `batch.run` (uses each tab's current settings and the panels' own
    methods: `RoiPanel.detect_jobs`, particle settings + `particles_for`,
    `MeasureBox.measure_items`, `ColocPanel._run`, `FrapPanel.groups(items=)`),
    `BatchResults` window (double-click opens the image in the step's tab,
    다시 측정 = `run(detect=False)`), `batch.save_results` (only those steps and
    images), settings JSON `format: cytosol-viewer-batch`. State in
    `MainWindow.batch` (`BatchState`), saved in projects as `batch`. A new
    analysis feature should get a `STEPS` entry and a branch in `batch.run` /
    `save_results`.
  - **Tool** (`MainWindow.tool_menu`, owner request 2026-10-30, v0.41): one
    submenu per feature, e.g. Tool › FRAP 측정 › FRAP ROI 불러오기…:
    **LUT** (이미지 내보내기, LUT 프리셋 저장/불러오기),
    **마커** (설정 저장/불러오기, JSON with `format: cytosol-viewer-markers`),
    **Crop**, **세포질 ROI**, **입자 ROI**, **강도 측정**, **Coloc 2**,
    **라인 프로파일**, **FRAP 측정**, **스택**, **이미지 정보**, **Figure**. Each holds its tab
    action, its saves and its loads (`import_kind_dialog(kind)`, kinds in
    `IMPORT_KINDS`; it only pre-filters the file chooser, `import_paths`
    still detects by content).
  - Rule from the owner (2026-10-26, v0.25): every feature gets its own
    menu (since v0.41 a submenu of **Tool**, next to 파일) with its own save
    and load items; a new feature's menu goes under Tool (`tools.addMenu`); only bulk saving
    (통합 저장), projects and auto-detecting load stay in 파일. Panels keep no
    save/load buttons; they expose methods (`save_current`, `save_all`,
    `save_csv`, ...) that the menus call. Option widgets that belong to a
    save (image export options `exp_box`, stack `save_box`) are shown in a
    dialog (`_options_dialog`). The Figure window keeps its own save buttons.
- **세포질 ROI tab** (`roi_panel.py`): the **ROI 검출** box has sub-tabs
  **자동** (`segment_cells`) and **수동 (threshold)** (`threshold_cells`);
  `manual_mode()` says which one detection uses. Shared below them: cell /
  nucleus size ranges (min–max with log sliders; `size_auto` (cells) and
  `nuc_size_auto` (nuclei), both on by default, estimate them per image:
  `_image_sizes`, cached in `_size_cache`, `_auto_sizes` keeps only the
  automatic ones, `_estimate_async` fills the fields when an image is
  picked; with both ranges manual `detect_all` asks whether all images get
  the same range), frame handling, and `live` (실시간 미리보기: debounced
  background detection drawn as dashed ROIs, reused by ROI 검출). Hovering a
  ROI shows its name and area (`Canvas.hover_info`). Smoothing, neck width
  and inner border margin have 자동 checkboxes too (`val_auto`; auto = the
  `RoiParams` default). Editing: Shift+click (`Canvas.cellShiftClicked`)
  builds a multi-selection (`RoiPanel.selection()`), 합치기 (M) joins it
  (`CellRois.merge`, bridges gaps ≤ 3 µm), Option/Alt+drag with 선택 draws a
  cut line (`Canvas.roi_edit_active`, `_lasso_tool`).
  - Rule from the owner (2026-10-27, v0.26): the plain manual threshold mode
    (at or above the threshold = ROI, below = discarded, nothing else) must
    always stay, whatever detection algorithms are added later; automatic
    modes must also accept user-set thresholds into their algorithm.
  - Rule from the owner (2026-10-27): every automatic setting is switched
    with its own **자동** checkbox, and its value field always shows the
    value actually used (filled in even while automatic). Sizes and
    thresholds get sliders under their fields; live previews that cost
    detection time sit behind a checkbox.
- **Status bar**: `LoggingStatusBar` (`worklog.py`); every lasting message
  (`showMessage` without timeout) goes into the `WorkLog` and marks the
  project dirty. Use `statusBar().showMessage(...)` for anything the user
  should find later in the work log.

## Modules (`cytosol/`)

| Module | Role |
|---|---|
| `io.py` | Readers for TCF (HT/FL aligned on one grid, Z+T, lazy planes), CZI, OIR, TIFF |
| `imageid.py` | Stable image ID from file metadata; pairing files by ID on folder load |
| `imageinfo.py`, `info_panel.py` | Acquisition metadata tables (이미지 정보 tab), CZI bleach ROIs |
| `lut.py` | `ImageItem` (one loaded image: LUTs, crops, cells, particles, group, load kwargs), export of TIFF/MP4 |
| `render.py` | Pseudo-color rendering, scale bar, time stamp |
| `movie.py` | MP4 export |
| `prefetch.py` | Background read-ahead of timepoints for the T slider |
| `crops.py` | Crop regions as ImageJ rectangle ROIs (`<stem>_crops.zip`, `cropN`) |
| `cellroi.py`, `roi_panel.py` | Cell / nucleus / cytosol ROI detection, editing, ImageJ ROI I/O (세포질 ROI tab) |
| `intensity.py` | ImageJ Measure values, particle detection (Otsu / Hessian spot seeds + watershed), shape (iso-contours), logic regions |
| `particle_panel.py` | 입자 ROI tab, per-cell and per-particle measurement, summaries |
| `intensity_panel.py`, `radial.py` | 강도 측정 tab (regions from expressions like `cyto - particle`; distance bands from the nucleus with graph) |
| `measure_box.py` | Measurement table shared by the three measuring tabs |
| `coloc.py`, `coloc_panel.py` | Fiji Coloc 2 port, per cell |
| `lineprofile.py`, `profile_panel.py` | Line profile (ImageJ RGB Profiler) |
| `frap.py`, `frap_panel.py` | FRAP 측정 tab: bleach / control / background ROIs (`FrapState` per image in `ImageItem.frap`, auto placement, dragged on the canvas via `Canvas.show_frap` / `frapMoved`), (B−BG)/(C−BG) curves, ImageJ-equal ROI masks, exponential recovery fit, drift correction (ROIs follow each frame's movement, `track_drift`), group means, summary CSV / figures |
| `stack.py`, `stack_panel.py` | Z projections (2D) and 3D rotation views |
| `marker_panel.py` | Scale bar, time stamp, bleach ROI display |
| `figure.py`, `figure_window.py` | Figure window (image table, insets, scale bars, per-cell / per-inset brightness, PNG/TIFF/PDF/SVG) |
| `groups.py`, `image_tree.py` | Image groups and the grouped image list |
| `flow.py` | `FlowLayout` and `reflow` (panel rows that follow the pane width) |
| `project.py` | `.cyproj` project files (see below) |
| `settings.py` | `QSettings` preferences: mouse sensitivities, recent projects; `SettingsDialog` |
| `worklog.py` | `WorkLog`, `LoggingStatusBar`, `LogWindow` |
| `batch.py` | 일괄 분석: steps × groups run on all images, results window, batch-only save, batch settings JSON |
| `selftest.py` | Headless smoke test of the whole app (CI and built apps; `CYTOSOL_SELFTEST_ONLY='step name,…'` runs only some steps) |
| `version.py` | `__version__`, the single version source |
| `app.py` | `MainWindow`, `Canvas`, menus, loading (`import_paths`, `add_files`, `_attach_file`), projects |

## Project files (`.cyproj`)

A zip with `project.json` plus binary entries (`cytosol/project.py`).
`image_entry` stores each image's path relative to the project file and its
absolute path, name, ID, load kwargs, Z/T, LUTs, crops, group, profile line,
ROI roles and particle settings; `item_files` stores cells (`cells.npz`),
fixed particles, bleach ROIs and Coloc results. Panel widgets are saved
generically (`widget_state` / `restore_widgets` over the panel's attributes),
so a new QCheckBox / QSpinBox / QComboBox / QLineEdit on a panel is saved
automatically. Also saved: open tabs, batch LUT rows, the work log, the
current image and the Figure window layout. `open_project` asks for a folder
when images moved (`resolve_image` searches it). Bump `project.VERSION` only
for incompatible changes.

**불러오기** (`import_paths`) detects the kind of each file: project →
`open_project`; folder → `add_files(..., pair=True)`; LUT preset `.json`;
`image_groups.csv`; images; ROI zips/roi files (cells, particles, crops,
line, regions, bleach) attached by image ID or to the current image.

## Testing

```bash
sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libglib2.0-0   # Linux container
pip install -r requirements.txt
QT_QPA_PLATFORM=offscreen python3 -m cytosol.selftest /tmp/selftest-out
```

The self-test builds synthetic images, drives the main window (zoom, wheel,
feature menus and tabs, markers, every analysis, exports, project round trip, 불러오기) and must
print PASS. CI (`.github/workflows/*.yml`, Windows) runs it on the packaged
exe for every push to `main` and `claude/**`. Add a check to `selftest.py`
for each new feature; reset shared panel state afterwards so later checks are
not affected.

## Build and release rules (set by the owner)

- After every change: commit and push without asking. Open a PR and merge it
  yourself once CI is green.
- Bump `cytosol/version.py` for each released change.
- Build names include the version: `scripts/build_name.sh` →
  `CytosolViewer-<version>-<commit>`. Mac DMGs get a machine suffix
  (`make_dmg.sh` adds it from `uname -m`): Mac mini (Apple Silicon)
  `..._apple silicon.dmg`, Intel MacBook `..._intel.dmg`.
- Mac build (owner's Mac mini, via Remote Control, repo in
  `/Users/changwooyoon/Developer/cytosol-analysis`):
  `PYTHON=~/.local/bin/python3.12 ./build_mac.sh && ./make_dmg.sh` → DMG on the
  Desktop; also replace `/Applications/Cytosol Viewer.app`. Intel MacBook:
  `~/Developer/cytosol-analysis`, Homebrew python3.12.
- Auto update (2026-10-27): `scripts/install_auto_update.sh` (launchd
  agent, every 30 min) runs `scripts/mac_auto_update.sh`, which builds new
  `origin/main` commits in `~/.cytosol-autoupdate/src`, runs the selftest and
  replaces `/Applications/Cytosol Viewer.app`, puts the DMG and the newest
  release's Windows zip on the Desktop (older ones it made go to the Trash).
  Once installed on a Mac, merged PRs reach that Mac without a manual build.
- Windows releases: pushes to `main` publish the exe zip as release
  `v<version>` (one per version, newest commit of it).
- Windows exe: built by GitHub Actions (`build_windows.ps1`), artifact
  `CytosolViewer-<ver>-<sha>-Windows`.
- Docs: update both `docs/ko` and `docs/en` whenever the UI changes.
- `README.md` keeps a one-sentence **Methods statement** citing the ImageJ /
  Fiji plugins whose algorithms are used (never this program's name or its
  development); update it whenever a new analysis feature lands.

## History

| PR | Version | Change |
|---|---|---|
| #1–#3 | | Readers (TCF/CZI/OIR), Cytosol Viewer with LUTs, crops, batch export, DMG script; cell/cytosol ROIs; Figure window |
| #4–#5 | | Export folders per image; Windows build in GitHub Actions + selftest |
| #6 | | TCF HT/FL aligned, Z+T time series, marker tab (scale bar, time stamp) |
| #8 | | Image ID from metadata in every export; folder load pairs image / TIFF / ROI |
| #9 | | Manual nucleus / cell threshold in the 세포질 ROI tab |
| #10 | 0.3 | Versioned build names, `version.py` |
| #11 | | Per-image export folders `<stem>_<image ID>` |
| #13 | 0.5 | Vertical Z slider, 스택 tab (2D / 3D projection), lazy TCF planes |
| #15 | 0.6 | Line profile tab, MP4 export |
| #16 | 0.8 | Channel visibility checkboxes, multi-select image removal |
| #17 | | Coloc 2 tab (Fiji Coloc 2 port) |
| #18 | 0.8.1 | Line profile also saves `_line.roi` + `_image.png` |
| #19 | 0.9 | Move crops by dragging, rectangle zoom, 3D drag pan / rotate |
| #20 | 0.9.1 | Figure: per-cell channel combinations |
| #21 | 0.10 | Figure inset `.roi` save/load, copy/paste between cells |
| #22–#24 | 0.11–0.12 | Live T-slider drag, partial TCF FL reads, MIP preview, read-ahead, right-drag T/Z |
| #25 | 0.13 | 강도 측정 tab, particle ROIs, logic regions (verified against ImageJ) |
| #26 | 0.14 | Automatic particles: Hessian spot seeds + watershed |
| #27 | 0.15 | Figure insets of one fixed size, resize all, drag to move |
| #28–#29 | 0.16–0.17 | 입자 ROI tab split out, per-tab measure/save, whole-image particle mode |
| #30 | 0.18 | Per-particle shape measurement (Analyze Particles), partition coefficient, NND |
| #31–#32 | 0.19–0.20 | Image groups (tree, name suggestion, auto groups), per-image / per-group summaries |
| #33–#34 | 0.21–0.22 | Particle shape from sub-pixel iso-intensity contours; pixel / contour intensity ROI |
| #35 | 0.23 | CZI bleach ROIs, 이미지 정보 tab, CZI time / single-channel fixes |
| #36 | | User manuals `docs/ko`, `docs/en` |
| #37 | 0.24 | Project files (`.cyproj`), 파일 / Tool menus, 불러오기 with automatic detection, tabs opened from Tool, Crop tab, work log, settings (mouse sensitivity), `Cmd`+drag / `[` `]` zoom, wheel = time, this file |
| #38 | 0.25 | One menu per feature next to 파일 (tab, saves, loads), markers fixed under the LUT tab, marker settings save/load, Tool menu removed |
| #39 | 0.26 | 세포질 ROI: 자동 / 수동 (threshold) sub-tabs, cell and nucleus size ranges with sliders, split / merge touching cells to the range, size range estimated from all images, 자동 checkboxes showing the values in use, live detection preview, ROI hover label (name, area), detection time in the status bar |
| #40 | | Mac auto update: launchd agent builds, self-tests and installs new `main` commits into /Applications, DMG + exe on the Desktop; Windows release per version |
| #41 | 0.27 | 세포질 ROI size range: 자동 = each image its own range (median ÷ 4 – × 3, nuclei ÷ 20), 수동 range: 모든 이미지 asks whether all images get the same range |
| #42 | 0.28 | 세포질 ROI: 가는 목으로 붙은 세포 자르기 (geodesic rings from the nucleus + darkest-path cut, else concave-point chord; `cellroi.cut_necks`), 자르기 (C) editing tool (`CellRois.cut`) |
| #43 | 0.29 | 강도 측정: 핵 → 세포막 등거리 띠 (`radial.py`, relative / µm distance, n bands, per-band intensity + particles, graph with selectable axes, `<name>_bands.csv`) |
| #44 | 0.29.1 | Neck cut on by default, neck ≤ 6 µm, part beyond ≥ 2 × wider (FV3000 tip-joined cell cut; PRD 24h cell IoU 0.733 → 0.738) |
| #45 | 0.30 | Nucleus split kept only when the shape says two nuclei (`_split_ok`: notches at both ends, convex pieces / non-convex pair, short cut, centres apart); bean nuclei stay whole (FV3000: 19 split blobs → 7) |
| #46 | 0.31 | Wedge-shaped cell ROIs around dim nuclei fixed: nucleus patches < 2 µm apart are joined before splitting (`nucleus_gap_um`), auto size range gets 10 % slack; 자동 checkbox per value (cell / nucleus size separately, smoothing, neck, margin), all on and filled when an image is picked; Shift+click multi-select, 합치기 (M), Option+drag cut |
| #48 | 0.32 | Nucleus outline per seed: own LUT stretch + own Otsu threshold (`_local_nuclei`), dim nuclei kept when compact with a sharp edge; FV3000 dim nuclei found, PRD 24h cell IoU 0.733 |
| #47 | 0.33 | Side panes keep their width (only the preview grows, dragged widths remembered), pane contents reflow to the width (`flow.py`), long image names wrap in the list |
| #51 | 0.35 | 측정할 채널 check boxes in the measurement block of 세포질 ROI, 입자 ROI and 강도 측정 (`MeasureBox.channels_off`, by channel name, saved in projects as `measure_channels_off`) |
| #52 | 0.36 | FRAP 측정 tab and menu: bleach ROI from the file (CZI bleach regions, OIR stimulation regions now read too) or detected, control in the unbleached part of the condensate (else another unbleached condensate), background of the bleach ROI's size; drag ROIs with live update; (B−BG)/(C−BG) normalized to the first / pre-bleach frames; ImageJ Exponential recovery fit (mobile fraction, t½, k, plateau); group mean ± SD/SEM; one-step summary save (CSV + figures); verified against ij 1.54f |
| #53 | 0.37 | FRAP drift correction (on by default): ROIs follow the movement of each frame (`frap.track_drift`, sub-pixel cross-correlation with a key frame, around the ROIs or the whole field; window size with 자동), drawn where measured on the frame shown, per-frame movement in the CSV, `max_drift_px` in the summary |
| #54 | 0.38 | 일괄 분석 (File menu): pick groups and analyses with check boxes, run them on all images of those groups, results window to open / fix / measure again, save only the batch results and settings (`batch_settings.json`, `format: cytosol-viewer-batch`); opening a project asks 전체 or 설정(파이프라인)만 |
| #55 | 0.39 | Figure: brightness (Min/Max) per cell and per inset (`FigureCell.levels`, `Inset.levels`; 자동 = LUT tab, inset 자동 = the cell's), dropdown next to each channel check box picks LUT tab / this cell / another cell's or inset's levels (`FigureCell.level_from`), saved in projects |
| #56 | 0.40 | FRAP: Control 위치 option (주변의 다른 응집체, default: the most stable of the 12 nearest, lowest CV measured along the drift / 같은 응집체 안), full-scale normalization by default (pre-bleach = 1, first post-bleach frame = 0, Recovery %), paper-style graphs (black open / filled markers, error bars, black fit lines, legend above, no grid), formulas in every FRAP CSV and `frap_formulas.txt` |
| #57 | 0.41 | Tool menu next to 파일: every feature menu (LUT … Figure) moved under it unchanged (Tool › FRAP 측정 › 불러오기 …) |
| #58 | 0.42 | FRAP group graph: check boxes pick the groups drawn (`groups_hidden`, saved in projects), 그룹별로 정규화 option |
| this PR | 0.43 | FRAP: 그룹별로 정규화 removed (owner: normalize per image); group means are of each image's own normalized curve (pre-bleach = 1, post-bleach = 0); group check boxes kept |
