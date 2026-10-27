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
At first every value is automatic, and picking an image (with the 세포질 ROI
tab open) fills the fields with the values for that image (the size ranges
are estimated in the background and filled in when done). Untick only the
values you want to set yourself.

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
| **스무딩** ☑ 자동 (Smoothing) | Gaussian smoothing of the merged image. Auto = 0.8 µm. |
| **붙은 세포를 크기 범위에 맞게 나누기 · 합치기** (Fit touching cells to the size range) | Regions larger than the **세포 크기** maximum are cut along the dark valleys between cells into the fewest pieces that fit the range (seeds: distance-map maxima, k-means centres where there are too few; a cell's nucleus stays whole in one piece). Pieces smaller than the minimum are merged with the neighbour across the weakest border, when the merged size fits better (their nuclei are joined). The nucleus size range is fitted the same way. Off by default. |
| (Nucleus outline, always) | Each nucleus seed gets its own LUT (local background → 0, that nucleus' bright end → 1) and its own threshold, the Otsu value of that window, so dim nuclei come out round and clean. Dim nuclei the image-wide threshold misses are used only when compact, dropping off sharply at their edge and at least half the size of the other nuclei (cytoplasmic stain is left out). A nucleus that grows too large (over 2.5 × the typical one) keeps the image-wide threshold's area. A manual **핵 threshold** sets the seeds. |
| (Joining nucleus patches, always) | A dim or mottled nucleus crosses the threshold in patches. Patches less than 2 µm apart are first joined into one nucleus and its holes filled; otherwise each patch seeded a cell of its own, giving wedge-shaped cells around the nucleus (v0.31). |
| (Splitting nuclei, always) | Touching nuclei are split at distance-map peaks, and the cut is kept only when the shape says two nuclei: an inward notch of the outline at both ends of the cut, each piece convex while the pair is not, a cut shorter than the pieces are wide, and centres far enough apart for their size. Otherwise the pieces are joined again, so kidney- or bean-shaped nuclei stay whole. |
| **가는 목으로 붙은 세포 자르기**, **목 폭 ≤** ☑ 자동 (Cut cells joined by a thin neck, neck width) | For cells joined only at their tips into one ROI (usually because one cell's nucleus was missed). Rings of equal distance inside the cell are grown out from the nucleus; where the ring squeezes through a gap of at most the **neck width** into a part at least 2 × wider and at least the minimum cell size, the gap is a neck and the part is cut off along the darkest path of the signal across it. Without such a neck, the shortest line between two deep concave points of the outline is cut under the same conditions. Cut-off parts become new cells without a nucleus. On by default, neck width auto = 6 µm (detection takes about twice as long). |

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
| **세포 크기** min – max ☑ 자동 (Cell size) | Cells outside this range are dropped (with 자동 off it starts at 80 µm² – no limit). The sliders under the fields (log scale, 1 – 100 000 µm²) set them too; the maximum slider at its right end = **제한 없음** (no limit). |
| **핵 크기** min – max ☑ 자동 (Nucleus size) | Nuclei outside this range are not used as nuclei (with 자동 off it starts at 15 µm² – no limit). |
| The sizes' **☑ 자동** (Auto; cell and nucleus each) | On by default: each image gets its own size range. One detection without size limits runs on that image (cells on the frame left out); the range is the median cell area ÷ 4 to × 3 (nuclei ÷ 20 to × 3), widened (with 10 % slack) to the smallest – largest area left after setting outliers aside (debris, clumps; Tukey fences on log area, quartiles ± 1.5 IQR). One image holds only a few whole cells, so their smallest – largest alone is far too narrow; and a small nucleus (on the edge, dim) that is dropped hands its cell to a neighbour, so the nucleus minimum stays low. While on, the fields are locked and show the range used on the current image; the status bar lists the range of each image. |
| **프레임에 걸친 세포** (Cells touching the frame) | **안쪽 경계로 자르기** (cut along an inner border, default), **제외** (drop) or **그대로 두기** (keep as is). |
| **안쪽 경계 여백** ☑ 자동 (Inner border margin) | Distance of that inner border from the frame (auto = 1 µm). |
| **실시간 미리보기** (Live preview) | When on, every change of a threshold, size range, smoothing etc. reruns the detection on the current image in the background (about 1 s per image) and shows the result as dashed ROIs in place of the existing ones. **ROI 검출** then keeps exactly that result. Turn it off when it is too slow. Off by default. |

Run it with **ROI 검출 (현재 이미지)** (Detect ROIs, current image) or
**모든 이미지** (All images: same settings, channels matched by name; you are
asked whether to redo images that already have ROIs). With manual cell and nucleus size ranges (both 자동 off), **모든 이미지** asks whether every image gets the same range: Yes uses the fields' range everywhere, No estimates a range for each image as 자동 does. The status bar shows
the number of cells, the time it took (per image on average for all images)
and the values used.

**Detection time** (for reference): about 0.7 s for one 1024 × 1024 Zeiss
image (nucleus + background channel), 0.8 – 1.1 s with size fitting on, and
2 – 4 s for a 1058 × 1058 TCF fluorescence MIP (4-core cloud machine; a Mac
is usually faster).

## 3. 확인 · 수정 (Check and edit)

| Tool / key | Action |
|---|---|
| **선택/이동 (V)** | Click a cell to select it (or pick it in the list); drag pans. **Shift+click** picks several cells (Shift+click again takes one out) to merge or delete; **Option (Alt)+drag** draws a cut line without switching tools (as 자르기) |
| **더하기 (A)** (Add) | Drag a freehand area to add it to the selected cell |
| **빼기 (S)** (Subtract) | Drag an area to remove it from the selected cell (from all cells when none is selected) |
| **새 세포 (N)** (New cell) | The drawn area becomes a new cell; with a nucleus channel its nucleus is found inside it |
| **자르기 (C)** (Cut) | Draw a line to split cells: the selected cell, or every cell the line crosses when none is selected. The piece with the nucleus (else the largest) keeps the number, the others become new cells. The line has to cross the cell completely |
| **합치기 (M)** (Merge) | Join the Shift+clicked cells into one; the lowest number stays. Cells that do not touch are bridged across the gap between them (up to 3 µm, where no other cell is); nearby nucleus pieces are joined too |
| **선택 세포 삭제** / `Delete` | Delete the selected cell(s) |
| **되돌리기** / **다시 실행** | Undo (`Ctrl+Z`) / redo (`Ctrl+Shift+Z`) |
| **번호 다시 매기기** | Renumber the cells |
| **ROI 표시** / **핵 경계 표시** | Show the ROIs / nucleus outlines |

A cell is always one filled piece (ImageJ polygon ROIs have no holes), so
to cut into a cell, start the drawing from outside its border. You can draw
**새 세포** without running detection first.

Hovering over a ROI shows its name and area above it (`cellNNN`, and
`nucNNN` / `cytoNNN` when it has a nucleus), also on the live preview.

The cell list shows each cell's area and whether it was cut at the frame
(**프레임 안쪽으로 자름**) or touches it (**프레임에 걸침**), has no nucleus
(**핵 없음**) or has a nucleus threshold set by hand (**핵 threshold value**).

### 핵 다시 찾기 (Re-detect nuclei inside the cell ROIs, one per cell)

Use this box after editing the cells. The cell ROIs stay as they are; inside
each cell, **one** nucleus is found again with **the cell's own threshold**.

| Item | Description |
|---|---|
| **핵 threshold** · **자동** | On: every cell gets its own LUT stretch (1st – 99.5th percentile of the cell plus a 2 µm outer ring) and its own Otsu threshold; the field shows the value used (or to be used) for the selected cell. Off: the field / slider value is the threshold of the selected cell(s) (Shift+click for several), and moving it re-draws their nuclei at once (one undo step brings them back). Selecting a cell sets the check box and value to that cell's setting. |
| **핵 다시 찾기 (선택 세포)** | Re-detect the nuclei of the selected cells with the setting above (automatic or the value entered). |
| **모든 세포** (All cells) | Re-detect every cell's nucleus: cells with a manual threshold keep it, the others get their own automatic threshold. |

Inside the cell, pieces above the threshold closer than 2 µm are joined and
the piece with the most signal becomes the nucleus. An automatic result about
as dark as the image background (noise in a cell piece without a nucleus) is
left as no nucleus. The threshold of each cell is saved in the project.

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
- Fix the remaining cells by hand with **더하기**, **빼기**, **새 세포** and **자르기**. Cells joined at their tips: turn on **가는 목으로 붙은 세포 자르기** or draw a line with **자르기**.
- If no nucleus is found, the status bar says so and cells are split
  without nuclei.
- When nothing else works, the **수동 (threshold)** tab takes exactly what is
  at or above a threshold.
- From Python: `cytosol.cellroi.segment_cells(bg_plane, nucleus_plane, pixel_um, RoiParams())`;
  the manual method is `threshold_cells(bg_plane, nucleus_plane, pixel_um, cell_thr, nuc_thr, RoiParams())`.
