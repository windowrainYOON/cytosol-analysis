"""The graph kinds offered by the kind picker (names and one-line notes)."""
from __future__ import annotations




KINDS = [('xy', '선 · 점 (XY)', '시간 · 거리 같은 숫자 x'),
         ('bar', '막대', '그룹 평균 ± 에러바'),
         ('strip', '점 그림', '개별 값 + 평균'),
         ('box', '상자 그림', '중앙값과 사분위'),
         ('violin', '바이올린', '값의 분포 모양'),
         ('hist', '히스토그램', '한 값의 분포'),
         ('heatmap', '히트맵', 'x · y 위의 값'),
         ('corr', '상관 행렬', '여러 열 사이의 상관'),
         ('corrcmp', '상관 비교', '그룹마다 상관이 다른지')]


_THUMBS = {}
