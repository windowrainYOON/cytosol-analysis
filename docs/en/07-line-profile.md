# 라인 프로파일 tab (line intensity profile)

[← Manual index](README.md) · [한국어](../ko/07-line-profile.md)

**Since v0.73** there is no 라인 프로파일 tab: turn on the **Line profile** icon at the canvas' top right,
drag a line on the image, and the per-channel intensity plot appears in the live box under the canvas. The
row under the plot holds **Line width**, **leave out channels hidden in the LUT**, **0–1 per channel**,
**Clear Line** and **Export…** (the **Line Profile** kind of 파일 › 내보내기). Line ROIs are read with
**파일 › 불러오기**. Button names further down are those of the tab up to v0.72; values and files are the same.

The plot's legend (channel names and line colours) is drawn outside the plot, on its left (v0.74): instead
of the number tiles (line length · per-channel maximum) the plot's white background goes on to the left and
holds the legend; the plot itself keeps its size and ratio. Saved plot figures (PNG · PDF …) keep the legend
inside as before.

## Ruler (v0.74)

Turn on the **Ruler** icon at the canvas' top right (next to Line profile) and drag a line on the image to
measure it. The line has a tick every 1 µm (longer ones every 5 µm and 10 µm) and its length beside the end
(e.g. `10.3 µm`). `Shift` = horizontal, vertical or 45°. A new line replaces the old one; turning the icon
off removes the line and its ticks (a temporary line, never saved). Zoomed far out, when 1 µm ticks would be
too dense, only the 5 µm / 10 µm ticks are drawn.

Plots each channel's raw intensity along a line, like ImageJ's RGB Profiler
(Plot Profile per channel), in the channel colors, against distance in µm.

## Drawing the line

1. Press **선 그리기 (드래그)** (Draw line) in the tab.
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

From the **Tool › 라인 프로파일** menu in the menu bar:

> Since v0.59 the saves below are picked in **파일 › 내보내기…** (Export), kind **라인 프로파일**, instead of a menu ([Export window](17-export.md)). The files written are the same.

- **CSV 저장…**: distance plus one column per channel.
- **그래프 저장 (PNG / PDF / SVG / TIFF)…** (Graph): PNG/TIFF at 300 dpi, PDF or SVG.
- With **파일 › 측정·프로파일 저장 시 ROI와 ROI가 그려진 이미지(.png)도
  함께** (on by default) the save also writes `<name>_line.roi` (ImageJ straight-line
  ROI, with its width) and `<name>_image.png` (the image with the current LUTs
  and the line) in the same folder. Choosing a `_line.roi` in **라인 프로파일 › 선 ROI 불러오기…** (or **파일 › 불러오기**) draws the line again.

## Agreement with ImageJ

Sampling is ImageJ's: bilinear interpolation, round(length) + 1 points, and
width > 1 averaged across the line as ImageJ straightens it. Values are
identical for width 1 and within 4 × 10⁻⁵ (relative) for wider lines.
