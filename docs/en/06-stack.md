# 스택 tab (Z projections and 3D views)

[← Manual index](README.md) · [한국어](../ko/06-stack.md)

Open or close this tab with **스택 › 스택 탭 열기** (Open 스택 tab) in the menu bar. This tab's saves and loads are in the same **스택** menu.

While this tab is open, the image area shows its projection instead of a
single slice. It needs an image with a Z stack; the whole stack is loaded
when the tab opens (status: **Z 스택 불러오는 중…**) and released afterwards.

## Projection type

- **2D projection (스택을 한 장으로)**: the Z range collapsed into one image.
- **3D projection (돌려 보기)**: the volume turned by an angle and projected.

## 범위 (Range)

- **Z 슬라이스** (Z slices): first–last slice; **전체** (All) selects every slice.
- **선택한 Crop 영역만 (빠름)** (Selected crop only, faster): project only the
  crop selected in the list of the **Crop** tab (**Crop › Crop 탭 열기**).

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
| **Z 간격** (Z spacing) | **자동** (from the metadata: voxel Z / pixel size; the note shows the numbers) or **수동** (manual, µm). If the file has no Z step, auto uses 1 pixel; enter the real step by hand. |
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

Choose an item in the **스택** menu of the menu bar; a window with the options below opens.

- **현재 투영 저장 (TIFF / MP4)…** (Current projection): an RGB image with
  the LUTs and markers plus a float32 ImageJ stack of the projected values.
  With **타임시리즈는 모든 시점 저장** every timepoint is projected and saved.
- **3D 회전 시리즈 저장 (TIFF 스택 / MP4)…** (3D rotation series): angles
  **회전** from → to, **간격** (step), as a TIFF stack.
- Choose **MP4 동영상** as the file type in the save dialog to get a movie
  instead (one frame per timepoint or angle, at **MP4 프레임 속도**, fps).
- **3D는 원본 해상도로 저장** (Save 3D at full resolution) uses the original
  resolution instead of the preview resolution.
