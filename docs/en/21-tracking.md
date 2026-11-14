# Particle tracking tab (v0.66)

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
- **프레임**: the range tracked.

## 2 연결 (linking)

Detections are matched to the next frame by a linear assignment; the cost is the distance from the
predicted position + intensity change + area change + a penalty for changing cell + a penalty for moving
unlike the neighbours.

- **위치 예측** chips (any combination): **세포 움직임** (optical flow of the cell channel),
  **주변 패턴 매칭** (template of the particle's neighbourhood, retried with a small template when the
  score is low), **트랙 속도 (Kalman)** (the track's own velocity; its error widens that track's gate).
- **최대 이동 (gate)** 1.55 µm, **최대 gate** 2.5 µm: farther detections are not linked.
- **누락 프레임 연결** 1 frame: pieces on both sides of a missed detection become one track.
- **밝기 / 크기 차이 가중치**: factors of |ln(ratio)| in the cost.

## 3 측정 (measurement)

- Per channel: particle ROI mean − median of a ring around it (3–8 px, other particles left out).
- **비율**: channel B / A. Frames where particles merge or are covered (area × 1.8 or intensity × 1.6) get
  no ratio while **합쳐짐 / 가림 시점은 비율에서 제외** is on.
- **세포 안 기준**: in a cell on ≥ 50 % of its frames = an inside track.
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
