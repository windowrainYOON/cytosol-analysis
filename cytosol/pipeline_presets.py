"""Built-in pipelines of the 보관함, in the named-ROI format (design v4,
owner approval 2026-11-25; rebuilt from the v2 presets, same analyses).
Each is a plain pipeline dict; ``settings.panel = None`` means the tab's
current settings, so a preset follows what the user set in the tabs until
they save their own. Names are the features used (owner 2026-11-25)."""

from __future__ import annotations


def S(kind, **settings):
    return {'kind': kind, 'settings': settings}


def DETECT(method, names=None, **settings):
    from .pipeline_roi import METHODS
    nm = {r: n for r, n, _k, _t in METHODS[method][1]}
    nm.update(names or {})
    return S('detect.roi', method=method, names=nm, panel=None, redo=True, channels={}, **settings)


def TRACK(algorithm, out, **settings):
    return S('roi.track', algorithm=algorithm, input='', out=out, panel=settings.pop('panel', None),
             cell_track=settings.pop('cell_track', None), redo=True, **settings)


def FILTER(inp, out, conds, by='relation', mode='all', rest=''):
    return S('roi.filter', input=inp, by=by, mode=mode, conds=conds, out=out, rest=rest)


def OP(a, do, b, out, **settings):
    return S('roi.op', a=a, do=do, b=b, out=out, pair=settings.pop('pair', 'cell'), **settings)


def MEASURE(kind, a, params, b='', channels=(), name='', **settings):
    return S('measure.roi', type=kind, a=a, b=b, channels=list(channels), params=list(params), name=name,
             bg=settings.pop('bg', 'none'), **settings)


SIGNAL = ('Area', 'Mean', 'IntDen')
ON = {'checked': True}
REVIEW = {'kind': 'human.review', 'settings': {'images': ['chips']}}
END = [{'kind': 'end.export', 'settings': {}}]


OLD_NAMES: dict = {}   # earlier names (before v0.75.3, and the v0.75.3 feature names) -> name


def P(old, note, stages):
    """A preset named by the features it uses (owner 2026-11-25), e.g. '입자 추적 · 신호 강도'."""
    from .pipeline import feature_name
    name = feature_name(stages)
    for o in old:
        OLD_NAMES[o] = name
    return {'format': 'cytosol-viewer-pipeline', 'version': 3, 'name': name, 'note': note, 'stages': stages}


PRESETS = [
    P(('세포질 + 입자 · 띠', '세포질 ROI · 입자 ROI · 연산 · 세기 · 개수 · 등거리 띠'),
      'Cell · Nuc · Cyto → Spot → 가장자리 세포 빼기 → Cyto − Spot → 신호 강도 · 개수 · 등거리 띠', [
          S('start.auto_group'), DETECT('cells'), DETECT('particles'),
          FILTER('Cell', 'Cell_inner', [['edge', 'no']], by='value'),
          OP('Cyto', 'subtract', 'Spot', 'Cyto_noSpot'),
          MEASURE('signal', 'Cyto', SIGNAL, name='신호 · Cyto'),
          MEASURE('signal', 'Spot', SIGNAL, name='신호 · Spot'),
          MEASURE('signal', 'Cyto_noSpot', SIGNAL, name='신호 · Cyto_noSpot'),
          MEASURE('relation', 'Cell', ('Count', 'Density'), b='Spot', name='개수 · Spot'),
          MEASURE('relation', 'Cell', ('Bands',), b='Nuc', name='등거리 띠'), REVIEW, *END]),
    P(('261118 TCF', '입자 추적 · 세기'),
      'TCF RI + FL: ParticleTracker 방식 입자 추적, 5 신호 기준 (green ≥ 5, 3 프레임), 6 신호 변화 트랙', [
          S('start.auto_group'),
          TRACK('particle', 'Spot_track', panel={'sig_on': ON, 'chg_on': ON}, signal_thr=5),
          MEASURE('signal', 'Spot_track', ('PerFrame',), name='입자 추적 · 점'), *END]),
    P(('세포질 세기', '세포질 ROI · 세기'), 'Cell · Nuc · Cyto → 신호 강도 (배경 = 세포 밖 중앙값)', [
        DETECT('cells'),
        MEASURE('signal', 'Cell', SIGNAL, name='신호 · Cell', bg='outside'),
        MEASURE('signal', 'Nuc', SIGNAL, name='신호 · Nuc', bg='outside'),
        MEASURE('signal', 'Cyto', SIGNAL, name='신호 · Cyto', bg='outside'), REVIEW, *END]),
    P(('ParticleTracker 기본', '입자 추적'), '입자 추적 탭의 ParticleTracker 방식 그대로', [
        TRACK('particle', 'Spot_track'), *END]),
    P(('ParticleTracker 신호 기준', '입자 추적 · 연산 · 세기'), '입자 추적 → 신호 있는 트랙만 (Spot_signal)', [
        TRACK('particle', 'Spot_track'),
        FILTER('Spot_track', 'Spot_signal', [['class', '=', 'signal']], by='value'),
        MEASURE('signal', 'Spot_signal', ('PerFrame',), name='신호 · Spot_signal'), *END]),
    P(('FRAP',), 'FRAP 측정 탭의 설정으로 회복 곡선', [S('start.auto_group'), S('measure.frap'), *END]),
    P(('세포질 강도 추적 + 변화 필터', '입자 추적 · 세포질 강도 추적 · 연산 · 세기'),
      '입자 추적 (ParticleTracker 세포) → 세포질 추적 (같은 세포 · 형광 격자) → 분열 · 가장자리 제외 → Cell_kept', [
          S('start.auto_group'), TRACK('particle', 'Spot_track'),
          TRACK('cytosol', 'Cell_track', cell_track={'algorithm': 'particle'}),
          FILTER('Cell_track', 'Cell_kept', [['divided', 'no'], ['edge', 'no']], by='value'),
          MEASURE('signal', 'Cell_kept', ('PerFrame',), name='세포질 강도 추적 · 고른 세포'), *END]),
    P(('Mito Analyzer (형태)', '세포질 ROI · mitoROI · 미토 형태 (MiNA)'), 'Cell → Mito → MiNA 골격', [
        DETECT('cells'), DETECT('mito', cells='Cell'),
        MEASURE('shape', 'Mito', ('Skeleton',), name='미토 형태 (MiNA)'), REVIEW, *END]),
    P(('Mito Analyzer (관심 단백질)', '세포질 ROI · mitoROI · 세기'), 'Cell → Mito → Mito × 채널 신호 강도', [
        DETECT('cells'), DETECT('mito', cells='Cell'),
        MEASURE('signal', 'Mito', ('Area', 'Mean', 'Max', 'IntDen'), name='신호 · Mito'), *END]),
    P(('Coloc 2', '세포질 ROI · Coloc 2'), 'Cell마다 Coloc 2 (Coloc 2 탭의 두 채널)', [
        DETECT('cells'), MEASURE('relation', 'Cell', ('Coloc',), name='Coloc 2'), REVIEW, *END]),
    P(('Analyze Particles', '입자 ROI · 세기'), 'Spot → 크기 · 모양 · 신호 강도 (ImageJ Analyze Particles 열)', [
        DETECT('particles'),
        MEASURE('shape', 'Spot', ('Area', 'Perimeter', 'Circularity'), name='형태 · Spot'),
        MEASURE('signal', 'Spot', ('Mean', 'Min', 'Max', 'IntDen', 'RawIntDen'), name='신호 · Spot'), *END]),
]
