# 강도 측정 tab (intensity in logic regions) and the measurement table

[← Manual index](README.md) · [한국어](../ko/09-intensity.md)

Open this tab with **Tool › 강도 측정** (it appears on the right; turn the item off to close it). Its results are saved from **파일 › 내보내기** (File › Export).

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

All three tabs with a measurement table save from their own menu under
**파일 › 내보내기** (**세포질 ROI**, **입자 ROI**, **강도 측정 (논리 영역)**).

- **측정 CSV 저장 (현재 이미지)…** (Save measurement CSV, current image).
- **모든 이미지 측정 + 저장 (폴더)…** (Measure all and save): measures every
  image again, then writes the set's CSV (`<suffix>.csv`) and each image's
  `<name>_<suffix>.csv` in its `<name>_<ID>` folder (plus the summaries in
  the 입자 ROI tab and `image_groups.csv`).
- With **파일 › 내보내기 › 측정·프로파일 저장 시 ROI와 ROI가 그려진 이미지(.png)도
  함께** (on by default, shared by every tab) the save also writes
  `<name>_RoiSet.zip` (cell, nucleus, cytosol), `<name>_particles.zip` when
  particles are used, the logic-region ROIs, and `<name>_image.png` (the
  image with the current LUTs and the ROI outlines).

| Tab | `<suffix>` |
|---|---|
| 세포질 ROI | `cell_intensity` |
| 입자 ROI | `particle_intensity` (per cell) or `particle_shape` (per particle) |
| 강도 측정 | `intensity` |
