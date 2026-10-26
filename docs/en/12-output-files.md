# Output files

[← Manual index](README.md) · [한국어](../ko/12-output-files.md)

`<name>` is the image's file name without extension. With
**이미지별 폴더에 나눠 저장** (on by default) each image's files go into a folder
`<name>_<image ID>/`; the combined tables for all images stay in the folder
you chose. Every TIFF, ROI and CSV carries the image ID (see
[Image ID](01-getting-started.md#image-id)).

## Images

| File | Written by | Contents |
|---|---|---|
| `<name>_full_composite.tif` | LUT › 이미지 내보내기 | Composite RGB with LUTs and markers; with crops `<name>_crop1_composite.tif`, … |
| `<name>_full_C<i>_<channel>.tif` | export, **채널별 RGB** | One RGB image per channel |
| `<name>_full_raw.tif` | export, **원본값 스택** | ImageJ hyperstack of the original values (TZCYX for time series) |
| `….mp4` | export / 스택 tab with MP4 chosen | Movie, one frame per timepoint (or angle) |
| projection `.tif` / `.mp4` | 스택 tab | RGB projection + float32 ImageJ stack, or rotation series |
| `<name>_image.png` | measurement / line-profile saves | The image with the current LUTs and ROI outlines or the line |
| Figure `.png` / `.tif` / `.pdf` / `.svg` | Figure window | The figure table |

## ROIs (ImageJ format, open with ROI Manager › Open)

| File | Written by | ROI names |
|---|---|---|
| `<name>_RoiSet.zip` | 세포질 ROI tab, measurement saves, save all results | `cellNNN`, `nucNNN`, `cytoNNN` |
| `<name>_particles.zip` | 입자 ROI tab | `partCCC-NN` (pixel-edge outlines; settings in the properties) |
| `<name>_particles_contour.zip` | 입자 ROI tab | `partCCC-NN` sub-pixel iso-contours |
| `<name>_regions.zip` | 강도 측정 tab | `rgnCCC-R`, the expression in the `region` property |
| `<name>_bleach_rois.zip` | every export (CZI with bleach regions) | Ovals or polygons |
| `<name>_line.roi` | 라인 프로파일 tab | Straight line with its width |
| `<name>_crops.zip` | image export, Crop › Crop 영역 ROI 저장, save all results | `cropN` rectangles (property `crop_region`) |
| inset `.roi` / `.zip` | Figure window | Rectangles in original-image coordinates |

## Tables (CSV)

| Per image | All images | Written by |
|---|---|---|
| `<name>_cell_rois.csv` | `cell_rois.csv` | Cell, nucleus and cytosol areas (세포질 ROI tab, save all results) |
| `<name>_cell_intensity.csv` | `cell_intensity.csv` | 세포질 ROI tab measurement |
| `<name>_particle_intensity.csv` | `particle_intensity.csv` | 입자 ROI tab, per cell |
| `<name>_particle_shape.csv` | `particle_shape.csv` | 입자 ROI tab, per particle |
| `<name>_<suffix>_summary.csv` | `<suffix>_summary_image.csv`, `<suffix>_summary_group.csv` | 입자 ROI tab summaries |
| `<name>_intensity.csv` | `intensity.csv` | 강도 측정 tab |
| `<name>_coloc2.csv` | `coloc2.csv` | Coloc 2 tab |
| `<name>_info.csv` | — | 이미지 정보 tab (save all results) |
| — | `image_groups.csv` | Image, image ID, group |
| line profile `.csv` | — | Distance + one column per channel |
| — | work log `.csv` | Time, image, image ID, action (파일 › 작업 기록 저장 (CSV)) |

## Project (`.cyproj`)

Written by **파일 › 프로젝트 저장** (Save project, `Ctrl+S`) and by
**모든 분석 결과 통합 저장** (`project.cyproj`). The image files themselves are
not included, only their paths relative to the project file (and absolute);
cell and particle ROIs, crops, groups, LUTs, tab settings, measurement
settings, the figure layout and the work log are stored with them. See
[Menus, project files and the work log](13-project-menus.md).

## Loading results back

**파일 › 불러오기 (자동 인식)…** (`Ctrl+O`) detects what each chosen file is:
a `.cyproj` opens as a project, images are added to the list, ROIs (cell
`RoiSet`, particles, crops, line, logic regions, bleach) go to the open image
with the matching image ID, otherwise to the current image, a LUT preset
`.json` is applied to every image and `image_groups.csv` restores groups.
Images that are already open are not opened again.

**파일 › 불러오기 (폴더)…** (`Ctrl+Shift+O`) scans a folder and its subfolders and:

- pairs exported TIFFs with their original image by image ID; when the
  original is not there, opens the best export in its place (raw stack
  first) and keeps the original's ID,
- loads `<name>_RoiSet.zip` into its image (by ID, or by file name for ROIs
  saved before IDs existed),
- loads `<name>_particles.zip` as particles and links
  `<name>_particles_contour.zip`, `<name>_regions.zip` and
  `<name>_bleach_rois.zip` without reading them as cells,
- loads `<name>_crops.zip` as crops and `<name>_line.roi` as the line profile,
- restores groups from `image_groups.csv`.
