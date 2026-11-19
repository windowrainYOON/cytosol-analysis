# Particle tracking tab (v0.66, Z projection v0.69, ParticleTracker method v0.70, result folder v0.71, signal criterion v0.72)

On images with a time axis, the 입자 ROI tab's detection settings are applied to every frame and the same
particle is linked from frame to frame into tracks. The linking and measurement follow the ParticleTracker
app.

Open: Tool › **입자 추적** › 입자 추적 탭 열기 (or the View menu).

## Running

- **추적 실행**: tracks the current image (frame range of card 1).
- **모든 이미지에 실행**: tracks every image with a time axis. The batch step **입자 추적** (파일 › 일괄
  분석) does the same.

## 1 검출 (detection)

- **입자 검출**: the 입자 ROI tab's channel, method (자동 (유의성) / 점 모양 강조 / threshold) and particle
  criterion. Change them in the 입자 ROI tab.
- **방식** › **ParticleTracker와 같게 (형광 원본 해상도)** (same as ParticleTracker; shown for Tomocube TCF
  files with RI and fluorescence, on by default): ParticleTracker 1.11's own code (copied unchanged) runs on
  the TCF file itself: reference-channel detection at the native fluorescence resolution (ParticleTracker
  detection; k from the 입자 ROI tab when it uses the ParticleTracker method, else 10) → fluorescence → RI
  and reference ↔ measure registration per frame → RI cells, cell flow, spread membrane, dividing cells →
  pattern predictions, 2-pass appearance linking, gap closing → ROI measurement, merged frames, track
  classes (tracks of dividing cells `excluded_mitotic`). On the same file the detections, tracks and ratios
  equal ParticleTracker's (up to its CSV rounding). Reference = the 입자 ROI tab's channel (else ratio A,
  else the last CH), measure = ratio B. The cell ROI choice is hidden (ParticleTracker always finds cells
  per frame from the RI); with the Z projection off this app's method is used. Off: tracking on the image
  shown (fluorescence resampled to the HT grid) as below.
- **세포 ROI**:
  - *as they are*: the 세포질 ROI tab's ROIs on every frame.
  - *detected per frame + IDs linked*: cells found on every frame with the 세포질 ROI tab's settings; a
    cell overlapping a cell of the previous frame by ≥ 30 % keeps its number. HT (RI) images get cells
    from the RI alone, without nuclei.
  - *none*: the whole image (no inside / outside).
  Per-frame HT (RI) cells use ParticleTracker's cell code as it is: the cell body image (particles removed
  by an opening), triangle (cell area) / Otsu (cell core) thresholds from a sample of every 4th frame, a
  watershed, the ID kept when a cell overlaps the previous frame's by more than 30 %, cell flow on the body
  images. Other cells come from the 세포질 ROI tab's settings, cells at the frame edge kept.
- **Z 스택** › **Z 투영 후 추적** (Track on Z projection; shown for Z stacks only, on by default): every
  frame's Z stack is projected to 2D before particles are found and linked, independent of the viewer's
  Z slider.
  - **최대 투영 (MIP)** (default, as in ParticleTracker): the brightest value over Z; small particles stand
    out.
  - **평균 투영** (mean): the mean over Z; less noise and brightness for the whole stack, but a faint
    particle on one plane only gets weaker.
  - Off: the plane chosen on the viewer's Z slider (or the viewer's MIP). The hint below says which Z is
    tracked.
- **프레임**: the range tracked.

## 2 연결 (linking)

Detections are matched to the next frame by a linear assignment; the cost is the distance from the
predicted position + intensity change + area change + a penalty for changing cell + a penalty for moving
unlike the neighbours.

With an RI channel (Tomocube TCF) the linking runs **twice**, as in ParticleTracker: the sure links of
the first pass (pattern score ≥ 0.9, cost margin to the runner-up ≥ 2) teach weights for area, detection
channel intensity, RI mean, RI max and shape (eccentricity) from how much they change along one particle
compared with the nearest other one; the second pass links with these weights (instead of the intensity /
area weights).

- **위치 예측** chips (any combination): **세포 움직임** (optical flow of the cell channel),
  **주변 패턴 매칭** (template of the particle's neighbourhood, retried with a small template when the
  score is low), **트랙 속도 (Kalman)** (the track's own velocity; its error widens that track's gate).
- **최대 이동 (gate)** 1.55 µm, **최대 gate** 2.48 µm: farther detections are not linked (ParticleTracker's
  10 / 16 HT px).
- **누락 프레임 연결** 2 frames (default 2 since v0.70; ParticleTracker's default is 1): pieces on both sides
  of missed detections become one track. With 1, ParticleTracker's one-frame closing (the end extrapolated
  two frames ahead, gate × 1.3); with 2 or more, ParticleTracker's close_gaps as it is (forward and backward
  extrapolation, gate × √(gap + 1), appearance of the last / first 3 points, one assignment per connected
  group).
- **밝기 / 크기 차이 가중치**: factors of |ln(ratio)| in the cost.

## 3 측정 (measurement)

- Per channel: particle ROI mean − median of a ring around it (0.34–0.9 µm = ParticleTracker's 3–8
  fluorescence px, other particles left out).
- **비율**: channel B / A. Frames where particles merge or are covered (area × 1.8 or intensity × 1.6) get
  no ratio while **합쳐짐 / 가림 시점은 비율에서 제외** is on.
- **세포 안 기준**: in a cell on more than 50 % of its frames = an inside track (ParticleTracker's rule).
- **긴 트랙**: ≥ 10 frames; shorter ones are short tracks.

## 5 신호 기준 (signal criterion, long tracks, v0.72)

Instead of inside / outside the cell, long tracks are split into tracks with and without signal in one channel (e.g. particles where pHrodo green turns on).

- **신호 있는 트랙으로 나누기** (split by signal): when on, the 4 트랙 chips and summary, the data tables (`class` = `signal` / `nosignal`), graphs, batch analysis and export use these two groups. Off = inside / outside as before.
- **채널** (channel): the tracking's measure channel by default (measure for the ParticleTracker method).
- **Histogram · Min = signal threshold · Max**: the same values as that channel's Min / Max in the LUT tab. Moving them here changes the LUT tab and the preview, and changes in the LUT tab show here. Everything below Min is black in the preview, so the threshold is set by eye. Auto, Min/Max and 전체 이미지에 적용 work as in the LUT tab. Each image uses its own Min.
- **기준 값** (value used): particle ROI maximum (any pixel at or above Min) or particle ROI mean.
- **신호 프레임** (signal frames): a track has signal when the value is ≥ Min in at least this many frames (default 3). Long tracks are those of 3 측정 › 긴 트랙 (default 10 frames).
- **Preview**: in the current frame, a green ring on particles of signal tracks at or above Min, a white dashed ring when below Min.
- Values: the measure channel maximum of the ParticleTracker method comes from the tracking result (`I_B_max`); other channels / the mean come from the track values or are measured on the image inside each particle outline (once, reading every frame).
- Export › 입자 추적 › 신호 기준: per image `<name>_signal_thr<Min>/` (track summary and point CSVs, comparison graphs = median ± IQR of the ratio and the signal value, signal track time courses), all images `신호 기준 통합/` (combined graphs, `per_image_summary.csv`, per-image fraction).

## 4 트랙 (tracks)

- Status: tracks, long tracks (inside / outside), closed gaps, merged frames.
- Chips **세포 안 / 세포 밖 / 짧은 트랙** pick the tracks shown in the table and on the canvas.
- Track table: track, frames, cell, mean speed (µm/min), ratio last / first. Picking a row highlights the
  track on the canvas and shows its ratio curve in the live box.
- **이미지에 트랙 표시**: tails of the last 8 frames and circles at the current positions.
- **트랙 불러오기…**: a ParticleTracker `tracks_points` CSV (or one this app exported) onto the current
  image; 파일 › 불러오기 and drag and drop recognise them too.
- **그래프 ›**: a new graph from `입자 추적 · 시점` (default: time vs ratio, one grey line per track +
  mean ± SD).

## Data and export

- Graph window data list: `입자 추적 · 시점` (track × time point), `입자 추적 · 트랙` (per track),
  `입자 추적 · 세포 × 시점`.
- 파일 › 내보내기 › **입자 추적**: `<name>_tracks_points.csv`, `<name>_tracks_summary.csv`,
  `<name>_tracks.zip` (one ROI per particle and frame `T001-f012` + the path `T001-path`), and for all
  images `tracks_points.csv`, `tracks_summary.csv`, `tracks_cells.csv`. **ParticleTracker 열 이름으로**
  writes ParticleTracker's column names (x_fl, y_fl, roi_label, ratio_BA …).
- Tracks are saved in projects.

## ParticleTracker defaults

The tab's initial values are ParticleTracker 1.11's defaults in µm (HT 1 px = 0.155 µm, fluorescence
1 px = 0.112 µm): gate 1.55 µm, largest gate 2.48 µm, gate factor 4, velocity α 0.4, cell mismatch 2,
intensity 3, area 1.5, neighbour consistency 1 (radius 2.8 µm, at least 2), pattern half width 1.7 µm,
search 1.35 µm, scores 0.5 / 0.4, second stage half width 0.56 µm, search 2.7 µm, minimum score 0.5,
weight 0.5, gap closing 1 frame, appearance features on, ring 0.34–0.9 µm, minimum I(A) 5, long tracks
10 frames, inside 50 %, merged 1.8 × / 1.6 × / 3 frames, merged frames left out of the ratio, Z max
projection. The one difference is gap closing (this app 2, ParticleTracker 1).

With **ParticleTracker와 같게** off: particles are found with the 입자 ROI tab's method (the same detection
when it is set to ParticleTracker 방식) on the fluorescence resampled to the HT grid, and the fluorescence
→ RI alignment is the TCF's fixed one. The learned linking model, the constellation cost (off by default),
the exclusion of dividing cells and the spread-membrane region are not part of this method.

### Comparison (BafA1 P02 TCF, 19 frames, gap closing 2)

| | Time | Detections | Tracks | Long tracks inside / outside |
|---|---|---|---|---|
| ParticleTracker 1.11 | 142 s | 7 206 | 1 793 | 103 / 117 |
| Same as ParticleTracker | 136 s | 7 206 | 1 793 | 103 / 117 (every point equal) |
| Off + 입자 ROI ParticleTracker method | 68 s | 7 089 | 1 758 | 100 / 113 |

## ParticleTracker result folder (v0.71)

파일 › 내보내기 › 입자 추적 › **ParticleTracker 결과 폴더** (on by default) writes, per image,
`<name>_ParticleTracker/` with the files ParticleTracker writes to its result folder, under the same names,
columns and rounding, so ParticleTracker's combine / rise-fall / group comparison tabs and scripts that read
its CSVs take them as they are.

| File | Same as ParticleTracker | This app's method |
|---|---|---|
| `tracks_points_A_B_HT.csv` (track × time point, 40 columns) | equal (byte for byte) | same columns (fluorescence coordinates = image coordinates; registration, spread membrane, mitosis and HT-confirmed columns empty / False) |
| `tracks_summary_A_B_HT.csv` | equal | same columns (computed by ParticleTracker's summary code) |
| `particles_all_slices.csv`, `summary_per_slice.csv` | equal | same columns (perimeter, max / min intensity, threshold empty) |
| `particles_per_cell.csv` | equal | same columns (cell area empty) |
| `registration.csv`, `footprint_per_frame.csv`, `cell_stats_mitosis.csv`, `cell_intensity.csv`, `particle_labels.tif`, `tracking_appearance_weights.json` | equal | not written (no such step) |
| `dataset.json`, `config_used.yaml` | same format | same names (this app's settings) |
| 9 graph PNGs (`ratio_timecourse_inside.png` …) | ParticleTracker's plotting code | not written |
| 7 movies MP4 (`movie_reference_inside.mp4` …, off by default) | ParticleTracker's movie code | not written |

ParticleTracker's `_cache/` folder (intermediate results for re-runs) is not written. Graphs and movies read
the TCF file again.
