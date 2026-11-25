"""파이프라인 v4: 이름 붙인 ROI (owner request 2026-11-25, approved 15:06;
design /mnt/project-files/pipeline/파이프라인_v4_ROI이름.md).

Every stage reads ROI sets by **name** and writes new names:

검출 (``detect.roi``)     image → named ROI sets (Cell / Nuc / Cyto, Spot, Mito)
ROI 연산 (``roi.op``)      A (· B) → new name (빼기 · 겹친 부분 · 합치기 · 넓히기 …)
ROI 필터 (``roi.filter``)  ROI → the ROIs that pass (+ the rest), by relation or measured value
ROI 추적 (``roi.track``)   ROI → track set (입자 추적 / 세포질 추적 algorithm)
측정 (``measure.roi``)     형태 / 신호 강도 / 관계 × ROI name(s) × channels → parameters
측정값 연산 (``calc.values``) parameters → new parameters (계산 · 정규화)

Detection and tracking still run the tabs' own code (`batch.run`), so results
equal the v3 stages; a detected name is an alias of the tab result
(`it.pipe_alias`, resolved on every access so 검토 edits are seen), other names
are `PipeObject`s in `it.pipe_objects`. v2 pipelines (``.cypipe`` VERSION 2,
presets, projects) are converted by `convert_stages` when they are opened.
"""

from __future__ import annotations

import copy
import math

import numpy as np
from scipy import ndimage as ndi

# ---------------------------------------------------------------------------
# detection methods: what they make, their default names, their input channels
# ---------------------------------------------------------------------------

# method -> (title, [(role, default name, ROI kind, Korean label)], panel, batch step, [(channel label, panel combo)])
METHODS = {
    'cells': ('세포질 ROI', [('cell', 'Cell', 'region', '세포'), ('nuc', 'Nuc', 'region', '핵'),
                            ('cyto', 'Cyto', 'region', '세포질 (세포 − 핵)')], 'roi', 'cells',
              [('핵 채널', 'nuc_combo'), ('배경 신호 채널', 'bg_combo')]),
    'particles': ('입자 ROI', [('spot', 'Spot', 'spot', '입자')], 'particle', 'particles',
                  [('입자 채널', 'part_channel')]),
    'mito': ('mitoROI', [('mito', 'Mito', 'region', '미토 조각')], 'mito', 'mito',
             [('미토 채널', 'mito_ch'), ('관심 단백질 채널', 'poi_ch')]),
}
# role -> the tab-result object of `pipeline.base_objects`
ROLE_BASE = {'cell': '세포', 'nuc': '핵', 'cyto': '세포질', 'spot': '입자', 'mito': '미토 조각',
             'particle_track': '입자 트랙', 'cell_track': '세포 트랙'}
KIND_TEXT = {'region': '영역 · 시점마다', 'spot': '점 영역 · 시점마다', 'track': '트랙'}

# tracking algorithms
TRACKERS = {'particle': ('입자 추적', 'particle_track', 'Spot_track', 'track', 'track'),
            'cytosol': ('세포질 추적', 'cell_track', 'Cell_track', 'cyto_track', 'cyto_track')}

ROI_OPS = (('subtract', '빼기 (A − B)'), ('intersect', '겹친 부분 (A ∩ B)'), ('add', '합치기 (A ∪ B)'),
           ('dilate', '넓히기 (µm)'), ('erode', '줄이기 (µm)'), ('ring', '고리 (안 – 밖 µm)'),
           ('bands', '등거리 띠 (n개)'), ('merge', '부모마다 하나로 합치기'))
NEEDS_B = ('subtract', 'intersect', 'add')
PAIRS = (('cell', '같은 부모 (세포 번호)끼리'), ('overlap', '겹치는 것끼리'), ('image', '이미지 전체'))

# ROI 필터 relations: (key, text, field template, op)
RELATIONS = (('overlaps', '겹친다', 'overlap:{}', '>'), ('not_overlaps', '겹치지 않는다', 'overlap:{}', '<='),
             ('inside', '안에 있다', 'inside:{}', 'yes'), ('contains', '포함한다', 'contains:{}', 'yes'),
             ('not_contains', '포함하지 않는다', 'contains:{}', 'no'), ('near', '거리 ≤ (µm)', 'dist:{}', '<='),
             ('same_parent', '같은 부모', 'parent_in:{}', 'yes'))
CMP = (('>=', '≥'), ('<=', '≤'), ('>', '>'), ('<', '<'), ('=', '='), ('between', '사이'), ('yes', '예'),
       ('no', '아니오'))

# ---------------------------------------------------------------------------
# measurement parameters (design §6.1)
# ---------------------------------------------------------------------------

MEASURE_TYPES = (('shape', '형태'), ('signal', '신호 강도'), ('relation', '관계'))
# type -> [(group, [(param, text)], applies to: 'region' / 'track' / 'mito' / 'any', channels needed)]
PARAMS = {
    'shape': [
        ('크기', [('Area', 'Area'), ('Perimeter', 'Perimeter'), ('Feret', 'Feret'), ('MinFeret', 'MinFeret'),
                ('Major', '장축'), ('Minor', '단축'), ('EqDiam', '등가 지름')], 'region', 0),
        ('모양', [('Circularity', 'Circularity'), ('AR', 'AR'), ('Round', 'Roundness'), ('Solidity', 'Solidity'),
                ('Eccentricity', 'Eccentricity')], 'region', 0),
        ('위치', [('X', '중심 X'), ('Y', '중심 Y'), ('DistParent', '부모 중심까지 거리'),
                ('DistParentEdge', '부모 경계까지 거리')], 'region', 0),
        ('골격 (MiNA)', [('Skeleton', '골격 길이 · 가지 · 분기점')], 'mito', 0),
        ('트랙만', [('Frames', '길이 (프레임)'), ('PathLength', '총 이동 거리'), ('Displacement', '순 변위'),
                  ('Speed', '평균 속도'), ('Straightness', '직진도')], 'track', 0),
    ],
    'signal': [
        ('기본 (ImageJ Measure)', [('Area', 'Area'), ('Mean', 'Mean'), ('Median', 'Median'), ('Min', 'Min'),
                                  ('Max', 'Max'), ('StdDev', 'StdDev'), ('IntDen', 'IntDen'),
                                  ('RawIntDen', 'RawIntDen')], 'region', 1),
        ('분포', [('TopMean', '상위 n % 평균'), ('CV', 'CV'), ('PosFrac', '양성 픽셀 비율')], 'region', 1),
        ('시간 (트랙)', [('PerFrame', '시점별 값'), ('First', '처음'), ('Last', '끝'), ('TMax', '최대'),
                      ('TMin', '최소'), ('MaxOverStart', '최대 ÷ 시작'), ('OnFrames', '켜진 프레임 수'),
                      ('Change', '변화 종류'), ('FirstOn', '처음 켜진 시점')], 'track', 1),
    ],
    'relation': [
        ('개수 · 밀도', [('Count', 'A 안 B 개수'), ('Density', '밀도 (개수 ÷ A 면적)'),
                      ('AreaFrac', 'B 면적 합 ÷ A 면적')], 'region', 0),
        ('겹침', [('OverlapArea', '겹친 면적'), ('OverlapA', '겹친 비율 (A 기준)'), ('OverlapB', '겹친 비율 (B 기준)'),
                ('IoU', 'IoU')], 'region', 0),
        ('거리', [('DistEdge', 'B → A 경계 최단 거리'), ('NND', 'B → 가장 가까운 B (NND)'),
                ('RelPos', 'B의 상대 위치 (0 안 · 1 경계)')], 'region', 0),
        ('등거리 띠', [('Bands', '등거리 띠 (등거리 띠 탭 설정)')], 'region', 0),
        ('분배 · 농축', [('Partition', '분배 계수'), ('Enrich', '농축 비율')], 'region', 1),
        ('공존 (Coloc 2)', [('Coloc', 'Pearson · Manders · Li ICQ (Coloc 2 탭 설정)')], 'region', 2),
        ('트랙만', [('InsideFrac', 'B 트랙이 A 안에 있던 프레임 비율'), ('Crossings', 'A 경계를 넘은 횟수')],
         'track', 0),
    ],
}
SHAPE_REGION = {p for _g, ps, a, _c in PARAMS['shape'] if a == 'region' for p, _t in ps}
PARAM_TEXT = {p: t for groups in PARAMS.values() for _g, ps, _a, _c in groups for p, t in ps}
BG = (('none', '없음'), ('ring', 'ROI 둘레 고리 (µm)'), ('outside', '세포 밖 중앙값'), ('roi', '다른 ROI의 값'),
      ('low', '이미지 하위 n %'))
ROW_UNITS = (('a', 'A마다 (B를 요약)'), ('b', 'B마다 (속한 A와 거리)'))

CALC_OPS = (('/', '÷'), ('-', '−'), ('+', '+'), ('*', '×'), ('log2', 'log₂ (A)'), ('expr', '식 쓰기'))
NORMS = (('none', '안 함'), ('first', '첫 시점 = 1'), ('firstn', '처음 n 시점 평균 = 1'), ('control', '대조군 그룹 평균 = 1'),
         ('minmax', '최소–최대 (0–1)'), ('z', 'z-score'))
SCOPES = (('track', '트랙마다'), ('roi', 'ROI마다'), ('image', '이미지마다'), ('group', '그룹마다'), ('all', '전체'))
PAIR_ROWS = (('same', '같은 ROI · 같은 시점'), ('parent', '부모 ROI의 값'), ('image', '이미지 평균'))

# v2 object names -> v4 default names
V2_NAMES = {'세포': 'Cell', '핵': 'Nuc', '세포질': 'Cyto', '입자': 'Spot', '미토 조각': 'Mito', '입자 트랙': 'Spot_track',
            '세포 트랙': 'Cell_track'}


def method_names(method) -> list:
    return [(r, n, k, t) for r, n, k, t in METHODS[method][1]]


def detect_outputs(st) -> list:
    """[(name, kind)] a detect.roi stage makes."""
    s = st.get('settings') or {}
    names = s.get('names') or {}
    out = []
    for role, default, kind, _t in METHODS.get(s.get('method', 'cells'), METHODS['cells'])[1]:
        n = names.get(role, default)
        if n:
            out.append((n, kind))
    return out


# ---------------------------------------------------------------------------
# objects by name
# ---------------------------------------------------------------------------

def named_objects(it, base=None) -> dict:
    """name -> PipeObject: detected / tracked names (aliases of the tab
    results, read now) and the names made by ROI 연산 / 필터."""
    from .pipeline import PipeObject, base_objects
    base = base if base is not None else base_objects(it)
    out = {}
    for name, key in (getattr(it, 'pipe_alias', None) or {}).items():
        o = base.get(key)
        if o is not None:
            out[name] = PipeObject(name, o.kind, o.labels, o.parent, o.source, o.tracks, o.track_of)
    out.update(getattr(it, 'pipe_objects', None) or {})
    return out


def obj_kind(o) -> str:
    if o.kind == 'track':
        return 'track'
    return 'spot' if o.source == 'detect.particles' else 'region'


# ---------------------------------------------------------------------------
# ROI 연산 / ROI 필터
# ---------------------------------------------------------------------------

def roi_op(it, s, objs) -> dict:
    """One ROI 연산 on one image → {out name: PipeObject} (v3 `apply_op` with no condition)."""
    from .pipeline import apply_op
    do = s.get('do', 'subtract')
    a = {'do': do, 'with': s.get('b', ''), 'pair': s.get('pair', 'cell'), 'um': s.get('um', 1.0),
         'inner': s.get('inner', 2.0), 'outer': s.get('outer', 6.0), 'n': s.get('n', 4)}
    if do == 'ring':
        a['outside_cells'] = bool(s.get('avoid'))
        a['avoid'] = s.get('avoid', '')
    if do == 'bands':
        a['nuc'] = s.get('b', '')
    return apply_op(it, {'input': s.get('a'), 'where': {}, 'action': a, 'out': s.get('out')}, objs)


NATIVE = ('Area', 'Perimeter', 'Circularity', 'Solidity', 'Feret', 'AR', 'Mean', 'IntDen', 'Max', 'Min', 'Median',
          'overlap', 'inside', 'contains', 'dist', 'parent_in', 'edge', 'cell', 'frames', 'divided', 'change', 'class')


def _table_hits(it, src, c, tables) -> set:
    """ROIs of ``src`` whose measured parameter (a column of a measurement
    table, e.g. 「신호 › GFP Mean」) passes the condition."""
    from .pipeline import _cmp
    f, op = str(c[0]), c[1]
    val = c[2] if len(c) > 2 else None
    vals = {}
    for rows in (tables or {}).values():
        for r in rows:
            if r.get('image_id') != it.image_id or f not in r:
                continue
            if r.get('roi', r.get('object')) != src.name:
                continue
            lab = r.get('label')
            if r.get('summary') == 'track' or lab not in vals:
                vals[lab] = r[f]
    if not vals:
        raise ValueError(f'측정값 "{f}"이(가) {src.name}에 없습니다 (앞의 측정 단계에서 이 ROI를 재세요).')
    return {i for i in src.ids() if _cmp(vals.get(i), op, val)}


def roi_filter(it, s, objs, tables=None) -> dict:
    """ROI 필터: the ROIs of ``input`` that pass ``conds`` (and / or) → out, the rest → rest."""
    from .pipeline import _subset, matching
    src = objs.get(s.get('input'))
    if src is None:
        raise ValueError(f'ROI "{s.get("input")}"이(가) 없습니다.')
    conds = s.get('conds') or []
    native = [c for c in conds if str(c[0]).partition(':')[0] in NATIVE]
    if len(native) == len(conds):
        hit = matching(it, src, {'mode': s.get('mode', 'all'), 'conds': conds}, objs)
    else:
        sets = [matching(it, src, {'mode': 'all', 'conds': [c]}, objs) if c in native else
                _table_hits(it, src, c, tables) for c in conds]
        hit = set.intersection(*sets) if s.get('mode', 'all') == 'all' else set.union(*sets)
    out = {}
    if s.get('out'):
        out[s['out']] = _subset(src, hit, s['out'])
    if s.get('rest'):
        out[s['rest']] = _subset(src, set(src.ids()) - hit, s['rest'])
    return out


def relation_values(it, obj, f, objs) -> dict:
    """label -> value for the relation fields contains / dist / parent_in (ROI 필터)."""
    head, _, arg = f.partition(':')
    other = objs.get(arg)
    if other is None or other.labels is None:
        raise ValueError(f'ROI "{arg}"이(가) 없습니다.')
    lab = obj.labels
    px = float(it.pixel_um or 1.0)
    out = {}
    if head == 'contains':
        from skimage import measure
        H, W = lab.shape
        cen = np.zeros(lab.shape, bool)
        for r in measure.regionprops(other.labels):
            cy, cx = (int(round(x)) for x in r.centroid)
            cen[min(cy, H - 1), min(cx, W - 1)] = True
        for i, sl in enumerate(ndi.find_objects(lab), start=1):
            if sl is not None:
                out[i] = bool(cen[sl][lab[sl] == i].any())
    elif head == 'dist':
        d = ndi.distance_transform_edt(other.labels == 0) * px
        for i, sl in enumerate(ndi.find_objects(lab), start=1):
            if sl is not None:
                out[i] = float(d[sl][lab[sl] == i].min())
    elif head == 'parent_in':
        have = {p for p in other.parent.values() if p}
        for i in obj.ids():
            out[i] = obj.parent.get(i, 0) in have
    return out


# ---------------------------------------------------------------------------
# 측정
# ---------------------------------------------------------------------------

def _head(it):
    return {'image': it.label, 'image_id': it.image_id, 'group': it.group or ''}


def col(name, ch, p) -> str:
    """Parameter column 「측정 이름 › [채널] 파라미터」 (design §6.1)."""
    return f'{name} › {ch} {p}' if ch else f'{name} › {p}'


def measure_name(s) -> str:
    if s.get('name'):
        return s['name']
    t = dict(MEASURE_TYPES).get(s.get('type', 'signal'), '측정')
    who = ' ⊃ '.join(x for x in (s.get('a'), s.get('b') if s.get('type') == 'relation' else '') if x)
    return f'{t} · {who}' if who else t


def _channels(it, s):
    return [c for c in (s.get('channels') or list(it.channels))]


def _plane(it, ch, z=''):
    from .pipeline import _plane as plane
    if not z:
        return plane(it, ch)
    chs = list(it.channels)
    k = chs.index(ch) if ch in chs else int(ch)
    try:
        stack = np.asarray(it.zstack(k), float) if hasattr(it, 'zstack') else None
    except Exception:  # noqa: BLE001
        stack = None
    if stack is None or stack.ndim != 3:
        return plane(it, ch)
    return {'mip': stack.max(0), 'mean': stack.mean(0), 'sum': stack.sum(0)}.get(z, plane(it, ch))


def measure_rows(it, s, objs, win=None) -> list:
    t = s.get('type', 'signal')
    if t == 'shape':
        return measure_shape(it, s, objs)
    if t == 'relation':
        return measure_relation(it, s, objs, win)
    return measure_signal(it, s, objs)


def _region_head(it, obj, i):
    return {**_head(it), 'roi': obj.name, 'label': int(i), 'parent': int(obj.parent.get(i, 0))}


def measure_shape(it, s, objs) -> list:
    from skimage import measure
    from .pipeline import mina_rows
    obj = objs.get(s.get('a'))
    if obj is None:
        raise ValueError(f'ROI "{s.get("a")}"이(가) 없습니다.')
    name = measure_name(s)
    params = s.get('params') or ['Area']
    if obj.kind == 'track':
        return track_shape(it, obj, params, name)
    if 'Skeleton' in params:     # MiNA on mitoROI's fragments (v3 measure.mina)
        return mina_rows(it)
    px = float(it.pixel_um or 1.0)
    lab = obj.labels
    parent_obj = objs.get(s.get('parent_roi')) if s.get('parent_roi') else None
    if parent_obj is None:
        parent_obj = next((o for o in objs.values() if o.kind != 'track' and o.labels is not None
                           and o.source == 'detect.cells' and o is not obj and set(o.parent) == set(o.parent.values())),
                          None)
    pcen = {}
    pedge = None
    if parent_obj is not None and parent_obj.labels is not None:
        for r in measure.regionprops(parent_obj.labels):
            pcen[r.label] = r.centroid
        if 'DistParentEdge' in params:
            pedge = ndi.distance_transform_edt(parent_obj.labels > 0) * px
    rows = []
    for r in measure.regionprops(lab):
        i = r.label
        a = r.area * px * px
        per = r.perimeter * px
        maj, mnr = r.axis_major_length * px, r.axis_minor_length * px
        v = {'Area': a, 'Perimeter': per, 'Feret': r.feret_diameter_max * px,
             'MinFeret': mnr, 'Major': maj, 'Minor': mnr, 'EqDiam': 2 * math.sqrt(a / math.pi),
             'Circularity': min(1.0, 4 * math.pi * a / per ** 2) if per > 0 else 0.0,
             'AR': maj / max(mnr, 1e-9), 'Round': 4 * a / (math.pi * maj ** 2) if maj else np.nan,
             'Solidity': r.solidity, 'Eccentricity': r.eccentricity,
             'X': r.centroid[1] * px, 'Y': r.centroid[0] * px}
        p = obj.parent.get(i, 0)
        if 'DistParent' in params:
            c = pcen.get(p)
            v['DistParent'] = math.hypot((r.centroid[0] - c[0]) * px, (r.centroid[1] - c[1]) * px) if c else np.nan
        if 'DistParentEdge' in params:
            cy, cx = (int(round(x)) for x in r.centroid)
            v['DistParentEdge'] = float(pedge[min(cy, lab.shape[0] - 1), min(cx, lab.shape[1] - 1)]) \
                if pedge is not None else np.nan
        row = _region_head(it, obj, i)
        for k in params:
            if k in v:
                row[col(name, '', k)] = float(v[k])
        rows.append(row)
    return rows


def _track_points(it, obj):
    keep = set(obj.ids())
    if obj.track_of == 'cell':
        by = {}
        for r in it.cell_tracks.rows:
            if r['cell_id'] in keep:
                by.setdefault(r['cell_id'], []).append(r)
        return by, 'cell'
    by = {}
    for p in it.tracks.points:
        if p['track_id'] in keep:
            by.setdefault(p['track_id'], []).append(p)
    return by, 'particle'


def _xy_t(p):
    x = p.get('x_um', p.get('x', np.nan))
    y = p.get('y_um', p.get('y', np.nan))
    t = p.get('time_min', p.get('time_h', p.get('frame', np.nan)))
    if 'time_h' in p and 'time_min' not in p:
        t = p['time_h'] * 60
    return float(x), float(y), float(t)


def track_shape(it, obj, params, name) -> list:
    by, _k = _track_points(it, obj)
    px = float(it.pixel_um or 1.0)
    rows = []
    for tid, pts in sorted(by.items()):
        pts = sorted(pts, key=lambda p: p['frame'])
        xyt = [_xy_t(p) for p in pts]
        if obj.track_of == 'cell':   # cell rows are in pixels
            xyt = [(x * px, y * px, t) for x, y, t in xyt]
        steps = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(xyt, xyt[1:])]
        path = float(np.nansum(steps)) if steps else 0.0
        disp = math.hypot(xyt[-1][0] - xyt[0][0], xyt[-1][1] - xyt[0][1]) if len(xyt) > 1 else 0.0
        dt = xyt[-1][2] - xyt[0][2] if len(xyt) > 1 else 0.0
        v = {'Frames': len(pts), 'PathLength': path, 'Displacement': disp,
             'Speed': path / dt if dt else np.nan, 'Straightness': disp / path if path else np.nan}
        row = {**_head(it), 'roi': obj.name, 'label': int(tid)}
        for k in params:
            if k in v:
                row[col(name, '', k)] = float(v[k])
        rows.append(row)
    return rows


def _bg_value(it, s, ch, img, objs, obj, ids):
    """Background per label (dict) or one value for the image."""
    from .pipeline import _bg_value as outside
    bg = s.get('bg', 'none')
    if bg == 'outside':
        return outside(it, ch)
    if bg == 'low':
        return float(np.percentile(img, float(s.get('low_pct', 10))))
    if bg in ('roi', 'ring'):
        if bg == 'ring':
            from .pipeline import apply_op
            ring = apply_op(it, {'input': obj.name, 'where': {}, 'out': '_ring',
                                 'action': {'do': 'ring', 'inner': (s.get('ring') or [0.5, 2.0])[0],
                                            'outer': (s.get('ring') or [0.5, 2.0])[1],
                                            'outside_cells': False}}, {**objs, obj.name: obj})['_ring']
            rlab = ring.labels
            return {i: (float(np.median(img[rlab == i])) if (rlab == i).any() else np.nan) for i in ids}
        ring = objs.get(s.get('bg_roi'))
        if ring is None or ring.labels is None:
            raise ValueError(f'배경 ROI "{s.get("bg_roi")}"이(가) 없습니다.')
        rp = np.zeros(int(ring.labels.max()) + 1, np.int64)
        for j, p in ring.parent.items():
            rp[j] = p
        rpar = np.where(ring.labels > 0, rp[ring.labels], 0)
        return {i: (float(np.median(img[rpar == obj.parent.get(i, -1)]))
                    if (rpar == obj.parent.get(i, -1)).any() else np.nan) for i in ids}
    return 0.0


def measure_signal(it, s, objs) -> list:
    """ImageJ Measure values of ROI × channel (each channel separately), or a
    track's points and its time summary."""
    obj = objs.get(s.get('a'))
    if obj is None:
        raise ValueError(f'ROI "{s.get("a")}"이(가) 없습니다.')
    name = measure_name(s)
    params = s.get('params') or ['Area', 'Mean', 'IntDen']
    if obj.kind == 'track':
        return track_signal(it, obj, s, name, params)
    chans = _channels(it, s)
    lab = obj.labels
    ids = obj.ids()
    if not ids:
        return []
    px = float(it.pixel_um or 1.0)
    bg = s.get('bg', 'none')
    counts = np.bincount(lab.ravel(), minlength=int(lab.max()) + 1)
    rows = {i: _region_head(it, obj, i) for i in ids}
    if 'Area' in params:
        for i in ids:
            rows[i][col(name, '', 'Area')] = float(counts[i] * px * px)
    for ch in chans:
        img = _plane(it, ch, s.get('z', ''))
        b = _bg_value(it, s, ch, img, objs, obj, ids) if bg != 'none' else 0.0
        d = {}
        for p in params:
            if p == 'Mean':
                d[p] = ndi.mean(img, lab, ids)
            elif p == 'StdDev':
                d[p] = ndi.standard_deviation(img, lab, ids)
            elif p == 'Min':
                d[p] = ndi.minimum(img, lab, ids)
            elif p == 'Max':
                d[p] = ndi.maximum(img, lab, ids)
            elif p == 'Median':
                d[p] = ndi.median(img, lab, ids)
            elif p == 'RawIntDen':
                d[p] = ndi.sum(img, lab, ids)
            elif p == 'IntDen':
                d[p] = np.asarray(ndi.sum(img, lab, ids)) * px * px
        extra = {}
        if any(p in params for p in ('TopMean', 'CV', 'PosFrac')):
            thr = _on_threshold(it, s, ch)
            n = float(s.get('top_pct', 10))
            for i, sl in zip(range(1, int(lab.max()) + 1), ndi.find_objects(lab)):
                if sl is None or i not in rows:
                    continue
                v = img[sl][lab[sl] == i]
                bb = b.get(i, 0.0) if isinstance(b, dict) else b
                e = {}
                if 'TopMean' in params:
                    k = max(1, int(round(v.size * n / 100)))
                    e['TopMean'] = float(np.sort(v)[-k:].mean()) - bb
                if 'CV' in params:
                    e['CV'] = float(v.std() / v.mean()) if v.mean() else np.nan
                if 'PosFrac' in params:
                    e['PosFrac'] = float((v >= thr).mean()) if np.isfinite(thr) else np.nan
                extra[i] = e
        for k, i in enumerate(ids):
            bb = b.get(i, np.nan) if isinstance(b, dict) else b
            for p in params:
                if p in d:
                    v = float(np.atleast_1d(d[p])[k])
                    if bg != 'none':
                        if p in ('Mean', 'Median', 'Min', 'Max'):
                            v -= bb
                        elif p in ('IntDen', 'RawIntDen'):
                            v -= bb * counts[i] * (px * px if p == 'IntDen' else 1)
                    rows[i][col(name, ch, p)] = v
                elif p in extra.get(i, {}):
                    rows[i][col(name, ch, p)] = extra[i][p]
            if bg != 'none':
                rows[i][col(name, ch, 'bg')] = bb
    shape = [p for p in params if p in SHAPE_REGION and p != 'Area']
    if shape:   # e.g. Analyze Particles: Perimeter, Circularity with the intensities
        for r in measure_shape(it, {**s, 'params': shape}, objs):
            rows.get(r['label'], {}).update({k: v for k, v in r.items() if ' › ' in k})
    return [rows[i] for i in ids]


def _on_threshold(it, s, ch):
    on = s.get('on', 'lut')
    if on == 'lut':
        chs = list(it.channels)
        if ch in chs:
            return float(it.luts[chs.index(ch)].vmin)
        return np.nan
    try:
        return float(on)
    except (TypeError, ValueError):
        return np.nan


def _value_key(p0, ch, bgsub):
    for k in ((f'I_{ch}' if bgsub else f'I_{ch}_raw'), f'I_{ch}', f'I_{ch}_raw', 'I_thr' if bgsub else 'I_raw',
              'I', 'I_raw'):
        if k in p0:
            return k
    return None


def track_signal(it, obj, s, name, params) -> list:
    """Track × time: the tracker's point rows (as v3), and with 시간 params a
    summary per track and channel (``rows`` of kind 'track')."""
    by, kind = _track_points(it, obj)
    rows = []
    for tid in sorted(by):
        for p in sorted(by[tid], key=lambda r: r['frame']):
            r = {k: v for k, v in p.items() if not k.startswith('_')}
            rows.append({**_head(it), 'object': obj.name, 'label': tid, **r})
    time_params = [p for p in params if p in PARAM_TEXT and p in dict(PARAMS['signal'][2][1])]
    if not time_params or time_params == ['PerFrame']:
        return rows
    summary = []
    bgsub = s.get('bg', 'none') != 'none'
    for ch in (_channels(it, s) if kind == 'particle' else ['']):
        thr = _on_threshold(it, s, ch) if ch else np.nan
        for tid in sorted(by):
            pts = sorted(by[tid], key=lambda r: r['frame'])
            key = _value_key(pts[0], ch, bgsub)
            if key is None:
                continue
            v = np.array([float(p.get(key, np.nan)) for p in pts])
            t = np.array([_xy_t(p)[2] for p in pts])
            ok = np.isfinite(v)
            on = v >= thr if np.isfinite(thr) else np.zeros(len(v), bool)
            row = {**_head(it), 'roi': obj.name, 'label': int(tid), 'summary': 'track'}
            vals = {'First': v[ok][0] if ok.any() else np.nan, 'Last': v[ok][-1] if ok.any() else np.nan,
                    'TMax': np.nanmax(v) if ok.any() else np.nan, 'TMin': np.nanmin(v) if ok.any() else np.nan,
                    'OnFrames': int(on.sum()), 'FirstOn': float(t[on][0]) if on.any() else np.nan}
            vals['MaxOverStart'] = vals['TMax'] / vals['First'] if vals['First'] else np.nan
            n = max(1, len(on) // 3)
            vals['Change'] = ('켜짐→꺼짐' if on[:n].any() and not on[-n:].any() else
                              '켜짐' if on.any() else '꺼짐') if np.isfinite(thr) else ''
            for p in time_params:
                if p in vals:
                    row[col(name, ch, p)] = vals[p]
            summary.append(row)
    return rows + summary


def _cells_of(a_obj, b_obj):
    """b label -> a label it sits in (the b's parent when a carries cell numbers, else by overlap)."""
    out = {}
    for j, sl in enumerate(ndi.find_objects(b_obj.labels), start=1):
        if sl is None:
            continue
        v = a_obj.labels[sl][b_obj.labels[sl] == j]
        v = v[v > 0]
        out[j] = int(np.bincount(v).argmax()) if v.size else 0
    return out


def measure_relation(it, s, objs, win=None) -> list:
    """ROI A (outside / parent) and B (inside / object); count, overlap,
    distance, partition per A (or per B); bands / Coloc 2 through their tabs."""
    from .pipeline import measure_count
    a, b = objs.get(s.get('a')), objs.get(s.get('b'))
    params = s.get('params') or ['Count']
    name = measure_name(s)
    if a is None:
        raise ValueError(f'ROI "{s.get("a")}"이(가) 없습니다.')
    rows = []
    tab = [p for p in params if p in ('Bands', 'Coloc')]
    rest = [p for p in params if p not in tab]
    if 'Coloc' in params:
        for r in getattr(it, 'coloc', None) or []:
            rows.append({**_head(it), 'roi': a.name, **{k: v for k, v in r.items() if not k.startswith('_')}})
    if not rest:
        return rows
    if b is None:
        raise ValueError(f'ROI "{s.get("b")}"이(가) 없습니다.')
    if b.kind == 'track':
        return rows + track_relation(it, a, b, rest, name)
    px = float(it.pixel_um or 1.0)
    if rest == ['Count', 'Density'] or rest == ['Count'] or rest == ['Density']:
        # the v3 개수 · 밀도 table, values unchanged (b's parent = its cell)
        old = measure_count(it, {'object': b.name, 'parent': a.name}, objs)
        for r in old:
            row = {**_head(it), 'roi': a.name, 'label': r['cell'], 'object': b.name}
            if 'Count' in rest:
                row[col(name, '', 'Count')] = r['count']
            if 'Density' in rest:
                row[col(name, '', 'Density')] = r['density_per_um2']
            row[col(name, '', 'A Area')] = r['parent_area_um2']
            rows.append(row)
        return rows
    in_a = {j: b.parent.get(j, 0) for j in b.ids()} if set(a.parent.values()) <= set(a.ids()) and b.parent \
        else _cells_of(a, b)
    a_area = np.bincount(a.labels.ravel(), minlength=int(a.labels.max()) + 1) * px * px
    b_area = np.bincount(b.labels.ravel(), minlength=int(b.labels.max()) + 1) * px * px
    unit = s.get('row', 'a')
    chans = _channels(it, s) if any(p in rest for p in ('Partition', 'Enrich')) else []
    planes = {ch: _plane(it, ch, s.get('z', '')) for ch in chans}
    if unit == 'b' or any(p in rest for p in ('DistEdge', 'NND', 'RelPos')):
        from skimage import measure
        H, W = a.labels.shape
        props = {r.label: r for r in measure.regionprops(b.labels)}
        cen = {j: r.centroid for j, r in props.items()}
        dist_edge = ndi.distance_transform_edt(a.labels > 0) * px
        nnd = {}
        if 'NND' in rest and len(cen) > 1:
            from scipy.spatial import cKDTree
            keys = list(cen)
            pts = np.array([cen[k] for k in keys]) * px
            d, _ = cKDTree(pts).query(pts, 2)
            nnd = {k: float(d[n, 1]) for n, k in enumerate(keys)}
        if unit == 'b':
            ref = objs.get(s.get('ref_roi')) if s.get('ref_roi') else None
            for j, c in cen.items():
                cy, cx = min(int(round(c[0])), H - 1), min(int(round(c[1])), W - 1)
                row = {**_head(it), 'roi': b.name, 'label': j, 'parent': int(in_a.get(j, 0)), 'in': a.name}
                if 'DistEdge' in rest:
                    row[col(name, '', 'DistEdge')] = float(dist_edge[cy, cx])
                if 'NND' in rest:
                    row[col(name, '', 'NND')] = nnd.get(j, np.nan)
                if 'RelPos' in rest:
                    de = float(dist_edge[cy, cx])
                    if ref is not None and ref.labels is not None:
                        dr = ndi.distance_transform_edt(ref.labels == 0)[cy, cx] * px
                        row[col(name, '', 'RelPos')] = dr / (dr + de) if dr + de else np.nan
                    else:
                        dmax = dist_edge[a.labels == a.labels[cy, cx]].max() if a.labels[cy, cx] else 0
                        row[col(name, '', 'RelPos')] = 1 - de / dmax if dmax else np.nan
                if 'OverlapB' in rest:
                    m = b.labels == j
                    row[col(name, '', 'OverlapB')] = float((a.labels[m] > 0).mean())
                rows.append(row)
            return rows
    for i in a.ids():
        mine = [j for j, p in in_a.items() if p == i]
        row = {**_head(it), 'roi': a.name, 'label': int(i), 'object': b.name}
        ma = a.labels == i
        if 'Count' in rest:
            row[col(name, '', 'Count')] = len(mine)
        if 'Density' in rest:
            row[col(name, '', 'Density')] = len(mine) / a_area[i] if a_area[i] else np.nan
        if 'AreaFrac' in rest:
            row[col(name, '', 'AreaFrac')] = float(sum(b_area[j] for j in mine) / a_area[i]) if a_area[i] else np.nan
        if any(p in rest for p in ('OverlapArea', 'OverlapA', 'OverlapB', 'IoU')):
            mb = b.labels > 0
            inter = float((ma & mb).sum()) * px * px
            bsum = float(sum(b_area[j] for j in np.unique(b.labels[ma]) if j > 0))
            if 'OverlapArea' in rest:
                row[col(name, '', 'OverlapArea')] = inter
            if 'OverlapA' in rest:
                row[col(name, '', 'OverlapA')] = inter / a_area[i] if a_area[i] else np.nan
            if 'OverlapB' in rest:
                row[col(name, '', 'OverlapB')] = inter / bsum if bsum else np.nan
            if 'IoU' in rest:
                union = a_area[i] + bsum - inter
                row[col(name, '', 'IoU')] = inter / union if union else np.nan
        if 'DistEdge' in rest or 'NND' in rest:
            ds = [float(dist_edge[min(int(round(cen[j][0])), H - 1), min(int(round(cen[j][1])), W - 1)])
                  for j in mine if j in cen]
            if 'DistEdge' in rest:
                row[col(name, '', 'DistEdge mean')] = float(np.mean(ds)) if ds else np.nan
            if 'NND' in rest:
                v = [nnd[j] for j in mine if j in nnd]
                row[col(name, '', 'NND mean')] = float(np.mean(v)) if v else np.nan
        for ch, img in planes.items():
            mb = np.isin(b.labels, mine) & ma if mine else np.zeros_like(ma)
            inside = img[mb]
            out = img[ma & ~mb]
            if 'Partition' in rest:
                row[col(name, ch, 'Partition')] = float(inside.mean() / out.mean()) \
                    if inside.size and out.size and out.mean() else np.nan
            if 'Enrich' in rest:
                tot = float(img[ma].sum())
                row[col(name, ch, 'Enrich')] = float(inside.sum() / tot) if tot else np.nan
        rows.append(row)
    return rows


def track_relation(it, a, b, params, name) -> list:
    by, kind = _track_points(it, b)
    px = float(it.pixel_um or 1.0)
    H, W = a.labels.shape
    rows = []
    for tid, pts in sorted(by.items()):
        pts = sorted(pts, key=lambda p: p['frame'])
        ins = []
        for p in pts:
            x = p.get('x', np.nan)
            y = p.get('y', np.nan)
            if kind == 'particle' and 'x' not in p and 'x_um' in p:
                x, y = p['x_um'] / px, p['y_um'] / px
            if not (np.isfinite(x) and np.isfinite(y)):
                continue
            ins.append(bool(a.labels[min(max(int(round(y)), 0), H - 1), min(max(int(round(x)), 0), W - 1)] > 0))
        row = {**_head(it), 'roi': b.name, 'label': int(tid), 'in': a.name}
        if 'InsideFrac' in params:
            row[col(name, '', 'InsideFrac')] = float(np.mean(ins)) if ins else np.nan
        if 'Crossings' in params:
            row[col(name, '', 'Crossings')] = int(sum(1 for u, v in zip(ins, ins[1:]) if u != v))
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# 측정값 연산
# ---------------------------------------------------------------------------

KEYS = ('image_id', 'roi', 'object', 'label', 'frame')


def _key(r, keys=KEYS):
    return tuple(r.get(k) for k in keys)


def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return np.nan
    return v


def calc_values(tables: dict, s: dict) -> tuple[str, int]:
    """Adds the parameter ``out`` to the rows of ``table`` (A · op · B, then
    the normalization over ``scope``); returns (table, rows filled)."""
    tname = s.get('table')
    rows = tables.get(tname)
    if not rows:
        raise ValueError(f'표 "{tname}"이(가) 없습니다.')
    out = s.get('out') or '계산'
    a, b, op = s.get('a', ''), s.get('b', ''), s.get('op', '/')
    btab = tables.get(s.get('b_table') or tname) or rows
    pair = s.get('pair', 'same')

    def bval(r):
        if b == '' or b is None:
            return np.nan
        try:
            return float(b)
        except (TypeError, ValueError):
            pass
        if btab is rows and pair == 'same':
            return _num(r.get(b))
        return lut_b(r)
    lut = {}
    if btab is not rows or pair != 'same':
        if pair == 'image':
            acc = {}
            for r in btab:
                acc.setdefault(r.get('image_id'), []).append(_num(r.get(b)))
            lut = {k: float(np.nanmean(v)) for k, v in acc.items()}
        elif pair == 'parent':
            lut = {(r.get('image_id'), r.get('label')): _num(r.get(b)) for r in btab}
        else:
            lut = {_key(r): _num(r.get(b)) for r in btab}

    def lut_b(r):
        if pair == 'image':
            return lut.get(r.get('image_id'), np.nan)
        if pair == 'parent':
            return lut.get((r.get('image_id'), r.get('parent', r.get('cell'))), np.nan)
        return lut.get(_key(r), np.nan)

    vals = []
    for r in rows:
        x = _num(r.get(a))
        y = bval(r)
        with np.errstate(all='ignore'):
            if op == '/':
                v = x / y if y else np.nan
            elif op == '-':
                v = x - y
            elif op == '+':
                v = x + y
            elif op == '*':
                v = x * y
            elif op == 'log2':
                v = math.log2(x) if x > 0 else np.nan
            elif op == 'expr':
                v = _expr(s.get('expr', 'A'), x, y)
            else:
                v = x
        vals.append(v)
    vals = normalize(rows, vals, s)
    n = 0
    for r, v in zip(rows, vals):
        r[out] = v
        n += int(np.isfinite(v)) if isinstance(v, float) else 1
    return tname, n


def _expr(text, a, b):
    safe = {'A': a, 'B': b, 'log2': np.log2, 'log10': np.log10, 'log': np.log, 'sqrt': np.sqrt, 'abs': abs,
            'exp': np.exp}
    try:
        return float(eval(compile(text, '<식>', 'eval'), {'__builtins__': {}}, safe))  # noqa: S307
    except Exception:  # noqa: BLE001
        return np.nan


def _scope_key(r, scope):
    if scope == 'track':
        return (r.get('image_id'), r.get('roi', r.get('object')), r.get('label', r.get('track_id')))
    if scope == 'roi':
        return (r.get('image_id'), r.get('roi', r.get('object')), r.get('label'))
    if scope == 'image':
        return r.get('image_id')
    if scope == 'group':
        return r.get('group')
    return 0


def normalize(rows, vals, s):
    norm = s.get('norm', 'none')
    if norm == 'none':
        return vals
    scope = s.get('scope', 'track')
    vals = np.asarray(vals, float)
    out = vals.copy()
    groups = {}
    for k, r in enumerate(rows):
        groups.setdefault(_scope_key(r, scope), []).append(k)
    frame = [_num(r.get('frame', r.get('time_min', k))) for k, r in enumerate(rows)]
    if norm == 'control':
        ctrl = [vals[k] for k, r in enumerate(rows) if r.get('group') == s.get('control')]
        ref = float(np.nanmean(ctrl)) if ctrl else np.nan
        return list(vals / ref) if ref else [np.nan] * len(vals)
    for _g, ks in groups.items():
        ks = sorted(ks, key=lambda k: frame[k])
        v = vals[ks]
        ok = v[np.isfinite(v)]
        if not ok.size:
            continue
        if norm == 'first':
            ref = ok[0]
            out[ks] = v / ref if ref else np.nan
        elif norm == 'firstn':
            ref = float(np.mean(ok[:max(1, int(s.get('n', 3)))]))
            out[ks] = v / ref if ref else np.nan
        elif norm == 'minmax':
            lo, hi = ok.min(), ok.max()
            out[ks] = (v - lo) / (hi - lo) if hi > lo else np.nan
        elif norm == 'z':
            sd = ok.std()
            out[ks] = (v - ok.mean()) / sd if sd else np.nan
    return list(out)


# ---------------------------------------------------------------------------
# columns a stage will make (editors, ROI 필터 by value, graph column sets)
# ---------------------------------------------------------------------------

def predicted_columns(st, channels) -> list:
    s = st.get('settings') or {}
    if st['kind'] == 'calc.values':
        return [s.get('out') or '계산']
    if st['kind'] != 'measure.roi':
        return []
    name = measure_name(s)
    params = s.get('params') or []
    chans = s.get('channels') or list(channels)
    out = []
    for p in params:
        if p in ('Bands', 'Coloc', 'Skeleton', 'PerFrame'):
            continue
        per_ch = any(p in dict(ps) and c >= 1 for _g, ps, _a, c in PARAMS.get(s.get('type', 'signal'), []))
        if per_ch and p != 'Area':
            out += [col(name, ch, p) for ch in chans]
        else:
            out.append(col(name, '', p))
    return out


# ---------------------------------------------------------------------------
# v2 → v3 conversion (design §9)
# ---------------------------------------------------------------------------

def _rename(n, names):
    return names.get(n, n) if n else n


def _cond_v4(c, names):
    c = list(c)
    f = str(c[0]) if c else ''
    head, sep, arg = f.partition(':')
    if head in ('overlap', 'inside') and arg:
        c[0] = f'{head}:{_rename(arg, names)}'
    return c


def convert_stages(stages) -> tuple[list, list]:
    """v2 stages (detect.cells … op … measure.intensity) → v4 stages and the
    notes of what changed (shown before the pipeline is saved again)."""
    names = dict(V2_NAMES)
    out, notes = [], []
    tables = {}

    def add(kind, settings, src=None, note=None):
        st = {'kind': kind, 'enabled': (src or {}).get('enabled', True), 'name': '', 'settings': settings,
              'review': False}
        out.append(st)
        if note:
            notes.append(f'{len(out)}. {note}')
        return st
    for st in stages:
        k = st.get('kind')
        s = copy.deepcopy(st.get('settings') or {})
        if k in ('detect.cells', 'detect.particles', 'detect.mito'):
            m = {'detect.cells': 'cells', 'detect.particles': 'particles', 'detect.mito': 'mito'}[k]
            nm = {r: n for r, n, _k, _t in METHODS[m][1]}
            ns = {'detect.mito': {'cells': names['세포']}}.get(k, {})
            add('detect.roi', {'method': m, 'panel': s.get('panel'), 'redo': s.get('redo', True), 'names': nm,
                               'channels': {}, **ns}, st,
                f'{METHODS[m][0]} → 검출 · 이름 {", ".join(nm.values())}')
        elif k in ('track.particles', 'track.cytosol'):
            alg = 'particle' if k == 'track.particles' else 'cytosol'
            d = {'algorithm': alg, 'input': '', 'panel': s.get('panel'), 'cell_track': s.get('cell_track'),
                 'redo': s.get('redo', True), 'out': TRACKERS[alg][2]}
            if s.get('signal_thr') is not None:
                d['signal_thr'] = s['signal_thr']
            add('roi.track', d, st, f'{"입자 추적" if alg == "particle" else "세포질 강도 추적"} → ROI 추적 · 이름 {d["out"]}')
        elif k == 'op':
            a = s.get('action') or {}
            do = a.get('do', 'keep')
            conds = [_cond_v4(c, names) for c in (s.get('where') or {}).get('conds') or []]
            inp = _rename(s.get('input'), names)
            outn, rest = s.get('out') or f'{inp} 연산', s.get('rest') or ''
            by = 'value' if any(str(c[0]).split(':')[0] not in ('overlap', 'inside') for c in conds) else 'relation'
            if do in ('keep', 'drop'):
                o, r = (outn, rest) if do == 'keep' else (rest, outn)
                add('roi.filter', {'input': inp, 'by': by, 'mode': (s.get('where') or {}).get('mode', 'all'),
                                   'conds': conds, 'out': o, 'rest': r}, st,
                    f'연산 「{outn}」 (조건 {len(conds)}) → ROI 필터')
                continue
            if conds:
                sel = f'{inp}_sel'
                add('roi.filter', {'input': inp, 'by': by, 'mode': (s.get('where') or {}).get('mode', 'all'),
                                   'conds': conds, 'out': sel, 'rest': rest}, st,
                    f'연산 「{outn}」의 조건 → ROI 필터 「{sel}」')
                inp = sel
            d = {'a': inp, 'b': _rename(a.get('with', ''), names), 'do': do, 'pair': a.get('pair', 'cell'),
                 'um': a.get('um', 1.0), 'inner': a.get('inner', 2.0), 'outer': a.get('outer', 6.0),
                 'n': a.get('n', 4), 'out': outn}
            if do == 'ring' and a.get('outside_cells', s.get('input') == '세포'):
                d['avoid'] = names['세포']
            if do == 'bands':
                d['b'] = names['핵']
            add('roi.op', d, st, f'연산 「{outn}」 → ROI 연산 · {dict(ROI_OPS).get(do, do)}')
        elif k == 'measure.intensity':
            tname = s.get('name') or '측정 · ' + ' · '.join(t['object'] for t in s.get('targets') or [])
            bg = s.get('bg', 'none')
            bgd = {'bg': 'none'}
            if bg == 'outside':
                bgd = {'bg': 'outside'}
            elif str(bg).startswith('ring:'):
                bgd = {'bg': 'roi', 'bg_roi': _rename(bg.split(':', 1)[1], names)}
            for t in s.get('targets') or []:
                add('measure.roi', {'type': 'signal', 'a': _rename(t.get('object'), names), 'b': '',
                                    'channels': list(t.get('channels') or []), 'params': list(s.get('stats') or
                                                                                            ['Area', 'Mean', 'IntDen']),
                                    'name': tname, **bgd}, st,
                    f'세기 · {t.get("object")} → 측정 · 신호 강도 (표 「{tname}」)')
            tables[tname] = True
        elif k == 'measure.count':
            add('measure.roi', {'type': 'relation', 'a': _rename(s.get('parent'), names),
                                'b': _rename(s.get('object'), names), 'channels': [], 'params': ['Count', 'Density'],
                                'row': 'a', 'name': s.get('name') or f'개수 · {s.get("object")}'}, st,
                '개수 · 밀도 → 측정 · 관계')
        elif k == 'measure.bands':
            add('measure.roi', {'type': 'relation', 'a': names['세포'], 'b': names['핵'], 'channels': [],
                                'params': ['Bands'], 'panel': s.get('panel'), 'name': '등거리 띠'}, st,
                '등거리 띠 → 측정 · 관계 · 등거리 띠')
        elif k == 'measure.coloc':
            add('measure.roi', {'type': 'relation', 'a': names['세포'], 'b': '', 'channels': [],
                                'params': ['Coloc'], 'panel': s.get('panel'), 'name': 'Coloc 2'}, st,
                'Coloc 2 → 측정 · 관계 · 공존')
        elif k == 'measure.mina':
            add('measure.roi', {'type': 'shape', 'a': names['미토 조각'], 'channels': [], 'params': ['Skeleton'],
                                'name': '미토 형태 (MiNA)'}, st, '미토 형태 (MiNA) → 측정 · 형태 · 골격')
        else:
            out.append(copy.deepcopy(st))
    return out, notes
