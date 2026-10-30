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
- **Right panel**: at first only the **LUT** tab (marker settings fixed at its
  bottom) and **이미지 정보** (Image info); the other tabs are opened with
  the **View** menu (or **… 탭 열기**, Open … tab, in each feature's menu).
- **Menu bar**: **파일** (File: projects, loading with automatic detection,
  saving all results, work log, settings), then **Tool** with one submenu per feature
  (**LUT**, **마커**, **Crop**, **세포질 ROI**, **입자 ROI**, **강도 측정**,
  **Coloc 2**, **라인 프로파일**, **FRAP 측정**, **스택**, **이미지 정보**, **Figure**), each with
  that feature's tab and its saves and loads. See
  [Menus, project files and the work log](13-project-menus.md).

## Manuals by feature

| Manual | Covers |
|---|---|
| [Getting started: images, viewing, groups](01-getting-started.md) | Adding files and folders, image list, groups, TCF HT/FL alignment, Z/T navigation, zoom, crops, image ID |
| [Batch analysis](15-batch.md) | Pick groups and tick analyses to run them all at once, review / fix / measure again, save only the batch results and settings, load only a project's settings |
| [Menus, project files and the work log](13-project-menus.md) | File menu and feature menus, loading with automatic detection, saving and opening projects, work log, mouse sensitivity |
| [LUT tab and image export](02-lut-export.md) | Channel display (LUT), batch LUT, presets, TIFF/MP4 export, saving all results |
| [세포질 ROI tab](03-cytosol-roi.md) | Automatic cell/nucleus/cytosol ROI detection, editing, ImageJ ROI files, cell intensity |
| [입자 ROI tab](04-particle-roi.md) | Particle (spot/condensate) detection, per-cell and per-particle measurements, shape, summaries |
| [마커 (Markers, in the LUT tab)](05-markers.md) | Scale bar, time stamp, CZI bleach ROIs, saving and loading the settings |
| [스택 tab](06-stack.md) | 2D Z projections and 3D rotation views, saving them |
| [라인 프로파일 tab](07-line-profile.md) | Intensity profile along a line (ImageJ RGB Profiler) |
| [FRAP 측정 tab](14-frap.md) | Recovery after photobleaching, group means ± error bars, mobile fraction / t½ summary |
| [Coloc 2 tab](08-coloc2.md) | Per-cell colocalization (Fiji Coloc 2) |
| [강도 측정 tab](09-intensity.md) | Intensity in regions defined by logic (e.g. `cyto - particle`), and the measurement table shared by all measuring tabs |
| [이미지 정보 tab](10-image-info.md) | Acquisition metadata (lasers, detectors, objective, bleaching) |
| [Figure window](11-figure.md) | Figure tables with labels, zoom insets, scale bars; PNG/TIFF/PDF/SVG |
| [Graph editor window](16-graph.md) | A tab's graph in its own window: chart type, x / y columns, colors, widths, fonts, axes, legend, text boxes; export of the graph and its data |
| [Output files](12-output-files.md) | Every file the program writes, and folder loading |

The Crop, 세포질 ROI, 입자 ROI, 강도 측정, Coloc 2, 라인 프로파일, FRAP 측정 and 스택 tabs
are opened from the menu of the same name under **Tool**, which also saves and loads that
tab's results.

## Keyboard and mouse summary

| Action | How |
|---|---|
| Load (projects, images, ROIs, presets; detected automatically) | `Ctrl+O` (macOS `⌘O`), or drag files/folders onto the window |
| Load a folder (pair images, TIFFs and ROIs by ID) | `Ctrl+Shift+O` |
| New project / save project / save as | `Ctrl+N` / `Ctrl+S` / `Ctrl+Shift+S` |
| Image export (TIFF / MP4) | `Ctrl+E` |
| Save all results (one folder per image) | `Ctrl+Shift+E` |
| Batch analysis / batch results | `Ctrl+B` / `Ctrl+Shift+B` |
| Figure window | `Ctrl+Shift+F`; inside it, save with `Ctrl+S` |
| Graph editor of the current tab | `Ctrl+G`; inside it, save the image with `Ctrl+S`, reload with `Ctrl+R` |
| Work log | `Ctrl+Shift+L` |
| Zoom | `Cmd` (Windows `Ctrl`) + drag up/down, `]` in / `[` out; **영역 확대** (zoom to area) or `Shift`+drag a rectangle; **화면 맞춤** (fit) to reset. Sensitivity in **파일 › 설정…** |
| Mouse wheel | Time series: moves through time (one timepoint per notch). Otherwise scrolls the view |
| Pan | Middle-button drag (right-button drag too on images without Z or T) |
| Move through T and Z | Right-button drag on the image: left/right = T, up/down = Z |
| Z slice | Z slider, mouse wheel over the slider, `↑` `↓` / `PageUp` `PageDown` |
| Remove images from the list | Select, then `Delete` / `Backspace` |
| Cell ROI editing | `V` select, `A` add, `S` subtract, `N` new cell, `Delete` delete cell, `Ctrl+Z` / `Ctrl+Shift+Z` undo/redo |

## Citing the analysis

For the Methods section of a paper, use the statement in the repository
[README](../../README.md#methods-statement).
