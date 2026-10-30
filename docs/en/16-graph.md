# Graph editor window (그래프 편집 창)

[← Manual contents](README.md) · [한국어](../ko/16-graph.md)

Opens a feature tab's graph in its own window, where every part of it can be changed,
and exports the graph and its data. Like the Figure window, it is a separate window
(one per feature).

## Opening it

- The **그래프 편집 창…** button under each tab's graph (or measurement table)
- **Tool › (feature) › 그래프 편집 창 (…)…**
- **View › 현재 탭의 그래프 편집 창** (`Ctrl+G`): the graph of the tab shown on the right
- **View › 그래프 편집 창 › (feature)**; open windows are marked **(열림)**
- **View › 그래프 편집 창 › 새 그래프** (new graph): an empty window; bring in any analysis
  result or a CSV from its **데이터** menu.

| Feature | Graph it opens with |
|---|---|
| FRAP 측정 | The graph picked in the tab: recovery curve + fit, ROI mean intensities, or group means ± SEM/SD (+ single curves, fits) |
| 라인 프로파일 | One line per channel (channel colors, channels hidden in the LUT tab left out, 0–1 normalization as set) |
| 강도 측정 › distance bands | A gray line per cell + the red mean ± SD band (the x / y picked in the tab) |
| 세포질 ROI · 입자 ROI · 강도 측정 tables | Bars (mean ± SD, one dot per value) of the first mean column (area for per-particle rows) by group, image, region or ROI |
| Coloc 2 | The selected ROI's 2D histogram as a heat map (regression line, thresholds); per-ROI Pearson R bars when a result image was shown |

Opening it again, or **다시 불러오기** (reload, `Ctrl+R`), takes the tab's latest results;
settings you changed are kept while the column names stay the same.
**처음 그래프로** (reset) returns every setting to the tab's graph.

## Layout

- **Top 70 %**: the graph preview on the left (scaled to the saved proportions) and the
  settings tabs on the right (**그래프**, **데이터 시리즈**, **축**, **글꼴**, **범례·글자**).
- **Bottom 30 %**: the data. **그래프에 쓰인 데이터** (plotted data, one row per point),
  for bar / box / … charts **그래프 요약** (n, mean, SD, SEM, median, min, max), and every
  result table the feature passed (e.g. FRAP group means, per-image curves, fit curves,
  group summary). **선택한 시리즈만** shows only the series selected in the series tab.
  Select cells and press `Ctrl+C` (macOS `⌘C`) to copy.

Drag the border between the two parts to resize them.

## Data from other analyses

The **데이터** (data) menu, or **다른 분석 데이터 +** in the toolbar, adds data to this window.

- **다른 분석 결과 가져오기 ›** (import another analysis' result) 세포질 ROI / 입자 ROI /
  강도 측정 tables, distance bands, Coloc 2, line profile, FRAP, 일괄 분석 results: adds that
  feature's tables as `feature · table` and one series using them (pick its x / y in the
  series tab). E.g. a line profile over a FRAP curve, bars of several analyses in one graph.
- **CSV 파일 불러오기…**: a CSV with column names in its first row (comma, semicolon, tab).
- **가져온 표 지우기…**: removes an imported table and the series using it.

Imported tables are saved in the project and kept on **다시 불러오기**.

## On the graph

The **plot area**, **title**, **X / Y axis labels**, **text boxes** and **legend** are all
objects you select, move and resize.

- **Click** selects (dashed blue box); **drag** moves.
- **Drag the blue handle** (bottom right) to resize: width / height for the plot area (top
  edge fixed), the font size for text (both axis labels share one size).
- Dragging something laid out automatically first pins it where it is. **배치** in the
  **그래프** tab or right-click › **모든 위치·크기 자동 배치로** returns to automatic layout.
- **Double-click** a text box, the title, an axis label or a legend entry to edit it.
- **Right-click**: add a text box here, move the legend here, add a legend entry, delete
  this text box.

### Zooming the preview (as in the image preview)

- `Cmd` (Windows `Ctrl`) + left-drag up / down, `]` in / `[` out, `Cmd` (`Ctrl`) + wheel.
- **화면 맞춤** (fit, `Ctrl+0`) and the **－ ＋** buttons above the preview; the zoom is shown.
- Pan with the middle button, the wheel (up / down) and `Shift` + wheel (sideways). The drag
  rate follows the zoom sensitivity in Settings. Zoom only changes the preview, not the
  saved figure size.

## Settings

### 그래프 (graph)

- **그래프 종류** (chart type): XY (lines / points), bars (mean ± error bars), dot plot
  (values + mean), box plot, violin, histogram, heat map (2D).
  - XY: values of the x and y columns; text x values are placed in order as categories.
  - Bars / dot plot / box / violin: y values gathered per value (category) of the x column;
    empty x = one category per series; several series sit side by side in each category.
  - Histogram: distribution of the y values. Heat map: x, y, z columns of the first series
    (other series drawn on top as lines).
- Title, size (width × height in inches), image resolution (dpi), background color.
- **배치** (layout): automatic plot area or its left / bottom / width / height (fractions of
  the figure, the values in use shown while automatic), automatic title / X / Y label
  positions, **모두 자동 배치로** (all automatic).
- Bars etc.: error bars (SD / SEM / 95 % CI / none), show single values as dots, width,
  fill opacity, dot jitter. Histogram: bins (0 = automatic), density, filled. Heat map:
  color map, log color scale, color bar.

### 데이터 시리즈 (data series)

The series list (ticked = shown) with add, duplicate, delete, ▲ ▼ (drawing order) and
**값마다 나누기…** (split into one series per value of a column, e.g. a colored series per group).

- **Data**: table, x, y, ± error column, z (heat map), two conditions (column = value),
  **같은 스타일로 나눠 그리기** (one line per value of a column in the same style, e.g. per
  cell), **묶기** (mean / median of rows with the same x, or the same value of the
  **묶는 열** column, with SD / SEM / 95 % CI).
- **Name and style**: legend name, shown, in legend, shape (line + points, line, points,
  steps, area), color, line width, line style (solid, dashed, dotted, dash-dot), marker,
  marker size, filled / open markers, marker edge, opacity, error display (bars / band / none),
  error bar color (right-click = series color), width and cap size.
  **이 스타일을 모든 시리즈에** applies the style (not the color) to every series.

### 축 (axes)

For X and Y: label, **최소 – 최대** (min – max) with **자동** (auto), tick spacing with
**자동** (auto picks a readable spacing), **단위** (unit), **값 배율** (value scale), log scale,
minor ticks, tick direction, tick label rotation. While automatic, the fields show the range
and spacing in use; switching 자동 off starts from them.

- **Unit**: added in brackets after the axis name (`Time` + `min` → `Time (min)`; a unit
  already in brackets at the end of the name is replaced). Type any unit not in the list.
- **Value scale (×)**: values are multiplied by it when drawn (fractions like `1/60` work).
  The **단위 바꾸기…** list (s → min, min → s, s → ms, min → h, 0–1 → %, % → 0–1, µm → nm,
  nm → µm) sets the scale and unit together. Changing the scale also converts a manual
  min / max / spacing so the same part of the data stays shown. The data table and exported
  CSV show scaled x / y. Top / right axis lines, axis line and tick width, grid and its color.

### 글꼴 (fonts)

Font family (empty = default, Korean falls back to a Korean font) and, for the title, axis
labels, tick labels and legend: size, color, bold, italic.

### 범례·글자 (legend and text)

- Legend: shown, position (automatic, above the graph, right of it, the four inside
  corners, custom), title, columns, frame.
- Extra legend entries that belong to no series: name, color, marker, line style.
- Text boxes: text (several lines), size, color, bold, italic, frame, alignment, position
  (axes fraction: 0–1 is inside the axes; outside works too).

## Export

| Menu | What it saves |
|---|---|
| **파일 › 그래프 이미지 저장** (`Ctrl+S`) | PNG / TIFF (at the set dpi), PDF / SVG (editable text) |
| **파일 › 그래프 설정 저장 (JSON)** | Every setting (`format: cytosol-viewer-graph`) |
| **파일 › 그래프 설정 불러오기 (전체)** / **스타일만 불러오기** | All saved settings, or only the look (fonts, axis style, legend, size, series styles by position) to give another graph the same style |
| **내보내기 › 그래프에 쓰인 데이터 (CSV)** | Every plotted point (series, x, y, error, n when aggregated) |
| **내보내기 › 선택한 시리즈의 데이터 (CSV)** | Only the series selected in the series tab |
| **내보내기 › 그래프 요약 (CSV)** | n, mean, SD, SEM, median, min, max per series and category |
| **내보내기 › 아래 표 전체 / 선택한 행 (CSV)** | The table shown below (select rows with Shift / Cmd·Ctrl + click) |
| **내보내기 › 모든 데이터 표 (폴더)** | Every result table of the feature + plotted data + summary, one CSV each |

CSVs are UTF-8 with BOM so Excel opens them directly.
