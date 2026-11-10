# Cytosol Viewer user manual (English)

[한국어 설명서](../ko/README.md)

Cytosol Viewer (v0.38) opens Tomocube TCF, Zeiss CZI, Olympus/Evident OIR and
TIFF images, finds cell, nucleus and cytosol ROIs, measures them the way
ImageJ/Fiji does and exports images, ROIs, tables and figures.

The program's buttons are in Korean. This manual writes each label as it
appears on screen, followed by its meaning in parentheses, e.g.
**파일 추가…** (Add files).

## Window layout

- **Left panel**: the image list and groups.
- **Centre**: the image, with the Z slider on its left, the T slider below it
  and the view buttons above it.
- **Right panel**: at first only **LUT**, **마커** (Markers) and **이미지 정보**
  (Image info), switched with capsule buttons; the other tabs are opened with
  the **View** menu (or **… 탭 열기**, Open … tab, in each feature's menu).
- **Menu bar**: **파일** (File: projects, loading with automatic detection, **내보내기…**
  (Export), batch analysis, work log, settings), **Tool** (one submenu per feature: **LUT**,
  **마커**, **세포질 ROI**, **입자 ROI**, **강도 측정**, **Coloc 2**, **라인 프로파일**,
  **FRAP 측정**, **스택**; tab and loads), **View**, **그래프** (graphs) and **Figure**.
  Everything is saved from the [Export window](17-export.md). See
  [Menus, project files and the work log](13-project-menus.md).

## Manuals by feature

| Manual | Covers |
|---|---|
| [Getting started: images, viewing, groups](01-getting-started.md) | Adding files and folders, image list, groups, TCF HT/FL alignment, Z/T navigation, zoom, crops, image ID |
| [Batch analysis](15-batch.md) | Pick groups and tick analyses to run them all at once, review / fix / measure again, save only the batch results and settings, load only a project's settings |
| [Menus, project files and the work log](13-project-menus.md) | File menu and feature menus, loading with automatic detection, saving and opening projects, work log, mouse sensitivity |
| [LUT tab](02-lut-export.md) | Channel display (LUT), batch LUT, presets |
| [세포질 ROI tab](03-cytosol-roi.md) | Automatic cell/nucleus/cytosol ROI detection, editing, ImageJ ROI files, cell intensity |
| [입자 ROI tab](04-particle-roi.md) | Particle (spot/condensate) detection, per-cell and per-particle measurements, shape, summaries |
| [마커 (Markers tab)](05-markers.md) | Scale bar, time stamp, CZI bleach ROIs, saving and loading the settings |
| [스택 tab](06-stack.md) | 2D Z projections and 3D rotation views, saving them |
| [라인 프로파일 tab](07-line-profile.md) | Intensity profile along a line (ImageJ RGB Profiler) |
| [FRAP 측정 tab](14-frap.md) | Recovery after photobleaching, group means ± error bars, mobile fraction / t½ summary |
| [Coloc 2 tab](08-coloc2.md) | Per-cell colocalization (Fiji Coloc 2) |
| [강도 측정 tab](09-intensity.md) | Intensity in regions defined by logic (e.g. `cyto - particle`), and the measurement table shared by all measuring tabs |
| [이미지 정보 tab](10-image-info.md) | Acquisition metadata (lasers, detectors, objective, bleaching) |
| [Figure window](11-figure.md) | Figure tables with labels, zoom insets, scale bars; PNG/TIFF/PDF/SVG |
| [Graph editor window](16-graph.md) | A tab's graph in its own window: chart type, x / y columns, colors, widths, fonts, axes, legend, text boxes; export of the graph and its data |
| [등거리 띠 tab](18-bands.md) | Distance bands from the nucleus to the cell edge: per-band intensity and particles, graph |
| [Export window](17-export.md) | File › Export: images, crops, ROIs, tables, graphs, info, batch results and the project saved from one window |
| [Output files](12-output-files.md) | Every file the program writes, and folder loading |

The 세포질 ROI, 입자 ROI, 강도 측정, Coloc 2, 라인 프로파일, FRAP 측정 and 스택 tabs
are opened from the menu of the same name under **Tool** (or **View**). Results are saved
from **파일 › 내보내기…** ([Export window](17-export.md)).

## Keyboard and mouse summary

| Action | How |
|---|---|
| Load (projects, images, ROIs, presets; detected automatically) | `Ctrl+O` (macOS `⌘O`), or drag files/folders onto the window |
| Load a folder (pair images, TIFFs and ROIs by ID) | `Ctrl+Shift+O` |
| New project / save project / save as | `Ctrl+N` / `Ctrl+S` / `Ctrl+Shift+S` |
| Export (images, crops, ROIs, tables, graphs, project …) | `Ctrl+E` |
| Batch analysis / batch results | `Ctrl+B` / `Ctrl+Shift+B` |
| Figure window | `Ctrl+Shift+F`; inside it, save with `Ctrl+S` |
| Graph editor of the current tab | `Ctrl+G`; inside it, reload with `Ctrl+R` |
| Work log | `Ctrl+Shift+L` |
| Zoom | `Cmd` (Windows `Ctrl`) + drag up/down, `]` in / `[` out; **영역 확대** (zoom to area) or `Shift`+drag a rectangle; **화면 맞춤** (fit) to reset. Sensitivity in **Preferences** |
| Mouse wheel | Time series: moves through time (one timepoint per notch). Otherwise scrolls the view |
| Pan | Middle-button drag (right-button drag too on images without Z or T) |
| Move through T and Z | Right-button drag on the image: left/right = T, up/down = Z |
| Z slice | Z slider, mouse wheel over the slider, `↑` `↓` / `PageUp` `PageDown` |
| Remove images from the list | Select, then `Delete` / `Backspace`, the trash icon at the end of the row, or right-click |
| Group images | Select two or more, right-click › 그룹 지정… / 그룹 이름 변경… / 그룹 해제 |
| Cell ROI editing | `V` select, `A` add, `S` subtract, `N` new cell, `Delete` delete cell, `Ctrl+Z` / `Ctrl+Shift+Z` undo/redo |

## Screen design (Apple HIG)

The screens follow the desktop rules of the Apple Human Interface Guidelines.

- Every platform is drawn in the same design-system style (light and dark,
  following the system setting); all colors come from the design tokens
  (accent blue, secondary label, separator, fills).
- macOS (tahoe) style: buttons, tab buttons and chips are capsules, fields
  are borderless fills (radius 8), and radii shrink inwards (card 12 → selected
  row 10 → value 6). The window is three regions (image list, preview, tools):
  the image list is the window's lowest layer, the preview and tools float on
  it as rounded boxes (v0.58), each with its own inner padding (20 px). Switch
  knobs are slightly wide capsules, and rows that belong together have no
  hairline between them. Only each tab's main action (e.g. **ROI 검출 (현재
  이미지)**, **지금 측정**) is a filled blue button.
- Selection controls follow their use: a **switch** only for a value's
  **자동 / 수동** (auto / manual) choice, a **check box** for one on / off
  option, **multi-select chips** for short values picked together
  (measurements Mean·StdDev…, channels to measure, channel visibility, ROI
  kinds; a check mark and blue outline when on), **radio buttons** for one of
  several, and **choice chips** for sub-tabs inside a panel (e.g. 자동 /
  수동 (threshold)).
- Settings sit in rounded translucent cards (inset groups). Every tab uses
  the same spacing, so group titles, the rows in a card and the text outside
  the cards start on one vertical line (12 px inside the card).
- Selected items in menus and lists are a blue pill with white text.
- On macOS the image list on the left and the tab pane on the right use the
  translucent sidebar material (Liquid Glass), so the desktop shows through;
  the image preview in the centre stays opaque. With **Reduce transparency**
  on (Accessibility) they are drawn opaque.
- Help text is one step smaller in the secondary label color; warnings are a
  colored dot plus text (e.g. an orange dot and the message on a tinted
  background), never color alone.
- Delete / remove buttons that cannot be undone are set apart from the other
  buttons in red text; a trailing `…` means a confirmation alert follows, and
  its default button (Return) is **취소** (Cancel). Deleting cell ROIs, which
  can be undone, needs no confirmation.
- Measurement graphs (FRAP, line profile, graph editor, Figure) and the image
  preview are not restyled.

## Citing the analysis

For the Methods section of a paper, use the statement in the repository
[README](../../README.md#methods-statement).
