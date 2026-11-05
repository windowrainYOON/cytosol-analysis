# Export window

[← Manual contents](README.md) · [한국어](../ko/17-export.md)

Everything is saved from one window, **파일 › 내보내기…** (File › Export…,
`Ctrl+E` / `⌘E`): images, crop regions, ROIs, measurement tables, graphs, image
information, batch results and the project, picked together and written in one go.
The feature menus (Tool › …) keep only their tab item and their loads. LUT presets,
marker settings and batch settings are still saved from Tool / 파일.

## Window

- **Toolbar**: **대상** (target: current image / selected images / all images / one
  group), **저장 위치** (destination) with **폴더 선택…**, and the blue **내보내기**
  (Export) button.
- **이미지별 폴더에 나눠 저장**: on = one folder `<destination>/<name>_<image ID>/`
  per image; off = everything in one folder (same names get a number).
- **List on the left**: the kinds of output. The check box includes a kind; the
  number shows its outputs switched on / all.
- **Cards on the right**: the items and formats of the kind picked.

The choices come back the next time the window opens (image formats are also saved
in projects).

## Kinds

| Kind | Saved |
|---|---|
| 이미지 (TIFF / MP4) | Composite RGB, RGB per channel, raw-value stack (ImageJ). Time series: all time points or the current one, TIFF / MP4 / both, fps, markers drawn |
| Crop 영역 | An image per crop region (format as for images; **all regions** or **only the selected one**), crop ROIs (`<name>_crops.zip`). A region reshaped with 점 편집 (edit points) is cut as its bounding rectangle with the outside set to 0 |
| 세포질 ROI | Cell / nucleus / cytosol ROIs (RoiSet .zip or .roi), measurement CSV, PNG with the ROIs drawn, distance bands CSV / graph |
| 입자 ROI | Particle ROIs (.zip), measurement CSV, per-image / per-group summaries |
| 강도 측정 | Measurement CSV, logic region ROIs |
| Coloc 2 | Results CSV, PDF report per ROI |
| 라인 프로파일 | Line of the current image: CSV, graph, line ROI + picture |
| FRAP | Summary CSV + group graphs; per image curve CSV / graph / ROIs |
| 스택 투영 | Current projection, 3D rotation series (TIFF or MP4) |
| 그래프 | The graphs of the graph editor (pick them), format (PNG / TIFF / PDF / SVG), data CSV, settings JSON |
| 이미지 정보 | Acquisition CSV, raw metadata |
| 일괄 분석 결과 | Results (`batch/`), settings JSON |
| 프로젝트 · 작업 기록 | `project.cyproj` relative to the destination, work log CSV |

Tables over several images (`cell_rois.csv`, `coloc2.csv`, measurement CSVs,
summaries, `image_groups.csv`) go once to the top of the destination. File names:
[Output files](12-output-files.md).

Figures are saved with **Figure 저장…** / **모든 Figure 저장…** at the top of the
Figure window ([Figure](11-figure.md)).
