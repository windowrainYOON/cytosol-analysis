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

- **파일 › 불러오기 (자동 인식)…** (File › Load files, `Ctrl+O`), or drag files
  onto the window. An empty list shows a drop icon. **불러오기**
  also recognises projects (`.cyproj`), ROIs, crops and LUT presets (see
  [Menus, project files and the work log](13-project-menus.md#loading)). Files
  already in the list are not opened again.
- **파일 › 불러오기 (폴더)…** (Load folder)
  (`Ctrl+Shift+O`), or drop a folder: scans the
  folder and its subfolders and pairs original images, exported TIFFs and ROI
  files (`.zip` / `.roi`) by image ID (see below). If an original is missing,
  the best export (raw stack first) opens in its place; ROIs are attached to
  their image automatically. `image_groups.csv` restores groups.
- Hover over an image in the list to see its image ID, source file, group,
  linked exports and the number of cell ROIs.

### TCF: HT and FL as one image

**Preferences › 이미지 불러오기 › TCF: HT와 FL을 정렬해 한 이미지로** (TCF: align HT
and FL into one image), on by default, opens a TCF as one entry with channels `RI`, `CH0`, `CH1`, …:
fluorescence is resampled onto the HT pixel grid (pixel size around the
shared image centre plus an automatic fine registration of at most 2 µm) and
placed in Z from `3DFL/OffsetZ`. Turn it off to get HT and FL as two separate
entries. The setting applies to files added afterwards.

## Window layout

The window has three panes: the image list (left), the preview (centre) and
the tools (right: LUT, 마커, 이미지 정보 and the feature tabs), v0.58: the
image list is the window's own, lowest layer; the preview and the tools float
on it as two large rounded boxes (10 px from the window edge and from each
other, a hairline edge, no shade). The preview box is a shade darker than the
tools box. Each region has its own inner padding (20 px). The capsule
buttons at the top of the tools pane switch tabs. A feature tab's **×** (or right-click › 탭 닫기)
closes it.

- The image list and the tools pane keep their width; making the window
  larger or smaller only changes the preview.
- Drag the border between two panes to change a pane's width. The widths are
  remembered for the next start.
- The contents of a pane follow its width: rows of buttons and check boxes
  continue on the next line, and a field moves under its label when the
  row does not fit.
- In a settings card each row has its name on the left and its value or
  control at the right end, with a thin line between rows; numbers in a field
  start at the left.
- A **자동** (auto) switch sits after its label, at the end of the row (on =
  blue). Every auto / manual choice is this switch. For a single value the
  field keeps showing the value in use, greyed; an automatic size worked out
  when drawing (marker sizes) hides its field until the switch is off. Where
  auto and manual take different inputs, only the chosen side's show.
- Every settings row of a card has the same height; a value with a slider is
  one row: name – slider – number field (no arrows).
- Pop-up menus have no box: the chosen value and a round arrow cap, as wide as
  the longest choice. Click the value or the cap to open the list.
- Hover an icon-only button to see its name (and shortcut).

## Image list

- Long image names wrap onto more lines, so the whole name is always
  visible.
- Select several images with `Shift`/`Ctrl` (`⌘`) + click.
- Only **자동 그룹** (Auto group) sits at the top of the pane; everything else
  happens in the list.
- The trash icon at the end of an image name (shown on hover and on the
  selected row), right-click › **이미지를 목록에서 제거…** (Remove images from
  the list, last in the menu) or `Delete`: after **제거** (Remove) in the confirmation alert,
  the selected images leave the list (the files are not deleted). The
  alert's default button (Return) is **취소** (Cancel).

### Groups

Groups are used for the `group` column and the per-group summaries of the
measurement tabs.

- Select two or more images (or a group folder) and right-click for **그룹
  지정…** (Assign group), **그룹 이름 변경…** (Rename group) and **그룹 해제**
  (Ungroup).
- **그룹 지정…** (Assign group): puts the selected images in a group. The name
  offered is what their file names share without the trailing number
  (`abc`, `abc_0001`, `abc_0002` → `abc`); type another name or pick an
  existing group.
- **자동 그룹** (Auto group): groups images whose names differ only in the
  trailing number. Applies to the selected images when two or more are
  selected, otherwise to all images. A confirmation lists the groups first.
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
  at the same time. Its speed is set in **Preferences**.
- **Mouse wheel** (without `Cmd`/`Ctrl`): one timepoint per notch. On images
  that are not time series it scrolls the view.

### Zoom and pan

- Hold `Cmd` (Windows `Ctrl`) and drag up to zoom in around the point you
  pressed, down to zoom out. The wheel does not zoom. The speed is
  **확대/축소 드래그** (Zoom drag) in **Preferences** (default 0.6).
- `]` zooms in, `[` zooms out (around the view centre, 1.25× per press).
- **영역 확대** (Zoom to area, magnifier icon at the top right of the preview): press it and drag a rectangle; `Shift`+drag
  does the same without the button.
- **화면 맞춤** (Fit to window, the corner icon next to it): back to the whole image.
- Pan with a middle-button drag (right-button drag too when the image has no
  Z or T).

### Channels

Channels are shown or hidden with the **채널 표시** (Show channels) checkboxes,
and their colors and contrast set, in the
[LUT tab](02-lut-export.md).

## Crop regions

Crops are rectangular regions of an image that can be viewed, projected and
exported on their own. There is no Crop tab (v0.58): the **Crop** icon, first
of the icons at the top right of the canvas, handles them.

1. Switch the **Crop** icon on (blue): the image's crop regions show on the
   canvas, and dragging outside them draws a new one (`Shift`+drag: a
   square). The icon stays on after drawing, so you can keep drawing. With
   the icon off, crop regions are not drawn on the canvas.
2. While the icon is on, drag inside a region to move it.
3. Each region is listed in the left sidebar under its image, e.g.
   **Crop 1 77×77**. Picking a row selects that crop (yellow on the canvas);
   the triangle before the image name folds the rows away.
4. **Right-click a crop row or a crop on the canvas** for:
   - **이 ROI 복사** (copy, `⌘C` / `Ctrl+C`) and **붙여넣기** (paste, `⌘V` / `Ctrl+V`: a new
     crop of the same place and shape),
   - **수정** (edit): drag the 8 handles on the corners and sides to resize,
   - **점 편집** (edit points): drag a vertex, click an edge to add a point,
     `Option(⌥)`/`Alt`+click a point to delete it (polygon crop); `Esc` or a click
     elsewhere ends it,
   - **선택한 Crop만 보기** (show selected crop only), **같은 크기 이미지에 Crop 복사**
     (copy crops to images of the same size),
   - last, in red, **삭제…** (delete) and **이 이미지의 Crop 모두 삭제…** (delete all crops of
     this image); the alert's default button is **취소** (Cancel).
   The trash glyph at the end of the row and the `Delete` key delete too.
5. Saving: **파일 › 내보내기…**, kind **Crop 영역**, writes an image per crop
   (`<name>_crop1_*`) and the ImageJ ROIs `<name>_crops.zip` ([Export window](17-export.md)).
   A crop reshaped with 점 편집 is cut as its bounding rectangle with the outside set to 0.
   Loading `_crops.zip` with **파일 › 불러오기** brings the crops back.

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
