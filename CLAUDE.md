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

## Window structure (v0.75.0)

- **Regions** (owner request 2026-11-04, v0.58, after mockups; replaces the
  v0.52 RegionLayout shade): the sidebar is the window's own, lowest layer
  (`region-base`); canvas and inspector float on it as two large rounded
  boxes (`theme.BOX_RADIUS` 16, hairline edge, `theme.BOX_GAP` 10 from the
  window edge and between them = `PaneSplitter` margins / handle width, no
  shade: `region_shade` 0). Inspector box in the pages' light grey
  `background-secondary` (owner choice 2026-11-10, v0.61; it was the white
  `region-box`), canvas box `region-canvas` (`theme.region_color(role)`, opaque or the
  glass variant). Padding `theme.REGION_MARGIN` 20 in each region, 24
  between the inspector chips and the page. Pages in a QScrollArea must
  not fill their background (`theme.unify` turns it off), or they paint a
  box over the region.
- **Panes** (`MainWindow.main_split`): left and right keep their width
  (stretch 0, defaults `LEFT_W` / `RIGHT_W`, widths remembered in
  `QSettings` `layout/*_width`), only the centre grows with the window.
  Pane contents follow the pane width: `flow.reflow` turns rows of 3+
  buttons / check boxes of every right tab into `FlowLayout`s and lets form
  rows wrap; use `FlowLayout` (or word-wrapping labels, `wrapped_check` for a
  long check box) in new panels instead of wide fixed rows.
- **Left**: image list with group folders (`image_tree.py`, `groups.py`;
  long names wrap, `WrapDelegate`) and each image's crop regions as child
  rows (`image_tree.CROP`, `ImageTree.set_crops`, `cropPicked`,
  `cropRemoveClicked`; v0.58) in the sidebar region (`MainWindow.sidebar`,
  `#hig_sidebar`). Only one button, 자동 그룹 (owner request 2026-11-03);
  the TCF HT + FL alignment option lives in Preferences since v0.57;
  files come in by 파일 › 불러오기 or drag and drop (the empty list paints a
  drop glyph). Remove: trash glyph at the end of the hovered / selected row
  (`ImageTree.removeClicked`) and the context menu (`MainWindow.list_menu`:
  그룹 지정… / 그룹 이름 변경… / 그룹 해제 only for 2+ selected or a folder,
  the destructive remove last).
- **Centre**: `Canvas` (QGraphicsView in `app.py`) with the Z slider (left),
  T slider (below), toolbar icon buttons on one capsule (`crop_btn` Crop,
  `zoom_btn` 영역 확대, `fit_btn` 화면 맞춤; `hig_widgets.IconButton`).
  - Crop (owner request 2026-11-04, v0.58: no Crop tab): `crop_btn` on =
    crops drawn on the canvas, drag outside a region draws one, inside moves
    it (`Canvas.crop_mode`), stays on after drawing; off = crops not drawn.
    The selected crop is `MainWindow._crop_sel` (sidebar row or canvas
    click); since v0.59 there is no Tool › Crop: the context menu of a crop
    row or a crop on the canvas (`MainWindow._crop_menu`, `Canvas.crop_menu_enabled`)
    has 이 ROI 복사 / 붙여넣기 (`copy_crop` / `paste_crop`, ⌘C / ⌘V,
    `_crop_clip`), 수정 (8 handles) and 점 편집 (drag a vertex, click an edge
    = new point, Option+click = delete) via `edit_crop('resize' | 'points')`
    (`Canvas._edit_press/_move/_release`, signals → `_crop_resized`,
    `_crop_points`), Crop 복사, red 삭제… last.
    **Crop view** (owner request 2026-11-24, v0.75; replaces 선택한 Crop만 보기 and the
    3D 선택한 Crop만 preference): a crop row (`ImageTree.cropPicked`, also on a click
    of the current row, `_clicked`) sets `MainWindow._crop_view` and fills the canvas with
    that crop (status line with size / place, scale bar cut to fit by `lut.fit_scale`),
    `crop_region()` feeds 3D (`View3DPane.show_item(region)`) and sections
    (`ImageItem.crop_item`); the image row (`imagePicked`) or another image = whole image.
    **Crop 영역도 따로 분석** (`measure_bar.crops`, off): `MainWindow.analysis_items()`
    (used by every panel instead of `win.items` for 전체 이미지 runs and data tables)
    adds `ImageItem.crop_items()` (sub-images 「이미지 · Crop n」, id suffix `cropN`,
    cached per box) after each image.
    Polygon crops: `ImageItem.crop_polys` (None = plain rectangle,
    `crops.polys_of`), `item.crops[k]` stays the bounding box; exported as
    that box with the outside 0.
  - Zoom: `Cmd`/`Ctrl` + left-drag up/down (`ZOOM_DRAG_RATE` × sensitivity),
    `]` in / `[` out (`ZOOM_KEY_STEP`), `Shift`+drag rectangle zoom.
  - Mouse wheel (no modifier): moves T on time series (`MainWindow._wheel_t`),
    otherwise scrolls. `Ctrl`+wheel does nothing.
  - Right-drag: T (left/right) and Z (up/down). Middle-drag: pan.
- **Right tabs** (`right_tabs` = `hig_widgets.ChipTabs`: the QTabWidget API
  with its tab bar replaced by wrapping capsule chips, × / right-click closes a
  feature tab; pane = `MainWindow.inspector`): `LUT` (one scrolling page:
  채널 표시, the channel LUTs; no inner scroll; 일괄 적용 = `lut_batch` in `lut_footer`, fixed
  at the inspector bottom like the 측정 바 while `lut_tab_page` is current, owner request 2026-11-25), `마커`
  (`marker_tab`) and `이미지 정보` are always present. The other tabs
  live in `MainWindow.tab_pages` (roi_tab, particle_tab,
  intensity_tab, bands_tab, coloc_tab, profile_tab, frap_tab, track_tab, mito_tab, stack_tab) and are shown / hidden
  by the "… 탭 열기" check action in each feature's menu (`tool_actions`,
  `show_tab`, `hide_tab`, `tab_open`, `tab_current`; no Crop tab since v0.58). Panels ask
  `win.tab_current('<name>')` to know whether they are the visible tab
  (don't compare `right_tabs.currentIndex()` to fixed numbers).
- **Menus** (`MainWindow._build_menus`): 파일, Tool with the feature menus,
  View, 그래프 (`graph_menu`, filled on show by `_fill_graph_menu`: 현재 탭의
  그래프 편집 창 ⌘G, one item per graph source with results, 새 그래프) and
  Figure (Figure 창 열기… ⇧⌘F) (v0.59). View (`view_menu`, v0.43): one check item per feature tab
  (`view_actions`, kept in step with `tool_actions` by `_check_tab_actions`)
  plus 모든 기능 탭 열기 / 닫기:
  - **Preferences…** (`settings.PreferencesDialog`, owner request 2026-11-04,
    v0.57; macOS app menu, `⌘,`): loading flags (`settings.FLAGS`,
    `view_settings.flag('align_tcf')`), mouse sensitivities, 탭 설정 초기값
    (`MainWindow.tab_defaults()` → `view_settings.set_defaults('tabs', …)`)
    and 마커 초기값 (an own `MarkerPanel`, `defaults('markers')`), all in
    QSettings; `MainWindow.apply_defaults()` runs at start-up and in
    `new_project`. The self-test uses its own ini store (`use_store`).
  - **파일**: 새 프로젝트, 불러오기 (자동 인식) / (폴더), 최근 프로젝트,
    프로젝트에서 설정(파이프라인)만 불러오기, 프로젝트 저장 / 다른 이름으로,
    **내보내기…** (⌘E), 일괄 분석 실행 / 결과 보기 / 설정 저장·불러오기, 작업 기록
    보기, 설정, 종료. Opening a project from 불러오기 / 최근 프로젝트 goes
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
    **LUT** (LUT 프리셋 저장/불러오기),
    **마커** (설정 저장/불러오기, JSON with `format: cytosol-viewer-markers`),
    **세포질 ROI**, **입자 ROI**, **강도 측정**, **등거리 띠**, **Coloc 2**,
    **라인 프로파일**, **FRAP 측정**, **입자 추적**, **mitoROI**, **스택**. Each holds its tab
    action and its loads (`import_kind_dialog(kind)`, kinds in
    `IMPORT_KINDS`; it only pre-filters the file chooser, `import_paths`
    still detects by content).
  - **그래프 편집 창** (owner request 2026-10-30, v0.46; one window since
    v0.59; step flow since v0.61): every graph is a `GraphDoc` in the sidebar
    of the one `MainWindow.graph_win` (`GraphWindow`: sidebar (right-click:
    new / duplicate / rename / delete) | canvas box with the **새 그래프**
    chips (one per tool + CSV…; disabled + tool tip without results), graph,
    data table | inspector `ChipTabs` **데이터** / **모양** / **통계**).
    `GraphWindow` attributes (`spec`, `key`, `tables()`…) delegate to the
    current doc. `MainWindow.open_graph(key)` opens the tab's own graph (from
    the 그래프 menu); a chip runs `GraphWindow.start_wizard(key)` /
    `start_wizard_csv` → `graph_editors.GraphWizard` (종류 → 축 배치 → 그룹,
    preview) → `add_from_wizard` (a `free<n>` doc that keeps `_source` in
    projects). The 축 배치 is `GraphSpec.mapping` (`graph.Mapping`: table,
    X / Y each 범주 or 값 (`x_cat` / `y_cat`), several `ys`, `color` '' / '@y' /
    column, `err`, `agg`); `graph.build_series` makes the series from it
    (series of other tables stay as overlays; styles kept by `Series.key`),
    groups via `cat_order` / `cat_hidden` (`Series.hide`), category charts with
    Y 범주 draw horizontally (`spec.horizontal`). Shared editors in
    `graph_editors.py`: `KindPicker`, `MappingEditor`, `GroupEditor`,
    `StatsEditor`, `StatsDialog`. Significance (`GraphSpec.stats`,
    `graph.Stats`; `cytosol/stats.py`: Shapiro / Levene check, recommended
    test, pairs, corrections, stars, caption; brackets drawn by
    `graph._draw_stats`, result in `art['stats']`); its look's initial
    values are Preferences › 그래프 · 유의성 표시 초기값
    (`view_settings.defaults('stats')`, `graph_editors.apply_stats_defaults`),
    the test is always recommended per data. Clicking a graph part jumps to
    its 모양 card (`_show_selection`). Saved via the export window (kind
    `graph`). Features not built yet (기준선, 피팅 곡선, 보조 y축) stay hidden.
    A new feature graph gets a `graph_sources` function and an entry in
    `graph_sources()`; every new graph option belongs in `GraphSpec` / `Series`
    (saved and loaded with it, nested dataclasses in `graph._NESTED`).
  - Rule from the owner (2026-10-26, v0.25; changed 2026-11-05, v0.59):
    every feature gets its own menu under **Tool** (`tools.addMenu`) with
    its tab item and its loads. Every save goes through **파일 › 내보내기…**
    (`export_dialog.ExportDialog`: toolbar 대상 / 저장 위치 / prominent
    내보내기, 이미지별 폴더 check box, kinds list with check boxes and on/total
    counts, settings cards; choices in `view_settings.defaults('export')`;
    `exporter.run(win, items, out, opts)` writes the files with the panels'
    own methods). A new feature's outputs get a `KINDS` entry and a branch
    in `exporter.run`. Only LUT presets, marker settings and batch settings
    are still saved from their menus. Panels keep no save buttons. The
    Figure window keeps its own saves (toolbar: 새 Figure, 복제 | 해상도,
    형식, 모든 Figure 저장…, Figure 저장… ⌘S).
- **세포질 ROI tab** (`roi_panel.py`): the **ROI 검출** box has sub-tabs
  **자동** (`segment_cells`) and **수동 (threshold)** (`threshold_cells`),
  two pages of `mode_tabs` (`_ModePages`: QStackedWidget API, as tall as the
  page shown) chosen by the **검출 방식** pop-up (`mode_combo`;
  `_mode_auto` kept as hidden state); `manual_mode()` says which one
  detection uses.
  - **검출 자동화** (owner request 2026-11-04, v0.58; `detect_auto`, also in
    the 입자 ROI tab): on = only the basic sensitivity (배경 포화값 + 합성
    보기; particle k / threshold) and 프레임에 걸친 세포 (default 제외) are
    shown, the details (thresholds, threshold preview, smoothing,
    나누기·합치기 (on), 목 자르기 + 목 폭, size ranges, 경계 여백) are
    behind **세부 설정…** (`set_details_open`, `_details`), editable there:
    an edited value clears its hidden per-value auto box (`sat_auto`,
    `thr[k]['auto']`, `size_auto`, `nuc_size_auto`, `val_auto`; user edit =
    widget has focus, `_edited`) and shows '· 수정됨' + a reset glyph
    (`_auto_field`, `_auto_ui`); the rest stay automatic. Off (clicked) =
    every value manual and shown, from the automatic values; on again (clicked)
    = all automatic. The per-value 자동 switches are gone (hidden state only). Shared below them: cell /
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
  cut line (`Canvas.roi_edit_active`, `_lasso_tool`). The **핵 다시 찾기**
  box under 확인 · 수정 re-draws nuclei inside the existing cell ROIs (never
  changing them), one per cell, with a per-cell threshold (`cn_auto`,
  `cn_spin` / `cn_slider` follow the selected cell, `CellRois.nuc_thr`).
  - Rule from the owner (2026-10-27, v0.26): the plain manual threshold mode
    (at or above the threshold = ROI, below = discarded, nothing else) must
    always stay, whatever detection algorithms are added later; automatic
    modes must also accept user-set thresholds into their algorithm.
  - Rule from the owner (2026-10-27; for the ROI / particle detection
    replaced 2026-11-04 by one **검출 자동화** switch, see above): every
    automatic setting is switched with its own **자동** checkbox, and its value field always shows the
    value actually used (filled in even while automatic). Sizes and
    thresholds get sliders under their fields; live previews that cost
    detection time sit behind a checkbox.
- **등거리 띠 tab** (`bands_tab`, owner request 2026-11-09, v0.60):
  **핵 → 세포막 등거리 띠** (`bands_panel.BandsPanel` = `MainWindow.bands_panel`;
  v0.57–0.59 at the bottom of 세포질 ROI as `roi_panel.bands`, before that in
  강도 측정). Tool › 등거리 띠, its own export kind `bands`, batch step tab
  `bands_tab`; band edges drawn only while the tab is shown. Projects keep it
  as panel `bands` + `intensity_bands`, older projects' band keys under
  `intensity` are read via `bands_panel.LEGACY_KEYS`.
- **파이프라인** (owner request + approval 2026-11-24, design v3.x in
  `/mnt/project-files/pipeline/`, v0.73; `pipeline.py` engine, `pipeline_window.py`
  window + `ReviewBand`, `pipeline_presets.py`, `pipe.py` CLI): 파일 › 파이프라인… (⇧⌘P) /
  파이프라인 보관함… replace 일괄 분석 실행 / 설정 저장·불러오기 (old batch JSON converts via
  `PipelineSpec.from_batch`; 측정 현황 · 일괄 분석 stays). `STAGES` (groups start / detect /
  track / op / measure / human / end, `stage_rank`: a human.review stays after the stage before
  it); stages make named `PipeObject`s (`objects_of(it)`, `it.pipe_objects`, reset only by
  detect / track stages); tab stages run through `batch.run` with their stored settings applied
  by `_Settings` (widget_state / restore_widgets). Result folder `<data parent>/Processed/
  <data>_<pipeline>_<date>_<time>` (pipeline.json, project.cyproj, README.txt, summary.json,
  progress.jsonl, review_log.csv, 1_통합데이터 / 2_그래프 / 3_이미지). Review chips in the image
  list (`image_tree.CHIPS`, `ImageTree.chips`, `pipeline.review_chips`, `nucleus_odd`). A new
  analysis feature gets a `STAGES` entry (and a `batch.STEPS` entry it runs through).
  **Running analyses for the owner headless** (Remote Control, unattended): `python3 -m
  cytosol.pipe inspect <folder>` → `presets` → `new my.cypipe --from <preset>` / `edit --set` →
  `validate --folder` → `run --dry-run` → `run [--background]` → read `summary.json`.
- **Tool groups** (v0.73): Tool › 검출 (세포질 ROI, 입자 ROI, mitoROI) / 추적 (입자 추적,
  세포질 강도 추적) / 측정 (등거리 띠, Coloc 2, FRAP 측정, 미토 형태 (MiNA)). No 강도 측정 tab
  (`MainWindow.HIDDEN_TABS = ('intensity_tab',)`, `export_dialog.HIDDEN_KINDS`; the panel stays
  for old projects and the pipeline), no 스택 / 라인 프로파일 tabs: canvas view icons
  `view_btns` [라인 프로파일 · 자 · 단면 · 3D 투영] (`canvas_views.SectionView` with a MIP check box
  for the XY panel and a scale bar per panel / `View3DPane`, `ruler.RulerItem` = 자, temporary, cleared when
  off; `gl3d` OpenGL volume view rendered offscreen into an FBO and painted as an image (never a
  QOpenGLWidget: on macOS it showed the window's backing store) with CPU fallback, `vol3d.VolumeCache` pre-render of every
  timepoint; Preferences › 3D 스택 보기 / 단면 보기), the profile plot + `profile_strip` in the
  live box. LUT presets / marker settings: 파일 › 불러오기 and export kind `settings`.
- **세포질 강도 추적 tab** (`cyto_track_tab`, `cell_track.py`, `cell_track_panel.py`): cells per
  frame (ParticleTracker RI cells / 세포질 ROI / 입자 추적's cells), overlap linking after optical
  flow, division / edge exclusion, ring background, condition filters; export kind `cyto_track`,
  pipeline stage `track.cytosol`. **미토 형태 (MiNA) tab** (`mina_tab`, `mina_panel.py`): MiNA on
  mitoROI's fragments (mitoROI = detection). **입자 추적 › 6 신호 변화 트랙** (`track_change.py`:
  tracking score, 켜짐 / 켜짐→꺼짐 / 꺼짐, pass-by frames; export `track_change`).
  Exports run in the background with progress and cancel (`ExportDialog`); graph window
  파일 불러오기… reads CSV / Excel (`table_import.py`, `table_import_page.py`).
- **측정 바** (owner request 2026-11-15, v0.68; `measure_bar.MeasureBar` =
  `MainWindow.measure_bar`): 이 이미지만 측정 / 전체 이미지 측정 fixed at the
  bottom of the inspector box, shown only for tabs in `MainWindow.measurers`
  (`Measurer(current, all, status)`; `box_measurer(MeasureBox)`; bound in
  `_bind_measure_bar` on tab change). Panels keep no measure / run buttons of
  their own. Inspector pages scroll as one page: lists / tables inside them use
  `measure_bar.grow_to_content` (no inner scroll), result tables of mitoROI /
  입자 추적 / Coloc 2 became `DataRows` (name, size, 그래프 ›).
- **통합 데이터** (owner request 2026-11-15, design v4, v0.68; `integrate.py`):
  `Integrator.build()` turns the tabs' existing results into per-category rows
  (`CATEGORIES`: 이미지별, 세포별, 세포 × 띠별, 입자별, 미토 조각별, 시점별),
  columns `기능 › 열` after `KEYS`; `integrate.tables(win)` → graph `Table`s
  with column sets per feature, first in `MainWindow.data_entries()` /
  the graph window's data list (other tables folded under 기능별 표 (원본)),
  graph source `integrated`, export kind `integrated` (`write_csv`). A new
  measuring feature adds its rows in `Integrator.build` and its categories in
  `FEEDS`.
- **화면 언어** (owner request 2026-11-15, v0.68; `i18n.py`, design system
  Language): Preferences › 일반 › 언어 / Language (`ui/language` = system / ko
  / en). `i18n.install()` (in `main` and the self-test, before any window)
  wraps the Qt text setters so Korean text goes through `i18n.tr()`
  (`i18n_en.EN` exact texts, `TEMPLATES` f-string templates with `{}`), and
  the Python getters (`text()`, `currentText()`, `itemText()`, `findText()`,
  `title()`, `toolTip()`, item `text()`, `tabText()`) return the Korean source,
  so code keeps comparing Korean keys; `i18n.shown()` gives the text on screen.
  `QPainter.drawText` is translated too; long check boxes get a word-wrapping
  label when shown (`_maybe_wrap`). Keep writing UI text in Korean; add its
  English to `i18n_en.py` (run a coverage check over new strings). Never
  translate user data, CSV keys or file names; the self-test runs in Korean.
- **Status bar**: `LoggingStatusBar` (`worklog.py`); every lasting message
  (`showMessage` without timeout) goes into the `WorkLog` and marks the
  project dirty. Use `statusBar().showMessage(...)` for anything the user
  should find later in the work log.

## UI design system (owner rule, 2026-11-03, v0.48)

All UI follows the owner's **"Apple HIG" design system** (a Design System
artifact on claude.ai; read its `README.md` → `platforms.md` →
`proportions.md` → `hierarchy.md` → `component-map.md` and the component
READMEs before UI work, check new screens against `anti-patterns.md`).
Profile: **Desktop** only (no 44 px touch controls, no bottom tab bar).
The tokens are mapped onto Qt in `cytosol/theme.py` and
`cytosol/hig_style.py`, never written as values in panels. Since v0.49 every
platform (macOS too) runs Fusion + `theme.palette()` + one app-wide style
sheet generated from the tokens (`hig_style.stylesheet(scheme)`, light/dark,
re-applied on colour-scheme change; indicator SVGs written to a temp dir):
since v0.50 the **macOS tahoe style** (`components/MacOSStyle` of the design
system): concentric radii (selected row 10;
inset group 12; field 8; value 6; menu 12), capsule buttons (fill, no
border; `theme.prominent(btn)` = filled accent, at most 2 per tab), fields /
editable combos / steppers filled without border (number fields 80–140 px),
pop-ups = Select (v0.53: no box, value + round `fill` cap, content width),
switches after their label at the row end (v0.53), settings rows (v0.54,
`theme.settings_rows` + `theme.RowLines` from `unify` / `align_forms`: title
leading, control at the row end, hairline between rows, none before a
title-less slider row; stepper text leading; v0.55: one row height
`SETTINGS_ROW_H`, single fields `SETTINGS_FIELD_W` 140, slider rows
`theme.slider_field` = title – slider – plain number field
(`plain_number`, stepper hidden by the sheet), every 자동 / 수동 choice a
switch: per value [value][자동] keeps the value greyed (owner choice
2026-11-04), special-value autos `theme.auto_value` hide the field, mode
choices show only the chosen mode's rows `theme.show_rows`; the ROI
자동 / 수동 pages are a `QStackedWidget` picked by `_mode_auto`), inset groups = settings
cards (`QGroupBox`: `label` 5 %, no border, title in `label` 600 above at
x 12), icon-only toolbars as `hig_widgets.icon_group` capsules (tool tip =
name + shortcut), choice chips for sub-tabs, accent pill + white text for
menu and sidebar selection, three regions without lines (RegionLayout, v0.52).
Selection controls (owner rule 2026-11-03): `QCheckBox` = check box; switch
(`theme.switch`) only for the 자동 / 수동 choice (check boxes whose text
starts with 자동 become switches by themselves); multi-select chips
(`theme.chip`, also every row of 3+ check boxes that `flow.reflow` turns into
a flow) for short values picked together; `QRadioButton` for one of several.
One layout system for every inspector page: `theme.unify(page)` (page
without margins, group padding `GROUP_MARGINS` 12/10/12/12, gaps 12 / 8,
holders without the style's default margins; text and options outside a
group start at x 12 via `#hig_page`), so all titles, rows and labels share
one grid line. Icons: `hig_widgets.ICONS` (24 px stroke glyphs of the design
system's icon set; drawn in a token colour). Surfaces: window
`background-secondary`; regions use `theme.region_color` (RegionLayout). Liquid Glass
(`cytosol/glass.py`, macOS, pyobjc; widgets that cache a region colour need a
`refresh_theme`, re-run by `theme.refresh_regions` once the glass is attached): an `NSVisualEffectView` (sidebar
material, behind window) under the Qt view, panes `#hig_sidebar` /
`#hig_inspector` tinted see-through; opaque when pyobjc is missing or Reduce
Transparency is on. New widgets get the style automatically; don't add
per-widget style sheets.

- Colours: `QPalette` roles (macOS: the system palette untouched; Windows /
  Linux: Fusion + `theme.palette()` built from the tokens, light and dark).
  No `setStyleSheet('color: …')` / hex colours for UI text.
- Text: `theme.hint(label)` (Callout, label-secondary) for help text,
  `theme.secondary(label)`, `theme.text_style(w, role)` for `hig-text-*`
  roles, `theme.section_header(text)` for a group title.
- Status: `theme.StatusLabel(kind=…)` (dot + text on `status-*-tint`, never
  colour alone), `theme.status_icon(kind)` on a button.
- Destructive actions: `theme.destructive(button)` (plain, red), label "동사 +
  대상…", set apart (separator / spacing, last in a row or menu), confirmed
  with `theme.confirm_destructive(...)` (default and Escape = 취소) unless an
  undo exists. Keep the confirmation in the click handler, not in the panel
  method the self-test calls.
- No `QGroupBox` inside a `QGroupBox` (use `section_header`); controls of a
  row the same height; important actions at the top / leading side, nothing
  important on the window's bottom edge; icon-only buttons need a tool tip.
- Excluded (`measurement-plots.md`): matplotlib graphs, `graph.py`,
  `figure.py`, `render.py`, the image canvas: data colours, fonts and white
  backgrounds stay as they are.
- Owner rule (2026-11-04): show an in-app mockup image first for every change
  (patch a live window offscreen, `QT_SCALE_FACTOR=2`, save to
  `/mnt/project-files/mockups/`), develop and build only after approval.
- Switch knob (v0.58): a slightly wide capsule (`hig_style.switch`, 40 × 22,
  knob 24 × 18). Rows that belong together (`theme.group_rows`) get no
  hairline between them (`RowLines` across every settings form of a card).
- Known gaps, kept on purpose: up to 10 right tabs when every feature tab is
  open (HIG: ≤ 6; only 2 open by default), the T slider and status bar
  under the preview, Fusion-drawn controls instead of native AppKit ones
  on macOS (needed for one styled look).

## Component library (`cytosol/ui/`, owner rule 2026-11-25, v0.75)

Every widget class, dialog and painter part lives in `cytosol/ui/`; screens
(panels, windows) only import and arrange them (design system reuse rules
1–9). Same-role parts are one component with variants: `ui.dialogs`
(`Alert`, `information` / `warning` / `critical` / `question`, `choose`,
`confirm_destructive`, `Prompt` + `get_text` / `get_item` / `get_int` /
`get_double`, `Progress` with the QProgressDialog API, `HEADLESS` hook for the
CLI), `ui.window` (`RoundedDialog`, `button_row`, window variants),
`ui.color_well` (`ColorWell` row / header / inline, `RgbColorWell`),
`ui.histogram` (`Histogram` lut / threshold / mini, ▲ handles →
`rangeEdited`), `ui.scrubber` (Z / T capsule, ▶ play), `ui.steps`,
`ui.overlay` (canvas pens per kind and state, label capsule), `ui.empty`,
`ui.fields`, `ui.prism` (graph defaults = the Prism exception), and the
parts moved from screens (`lut_channel`, `figure_parts`, `graph_parts`,
`graph_kinds`, `pipeline_parts`, `page_stack`, `tables`, `import_parts`,
`legend`, `picker_tile`, `overlay_chip`; old modules re-export them).
The self-test lint (`selftest2._lint_ui`) fails on direct `QMessageBox` /
`QInputDialog` / `QProgressDialog` calls and `setStyleSheet` in screen files
(`# hig-allow` marks the figure preview exception). A component change must
keep each button's signals: `scripts/signal_map.py snap` before / after +
`diff` (baseline `/mnt/project-files/components/signal-baseline-v0.74.2.json`).

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
| `particle_detect.py`, `particle_calib.py` | 자동 (유의성) particle detection, 입자 기준 잡기 candidates and the calibration page |
| `intensity_panel.py` | 강도 측정 tab (regions from expressions like `cyto - particle`) |
| `bands_panel.py`, `radial.py` | 핵 → 세포막 등거리 띠 tab (`bands_tab`; distance bands from the nucleus, per-band measurement, graph) |
| `measure_box.py` | 측정 항목 + 데이터 cards shared by the measuring tabs (data names, state per image, re-measure changed images) |
| `live_box.py` | 실시간 값 박스 under the canvas: per-tab numbers + small graph of the current image |
| `columns_doc.py` | 열 설명: unit, meaning and ImageJ source of result columns |
| `coloc.py`, `coloc_panel.py` | Fiji Coloc 2 port, per cell |
| `lineprofile.py`, `profile_panel.py` | Line profile (ImageJ RGB Profiler) |
| `frap.py`, `frap_panel.py` | FRAP 측정 tab: bleach / control / background ROIs (`FrapState` per image in `ImageItem.frap`, auto placement, dragged on the canvas via `Canvas.show_frap` / `frapMoved`), (B−BG)/(C−BG) curves, ImageJ-equal ROI masks, exponential recovery fit, drift correction (ROIs follow each frame's movement, `track_drift`), group means, summary CSV / figures |
| `ptcore/`, `pt_engine.py` | ParticleTracker 1.11 analysis code (`config`, `detection`, `registration`, `cells`, `tracking`, `measurement`, `io_utils`, `plots`, `movies`, `style`, `lut`, commit 9eca503) copied unchanged except a lazy `yaml` import; `pt_engine.run` = its detect → register → cells → track → measure on a TCF (native fluorescence, `load` with Z 'mip' / 'mean'), `to_points` / `outlines` put the result on the RI grid; `TrackState.pt` keeps its tables (+ LAB / CID / FP compressed) for `write_outputs` (ParticleTracker's result folder, byte-equal CSVs, its figures / movies), `write_app_outputs` / `app_tables` give tracks of this app's method the same file names and columns. Used by 입자 추적 (`TrackSettings.engine` 'pt'), the 입자 ROI method `pt` (`intensity.pt_particles`), per-frame RI cells and multi-frame gap closing (`tracking._close_gaps_pt`). Keep it unchanged; re-copy when ParticleTracker changes |
| `track_signal.py` | 입자 추적 › 5 신호 기준 (v0.72): per point channel max / mean (`point_values`: point keys, PT `I_B_max`, or measured in outlines; cached in `TrackState.signal_cache`), `classify` long tracks by the channel's LUT minimum, outputs per image (`write_item`) and all images (`write_all`); track classes `signal` / `nosignal` replace `inside` / `outside` in `TrackPanel.summary_of` when on (`IN_CLASSES` / `OUT_CLASSES`) |
| `tracking.py`, `track_panel.py` | 입자 추적 tab (`track_tab`, v0.66): per-frame detections with the 입자 ROI settings on a per-frame Z projection (`TrackSettings.z_project` 'mip' / 'mean' / '' = viewer Z, `track_panel.frame_planes`, v0.69), LAP linking ported from ParticleTracker (cell flow / pattern / velocity predictions, 2-pass appearance weights with an RI channel `learn_appearance`, PT one-frame gap closing `_close_one_gap`, gap closing), ring-background intensities, ratio, track classes, `TrackState` in `ImageItem.tracks` (pickled in projects), canvas tails, track table, ParticleTracker CSV import (`is_pt_points`, `from_pt`), export kind `track`, batch step `track`, graph source `track` |
| `mito.py`, `mito_panel.py`, `mitoan/` | mitoROI tab (`mito_tab`, v0.67): Mito Analyzer 1.8.0's measurement code copied unchanged into `mitoan/` (MiNA skeleton, mito objects, POI / puncta, green+ / −, correlation stats), `mito.analyze` on the app's cell ROIs → `MitoResult` in `ImageItem.mito` (pickled in projects), canvas layers, tables + column sets (graph source `mito`, 상관 행렬), export kind `mito` (Mito Analyzer file names), batch step `mito`, `_per_cell.csv` import |
| `stack.py`, `stack_panel.py` | Z projections (2D) and 3D rotation views |
| `marker_panel.py` | Scale bar, time stamp, bleach ROI display |
| `figure.py`, `figure_window.py` | Figure window (image table, insets, scale bars, per-cell / per-inset brightness, PNG/TIFF/PDF/SVG; drag and drop: `FigureTable` + `FigureWindow.drop_on` / `move_cell` / `place`, `move_whole` 행/열 전체 옮기기). v0.59: regions sidebar (`fig_list`, `FigureWindow.figures` = [[name, FigureSpec]], `new_figure` / `duplicate_figure` (`copy_spec`) / `show_figure` / `remove_figure`, `export_all`) | canvas box (table + preview) | inspector of fixed width (`INSPECTOR_W`, `flow.reflow(right, min_n=2)`, never clipped); table: one extra ＋ row / column (`add_at_end`), `FigureHeader` (hover red × beside the title, title drag with a blue line = `move_label`); projects keep `figures` (+ `figure` for older versions) |
| `export_dialog.py`, `exporter.py` | 파일 › 내보내기 window (`KINDS`, `ExportDialog.run(ask=)`) and the writer (`exporter.run` → `Result(files, errors, skipped)`) |
| `graph_calc.py` | Correlation / regression maths of the graph window (Mito Analyzer `stats.py` functions), group summary, per-image means |
| `graph_editors.py`, `stats.py` | Step window (새 그래프), 축 배치 / 그룹 / significance editors; significance tests (SciPy), stars, caption |
| `graph.py`, `graph_window.py`, `graph_sources.py` | 그래프 편집 창: `GraphSpec` (every graph setting, JSON `format: cytosol-viewer-graph`) drawn by `graph.draw` from result `Table`s; `GraphWindow` (graph + settings top 70 %, data table bottom 30 %, drag text boxes / legend); `graph_sources` turns each tab's graph into `GraphData` |
| `groups.py`, `image_tree.py` | Image groups and the grouped image list |
| `stacking.py`, `stack_dialog.py` | 이미지 묶기: `StackSpec` (C / Z / T, sources with channel / name / colour) built into one `Image`, RGB triplets found on load, the 이미지 묶기… window |
| `flow.py` | `FlowLayout` and `reflow` (panel rows that follow the pane width) |
| `theme.py` | Apple HIG design system mapped onto Qt: palette from the tokens, text roles, `StatusLabel`, destructive buttons + confirmation alert, section headers |
| `hig_style.py` | App-wide style sheet generated from the tokens (all controls, light/dark), indicator SVGs |
| `glass.py` | macOS Liquid Glass sidebar material (NSVisualEffectView via pyobjc) behind the side panes |
| `project.py` | `.cyproj` project files (see below) |
| `settings.py` | `QSettings` preferences: loading flags, mouse sensitivities, tab / marker initial values, recent projects; `PreferencesDialog` |
| `worklog.py` | `WorkLog`, `LoggingStatusBar`, `LogWindow` |
| `batch.py` | 일괄 분석: steps × groups run on all images, results window, batch-only save, batch settings JSON |
| `selftest.py` | Headless smoke test of the whole app (CI and built apps; `CYTOSOL_SELFTEST_ONLY='step name,…'` runs only some steps) |
| `version.py` | `__version__`, the single version source |
| `measure_bar.py` | 측정 바 at the bottom of the inspector (`MeasureBar`, `Measurer`), `DataRows`, `grow_to_content` |
| `integrate.py` | 통합 데이터: per-category tables from every measurement, column notes, `integrated_*.csv` |
| `i18n.py`, `i18n_en.py` | 화면 언어 (한국어 / English): Qt setter / getter wrapping, translation tables |
| `pipeline.py`, `pipeline_window.py`, `pipeline_presets.py`, `pipe.py` | 파이프라인: stage schema, objects, operations, measurements, runner + result folder; window, review band, library; presets; headless CLI `python3 -m cytosol.pipe` |
| `cell_track.py`, `cell_track_panel.py` | 세포질 강도 추적 tab: cells per frame, linking, exclusion, intensities, filters |
| `track_change.py` | 입자 추적 › 6 신호 변화 트랙: tracking score, on / off kinds, outputs |
| `mina_panel.py` | 미토 형태 (MiNA) tab on mitoROI fragments |
| `canvas_views.py`, `gl3d.py`, `vol3d.py` | Canvas view icons: section view, GPU 3D projection (OpenGL, CPU fallback), volume pre-render cache |
| `table_import.py`, `table_import_page.py` | Graph window 파일 불러오기: CSV / Excel tables, column roles, groups |
| `ruler.py` | 자 on the canvas: `RulerItem` (screen-pixel ticks every 1 µm, length label), `ticks`, `label` |
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
| #60 | 0.43 | View menu next to Tool: open / close each feature tab (check items in step with Tool › … 탭 열기 and the tab ×), open / close all |
| #59 | 0.44 | FRAP: 그룹별로 정규화 removed (owner: normalize per image); group means are of each image's own normalized curve (pre-bleach = 1, post-bleach = 0); group check boxes kept |
| #61 | 0.45 | FRAP: normalization is one check box (정규화: 이미지마다 bleach 전 = 1, 직후 = 0; the 첫 프레임 / bleach 전 평균 choices are gone, so old projects saved with them no longer show 'Normalized recovery' starting above 0); group picker is a scrolling table (check, name, n; `group_table`, 모두 표시 / 숨기기) |
| #62 | 0.46 | 그래프 편집 창 (owner request): every feature graph (FRAP, line profile, distance bands, Coloc 2, measurement tables) opens in its own window, graph + settings top 70 %, data bottom 30 %; 7 chart types, x / y / error columns, filters, split, mean / median aggregation, all styles (series, axes with automatic tick spacing, fonts, legend, text boxes; drag text and legend), exports (image, plotted / series / summary / all tables CSV, settings JSON), settings kept in projects; Tool › … 그래프 편집 창, View › 현재 탭의 그래프 편집 창 (Ctrl+G), button under each graph |
| #63 | 0.47 | 그래프 편집 창 (owner request): plot area, title, axis labels, text boxes and legend are objects selected, moved and resized on the graph (handle; font size for text; `*_auto` / `plot_*` in `GraphSpec`); preview zoom like the image preview (scroll area, Cmd/Ctrl+drag, `[` `]`, Ctrl+wheel, fit); 데이터 menu imports any analysis result (`graph_sources(all_data=True)`, incl. 일괄 분석) or a CSV into a window, saved in projects (`_tables`); View › 그래프 편집 창 › 새 그래프 (empty window, keys `free<n>`); axis min / max / step / unit / value scale (`Axis.unit`, `Axis.scale`, unit conversion list) |
| #64 | 0.48 | Apple HIG design system (owner request, desktop profile): `theme.py` maps the tokens onto Qt roles (native macOS look kept, Fusion + token palette light/dark elsewhere); help text in label-secondary text roles instead of fixed gray; warnings as StatusIndicator (dot + text); destructive buttons red, set apart, "동사 + 대상…" and confirmed with 취소 as default; no box in a box (markers, stack channel display); image list pane: actions on top, list last; graph editor desk uses a system role; measurement plots unchanged |
| #65 | 0.49 | Full HIG visual style (owner request): token-generated app-wide style sheet on every platform (rounded buttons, filled accent main actions, switches, steppers, rounded group cards, segmented tabs, lists, menus, sliders), Liquid Glass sidebar material on macOS (`glass.py`, pyobjc), pane surfaces; measurement plots unchanged |
| #66 | 0.49.1 | Glass only with the Cocoa platform plugin (offscreen self-test on macOS crashed in `glass.attach`) |
| #67 | 0.49.2 | HIG polish after the Mac check: inspector pane padding (titles off the edge), number fields at most 140 px wide, centre background = window background (no black band), LUT tab main action filled, shorter bleach export switch text (marker card fits the pane) |
| #68 | 0.50.0 | Owner request: macOS tahoe style of the updated design system (capsule buttons and chips, borderless filled fields, inset groups, accent-pill selection, floating sidebar panel, no dividers); left pane only 자동 그룹 + list (trash glyph per row, context menu with group actions for multi-selection, drop-target empty state); LUT tab one scroll with 일괄 적용 on top; 마커 its own tab; capsule chip tab switcher; zoom / fit icon buttons; one layout grid for every right tab (`theme.unify`); switches only for 자동 / 수동, check boxes / multi-select chips / radio otherwise |
| #69 | 0.50.1 | Polish after the Mac check: number fields at least as wide as their text (suffix / 제한 없음, up to 118 px), [value][자동] order in every row, preview letterbox = window background (light / dark), no Z / T controls without an image, checkable group titles in label colour, visible edge on colour swatches, more compact tab chips |
| #70 | 0.51.0 | Owner request: Sidebar, Canvas and Inspector clearly separate regions (own surfaces: side panes `background` / dark `background-tertiary`, canvas `background-secondary`; 1 px dividers, `PaneSplitter`), each with its own inner padding (sidebar 16, canvas 16 / 12, inspector 20 / 16 with a chip header and a divider under it); the floating sidebar panel is gone; status bar with a top divider |
| #71 | 0.52.0 | Owner request + updated design system (`components/RegionLayout`): regions separated by tone and the sidebar's shade instead of lines (raised sidebar / inspector, recessed canvas, glass variant on macOS), padding 20 per region; fixes the box an info / LUT page painted over the inspector (scroll-area autofill) and the tab chip tool tip with square corners covering the page |
| dev branch | 0.53.0 | Owner request + design system Toggle / Select: switches after their label at the row end (`theme.switch` RightToLeft, settings-look knob), pop-ups without a box (value + round `fill` cap with chevron.up.chevron.down, as wide as the content: `AdjustToContents` + `Maximum`; editable combos keep the field), inset groups as settings cards (`label` 5 %, no border, heading in `label`); 세포질 ROI editing buttons are icon buttons in capsule groups (`hig_widgets.icon_group`, `hig_no_reflow`; name + shortcut in the tool tip, red trash last) |
| dev branch | 0.54.0 | Owner request: settings rows: titles left, controls at the row end (`theme.settings_rows`: field items aligned right, a trailing stretch of a [value][자동] row moved to the front), steppers' text left, hairlines between rows (`theme.RowLines` overlay per group, row gap 12 = 40 px rows); dialogs' forms the same |
| dev branch | 0.55.0 | Owner request + design system (SettingsPane › 자동 / 수동, slider rows): slider values on one row (title – slider – plain number field), one row height per card, single fields 140 wide, every 자동 / 수동 choice a switch (ROI 검출 방식, particle 검출 방식, stack Z 간격, marker / figure / graph special-value autos), only the chosen mode's inputs shown; hairlines full card width |
| dev branch | 0.56.0 | Owner request: FRAP 측정 tab in settings cards like the others: 측정 ROI card is a form (`_roi_form`: ■ ROI 위치 + 자동 switch, hint under it without a hairline (`theme.hint` sets `hig_hint`), Bleach / Control 지름, Control 자리, threshold slider row), rows that don't apply are hidden (Bleach 지름 for the file's region, 파일 영역 with one region, 추적 방식 / 추적 창 by the drift settings, empty hints); short Control 자리 names |
| dev branch | 0.57.0 | Owner request: Preferences window (`PreferencesDialog`, app menu `⌘,`): TCF HT + FL alignment moved there from the sidebar, mouse sensitivities, 탭 설정 초기값 (save the window's tab settings as initial values / clear) and 마커 초기값 (marker cards incl. 자동 values), stored in QSettings and applied at start-up and 새 프로젝트; 핵 → 세포막 등거리 띠 moved from 강도 측정 to the bottom of the 세포질 ROI tab (`bands_panel.py`, menu items under Tool › 세포질 ROI, batch step tab, old projects' band settings migrated) |
| dev branch | 0.57.0 | Owner request: Figure window drag and drop (cells dragged onto other cells to move, Option/Alt = copy; images dragged from the main image list (`ImageTree` drag, `image_tree.ROWS_MIME`) or files from Finder / Explorer fill cells from the drop target on, rows added as needed; PNG / JPEG / RGB TIFF as pictures, microscopy files opened in the main list first); 행/열 전체 옮기기 check box (off: ▲▼◀▶ and drags move only the selected cell, not every channel of the row) |
| dev branch | 0.58.0 | Owner request, after mockups: canvas and inspector float as rounded boxes on the sidebar layer (no shade); wide-capsule switch knobs; no hairlines between grouped rows; **검출 자동화** in 세포질 ROI / 입자 ROI (one switch, detail values behind 세부 설정…, edited values marked · 수정됨 with reset, per-value 자동 switches gone, 검출 방식 a pop-up, split/merge on and frame cells 제외 by default); Crop tab removed: Crop icon on the canvas toolbar (draw / move / show while on), crops as rows under their image in the sidebar |
| dev branch | 0.58.1 | Owner request: one colour per region with Liquid Glass on: the canvas view takes the glass colour once the glass is attached (`theme.refresh_regions`; it had kept the opaque `region-canvas` picked before), the glass sidebar adds no tint of its own and the title bar draws no surface (`setTitlebarAppearsTransparent_`), so the window top and the sidebar show the same material |
| dev branch | 0.59.0 | Owner request, after mockups: 파일 › 내보내기… (⌘E) one window for every export (target, destination, 이미지별 폴더, kinds list + settings cards; polygon crops cut as their box with the outside 0), export items removed from the feature menus (Tool › Crop / 이미지 정보 / Figure gone); crop context menu: 이 ROI 복사 / 붙여넣기, 수정 (8 handles), 점 편집 (polygon points), 삭제…; menu bar 파일 · Tool · View · 그래프 · Figure; one graph editor window (graphs in a sidebar, a data chip per tool, inspector tabs 종류 / 값 / 모양 / 컴포넌트 with 선택한 요소 / 전체 그래프, unbuilt features hidden); Figure window with a figures sidebar, the saves on a top toolbar, a fixed-width inspector that never clips, ＋ to add rows / columns, hover × to delete, title drag to move |
| dev branch | 0.60.0 | Owner request, after a mockup: 핵 → 세포막 등거리 띠 out of the 세포질 ROI tab into its own **등거리 띠** tab (`bands_tab`, `MainWindow.bands_panel`; Tool › 등거리 띠, View item, own export kind, batch step opens it; old projects load unchanged); docs `18-bands.md` |
| dev branch | 0.61.0 | Owner request, after mockups (v1–v3): graph editor as a step flow: 새 그래프 chips (per tool + CSV) open 종류 → 축 배치 → 그룹 with a preview; X / Y each 범주 or 값 (horizontal category charts), several Y columns, colour split, groups checked / ordered; inspector 데이터 / 모양 / 통계 (old 종류 / 값 / 모양 / 컴포넌트, 선택한 요소, series list, 데이터 menu, sidebar buttons removed); significance marks (data check, recommended test, tails, corrections, pairs, stars / p, brackets, caption) with a 통계 window and Preferences initial values; inspector box in the pages' light grey; merged with the distance-bands tab split (0.60.0) |
| dev branch | 0.62.0 | Owner request (2026-11-14, proposals mito-tracking ch. 이미지 묶기): 이미지 묶기 (`stacking.py`, `stack_dialog.py`): Red/Green/Blue TIFF triplets stacked on load, 이미지 묶기… dialog (C / Z / T, row order by drag, channel per file, name / colour, size check with refuse / crop / pad, same naming pattern), stacked rows `name (3채널)` with greyed source rows (`image_tree.SOURCE`), 묶음 풀기, projects rebuild stacks from the sources; `theme.RoundedDialog` (radius 18, shadow) for new windows; `selftest2.py` holds the new steps |
| dev branch | 0.63.0 | Owner request (2026-11-14, proposal mito-tracking ch. 6): graph window correlation tools for any table: `graph_calc.py` (Mito Analyzer `stats.py` functions: regression, Spearman, corr matrix, Fisher z, Cochran Q, Holm / FDR, why_nan, group summary, sample means), `Table.labels` / `column_sets`, `Mapping.unit` (점 하나 = 행 / 이미지 평균 / 그룹 평균, `graph.view_tables`), chart kinds 상관 행렬 / 상관 비교 (`GraphSpec.calc` = `graph.Calc`; 상관 계산 card in `MappingEditor._calc_rows`; cell hover r · n · p, click = scatter with regression `GraphWindow.open_scatter`), XY 회귀 · 사분면 card (`RegressionEditor`), 편집 › 여러 열 그룹 요약표 |
| dev branch | 0.64.0 | Owner request + decisions (2026-11-14, data-display proposal): measuring tabs end with **측정 항목** + **데이터** cards (`MeasureBox`: no inspector result table, no auto refresh; data names 「기능 · 점 하나」 `data_name` / `data_tables`; 설정 바뀜 per image `stale_items` / `_measured`, `update_stale`, 모든 이미지 측정 / 현재 이미지만), ROI hover values (`RoiPanel.hover_values`), red dot on tab chips (`ChipTabs.set_badge`, `MainWindow.update_tab_badges`), 실시간 값 박스 under the canvas (`live_box.LiveBox`; FRAP / profile / Coloc 2 plots moved there, band graph only in the graph window), graph window 데이터 list (`MainWindow.data_entries`, `GraphWindow.start_data` re-measures changed images; chips hidden) + 열 설명 (`columns_doc.py`) + table header, 측정 현황 · 일괄 분석 window (`batch.BatchResults` rewritten; View menu); docs `20-data.md` |
| dev branch | 0.65.0 | Owner request + decisions (2026-11-13/14, particle-tracking proposal ch. 9–11): 입자 ROI **자동 (유의성)** (`particle_detect.py`: DoG image, σ from the lower half, k from the image area and noise smoothness for 0.5 noise peaks per image, h-maxima split 3 σ, extent k/2; `ParticleSettings.noise / crit_k / crit_area`, `Particles.info`), the Hessian mode kept as **점 모양 강조** (method `spot`), **입자 기준 잡기** (`particle_calib.CalibPage`: 밝기 / 크기 / 적용 steps in the tab, numbered boxes on the canvas, scope all / group / image, `ParticlePanel.criteria` saved as `particle_criterion`, asked on the first user switch-on), HT (RI) cell ROIs without nuclei (`cellroi.is_ri`, `segment_ht_cells`, routed in `RoiPanel._run_planes`), `cellroi.link_cell_frames` (cell IDs between frames, for 입자 추적) |
| dev branch | 0.66.0 | Owner request + decisions (2026-11-13/14, particle-tracking proposal): **입자 추적** tab (`track_panel.py`, `tracking.py`): 입자 ROI detection on every frame, cell ROIs as they are / per frame with IDs linked (`link_cell_frames`) / none, LAP linking (cost: predicted-position distance, intensity, area, cell change, neighbours; predictions from TV-L1 cell flow, neighbourhood template matching, α-β velocity with an adaptive gate 1.55–2.5 µm), gap closing, merged frames flagged, ring-median background per channel, ratio B / A, track classes inside / outside / short, track table + canvas tails, live box, data tables 입자 추적 · 시점 / 트랙 / 세포 × 시점 + graph source, export kind `track` (points / summary CSV, ROI zip, ParticleTracker column names), batch step, ParticleTracker `tracks_points` CSV import (불러오기 and Tool › 입자 추적), tracks in projects; docs `21-tracking.md` |
| dev branch | 0.68.0 | Owner request + decisions (2026-11-15, data-join v4, measure-bar mockups, design system Language): 측정 바 (이 이미지만 측정 / 전체 이미지 측정 fixed under the inspector for measuring tabs), no nested scroll areas in inspector pages (lists grow, result tables → 데이터 rows), **통합 데이터** (`integrate.py`: per image / cell / cell × band / particle / mito fragment / timepoint tables filled by every measurement, objects placed in cells and bands, graph window data list head, correlation matrix over features, export kind `integrated`), **화면 언어** 한국어 / English in Preferences › 일반 (`i18n.py`, `i18n_en.py`, switches open windows at once); docs `23-integrated.md` |
| dev branch | 0.68.1 | Mac self-test fix: `theme.settings_rows` and `i18n.retranslate` skip non-widgets (a stale spacer-item wrapper at a reused address on macOS crashed the main window / stopped the language switch); `_maybe_wrap` uses `removeWidget` instead of `takeAt` |
| dev branch | 0.67.0 | Owner request + decisions (2026-11-13/14, mitoROI proposal ch. 1–5, 9): **mitoROI** tab (`mito_panel.py`, `mito.py`, `mitoan/` = Mito Analyzer's `mina`, `mito_objects`, `green`, `green_cells`, `stats` unchanged; same numbers for the same ROIs): cards 채널 · 세포 (edge cells / weak-border neighbours), 미토 분할 (조각 분할 / MiNA 기본, threshold [value][자동] + slider, minimum object), 관심 단백질 (background, green+ 기준, puncta sensitivity / threshold), 표시 (layer chips on the canvas), 결과 (cells / objects / puncta table, 상관 히트맵 › / 그룹 비교 › into the graph window, Mito Analyzer results loaded); tables with labels and column sets, export kind `mito`, batch step, import of `_per_cell.csv`, live box, projects; docs `22-mito.md` |
| dev branch | 0.69.0 | Owner request (2026-11-18): 입자 추적 **Z 투영 후 추적** (1 검출 card, Z stacks only, on by default: 최대 투영 (MIP) / 평균 투영 every frame, independent of the viewer's Z slider; off = viewer Z; `TrackSettings.z_project`, `frame_planes`); ParticleTracker defaults checked and carried over: 2-pass appearance weights (area, detection mean, RI mean / max, eccentricity; `learn_appearance`, RI per detection `ri_mean` / `ri_max`), PT one-frame gap closing (`_close_one_gap`), background ring in µm (`ring_in_um` 0.34 / `ring_out_um` 0.9 = 3 / 8 FL px), largest gate 2.48 µm (16 HT px), inside = more than 50 % (was ≥), per-frame cells keep edge cells and HT cells share one threshold (median of every 4th frame, `_cell_params`). Benchmark vs ParticleTracker 1.11 on BafA1 P02 (19 frames, 1058² HT): 58 s vs 142 s, 94 % of PT links kept, 80 % of PT detections matched (detection method differs) |
| dev branch | 0.70.0 | Owner request (2026-11-18, after the v0.69 comparison: "셋 다, ParticleTracker와 가능한 동일 방식"): ParticleTracker code in `ptcore/` (unchanged) and `pt_engine.py`; 입자 추적 **방식 › ParticleTracker와 같게 (형광 원본 해상도)** for TCF with RI + FL (default on; `uses_pt`, `pt_channels`, `_run_pt`; points / tracks / ratios equal ParticleTracker's on BafA1 P02, 136 s vs 142 s); 입자 ROI **ParticleTracker 방식** (`method` 'pt', `pt_k` 10, `pt_mode` hidden state, combo index 3); per-frame RI cells with PT `cell_body_images` / `segment_cells` / `cell_flow`; gap closing default 2 with PT `close_gaps`; `summary` keeps PT's class (`pt_group`, `excluded_mitotic` shown with the short chip); selftest `tracking_pt_step` (synthetic TCF `_tracking_tcf`) |
| dev branch | 0.71.0 | Owner request (2026-11-18): output data matched to ParticleTracker: export 입자 추적 › **ParticleTracker 결과 폴더** (`track_ptdir` on, `track_ptfig` on, `track_ptmovie` off; `<stem>_ParticleTracker/`): with the ParticleTracker method every CSV, `particle_labels.tif`, `config_used.yaml`, appearance JSON byte-equal to ParticleTracker's on BafA1 P02 (dataset.json differs only by name / out_dir), its 9 PNGs and 7 MP4s by its own code (`ptcore/plots`, `movies`); this app's method writes the same names and columns (empty where it has no value). Docs 17 / 21 |
| dev branch | 0.72.0 | Owner request (2026-11-19, after the 261118 pHrodo / Cy5-PRD batch; mockup v2 approved): 입자 추적 **5 신호 기준 (긴 트랙)** card: split long tracks by a channel's signal (ROI max / mean ≥ that channel's LUT Min in ≥ n frames) instead of inside / outside; histogram + Min / Max sliders that are the LUT tab's values (both ways, `lut_changed`), Auto / Min/Max / 전체 이미지에 적용, canvas rings preview, chips / summary / tables follow; export 입자 추적 › 신호 기준 (`track_signal`, `track_signal_all`); `from_pt` keeps `I_B_max` as `I_<measure>_max`; `scripts/batch_folder.py` (+ `run_batch_bg.sh`, `track_green*.py`, `track_integrate.py`) for headless batch runs. Docs 21 |
| dev branch | 0.72.1 | Crash fix (owner report 2026-11-20: the app quit while making a graph from 그래프 편집 창 › 데이터 › CSV 불러오기…; macOS report: segmentation fault in the backing-store flush under the 새 그래프 window opened from the data list's click): the graph window's tool chips no longer get a `QGraphicsOpacityEffect` (replacing it on every `refresh_chips` segfaulted, also in the self-test on macOS; disabled chips use the style sheet's `:disabled` look), the data list / chips open the file chooser and the 새 그래프 window after the click handler returns (`QTimer.singleShot(0)`; finishing the wizard rebuilds that list and deleted the clicked item under `QTreeView::mouseReleaseEvent`) |
| dev branch | 0.73.0 | Owner approval (2026-11-24 10:54, "지금까지 수정 사항 전부 반영해서 개발 시작해", pipeline design v3.x + mockups pipe-1…22): **파이프라인** (stages 시작 / 검출 / 추적 / 연산 / 측정 / 사람 / 끝, named objects, operations with conditions, object × channel measurement, review stops with a band + list chips, result folder under `Processed/`, presets, library, `cytosol-pipe` CLI) replacing 일괄 분석 and the 강도 측정 tab; Tool › 검출 / 추적 / 측정; canvas icons 라인 프로파일 · 단면 · 3D 투영 (GPU, pre-rendered time series, 3-axis rotation) replacing the 스택 / 라인 프로파일 tabs; mitoROI detection + 미토 형태 (MiNA) tab; 세포질 강도 추적 tab; 입자 추적 › 6 신호 변화 트랙; background export with cancel; graph CSV / Excel import; docs 24 / 25 |
| dev branch | 0.74.0 | Owner request (2026-11-24, "반영해서 바로 개발해줘"): 3D view fixed (macOS drew a mirrored copy of the window: the GL view now renders into an offscreen FBO and paints the image, fast lower-resolution frames while dragging); 단면 보기 MIP check box (XY = Z max, sections unchanged) and a scale bar per panel; 자 canvas icon (1 µm ticks, `N µm` label, gone when off); line profile legend beside the plot in the live box (`PlotLegend`, number tiles hidden, plot size unchanged); 파일 › 새 파이프라인 (empty; the window also starts empty), library cards as top-to-bottom chip flows (`stage_flow_widget`); View menu grouped 검출 / 추적 / 측정 (`MainWindow.TAB_GROUPS`, `view_groups`) |
| dev branch | 0.74.1 | Owner request (2026-11-24, "같은 파일로 입자추적, 세포 추적 파이프라인 돌려보고 결과 비교 … 기존이랑 같은 결과"; 261118 T001P vs the 2026-11-19 batch): pipeline `end.export` with no kind picked writes the export defaults of the tab stages it ran (`pipeline.default_export_opts`, `STAGE_EXPORT`) with those stages' settings applied (`_Settings` per stage); `track.particles` setting `signal_thr` sets the 5 신호 기준 channel's LUT Min (preset 261118 TCF: 5 + 6 on, Min 5); 세포질 강도 추적 '입자 추적 결과의 세포' keeps ParticleTracker's cell IDs and measures on its fluorescence grid (`cell_track.pt_native`, ring < 50 px dropped, threshold from all pixels) like `scripts/cell_local_bg.py` / `cell_green_thr.py`; preset 세포질 강도 추적 + 변화 필터 runs PT tracking first; exporter `track_all` skips the 신호 변화 tables (KeyError). P01: tracks / points / PT folder / green split equal, cells 6 = 6 with values equal to 5 decimals |
| dev branch | 0.74.2 | Design-system check before the build (owner rule 2026-11-24): canvas view icons also as View commands with shortcuts (`view_mode_actions`: 라인 프로파일 ⌃⌥L, 자 ⌃⌥R, 단면 보기 ⌃⌥S, 3D 투영 보기 ⌃⌥3), 단면 MIP check box moved to the top row (no controls on the bottom edge), library: review chips info (not warning), 새 파이프라인 prominent at the trailing end after 파일에서 불러오기… |
| dev branch | 0.75.0 | Owner request (2026-11-25 08:58, "개발 시작해 … 각 버튼이나 컴포넌트의 신호 전달이 이전과 동일하면 돼"; component sheet + crop-view mockups): design system foundations applied (accent #0066cc / #2997ff, label / secondary / tertiary, grouped background #f5f5f7, separators, row padding 16, inspector ≤ 360), 9 new components, the `cytosol/ui` library (all dialogs, colour wells, histograms with ▲ handles, Z / T scrubber with ▶, steps, overlay pens, empty state, Prism graph defaults); every QMessageBox / QInputDialog / QProgressDialog replaced; signal map before / after: no lost connection except the removed 선택한 Crop만 controls; crop view (crop row fills the canvas, 3D / sections of the crop, fitted scale bar) and Crop 영역도 따로 분석; LUT 일괄 적용 box fixed at the inspector bottom; self-test step `components + crop view` + reuse lint |
| dev branch | 0.73.1 | Pipeline fix: the result folder's `summary.json` / `README.txt` are written again after the last stage, so `status` reads `done` (it stayed `running` because the export stage wrote them first) |
| #50 (main) | 0.53.0 (main) | 핵 다시 찾기: nuclei re-detected inside the (edited) cell ROIs, cells untouched, one nucleus per cell, each cell its own threshold (자동 = own LUT stretch + Otsu over the cell and a 2 µm ring, or a manual value per cell, live), noise in nucleus-free cells dropped (`cellroi.cell_nucleus`, `CellRois.redetect_nucleus`, `nuc_thr` saved in projects); PRD 24h ref-cell nucleus IoU 0.969 |
