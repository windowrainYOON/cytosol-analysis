# Graph editor window (그래프 편집 창)

[← Manual contents](README.md) · [한국어](../ko/16-graph.md)

Opens a feature tab's graph in one window, where every part of it can be changed. All
graphs gather in this one window's sidebar; they are saved from **파일 › 내보내기…** (File ›
Export), kind **그래프**.

## Opening it

- **그래프 › 현재 탭의 그래프 편집 창** (`Ctrl+G`): the graph of the tab shown on the right
- **그래프 ›** (feature name): the graph of a feature that has results, as its tab shows it
- the **새 그래프** (new graph) chips on top of the graph editor: a new graph from an
  analysis' result, step by step (below).

| Feature | Graph it opens with |
|---|---|
| FRAP 측정 | The graph picked in the tab: recovery curve + fit, ROI mean intensities, or group means ± SEM/SD (+ single curves, fits) |
| 라인 프로파일 | One line per channel (channel colors, channels hidden in the LUT tab left out, 0–1 normalization as set) |
| Distance bands | A gray line per cell + the red mean ± SD band (the x / y picked in the tab) |
| 세포질 ROI · 입자 ROI · 강도 측정 tables | Bars (mean ± SD, one dot per value) of the first mean column (area for per-particle rows) by group, image, region or ROI |
| Coloc 2 | The selected ROI's 2D histogram as a heat map (regression line, thresholds); per-ROI Pearson R bars when a result image was shown |

Opening it again, or **편집 › 도구의 현재 결과 다시 불러오기** (reload, `Ctrl+R`), takes the
tab's latest results; settings you changed are kept while the column names stay the same.
**편집 › 처음 그래프로 되돌리기** (reset) returns every setting to the first graph.

## A new graph, step by step

The **새 그래프** chips on top are one per analysis (cell / particle ROI measurements, 강도
측정, distance bands, Coloc 2, line profile, FRAP, batch results); the last one, **CSV…**,
takes a CSV file (first row = column names; comma, semicolon or tab). Chips of features not
analysed yet are dimmed; their tool tip says what to do first. A chip opens the **새 그래프**
window, where three steps are set in turn next to a preview:

1. **그래프 종류** (chart kind): XY (lines · points), bars, dot plot, box plot, violin,
   histogram, heat map. The kind that fits the table is marked **추천** (recommended): category
   comparisons when it has text columns, XY for two numbers.
2. **축 배치** (axes): the **data table**, and for the **X axis** and the **Y axis** each
   **범주 / 값** (category / value) and a column.
   - **범주** gathers equal values in one place (group, image …); **값** puts numbers on a
     scale. Text columns can only be categories. Either axis can take any column.
   - Bars, dot plots, box plots and violins have one category axis. Switching X to 값 swaps the
     axes: categories go on the vertical axis (a horizontal graph).
   - The **Y axis takes several columns** (**＋ Y 열 추가**, × at the end of a row removes
     one); each becomes a series of its own colour.
   - **색으로 나누기** (colour split): none, **one colour per Y column**, or a text column (one
     colour per value; the category column itself = one colour per category).
   - **에러바** (SD / SEM / 95 % CI / none); XY: **같은 x 묶기** (mean / median of equal x).
3. **그룹** (groups): one row per value of the category column (else of the colour column),
   with n. Only checked groups are drawn; drag rows to change their order. **모두** / **없음**.

**그래프 만들기** adds the graph to the sidebar. The three steps can be changed any time in the
inspector's **데이터** tab.

## Layout

- **Sidebar** (left): the graphs of this window. Double-click renames; right-click: new
  graph, duplicate, rename and, last in red, **그래프 삭제…**.
- **Centre box**: the **새 그래프** chips on top, the graph preview (same proportions as the
  saved size), and the data table below: **그래프에 쓰인 데이터** (one row per point drawn),
  **그래프 요약** for bars / boxes (n, mean, SD, SEM, median, min, max), and every result
  table of the feature. Copy cells with `Ctrl+C` (macOS `⌘C`); drag the border to resize.
- **Inspector** (right, fixed width): tabs **데이터** / **모양** / **통계**.
  - **데이터** (data): chart kind cards, **축 배치** and **그룹** (as in the step window). A
    graph opened from a feature tab starts with the tab's own series; changing the axes draws
    it again from the chosen table (lines of other tables, such as fit curves, stay).
  - **모양** (look): **색** (one per series), **점 · 선**, bar / histogram / heat map options,
    **축** (X / Y chips), **제목**, **범례**, **글꼴**, **그림**, **글자 상자**. Clicking the title,
    an axis label, the legend, a point or bar, or a text box on the graph jumps to its card.
  - **통계** (statistics): significance marks (below).

## On the graph

The **plot area**, **title**, **X / Y axis labels**, **text boxes** and **legend** are all
objects you select, move and resize.

- **Click** selects (dashed blue box); **drag** moves.
- **Drag the blue handle** (bottom right) to resize: width / height for the plot area (top
  edge fixed), the font size for text (both axis labels share one size).
- Dragging something laid out automatically first pins it where it is. **모두 자동 배치로** in
  **모양 › 그림** or right-click › **모든 위치·크기 자동 배치로** returns to automatic layout.
- **Double-click** a text box, the title, an axis label or a legend entry to edit it.
- **Right-click**: add a text box here, move the legend here, add a legend entry, delete
  this text box.

### Zooming the preview (as in the image preview)

- `Cmd` (Windows `Ctrl`) + left-drag up / down, `]` in / `[` out, `Cmd` (`Ctrl`) + wheel.
- **화면 맞춤** (fit, `Ctrl+0`) and the **－ ＋** buttons above the preview; the zoom is shown.
- Pan with the middle button, the wheel (up / down) and `Shift` + wheel (sideways). The drag
  rate follows the zoom sensitivity in Settings. Zoom only changes the preview, not the
  saved figure size.

## Look (모양)

- **점 · 선** (all series): drawing style (XY: line + points, line, points, steps, area), line
  style and width, marker shape, size and fill, opacity, error bar style (bars / band / none),
  width and caps.
- Bars / dot plots / boxes / violins: **개별 값을 점으로 표시** (show single values), width, fill
  opacity, jitter. Histogram: bins (automatic), density, fill. Heat map: colour map, log
  scale, colour bar. Series that share a category stand side by side; a series alone in its
  category (colour = category) sits in the middle.
- **축** (axes), picked with the **X 축** / **Y 축** chips: name, unit, unit conversion
  (s → min, …; sets scale and unit together), automatic range with min / max, automatic tick
  spacing with its step, log scale, minor ticks, tick direction, tick label rotation, value
  scale (×). While automatic, the fields show the values in use. A unit is added to the name in
  brackets (`Time` + `min` → `Time (min)`); a new scale also converts a range set by hand.
- **제목** (title) text and font; **범례** (legend): shown, position (automatic, above, right,
  inside corners, placed by hand), title, columns, frame, font, extra entries (name, colour,
  marker); rename entries by double-clicking them in the legend.
- **글꼴** (fonts): family (empty = default with Korean fallback), axis label size / bold, tick
  label size, text and axis colour. **그림** (figure): width × height (in), dpi, background,
  top / right spines, spine width, grid and its colour, automatic plot area, **모두 자동 배치로**.
- **글자 상자** (text boxes): list, add, red **삭제…**, text, size, colour, bold, frame, alignment.

## Statistics and significance marks (통계 · 유의성 표시)

Bars, dot plots, box plots and violins can compare their categories and draw brackets with
stars (\*). Switch **유의성 표시** on in the inspector's **통계** tab; **통계 창 열기…** (or
**편집 › 통계 · 유의성 표시…**) sets the same things in a large window with a preview
(**적용** writes them into the graph). Everything is computed with SciPy.

- **Data check** (window): n and normality (Shapiro-Wilk; n < 3 cannot be tested) per group,
  equal variances (Levene).
- **Test**: a **recommendation** from the data.
  - 2 groups: normal + similar variances → t-test, normal + different variances → Welch's
    t-test, not normal → Mann-Whitney U.
  - 3 or more: normal + similar variances → one-way ANOVA + Tukey, normal + different
    variances → Welch's ANOVA + Games-Howell, not normal → Kruskal-Wallis + Dunn.
  - **Paired** samples (same cells / images): paired t-test or Wilcoxon signed-rank.
  - **비교할 값**: which Y column (or series) is compared when there are several.
  - **Method**: recommended (default) or chosen. **Tails**: two-tailed (recommended),
    one-tailed (compared group > / < reference; only when the direction was fixed before the
    experiment). Post hoc tests after ANOVA / Kruskal-Wallis are two-tailed only.
  - **Multiple comparisons**: Holm (default), Bonferroni, Benjamini-Hochberg (FDR), none;
    Tukey and Games-Howell use their own. **α**: 0.05 / 0.01 / 0.001.
- **Pairs**: **all pairs**, **reference vs the others** (reference group), or **chosen**
  (check boxes); the table shows each pair's adjusted p and mark.
- **Marks**: stars / p value / both, star levels (4: \* < 0.05, \*\* < 0.01, \*\*\* < 0.001,
  \*\*\*\* < 0.0001, or 3), ns shown, brackets (bent ends / straight), line width, text size,
  bold, and a **caption sentence** ("One-way ANOVA with Tukey's post hoc test (two-tailed),
  n = 10 per group; …", **캡션 복사** copies it).

The initial look (display, star levels, ns, tails, α, bracket shape / width / end length /
spacing, font, size, bold, caption) is set in **Preferences › 그래프 · 유의성 표시 초기값**.
The test itself has no initial value: it is recommended for each data set.

## Saving

Graph images (PNG / TIFF / PDF / SVG), data CSVs and settings JSON are saved from
**파일 › 내보내기…**, kind **그래프**, picking graphs of the sidebar
([Export window](17-export.md)). This window's **파일 › 내보내기…** opens that window with
only **그래프** switched on. **파일 › 그래프 설정 불러오기 (전체)** / **스타일만 불러오기**
apply saved settings (`format: cytosol-viewer-graph`) to another graph. CSVs are UTF-8 with
BOM so Excel opens them directly.

Features not built yet (reference lines, added fit curves, a second y axis) are not shown
in the menus.
