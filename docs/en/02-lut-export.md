# LUT · 내보내기 tab (display and export)

[← Manual index](README.md) · [한국어](../ko/02-lut-export.md)

This tab sets how each channel is displayed (its LUT) and exports images.
The LUTs set here are used by the preview, every RGB export, the 스택 tab
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
- **LUT 프리셋 저장… / 불러오기…** (Save / load LUT preset): LUTs as a JSON file.

## Export — 일괄 저장 (TIFF / MP4)

1. **범위** (Scope): **전체 이미지** (whole image, `<name>_full_*`) and/or
   **Crop 영역 각각** (each crop region, `<name>_crop1_*`, `<name>_crop2_*`, …).
2. What to write:
   - **합성 RGB (LUT 적용)**: composite RGB with the current LUTs, markers
     (scale bar, time stamp) and µm calibration, 8-bit.
   - **채널별 RGB**: one RGB image per channel.
   - **원본값 스택 (ImageJ, 모든 Z)**: an ImageJ hyperstack of the original
     values for all Z, with the channel LUTs, display ranges and µm
     calibration, ready for measuring in Fiji.
3. Time series:
   - **타임시리즈는 모든 시점 저장 (끄면 현재 시점만)** (Save every timepoint;
     off = current timepoint only). RGB outputs become T-frame stacks with
     the time stamp on each frame; the raw stack becomes a TZCYX hyperstack.
   - **타임시리즈 RGB 형식** (RGB format for time series): **TIFF**, **MP4
     (동영상)** (H.264 movie, one frame per timepoint, at the fps next to it)
     or **TIFF + MP4**. Single-timepoint images and raw stacks are always TIFF.
4. **이미지별 폴더에 나눠 저장** (Separate folder per image; on by default,
   shared with the 세포질 ROI tab): each image's files go into
   `<chosen folder>/<name>_<image ID>/`.
5. **현재 이미지만 저장…** (Current image only) or **모든 이미지 저장…** (All
   images), then choose the folder.

CZI bleach regions are written as `<name>_bleach_rois.zip` with every export,
and drawn into RGB images when the [마커 tab](05-markers.md) says so.

## Export everything — 모든 데이터 일괄 저장

**모든 데이터 일괄 저장 (TIFF + ROI, 이미지별 폴더)…** (also **파일** menu,
`Ctrl+Shift+E`) makes one folder per image and puts in it everything that
exists for that image:

- the TIFF/MP4 exports above,
- `<name>_RoiSet.zip` and `<name>_cell_rois.csv` (cell ROIs and areas),
- the cell, particle and logic-region intensity CSVs and `<name>_particles.zip`,
- `<name>_info.csv` (image information), `<name>_coloc2.csv` (if Coloc 2 was run),

plus, in the top folder, the combined `cell_rois.csv`, `coloc2.csv`, the
intensity CSVs with their summaries and `image_groups.csv`.

See [Output files](12-output-files.md) for every file name.
