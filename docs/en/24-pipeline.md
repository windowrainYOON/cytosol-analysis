# Pipeline (v0.73)

[← Manual contents](README.md) · [한국어](../ko/24-pipeline.md)

A pipeline is **an ordered list of stages + the settings stored in each stage + review (correction)
stops in between**. It runs the stages one by one on every image of a data folder (one stage on all
images, then the next stage), stops at a review stage so you can fix ROIs, then goes on, and at the
end writes a result folder under the data folder's parent › `Processed/`. The former **batch
analysis** became "a pipeline without review" and moved here, and the **intensity measurement tab**
moved into the pipeline's **Operation** stages (add · subtract · intersect) and **Measurement ›
Intensity**.

Open the window with **File › Pipeline…** (`⇧⌘P`). **File › Pipeline Library…** shows saved
pipelines and the built-in presets as cards. Opening a `.cypipe` file or an old batch-analysis
settings file (`.json`) with **Import** opens this window too.

## Window

- **Toolbar**: **Pipeline** (pick from the library), **Save…** (save / save as / load from file /
  duplicate / library…), **Data** folder (empty = the images open now), **Choose Folder…**, **Run**
  (blue button).
- The row below: a chip like `14 stages · 9 objects · 1 review` (an orange chip and `n problems` when
  something is wrong) and a preview of the result folder.
- **Left sidebar**: **＋ Add Stage** (a menu per group) and the numbered stage list. Stages always stay
  in the group order **Start → Detect → Track → Operation → Measurement → End** under group headings;
  a review stage stays right after the stage before it.
  - Drag to reorder. Stages move **only within their group**; when an object a stage needs does not
    exist yet at the new place, it does not move and the status bar says why. `⌥↑` / `⌥↓` do the same.
  - Right-click: up · down · duplicate · turn off (skip) · **Delete Stage…**.
  - A stage that uses an object no earlier stage makes shows `⚠ no object` (reason in the tool tip).
- **Right**: the setting cards of the selected stage.

## Objects

Every ROI made by detection, tracking or an operation is a **named object**. Cytosol ROI detection
makes **cells · nuclei · cytosol** (= cell − nucleus), particle ROI **particles**, mitoROI **mito
fragments**, particle tracking **particle tracks**, cytosol intensity tracking **cell tracks**, and
an operation stage a new object with the name you give. Every object keeps its parent cell number,
so later "same cell number" pairing and the `cell` column of the measurement tables use it as is.

## Stage kinds

| Group | Stage | What it does |
|---|---|---|
| Start | Load, Auto group | folder · file name pattern · include subfolders / group images whose names match without the trailing number |
| Detect | Cells · nuclei (Cytosol ROI), Particles (Particle ROI), Mito ROI (mitoROI) | find them in every image with that tab's detection settings |
| Track | Particle tracking, Cytosol intensity tracking | detect and link per frame in time series |
| Operation | Operation | input object · condition · action · result name (below) |
| Measurement | Intensity (ImageJ Measure), Count · density, Distance bands, Coloc 2, FRAP recovery, Mito morphology (MiNA) | object × channel → table |
| Person | Review (your corrections) | stop, fix the ROIs of chosen images, continue |
| End | Graphs, Save · export | redraw graphs, result folder |

### Stages that use tab settings

Detection, tracking, distance band, Coloc 2 and FRAP stages use that tab's settings.

- **Settings source**: **Settings stored in this stage** (the tab's settings are copied when the stage
  is added; changing the tab for other images does not change the pipeline's results) or **the tab's
  current settings** (read from the tab at run time, like the old batch analysis).
- **Take Tab Settings**: copy the tab's current settings into this stage.
- **Edit in Tab…**: opens the tab with this stage's settings and shows a band "editing pipeline stage
  n settings" above the canvas. Tune with every feature of the tab (preview, live detection …), then
  **Apply to Stage** stores them in the stage and returns the tab to its own settings (**Cancel**
  leaves the stage as it was).
- **If results exist**: **Detect again** or **Keep as is** (keep ROIs you fixed in a review).

### Operation

Every operation stage has the same four cards.

1. **Input object**: an object made earlier.
2. **Condition**: **All** or **Only those meeting conditions**. Each condition row is [item] [≥ · ≤ · > · < ·
   = · range · yes · no] [value], with **＋ Add Condition** and **Combine** (all / any). Items:
   - size · shape: `Area` (µm²), `Perimeter`, `Feret` (µm), `Circularity`, `Solidity`, `AR`
   - intensity: `Mean:<channel>`, `IntDen:<channel>`; a value `bg*1.5` means 1.5 × that channel's
     background (median outside cells)
   - with another object: `overlap:<object>` (% overlapping), `inside:<object>` (centre inside)
   - `edge` (touches the image border)
   - tracks: `frames`, `divided`, `edge`, `change:thr` (last / first intensity), `class` (particle track
     class, e.g. `signal`; for cell tracks the cytosol intensity tracking filter name)
3. **Action**: keep matches · drop matches · subtract (what) · add (to what) · overlap only (with what) ·
   merge (one per parent) · dilate / erode (µm) · ring (inner – outer µm) · distance bands (n).
   Subtract, add and overlap pick the **other object** and the **pairing** (same cell number / overlapping
   ones / whole image). Example: cytosol = cell **subtract** nucleus (same cell number) = the intensity
   tab's region expression `cyto = cell − nuc`. A ring around cells avoids other cells, so it serves as a
   background ring. Distance bands: n bands by relative nucleus → membrane distance.
4. **Result name**: the new object's name. For keep / drop, a **name for the rest** makes the others an
   object too (e.g. "cells with rising signal" and "rest").

The **preview** below paints the result of the operations up to this stage on the current image and
counts them with a chip like `cytosol 2` (on an image where the detection stages already ran).

### Measurement

- **Intensity (ImageJ Measure)**: rows of **targets (object × channel)**, each an object and its channel
  chips (all on = every channel), **＋ Add Target**. **Measured items** chips: Area, Mean, StdDev, Min,
  Max, Median, IntDen, RawIntDen, Perimeter, Circularity. **Subtract background**: none / median outside
  cells / median of a ring object (the same cell's ring). Column names carry the channel, e.g.
  `Mean (GFP)`; with background subtraction a `bg (GFP)` column is added. One row = one object (one
  timepoint for tracks).
- **Count · density**: per parent (cell) the number of objects, the parent area and the count per area.
- **Distance bands / Coloc 2 / FRAP recovery**: the tab's own computation (also in the integrated data).
- **Mito morphology (MiNA)**: skeleton length · branches · junctions of mito fragments ([mitoROI](22-mito.md)).

An empty table name becomes `측정 · <object>`. Result tables go to the graph stage and to `1_통합데이터/`.

### Review (your corrections)

- **Images to review**: **Pick by hand** (`4 picked` chip + **Pick…**), **Images with finding chips**,
  **All images**, **Does not stop (chips only)**. With no image picked it does not stop.
- **Pick window**: the open images as a check list per group, with each image's findings. Quick picks:
  all · none · with findings · one per group.
- **Show Findings as Chips**: cell count out of range · touching nuclei · odd nucleus shape · detection
  failed (on), cells without nucleus · edge cells (off). **Cell count range** 3–40 by default.
  **Odd nucleus rule**: normal = a hole (filled − area > 2 %) or a dent deeper than 15 % of the nucleus
  diameter from the convex hull or solidity < 0.85; strict < 0.90; loose < 0.80. Chips are computed when
  cytosol ROI detection finishes and only help you pick (images are not added automatically).

When a run reaches a review, the pipeline window hides and a **review band** appears above the main
window's canvas.

- Title `Review: <previous stage>`, chips `pipeline 4 / 8` · `review 1 / 4` · this image's findings.
- **Pick Images…**, **Back** / **Next** (`⌘[` / `⌘]`), **Confirm This Image** (`⌘↩`), **Finish Review and
  Continue** (blue). With unconfirmed images left it asks **Continue Anyway** / **Go Back**.
- Chips under the names in the image list: review, confirmed, left out, findings (orange warning / red
  failure / grey note).
- Fix ROIs as in the [Cytosol ROI tab](03-cytosol-roi.md) (merge M, cut C, delete, draw, detect again).
  Right-click in the list › **Add to / Remove from Review**, **Leave Out of This Run**.
- The measure bar hides during a review; confirmations and leave-outs go to `review_log.csv`.

### Graphs

**＋ Add the Graph Editor’s Current Graph** puts a graph of the [graph editor](16-graph.md) into the stage.
Graphs are stored by column names, so new data are drawn the same way; a graph whose table is missing is
skipped and the reason goes into `README.txt`. **Format** PNG · PDF · SVG, **CSV of the plotted tables**.

### Save · export

- **Destination**: **data folder's parent › Processed/** (default) or **custom**.
- **Folder name pattern**: `<data folder>_<pipeline>_<date>_<time>`; an existing name gets ` (2)` and so on.
- **Export kinds (per image)** chips: the kinds of the [export window](17-export.md) (with their default
  outputs), in per-image folders under `3_이미지/`.
- **Integrated data CSV**, **Project file**.

```
<data folder's parent>/Processed/<data folder>_<pipeline>_<date>_<time>/
  pipeline.json      every stage · setting · app version of this run
  project.cyproj     opens with the ROIs · measurements · pipeline
  README.txt         stage summary, image count, run time, warnings, Methods sentence
  review_log.csv     confirmations and leave-outs of the review
  work_log.csv       work log
  summary.json       image count, objects per image, table rows, warnings
  progress.jsonl     one line per stage (progress record)
  1_통합데이터/       integrated_*.csv + the measurement stages' tables (<table name>.csv)
  2_그래프/          <graph>.png / .pdf / .svg + .csv
  3_이미지/          per-image exports
```

## Run and done

**Run** first checks for problems (missing objects, order, missing channels), opens the images of the
data folder (images already open stay) and runs the stages. The progress bar shows `3 / 10 · Particles
(Particle ROI)`. When it finishes the **done** page shows chips for images · tables · warnings, the
result folder, warnings, tables, **Open Result Folder**, **Show in Graph Editor**, **Show Measurement
Status**, **Run on Another Folder…** and **Back to Stages**.

Saving a project saves the current pipeline with it.

## Built-in presets (library)

| Preset | Stages |
|---|---|
| 세포질 + 입자 · 띠 (cytosol + particles · bands) | auto group → cells · nuclei → particles → inner cells = cells not at the edge → cytosol (minus particles) → intensity · count · distance bands → review → save |
| 261118 TCF | particle tracking (tab settings: ParticleTracker method, 5 signal threshold, 6 signal change tracks) → track point intensity |
| 세포질 세기 (cytosol intensity) | cells · nuclei → cell / nucleus / cytosol intensity (background = outside cells) → review (replaces the intensity tab) |
| ParticleTracker 기본 / 신호 기준 | particle tracking (→ only `class = signal` tracks) |
| FRAP | FRAP recovery |
| 세포질 강도 추적 + 변화 필터 | cytosol intensity tracking → cell tracks not dividing and not at the edge → intensity per timepoint |
| Mito Analyzer (형태) / (관심 단백질) | cells → mito ROI → MiNA / mito fragment × channel intensity |
| Coloc 2 | cells → Coloc 2 |
| Analyze Particles | particles → size · shape · intensity |

The presets' tab stages use **the tab's current settings**. To keep your own settings, **Take Tab
Settings** and then **Save…** to the library (`~/.cytosol/pipelines/`). Preset names are not translated.

## Command line (cytosol-pipe)

The same runner without a window (Remote Control, unattended runs, other programs). Every command prints
readable lines, or one JSON object with `--json`.

```bash
python3 -m cytosol.pipe stages [--json]          # stage kinds · settings · object rules
python3 -m cytosol.pipe presets                  # library
python3 -m cytosol.pipe inspect <folder>         # images · channels · timepoints · pixel size · auto groups
python3 -m cytosol.pipe new my.cypipe --from '세포질 세기' --name myrun
python3 -m cytosol.pipe edit my.cypipe --set 'stages[1].settings.bg="outside"'
python3 -m cytosol.pipe add my.cypipe op --at 2
python3 -m cytosol.pipe validate my.cypipe --folder <folder>
python3 -m cytosol.pipe run my.cypipe <folder> --dry-run
python3 -m cytosol.pipe run my.cypipe <folder> [--out DIR] [--only 1,3] [--images part] [--background]
python3 -m cytosol.pipe status <result folder>   # progress.jsonl / summary.json
python3 -m cytosol.pipe resume <result folder>   # continue a run stopped at a review with --review stop
python3 -m cytosol.pipe rerun <result folder> --from 5
```

The command line does not stop at reviews by default (`--review skip`). Open the result folder's
`project.cyproj` the next day, fix, and rerun only the later stages.
