# Pipeline (v0.73, named ROIs v0.76)

[← Manual contents](README.md) · [한국어](../ko/24-pipeline.md)

A pipeline is **an ordered list of stages + the settings stored in each stage + review (correction)
stops in between**. It runs the stages one by one on every image of a data folder (one stage on all
images, then the next stage), stops at a review stage so you can fix ROIs, then goes on, and at the
end writes a result folder under the data folder's parent › `Processed/`. The former **batch
analysis** became "a pipeline without review" and moved here, and the **intensity measurement tab**
moved into the pipeline's **ROI operation** stages (subtract · join · overlap) and **Measure · Signal intensity**.

Since v0.76 every stage **picks ROIs by name** and makes new names (see [ROI names](#roi-names)).
Pipelines of the old format (v0.73–0.75) are converted when opened ([Converting old pipelines](#converting-old-pipelines)).

Open the window with **File › Pipeline…** (`⇧⌘P`). **File › New Pipeline** (v0.74) opens it with an
empty pipeline without stages (the window also starts empty the first time). **File › Pipeline
Library…** shows saved pipelines and the built-in presets as cards; each card lists its stages from top to
bottom as chips joined by ↓, the group name (Detect · ROI operation · Measure …) beside the first stage of a group,
review stages as blue chips and switched-off stages greyed. Opening a `.cypipe` file or an old batch-analysis
settings file (`.json`) with **Import** opens this window too.

## Window

- **Toolbar**: **Pipeline** (pick from the library), **Save…** (save / save as / load from file /
  duplicate / library…), **Data** folder (empty = the images open now), **Choose Folder…**, **Run** (blue).
- The line below: a `14 stages · 9 ROI names · 1 review` chip (an orange chip and `n problems` when
  something is wrong) and the result folder preview. A pipeline converted from the old format also shows a
  `Converted from the old format · n places · not saved` chip, **Changes…** and **Undo conversion**.
- **Left sidebar**: **＋ Add Stage** (a menu per group: start · detect · ROI operation · ROI filter · ROI tracking ·
  measure · value calculation · human · end) and the numbered stage list. A new stage goes right after the selected one.
  - A stage's title is **the feature it uses** (e.g. `Detect · Cytosol ROI`, `ROI filter · Relation`,
    `Measure · Signal intensity`). The second line shows **input → result names** (e.g. `Cyto, Spot → Cyto_noSpot`).
  - Drag to reorder **freely**. A move that would leave a stage using a name not made before it is refused,
    with the reason in the status bar. `⌥↑` / `⌥↓` do the same.
  - Right-click: up · down · duplicate · switch off (skip) · **Delete Stage…**.
  - A stage using a name no earlier stage makes shows `⚠ Check` (reason in the tool tip).
- **Right**: the settings cards of the selected stage. Every stage reads **input → what to do → details →
  result name**; ROI inputs and channel inputs are separate cards, and the result-name card is always last.
- Unless you name the pipeline yourself, it is named by the features it uses
  (e.g. `Cytosol ROI · Particle ROI · ROI filter · ROI operation · Signal intensity`).

## ROI names

Every ROI set made by detection, ROI operations, ROI filters and ROI tracking has a **name**, and later stages
pick it by that name. Default names are in English.

| Made by | Default names | Kind |
|---|---|---|
| Detect · Cytosol ROI | `Cell`, `Nuc`, `Cyto` (= Cell − Nuc) | Regions · per timepoint |
| Detect · Particle ROI | `Spot` | Spot regions · per timepoint |
| Detect · mitoROI | `Mito` | Regions · per timepoint |
| ROI tracking · particle tracking | `Spot_track` | Tracks |
| ROI tracking · cytosol tracking | `Cell_track` | Tracks |

- Each name is used once in a pipeline (making the same name again shows `⚠ Check`).
- The chip beside a name gives its kind; ROI pickers grey out kinds the stage cannot use.
- Every ROI keeps its parent cell number, used by "within the same parent (cell number)" pairing and the `cell` column of measurement tables.

## Stage kinds

| Group | Stage | What it does |
|---|---|---|
| Start | Load, auto group | folder · file name pattern · subfolders / group equal names without the trailing number |
| Detect | Cytosol ROI, particle ROI, mitoROI | image → ROI names (with that tab's detection settings) |
| ROI operation | subtract · overlap · join · grow · shrink · ring · distance bands · join per parent | ROI A (· B) → new name |
| ROI filter | by relation to another ROI / by measured value | ROI → matching ROIs (+ the rest) |
| ROI tracking | particle tracking, cytosol tracking | per-timepoint ROIs → tracks |
| Measure | shape, signal intensity, relation | ROI × channels → parameters |
| Value calculation | calculate, normalize | parameters → new parameters |
| Human | review (your corrections) | stop, fix the ROIs of picked images, go on |
| End | graphs, save · export | redraw graphs, result folder |

FRAP recovery stays a **Measure · FRAP** stage.

### Stages that use tab settings

Detection, ROI tracking and the measurements distance bands · Coloc 2 · FRAP use that tab's settings.

- **Input channels** card: the channels detection uses (cytosol ROI: nucleus · background channel, particle ROI:
  particle channel, mitoROI: mito · protein of interest channel) are set in the stage. **Tab settings as they are**
  uses the tab's channels.
- **Settings source**: **settings stored in this stage** (the tab's settings are copied when the stage is
  added; working on other images in the tab does not change the pipeline's result) or **the tab's current
  settings** (read at run time, like the old batch analysis).
- **Take tab settings**: copies the tab's current settings into the stage.
- **Open in Tab to Edit…**: opens the tab with this stage's settings and shows a band 「pipeline stage n
  settings being edited」 above the canvas. Tune with every tool of the tab (previews, live detection),
  then **Apply to Stage** stores them and the tab goes back to its own settings (**Cancel** leaves them).
- **When results exist**: **find again** or **keep** (keep to protect ROIs fixed in a review).
- **Result names**: the ROI names detection makes (`Cell` · `Nuc` · `Cyto` …). If you change them, pick the new names in later stages.

### ROI operation

1. **Input ROI**: **A** and (when needed) **B**.
2. **Operation**:
   - **Subtract (A − B)**: subtracts the matching B from each A (e.g. `Cyto − Spot`).
   - **Overlap (A ∩ B)**, **Join (A ∪ B)** (adds B to A, only parts not overlapping another A).
   - **Join per parent**: joins the pieces inside the same parent (cell) into one.
   - **Grow / shrink** (µm).
   - **Ring**: a ring around A (inner – outer µm, for background); parts overlapping the **ROI to avoid** (e.g. `Cell`) are left out.
   - **Distance bands**: n bands by relative distance B (nucleus) → A edge (without B: edge → centre).
3. **B pairing**: within the same parent (cell number) / overlapping ones / whole image.
4. **Result name**: the new ROI name. Result ROIs keep the parent number of A.

Example: `Cyto` = `Cell` subtract `Nuc` (same parent) = the intensity tab's region expression `cyto = cell − nuc`.

### ROI filter

1. **Input ROI**.
2. **Criterion**:
   - **By relation to another ROI**: [overlaps / does not overlap / is inside / contains / does not contain / distance ≤ (µm) /
     same parent] + other ROI + value (e.g. `Spot` **is inside** `Cyto`, `Cell` **contains** `Spot` ≥ 3).
   - **By measured value**: [item] [≥ · ≤ · > · < · = · between · yes · no] [value]. Items: size · shape (`Area`,
     `Perimeter`, `Feret`, `Circularity`, `Solidity`, `AR`), intensity (`Mean:<channel>`, `IntDen:<channel>`; value `bg*1.5` =
     1.5 × that channel's background), `edge` (touches the edge), tracks (`frames`, `divided`, `edge`, `change:<value>`, `class`),
     and **columns made by an earlier measure stage** (e.g. `신호 · Cyto › GFP Mean`).
3. **Combine conditions**: all must match (and) / any (or). Without conditions everything passes.
4. **Result names**: the **matching ROIs** name and an optional name for **the rest**.

The **preview** below paints the result up to this stage on the current image, with a chip such as
`Cyto_noSpot 12` (on an image whose detection stages have run once).

### ROI tracking

**Input ROI** (empty = the algorithm finds per timepoint itself), **tracking algorithm** (particle tracking: LAP, the
ParticleTracker way / cytosol tracking: optical flow + overlap, dividing · edge cells excluded), algorithm settings (tab
settings), **result name** (`Spot_track` / `Cell_track`). Particle tracking can set the **5 Signal threshold value**
(the channel's LUT Min) in the stage.

### Measure

Cards: **input ROI** (A, and B for relations) → **input channels** (each picked channel measured on its own) →
**measurement kind** → **parameters** → **settings** → **result name**.

- **Shape** (no channel): size (Area, Perimeter, Feret, MinFeret, major, minor, equivalent diameter), shape (Circularity, AR,
  Roundness, Solidity, Eccentricity), position (centre X · Y, distance to the parent centre · edge), skeleton (MiNA: skeleton
  length · branches · junctions, mito ROIs only), tracks only (length (frames), total distance, net displacement, mean speed, straightness).
- **Signal intensity**: basic (ImageJ Measure: Area, Mean, Median, Min, Max, StdDev, IntDen, RawIntDen), distribution (mean of
  the top n %, CV, positive pixel fraction), time (tracks: values per timepoint, start, end, max, min, max ÷ start, frames on,
  change kind, first on timepoint). **Background**: none / ring around the ROI (µm) / median outside cells / another ROI's
  value (median of the same parent) / image bottom n %. With a background a `› <channel> bg` column is added.
- **Relation** (per A, B summarized, or per B): count (B in A), density (count ÷ A area), B area ÷ A area, overlap area ·
  fractions · IoU, shortest distance B → A edge, B → nearest B (NND), relative position of B (0 inside · 1 edge), partition
  coefficient · enrichment ratio (one channel), colocalization (Coloc 2, two channels), distance bands (distance bands tab
  settings), fraction of frames a B track was inside A · crossings of the A edge.
  No channel = count · overlap · distance, one = partition · enrichment, two = Coloc 2.
- **Measure · FRAP**: the FRAP tab's calculation as is.

An empty **measurement name** becomes `측정 · <ROI>`. Parameter columns are named **`measurement name › channel parameter`**
(e.g. `신호 · Cyto › GFP Mean`; shape has no channel: `형태 · Spot › Area`), and stages with the same measurement name
join one table. One row = one ROI (a track: one timepoint). Result tables go to the graph stage and `1_통합데이터/`.

### Value calculation

**Input values** (an earlier measurement table and its columns) → **calculate** (A ÷ B · A − B · A + B · A × B · log₂ (A) ·
write an expression with `A`, `B`, `log2`, `log10`, `sqrt`, `abs`, `exp`; B is a column or a number) or **normalize**
(first timepoint = 1 · mean of the first n timepoints = 1 · control group mean = 1 · min–max (0–1) · z-score; scope: per
track · ROI · image · group · all) → **result name** (e.g. `계산 › GFP ÷ RFP`). The result is a new column of the same table,
usable in ROI filters (measured value) and graphs.

### In the graph window

After a run the [graph window](16-graph.md) data list starts with **Pipeline results**: every measured and
calculated parameter is a column, in column sets (`Measure · signal intensity` · `Measure · shape` ·
`Measure · relation` · `Value calculation`).

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
| 세포질 ROI · 입자 ROI · ROI 필터 · ROI 연산 · 신호 강도 · 관계 · 등거리 띠 | auto group → Cell · Nuc · Cyto → Spot → Cell_inner (Cells not at the edge) → Cyto_noSpot = Cyto − Spot → signal intensity (Cyto, Spot, Cyto_noSpot) · count · density · distance bands → review → save |
| 입자 추적 · 신호 강도 | particle tracking (ParticleTracker method, 5 Signal threshold 5, 6 Signal-change tracks) → Spot_track values per timepoint |
| 세포질 ROI · 신호 강도 | Cell · Nuc · Cyto → signal intensity (background = median outside cells) → review (replaces the intensity tab) |
| 입자 추적 / 입자 추적 · ROI 필터 · 신호 강도 | Spot_track (→ only `class = signal` tracks, Spot_signal) |
| FRAP | FRAP recovery |
| 입자 추적 · 세포질 강도 추적 · ROI 필터 · 신호 강도 | Spot_track → Cell_track (same cells) → Cell_kept (not dividing, not at the edge) → values per timepoint |
| 세포질 ROI · mitoROI · 미토 형태 (MiNA) / 세포질 ROI · mitoROI · 신호 강도 | Cell → Mito → skeleton (MiNA) / Mito × channel signal intensity |
| 세포질 ROI · Coloc 2 | Cell → relation · colocalization (Coloc 2) |
| 입자 ROI · 형태 · 신호 강도 | Spot → size · shape · signal intensity |

Preset names join the features the stages use in order (start, review and save stages left out). Earlier names (e.g.
`세포질 세기`, `세포질 ROI · 세기`) are still found by `cytosol.pipe --from`. On the same images they give the same results as the v0.75 presets.

The tab stages of the built-in presets use **the tab's current settings**. To keep your own, use **Take tab
settings** and then **Save…** into the library (`~/.cytosol/pipelines/`).

## Converting old pipelines

Pipelines of v0.73–0.75 (`.cypipe` format version 2, old batch-analysis settings, pipelines saved in projects) are
converted to the new format (version 3) when opened: detection → `Detect · …` (default names Cell · Nuc · Cyto …), tracking →
`ROI tracking`, keep / drop operations → `ROI filter`, subtract · overlap · ring … → `ROI operation`, intensity →
`Measure · Signal intensity`, count · distance bands · Coloc 2 → `Measure · Relation`, mito morphology → `Measure · Shape`.
Object names (세포 · 핵 · 입자 …) become the English names.

**Changes…** on the line under the toolbar lists every change, and **Undo conversion** goes back to the pipeline before
conversion. The original file is unchanged until you **Save…**. A converted pipeline gives the same results as before.

## Command line (cytosol-pipe)

The same runner without a window (Remote Control, unattended runs, other programs). Every command prints
readable lines, or one JSON object with `--json`.

```bash
python3 -m cytosol.pipe stages [--json]          # stage kinds · settings · object rules
python3 -m cytosol.pipe presets                  # library
python3 -m cytosol.pipe inspect <folder>         # images · channels · timepoints · pixel size · auto groups
python3 -m cytosol.pipe new my.cypipe --from '세포질 ROI · 세기' --name myrun
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
