# Particle tracking tab (v0.66, Z projection v0.69)

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
- **세포 ROI**:
  - *as they are*: the 세포질 ROI tab's ROIs on every frame.
  - *detected per frame + IDs linked*: cells found on every frame with the 세포질 ROI tab's settings; a
    cell overlapping a cell of the previous frame by ≥ 30 % keeps its number. HT (RI) images get cells
    from the RI alone, without nuclei.
  - *none*: the whole image (no inside / outside).
  Cells detected per frame keep the cells at the frame edge (as ParticleTracker does), and HT (RI) cells
  use one threshold for all frames (the median of the thresholds of every 4th frame), so cells don't come
  and go with small RI changes.
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
- **누락 프레임 연결** 1 frame: pieces on both sides of a missed detection become one track. With 1 frame
  ParticleTracker's method is used (the end extrapolated two frames ahead, gate × 1.3); with 2 or more,
  gaps of several frames are closed by one global assignment.
- **밝기 / 크기 차이 가중치**: factors of |ln(ratio)| in the cost.

## 3 측정 (measurement)

- Per channel: particle ROI mean − median of a ring around it (0.34–0.9 µm = ParticleTracker's 3–8
  fluorescence px, other particles left out).
- **비율**: channel B / A. Frames where particles merge or are covered (area × 1.8 or intensity × 1.6) get
  no ratio while **합쳐짐 / 가림 시점은 비율에서 제외** is on.
- **세포 안 기준**: in a cell on more than 50 % of its frames = an inside track (ParticleTracker's rule).
- **긴 트랙**: ≥ 10 frames; shorter ones are short tracks.

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
projection.

Different from ParticleTracker: particles are found with the 입자 ROI tab's method (ParticleTracker
subtracts a σ 25 px background and thresholds at median + 10 × MAD), on the fluorescence resampled to the
HT grid. The learned linking model, the constellation cost (off by default), the exclusion of dividing
cells and the spread-membrane region are not ported.
