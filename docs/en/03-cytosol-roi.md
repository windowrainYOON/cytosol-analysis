# 세포질 ROI tab (cell, nucleus and cytosol ROIs)

[← Manual index](README.md) · [한국어](../ko/03-cytosol-roi.md)

This tab finds one ROI per cell, with its nucleus, and gives three regions
per cell: `cell` (whole cell), `nuc` (nucleus) and `cyto` (cell minus
nucleus). The ROIs are used by every other analysis tab and saved as ImageJ
ROI files.

Detection works on the current Z plane (or MIP) and timepoint.

## 1. 채널 역할 (Channel roles)

- **핵** (Nucleus): the nuclear channel (e.g. DAPI), or **없음** (none).
- **배경 신호** (Background signal): a dim channel that fills the whole
  cytoplasm when its LUT is pushed very bright (autofluorescence or
  non-specific signal is fine).

## 2. 자동 검출 (Automatic detection)

How it works: the background channel is saturated at **배경 포화값**, merged
with the nuclei, and split into cells by a watershed seeded from each
in-focus nucleus, so every cell gets one nucleus (touching nuclei are split
first). Without a nucleus channel, cells are split along the dark borders
between them.

| Setting | Meaning |
|---|---|
| **배경 포화값** (Background saturation) | The background channel is shown as white from this value up. **자동** (Auto) = median of the smoothed channel; **자동값** (Auto value) puts the automatic value back. Lower it until each cell is one solid blob. |
| **검출용 합성 이미지 보기 (배경 밝게 + 핵)** | Show exactly what the detector sees (bright background + nuclei). |
| **핵 threshold** (Nucleus threshold) | Brighter than this in the lightly smoothed nucleus channel = nucleus. Otsu by default; tick **수동** (Manual) to set it with the box or slider. |
| **세포 threshold** (Cell threshold) | Brighter than this in the background channel = cell; the gaps between cells must be darker. Keep it below the saturation value. Otsu by default, or **수동**. |
| **threshold 영역 미리보기 (노랑: 세포, 파랑: 핵)** | Paint what passes each threshold (yellow: cell, blue: nucleus) on the image. Follows the sliders live; moving a manual slider turns it on. |
| **최소 세포 크기** / **최소 핵 크기** | Smaller objects are dropped (defaults 80 µm² and 15 µm²). |
| **스무딩** (Smoothing) | Gaussian smoothing of the merged image (default 0.8 µm). |
| **프레임에 걸친 세포** (Cells touching the frame) | **안쪽 경계로 자르기** (cut along an inner border, default), **제외** (drop) or **그대로 두기** (keep as is). |
| **안쪽 경계 여백** (Inner border margin) | Distance of that inner border from the frame (default 1 µm), so no ROI runs along the edge of the image. |

Run it with **ROI 검출 (현재 이미지)** (Detect ROIs, current image) or
**모든 이미지** (All images: same settings, channels matched by name; you are
asked whether to redo images that already have ROIs). The thresholds that
were used are shown after detection.

## 3. 확인 · 수정 (Check and edit)

| Tool / key | Action |
|---|---|
| **선택/이동 (V)** | Click a cell to select it (or pick it in the list); drag pans |
| **더하기 (A)** (Add) | Drag a freehand area to add it to the selected cell |
| **빼기 (S)** (Subtract) | Drag an area to remove it from the selected cell (from all cells when none is selected) |
| **새 세포 (N)** (New cell) | The drawn area becomes a new cell; with a nucleus channel its nucleus is found inside it |
| **선택 세포 삭제** / `Delete` | Delete the selected cell |
| **되돌리기** / **다시 실행** | Undo (`Ctrl+Z`) / redo (`Ctrl+Shift+Z`) |
| **번호 다시 매기기** | Renumber the cells |
| **ROI 표시** / **핵 경계 표시** | Show the ROIs / nucleus outlines |

A cell is always one filled piece (ImageJ polygon ROIs have no holes), so
to cut into a cell, start the drawing from outside its border. You can draw
**새 세포** without running detection first.

The cell list shows each cell's area and whether it was cut at the frame
(**프레임 안쪽으로 자름**) or touches it (**프레임에 걸침**).

## 4. ImageJ ROI 파일 (ImageJ ROI files)

- Choose which ROIs to save: **세포 전체** (`cellNNN`, cell polygon), **핵**
  (`nucNNN`), **세포질 (핵 제외)** (`cytoNNN`, cell minus nucleus as a
  composite ROI).
- **ROI 저장…** (Save ROIs): `.zip` = one ImageJ RoiSet (ROI Manager › Open);
  `.roi` = one `.roi` file per ROI.
- **ROI 불러오기…** (Load ROIs): reads `.zip` / `.roi` back for editing. If the
  file was saved from another image (different image ID) you are asked first.
- **모든 이미지 ROI 저장 (폴더)…** (Save all images' ROIs): one RoiSet per image
  plus `cell_rois.csv` with cell, nucleus and cytosol areas; with
  **이미지별 폴더에 나눠 저장** each image's files go in its own folder.

## 5. 세포 강도 측정 (Cell intensity)

**측정할 영역** (Regions to measure): **세포 전체**, **핵**, **세포질**. The
table gives, per cell, region and channel, ImageJ Measure values (Mean and
optionally StdDev, Min, Max, IntDen, RawIntDen) of the raw data on the
current plane and timepoint. It updates whenever a ROI is edited.

Files: `<name>_cell_intensity.csv` per image, `cell_intensity.csv` for all
images. How the table, batch measurement and saving work is described in
[the measurement table](09-intensity.md#the-measurement-table).

## Tips

- Each cell is grown from one nucleus, so when cells come out wrong, look
  at the nuclei first with **threshold 영역 미리보기**: a nucleus split in
  two gives two cells, two nuclei found as one give one cell. Then check
  with **검출용 합성 이미지 보기** that every cell is one solid blob, and
  lower **배경 포화값** (or set the cell threshold by hand) if it is not.
- Fix the remaining cells by hand with **더하기**, **빼기** and **새 세포**.
- If no nucleus is found, the status bar says so and cells are split
  without nuclei.
- From Python: `cytosol.cellroi.segment_cells(bg_plane, nucleus_plane, pixel_um, RoiParams())`.
