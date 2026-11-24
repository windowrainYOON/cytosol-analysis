"""Built-in pipelines of the 보관함 (design v3.1 ch. 7). Each is a plain
pipeline dict; ``settings.panel = None`` means the tab's current settings, so
a preset follows what the user set in the tabs until they save their own."""

from __future__ import annotations


def S(kind, **settings):
    d = {'kind': kind, 'settings': settings}
    return d


def OP(inp, out, do='keep', conds=None, mode='all', rest='', **action):
    return {'kind': 'op', 'settings': {'input': inp, 'out': out, 'rest': rest,
                                       'where': {'mode': mode, 'conds': conds or []},
                                       'action': {'do': do, **action}}}


def M(*targets, stats=('Area', 'Mean', 'IntDen'), bg='none', name=''):
    return {'kind': 'measure.intensity', 'settings': {
        'targets': [{'object': t, 'channels': []} for t in targets], 'stats': list(stats), 'bg': bg, 'name': name}}


REVIEW = {'kind': 'human.review', 'settings': {'images': ['chips']}}
END = [{'kind': 'end.export', 'settings': {}}]


def P(name, note, stages):
    return {'format': 'cytosol-viewer-pipeline', 'version': 2, 'name': name, 'note': note, 'stages': stages}


PRESETS = [
    P('세포질 + 입자 · 띠', '세포 · 핵 → 입자 → 가장자리 세포 빼기 → 세포질 · 입자 세기 → 등거리 띠', [
        S('start.auto_group'), S('detect.cells'), S('detect.particles'),
        OP('세포', '세포 (안쪽)', conds=[['edge', 'no']]),
        OP('세포질', '세포질 (입자 뺀)', do='subtract', **{'with': '입자', 'pair': 'cell'}),
        M('세포질', '입자', '세포질 (입자 뺀)'),
        S('measure.count', object='입자', parent='세포'),
        S('measure.bands'), REVIEW, *END]),
    P('261118 TCF', 'TCF RI + FL: ParticleTracker 방식 입자 추적, 5 신호 기준, 6 신호 변화 트랙', [
        S('start.auto_group'), S('track.particles'),
        M('입자 트랙', name='입자 추적 · 점'), *END]),
    P('세포질 세기', '세포 · 핵 → 세포질 Mean / IntDen (배경 = 세포 밖 중앙값)', [
        S('detect.cells'), M('세포', '핵', '세포질', bg='outside'), REVIEW, *END]),
    P('ParticleTracker 기본', '입자 추적 탭의 ParticleTracker 방식 그대로', [
        S('track.particles'), *END]),
    P('ParticleTracker 신호 기준', '입자 추적 → 신호 있는 트랙만', [
        S('track.particles'), OP('입자 트랙', '신호 트랙', conds=[['class', '=', 'signal']]),
        M('신호 트랙'), *END]),
    P('FRAP', 'FRAP 측정 탭의 설정으로 회복 곡선', [S('start.auto_group'), S('measure.frap'), *END]),
    P('세포질 강도 추적 + 변화 필터', '세포 추적 → 분열 · 가장자리 제외 → 필터 1 세포', [
        S('start.auto_group'), S('track.cytosol'),
        OP('세포 트랙', '바뀐 세포', conds=[['divided', 'no'], ['edge', 'no']]),
        M('바뀐 세포', name='세포질 강도 추적 · 고른 세포'), *END]),
    P('Mito Analyzer (형태)', '세포 → 미토 ROI → MiNA', [
        S('detect.cells'), S('detect.mito'), S('measure.mina'), REVIEW, *END]),
    P('Mito Analyzer (관심 단백질)', '세포 → 미토 ROI → 미토 조각 × 채널 세기', [
        S('detect.cells'), S('detect.mito'), M('미토 조각', stats=('Area', 'Mean', 'Max', 'IntDen')), *END]),
    P('Coloc 2', '세포마다 Coloc 2', [S('detect.cells'), S('measure.coloc'), REVIEW, *END]),
    P('Analyze Particles', '입자 → 크기 · 모양 · 세기 (ImageJ Analyze Particles 열)', [
        S('detect.particles'),
        M('입자', stats=('Area', 'Perimeter', 'Circularity', 'Mean', 'Min', 'Max', 'IntDen', 'RawIntDen')),
        *END]),
]
