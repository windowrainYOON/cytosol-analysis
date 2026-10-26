# Cytosol Viewer 사용 설명서 (한국어)

[English manual](../en/README.md)

Cytosol Viewer(v0.23)는 Tomocube TCF, Zeiss CZI, Olympus/Evident OIR, TIFF
이미지를 열어 세포·핵·세포질 ROI를 찾고, ImageJ/Fiji와 같은 방식으로 측정한
뒤 이미지, ROI, 표, figure로 내보내는 프로그램입니다.

설명서에 나오는 **굵은 글씨**는 화면에 보이는 버튼·항목 이름 그대로입니다.

## 창 구성

- **왼쪽 패널**: 이미지 목록, Crop 목록, **Figure 만들기…**
- **가운데**: 이미지. 왼쪽에 Z 슬라이더, 아래에 T 슬라이더, 위에 보기 버튼
- **오른쪽 패널**: 아래 탭들
- **메뉴**: **파일**, **Figure**

## 기능별 설명서

| 설명서 | 내용 |
|---|---|
| [시작하기: 이미지 열기·보기·그룹](01-getting-started.md) | 파일·폴더 추가, 이미지 목록, 그룹, TCF HT/FL 정렬, Z/T 이동, 확대, Crop, 이미지 ID |
| [LUT · 내보내기 탭](02-lut-export.md) | 채널 표시(LUT), 일괄 LUT 적용, 프리셋, TIFF/MP4 저장, 모든 데이터 일괄 저장 |
| [세포질 ROI 탭](03-cytosol-roi.md) | 세포·핵·세포질 ROI 자동 검출과 수정, ImageJ ROI 파일, 세포 강도 측정 |
| [입자 ROI 탭](04-particle-roi.md) | 입자(점·응축체) 검출, 세포별·입자별 측정, 형태, 요약 |
| [마커 탭](05-markers.md) | Scale bar, 타임 스탬프, CZI bleach ROI |
| [스택 탭](06-stack.md) | Z 스택 2D 투영, 3D 회전 보기, 저장 |
| [라인 프로파일 탭](07-line-profile.md) | 선을 따라 채널별 강도 그래프 (ImageJ RGB Profiler) |
| [Coloc 2 탭](08-coloc2.md) | 세포별 공존(colocalization) 분석 (Fiji Coloc 2) |
| [강도 측정 탭](09-intensity.md) | 논리식 영역(예: `cyto - particle`)의 강도, 그리고 측정 탭들이 함께 쓰는 측정 결과 표 |
| [이미지 정보 탭](10-image-info.md) | 획득 메타데이터 (레이저, 검출기, 대물렌즈, bleaching) |
| [Figure 창](11-figure.md) | 행·열 이름, 확대 inset, scale bar가 있는 figure 표; PNG/TIFF/PDF/SVG |
| [저장되는 파일](12-output-files.md) | 프로그램이 쓰는 모든 파일과 폴더 불러오기 |

## 단축키와 마우스

| 동작 | 방법 |
|---|---|
| 파일 열기 | `Ctrl+O` (macOS `⌘O`), 또는 파일·폴더를 창에 끌어다 놓기 |
| 폴더 불러오기 (이미지·TIFF·ROI를 ID로 짝짓기) | `Ctrl+Shift+O` |
| TIFF로 일괄 저장 | `Ctrl+E` |
| 모든 데이터 일괄 저장 (이미지별 폴더) | `Ctrl+Shift+E` |
| Figure 창 | `Ctrl+Shift+F`, 창 안에서 저장은 `Ctrl+S` |
| 확대·축소 | 마우스 휠, **영역 확대** 또는 `Shift`+드래그로 사각형, 원래대로는 **화면 맞춤** |
| 화면 이동 | 가운데 버튼 드래그 (Z·T가 없는 이미지는 오른쪽 버튼 드래그도) |
| T와 Z 이동 | 이미지 위에서 오른쪽 버튼 드래그: 좌우 = T, 위아래 = Z |
| Z 슬라이스 | Z 슬라이더, 슬라이더 위에서 휠, `↑` `↓` / `PageUp` `PageDown` |
| 목록에서 이미지 제거 | 선택 후 `Delete` / `Backspace` |
| 세포 ROI 수정 | `V` 선택, `A` 더하기, `S` 빼기, `N` 새 세포, `Delete` 세포 삭제, `Ctrl+Z` / `Ctrl+Shift+Z` 되돌리기/다시 실행 |

## 논문에 인용할 때

Methods 문장은 저장소 [README](../../README.md#methods-statement)에 있습니다.
