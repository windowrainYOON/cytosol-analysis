# mitoROI 탭 (v0.67)

세포질 ROI 탭의 세포마다 미토콘드리아를 나누고 골격(MiNA)과 미토 조각을 측정합니다. 관심 단백질 채널이
있으면 미토 위 / 밖의 신호, 점(puncta), 공존(Pearson, Manders), green+ / green− 세포도 함께 잽니다.
계산은 Mito Analyzer 1.8.0의 코드를 그대로 옮겨, 같은 세포 ROI면 Mito Analyzer와 같은 숫자가 나옵니다.

열기: Tool › **mitoROI** › mitoROI 탭 열기 (또는 View 메뉴). 세포 ROI는 먼저 세포질 ROI 탭에서 찾습니다.

## 실행

- **분석 실행**: 현재 이미지. **모든 이미지에 실행**: 세포 ROI가 있는 모든 이미지. 파일 › 일괄 분석의
  **mitoROI** 단계도 같습니다.

## 1 채널 · 세포

- **미토콘드리아** / **관심 단백질** 채널 (관심 단백질 = 없음이면 미토 형태만).
- **가장자리 세포 포함**: 이미지 가장자리에 닿은 세포도 분석합니다 (기본은 뺌).
- **경계 약한 이웃 제외**: 이웃과의 경계가 주변보다 어둡지 않은 세포(한 세포가 둘로 나뉜 경우)를 뺍니다.
  **경계 대비 기준**으로 정도를 정합니다.
- 상태 줄: 세포 수, 분석한 세포, 가장자리 / 경계 약한 이웃으로 뺀 세포.

## 2 미토 분할

- **조각 분할 (적응 임계값 + 접촉선 분리)** (기본): rolling ball 1.5 µm 배경 빼기 + σ 0.7 px 평활, 세포마다
  국소 평균 AND 0.5 × Otsu 이상, 맞닿은 조각은 h-maxima watershed로 나눔.
- **MiNA 기본 (세포마다 Otsu)**: 세포 안 미토 채널 값의 Otsu 임계값.
- **임계값** [값][자동]: 끄면 전처리한 영상에 하나의 값을 씁니다.
- **최소 조각**: 이보다 작은 조각은 조각 표에 넣지 않습니다 (MiNA 값에는 들어감).

## 3 관심 단백질

- **배경** [값][자동]: 자동 = 세포 사이 어두운 틈의 값.
- **green+ 기준**: 밝은 green이 세포질의 이 비율 이상을 덮으면 green+.
- **점 (puncta) 민감도**, **점 임계값** [값][자동]: top-hat 영상에 이미지마다 하나의 임계값
  (자동 = max(Otsu, 중앙값 + 6 MAD) × 민감도).

## 4 표시

캔버스 레이어 칩: 미토 면적(자홍), 골격(초록), 끝점(노랑), 분기점(파랑), green 점, 세포 번호. 결과 표에서
고른 세포는 노란 테두리.

## 5 결과

- 표: **세포마다 / 미토 조각마다 / 점마다**.
- **상관 히트맵 ›**: 그래프 창에 `mitoROI · 세포` 표의 상관 행렬 (미토 형태 × 관심 단백질, Spearman ρ).
  칸을 누르면 그 두 열의 산점도 + 회귀선.
- **그룹 비교 ›**: 이미지 그룹 사이 상관 비교 (A vs B, Fisher z).
- **Mito Analyzer 결과 불러오기…**: `<이름>_per_cell.csv` (옆의 `_per_mito`, `_green_puncta`도)를 이름이 같은
  이미지(없으면 현재 이미지)에 붙입니다. 파일 › 불러오기 / 끌어다 놓기도 알아서 인식합니다.

## 데이터 · 내보내기

- 그래프 창 데이터 목록: `mitoROI · 세포`, `mitoROI · 미토 조각`, `mitoROI · 점`. 열 이름은 Mito Analyzer와
  같고, 열 묶음 「미토 형태」「관심 단백질」(세포), 「조각 형태」「조각 위 green」(조각)이 상관 행렬의 기본
  X / Y입니다.
- 파일 › 내보내기 › **mitoROI**: Mito Analyzer와 같은 이름 `<이름>_per_cell.csv`, `_per_mito.csv`,
  `_green_puncta.csv`, `_correlations.csv`, `_mito_RoiSet.zip`, 모든 이미지를 합친 `mito_per_cell.csv` ….
- 결과는 프로젝트에 함께 저장됩니다.

## 주요 열

| 열 | 뜻 |
|---|---|
| footprint_fraction | 미토 면적 / 세포 면적 |
| n_networks, n_branches, total_branch_length_um | MiNA 골격: 네트워크 수, 가지 수, 가지 길이 합 |
| branch_length_mean_um, summed_branch_lengths_mean_um, network_branches_mean | 가지 평균 길이, 네트워크 평균 길이, 네트워크당 가지 |
| donuts | 고리 모양 네트워크 수 |
| n_mito_objects, mito_length_mean_um, mito_aspect_ratio_mean, form_factor_mean | 미토 조각 수와 모양 |
| green_mean_on_mito / off_mito, green_enrichment_on_mito | 미토 위 / 밖 관심 단백질 평균과 그 비 |
| pearson_red_green, manders_m_green, manders_m_mito | 공존 (Pearson, Manders) |
| n_green_puncta, fraction_puncta_on_mito | 점 수, 미토 위 점 비율 |
| green_status, green_bright_area_percent | green+ / green−, 밝은 green이 덮은 세포질 % |
