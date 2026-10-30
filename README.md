# cytosol-analysis

Microscopy image-based cytosol ROI determination and analysis.

**User manual** (one page per feature): [English](docs/en/README.md) ·
[한국어](docs/ko/README.md)

## Methods statement

For a paper's Methods section (update this sentence whenever an analysis
feature is added; keep the bracketed words only when the 입자 ROI tab's
**강도 측정 ROI** was set to **등강도선 ROI**, and change 50% to the
**레벨** used):

> Line intensity profiles, per-cell colocalization (Pearson's, Spearman's
> and Kendall's correlations, Manders' coefficients with Costes' automatic
> threshold, Li's ICQ and Costes' significance test), and mean intensities of
> cell, nucleus, cytosol and intracellular particle ROIs (and of cytosol bands
> of equal Euclidean distance from the nucleus) and particle shape
> descriptors (area, perimeter, circularity, solidity, aspect ratio, roundness,
> Feret's diameters and fitted ellipse) were analysed with the
> algorithms of the ImageJ Plot Profile/RGB Profiler, the Fiji Coloc 2 plugin
> and ImageJ's Measure and Analyze Particles functions, respectively, with
> particle intensities measured on the particles' pixel ROIs [iso-contour
> mode: within those contours] and shape descriptors computed from sub-pixel
> iso-intensity contours (marching squares) at 50% of each particle's height
> above its local background;
> particles were detected within each cell ROI as spots whose scale-normalised
> Hessian response (as in the FeatureJ Hessian plugin) exceeded the cell's
> median + 3 × MAD, and delineated by marker-controlled watershed (as in the
> MorphoLibJ plugin) on the background-subtracted image (grey opening, as in
> ImageJ's Subtract Background) down to 30% of each spot's peak (or by a
> manual threshold); FRAP recovery was quantified as the mean intensity of
> the bleached region relative to an unbleached reference region (a
> neighbouring condensate whose intensity varied least over the series, or
> the unbleached part of the bleached condensate), each after subtracting a
> background region of the bleach region's size (double normalisation,
> Phair et al., 2004) and scaled to 1 before and 0 right after bleaching
> (full-scale normalisation; for group means, of each group's mean curve), with ROI means as in ImageJ's Measure function and
> the ROIs moved on every frame by the lateral drift found by sub-pixel
> cross-correlation with a key frame (as in Fiji's Correct 3D Drift plugin),
> and fitted with ImageJ's Curve Fitter "Exponential recovery" function
> y = a(1 − e^(−kt)) + c to give the mobile fraction a/(1 − c) and the
> half-time t½ = ln 2/k.

## Reading raw files

`cytosol.io.read_image(path)` opens Tomocube `.TCF`, Zeiss `.czi`,
Olympus/Evident `.oir` and `.tif`/`.tiff` files and returns an `Image` with
`data` shaped `(C, Z, Y, X)`, channel names, voxel size in micrometers, the raw
metadata and `ranges`: per channel the value range the file can hold (0 to
the detector maximum), read from the metadata.

| Format | Reader | Notes |
|---|---|---|
| TCF (HDF5) | `h5py` | `modality='3D'` (default) or `'2DMIP'` gives refractive index (stored uint16 / 10000); `'3DFL'` / `'2DFLMIP'` gives fluorescence per channel. HT and FL have different XY pixel sizes and Z ranges (`Data/3DFL` `OffsetZ`). |
| CZI | `czifile` | `scene=` selects a scene in multi-scene files. Frame times come from the `TimeStamps` attachment; bleach regions and events (`metadata['bleach_rois']`, `metadata['bleach']`) from the experiment XML and the `EventList` attachment. |
| OIR | `oirfile` | Stimulation (bleach) regions, laser and pre-bleach frame count (`metadata['bleach_rois']`, `metadata['bleach']`) from the `stimulationParam` and synchronized-acquisition XML. |
| TIFF | `tifffile` | ImageJ hyperstacks and OME-TIFF keep T/Z/C, pixel size, channel names and colors (ImageJ LUTs, OME `Color`). A plain multi-page TIFF is a Z stack; an RGB TIFF gives channels R/G/B. |

Value range per format: CZI `ComponentBitCount`, OIR bits per sample,
OME-TIFF `SignificantBits` (else the TIFF `BitsPerSample` / stored integer
type), TCF fluorescence the stored integer type (uint8/uint16), and TCF RI the
`RIMin`–`RIMax` recorded in the file. Float TIFFs without metadata use 0 to
the data maximum.

```
pip install -r requirements.txt
python scripts/inspect_file.py FILE --out format-check/
```

`inspect_file.py` prints key metadata as JSON and writes preview PNGs
(mid-slice, MIP and XZ section for TCF; per-channel MIP and composite for CZI/OIR).

## Colored images with a scale bar

```
python scripts/render_image.py FILE --out figures/
```

Writes one PNG per channel plus a composite, at the original pixel size,
with a scale bar burned in. The bar length is picked automatically from the
pixel size in the file (about 20% of the width, rounded to 1/2/5/10/20/25/50…
µm) and channel colors come from the file itself: ZEN display colors for CZI,
the FluoView LUT for OIR, and the HTX channel colors for TCF (RI is gray).
For TCF both the HT (`3D`) and fluorescence (`3DFL`) volumes are rendered as
max projections by default.

Options: `--scale-um 10`, `--scale-position "upper left"`,
`--color 0=magenta --color DAPI-T3=#0050FF`, `--z mid` or `--z 12`,
`--modality 2DMIP`, `--no-labels`, `--low/--high` contrast percentiles.

From Python:

```python
from cytosol.io import read_image
from cytosol.render import render
render(read_image('cells.czi'), 'figures/', prefix='cells', scale_um=10,
       colors={'DAPI-T3': 'blue'})
```

## Cytosol Viewer (desktop app)

A GUI for working on a whole set of images at once:

- **Menus**: **파일** (File) holds projects (new / open / save; `.cyproj`:
  image paths relative to the project plus all ROIs, crops, groups, LUTs,
  tab and measurement settings, the figure layout and the work log, so a
  project continues where it was left), **불러오기** (load files or a folder;
  projects, images, cell / particle / crop / line ROIs, LUT presets, marker
  settings and `image_groups.csv` are recognised automatically and attached to
  the matching open image; opening a project asks whether to load everything
  or only its settings), **일괄 분석** (batch analysis per group, see below),
  **모든 분석 결과 통합 저장** (save all results), the
  work log (every lasting status message with time and image) and the
  settings (mouse sensitivity). Next to it every feature has its own menu
  (LUT, 마커, Crop, 세포질 ROI, 입자 ROI, 강도 측정, Coloc 2, 라인 프로파일, 스택,
  이미지 정보, Figure) that opens its tab on the right and holds its own saves
  and loads. The **LUT** and **이미지 정보** tabs are always there; the marker
  settings are fixed at the bottom of the LUT tab.
- **Layout**: the image list (left) and the tools (right) keep their width
  and only the preview grows with the window; pane borders can be dragged and
  the widths are remembered. Rows of buttons and check boxes reflow to the
  pane width, and long image names wrap in the list.
- Zoom with `Cmd`/`Ctrl` + drag up/down or `]` / `[`; the mouse wheel moves
  through time on time series and scrolls otherwise.
- Add TCF / CZI / OIR / TIFF files with **파일 › 불러오기** or by dragging files or folders
  onto the window. **그룹 지정…** puts the selected images in a group you name
  (the name offered is what their file names share without the trailing
  number: abc, abc_0001, abc_0002 → abc); **자동 그룹** groups every image
  (or the selected ones) by that rule; **그룹 이름 변경…**, **그룹 해제**. The
  list shows each group as a folder you can expand or collapse, and
  selecting a folder selects its images. Measurement rows
  get a `group` column, and saving measurements or exports writes
  `image_groups.csv` (image, image ID, group), which loading that folder
  again reads back. A TCF becomes one entry with HT and FL aligned on the HT
  grid (channels `RI`, `CH0…`): FL is resampled by pixel size around the shared
  image center plus a small automatic registration (at most 2 µm), and in Z
  from `3DFL/OffsetZ` (the center of the FL stack measured from the bottom of
  the HT volume). Turn off **TCF: HT와 FL을 정렬해 한 이미지로** to get HT and
  FL as two entries instead (`read_image(path, aligned=True)` from Python).
- **Time series** (TCF, CZI, OIR with a T axis, together with Z): a **T** slider
  under the image. The image follows the slider while it is dragged (each
  timepoint is read in the background, so the window does not freeze);
  histograms and the line profile follow when it stops. TCF fluorescence is
  read only for the slices a plane needs; in MIP view the drag shows a quick
  FL projection (taken before resampling) and the exact MIP replaces it on
  release, so analysis always uses the exact values. Files with a **Z stack**
  also read ahead every timepoint of the current Z (or MIP) once an image is
  shown (up to 1.5 GB; the status bar shows the progress), so scrubbing only
  redraws; single-plane time series keep just the last few planes to save
  memory. **Right-drag on the image** moves through T (left/right) and Z
  (up/down) at once, updating the image while it moves (MIP switches to
  slices once the drag goes up or down); the middle button still pans. Export
  writes every timepoint (RGB TIFFs become T-frame stacks with the time stamp
  on each frame, the raw stack a TZCYX hyperstack) unless
  **타임시리즈는 모든 시점 저장** is off. **타임시리즈 RGB 형식** writes those RGB
  outputs as a TIFF stack, an **MP4** movie (H.264, one frame per timepoint at
  the chosen fps, ffmpeg bundled via imageio-ffmpeg) or both; the raw stack
  stays TIFF.
- **라인 프로파일 tab** (like ImageJ's RGB Profiler): press **라인 프로파일 (선 그리기)**
  above the image and drag a line (Shift: horizontal, vertical or 45°). The tab
  plots each channel's raw intensity along the line against distance in µm, in
  the channel colors, for the current Z (or MIP) and timepoint, and follows
  Z/T/LUT changes. Line width (pixels averaged across the line), hide channels
  hidden in the LUT, per-channel 0–1 normalization; **CSV 저장** (distance + one
  column per channel) and **그래프 저장** (PNG/TIFF 300 dpi, PDF, SVG).
  The samples are ImageJ's (Plot Profile, which RGB Profiler plots per
  channel): bilinear interpolation, round(length) + 1 points, width > 1
  averaged across the line as ImageJ straightens it; identical values for
  width 1, within 4e-5 relative for wider lines.
- **Coloc 2 tab** (Fiji's Coloc 2, ported line by line from its source):
  colocalization of two channels in each cell ROI of the 세포질 ROI tab, per
  region (`세포 전체`, `세포질 (핵 제외)`, `핵`), `선택한 세포만` or
  `이미지 전체 (ROI 없음)`, on the current Z plane or the whole Z stack (the 2D
  ROI through every slice, as Coloc 2 does with a 2D mask on a stack), for the
  current or every timepoint. Same options as the plugin: threshold regression
  (Costes / Bisection), Li histograms, Li ICQ, Spearman, Manders, Kendall tau,
  2D intensity histogram, Costes significance test (PSF, randomisations), and
  the same values, warnings and plots (2D histogram with the regression line
  and thresholds, Li plots, shuffled image). **현재 이미지** / **모든 이미지**
  run it, a row of the results table shows that cell's plots and values and
  selects the cell in the image. **CSV 저장** writes one row per cell, region
  and timepoint with every value; **모든 이미지 CSV**, **그래프 저장** and a
  **PDF** report (like the plugin's) are there too, and `내보내기` adds
  `<name>_coloc2.csv` per image and `coloc2.csv` for the set. From Python:
  `cytosol.coloc.run_coloc2(ch1, ch2, mask, Coloc2Settings(), ValueType.for_dtype(ch1.dtype))`.
  Checked against the Coloc 2 code itself (`scripts/imagej_reference`): every
  value except the Costes randomisation agrees to about 1e-10 relative; the
  Costes test is random in both, and the shuffled mean/SD agree within that
  spread.
- **Intensity measurement** (ImageJ Measure on every cell ROI) sits in three
  tabs, each with its own table, all-image run and saving: per cell and
  region, per channel Mean (and optionally StdDev, Min, Max, IntDen,
  RawIntDen) of the raw values on the current Z (or MIP) and timepoint, for
  the channels checked under **측정할 채널** (kept by channel name, per tab,
  saved in projects). The
  table follows every ROI edit, plane change and setting; a row selects its
  cell. **CSV 저장** writes the current image's rows plus `<name>_RoiSet.zip`,
  the particle/region ROIs it used and `<name>_image.png` with the outlines;
  **모든 이미지 측정 + 저장** measures every image (optionally every
  timepoint) and writes the set's CSV plus each image's files in its
  `<name>_<ID>` folder (`내보내기` adds all three CSVs too).
  - **세포질 ROI tab**: `cell`, `nucleus` and `cytosol` regions →
    `<name>_cell_intensity.csv` / `cell_intensity.csv`.
  - **입자 ROI tab** (v0.16, moved out of 강도 측정): particle ROIs and the
    `particle` region and the rest of the region they were found in
    (`cyto - particle` or `cell - particle`), with the particle count per cell
    → `<name>_particle_intensity.csv` / `particle_intensity.csv`. **찾을 영역 →
    이미지 전체** (v0.17) finds and measures particles over the whole image
    with or without cell ROIs (one row `image`, regions `particle` and
    `image - particle`; preselected for images without cell ROIs); with
    **이 설정을 모든 이미지에 적용** and **모든 이미지 측정** the whole set gets
    the same extraction and measurement. Whole-image particles still split by
    the 강도 측정 logic (`cyto & particle`, `nuc & particle`, `cyto - particle`)
    per cell; checked on the Zeiss sample (12 cells, 4640 particles) that every
    region's pixel count and channel means match a direct numpy evaluation and
    that particle pieces crossing cell or nucleus borders go to each side.
    **측정 → 입자마다** (v0.18) gives one row per particle ROI (`particle`
    = its `partCCC-NN` name) → `<name>_particle_shape.csv` /
    `particle_shape.csv`, with checkboxes for: centroid, perimeter,
    circularity (4π·area/perimeter²), solidity (area/convex hull area), aspect
    ratio and roundness of the fitted ellipse, Feret/MinFeret/Feret angle,
    ellipse major/minor/angle (ImageJ Analyze Particles definitions),
    equivalent diameter 2√(area/π), nearest-neighbour distance to another
    particle centroid in the same cell (or image), and per channel the
    partition coefficient = particle mean / mean of the rest of the cell's
    search region (dilute phase; raw values, no background subtraction),
    plus the 측정값 checkboxes (Mean, IntDen, …) per particle. Checked against
    ImageJ 1.54f Analyze Particles (`scripts/imagej_reference/compare_shape.py`)
    on random blobs and on the Zeiss sample's automatic particles (3497
    particles): area, centroid, perimeter, circularity, solidity, Feret
    values identical, ellipse values within 1e-8. Saved particle ROIs are
    ImageJ traced ROIs, so Measure on them in ImageJ gives the same
    perimeter. Small particles have solidity below 1 even when round (the
    hull runs over pixel corners, as in ImageJ).
    **형태는 등강도선으로 측정** (v0.21, on by default, **레벨** 0.5): the
    shape values (perimeter, circularity, solidity, AR, roundness, Feret,
    ellipse, centroid, equivalent diameter, NND) come from each particle's
    sub-pixel iso-intensity outline instead of its pixel edges: marching
    squares on the particle channel at background + level × (peak −
    background), background = median of the free pixels within 3 px of the
    particle in its cell, peak = the particle's maximum after a 0.7 px
    Gaussian; the outline stays in the particle's cell and out of other
    particles (touching ones keep their watershed border). Intensities,
    `area_px`/`area_um2` and the partition coefficient stay on the pixel
    ROIs; the rows add `shape_outline` (`iso-contour 0.5`) and
    `shape_area_um2` (area inside the outline). Off = ImageJ Analyze
    Particles values as before. On synthetic blurred particles of known
    shape (PSF σ 1 px, Poisson noise, 30 placements each) round particles
    gave solidity 1.00 (pixel edges 0.89–0.94) and circularity/AR spread
    about 10× smaller; elongated particles a few pixels wide still read
    rounder than they are (PSF blur, any outline). The outlines are drawn in
    orange and saved next to the pixel ROIs as `<name>_particles_contour.zip`
    (sub-pixel polygon ROIs `partCCC-NN`, properties `outline = iso_contour`,
    `contour_level`); folder loading links that file without reading it as
    particles or cells.
    **강도 측정 ROI: 픽셀 ROI / 등강도선 ROI** (v0.22, default 픽셀 ROI):
    with 등강도선 ROI every intensity that uses particles (입자 / 입자를 뺀
    나머지 per cell, 입자마다 rows and partition coefficient, the 강도 측정
    tab's logic regions) is measured in the pixels whose centres lie inside
    each particle's iso-contour at the same **레벨** (ImageJ's polygon-ROI
    mask); a particle without a contour keeps its pixels. Rows then carry
    `particle_intensity_roi` / `intensity_roi` = `iso-contour 0.5`, and
    `area_px` is that ROI's pixel count. Both ROI files are saved as above.
    **Summaries** (v0.19): 모든 이미지 측정 adds the views **요약: 이미지별** /
    **요약: 그룹별**, and saving writes `<suffix>_summary_image.csv` and
    `<suffix>_summary_group.csv` (plus `<name>_<suffix>_summary.csv` per
    image): one row per image or group (and region in 세포별 mode) and
    parameter with `n` (particles or cells), `mean`, `sd` (n − 1), `min`,
    `max`; group rows also give `n_images`. Positions, angles and the time
    point are left out.
  - **강도 측정 tab**: regions set by logic over `cell`, `nuc`, `cyto` and
    `particle` (`cyto - particle`, `cell & particle`, `(cell - nuc) | particle`;
    `&` intersection, `|` union, `-` difference), shown filled in cyan on the
    image and saved as `<name>_regions.zip` (one ImageJ ROI per cell and
    region, `rgnCCC-R`, the expression in its `region` property) →
    `<name>_intensity.csv` / `intensity.csv`. Below it, **핵 → 세포막 등거리
    띠** (`cytosol/radial.py`): every cytosol pixel of a cell with a nucleus
    gets its distance from the nucleus, relative (d_nuc / (d_nuc + d_edge),
    Euclidean distance maps; 0 = nucleus edge, 1 = cell edge) or in µm from
    the nucleus outline; the chosen range is cut into n equal bands (default
    10) measured per cell and band (same values as Measure, plus particles
    with their centre in the band, particle area fraction and particle mean)
    → `<name>_bands.csv` / `bands.csv`, and a graph with any two measured
    columns as axes (cells grey, mean ± SD per band red).
- **입자 ROI** in each cell's cytosol (or whole cell) of one channel, with a
  minimum size: **자동 (점 검출)** (v0.14)
  finds spot centres where the scale-normalised Hessian's smaller curvature
  (high for round spots, not for cell or nucleus edges) and the
  background-subtracted intensity both exceed the cell's median + k × MAD
  (**민감도 k**, default 3; **입자 지름** default 0.4 µm sets the scale), then
  grows each spot by watershed over the background-subtracted image (grey
  opening) down to 30 % of its own peak, so touching spots stay apart and dim
  spots next to bright ones are kept. Picked over per-cell Otsu, top-hat +
  Otsu, ParticleTracker's DoG + median/MAD, LoG and local thresholding on
  synthetic cells with known spots (object F1 0.60 vs 0.37–0.57, pixel Dice
  0.75 vs 0.45–0.71, precision 0.98). **수동 threshold** keeps the pixels at
  or above one value in every cell, split into 8-connected particles
  (Analyze Particles). Particle files from v0.13 (per-cell Otsu, as
  `setAutoThreshold("Otsu dark")` with the cell's ROI) still reproduce. **이 설정을 모든
  이미지에 적용** uses the same channel (by name) and method on every image.
  `<name>_particles.zip` holds one ImageJ ROI per particle (`partCCC-NN`,
  outlines on the pixel edges so ImageJ's mask is exactly the particle; the
  settings are stored in the ROI properties). Folder loading pairs a particles
  zip with its image (a regions zip is linked, not read as cells). Checked
  against ImageJ 1.54f
  (`scripts/imagej_reference/compare_intensity.py`): per-ROI Otsu thresholds,
  pixel counts, min and max identical and Mean/StdDev within 1e-6 relative on
  8/16/32-bit data and the Zeiss sample; saved particle ROIs give ImageJ masks
  identical to the particles.
- **마커 tab**: size marker (scale bar) and time-series marker (time stamp).
  Each has on/off, text on/off, font size, marker length/thickness, text-marker
  gap, edge margin, position and color; the time stamp also has the unit
  (auto, s, min, h, hh:mm:ss, mm:ss, frame), decimals, prefix, a time offset
  and an optional progress bar. Used by the preview and every TIFF export.
  **Bleach ROI**: the bleach regions a Zeiss CZI records (FRAP etc.; from
  the executed bleach events, else the regions marked for bleaching) drawn as
  outlines: **화면에 표시** shows/hides them on the preview, **저장하는 RGB
  이미지에 선 포함** burns them into exported RGB TIFFs / MP4s (never into the
  raw stack); color, line width and region names are adjustable. Every export
  also writes them as ImageJ ROIs, `<name>_bleach_rois.zip` (ovals for
  circles, sub-pixel polygons otherwise), which folder loading attaches back to
  the image.
- **이미지 정보 tab**: the acquisition metadata as two tables, copyable and
  savable as CSV (also written as `<name>_info.csv` by 모든 분석 결과 통합 저장),
  plus the raw metadata (CZI/OIR XML, TCF attributes). Per channel:
  fluorophore and its Ex/Em, laser wavelength, laser intensity (the stored
  setting, %), the laser line's rated maximum and the nominal power (maximum ×
  setting; the power at the sample is not in any file), exposure time or pixel
  dwell / frame time / averaging, detector, detector voltage (gain), digital
  gain, offset, detection range, pinhole (µm and AU). Generally: size, pixel
  size and field of view, Z step, frame interval and duration, objective (NA,
  immersion), instrument and software, and for CZI the bleaching (laser and
  intensity, iterations, duration, number of bleaches, the frames that follow
  each bleach, pre-bleach frames) and each bleach ROI's position and size. CZI
  is read fully; OIR (laser %, PMT HV/offset/gain, pinhole, dye, scan speed),
  TCF (FL Ex/Em, light intensity %, exposure) and TIFF (ImageJ / OME
  metadata) give what they store.
- **Per-channel LUT** with a live preview: show/hide, color, min/max (slider,
  number or histogram), gamma, `Auto` (0.5–99.8 percentile) and `Min/Max`
  (the current image's data min–max). The sliders and histogram span the
  file's value range from its metadata (e.g. 0–4095 for 12-bit, 0–255 for
  8-bit), shown under the histogram; the starting min/max is still the
  automatic percentile range.
- **Z**: a vertical slider left of the image (bottom = first slice, with the
  slice number and height in µm), or **MIP**. TCF files are read lazily: a
  slice is one HT plane plus the few FL slices around it (the stored 2DMIP for
  MIP), and the whole volume is only loaded for the stack tab and exports and
  freed again afterwards, so browsing Z and T stays quick and each open TCF
  costs a few hundred MB instead of its whole volume.
- **스택 tab** (Z-stack projection; the image area shows the result while it is open):
  - 2D projection of a Z range (or the selected crop): max, mean, sum, min, SD, median.
  - 3D projection: the volume turned about the Y (left–right) or X (up–down)
    axis by any angle, brightest point or mean along the view. Z spacing is
    automatic (voxel Z / pixel size from the metadata) or a manual value in µm.
    The preview is subsampled for speed; saving can use full resolution.
    The 3D preview is built once per image, Z range, crop, preview size and
    timepoint (the stack reduced to the preview size, LUT-mapped to 8 bit and
    resampled to cubic voxels) and the full volume is then released; turning
    it only re-projects that structure (shear-warp, ~0.05 s). Min/max/gamma
    changes reach it with **새로고침 (LUT 반영)** (highlighted when the LUT
    changed); color and show/hide apply at once.
  - LUT: starts from the LUT tab's LUT; with **LUT 탭과 연동** on, changes go
    both ways (a sum's range is scaled by the slice count), off gives the
    projection its own LUT.
  - Saving: the current projection (RGB with markers + float32 ImageJ stack,
    optionally every timepoint) or a 3D rotation series as a TIFF stack; choose
    **MP4** in the save dialog to get a movie instead (frame rate in the tab).
- **Crop** regions per image: press `Crop 추가 (드래그)` and drag on the image;
  repeat for more regions. Each region is listed, numbered on the image, can be
  previewed alone, deleted, or copied to every image with the same pixel size.
- **Batch LUT**: `전체 이미지에 적용` on a channel copies its LUT to the same
  channel of every loaded image (matched by channel name; by index only between
  files of the same type and channel count). LUTs can be saved and loaded as JSON presets.
- **Batch TIFF export** (`모든 이미지` or `현재 이미지만`), with the current LUTs
  applied. Scope: the whole image (`<name>_full_*`) and/or every crop region as
  its own files (`<name>_crop1_*`, `<name>_crop2_*`, …). For each:
  - composite RGB with the LUTs and scale bar (8-bit, µm calibration),
  - optional per-channel RGB,
  - an ImageJ hyperstack of the original values for all Z, carrying the channel
    LUTs, display ranges and µm calibration, ready for measurement in Fiji.
- **이미지별 폴더에 나눠 저장** (on by default, an option in the 파일 menu shared by
  every folder save): each image's files go into their own subfolder
  `<chosen folder>/<name>_<image ID>/`.
- **모든 분석 결과 통합 저장** (File menu, Ctrl+Shift+E): for every image, one folder
  holding its TIFFs, crop / cell / particle / region ROIs and measurement
  CSVs, plus the combined tables and `project.cyproj` at the top.
- **일괄 분석** (batch analysis, File menu, Ctrl+B): after loading and
  grouping a set of images, tick the groups and the analyses (cell ROI
  detection, particle ROI detection, cell ROI / particle / logic-region
  intensity, nucleus → membrane bands, Coloc 2, FRAP); they run one after the
  other on every image of those groups with each tab's current settings
  (images that already have ROIs are left alone unless asked). A results
  window lists per image the cell / particle counts, measurement rows, Coloc 2
  ROIs and FRAP mobile fraction / t½; double-clicking opens the image in that
  analysis's tab to fix it, and **다시 측정** measures again keeping the edited
  ROIs. **일괄 분석 결과 저장** saves only those analyses of those images
  (per-image folders, combined CSVs and summaries, `batch_summary.csv`,
  `batch_settings.json`); **일괄 분석 설정 저장 / 불러오기** keeps the analysis and
  group choice plus the tab settings as JSON (`format: cytosol-viewer-batch`)
  to run the same pipeline on another image set. Opening a project asks
  whether to load everything (images, ROIs, results) or only its settings
  (pipeline) for the images already open.

### Image ID and folder loading

Every image gets an ID like `A9F3-2596-73B6`, derived from what the microscope
wrote into the file, so it survives renaming and copying: the TCF `UniqueID`,
the CZI file GUID, the OIR acquisition time plus channel UUIDs, the OME-TIFF
`UUID`, or (for anything else) a hash of the file content. It is shown under the
preview and in the file list tooltip (`cytosol/imageid.py`).

- Every export carries it: TIFFs in their ImageJ `Info` and `Properties`
  (`CytosolImageID`, plus the original file name as `CytosolSource`; Fiji:
  Image › Show Info), every ROI in a RoiSet in its properties, and the
  measurement CSVs in an `image_id` column.
- **불러오기 (폴더)…** (File menu, Ctrl+Shift+O; dropping a folder does the same)
  scans the folder and its subfolders and pairs files by ID: exported TIFFs are
  listed with their original image; when the original is not there, the best
  export opens in its place (full raw stack first) and keeps the original's ID;
  RoiSets are loaded into the image with their ID. ROIs saved before IDs existed
  are matched by file name (`<name>_RoiSet.zip`).
- Loading cell ROIs into an image that already has cells asks before replacing them.

### 세포질 ROI tab (cell / cytosol ROIs)

1. **채널 역할**: pick the nucleus channel (or `없음` when there is none) and the
   background-signal channel, i.e. the dim channel that fills the cytoplasm when
   its LUT is pushed very bright.
2. **ROI 검출**: the background channel is saturated at `배경 포화값`
   (`자동` = median of the smoothed channel; tick `검출용 합성 이미지 보기` to see
   exactly what the detector sees and lower the value until each cell is one solid
   blob), merged with the nuclei, and split into cells by a watershed seeded from
   each in-focus nucleus, so every cell gets one nucleus. Touching nuclei are split
   first. Without a nucleus channel, cells are split along the dark cell-cell
   borders instead (as in the mito-tracking project's `cell_roi.py`).
   Cells cut by the image frame are, by default, cut again along a new border
   `안쪽 경계 여백` inside the frame, so no ROI runs along the frame
   (`제외` drops them, `그대로 두기` keeps them as they are).
   **핵 threshold / 세포 threshold**: by default Otsu picks them (`자동` ticked,
   the value in use shown in the field); untick `자동` to set either by hand
   (spin box or slider). `배경 포화값` works the same way.
   The nucleus threshold is in nucleus-channel values (lightly smoothed), the
   cell threshold in background-channel values (cells brighter, gaps darker;
   keep it below `배경 포화값`). `threshold 영역 미리보기` paints what passes
   each threshold (yellow: cell, blue: nucleus) in the main view and follows
   the sliders live while you drag them; changing a manual threshold turns it on.
   The values used are shown after detection. `모든 이미지` runs the
   same settings on every loaded image, matching channels by name.
   The status bar also gives the detection time (about 0.7 s for a
   1024 × 1024 two-channel image).
   **Size ranges** `세포 크기` / `핵 크기` (min – max, with log-scale sliders;
   max 0 = no limit): cells and nuclei outside them are dropped. With
   `붙은 세포를 크기 범위에 맞게 나누기 · 합치기`, regions above the maximum are cut
   along the cell-cell valleys into the fewest pieces that fit (seeds at
   distance-map maxima or k-means centres, compact watershed; a cell's nucleus
   stays whole in one piece) and regions below the minimum are merged with the
   neighbour across the weakest border when the merged size fits better
   (`cellroi.fit_sizes`); nuclei are fitted the same way. Nuclei are drawn
   per seed (`cellroi._local_nuclei`): seeds are areas above a quarter of the
   way from the background to the (Otsu or manual) nucleus threshold; around
   each, the signal is stretched from the local background to the seed's
   bright end and cut at that window's own Otsu value (15 – 60 % of the
   stretch). A result over 2.5 × the image's typical nucleus keeps the image
   threshold's area; seeds the image threshold alone did not find must be
   compact (solidity ≥ 0.85), drop off sharply (outer 1 µm ring < 0.22 on
   their stretch), stand out (≥ 25 % of the threshold's step) and be at least
   half the typical size, so dim nuclei are found and cytoplasmic stain is
   not. Touching nuclei
   are split at distance-map maxima (watershed) and the cut is kept only
   when the shape says two nuclei (`cellroi._split_ok`): a notch (depth
   inside the convex hull ≥ 0.4 µm and 8% of the radius) at both ends of the
   cut, each piece convex (solidity ≥ 0.8) while the pair is not (≤ 0.93), a
   cut shorter than 0.8 × the narrower piece's width, and centres ≥ 0.6 × the
   sum of the pieces' radii apart; otherwise the pieces are joined again, so
   kidney- or bean-shaped nuclei stay whole. With
   `가는 목으로 붙은 세포 자르기` (`cellroi.cut_necks`), rings of equal geodesic
   distance are grown out from each cell's nucleus (from the widest point
   without one); where the front squeezes through a gap of at most `목 폭`
   into a part ≥ 2 × wider and at least the minimum cell size, the part is
   cut off along the darkest path of the signal across the neck (marker
   watershed in a band around it); without such a neck, the shortest chord
   between two deep concave points of the outline (depth from the convex
   hull) is cut under the same conditions. Cut-off parts become cells
   without nucleus. The editing tool `자르기 (C)` splits cells along a drawn
   line (`CellRois.cut`). `자동 (이미지마다
   추정)` gives each image its own range from one detection without limits on
   it: median area ÷ 4 to × 3 for cells (÷ 20 to × 3 for nuclei, which seed the
   cells), widened to the smallest – largest area left by Tukey fences on log
   area (`cellroi.image_size_range`). With a manual range, 모든 이미지 asks
   whether every image gets the same range or its own estimate.
   **수동 (threshold)** sub-tab: the plain manual mode, kept whatever else is
   added: connected areas at or above the cell threshold are the cells (holes
   filled), the largest area at or above the nucleus threshold inside each is
   its nucleus; only the size ranges and frame handling apply
   (`cellroi.threshold_cells`).
   `실시간 미리보기` reruns the detection in the background after every change
   and draws the result as dashed ROIs; `ROI 검출` keeps it. Hovering over a
   ROI shows its name and area above it.
3. **확인 · 수정**: click a cell to select it (or pick it in the list). With
   `더하기 (A)` / `빼기 (S)` drag a freehand area to add it to or remove it from
   the selected cell; `새 세포 (N)` turns the drawn area into a new cell and,
   with a nucleus channel, finds its nucleus inside it (at the manual nucleus
   threshold, else the one the detection used, else Otsu).
   `Delete` deletes the selected cell, `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo,
   middle-button drag pans in any tool (right-button too on images without T
   or Z). A cell is always one filled piece
   (ImageJ polygon ROIs cannot have holes), so cut from its border.
4. **ImageJ ROI 파일** (세포질 ROI menu): `ROI 저장 (현재 이미지)…` writes a RoiSet `.zip` (ROI Manager › Open)
   or, when saved as `.roi`, one `.roi` file per ROI. Per cell: `cellNNN`
   (whole cell polygon), `nucNNN` (nucleus polygon) and `cytoNNN` (cell minus
   nucleus, a composite ROI). `ROI 불러오기…` (or 파일 › 불러오기) reads `.zip` / `.roi` files back
   for editing. `모든 이미지 ROI 저장` writes one RoiSet per image plus
   `cell_rois.csv` with cell, nucleus and cytosol areas (with
   `이미지별 폴더에 나눠 저장`, each RoiSet and its own CSV go in `<name>/`).

From Python:

```python
from cytosol.cellroi import segment_cells, RoiParams
rois = segment_cells(bg_plane, nucleus_plane, pixel_um, RoiParams(edge_mode='trim'))
rois.save('cells_RoiSet.zip')
```

### Figure 만들기 (figure table)

`Figure › Figure 창 열기…` (`Ctrl+Shift+F`) opens a window
that lays images out as a table with row and column labels:

- **Table**: add, delete and reorder rows and columns; double-click a row or
  column header to edit its label (several lines allowed) and its color
  (right-click for insert/delete). `열 이름을 채널 이름/색으로` names the columns
  after the channels in the current row, in their LUT colors.
- **Cells** show a loaded image with its current LUTs (changes in the main window
  appear when you come back to the figure window): whole image or any crop region,
  the composite of visible channels or any set of channels. `파일…` puts a PNG/TIFF
  file (e.g. an earlier export) in a cell instead. `이 행을 채널별 + Merged로 채우기`
  fills a row with one column per channel plus the merged image.
- **Zoom insets**: drag `확대 영역 그리기` on the cell preview; the area gets a box.
  `표시 방식` chooses where the magnified copy goes: `이미지 안` puts it in the
  chosen corner of the same image at the chosen size; `다른 칸에 따로` shows it in
  its own table cell (`넣을 칸`: any cell, or a new column/row inserted next to the
  image; by default the free cell to the right, else a new column). `이 행 전체에 적용`
  copies the same insets to every same-sized cell of the row (or column); separate
  zoom cells keep the same offset, e.g. a zoom row under the image row.
- **Layout**: black or white background (labels switch to white/black), cell
  borders, cell width and aspect, gap, font and size, scale bars (one length for
  every cell, automatic or fixed, optional inset scale bars and a
  `(Scale bar = … µm)` caption).
- **Export** the whole table as PNG, TIFF (at the chosen DPI, default 300) or as
  PDF / SVG with editable text.

From Python: `cytosol.figure` (`FigureSpec`, `fill_row_by_channels`, `save_figure`).

Run from source: `python -m cytosol.app [files…]`

Build the macOS app: `./build_mac.sh` → `dist/Cytosol Viewer.app`
(set `PYTHON=/path/to/python3.10+` if the system python3 is older).
Package it: `./make_dmg.sh` → `~/Desktop/CytosolViewer-<version>-<commit>_<arch>.dmg` (`_apple silicon` on arm64 Macs, `_intel` on Intel Macs).
The version lives in `cytosol/version.py` (also shown in the window title);
bump it there for a release.

Automatic update on a Mac: `scripts/install_auto_update.sh` installs a launchd
agent (at login and every 30 minutes) that runs `scripts/mac_auto_update.sh`.
When `origin/main` has a new commit it builds the app in a separate worktree
(`~/.cytosol-autoupdate/src`, the clone itself is not touched), runs its
`--selftest`, and only if that passes swaps it into
`/Applications/Cytosol Viewer.app` (after the running app quits; the old one
goes to the Trash as `Cytosol Viewer <version>.app`). It also writes the DMG
to the Desktop and copies the Windows zip of the newest release there; only the
newest DMG and zip it made stay, older ones go to the Trash (`MAKE_DMG=0` /
`GET_EXE=0` at install turn these off). Log:
`~/Library/Logs/CytosolViewer-autoupdate.log`; remove with
`scripts/install_auto_update.sh --uninstall`.

### Windows build

Every push to `main` (and `claude/**` branches) builds the Windows app on
GitHub Actions (`.github/workflows/build-windows.yml`): open the run under the
repository's **Actions → Build Windows app** and download the
`CytosolViewer-<version>-<commit>-Windows` artifact. Unzip it anywhere and run
`Cytosol Viewer.exe`; keep the `_internal` folder next to it. Nothing needs to
be installed. Pushes to `main` also publish the zip as a GitHub release, one per
version (`v<version>`, holding the newest commit of that version). The exe is not code-signed, so Windows SmartScreen asks once
(**추가 정보 → 실행**).

On a Windows PC with Python 3.12:
`powershell -ExecutionPolicy Bypass -File build_windows.ps1` →
`dist\Cytosol Viewer\Cytosol Viewer.exe` and `dist\CytosolViewer-<version>-<commit>-Windows.zip`.
It uses its own `.venv-win` and `cytosol_viewer_win.spec`, so it does not touch
the macOS build files.

`"Cytosol Viewer.exe" --selftest OUT_DIR` (or `python -m cytosol.selftest OUT_DIR`)
runs export, ROI detection and figure export on a synthetic image and writes
`OUT_DIR\selftest.log`; the CI build runs it on the packaged exe.
