# Getting started: images, viewing, groups

[← Manual index](README.md) · [한국어](../ko/01-getting-started.md)

## Supported files

| Format | What is read |
|---|---|
| Tomocube `.TCF` | HT (refractive index) and FL (fluorescence) volumes, time series, the stored 2D MIP |
| Zeiss `.czi` | All channels, Z, T, scenes, display colors, frame times, bleach regions (FRAP) |
| Olympus/Evident `.oir` | Channels, Z, T, FluoView LUT colors |
| `.tif` / `.tiff` | ImageJ hyperstacks and OME-TIFF (T/Z/C, pixel size, channel names and colors); a plain multi-page TIFF is a Z stack; an RGB TIFF gives channels R/G/B |

The pixel size, Z step, channel names/colors and the value range of each
channel (e.g. 0–4095 for 12-bit) are taken from the file's metadata.

## Adding images

- **파일 추가…** (Add files) under the image list, **파일 › 불러오기 (자동 인식)…**
  (File › Load files, `Ctrl+O`), or drag files onto the window. **불러오기**
  also recognises projects (`.cyproj`), ROIs, crops and LUT presets (see
  [Menus, project files and the work log](13-project-menus.md#loading)). Files
  already in the list are not opened again.
- **폴더 불러오기…** (Load folder), **파일 › 불러오기 (폴더)…**
  (`Ctrl+Shift+O`), or drop a folder: scans the
  folder and its subfolders and pairs original images, exported TIFFs and ROI
  files (`.zip` / `.roi`) by image ID (see below). If an original is missing,
  the best export (raw stack first) opens in its place; ROIs are attached to
  their image automatically. `image_groups.csv` restores groups.
- Hover over an image in the list to see its image ID, source file, group,
  linked exports and the number of cell ROIs.

### TCF: HT and FL as one image

**TCF: HT와 FL을 정렬해 한 이미지로** (TCF: align HT and FL into one image), on
by default, opens a TCF as one entry with channels `RI`, `CH0`, `CH1`, …:
fluorescence is resampled onto the HT pixel grid (pixel size around the
shared image centre plus an automatic fine registration of at most 2 µm) and
placed in Z from `3DFL/OffsetZ`. Turn it off to get HT and FL as two separate
entries. The setting applies to files added afterwards.

## Window layout

The window has three panes: the image list (left), the preview (centre) and
the tools (right: LUT, 이미지 정보 and the feature tabs).

- The image list and the tools pane keep their width; making the window
  larger or smaller only changes the preview.
- Drag the border between two panes to change a pane's width. The widths are
  remembered for the next start.
- The contents of a pane follow its width: rows of buttons and check boxes
  continue on the next line, and a field moves under its label when the
  row does not fit.

## Image list

- Long image names wrap onto more lines, so the whole name is always
  visible.
- Select several images with `Shift`/`Ctrl` (`⌘`) + click.
- **목록에서 제거** (Remove from list) or `Delete`: removes the selected images
  from the list (the files are not deleted).

### Groups

Groups are used for the `group` column and the per-group summaries of the
measurement tabs.

- **그룹 지정…** (Assign group): puts the selected images in a group. The name
  offered is what their file names share without the trailing number
  (`abc`, `abc_0001`, `abc_0002` → `abc`); type another name or pick an
  existing group.
- **자동 그룹** (Auto group): groups images whose names differ only in the
  trailing number. Applies to the selected images when two or more are
  selected, otherwise to all images. A confirmation lists the groups first.
- **그룹 이름 변경…** (Rename group), **그룹 해제** (Ungroup).
- Groups appear as folders in the list; click a folder to select all its
  images. Saving measurements or exports writes `image_groups.csv`, which
  folder loading reads back.

## Viewing

### Z (slices)

- The vertical slider left of the image: bottom = first slice. The label
  shows the slice number and its height in µm. The mouse wheel over the
  slider, `↑` `↓` and `PageUp` `PageDown` also move it.
- **MIP**: show the maximum-intensity projection of all slices. Moving the
  slider switches back to single slices.
- TCF files are read lazily: one slice reads only that HT plane and the few
  FL planes around it, so browsing stays fast and memory use stays low.

### T (time series)

- Time series (TCF, CZI, OIR with a T axis) get a **T** slider under the
  image. The image follows the slider while you drag it; histograms and the
  line profile update when you release it.
- With a Z stack, every timepoint of the current Z (or MIP) is read ahead in
  the background (up to 1.5 GB; progress in the status bar), so scrubbing
  only redraws.
- **Right-drag on the image** moves through T (left/right) and Z (up/down)
  at the same time. Its speed is set in **파일 › 설정…** (Settings).
- **Mouse wheel** (without `Cmd`/`Ctrl`): one timepoint per notch. On images
  that are not time series it scrolls the view.

### Zoom and pan

- Hold `Cmd` (Windows `Ctrl`) and drag up to zoom in around the point you
  pressed, down to zoom out. The wheel does not zoom. The speed is
  **확대/축소 드래그** (Zoom drag) in **파일 › 설정…** (default 0.6).
- `]` zooms in, `[` zooms out (around the view centre, 1.25× per press).
- **영역 확대** (Zoom to area): press it and drag a rectangle; `Shift`+drag
  does the same without the button.
- **화면 맞춤** (Fit to window): back to the whole image.
- Pan with a middle-button drag (right-button drag too when the image has no
  Z or T).

### Channels

Channels are shown or hidden with the **채널 표시** (Show channels) checkboxes,
and their colors and contrast set, in the
[LUT tab](02-lut-export.md).

## Crop regions

Crops are rectangular regions of an image that can be viewed, projected and
exported on their own. Choose **Tool › Crop › Crop 탭 열기** (Open Crop tab) in the menu
bar to get the **Crop** tab on the right.

1. Press **Crop 추가 (드래그)** (Add crop, drag) and drag on the image.
   `Shift`+drag draws a square. Repeat for more regions; each is numbered on
   the image and listed in the tab.
2. Drag inside an existing crop to move it.
3. **선택한 Crop만 보기** (Show selected crop only) previews one region.
4. **선택 삭제** / **전체 삭제** (Delete selected / Delete all).
5. **같은 크기 이미지에 복사** (Copy to images of the same size): copies this
   image's crops to every other image with the same size; move them per
   image afterwards by dragging.
6. Saving: image exports write every crop separately (`<name>_crop1_*`) and
   the regions themselves as ImageJ rectangles, `<name>_crops.zip`.
   **Crop › Crop 영역 ROI 저장** (Save crop ROIs) saves only the regions.
   Loading that file with **Crop › Crop 영역 ROI 불러오기…** (or
   **파일 › 불러오기**) brings the crops back.

## Image ID

Every image gets an ID such as `A9F3-2596-73B6`, derived from what the
microscope wrote into the file (TCF `UniqueID`, CZI file GUID, OIR
acquisition time and channel UUIDs, OME-TIFF `UUID`, otherwise a hash of the
file content). It survives renaming and copying and is shown under the
preview and in the list tooltip.

Every export carries it: TIFFs (ImageJ `Info` / `Properties`:
`CytosolImageID`, `CytosolSource`; in Fiji Image › Show Info), every ROI in a
RoiSet, and an `image_id` column in every CSV. This is how
**폴더 불러오기…** pairs files, and how **불러오기** (Load) decides which image
a ROI file belongs to.

## Next

- Adjust display and export images: [LUT tab and image export](02-lut-export.md)
- Save the work and carry on later: [Menus, project files and the work log](13-project-menus.md)
- Find cells: [세포질 ROI tab](03-cytosol-roi.md)
