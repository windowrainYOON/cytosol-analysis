# 세포질 ROI tab (cell, nucleus and cytosol ROIs)

[← Manual index](README.md) · [한국어](../ko/03-cytosol-roi.md)

Open or close this tab with **Tool › 세포질 ROI › 세포질 ROI 탭 열기** (Open 세포질 ROI tab) in the menu bar. Results are saved from **파일 › 내보내기…** ([Export window](17-export.md)); loads are in the same **세포질 ROI** menu.

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

The top of the **ROI 검출** box has the **검출 자동화** (automatic detection)
switch and the **검출 방식** (detection method) pop-up (v0.58).

- **검출 방식**: **자동 검출 (파이프라인)** (the automatic pipeline) or
  **threshold만** (threshold only: at or above = ROI, below = discarded). Only
  the chosen method's settings are shown; the other's are hidden (their
  values are kept). The size ranges, frame handling and live preview are shared.
- **검출 자동화** on (default): only the basic sensitivity, **배경 포화값**
  (with the detector-input view), and **프레임에 걸친 세포** are shown; the
  detail values (nucleus / cell threshold, threshold preview, smoothing,
  fitting touching cells, neck cut and neck width, cell / nucleus size
  ranges, inner border margin) are set per image automatically and hidden.
  Fitting and the neck cut are on. **세부 설정…** (Details…) shows the detail
  values in use, editable right there: a value you change becomes yours
  (its title gets **· 수정됨** (edited) and a reset glyph ↺ that brings the
  automatic value back); values you leave alone stay automatic.
- **검출 자동화** off (manual): every setting is shown and set by you,
  starting from the automatic values at the moment you switch it off.
  Switching it on again makes every value automatic.

There are no per-value **자동** switches any more. A value with a slider
(thresholds) is one row: name – slider – number field; the cell and nucleus
sizes have **최소** (min) and **최대** (max) rows. Picking an image (with the
세포질 ROI tab open) fills the fields with the automatic values for that
image (the size ranges are estimated in the background and filled in when
done).

### 자동 (Automatic)

How it works: the background channel is saturated at **배경 포화값**, merged
with the nuclei, and split into cells by a watershed seeded from each
in-focus nucleus, so every cell gets one nucleus (touching nuclei are split
first). Without a nucleus channel, cells are split along the dark borders
between them. Thresholds you set by hand go into this pipeline as they are.

| Setting | Meaning |
|---|---|
| **배경 포화값** (Background saturation) | The background channel is shown as white from this value up. Auto = median of the smoothed channel (shown in the field). Lower it until each cell is one solid blob. |
| **검출용 합성 이미지 보기 (배경 밝게 + 핵)** | Show exactly what the detector sees (bright background + nuclei). |
| **핵 threshold** (Nucleus threshold) | Brighter than this in the lightly smoothed nucleus channel = nucleus. Auto = Otsu (shown); change it with the box or slider under 세부 설정. |
| **세포 threshold** (Cell threshold) | Brighter than this in the background channel = cell; the gaps between cells must be darker. Keep it below the saturation value. |
| **threshold 영역 미리보기 (노랑: 세포, 파랑: 핵)** | Paint what passes each threshold (yellow: cell, blue: nucleus) on the image; follows the sliders live. |
| **스무딩** (Smoothing) | Gaussian smoothing of the merged image. Auto = 0.8 µm. |
| **붙은 세포를 크기 범위에 맞게 나누기 · 합치기** (Fit touching cells to the size range) | Regions larger than the **세포 크기** maximum are cut along the dark valleys between cells into the fewest pieces that fit the range (seeds: distance-map maxima, k-means centres where there are too few; a cell's nucleus stays whole in one piece). Pieces smaller than the minimum are merged with the neighbour across the weakest border, when the merged size fits better (their nuclei are joined). The nucleus size range is fitted the same way. On by default (v0.58). |
| (Nucleus outline, always) | Each nucleus seed gets its own LUT (local background → 0, that nucleus' bright end → 1) and its own threshold, the Otsu value of that window, so dim nuclei come out round and clean. Dim nuclei the image-wide threshold misses are used only when compact, dropping off sharply at their edge and at least half the size of the other nuclei (cytoplasmic stain is left out). A nucleus that grows too large (over 2.5 × the typical one) keeps the image-wide threshold's area. A manual **핵 threshold** sets the seeds. |
| (Joining nucleus patches, always) | A dim or mottled nucleus crosses the threshold in patches. Patches less than 2 µm apart are first joined into one nucleus and its holes filled; otherwise each patch seeded a cell of its own, giving wedge-shaped cells around the nucleus (v0.31). |
| (Splitting nuclei, always) | Touching nuclei are split at distance-map peaks, and the cut is kept only when the shape says two nuclei: an inward notch of the outline at both ends of the cut, each piece convex while the pair is not, a cut shorter than the pieces are wide, and centres far enough apart for their size. Otherwise the pieces are joined again, so kidney- or bean-shaped nuclei stay whole. |
| **가는 목으로 붙은 세포 자르기**, **목 폭 ≤** (Cut cells joined by a thin neck, neck width) | For cells joined only at their tips into one ROI (usually because one cell's nucleus was missed). Rings of equal distance inside the cell are grown out from the nucleus; where the ring squeezes through a gap of at most the **neck width** into a part at least 2 × wider and at least the minimum cell size, the gap is a neck and the part is cut off along the darkest path of the signal across it. Without such a neck, the shortest line between two deep concave points of the outline is cut under the same conditions. Cut-off parts become new cells without a nucleus. On by default, neck width auto = 6 µm (detection takes about twice as long). |

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
| **세포 크기** min – max (Cell size) | Cells outside this range are dropped . The sliders under the fields (log scale, 1 – 100 000 µm²) set them too; the maximum slider at its right end = **제한 없음** (no limit). |
| **핵 크기** min – max (Nucleus size) | Nuclei outside this range are not used as nuclei . |
| The sizes' automatic values (cell and nucleus each) | Unless you change them, each image gets its own size range. One detection without size limits runs on that image (cells on the frame left out); the range is the median cell area ÷ 4 to × 3 (nuclei ÷ 20 to × 3), widened (with 10 % slack) to the smallest – largest area left after setting outliers aside (debris, clumps; Tukey fences on log area, quartiles ± 1.5 IQR). One image holds only a few whole cells, so their smallest – largest alone is far too narrow; and a small nucleus (on the edge, dim) that is dropped hands its cell to a neighbour, so the nucleus minimum stays low. The fields show the range used on the current image; the status bar lists the range of each image. |
| **프레임에 걸친 세포** (Cells touching the frame) | **안쪽 경계로 자르기** (cut along an inner border), **제외** (drop; default since v0.58) or **그대로 두기** (keep as is). Shown even while 검출 자동화 is on. |
| **안쪽 경계 여백** (Inner border margin) | Distance of that inner border from the frame (auto = 1 µm). |
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

All editing tools are icon buttons; hover one to see its name and shortcut.
From the left: the tool group (arrow = select, ⊕ = add, ⊖ = subtract, dashed
square = new cell, scissors = cut), merge and renumber (#), undo and redo, and
at the end the red trash can, which deletes the selected cells.

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
(**프레임 안쪽으로 자름**) or touches it (**프레임에 걸침**).

## 4. ImageJ ROI 파일 (ImageJ ROI files)

Saving and loading are in the **Tool › 세포질 ROI** menu of the menu bar.

> Since v0.59 the saves below are picked in **파일 › 내보내기…** (Export), kind **세포질 ROI**, instead of a menu ([Export window](17-export.md)). The files written are the same.

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

## 6. 핵 → 세포막 등거리 띠 (Distance bands from the nucleus to the cell edge)

At the bottom of the tab (before v0.57 it was in the 강도 측정 tab; band settings
of projects saved then are still loaded).

The cytosol is cut into bands of equal distance from the nucleus and every
band is measured per channel. Only cells with a nucleus are measured.

| Setting | Meaning |
|---|---|
| **거리** (Distance) | **상대 거리** (relative, default): distance from the nucleus ÷ (distance from the nucleus + distance to the cell edge), so 0 is the nucleus edge and 1 the cell edge whatever the cell's size. **핵 경계에서의 거리 (µm)**: the real distance from the nucleus outline (pixels without calibration). For cells cut by the frame the cut border counts as the cell edge. |
| **범위** (Range) | The distance range measured: 0 – 1 by default for relative, 0 – 10 for µm. |
| **띠 개수** (Number of bands) | How many equal bands the range is cut into (default 10). |
| **이미지에 띠 표시** (Show bands) | Draws the band borders in cyan while this tab is shown. |

The measurement table below works like the cell intensity table above. One row per
cell and band, with `band`, `distance_rel` (or `distance_µm`, the band's
centre) with `_from` and `_to`, the area and the values per channel. With
particles, every band also gets `n_particles` (particles whose centre is in
the band), `particle_area_um2`, `particle_area_fraction` and per channel
`_particle_Mean` (mean of the particle pixels in the band).

**그래프** (Graph): x and y can be any measured column (default x = the
distance, y = the first channel's Mean). Grey lines are single cells, the red
line and band the mean ± SD over cells per band. With the table set to **모든
이미지**, the batch results are drawn.

Saving (Tool › **세포질 ROI** menu): **등거리 띠 CSV 저장 (현재 이미지)…**
(`<name>_bands.csv`), **등거리 띠: 모든 이미지 측정 + 저장 (폴더)…** (per image
`<name>_bands.csv` and `bands.csv` for the set), **등거리 띠 그래프 저장
(PNG / PDF / SVG / TIFF)…**. **파일 › 내보내기…** also writes
`<name>_bands.csv`.

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
