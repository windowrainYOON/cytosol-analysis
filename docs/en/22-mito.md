# mitoROI tab (v0.67)

Splits the mitochondria of every cell of the 세포질 ROI tab and measures their skeleton (MiNA) and the
mito objects. With a protein-of-interest (POI) channel it also measures the signal on / off mito, puncta,
colocalisation (Pearson, Manders) and green+ / green− cells. The code is Mito Analyzer 1.8.0's own, so the
same cell ROIs give the same numbers as Mito Analyzer.

Open: Tool › **mitoROI** › mitoROI 탭 열기 (or the View menu). Find the cells in the 세포질 ROI tab first.

## Running

- **분석 실행**: the current image. **모든 이미지에 실행**: every image with cell ROIs. The batch step
  **mitoROI** does the same.

## 1 채널 · 세포 (channels and cells)

- **미토콘드리아** / **관심 단백질** channels (POI = 없음: mito shape only).
- **가장자리 세포 포함**: also cells touching the frame (left out by default).
- **경계 약한 이웃 제외**: leave out cells whose border with a neighbour is not darker than the cells (one
  cell split in two); **경계 대비 기준** sets how much.
- Status: cells, analysed, left out at the edge / with a weak border.

## 2 미토 분할 (mito segmentation)

- **조각 분할** (default): rolling ball 1.5 µm + σ 0.7 px, per cell above the local mean AND 0.5 × Otsu,
  touching objects split by an h-maxima watershed.
- **MiNA 기본**: Otsu of the mito channel inside each cell.
- **임계값** [value][자동]: off = one value on the preprocessed image.
- **최소 조각**: smaller pieces are not mito objects (they stay in the MiNA values).

## 3 관심 단백질 (POI)

- **배경** [value][자동]: automatic = the dark-gap level between cells.
- **green+ 기준**: bright green covering at least this % of the cytoplasm = green+.
- **점 (puncta) 민감도**, **점 임계값** [value][자동]: one top-hat threshold per image (automatic =
  max(Otsu, median + 6 MAD) × sensitivity).

## 4 표시 (layers)

Chips: mito area (magenta), skeleton (green), end points (yellow), junctions (blue), green puncta, cell
numbers. The cell picked in the table gets a yellow outline.

## 5 결과 (results)

- Tables per cell / mito object / punctum.
- **상관 히트맵 ›**: correlation matrix of `mitoROI · 세포` (mito shape × POI, Spearman ρ) in the graph
  window; a cell opens the scatter of those two columns with the regression line.
- **그룹 비교 ›**: correlation comparison between image groups (A vs B, Fisher z).
- **Mito Analyzer 결과 불러오기…**: `<name>_per_cell.csv` (with `_per_mito`, `_green_puncta` beside it) onto
  the image of that name (else the current one); 파일 › 불러오기 and drag and drop recognise it too.

## Data and export

- Graph window data list: `mitoROI · 세포`, `mitoROI · 미토 조각`, `mitoROI · 점`, with Mito Analyzer's
  column names and the column sets 「미토 형태」「관심 단백질」 (cells), 「조각 형태」「조각 위 green」
  (objects) as the matrix's default X / Y.
- 파일 › 내보내기 › **mitoROI**: Mito Analyzer's names `<name>_per_cell.csv`, `_per_mito.csv`,
  `_green_puncta.csv`, `_correlations.csv`, `_mito_RoiSet.zip`, and `mito_per_cell.csv` … for all images.
- Results are saved in projects.

## Main columns

| Column | Meaning |
|---|---|
| footprint_fraction | mito area / cell area |
| n_networks, n_branches, total_branch_length_um | MiNA skeleton: networks, branches, total branch length |
| branch_length_mean_um, summed_branch_lengths_mean_um, network_branches_mean | mean branch length, mean network length, branches per network |
| donuts | ring-shaped networks |
| n_mito_objects, mito_length_mean_um, mito_aspect_ratio_mean, form_factor_mean | number and shape of mito objects |
| green_mean_on_mito / off_mito, green_enrichment_on_mito | POI mean on / off mito and their ratio |
| pearson_red_green, manders_m_green, manders_m_mito | colocalisation |
| n_green_puncta, fraction_puncta_on_mito | puncta, fraction on mito |
| green_status, green_bright_area_percent | green+ / green−, % of cytoplasm under bright green |
