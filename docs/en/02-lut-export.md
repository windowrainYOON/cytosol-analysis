# LUT tab and image export

[← Manual index](README.md) · [한국어](../ko/02-lut-export.md)

The **LUT** tab (always open) sets how each channel is displayed (its LUT);
it scrolls as one page: **모든 채널 LUT를 전체 이미지에 적용** (apply all
channel LUTs to every image) on top, then channel visibility, then every
channel's LUT. The [marker settings](05-markers.md) have their own tab. Images are
saved from **파일 › 내보내기…** (`Ctrl+E`, [Export window](17-export.md)). The LUTs set here are used by the preview, every RGB export, the 스택 tab
(when linked) and the Figure window.

## Showing channels

**채널 표시** (Show channels): one checkbox per channel, in one row, with
**모두 켜기** / **모두 끄기** (All on / All off). Hidden channels are left out
of the preview and of composite exports, and can be left out of
measurements (**LUT에서 숨긴 채널 제외**, Exclude channels hidden in the LUT).

## Channel LUT (one panel per channel)

| Control | What it does |
|---|---|
| Color button | Pick the channel color |
| **Auto** | Min/max from the 0.5–99.8 percentiles of the current image |
| **Min/Max** | Min/max = the current image's data minimum–maximum |
| Histogram | Drag on it to set min/max |
| **Min**, **Max** | Slider or number |
| **Gamma** | 0.1–5 (1 = linear) |
| **전체 이미지에 적용** (Apply to all images) | Copy this channel's LUT to the same channel of every loaded image |

The sliders and histogram span the value range the file can hold, read from
its metadata (e.g. 0–4095 for 12-bit, 0–255 for 8-bit); it is printed under
the histogram as **파일 범위** (file range), or **데이터 범위** (data range)
when the file has no such information. The starting min/max is the automatic
percentile range.

Channels are matched between images by channel name; by position only
between files of the same type with the same channel count.

## Batch apply — 일괄 적용

- **모든 채널 LUT를 전체 이미지에 적용** (Apply all channel LUTs to all images).
- **색상도 함께 적용** (Apply colors too): when off, only min/max/gamma are
  copied and each image keeps its colors.
- LUT presets: **LUT › LUT 프리셋 저장…** saves the current image's LUTs as a
  JSON file; **LUT › LUT 프리셋 불러오기…** (or choosing the file in
  **파일 › 불러오기 (자동 인식)…**) applies it to every image.

## Saving images

Images (composite RGB, RGB per channel, raw-value stack, time series as TIFF / MP4) and
crop regions are saved from **파일 › 내보내기…** (`Ctrl+E`), kinds **이미지** and
**Crop 영역**. The former **LUT › 이미지 내보내기** and **모든 분석 결과 통합 저장** are
merged into that one window. Items and file names: [Export window](17-export.md) and
[Output files](12-output-files.md).

CZI bleach regions are saved with every image export as `<name>_bleach_rois.zip`, and
drawn on RGB images when switched on in the [marker tab](05-markers.md).
