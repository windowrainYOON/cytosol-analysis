# Cytosol intensity tracking tab (v0.73)

[← Manual contents](README.md) · [한국어](../ko/25-cell-tracking.md)

Open it with **Tool › Track › Cytosol Intensity Tracking**. In time series it finds the cells in every
frame, links the same cell across frames and measures each cell's fluorescence and its change. Conditions
(filters) pick the cells with the change you look for and compare them with all other cells. Run it with
**Measure This Image / Measure All Images** on the measure bar under the inspector. The
[pipeline](24-pipeline.md) stage **Track › Cytosol intensity tracking** computes the same.

## 1 Cell detection

| Item | Meaning |
|---|---|
| **Algorithm** | **Same as ParticleTracker (RI cell segmentation)**: cell bodies from the RI (HT) channel (ParticleTracker 1.11's cell segmentation). **Cytosol ROI algorithm**: cells and nuclei in every frame with the [Cytosol ROI tab](03-cytosol-roi.md)'s detection settings, cell − nucleus as cytosol. **Cells of the particle tracking result**: the cells found by [particle tracking](21-tracking.md) with the ParticleTracker method. |
| **Cell channel / nucleus channel** | channel to find cells in, nucleus channel (Cytosol ROI algorithm) |
| **Z stack** | **Detect on a Z projection** (maximum / mean) |
| **Frames** | first–last frame |

## 2 Cell tracking (linking)

- **Predict positions from the cell motion (optical flow)**: the previous frame's cells are moved by the flow before comparing.
- **Same-cell overlap**: a cell overlapping the predicted previous cell by at least this % is linked to it.
- **Missing frame linking**: a cell lost for up to this many frames is linked when found again at the same place.
- **Long cells**: only cells tracked for at least this many frames are analysed (the others are `short`).
- **Cells left out**: **cells that divide during tracking** (**division test**: both / RI rise · shrinking
  (ParticleTracker) / splitting in two), **cells touching the image border** (**border rule**: in any frame /
  in more than half of the frames, **border margin** px).

## 3 Intensity

- **Region**: cytosol (cell − nucleus) or the whole cell.
- **Measurement channel**, **reference channel (ratio denominator)**.
- **Background ring**: each cell's ring (inner – outer µm, other cells left out) mean is subtracted; no
  whole-field value is subtracted.
- **Change baseline**: `_change` columns and the filters' rise · fall are measured from the mean up to this time.
- **Measurement channel threshold**: **also compute the value with pixels below the threshold set to 0**
  (`I_thr`). Per image the threshold is the **percentile** of the measurement channel's pixels in the
  **early window** (up to minutes).

Columns: `I_raw`, `bg`, `I` (background subtracted), `I_thr`, `pos_frac`, `R_raw`, `R_bg`, `R`, `ratio`,
`area_um2`, `x`, `y`, `edge`, and `*_change` of each value.

## 4 Filters (cells picked by conditions)

A filter is a name plus conditions. **Add Filter**, **Add Condition**, **Combine conditions** (all / any).
One condition row:

- in the **window** (h), the **change** of the **value** (measurement channel (below threshold = 0) /
  background subtracted / raw / ratio / reference channel): **rises then falls**, **rises**, **falls**,
  **mean at least**.
- Rise size: **top % of all cells** or at least a value. For rises then falls, at least the **fall size** %
  of the rise must be gone by the **fall window** (h).
- Default filter 1: cells whose below-threshold-0 value rises within 2–6 h by the top 25 % of all cells and
  loses at least 60 % of that rise by 7–9.5 h.

Cells meeting the conditions are grouped under the filter name, the others under `나머지` (rest), and
compared in graphs, tables and exports.

## 5 Cells

Cell count · long cells · left out, class chips (switch one off to hide it on the canvas), **show cell
outlines and numbers on the image (filter cells = yellow, left out = dashed)**, data rows (**Cytosol
Intensity Tracking · cell × timepoint**, **· cell**, graph ›).

## Data · export

- Graph window data list and graph source `세포질 강도 추적` (x = time h, y = `I_thr`, mean per class).
- [Export window](17-export.md) › **Cytosol intensity tracking**: `<name>_cell_track_points.csv` (cell ×
  timepoint), `<name>_cell_track_cells.csv` (class · change per cell), graph PNG `<name>_cell_track.png`
  (filter cells / rest time courses, one line per cell + median ± IQR).
- Results and settings are saved in projects. Pipeline stage `세포질 강도 추적`.
