# 라인 프로파일 tab (line intensity profile)

[← Manual index](README.md) · [한국어](../ko/07-line-profile.md)

Plots each channel's raw intensity along a line, like ImageJ's RGB Profiler
(Plot Profile per channel), in the channel colors, against distance in µm.

## Drawing the line

1. Press **라인 프로파일 (선 그리기)** (Line profile, draw a line) above the
   image, or **선 그리기 (드래그)** in the tab.
2. Drag a line on the image. Hold `Shift` for a horizontal, vertical or 45°
   line.
3. **선 지우기** (Clear line) removes it.

The values are for the current Z (or MIP) and timepoint; the plot follows
Z, T and LUT color changes. The tab shows the line's length, width, plane and
end points in pixels.

## Options

| Setting | Meaning |
|---|---|
| **선 두께** (Line width, px) | 1 = values on the line. 2 or more: that many pixels across the line are averaged (ImageJ's line width) |
| **LUT에서 숨긴 채널 제외** | Leave out channels hidden in the LUT tab |
| **채널별 0–1 정규화** | Scale each channel to 0–1 so shapes can be compared |

## Saving

- **CSV 저장…** (Save CSV): distance plus one column per channel.
- **그래프 저장…** (Save graph): PNG/TIFF at 300 dpi, PDF or SVG.
- **저장할 때 선 ROI(.roi)와 선이 그려진 이미지(.png)도 함께 저장** (Also save the
  line ROI and an image with the line): `<name>_line.roi` (ImageJ straight-line
  ROI, with its width) and `<name>_image.png` (the image with the current LUTs
  and the line) in the same folder.

## Agreement with ImageJ

Sampling is ImageJ's: bilinear interpolation, round(length) + 1 points, and
width > 1 averaged across the line as ImageJ straightens it. Values are
identical for width 1 and within 4 × 10⁻⁵ (relative) for wider lines.
