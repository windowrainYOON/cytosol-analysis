# Coloc 2 탭 (공존 분석)

[← 설명서 목차](README.md) · [English](../en/08-coloc2.md)

**Tool › Coloc 2**를 켜면 오른쪽에 이 탭이 열리고, 끄면 닫힙니다. 결과는 **파일 › 내보내기**에서 저장합니다.

두 채널의 공존(colocalization)을 세포 ROI마다 계산합니다. Fiji Coloc 2 플러그인과
같은 계산입니다(원본 코드를 한 줄씩 옮김). 이미지 전체로 계산할 때가 아니면 먼저
[세포질 ROI 탭](03-cytosol-roi.md)에서 세포 ROI를 검출하거나 불러오세요.

## 설정

| 묶음 | 항목 | 의미 |
|---|---|---|
| **채널** | Channel 1, Channel 2 | 비교할 두 채널(서로 달라야 함) |
| **ROI** | **세포 전체**, **세포질 (핵 제외)**, **핵** | 세포마다 계산할 영역(기본: 세포 전체와 세포질) |
| | **선택한 세포만** | 이미지나 목록에서 선택한 세포만 |
| | **이미지 전체 (ROI 없음)** | ROI 없이. Coloc 2에서 `ROI_or_mask = <None>`과 같음 |
| **데이터** | **Z**: **현재 평면 (화면의 Z 또는 MIP)** 또는 **Z 스택 전체 (3D, ROI를 모든 Z에 적용)** | 현재 평면, 또는 2D ROI를 모든 슬라이스에 적용한 스택 전체(Coloc 2에 2D 마스크와 스택을 넣은 것과 같음) |
| | **시점: 모든 시점** | 현재 시점 대신 모든 시점 |
| **Coloc 2 옵션** | Threshold regression | Costes 또는 Bisection |
| | Li Histogram Channel 1/2, Li ICQ, Spearman's Rank Correlation, Manders' Correlation, Kendall's Tau Rank Correlation, 2D Intensity Histogram, Costes' Significance Test | 플러그인의 알고리즘 체크박스(기본 모두 켜짐) |
| | PSF (px), Costes randomisations | Costes 검정에서 섞는 블록 크기와 횟수(기본 3, 10) |
| | Display Images in Result, Display Shuffled Images | 플러그인처럼 결과에 이미지 추가 |

두 채널의 비트 깊이가 다르면 Coloc 2 자체는 실행하지 않습니다. 여기서는 경고와
함께 32-bit float로 계산합니다.

## 실행

- **계산 (현재 이미지)**.
- **모든 이미지**: ROI가 있는 모든 이미지에서, 같은 이름의 채널로 계산합니다.

## 결과

결과 표에는 세포·영역·시점마다 한 행으로 Pearson R, R above thr, tM1, tM2, M1,
M2, ICQ, Spearman, Kendall, Costes P가 나옵니다. 행을 누르면 그 세포가 이미지에서
선택되고, 그래프(회귀선과 threshold가 그려진 2D 히스토그램, Li 그래프, 섞은
이미지)와 모든 값, 플러그인의 경고가 표시됩니다.

## 저장

**파일 › 내보내기 › Coloc 2** 메뉴:

| 메뉴 | 파일 |
|---|---|
| **CSV (현재 이미지)…** | 현재 이미지, ROI마다 한 행, 열 이름은 Coloc 2와 같음 |
| **모든 이미지 CSV (폴더)…** | 이미지마다 `<이름>_coloc2.csv`, 전체 `coloc2.csv` |
| **그래프…** | 선택한 행의 그래프 |
| **PDF 리포트…** | 선택한 ROI의 히스토그램과 모든 값(Coloc 2의 PDF와 같은 내용) |

**모든 분석 결과 통합 저장**(`Ctrl+Shift+E`)에도 Coloc 2 CSV가 들어갑니다.

## Fiji와의 일치

Coloc 2 코드 자체와 비교했습니다(`scripts/imagej_reference`). Costes 무작위화를
뺀 모든 값이 상대 오차 약 10⁻¹⁰ 이내로 같습니다. Costes 검정은 두 프로그램 모두
무작위라서, 섞은 결과의 평균과 SD가 그 변동 범위 안에서 일치합니다.
