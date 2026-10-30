# FRAP 측정 탭 (bleach 후 회복 곡선)

[← 설명서 목차](README.md) · [English](../en/14-frap.md)

메뉴 막대의 **Tool › FRAP 측정 › FRAP 측정 탭 열기**로 오른쪽에 이 탭을 열고 닫습니다. 이 탭의
저장과 불러오기도 같은 **FRAP 측정** 메뉴에 있습니다.

시간축(T)이 있는 bleach 실험에서, bleach한 곳의 강도가 시간에 따라 얼마나 회복되는지
측정해 그래프로 그리고, mobile fraction, t½ 같은 FRAP 수치를 계산합니다. 탭을 열면
현재 이미지가 바로 측정됩니다.

## 측정값

프레임마다

> 값 = (Bleach − Background) / (Control − Background)

이고, 세 값은 각 ROI 안의 평균 강도(ImageJ Measure의 Mean과 같음)입니다.

| ROI | 색 | 자동 위치 |
|---|---|---|
| **Bleach** (B) | 빨강 | 파일에 기록된 bleach 영역 (Zeiss CZI의 bleach 영역, Olympus/Evident OIR의 stimulation 영역). 기록이 없으면 앞 프레임들보다 계속 어두워진 곳 중 가장 크게 어두워진 곳 (이미지 가장자리 4 %는 제외) |
| **Control** (C) | 초록 | Control 아래 **위치**에서 고름 (모든 이미지): **주변의 다른 응집체 (강도가 가장 안정된 곳)** (기본): bleach한 응집체에서 가까운 응집체 12개 중 시간에 따라 평균 강도가 가장 적게 변하는 곳 (변동계수가 가장 작은 곳, 드리프트 보정이 켜져 있으면 프레임마다 움직인 자리에서 측정). **같은 응집체 안 (bleach 영역 밖)**: bleach한 응집체에서 bleach 영역 밖의 가장 안쪽, 응집체가 통째로 bleach됐으면 주변에서 가장 안정된 응집체. 크기는 Bleach와 달라도 됨 |
| **Background** (BG) | 파랑 | Bleach ROI와 같은 모양·크기로, 응집체 신호가 없는 가장 가까운 곳 |

Control은 bleach 프레임에서 신호가 30 % 넘게 떨어지는 곳(같이 bleach된 곳)을 건너뜁니다.
손으로 옮긴 Control은 그 자리에 그대로 있습니다.
자동 위치가 알맞지 않을 때 쓰는 안내는 ROI 칸 아래 주황색 글로 나옵니다.

## ROI 옮기기

ROI는 이미지 위에 B / C / BG 글자와 함께 표시됩니다(**ROI 표시**로 끄고 켬). 이미지
위에서 ROI를 끌면 끄는 동안에도 값과 그래프가 바로 바뀌고, 놓으면 그 자리에 고정되며
그 ROI의 **자동**이 꺼집니다. **자동**을 다시 켜면 자동 위치로 돌아갑니다.
**모두 자동 배치**는 이 이미지의 ROI, 프레임, threshold를 모두 자동으로 되돌립니다.
ROI 위치와 설정은 이미지마다 따로 저장됩니다.

## 드리프트 보정

촬영하는 동안 응집체나 시야 전체가 움직이면(스테이지·시료가 천천히 밀림, 응집체가 떠다님)
**드리프트 보정 (ROI가 움직임을 따라감)** (기본 켬)이 세 ROI를 프레임마다 그 움직임만큼
옮겨 측정합니다. 이미지 자체는 바꾸지 않습니다. 프레임마다의 움직임은 기준 프레임(첫
프레임, 이후 프레임이 기준과 맞지 않게 되면 바로 앞 프레임이 새 기준)과의 서브픽셀
교차상관으로 찾고, ROI는 그 값을 정수 픽셀로 반올림해 옮깁니다(ImageJ에서 손으로 옮긴
것과 같음).

| 항목 | 의미 |
|---|---|
| **ROI 주변 추적** | Bleach ROI 둘레 정사각형의 움직임 (Background도 따라감). Control이 다른 응집체에 있으면 그 응집체는 따로 추적 |
| **전체 이미지** | 시야(가운데 512 px)의 움직임: 스테이지·시료 드리프트 |
| **추적 창** + **자동** | 추적하는 정사각형의 한 변. 자동: Bleach ROI의 8배, 최소 128 px |

아래 줄에 ROI가 움직인 최대 거리(px, µm)와 마지막 프레임의 이동량이 나옵니다. 이미지
위의 ROI는 보고 있는 프레임에서 측정하는 자리에 그려지므로 T 슬라이더를 옮기면 따라
움직입니다. 어느 프레임에서 ROI를 끌어 옮겨도 그 차이가 모든 프레임에 적용됩니다. 이미지별
CSV에는 프레임마다 이동량(`bleach_dx_px`, `bleach_dy_px`, Control을 따로 추적하면
`control_…`도), `frap_summary.csv`에는 최대 이동량(`max_drift_px`)이 들어갑니다.

이미지 평면 안의 움직임만 따라갈 수 있습니다. 한 평면만 찍은 시계열에서 초점이 밀리면 모든
곳의 신호가 줄어드는데, 고르게 줄어드는 부분은 Control로 나누는 정규화가 보정합니다.
Z-stack이면 MIP(Z 슬라이더)에서 측정하면 초점의 영향을 받지 않습니다.

## 설정

| 항목 | 의미 |
|---|---|
| **채널** | 측정할 채널 (모든 이미지에 같은 이름의 채널) |
| **bleach 전 강도로 정규화** (기본 켬) | **bleach 전 = 1, 직후 = 0** (기본): (값 − bleach 후 첫 프레임 값) / (bleach 전 프레임 평균 − 그 값), Recovery (%)로 표시 (full-scale 정규화). **첫 프레임 = 1** / **bleach 전 프레임 평균 = 1**: 그 값으로 나눔. 모두 Phair 등(2004)의 double normalization 위에서 계산합니다 |
| **bleach 후 첫 프레임** + **자동** | bleach 바로 다음 프레임 (1부터). 자동: 파일의 bleach 기록(CZI bleach 이벤트, OIR pre-bleach 프레임 수), 없으면 Bleach ROI 강도가 가장 크게 떨어진 프레임 |
| Bleach **지름** + **자동** | 파일 기록이 없을 때 찾은 원의 지름 (자동: 어두워진 영역의 넓이와 같은 원). 파일의 bleach 영역은 그 모양 그대로 |
| Control **지름** + **자동** | Control 원의 지름 (자동: Bleach ROI 크기까지, 응집체 안에 들어가는 가장 큰 원) |
| **응집체 threshold** + **자동** (슬라이더) | bleach 전 이미지(σ 1 px 가우시안)에서 이 값 이상이 응집체 신호. Control과 Background 자동 위치에 씀. 자동: Bleach ROI 둘레 창 안의 Otsu |

## 그래프

**그래프** 목록에서 고릅니다.

- **회복 곡선 (현재 이미지)**: 값을 bleach 뒤 시간(s, 0 = bleach 후 첫 프레임)에 대해.
  **지수 회복 피팅**을 켜면 피팅 곡선도.
- **ROI 평균 강도 (현재 이미지)**: Bleach, Control, Background의 원래 평균 강도.
- **그룹 평균 ± 에러바**: 이미지 그룹([그룹](01-getting-started.md))마다 평균 곡선과
  **SEM** 또는 **SD** 에러바. 프레임은 bleach 프레임에 맞춰 정렬합니다. 그룹에 넣지 않은
  이미지는 `No group` 한 묶음입니다. **개별 곡선도 표시**로 이미지마다 곡선도 흐리게.
  에러바에는 그룹마다 3개 이상의 이미지를 권장합니다(3개 미만이면 표시).
  - 그래프 위에 그룹마다 체크박스가 나오고, 체크한 그룹만 그립니다(`frap_groups.png` /
    `.pdf`도 같음, CSV에는 모든 그룹). 고른 것은 프로젝트에 저장됩니다.
  - **그룹별로 정규화 (bleach 전 = 1, 직후 = 0)** (기본 켬): 그룹마다 따로, 이미지마다
    bleach 전 값으로 나눈 곡선(R / R_pre)을 평균한 뒤 그 평균 곡선을 bleach 전 프레임 평균
    = 1, bleach 후 첫 프레임 = 0이 되게 맞춥니다(SD·SEM도 같은 비율로). bleach 깊이가 달라도
    모든 그룹이 같은 0–100 % 축에 놓입니다. 그래프 아래에 그룹 평균 곡선의 피팅값도
    나옵니다. 끄면 이미지마다 정규화한 곡선의 평균입니다.

그래프는 논문의 FRAP 그림처럼 그립니다: 세로축 Recovery (%) (0부터), 가로축 bleach 후
Time (s), 그룹마다 검은 마커(빈 네모, 찬 네모, 빈 동그라미, …)와 에러바, 피팅 곡선은 검은
선, 범례는 그래프 위, 격자와 위·오른쪽 축은 없음. (다른 정규화에서는 bleach 전 프레임도
보이고 bleach 시점에 점선을 긋습니다.)

그래프 아래에 FRAP 수치가 나옵니다.

## FRAP 수치

bleach 후 프레임을 ImageJ Curve Fitter의 **Exponential recovery**
`y = a·(1 − e^(−k·t)) + c`로 피팅합니다(t: bleach 후 첫 프레임부터의 s).
pre는 bleach 전 값(정규화하면 1)입니다.

| 열 | 의미 |
|---|---|
| `pre_bleach` | bleach 전 값 (정규화하면 1) |
| `post_bleach` | bleach 직후 값 (bleach 후 첫 프레임, "bleach 전 = 1, 직후 = 0"이면 0) |
| `bleach_depth` | 정규화 전 비율 R의 1 − 직후 / 전 |
| `final`, `final_recovery` | 마지막 프레임 값, (마지막 − 직후) / (전 − 직후). 피팅 없이 구한 회복률 |
| `plateau` | 피팅이 수렴하는 값 a + c |
| `mobile_fraction` | a / (전 − c): 회복할 수 있는 비율 |
| `immobile_fraction` | 1 − mobile fraction |
| `k_per_s`, `tau_s`, `half_time_s` | 회복 속도 상수 k, τ = 1/k, 반감기 t½ = ln 2 / k |
| `initial_rate_per_s` | 처음 회복 속도 a·k |
| `fit_r2` | 피팅 R² |
| `fit_ok` | 1 = 피팅 사용 가능. 0 = 회복이 없거나(a ≤ 0) t½가 관찰 시간보다 길어 피팅값을 비움 (그때는 `final_recovery`를 보세요) |
| `D_um2_per_s` | 원형 bleach일 때 확산계수 참고값 D ≈ 0.224 · r² / t½ (Soumpasis 1983). 실제 회복이 확산만으로 정해질 때만 의미가 있습니다 |

## 저장

메뉴 막대의 **Tool › FRAP 측정** 메뉴에서:

- **요약 저장: 모든 이미지·그룹 CSV + 그래프 (폴더)…**: 시간축이 있는 모든 이미지를
  측정해 한 번에 저장합니다.
  - `frap_summary.csv`: 이미지마다 한 행(위 FRAP 수치), 그룹마다 mean / sd / sem 행
    (n은 값이 있는 이미지 수)과 그룹 평균 곡선을 피팅한 행, 끝에 열 설명.
  - `frap_group_curves.csv`: 그룹 평균 곡선 (bleach 기준 프레임, 시간, mean, SD, SEM, n, 피팅값).
  - `frap_groups.png` / `.pdf`: 그룹 평균 ± 에러바 그래프.
  - `frap_summary.png`: 그룹별 mobile fraction, t½, 최종 회복률 막대(평균 ± 에러바)와 이미지마다 점.
  - `frap_formulas.txt`: 모든 값의 계산 공식(ROI 평균, 비율, 정규화, 피팅, mobile fraction,
    t½ …)과 쓴 설정. 같은 내용이 모든 FRAP CSV 맨 위에 `#` 줄로도 들어갑니다.
  - 이미지마다 `<이름>_frap.csv`(프레임별 시간, 세 ROI 평균, 비율, 값, 피팅),
    `<이름>_frap.png`, `<이름>_frap_rois.zip`. **파일 › 이미지별 폴더에 나눠 저장**이 켜져
    있으면 이미지별 폴더에.
- **CSV 저장 (현재 이미지)…**: `<이름>_frap.csv` (ROI 함께 저장 옵션이 켜져 있으면 `_rois.zip`도).
- **그래프 저장 (PNG / PDF / SVG / TIFF)…**: 탭에 보이는 그래프.
- **FRAP ROI 저장 (현재 이미지)…** / **FRAP ROI 불러오기…**: ImageJ ROI
  (`frap_bleach`, `frap_control`, `frap_background`). 불러온 ROI는 그 자리에 고정됩니다.

**파일 › 모든 분석 결과 통합 저장**은 FRAP 탭에서 측정한 이미지마다 `<이름>_frap.csv`와
`_frap_rois.zip`을, 전체 폴더에 `frap_summary.csv`, `frap_group_curves.csv`,
`frap_groups.png`, `frap_summary.png`를 씁니다. FRAP ROI와 설정은 프로젝트 파일에도
저장됩니다.

## ImageJ와의 일치

ROI 평균은 ImageJ(1.54f)와 같습니다: 원/타원 ROI는 `OvalRoi` 마스크, 사각형은 모든 픽셀,
다각형은 `PolygonFiller`(서브픽셀 좌표 포함)와 같은 규칙. 지수 회복 피팅은 ImageJ
`CurveFitter`의 Exponential recovery와 계수가 상대 10⁻⁵ 이내로 같습니다
(`scripts/imagej_reference/compare_frap.py`).
