# 입자 ROI tab (particles: spots, puncta, condensates)

[← Manual index](README.md) · [한국어](../ko/04-particle-roi.md)

Open or close this tab with **Tool › 입자 ROI › 입자 ROI 탭 열기** (Open 입자 ROI tab) in the menu bar. Results are saved from **파일 › 내보내기…** ([Export window](17-export.md)); loads are in the same **입자 ROI** menu.

This tab finds particles (bright spots, puncta, condensates) in one channel
inside each cell from the [세포질 ROI tab](03-cytosol-roi.md), or in the whole
image, and measures them per cell or one particle at a time. Particles are
found on the current Z plane (or MIP) and timepoint and are found again
whenever the ROIs or settings change.

## 1. 입자 ROI 추출 (Particle extraction)

1. Tick **이 이미지에서 입자 ROI 정의** (Define particle ROIs in this image).
2. **채널** (Channel): the particle channel.
3. **찾을 영역** (Search region):
   - **세포질 (핵 제외)** (cytosol, without the nucleus),
   - **세포 전체** (whole cell),
   - **이미지 전체 (세포 ROI 없이)** (whole image, no cell ROIs needed;
     preselected for images without cell ROIs).
4. **검출 자동화** (automatic detection) switch and **검출 방식** (detection
   method) pop-up: **자동 (유의성)** (automatic, significance; default since v0.65),
   **점 모양 강조 (작은 점 많을 때)** (spot emphasis, for many small spots) or
   **threshold**; only the chosen method's settings show.
   - **자동 (유의성)** (v0.65): on the smoothed image minus its background
     (Gaussian 2.8 µm), the noise σ comes from the lower half of the values
     (particles only add to the upper half) and a peak k σ above the median is
     a particle seed. Particles reach down to k/2 σ (covering the whole
     particle), touching ones are split only where the valley between them is
     3 σ deep, pieces smaller than half a diffraction spot (about 0.5 µm
     across) are dropped. k follows the **image area and the smoothness of its
     noise**: the expected number of noise peaks taken for particles in one
     image is **허용 노이즈 입자** (allowed noise particles, default 0.5; Euler
     characteristic of a Gaussian field), so a larger image gets a larger k.
     The k used is always shown. On a real TCF fluorescence image (1464 ×
     1464) the former automatic mode found 1 900 particles, mostly noise; this
     one finds 116 (ParticleTracker 128).
     - **허용 노이즈 입자** (slider + field): larger finds dimmer particles.
     - **입자 기준** (particle criterion): the criterion in use (default =
       statistical / user: date, channel, scope) and **기준 잡기…** (set
       criterion). A user criterion replaces the allowed noise particles; ↺
       goes back to the default. See [Particle criterion](#particle-criterion).
   - **점 모양 강조**: the former automatic mode. Spot centres where the
     scale-normalised Hessian (high for round spots, not for cell or nucleus
     edges) and the background-subtracted intensity both exceed the cell's
     median + k × MAD, each grown by watershed down to 30 % of its peak.
     - **자동 민감도 (k)** (default 3): smaller finds dimmer spots.
     - **입자 지름** (particle diameter, default 0.4 µm; under 세부 설정 while
       검출 자동화 is on): the filter scale. An edited value gets **· 수정됨**
       and ↺. Images without a pixel size are taken as 0.1 µm/px.
   - **threshold**: pixels at or above the **수동 threshold** value
     (slider or the number field beside it) in every cell, split into 8-connected particles (like
     ImageJ Analyze Particles).
5. **최소 입자 크기** (Minimum particle size, px): smaller particles are dropped.
6. **이미지에 입자 경계 표시** (Show particle outlines): pixel ROIs in magenta,
   iso-contours in orange.

### Particle criterion

The statistical default cannot know where "a particle" starts in every
experiment, so you can pick it from borderline candidates (v0.65). The first
time **이 이미지에서 입자 ROI 정의** is switched on with 자동 (유의성) and the
channel has no criterion, the app asks whether to set one first (**기준 잡기** /
**기본 기준으로 검출**). **입자 기준 › 기준 잡기…** sets it again at any time.
Three steps replace the tab's settings:

1. **밝기** (brightness): nine candidates of a permissive run (seeds ≥ 2σ)
   with nothing brighter around them, faint → bright (3σ → 15σ, log steps),
   as tiles sharing one display range and as numbered boxes on the canvas.
   Click the faintest one that is still a particle; it and the brighter ones
   get a ✓.
2. **크기** (size): nine candidates at least that bright, small → large (half-max
   area); click the smallest particle.
3. **적용** (apply): the new criterion (brightness ≥ the picked SNR × 0.98, size
   ≥ the picked half-max area), the particle count before → after, and the
   images it is used for: all images with that channel name, the same group
   only, or this image only. **기준 적용** removes the boxes and detects again.

If all nine are particles (or none is), **더 흐린 / 더 밝은 후보** (smaller /
larger in the size step) picks nine others. Brightness is in noise σ, so it
means the same on images with another exposure. Criteria are saved in the
project per channel name (`particle_criterion`); threshold and spot-emphasis
images are not changed.

### Shape from iso-intensity contours

**형태는 등강도선으로 측정 (서브픽셀)** (Measure shape on iso-contours,
sub-pixel; on by default) with **레벨** (Level, default 0.5 = half maximum):
the shape values (perimeter, circularity, solidity, AR, roundness, Feret,
ellipse, centroid, equivalent diameter, NND) come from each particle's
sub-pixel outline at background + level × (peak − background) instead of
its pixel edges. Background = median of the free pixels within 3 px of the
particle in its cell; peak = the particle's maximum after a 0.7 px Gaussian.
Round particles then really read round (solidity ≈ 1). Turn it off to get
exactly the ImageJ Analyze Particles values.

### Which pixels intensities use

**강도 측정 ROI** (Intensity ROI):

- **픽셀 ROI** (Pixel ROI, default): the particle's pixels, as ImageJ Analyze
  Particles.
- **등강도선 ROI** (Iso-contour ROI): the pixels whose centres lie inside
  the iso-contour at the same level (how ImageJ masks a polygon ROI). Applies
  to the particle and rest regions, per-particle rows, the partition
  coefficient and the [강도 측정 tab](09-intensity.md)'s logic regions.

### Several images

> Since v0.59 the saves below are picked in **파일 › 내보내기…** (Export), kind **입자 ROI**, instead of a menu ([Export window](17-export.md)). The files written are the same.

- **이 설정을 모든 이미지에 적용** (Apply these settings to all images): the
  same channel (by name) and method for every image.
- Saving / loading particle ROIs: **입자 ROI › 입자 ROI 저장 (현재 이미지)…**
  saves them and **입자 ROI › 입자 ROI 불러오기…** (or **파일 › 불러오기**) opens them again.
  `<name>_particles.zip`, one ImageJ ROI per particle (`partCCC-NN`, outlines
  on the pixel edges so ImageJ's mask equals the particle; the settings are
  stored in the ROI properties). The iso-contours are saved next to it as
  `<name>_particles_contour.zip`.

## 2. 측정 (Measurement)

### 세포별 (입자 영역 합) — per cell

One row per cell (or `image` in whole-image mode) and region, with the
number of particles:

- **입자** (Particle): all particle pixels of the cell together.
- **입자를 뺀 나머지** (Rest): the search region minus the particles
  (`cyto - particle` or `cell - particle`; `image - particle` for the whole
  image).

Files: `<name>_particle_intensity.csv`, `particle_intensity.csv`.

### 입자마다 (형태·분배계수) — per particle

One row per particle (`partCCC-NN`), with area always included and these
checkboxes (hover over each for its definition):

| Checkbox | Value |
|---|---|
| 중심 X, Y | Centroid |
| 둘레 | Perimeter |
| 원형도 | Circularity = 4π·area / perimeter² (1 = circle) |
| Solidity | Area / convex hull area (1 = no concavities; low = merged droplets or irregular aggregates) |
| 종횡비 (AR) | Major / minor axis of the fitted ellipse |
| Roundness | 4·area / (π·major²) |
| Feret 지름 | Feret, MinFeret, Feret angle |
| 타원 (장·단축, 각도) | Fitted ellipse major, minor, angle |
| 등가 지름 | Equivalent diameter 2√(area/π) |
| 최근접 입자 거리 | Nearest-neighbour distance to another particle centroid in the same cell (or image) |
| 분배계수 | Partition coefficient per channel = particle mean / mean of the rest of the cell's search region (dilute phase; raw values, no background subtraction) |

plus the per-channel intensity values (Mean, IntDen, …). Values match ImageJ
1.54f Analyze Particles when iso-contour shape is off. Rows also carry
`shape_outline` and `shape_area_um2` when iso-contour shape is on.

Files: `<name>_particle_shape.csv`, `particle_shape.csv`.

### Summaries per image and group

After **모든 이미지 측정** (Measure all images) the table's view selector
offers **요약: 이미지별** (Summary per image) and **요약: 그룹별** (Summary per
group): one row per image or group (and region, per cell mode) and parameter
with `n` (particles or cells), `mean`, `sd` (n − 1), `min`, `max`; group rows
add `n_images`. Saving writes `<suffix>_summary_image.csv` and
`<suffix>_summary_group.csv`. Groups are set in the image list
([Groups](01-getting-started.md#groups)).

The measurement table itself (auto update, channel values, saving) is
described in [the measurement table](09-intensity.md#the-measurement-table).

## Tips

- With 자동 (유의성), if dim particles are missed or noise is picked up, set a
  criterion with **기준 잡기…** or change **허용 노이즈 입자**. Spot emphasis uses
  **자동 민감도 (k)** and **입자 지름**.
- Use **수동 threshold** when you need exactly the same intensity cut-off
  across images.
- For condensate morphology, keep iso-contour shape on and report the level
  used (see the Methods statement in the repository README).
