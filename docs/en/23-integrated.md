# Integrated data (v0.68)

There is no separate step to combine the values of different features. Every measurement goes into
the tables of its **category** by itself. Measuring an image again changes only that image's rows, and
nothing is measured again for it (the tables are built from the results the tabs already hold, so they
always equal the original tables).

## Categories (one point = what)

| Table | One point | Filled by |
|---|---|---|
| 통합 · 이미지별 (per image) | image | cell means, particle count, FRAP fit (mobile fraction, t½ …) |
| 통합 · 세포별 (per cell) | cell | 세포질 ROI, 입자 ROI (per cell), 강도 측정, Coloc 2, mitoROI (cells), 입자 추적 (cell summary) |
| 통합 · 세포 × 띠별 (per cell × band) | one distance band of a cell | 등거리 띠 measurement + band area, particle count · density · means in the band, mito fragment count · length (MiNA) · junctions · end points · puncta in the band |
| 통합 · 입자별 (per particle) | particle | 입자 ROI per particle: shape, intensity, partition coefficient + its cell and band |
| 통합 · 미토 조각별 (per mito fragment) | mito fragment | mitoROI fragments: length, branches, area, green + cell, band, network / individual |
| 통합 · 시점별 (per timepoint) | timepoint | 입자 추적 (cell × timepoint), FRAP recovery curves |

- Columns are named `feature › column` (e.g. `입자 ROI › area_um2`, `mitoROI › footprint_fraction`);
  the key columns (image, image_id, group, cell, band, particle, mito, frame) come first and join the rows.
- Particles, mito fragments, junctions, end points and puncta get their cell and band from their position
  (bands follow the 등거리 띠 tab settings). An empty band counts 0 (when that image was measured).
- Measurements with timepoints put the first timepoint in the per-cell table; every timepoint is in the
  per-timepoint table.

## Where to see it

- **Data card of a measuring tab**: the line 「측정하면 통합 데이터의 … 표에 저절로 들어갑니다」 names the
  categories the tab fills.
- **Graph editor › Data**: **통합 데이터** at the top (rows and 「설정 바뀜」 per table), the tabs' own tables
  folded below under **기능별 표 (원본)**. Clicking an integrated table starts a new graph (type → axes →
  groups); the column lists of the axes step are grouped by feature. Images whose settings or ROIs
  changed are measured again when the table is opened.
- **Graph menu › 통합 데이터에서 새 그래프…**.
- Values of several features can be drawn as a **correlation matrix** (heat map): pick 상관 행렬 as the chart
  type; the column sets are per feature, so one or more features can be correlated with each other (the
  same calculation as the mitoROI tab's heat map).

## Export

**파일 › 내보내기…** has **통합 데이터** as its first kind (on by default). It writes one CSV per category at
the top of the export folder — `integrated_images.csv`, `integrated_cells.csv`,
`integrated_cell_bands.csv`, `integrated_particles.csv`, `integrated_mito_fragments.csv`,
`integrated_timepoints.csv` (only those with rows) — and the column notes `integrated_columns.csv`
(table, column, feature, source column, how: as is / cell mean / particle mean / count · mean in the
band), with only the rows of the images exported. Each feature's own CSVs are still picked under that
feature.
