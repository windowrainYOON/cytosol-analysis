# Image stacking

Stacks files saved one per channel, per focal plane (Z) or per time point (T) into one image.
The original files stay as they are; the image list shows one stack. A stack works like any
other image in every tab, the export window and batch analysis.

## Stacked automatically

Three TIFFs whose names differ only in `Red` / `Green` / `Blue` (e.g. `Control_01_Ch1_Red.tif`,
`..._Ch2_Green.tif`, `..._Ch3_Blue.tif`) loaded together become one 3-channel image. The status
bar and the work log say how many sets were stacked.

## Stacking by hand

Pick 2 or more images in the list, right-click › **이미지 묶기…** (or **파일 › 이미지 묶기…**).

| Setting | Meaning |
|---|---|
| **쌓는 방향** | **채널** (the same field with different stains / channels), **Z** (one file per plane), **시간 (T)** (one file per time point). |
| **순서 · 채널** | Drag a row or use ▲ ▼ to reorder. **쓸 채널**: which channel of the file is used (RGB files get the channel matching the colour in the name). For channel stacks also **채널 이름** and **색**. |
| **확인** | Whether sizes and pixel sizes match. **크기가 다르면**: refuse and say so (default) / crop to the centre / pad with 0. |
| **시점 간격**, **Z 간격** | Shown only for time / Z stacks. |
| **이름** | The stack name (default: the common start of the file names). |
| **원본 파일은 묶음 아래에 접어 두기** | On (default): the source images leave the list and show greyed, folded under the stack. |
| **같은 이름 규칙의 나머지 파일도 묶기** | Other sets named the same way in the list (e.g. `Control_02_…`) are stacked with the same settings. |

## In the list

A stack row reads like `name (3채널)`; unfolded, its source files show indented in grey (not
selectable, the path in the tool tip). Only the stack row has the trash glyph. Right-click ›
**묶음 풀기** opens the source files on their own again.

Projects store the stack settings and the source paths and rebuild the stack from the sources
when opened.
