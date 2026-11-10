# 등거리 띠 tab (distance bands from the nucleus to the cell edge)

Opened from **Tool › 등거리 띠** (or the View menu). In v0.57 – 0.59 it sat at the bottom of the
세포질 ROI tab, before that in the 강도 측정 tab; band settings of projects saved then are still loaded.
Cell and nucleus ROIs come from the [세포질 ROI tab](03-cytosol-roi.md) first.

The cytosol is cut into bands of equal distance from the nucleus and every
band is measured per channel. Only cells with a nucleus are measured.

| Setting | Meaning |
|---|---|
| **거리** (Distance) | **상대 거리** (relative, default): distance from the nucleus ÷ (distance from the nucleus + distance to the cell edge), so 0 is the nucleus edge and 1 the cell edge whatever the cell's size. **핵 경계에서의 거리 (µm)**: the real distance from the nucleus outline (pixels without calibration). For cells cut by the frame the cut border counts as the cell edge. |
| **범위** (Range) | The distance range measured: 0 – 1 by default for relative, 0 – 10 for µm. |
| **띠 개수** (Number of bands) | How many equal bands the range is cut into (default 10). |
| **이미지에 띠 표시** (Show bands) | Draws the band borders in cyan while this tab is shown. |

The measurement table below works like the cell intensity table of the 세포질 ROI tab. One row per
cell and band, with `band`, `distance_rel` (or `distance_µm`, the band's
centre) with `_from` and `_to`, the area and the values per channel. With
particles, every band also gets `n_particles` (particles whose centre is in
the band), `particle_area_um2`, `particle_area_fraction` and per channel
`_particle_Mean` (mean of the particle pixels in the band).

**그래프** (Graph): x and y can be any measured column (default x = the
distance, y = the first channel's Mean). Grey lines are single cells, the red
line and band the mean ± SD over cells per band. With the table set to **모든
이미지**, the batch results are drawn.

Saving: in **파일 › 내보내기…** pick the **등거리 띠** kind: **띠별 측정 CSV** (per image
`<name>_bands.csv` and `bands.csv` for the set) and **띠 그래프 (현재 이미지)**
([Export window](17-export.md)). The graph also opens in the graph editor from **그래프 › 등거리 띠**.
The batch step **핵 → 세포막 등거리 띠** uses this tab's settings.
