# 이미지 정보 tab (image information)

[← Manual index](README.md) · [한국어](../ko/10-image-info.md)

Shows the acquisition settings stored in the file of the current image, as
two tables, for checking experiments and writing Methods sections.

## 채널별 획득 설정 (Acquisition settings per channel)

One column per channel, as far as the file records them:

- fluorophore and its excitation/emission wavelengths,
- laser wavelength and laser intensity (the stored software setting, %),
- the laser line's rated maximum and the nominal power (maximum × setting),
- exposure time, or pixel dwell / frame time / averaging,
- detector, detector voltage (gain), digital gain, offset, detection range,
- pinhole (µm and Airy units).

The laser intensity is the software setting. The nominal power refers to the
fibre input; the actual power at the sample is not in any file.

## 이미지 · 장비 · Bleaching (Image, instrument, bleaching)

- Image size, pixel size and field of view, Z step, number of slices,
  frame interval and total duration.
- Objective (name, NA, immersion), microscope and acquisition software.
- For CZI with bleaching (FRAP): bleach laser and intensity, iterations,
  duration, number of bleaches, the frames that follow each bleach, the
  pre-bleach frames, and each bleach ROI's position and size (the ROIs
  themselves are drawn by the [마커 tab](05-markers.md)).
- For OIR with stimulation (FRAP): the stimulating laser and intensity, the
  repeat count, the pre-bleach frames and the stimulation regions. The
  [FRAP 측정 tab](14-frap.md) uses these bleach regions and frames.

## What each format gives

| Format | Contents |
|---|---|
| CZI | Read fully |
| OIR | Laser %, PMT HV / offset / gain, pinhole, dye, scan speed |
| TCF | FL Ex/Em, light intensity %, exposure |
| TIFF | Whatever the ImageJ / OME metadata stores |

## Copying and saving

- **표 복사** (Copy tables, button in the tab): both tables as tab-separated
  text, to paste into Excel.
- **Tool › 이미지 정보 › CSV 저장…** (Image info menu › Save CSV).
  **모든 분석 결과 통합 저장** (Save all results, `Ctrl+Shift+E`) also writes
  `<name>_info.csv` per image.
- **이미지 정보 › 원본 메타데이터 저장…** (Raw metadata): the complete metadata in the
  file (CZI/OIR XML, TCF attributes), unchanged.
