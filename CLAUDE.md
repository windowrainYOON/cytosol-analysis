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

## Window structure (v0.63.0)

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
    `_crop_points`), 선택한 Crop만 보기, Crop 복사, red 삭제… last.
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
  일괄 적용 on top, 채널 표시, the channel LUTs; no inner scroll), `마커`
  (`marker_tab`) and `이미지 정보` are always present. The other tabs
  live in `MainWindow.tab_pages` (roi_tab, particle_tab,
  intensity_tab, bands_tab, coloc_tab, profile_tab, frap_tab, stack_tab) and are shown / hidden
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
    **라인 프로파일**, **FRAP 측정**, **스택**. Each holds its tab
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
  cut line (`Canvas.roi_edit_active`, `_lasso_tool`).
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
| `intensity_panel.py` | 강도 측정 tab (regions from expressions like `cyto - particle`) |
| `bands_panel.py`, `radial.py` | 핵 → 세포막 등거리 띠 tab (`bands_tab`; distance bands from the nucleus, per-band measurement, graph) |
| `measure_box.py` | Measurement table shared by the three measuring tabs |
| `coloc.py`, `coloc_panel.py` | Fiji Coloc 2 port, per cell |
| `lineprofile.py`, `profile_panel.py` | Line profile (ImageJ RGB Profiler) |
| `frap.py`, `frap_panel.py` | FRAP 측정 tab: bleach / control / background ROIs (`FrapState` per image in `ImageItem.frap`, auto placement, dragged on the canvas via `Canvas.show_frap` / `frapMoved`), (B−BG)/(C−BG) curves, ImageJ-equal ROI masks, exponential recovery fit, drift correction (ROIs follow each frame's movement, `track_drift`), group means, summary CSV / figures |
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
