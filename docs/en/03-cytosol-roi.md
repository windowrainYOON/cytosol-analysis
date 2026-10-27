# 세포질 ROI tab (cell, nucleus and cytosol ROIs)

[← Manual index](README.md) · [한국어](../ko/03-cytosol-roi.md)

Open or close this tab with **세포질 ROI › 세포질 ROI 탭 열기** (Open 세포질 ROI tab) in the menu bar. This tab's saves and loads are in the same **세포질 ROI** menu.

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

## 2. ROI 검출 (Detect ROIs: automatic / manual)

The **ROI 검출** box has two sub-tabs, **자동** (Automatic) and
**수동 (threshold)** (Manual); detection uses the method of the selected
one. The size ranges, frame handling and live preview are shared.

Every automatic setting has its own **자동** checkbox. Even when it is on,
the value field shows the value actually used; untick it to edit from there.

### 자동 (Automatic)

How it works: the background channel is saturated at **배경 포화값**, merged
with the nuclei, and split into cells by a watershed seeded from each
in-focus nucleus, so every cell gets one nucleus (touching nuclei are split
first). Without a nucleus channel, cells are split along the dark borders
between them. Thresholds you set by hand go into this pipeline as they are.

| Setting | Meaning |
|---|---|
| **배경 포화값** ☑ 자동 (Background saturation) | The background channel is shown as white from this value up. Auto = median of the smoothed channel (shown in the field). Untick and lower it until each cell is one solid blob. |
| **검출용 합성 이미지 보기 (배경 밝게 + 핵)** | Show exactly what the detector sees (bright background + nuclei). |
| **핵 threshold** ☑ 자동 (Nucleus threshold) | Brighter than this in the lightly smoothed nucleus channel = nucleus. Auto = Otsu (shown); untick to set it with the box or slider. |
| **세포 threshold** ☑ 자동 (Cell threshold) | Brighter than this in the background channel = cell; the gaps between cells must be darker. Keep it below the saturation value. |
| **threshold 영역 미리보기 (노랑: 세포, 파랑: 핵)** | Paint what passes each threshold (yellow: cell, blue: nucleus) on the image; follows the sliders live. |
| **스무딩** (Smoothing) | Gaussian smoothing of the merged image (default 0.8 µm). |
| **붙은 세포를 크기 범위에 맞게 나누기 · 합치기** (Fit touching cells to the size range) | Regions larger than the **세포 크기** maximum are cut along the dark valleys between cells into the fewest pieces that fit the range (seeds: distance-map maxima, k-means centres where there are too few; a cell's nucleus stays whole in one piece). Pieces smaller than the minimum are merged with the neighbour across the weakest border, when the merged size fits better (their nuclei are joined). The nucleus size range is fitted the same way. Off by default. |

### 수동 (threshold) (Manual)

The simplest method; it stays available whatever other algorithms are added.

- Every connected area **at or above the cell threshold** in the background
  channel is a cell ROI; everything below is discarded (holes are filled,
  since ImageJ polygon ROIs have none).
- The nucleus is the largest area at or above the **nucleus threshold**
  inside each cell.
- No smoothing, splitting or merging: only the size ranges and the frame
  handling apply.
- The first time, each field starts at the channel's Otsu value; after
  that the values you set are used for every image. **threshold 영역
  미리보기** (on by default) paints what is at or above each threshold on
  the normal composite.

### Shared settings

| Setting | Meaning |
|---|---|
| **세포 크기** min – max (Cell size) | Cells outside this range are dropped (default 80 µm² – no limit). The sliders under the fields (log scale, 1 – 100 000 µm²) set them too; the maximum slider at its right end = **제한 없음** (no limit). |
| **핵 크기** min – max (Nucleus size) | Nuclei outside this range are not used as nuclei (default 15 µm² – no limit). |
| **☑ 자동 (이미지마다 추정)** (Auto, estimated per image) | Each image gets its own size range. One detection without size limits runs on that image (cells on the frame left out); the range is the median cell area ÷ 4 to × 3 (nuclei ÷ 20 to × 3), widened to the smallest – largest area left after setting outliers aside (debris, clumps; Tukey fences on log area, quartiles ± 1.5 IQR). One image holds only a few whole cells, so their smallest – largest alone is far too narrow; and a small nucleus (on the edge, dim) that is dropped hands its cell to a neighbour, so the nucleus minimum stays low. While on, the fields are locked and show the range used on the current image; the status bar lists the range of each image. |
| **프레임에 걸친 세포** (Cells touching the frame) | **안쪽 경계로 자르기** (cut along an inner border, default), **제외** (drop) or **그대로 두기** (keep as is). |
| **안쪽 경계 여백** (Inner border margin) | Distance of that inner border from the frame (default 1 µm). |
| **실시간 미리보기** (Live preview) | When on, every change of a threshold, size range, smoothing etc. reruns the detection on the current image in the background (about 1 s per image) and shows the result as dashed ROIs in place of the existing ones. **ROI 검출** then keeps exactly that result. Turn it off when it is too slow. Off by default. |

Run it with **ROI 검출 (현재 이미지)** (Detect ROIs, current image) or
**모든 이미지** (All images: same settings, channels matched by name; you are
asked whether to redo images that already have ROIs). With a manual size range (자동 off), **모든 이미지** asks whether every image gets the same range: Yes uses the fields' range everywhere, No estimates a range for each image as 자동 does. The status bar shows
the number of cells, the time it took (per image on average for all images)
and the values used.

**Detection time** (for reference): about 0.7 s for one 1024 × 1024 Zeiss
image (nucleus + background channel), 0.8 – 1.1 s with size fitting on, and
2 – 4 s for a 1058 × 1058 TCF fluorescence MIP (4-core cloud machine; a Mac
is usually faster).

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

Hovering over a ROI shows its name and area above it (`cellNNN`, and
`nucNNN` / `cytoNNN` when it has a nucleus), also on the live preview.

The cell list shows each cell's area and whether it was cut at the frame
(**프레임 안쪽으로 자름**) or touches it (**프레임에 걸침**).

## 4. ImageJ ROI 파일 (ImageJ ROI files)

Saving and loading are in the **세포질 ROI** menu of the menu bar.

- Choose which ROIs to save (check items in that menu): **저장할 ROI: 세포 전체**
  (`cellNNN`, cell polygon), **핵** (`nucNNN`), **세포질 (핵 제외)** (`cytoNNN`,
  cell minus nucleus as a composite ROI).
- **ROI 저장 (현재 이미지)…** (Save ROIs, current image): `.zip` = one ImageJ
  RoiSet (ROI Manager › Open); `.roi` = one `.roi` file per ROI.
- **모든 이미지 ROI 저장 (폴더)…** (Save all images' ROIs): one RoiSet per image
  plus `cell_rois.csv` with cell, nucleus and cytosol areas; with
  **파일 › 이미지별 폴더에 나눠 저장** each image's files go in its
  own folder.
- **ROI 불러오기…** (Load ROIs; or **파일 › 불러오기 (자동 인식)…**): choose a `.zip` / `.roi`.
  It is recognised as cell ROIs and loaded into the current image (or the open
  image with the matching image ID). If the image already has cells you are
  asked before they are replaced.

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
  two gives two cells, two nuclei found as one give one cell. When touching
  cells come out as one, set a **세포 크기** range and tick the size
  fitting (check it with **실시간 미리보기**). Then check
  with **검출용 합성 이미지 보기** that every cell is one solid blob, and
  lower **배경 포화값** (or set the cell threshold by hand) if it is not.
- Fix the remaining cells by hand with **더하기**, **빼기** and **새 세포**.
- If no nucleus is found, the status bar says so and cells are split
  without nuclei.
- When nothing else works, the **수동 (threshold)** tab takes exactly what is
  at or above a threshold.
- From Python: `cytosol.cellroi.segment_cells(bg_plane, nucleus_plane, pixel_um, RoiParams())`;
  the manual method is `threshold_cells(bg_plane, nucleus_plane, pixel_um, cell_thr, nuc_thr, RoiParams())`.
