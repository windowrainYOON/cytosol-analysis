# Cytosol Viewer user manual (English)

[한국어 설명서](../ko/README.md)

Cytosol Viewer (v0.23) opens Tomocube TCF, Zeiss CZI, Olympus/Evident OIR and
TIFF images, finds cell, nucleus and cytosol ROIs, measures them the way
ImageJ/Fiji does and exports images, ROIs, tables and figures.

The program's buttons are in Korean. This manual writes each label as it
appears on screen, followed by its meaning in parentheses, e.g.
**파일 추가…** (Add files).

## Window layout

- **Left panel**: the image list, the Crop list and **Figure 만들기…** (Make figure).
- **Centre**: the image, with the Z slider on its left, the T slider below it
  and the view buttons above it.
- **Right panel**: the tabs below.
- **Menu bar**: **파일** (File) and **Figure**.

## Manuals by feature

| Manual | Covers |
|---|---|
| [Getting started: images, viewing, groups](01-getting-started.md) | Adding files and folders, image list, groups, TCF HT/FL alignment, Z/T navigation, zoom, crops, image ID |
| [LUT · 내보내기 tab](02-lut-export.md) | Channel display (LUT), batch LUT, presets, TIFF/MP4 export, export everything |
| [세포질 ROI tab](03-cytosol-roi.md) | Automatic cell/nucleus/cytosol ROI detection, editing, ImageJ ROI files, cell intensity |
| [입자 ROI tab](04-particle-roi.md) | Particle (spot/condensate) detection, per-cell and per-particle measurements, shape, summaries |
| [마커 tab](05-markers.md) | Scale bar, time stamp, CZI bleach ROIs |
| [스택 tab](06-stack.md) | 2D Z projections and 3D rotation views, saving them |
| [라인 프로파일 tab](07-line-profile.md) | Intensity profile along a line (ImageJ RGB Profiler) |
| [Coloc 2 tab](08-coloc2.md) | Per-cell colocalization (Fiji Coloc 2) |
| [강도 측정 tab](09-intensity.md) | Intensity in regions defined by logic (e.g. `cyto - particle`), and the measurement table shared by all measuring tabs |
| [이미지 정보 tab](10-image-info.md) | Acquisition metadata (lasers, detectors, objective, bleaching) |
| [Figure window](11-figure.md) | Figure tables with labels, zoom insets, scale bars; PNG/TIFF/PDF/SVG |
| [Output files](12-output-files.md) | Every file the program writes, and folder loading |

## Keyboard and mouse summary

| Action | How |
|---|---|
| Open files | `Ctrl+O` (macOS `⌘O`), or drag files/folders onto the window |
| Load a folder (pair images, TIFFs and ROIs by ID) | `Ctrl+Shift+O` |
| Batch TIFF export | `Ctrl+E` |
| Export everything (one folder per image) | `Ctrl+Shift+E` |
| Figure window | `Ctrl+Shift+F`; inside it, save with `Ctrl+S` |
| Zoom | Mouse wheel; **영역 확대** (zoom to area) or `Shift`+drag a rectangle; **화면 맞춤** (fit) to reset |
| Pan | Middle-button drag (right-button drag too on images without Z or T) |
| Move through T and Z | Right-button drag on the image: left/right = T, up/down = Z |
| Z slice | Z slider, mouse wheel over the slider, `↑` `↓` / `PageUp` `PageDown` |
| Remove images from the list | Select, then `Delete` / `Backspace` |
| Cell ROI editing | `V` select, `A` add, `S` subtract, `N` new cell, `Delete` delete cell, `Ctrl+Z` / `Ctrl+Shift+Z` undo/redo |

## Citing the analysis

For the Methods section of a paper, use the statement in the repository
[README](../../README.md#methods-statement).
