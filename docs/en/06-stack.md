# 3D projection · section views (canvas icons)

[← Manual index](README.md) · [한국어](../ko/06-stack.md)

**Since v0.73** there is no 스택 tab: one of the three view icons at the canvas' top right,
**[Line profile · Sections · 3D projection]**, is on at a time; pressing it again returns to the plain XY
view. The settings are in **Preferences › 3D Stack View** and **Section View**; saving is the **3D Stack**
kind of **파일 › 내보내기…**.

## 3D projection view

- The whole canvas becomes the 3D view, drawn on the GPU (OpenGL) so it follows the mouse at once.
  Without a usable GPU it draws a CPU projection and says so in a status chip.
- **Drag** turns it freely on three axes (trackball); Shift+drag only around the screen axis, middle-drag
  moves. The angle chip and **↺** (first angle) sit on the canvas.
- Volumes are prepared ahead (preparation chip). For time series every timepoint's volume is prepared once
  (from the current timepoint outwards), so moving T shows it at once. Beyond the RAM limit they go to a
  disk cache (`.cycache`).

**Preferences › 3D Stack View**

| Item | Meaning |
|---|---|
| **Render method** | MIP: brightest value on the ray · translucent: emission-absorption · surface: where the ray first passes the threshold |
| **Rotation** | **three axes (trackball)** or **one axis (Y)** |
| **Z spacing** | **Auto** = the file metadata's Z spacing; off = type it in µm |
| **Render resolution** | XY resolution of the prepared volume (**1/2 (default)**, **original** …); lower uses less memory and time |
| **High-quality render** | **when 3D is turned on** or **when an image is picked (ahead)** |
| **Memory limit** | RAM kept for prepared volumes |
| **Follow LUT** | use the LUT tab's Min / Max / colour |
| **Selected crop only** | 3D of the selected crop only |

## Section view

Like Fiji's Orthogonal Views: the XY plane of the current Z with the X section (XZ) below and the Y
section (YZ) on the right, at one scale. Clicking or dragging the point in XY moves the cuts (white lines);
clicking a section moves Z there (yellow dashed line on the sections). **Preferences › Section View**:
**Section layout**, **Show cut lines**, **Z spacing as in 3D Stack View**.

## Saving (파일 › 내보내기 › 3D Stack)

- **3D projection image (current angle, PNG)**: at the 3D view's current angle and render method.
- **3D rotation series (one turn around Y)**, **as MP4 (off = TIFF)**.

---

The rest of this page describes the 스택 tab up to v0.72 (the 2D projection methods mean the same).

## Projection type

- **2D projection (스택을 한 장으로)**: the Z range collapsed into one image.
- **3D projection (돌려 보기)**: the volume turned by an angle and projected.

## 범위 (Range)

- **Z 슬라이스** (Z slices): first–last slice; **전체** (All) selects every slice.
- **선택한 Crop 영역만 (빠름)** (Selected crop only, faster): project only the
  crop selected in the sidebar (the crop rows under the image).

## 2D projection

**방법** (Method): Max intensity, Average intensity, Sum slices, Min
intensity, Standard deviation, Median (the same choices as ImageJ's
Z Project).

## 3D projection

| Setting | Meaning |
|---|---|
| **방법** (Method) | Brightest point (max) or Mean value along the line of view |
| **회전축** (Axis) | **Y축 (좌우로 돌리기)** turn left–right, or **X축 (위아래로 기울이기)** tilt up–down |
| **각도** (Angle) | −180° to 180°, slider or number |
| **Z 간격** (Z spacing) | **자동** switch: on = from the metadata (voxel Z / pixel size; the field and the note show the numbers), off = type it in the field (µm). If the file has no Z step, auto uses 1 pixel; enter the real step by hand. |
| **미리보기** (Preview) | Preview resolution: **빠름 (~256 px)**, **보통 (~400 px)**, **선명 (~600 px)**, **원본 해상도** |
| **새로고침 (LUT 반영)** (Refresh, apply LUT) | After changing min/max/gamma, press it to rebuild the 3D view (it is highlighted when the LUT changed). Color and show/hide apply at once. |

On the image: **left-drag** moves the view, **right-drag** rotates it
(left/right = Y axis, up/down = X axis).

The 3D structure is built once per image, Z range, crop, preview size and
timepoint; turning it afterwards only re-projects (about 0.05 s).

## LUT (투영 이미지)

- **LUT 탭과 연동 (한쪽에서 바꾸면 양쪽에 반영)** (Linked to the LUT tab): changes
  go both ways. A Sum projection's range is scaled by the number of slices.
- Off: the projection gets its own LUT, set here.
- **LUT 탭에서 다시 가져오기** (Take the LUT tab's LUT again).

## 저장 (Saving)

Choose an item in the **Tool › 스택** menu of the menu bar; a window with the options below opens.

> Since v0.59 the saves below are picked in **파일 › 내보내기…** (Export), kind **스택 투영**, instead of a menu ([Export window](17-export.md)). The files written are the same.

- **현재 투영 저장 (TIFF / MP4)…** (Current projection): an RGB image with
  the LUTs and markers plus a float32 ImageJ stack of the projected values.
  With **타임시리즈는 모든 시점 저장** every timepoint is projected and saved.
- **3D 회전 시리즈 저장 (TIFF 스택 / MP4)…** (3D rotation series): angles
  **회전** from → to, **간격** (step), as a TIFF stack.
- Choose **MP4 동영상** as the file type in the save dialog to get a movie
  instead (one frame per timepoint or angle, at **MP4 프레임 속도**, fps).
- **3D는 원본 해상도로 저장** (Save 3D at full resolution) uses the original
  resolution instead of the preview resolution.
