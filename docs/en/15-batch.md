# Batch analysis (per-group analysis pipeline)

[← Contents](README.md) · [한국어](../ko/15-batch.md)

After loading all images and grouping them, tick which analyses to run; they
then run automatically, one after the other, on every image of the chosen
groups. You review the results per image, open only the images that need it to
fix ROIs or settings, measure again, and save only the batch results and
settings. Everything is in the **파일** (File) menu.

## Steps

1. Open all images with **불러오기**.
2. Group them in the image list with **그룹 지정…** (or **자동 그룹**). Without
   groups every image counts as one set, ‘(그룹 없음)’.
3. Set the details in the tabs you need (e.g. automatic / manual threshold in
   the 세포질 ROI tab, the channel in the 입자 ROI tab, the two channels in the
   Coloc 2 tab). The batch uses each tab's **current settings**.
4. **파일 › 일괄 분석 실행…** (`Ctrl+B`):
   - **이미지 그룹**: tick the groups to analyse (image count per group shown).
   - **수행할 분석**: tick any of cell ROI detection, particle ROI detection,
     cell ROI intensity, particle measurement, intensity (logic regions),
     nucleus → membrane bands, Coloc 2, FRAP. The tooltip says which tab's
     settings each one uses.
   - **ROI가 이미 있는 이미지도 다시 검출** (detect again where ROIs exist):
     off (default) leaves images that already have ROIs / particle settings as
     they are and detects only the others; keep it off to protect hand-edited ROIs.
   - **선택한 분석의 설정 탭 열기**: opens the tabs of the ticked analyses so
     you can check their settings first.
   - **실행** (Run): detection first, then measuring. With the 세포질 ROI size
     range on **자동**, each image gets its own range.
5. The **일괄 분석 결과** (results) window opens.

## Review and fix

The results window (**파일 › 일괄 분석 결과 보기…**, `Ctrl+Shift+B`) has one row
per image: group, image and per analysis the number of cell ROIs, particles,
measurement rows, Coloc 2 ROIs, or the FRAP mobile fraction and t½. Empty or
zero cells are red. Above the table: when it ran, the groups, the analyses and
any problems (e.g. images without a matching channel).

- Double-click a row to open that image in the tab of the clicked column; fix
  the ROIs there (merge, cut, delete, …) or change settings.
- **다시 측정 (수정 반영)** (measure again): no new detection; measures the
  chosen analyses again with the edited ROIs. Particles are found again only
  where their settings or the cell ROIs changed.
- **전체 다시 실행…**: choose groups and analyses again and run from the start.
- The measurements also fill each measuring tab's **모든 이미지 (일괄 측정 결과)** view.

## Saving and loading

| Item | What it does |
|---|---|
| **파일 › 일괄 분석 결과 저장 (폴더)…** | Saves only the batch's analyses of the batch's images, measured again so edits are in. Per image a folder `<name>_<image ID>/` (ROIs, particle ROIs, measurement CSVs, Coloc 2 CSV, FRAP curves); at the top the combined CSVs and summaries, `image_groups.csv`, `batch_summary.csv` (the results table) and `batch_settings.json` (analyses, groups, tab settings, run time) |
| **파일 › 일괄 분석 설정 저장…** | Saves the chosen analyses and groups and the settings of the tabs they use as JSON (`format: cytosol-viewer-batch`), to run the same pipeline on another image set |
| **파일 › 일괄 분석 설정 불러오기…** | Loads such a file (or a `batch_settings.json`) and restores the tab settings and the analysis choice. **불러오기 (자동 인식)** recognises it too |

Projects (`.cyproj`) also keep the batch's analysis / group choice and its results table.

## Loading only the settings (pipeline) of a project

Opening a project (**불러오기**, **최근 프로젝트**) asks what to load:

- **전체 (이미지 + 분석 값)** (everything): closes the current work and opens
  the images, ROIs, results and settings.
- **설정(파이프라인)만** (settings only): keeps the open images and results and
  takes only the project's tab settings, open tabs, measured channels and batch
  choice — handy for running an earlier analysis setup on a new image set.

**파일 › 프로젝트에서 설정(파이프라인)만 불러오기…** takes only the settings
without asking (from a project or a batch settings file).
