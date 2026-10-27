# 강도 측정 tab (intensity in logic regions) and the measurement table

[← Manual index](README.md) · [한국어](../ko/09-intensity.md)

Open or close this tab with **강도 측정 › 강도 측정 탭 열기** (Open 강도 측정 tab) in the menu bar. This tab's saves and loads are in the same **강도 측정** menu.

## 강도 측정 tab

Builds new regions per cell by combining the cell ROIs
([세포질 ROI tab](03-cytosol-roi.md)) and particle ROIs
([입자 ROI tab](04-particle-roi.md)) with set logic, and measures each
channel's raw values in them (the same values as ImageJ Measure). Cell,
nucleus and cytosol on their own are measured in the 세포질 ROI tab, and the
particles in the 입자 ROI tab.

### 논리식 영역 (Logic regions)

Type one or more expressions, separated by semicolons:

| Name | Region |
|---|---|
| `cell` | whole cell |
| `nuc` | nucleus |
| `cyto` | cytosol (cell − nucleus) |
| `particle` | the cell's particles |

| Operator | Meaning |
|---|---|
| `&` | intersection |
| `\|` | union |
| `-` | difference |
| `( )` | grouping |

Examples:

```
cyto - particle;  cell & particle;  (cell - nuc) | particle
```

- `cyto - particle`: cytosol outside the particles (dilute phase).
- `cell & particle`: particles inside the cell.
- `nuc & particle`: particles in the nucleus.

A mistyped expression is reported under the box. **이미지에 영역 표시 (청록색)**
(Show regions on the image, cyan) fills the regions of the selected cell.

With whole-image particles (입자 ROI tab, **이미지 전체**), particles are still
split by these expressions per cell, and particle pieces that cross a cell or
nucleus border go to each side.

Files: `<name>_intensity.csv`, `intensity.csv`, and `<name>_regions.zip`
(one ImageJ ROI per cell and region, `rgnCCC-R`, with the expression in its
`region` property).

### 핵 → 세포막 등거리 띠 (Distance bands from the nucleus to the cell edge)

The cytosol is cut into bands of equal distance from the nucleus and every
band is measured per channel. Only cells with a nucleus are measured.

| Setting | Meaning |
|---|---|
| **거리** (Distance) | **상대 거리** (relative, default): distance from the nucleus ÷ (distance from the nucleus + distance to the cell edge), so 0 is the nucleus edge and 1 the cell edge whatever the cell's size. **핵 경계에서의 거리 (µm)**: the real distance from the nucleus outline (pixels without calibration). For cells cut by the frame the cut border counts as the cell edge. |
| **범위** (Range) | The distance range measured: 0 – 1 by default for relative, 0 – 10 for µm. |
| **띠 개수** (Number of bands) | How many equal bands the range is cut into (default 10). |
| **이미지에 띠 표시** (Show bands) | Draws the band borders in cyan instead of the logic regions. |

The measurement table below works like the logic regions' table. One row per
cell and band, with `band`, `distance_rel` (or `distance_µm`, the band's
centre) with `_from` and `_to`, the area and the values per channel. With
particles, every band also gets `n_particles` (particles whose centre is in
the band), `particle_area_um2`, `particle_area_fraction` and per channel
`_particle_Mean` (mean of the particle pixels in the band).

**그래프** (Graph): x and y can be any measured column (default x = the
distance, y = the first channel's Mean). Grey lines are single cells, the red
line and band the mean ± SD over cells per band. With the table set to **모든
이미지**, the batch results are drawn.

Saving (**강도 측정** menu): **등거리 띠 CSV 저장 (현재 이미지)…**
(`<name>_bands.csv`), **등거리 띠: 모든 이미지 측정 + 저장 (폴더)…** (per image
`<name>_bands.csv` and `bands.csv` for the set), **등거리 띠 그래프 저장
(PNG / PDF / SVG / TIFF)…**. **모든 분석 결과 통합 저장** also writes
`<name>_bands.csv`.

## The measurement table

The 세포질 ROI, 입자 ROI and 강도 측정 tabs share the same measurement block.

### 측정값 (채널마다) — values per channel

- **Mean** (on by default), **StdDev**, **Min**, **Max**, **IntDen**,
  **RawIntDen**: the ImageJ Measure definitions, on the raw data of the
  current Z plane (or MIP) and timepoint. Area is always included.
- **LUT에서 숨긴 채널 제외**: leave out channels hidden in the LUT tab.

### 강도 측정 결과 — results

- View selector: **현재 이미지** (current image), **모든 이미지 (일괄 측정 결과)**
  (batch results); in the 입자 ROI tab also **요약: 이미지별** / **요약: 그룹별**
  (summaries per image / group).
- **자동 갱신** (Auto update, on): recalculate the current image whenever
  ROIs, Z, T or settings change. **지금 측정 (현재 이미지)** measures on demand.
- Clicking a row selects its cell in the image.
- **모든 이미지 측정** (Measure all images): every image with ROIs, the same
  regions and values (particles with each image's particle settings).
  **일괄 측정에 모든 시점 포함** (Include all timepoints) measures every
  timepoint.
- Rows have `image`, `image_id`, `group`, `cell`, `region`, `plane`, the
  time point and one column per channel and value.

### Saving

All three tabs with a measurement table save from their own menu in the
menu bar (**세포질 ROI**, **입자 ROI**, **강도 측정**).

- **측정 CSV 저장 (현재 이미지)…** (Save measurement CSV, current image).
- **모든 이미지 측정 + 저장 (폴더)…** (Measure all and save): measures every
  image again, then writes the set's CSV (`<suffix>.csv`) and each image's
  `<name>_<suffix>.csv` in its `<name>_<ID>` folder (plus the summaries in
  the 입자 ROI tab and `image_groups.csv`).
- With **파일 › 측정·프로파일 저장 시 ROI와 ROI가 그려진 이미지(.png)도
  함께** (on by default, shared by every tab) the save also writes
  `<name>_RoiSet.zip` (cell, nucleus, cytosol), `<name>_particles.zip` when
  particles are used, the logic-region ROIs, and `<name>_image.png` (the
  image with the current LUTs and the ROI outlines).

| Tab | `<suffix>` |
|---|---|
| 세포질 ROI | `cell_intensity` |
| 입자 ROI | `particle_intensity` (per cell) or `particle_shape` (per particle) |
| 강도 측정 | `intensity` |
