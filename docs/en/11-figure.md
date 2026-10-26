# Figure window (Figure 만들기)

[← Manual index](README.md) · [한국어](../ko/11-figure.md)

Lays images out as a table with row and column labels, zoom insets and scale
bars, ready for a paper figure. Open it with **Tool › Figure…** or
`Ctrl+Shift+F`. Saving the figure and saving/loading inset ROIs use the
buttons in this window. The figure layout is also saved in the project file.

Cells show the loaded images with their current LUTs; changes made in the
main window appear when you come back to the figure window.

## The table

- **행 추가 / 열 추가** (Add row / column), **행 삭제 / 열 삭제** (Delete),
  **행 ▲ / 행 ▼ / 열 ◀ / 열 ▶** (Move).
- **Double-click a row or column header** to edit its label (Enter for a new
  line) and its text color (**색상…**, **기본 색상** = default). Right-click a
  header for **이름/색상 수정…**, **위에/아래에 행 삽입**, **왼쪽에/오른쪽에 열 삽입**.
- Click a cell to select it; the panels below act on the selected cell.

## 선택한 칸 (Selected cell)

| Control | Action |
|---|---|
| **이미지** (Image) | Which loaded image the cell shows |
| **영역** (Region) | **전체 이미지** (whole image) or one of the image's crop regions |
| **파일…** (File) | Put a PNG/TIFF file in the cell instead (e.g. an earlier export) |
| **메인 창 표시 채널 따르기** (Follow the main window's channels) | Use the channels shown in the main window |
| **채널 조합** (Channel combination) | Checkboxes per channel, any combination for this cell only (unticks the option above); **모두 켜기 / 모두 끄기** |
| **이 행을 채널별 + Merged로 채우기** | Fill the row with one column per channel plus the merged image in the last column |
| **열 이름을 채널 이름/색으로** | Name the columns after the channels of this row, in their LUT colors |
| **이 행의 다른 칸도 같은 이미지/영역으로** | Give the row's other cells the same image and region, keeping their channel choice |
| **칸 비우기** (Clear cell) | Empty the cell |

## 확대 영역 (inset) — zoom insets

1. Press **확대 영역 그리기 (드래그)** and drag a box on the cell preview
   (`Shift`+drag: square). Without drawing mode, drag an existing box to move it.
2. **표시 방식** (Placement):
   - **이미지 안 (모서리에 겹쳐서)** (inside the image): the magnified copy in a
     **모서리** (corner: 왼쪽 위 / 오른쪽 위 / 왼쪽 아래 / 오른쪽 아래), at
     **크기** (% of the cell width).
   - **다른 칸에 따로** (in another cell): shown in its own cell; **넣을 칸**
     (target cell) can be any cell, or **오른쪽에 새 열 삽입** / **아래에 새 행
     삽입** (insert a new column to the right / a new row below). By default the
     free cell to the right, else a new column. A cell that already holds an
     image is overwritten.
3. **이 행 전체에 적용** / **이 열 전체에 적용**: the same inset in every cell of
   the row/column with the same image size (separate zoom cells keep the same
   offset, e.g. a zoom row under the image row).
4. **삭제**: delete the selected inset.

### Same size, copy and paste

- **같은 크기로 그리기** (Draw at a fixed size): a click or drag places a box of
  the size (px) given next to it, in every cell.
- **모든 칸에 이 크기 적용** (Apply this size to all cells): resizes every inset
  of the figure to that size, keeping each box's centre.
- **영역 복사** (Copy inset) → **붙여넣기** (Paste) to the selected cell at the
  same position of the original image, or **여러 칸에 붙여넣기…** (Paste into
  several cells), optionally **그 칸의 기존 확대 영역 지우고 넣기** (replacing
  their insets).
- **ROI 저장…** (Save ROI): the selected inset as ImageJ `.roi`, or `.zip` for
  all insets of the cell; coordinates are in the original image, so they open
  in ImageJ directly. **ROI 불러오기…** adds the rectangles of `.roi` / `.zip`
  files as insets.

## 레이아웃 (Layout)

| Setting | Meaning |
|---|---|
| **배경** | **검은 배경** / **흰 배경** (labels switch to white/black); **칸 테두리** (cell borders) |
| **칸 너비** | Cell width (inch) |
| **세로/가로 비** | Cell aspect; **자동 (첫 이미지)** = from the first image |
| **칸 간격** | Gap between cells (inch) |
| **글꼴**, **글자 크기**, **굵게** | Label font, size (pt), bold |
| **Scale bar** | One length for every cell (**자동** or fixed µm) and position |
| **칸마다 길이 글자** | Write the length in every cell |
| **아래에 "(Scale bar = … µm)"** | A caption under the figure instead |
| **Inset에도 scale bar** | Scale bars in the insets too (own length) |
| **상자 색** | Color of the inset boxes |

## 내보내기 (Export)

**해상도** (Resolution, default 300 dpi) and **Figure 저장… (PNG / TIFF / PDF /
SVG)** (`Ctrl+S`). PNG and TIFF are written at the chosen dpi; PDF and SVG keep
the text editable. The size in inches and pixels is shown under the preview.
