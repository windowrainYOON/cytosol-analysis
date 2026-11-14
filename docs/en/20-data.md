# Viewing measured data (v0.64)

Tabs are where you choose what to measure and measure it; the graph window is where the data is
looked at.

## Measure bar at the bottom of the inspector (v0.68)

Tabs that measure (세포질 ROI, 입자 ROI, 강도 측정, 등거리 띠, Coloc 2, FRAP, 입자 추적, mitoROI) show two
buttons fixed at the bottom of the inspector: **이 이미지만 측정** (Measure This Image) and **전체 이미지
측정** (Measure All Images). They stay put while the page scrolls; one line above them shows the tab's
state. Tabs without measurement (LUT, markers, image info, line profile, stack) hide the bar. The
measure / run buttons inside the tabs moved to this bar.

An inspector page scrolls as one page only: lists and tables inside it (cell list, FRAP group table,
image info tables) grow to their rows instead of scrolling on their own, and the result tables of
mitoROI, 입자 추적 and Coloc 2 became 「그래프 ›」 rows in the data card (the whole table is in the graph
window's data list).

## The two cards of a measuring tab

The 세포질 ROI, 입자 ROI, 강도 측정 and 등거리 띠 tabs end with the same two cards.

- **측정 항목**: intensity (per channel) chips (Mean, StdDev, Min, Max, IntDen, RawIntDen), **측정할
  채널** chips (kept by channel name), **LUT에서 숨긴 채널 제외**.
- **데이터**: a state line (e.g. "12 이미지 중 12개 측정됨", or how many images must be measured again)
  and one line per table the tab makes: its name ("feature · one point", e.g. `입자 ROI · 세포`,
  `입자 ROI · 그룹 요약`), rows · images, state (최신 / 설정 바뀜) and **그래프 ›** (a new graph of this
  table in the graph window). Buttons: **모든 이미지 측정** and **현재 이미지만**.

The result table in the inspector and its automatic refresh are gone. When ROIs or measured items
change, that image's table becomes "설정 바뀜"; it is measured again when a measure button is
pressed or when the table is opened in the graph window (only the changed images).

## Where values are seen

- **Values on the ROI**: with a measuring tab shown, hovering a cell ROI shows that cell's values
  under its name and area (current image only).
- **Red dot on a tab chip**: the tab's tables have rows (any image); the chip's tool tip lists them.
- **Live box**: a card under the canvas (below the T slider) computed for the current image and time
  point only: big numbers (with the change from the previous value) and a small graph; ⌄ folds it.
  Cells (count, outside the size range, on the edge, without a nucleus; area histogram), particles
  (count, per cell, median area, small pieces with a noise warning; area histogram), intensity
  (region areas), bands (bands, cells; per-cell band curves), FRAP (mobile fraction, t½, recovery
  now, largest drift; the recovery curve, moved here from the tab), line profile (length, maximum
  per channel; the profile, moved here), Coloc 2 (Pearson r, Manders M1 / M2; its plot, moved here).
- **Graph window › 데이터 list**: tables by feature (rows, a mark when settings changed); clicking one
  opens 새 그래프 (kind → axes → groups). **CSV 불러오기…** is the last entry. A header above the graph
  names the table, rows, images, groups and columns; the table pop-up below has **열 설명** (column,
  shown name, kind, unit, meaning, ImageJ / source).
- **측정 현황 · 일괄 분석** (View menu, 파일 › 측정 현황 · 일괄 분석…): images by group × data tables,
  each cell 최신 · n rows / 설정 바뀜 / empty. Double-click opens the image in that tab, right-click
  measures that cell again. Toolbar: **그룹 · 분석 고르기…**, **일괄 분석 실행**, **바뀐 것 다시 측정
  (n)**, **내보내기…**. It replaces the former batch results window.
