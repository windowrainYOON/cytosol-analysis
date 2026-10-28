# FRAP 측정 tab (FRAP measurement: recovery after bleaching)

[← Manual contents](README.md) · [한국어](../ko/14-frap.md)

Open and close this tab with **FRAP 측정 › FRAP 측정 탭 열기** (Open FRAP tab) in the
menu bar. The tab's saves and loads are in the same **FRAP 측정** menu.

For bleach experiments with a time axis (T), the tab measures how far the
bleached area recovers over time, plots it and computes the usual FRAP numbers
(mobile fraction, t½, …). The current image is measured as soon as the tab
opens.

## What is measured

For every frame

> value = (Bleach − Background) / (Control − Background)

where each term is the mean intensity inside that ROI (the same as ImageJ
Measure's Mean).

| ROI | Colour | Automatic position |
|---|---|---|
| **Bleach** (B) | red | The bleach region recorded in the file (Zeiss CZI bleach regions, Olympus/Evident OIR stimulation regions). Without a record: the place that became darkest and stayed dark compared with the frames before (the outer 4 % of the image is left out) |
| **Control** (C) | green | The innermost point of the bleached condensate outside the bleach region (its size may differ from Bleach). If the whole condensate was bleached: the nearest other condensate that was not bleached (corrects for bleaching during imaging) |
| **Background** (BG) | blue | The Bleach ROI's shape and size, at the nearest place without condensate signal |

Control skips places whose signal falls by more than 30 % at the bleach frame
(they were bleached too). Hints about the automatic positions appear in orange
under the ROI box.

## Moving ROIs

The ROIs are drawn on the image with the letters B / C / BG (**ROI 표시**,
Show ROIs, turns them off). Drag a ROI on the image: the values and the graph
follow while it moves; when let go it stays there and its **자동** (Auto)
check box turns off. Turning **자동** on again puts it back at the automatic
position. **모두 자동 배치** (Place all automatically) resets this image's
ROIs, frame and threshold. Positions and settings are kept per image.

## Settings

| Setting | Meaning |
|---|---|
| **채널** (Channel) | Channel measured (the channel with the same name on every image) |
| **bleach 전 강도로 정규화** (Normalize to pre-bleach, on by default) | Divides the value by its pre-bleach value (pre-bleach = 1), taken from the **첫 프레임** (first frame) or the **bleach 전 프레임 평균** (mean of the pre-bleach frames). This is the double normalization of Phair et al. (2004) |
| **bleach 후 첫 프레임** (first frame after bleaching) + **자동** | 1-based. Auto: the file's bleach record (CZI bleach events, OIR pre-bleach frame count), else the frame where the Bleach ROI drops most |
| Bleach **지름** (diameter) + **자동** | Diameter of the detected circle when the file has no record (auto: the circle with the darkened area's size). A bleach region from the file keeps its own shape |
| Control **지름** + **자동** | Control circle diameter (auto: the largest circle up to the Bleach ROI's size that fits in the condensate) |
| **응집체 threshold** (condensate threshold) + **자동**, slider | Condensate signal = at or above this value in the pre-bleach image (σ 1 px Gaussian); used to place Control and Background. Auto: Otsu in a window around the Bleach ROI |

## Graph

Choose in the **그래프** list:

- **회복 곡선 (현재 이미지)** (recovery curve, current image): value against time
  after the bleach (s; 0 = first post-bleach frame). **지수 회복 피팅**
  (exponential recovery fit) adds the fitted curve.
- **ROI 평균 강도 (현재 이미지)**: the raw mean intensity of Bleach, Control and
  Background.
- **그룹 평균 ± 에러바** (group mean ± error bars): the mean curve of each image
  group ([groups](01-getting-started.md)) with **SEM** or **SD** error bars,
  frames aligned on the bleach frame. Images not in a group form one set,
  `No group`. **개별 곡선도 표시** also draws each image's curve faintly. Use
  three or more images per group for error bars (fewer are flagged).

The FRAP numbers are shown under the graph.

## FRAP numbers

The frames from the bleach on are fitted with ImageJ Curve Fitter's
**Exponential recovery** `y = a·(1 − e^(−k·t)) + c` (t: s since the first
post-bleach frame). "pre" is the pre-bleach value (1 when normalized).

| Column | Meaning |
|---|---|
| `pre_bleach` | Pre-bleach value |
| `post_bleach` | Value right after the bleach (first post-bleach frame) |
| `bleach_depth` | 1 − post / pre |
| `final`, `final_recovery` | Last frame's value; (last − post) / (pre − post), a recovery without a fit |
| `plateau` | Value the fit levels off at, a + c |
| `mobile_fraction` | a / (pre − c): the fraction that can recover |
| `immobile_fraction` | 1 − mobile fraction |
| `k_per_s`, `tau_s`, `half_time_s` | Rate constant k, τ = 1/k, half time t½ = ln 2 / k |
| `initial_rate_per_s` | Initial recovery rate a·k |
| `fit_r2` | R² of the fit |
| `fit_ok` | 1 = the fit is usable. 0 = no recovery (a ≤ 0) or t½ longer than the observation, so the fitted numbers are left empty (use `final_recovery`) |
| `D_um2_per_s` | For a circular bleach spot, a reference diffusion coefficient D ≈ 0.224 · r² / t½ (Soumpasis 1983); only meaningful when diffusion alone sets the recovery |

## Saving

From the **FRAP 측정** menu:

- **요약 저장: 모든 이미지·그룹 CSV + 그래프 (폴더)…** (save summary: all images
  and groups): measures every image with a time axis and writes at once
  - `frap_summary.csv`: one row per image (the numbers above), per group mean /
    sd / sem rows (n = images with a value) and a row for the fit of the
    group's mean curve, then a description of the columns;
  - `frap_group_curves.csv`: each group's mean curve (frame from bleach, time,
    mean, SD, SEM, n, fit);
  - `frap_groups.png` / `.pdf`: group means ± error bars;
  - `frap_summary.png`: mobile fraction, t½ and final recovery per group (bars
    with mean ± error, one dot per image);
  - per image `<name>_frap.csv` (time, the three ROI means, ratio, value and
    fit per frame), `<name>_frap.png` and `<name>_frap_rois.zip`, in per-image
    folders when **파일 › 이미지별 폴더에 나눠 저장** is on.
- **CSV 저장 (현재 이미지)…**: `<name>_frap.csv` (plus `_rois.zip` when saving
  ROIs with measurements is on).
- **그래프 저장 (PNG / PDF / SVG / TIFF)…**: the graph shown in the tab.
- **FRAP ROI 저장 (현재 이미지)…** / **FRAP ROI 불러오기…**: ImageJ ROIs
  (`frap_bleach`, `frap_control`, `frap_background`); loaded ROIs stay where
  they are.

**파일 › 모든 분석 결과 통합 저장** (save all results) writes `<name>_frap.csv`
and `_frap_rois.zip` for every image measured in the FRAP tab and
`frap_summary.csv`, `frap_group_curves.csv`, `frap_groups.png`,
`frap_summary.png` for the set. FRAP ROIs and settings are also kept in the
project file.

## Agreement with ImageJ

ROI means equal ImageJ 1.54f: oval ROIs use the `OvalRoi` mask, rectangles all
their pixels and polygons the `PolygonFiller` rule (sub-pixel coordinates
included). The exponential recovery fit agrees with ImageJ's `CurveFitter`
(Exponential recovery) to within 10⁻⁵ (relative) in its parameters
(`scripts/imagej_reference/compare_frap.py`).
