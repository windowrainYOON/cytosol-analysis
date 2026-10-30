# Coloc 2 tab (colocalization)

[← Manual index](README.md) · [한국어](../ko/08-coloc2.md)

Open or close this tab with **Tool › Coloc 2 › Coloc 2 탭 열기** (Open Coloc 2 tab) in the menu bar. This tab's saves and loads are in the same **Coloc 2** menu.

Colocalization of two channels in each cell ROI, with the same calculation
as Fiji's Coloc 2 plugin (its source code ported line by line). Detect or
load cell ROIs in the [세포질 ROI tab](03-cytosol-roi.md) first, unless you
use the whole image.

## Settings

| Group | Setting | Meaning |
|---|---|---|
| **채널** | Channel 1, Channel 2 | The two channels to compare (must differ) |
| **ROI** | **세포 전체**, **세포질 (핵 제외)**, **핵** | Regions of each cell to analyse (default: whole cell and cytosol) |
| | **선택한 세포만** (Selected cell only) | Only the cell selected in the image or list |
| | **이미지 전체 (ROI 없음)** (Whole image) | No ROI, as Coloc 2 with `ROI_or_mask = <None>` |
| **데이터** | **Z**: **현재 평면 (화면의 Z 또는 MIP)** or **Z 스택 전체 (3D, ROI를 모든 Z에 적용)** | Current plane, or the whole stack with the 2D ROI applied to every slice (as Coloc 2 does with a 2D mask on a stack) |
| | **시점: 모든 시점** (All timepoints) | Every timepoint instead of the current one |
| **Coloc 2 옵션** | Threshold regression | Costes or Bisection |
| | Li Histogram Channel 1/2, Li ICQ, Spearman's Rank Correlation, Manders' Correlation, Kendall's Tau Rank Correlation, 2D Intensity Histogram, Costes' Significance Test | The plugin's algorithm checkboxes (all on by default) |
| | PSF (px), Costes randomisations | Block size and number of shuffles for the Costes test (defaults 3 and 10) |
| | Display Images in Result, Display Shuffled Images | Extra images in the results, as in the plugin |

If the two channels have different bit depths, Coloc 2 itself refuses to
run; here they are computed as 32-bit float with a warning.

## Running

- **계산 (현재 이미지)** (Calculate, current image).
- **모든 이미지** (All images): every image with ROIs, channels matched by name.

## Results

The results table has one row per cell, region and timepoint with Pearson R,
R above threshold, tM1, tM2, M1, M2, ICQ, Spearman, Kendall and Costes P.
Clicking a row selects that cell in the image and shows its plots (2D
histogram with the regression line and thresholds, Li plots, shuffled image)
and all values, with the plugin's warnings.

## Saving

In the **Tool › Coloc 2** menu of the menu bar:

| Menu item | File |
|---|---|
| **CSV 저장 (현재 이미지)…** | Current image: one row per ROI, columns named as in Coloc 2 |
| **모든 이미지 CSV 저장 (폴더)…** | `<name>_coloc2.csv` per image and `coloc2.csv` for the set |
| **그래프 저장…** | The plots of the selected row |
| **PDF 리포트 저장…** | Histograms and every value of the selected ROI, like the plugin's PDF |

**모든 분석 결과 통합 저장** (Save all results, `Ctrl+Shift+E`) also writes the Coloc 2 CSVs.

## Agreement with Fiji

Checked against the Coloc 2 code itself (`scripts/imagej_reference`): every
value except the Costes randomisation agrees to about 10⁻¹⁰ (relative). The
Costes test is random in both programs; the shuffled mean and SD agree
within that spread.
