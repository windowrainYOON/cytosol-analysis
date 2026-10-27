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

- **Left**: image list with group folders (`image_tree.py`, `groups.py`),
  buttons 파일 추가… / 폴더 불러오기… / groups.
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
  intensity_tab, coloc_tab, profile_tab, stack_tab) and are shown / hidden
  by the "… 탭 열기" check action in each feature's menu (`tool_actions`,
  `show_tab`, `hide_tab`, `tab_open`, `tab_current`). Panels ask
  `win.tab_current('<name>')` to know whether they are the visible tab
  (don't compare `right_tabs.currentIndex()` to fixed numbers).
- **Menus** (`MainWindow._build_menus`), in this order:
  - **파일**: 새 프로젝트, 불러오기 (자동 인식) / (폴더), 최근 프로젝트,
    프로젝트 저장 / 다른 이름으로, 모든 분석 결과 통합 저장, the shared options
    `opt_per_image` and `opt_with_roi`, 작업 기록 보기 / 저장, 설정, 종료.
  - One menu per feature: **LUT** (이미지 내보내기, LUT 프리셋 저장/불러오기),
    **마커** (설정 저장/불러오기, JSON with `format: cytosol-viewer-markers`),
    **Crop**, **세포질 ROI**, **입자 ROI**, **강도 측정**, **Coloc 2**,
    **라인 프로파일**, **스택**, **이미지 정보**, **Figure**. Each holds its tab
    action, its saves and its loads (`import_kind_dialog(kind)`, kinds in
    `IMPORT_KINDS`; it only pre-filters the file chooser, `import_paths`
    still detects by content).
  - Rule from the owner (2026-10-26, v0.25): every feature gets its own
    menu next to 파일 with its own save and load items; only bulk saving
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
| `stack.py`, `stack_panel.py` | Z projections (2D) and 3D rotation views |
| `marker_panel.py` | Scale bar, time stamp, bleach ROI display |
| `figure.py`, `figure_window.py` | Figure window (image table, insets, scale bars, PNG/TIFF/PDF/SVG) |
| `groups.py`, `image_tree.py` | Image groups and the grouped image list |
| `project.py` | `.cyproj` project files (see below) |
| `settings.py` | `QSettings` preferences: mouse sensitivities, recent projects; `SettingsDialog` |
| `worklog.py` | `WorkLog`, `LoggingStatusBar`, `LogWindow` |
| `selftest.py` | Headless smoke test of the whole app (CI and built apps) |
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
| this PR | 0.31 | Wedge-shaped cell ROIs around dim nuclei fixed: nucleus patches < 2 µm apart are joined before splitting (`nucleus_gap_um`), auto size range gets 10 % slack; 자동 checkbox per value (cell / nucleus size separately, smoothing, neck, margin), all on and filled when an image is picked; Shift+click multi-select, 합치기 (M), Option+drag cut |
