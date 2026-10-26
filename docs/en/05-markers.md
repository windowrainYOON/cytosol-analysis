# 마커 tab (scale bar, time stamp, bleach ROIs)

[← Manual index](README.md) · [한국어](../ko/05-markers.md)

Open this tab with **Tool › 마커** (it appears on the right; turn the item off to close it). Its results are saved from **파일 › 내보내기** (File › Export).

The markers set here are drawn on the preview and burned into every RGB
export (TIFF and MP4) and 스택 tab save. Raw-value stacks never get
markers. Number fields showing **자동** (Auto) use a value fitted to the
image size; type a number to fix it.

## Size marker (scale bar)

Tick the group title to turn the scale bar on or off.

| Setting | Meaning |
|---|---|
| **마커 길이** (Bar length) | In µm. **자동**: about 20 % of the image width, rounded to 1/2/5/10/20/25/50… µm, from the file's pixel size |
| **위치** (Position) | lower right, lower left, upper right, upper left |
| **글자 표시 (예: 10 µm)** | Show the length as text |
| **글자 크기** (Font size), **마커 두께** (Bar thickness) | px |
| **글자-마커 간격** (Text–bar gap), **가장자리 여백** (Edge margin) | px |
| **색** (Color) | Bar and text color |

## Time-series marker (time stamp)

Drawn only on images with two or more timepoints. Times come from the file
(e.g. the CZI `TimeStamps`).

| Setting | Meaning |
|---|---|
| **위치** (Position) | Default upper left |
| **글자 표시** (Show text) | Show the time as text |
| **단위** (Unit) | `auto`, `s`, `min`, `h`, `hh:mm:ss`, `mm:ss`, `frame` |
| **소수점 자리** (Decimals) | 0–3 |
| **앞 글자** (Prefix) | Text before the time, e.g. `t = ` |
| **시간 보정** (Time offset) | Seconds added to every time, e.g. a negative value so the treatment starts at 0 |
| **글자 크기**, **가장자리 여백**, **색** | As for the scale bar |
| **진행 막대 표시** (Show progress bar) | A bar that grows with time; **막대 길이** (% of the image width, default 25), **막대 두께**, **글자-막대 간격** |

## Bleach ROI (bleach regions recorded in the file)

For Zeiss CZI files from FRAP and similar experiments: the regions that were
bleached (from the executed bleach events, otherwise the regions marked for
bleaching in the experiment). The box lists each region's size in px and µm.

| Setting | Meaning |
|---|---|
| **화면에 표시** (Show on screen) | Show/hide the outlines on the preview |
| **저장하는 RGB 이미지(합성·채널별, MP4)에 선 포함** | Draw the outlines into exported RGB TIFFs / MP4s (never into the raw stack) |
| **영역 이름 표시** (Show region names) | Label each outline |
| **선 두께** (Line width), **색** (Color) | Outline style |

Every export also writes the regions as ImageJ ROIs, `<name>_bleach_rois.zip`
(ovals for circles, sub-pixel polygons otherwise); folder loading attaches
that file back to the image. Bleach settings (laser, iterations, the frames
after each bleach) are listed in the [이미지 정보 tab](10-image-info.md).

When an image has no recorded bleach regions, the box says
**이 이미지에는 bleach 영역 기록이 없습니다** (no bleach regions recorded).
