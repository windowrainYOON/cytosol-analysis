# 저장되는 파일

[← 설명서 목차](README.md) · [English](../en/12-output-files.md)

`<이름>`은 확장자를 뺀 이미지 파일 이름입니다. **이미지별 폴더에 나눠 저장**
(기본 켜짐)을 켜면 이미지마다 `<이름>_<이미지 ID>/` 폴더에 저장되고, 모든 이미지를
합친 표는 고른 폴더에 남습니다. 모든 TIFF, ROI, CSV에 이미지 ID가 들어갑니다
([이미지 ID](01-getting-started.md#이미지-id) 참고).

## 이미지

| 파일 | 만드는 곳 | 내용 |
|---|---|---|
| `<이름>_full_composite.tif` | LUT · 내보내기 저장 | LUT와 마커가 들어간 합성 RGB. Crop은 `<이름>_crop1_composite.tif`, … |
| `<이름>_full_C<i>_<채널>.tif` | 저장, **채널별 RGB** | 채널마다 RGB |
| `<이름>_full_raw.tif` | 저장, **원본값 스택** | 원본값 ImageJ hyperstack(타임시리즈는 TZCYX) |
| `….mp4` | MP4를 고른 저장 / 스택 탭 | 시점(또는 각도)마다 한 프레임인 동영상 |
| 투영 `.tif` / `.mp4` | 스택 탭 | RGB 투영 + float32 ImageJ 스택, 또는 회전 시리즈 |
| `<이름>_image.png` | 측정·라인 프로파일 저장 | 현재 LUT 이미지 위에 ROI 경계나 선 |
| Figure `.png` / `.tif` / `.pdf` / `.svg` | Figure 창 | figure 표 |

## ROI (ImageJ 형식, ROI Manager › Open으로 열기)

| 파일 | 만드는 곳 | ROI 이름 |
|---|---|---|
| `<이름>_RoiSet.zip` | 세포질 ROI 탭, 측정 저장, 모든 데이터 일괄 저장 | `cellNNN`, `nucNNN`, `cytoNNN` |
| `<이름>_particles.zip` | 입자 ROI 탭 | `partCCC-NN`(픽셀 경계 윤곽, 설정은 속성에) |
| `<이름>_particles_contour.zip` | 입자 ROI 탭 | `partCCC-NN` 서브픽셀 등강도선 |
| `<이름>_regions.zip` | 강도 측정 탭 | `rgnCCC-R`, 식은 `region` 속성 |
| `<이름>_bleach_rois.zip` | 모든 저장(bleach 영역이 있는 CZI) | 타원 또는 다각형 |
| `<이름>_line.roi` | 라인 프로파일 탭 | 두께가 들어간 직선 |
| inset `.roi` / `.zip` | Figure 창 | 원본 이미지 좌표의 사각형 |

## 표 (CSV)

| 이미지마다 | 전체 | 내용 |
|---|---|---|
| `<이름>_cell_rois.csv` | `cell_rois.csv` | 세포·핵·세포질 면적(세포질 ROI 탭, 모든 데이터 일괄 저장) |
| `<이름>_cell_intensity.csv` | `cell_intensity.csv` | 세포질 ROI 탭 측정 |
| `<이름>_particle_intensity.csv` | `particle_intensity.csv` | 입자 ROI 탭, 세포별 |
| `<이름>_particle_shape.csv` | `particle_shape.csv` | 입자 ROI 탭, 입자마다 |
| `<이름>_<suffix>_summary.csv` | `<suffix>_summary_image.csv`, `<suffix>_summary_group.csv` | 입자 ROI 탭 요약 |
| `<이름>_intensity.csv` | `intensity.csv` | 강도 측정 탭 |
| `<이름>_coloc2.csv` | `coloc2.csv` | Coloc 2 탭 |
| `<이름>_info.csv` | — | 이미지 정보 탭(모든 데이터 일괄 저장) |
| — | `image_groups.csv` | 이미지, 이미지 ID, 그룹 |
| 라인 프로파일 `.csv` | — | 거리 + 채널마다 한 열 |

## 결과 다시 불러오기

**폴더 불러오기…**(`Ctrl+Shift+O`)는 폴더와 하위 폴더를 뒤져:

- 내보낸 TIFF를 이미지 ID로 원본과 짝짓습니다. 원본이 없으면 가장 알맞은
  내보낸 파일(raw 스택 우선)을 대신 열고 원본의 ID를 유지합니다.
- `<이름>_RoiSet.zip`을 해당 이미지에 불러옵니다(ID로, ID가 생기기 전에 저장한
  ROI는 파일 이름으로).
- `<이름>_particles.zip`은 입자로 불러오고, `<이름>_particles_contour.zip`,
  `<이름>_regions.zip`, `<이름>_bleach_rois.zip`은 세포로 읽지 않고 연결만 합니다.
- `image_groups.csv`로 그룹을 복원합니다.
