"""열 설명 (owner request 2026-11-14, data-display proposal 6.2): what a
result column means, its unit and where it comes from (ImageJ / Fiji),
for the graph window's data table and the 측정 항목 card's 항목 설명."""

from __future__ import annotations

import re

# exact names
EXACT = {
    'group': ('', '이미지 목록의 그룹', ''),
    'image': ('', '이미지 이름', ''),
    'image_id': ('', '파일 메타데이터로 만든 이미지 ID', ''),
    'timepoint': ('', '시점 (1부터)', ''),
    'plane': ('', '측정한 Z 면 (z n, MIP, mid)', ''),
    'roi': ('', 'ROI 이름 (cellN …)', 'ImageJ ROI 이름'),
    'region': ('', '측정한 영역 (cell, nucleus, cyto, 식)', ''),
    'cell': ('', '세포 번호', ''),
    'band': ('', '등거리 띠 번호 (핵 쪽부터)', ''),
    'distance_rel': ('0–1', '띠 가운데의 상대 거리 (0 = 핵 경계, 1 = 세포 경계)', ''),
    'Area': ('µm²', '면적', 'ImageJ Measure › Area'),
    'area_um2': ('µm²', '면적', 'ImageJ Measure › Area'),
    'n_particles': ('개', '입자 수', 'Analyze Particles › Count'),
    'Circ.': ('0–1', '원형도 4π·면적 / 둘레²', 'Analyze Particles › Circ.'),
    'circularity': ('0–1', '원형도 4π·면적 / 둘레²', 'Analyze Particles › Circ.'),
    'Solidity': ('0–1', '면적 / 볼록 껍질 면적', 'Analyze Particles › Solidity'),
    'solidity': ('0–1', '면적 / 볼록 껍질 면적', 'Analyze Particles › Solidity'),
    'AR': ('', '장축 / 단축 (맞춘 타원)', 'Analyze Particles › AR'),
    'Feret': ('µm', '가장 긴 지름', 'Analyze Particles › Feret'),
    'Perim.': ('µm', '둘레', 'Analyze Particles › Perim.'),
    'nnd_um': ('µm', '가장 가까운 입자까지의 거리', ''),
    'partition_coefficient': ('', '입자 안 평균 / 입자 밖 세포질 평균', ''),
    'mobile_fraction': ('0–1', '이동 분율 (회복 곡선 피팅)', 'ImageJ Exponential recovery'),
    't_half': ('s', '반 회복 시간 t½', 'ImageJ Exponential recovery'),
    'pearson_r': ('−1–1', 'Pearson 상관 계수', 'Fiji Coloc 2'),
    'manders_m1': ('0–1', 'Manders M1', 'Fiji Coloc 2'),
    'manders_m2': ('0–1', 'Manders M2', 'Fiji Coloc 2'),
}
# channel-suffixed measurement names (<channel>_<stat>)
STATS = {
    'Mean': ('세기', '평균 세기', 'ImageJ Measure › Mean'),
    'StdDev': ('세기', '세기의 표준편차', 'ImageJ Measure › StdDev'),
    'Min': ('세기', '최솟값', 'ImageJ Measure › Min'),
    'Max': ('세기', '최댓값', 'ImageJ Measure › Max'),
    'IntDen': ('세기 × µm²', '면적 × 평균', 'ImageJ Measure › IntDen'),
    'RawIntDen': ('세기', '픽셀 값의 합', 'ImageJ Measure › RawIntDen'),
}


def describe(col: str, label: str = '') -> tuple[str, str, str]:
    """(unit, meaning, ImageJ / source) of a column ('' when unknown)."""
    if col in EXACT:
        return EXACT[col]
    m = re.match(r'(.+?)_(particle_)?(Mean|StdDev|Min|Max|IntDen|RawIntDen)$', col)
    if m:
        unit, what, src = STATS[m.group(3)]
        where = ' (입자 픽셀)' if m.group(2) else ''
        return unit, f'{m.group(1)} 채널의 {what}{where}', src
    m = re.search(r'\((.+)\)$', label or col)
    return (m.group(1) if m else ''), (label if label and label != col else ''), ''


def table(t) -> 'object':
    """The 열 설명 table of a graph Table: column, shown name, unit, meaning, source."""
    from . import graph as G

    rows = []
    for c in t.columns:
        unit, what, src = describe(c, t.label(c))
        kind = '숫자' if t.is_numeric(c) else '글자'
        rows.append([c, t.label(c) if t.label(c) != c else '', kind, unit, what, src])
    return G.Table('열 설명', ['열', '표시 이름', '종류', '단위', '뜻', 'ImageJ / 출처'], rows)
