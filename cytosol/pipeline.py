"""분석 파이프라인 (owner request 2026-11-23/24, design v3.x in
/mnt/project-files/pipeline/파이프라인_설계안.md; built in v0.73).

A pipeline is an ordered list of stages (JSON ``.cypipe``, format
``cytosol-viewer-pipeline``) in five groups that always read in this order:
시작 → 검출 → 추적 → 연산 → 측정, plus 사람 (검토) and 끝 (그래프, 저장).
Every ROI a stage makes is a named **object** (`PipeObject`); 연산 stages take
an object, an optional condition (`where`), an action and a result name; 측정
stages measure object × channel. Detection and tracking reuse the tabs' own
code through `batch.run` / the panels, with the tab settings stored in the
stage (``settings.panel`` = the panel's `widget_state`, or None = the tab's
current settings). The same `Runner` serves the pipeline window, the batch and
the command line (`cytosol.pipe`).
"""

from __future__ import annotations

import copy
import csv
import json
import math
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage as ndi

FORMAT = 'cytosol-viewer-pipeline'
VERSION = 2
EXT = '.cypipe'
GROUPS = (('start', '시작'), ('detect', '검출'), ('track', '추적'), ('op', '연산'), ('measure', '측정'),
          ('human', '사람'), ('end', '끝'))
GROUP_ORDER = {g: i for i, (g, _t) in enumerate(GROUPS)}


# ---------------------------------------------------------------------------
# stage kinds (the schema `cytosol-pipe stages` prints)
# ---------------------------------------------------------------------------

def _stage(group, title, desc, settings=None, out=(), needs=(), panel=None, batch=None):
    return dict(group=group, title=title, desc=desc, settings=settings or {}, out=list(out), needs=list(needs),
                panel=panel, batch=batch)


STAGES = {
    'start.load': _stage('start', '불러오기', '폴더의 이미지를 엽니다 (비우면 지금 열린 이미지).',
                         {'folder': '', 'glob': '*', 'recursive': True, 'pair': True}),
    'start.auto_group': _stage('start', '자동 그룹', '이름 끝 번호를 뺀 같은 이름끼리 그룹으로 묶습니다.', {}),
    'detect.cells': _stage('detect', '세포 · 핵 (세포질 ROI)', '세포질 ROI 탭의 검출 설정으로 세포와 핵을 찾습니다. '
                           '세포질 = 세포 − 핵.', {'panel': None, 'redo': True}, ('세포', '핵', '세포질'),
                           panel='roi', batch='cells'),
    'detect.particles': _stage('detect', '입자 (입자 ROI)', '입자 ROI 탭의 설정으로 입자를 찾습니다.',
                               {'panel': None, 'redo': True}, ('입자',), panel='particle', batch='particles'),
    'detect.mito': _stage('detect', '미토 ROI (mitoROI)', 'mitoROI 탭의 미토 분할로 미토콘드리아를 찾습니다 (검출만).',
                          {'panel': None, 'redo': True}, ('미토 조각',), ('세포',), panel='mito', batch='mito'),
    'track.particles': _stage('track', '입자 추적', '입자 추적 탭의 설정으로 프레임마다 입자를 찾고 잇습니다.',
                              {'panel': None, 'redo': True}, ('입자 트랙',), panel='track', batch='track'),
    'track.cytosol': _stage('track', '세포질 강도 추적', '세포를 프레임마다 찾고 이어 시점별 세기를 잽니다.',
                            {'cell_track': None, 'redo': True}, ('세포 트랙',), panel='cyto_track',
                            batch='cyto_track'),
    'op': _stage('op', '연산', '입력 object · 기준 · 동작 · 결과 이름.', {
        'input': '세포', 'where': {'mode': 'all', 'conds': []},
        'action': {'do': 'keep', 'with': '', 'pair': 'cell', 'um': 1.0, 'inner': 2.0, 'outer': 6.0, 'n': 4},
        'out': '새 object', 'rest': ''}),
    'measure.intensity': _stage('measure', '세기 (ImageJ Measure)', 'object × 채널: Area, Mean, IntDen …',
                                {'targets': [{'object': '세포질', 'channels': []}],
                                 'stats': ['Area', 'Mean', 'IntDen'], 'bg': 'none', 'name': ''}),
    'measure.count': _stage('measure', '개수 · 밀도', '부모(세포)마다 object 개수와 면적당 개수.',
                            {'object': '입자', 'parent': '세포', 'name': ''}),
    'measure.bands': _stage('measure', '등거리 띠', '등거리 띠 탭의 설정으로 띠마다 잽니다.', {'panel': None},
                            needs=('세포',), panel='bands', batch='bands'),
    'measure.coloc': _stage('measure', 'Coloc 2', 'Coloc 2 탭의 두 채널로 세포마다 계산합니다.', {'panel': None},
                            needs=('세포',), panel='coloc', batch='coloc'),
    'measure.frap': _stage('measure', 'FRAP 회복', 'FRAP 측정 탭의 설정으로 회복 곡선을 맞춥니다.', {'panel': None},
                           panel='frap', batch='frap'),
    'measure.mina': _stage('measure', '미토 형태 (MiNA)', '미토 조각의 골격 길이 · 가지 · 분기점 (Mito Analyzer).',
                           {}, needs=('미토 조각',)),
    'human.review': _stage('human', '검토 (사용자 첨삭)', '멈추고 고른 이미지의 ROI를 고친 뒤 이어 갑니다.', {
        'images': [], 'chips': {'count': True, 'touching': True, 'nuc_shape': True, 'failed': True,
                                'no_nucleus': False, 'edge': False},
        'cells': [3, 40], 'nuc_shape': 'normal'}),
    'end.graph': _stage('end', '그래프', '열 이름으로 저장한 그래프를 새 데이터에 다시 그립니다.',
                        {'graphs': [], 'formats': ['png'], 'csv': True}),
    'end.export': _stage('end', '저장 · 내보내기', '결과 폴더 (데이터 폴더의 상위 › Processed/) 에 씁니다.',
                         {'dest': 'processed', 'name': '<데이터 폴더>_<파이프라인>_<날짜>_<시각>', 'opts': {},
                          'integrated': True, 'project': True}),
}

ACTIONS = (('keep', '맞는 것만 남기기'), ('drop', '맞는 것 버리기'), ('subtract', '빼기 (무엇을)'),
           ('add', '더하기 (무엇과)'), ('intersect', '겹친 부분만 (무엇과)'), ('merge', '합치기 (부모마다 하나)'),
           ('dilate', '넓히기 (µm)'), ('erode', '줄이기 (µm)'), ('ring', '고리 (안 – 밖 µm)'),
           ('bands', '등거리 띠 (n개)'))
PAIRS = (('cell', '같은 세포 번호끼리'), ('overlap', '겹치는 것끼리'), ('image', '이미지 전체'))
OPS = ('>=', '<=', '>', '<', '=', 'between', 'yes', 'no')
FIELDS = ('Area', 'Perimeter', 'Circularity', 'Solidity', 'Feret', 'AR', 'Mean:<채널>', 'IntDen:<채널>',
          'overlap:<object>', 'inside:<object>', 'edge', 'frames', 'divided', 'change:<값>', 'class')
STATS = ('Area', 'Mean', 'StdDev', 'Min', 'Max', 'Median', 'IntDen', 'RawIntDen', 'Perimeter', 'Circularity')


def default_stage(kind) -> dict:
    s = STAGES[kind]
    return {'kind': kind, 'enabled': True, 'name': '', 'settings': copy.deepcopy(s['settings']),
            'out': list(s['out']), 'review': False}


def stage_title(st) -> str:
    return st.get('name') or STAGES.get(st['kind'], {}).get('title', st['kind'])


def stage_summary(st) -> str:
    k, s = st['kind'], st.get('settings', {})
    if k == 'op':
        a = s.get('action', {})
        do = dict(ACTIONS).get(a.get('do'), a.get('do'))
        conds = (s.get('where') or {}).get('conds') or []
        w = f' · 조건 {len(conds)}' if conds else ''
        return f'{s.get("input")} → {do.split(" ")[0]}{(" " + a["with"]) if a.get("with") else ""}{w} → {s.get("out")}'
    if k == 'measure.intensity':
        return ', '.join(f'{t["object"]} × {"+".join(t.get("channels") or ["모든 채널"])}'
                         for t in s.get('targets', []))
    if k == 'human.review':
        im = s.get('images') or []
        return '모든 이미지' if im == ['*'] else '검토 칩이 붙은 이미지' if im == ['chips'] else \
            f'이미지 {len(im)}개 고름' if im else '멈추지 않음 (칩만 표시)'
    if k == 'measure.count':
        return f'{s.get("object")} / {s.get("parent")}'
    if k == 'start.auto_group':
        return '이름 끝 번호'
    if k == 'start.load':
        return f'{s.get("folder") or "데이터 폴더"} · {s.get("glob", "*")}'
    if k == 'end.graph':
        return f'그래프 {len(s.get("graphs") or [])}개 · {", ".join(s.get("formats") or ["png"]).upper()}'
    if k == 'measure.mina':
        return '미토 조각 골격 · 가지 · 분기점'
    if k in ('measure.bands', 'measure.coloc', 'measure.frap'):
        return '탭의 지금 설정' if not s.get('panel') else '저장된 설정'
    if k == 'end.export':
        return 'Processed/' if s.get('dest') == 'processed' else str(s.get('dest'))
    if st.get('out'):
        return ' · '.join(st['out'])
    return STAGES.get(k, {}).get('desc', '')


@dataclass
class PipelineSpec:
    name: str = '새 파이프라인'
    stages: list = field(default_factory=list)
    input: dict = field(default_factory=dict)
    note: str = ''

    def to_dict(self) -> dict:
        from .version import __version__
        return {'format': FORMAT, 'version': VERSION, 'name': self.name, 'app_version': __version__,
                'input': self.input, 'note': self.note, 'stages': self.stages}

    @classmethod
    def from_dict(cls, d) -> 'PipelineSpec':
        if d.get('format') == 'cytosol-viewer-batch':   # 일괄 분석 settings → a pipeline without review
            return from_batch(d)
        if d.get('format') not in (FORMAT, None):
            raise ValueError(f'파이프라인 파일이 아닙니다 ({d.get("format")}).')
        stages = []
        for st in d.get('stages') or []:
            st = upgrade_stage(st)
            if st is None:
                continue
            base = default_stage(st['kind'])
            base.update({k: v for k, v in st.items() if k != 'settings'})
            base['settings'].update(st.get('settings') or {})
            stages.append(base)
        return cls(d.get('name') or '파이프라인', stages, d.get('input') or {}, d.get('note') or '')

    def save(self, path) -> Path:
        p = Path(path)
        if p.suffix != EXT:
            p = p.with_suffix(EXT)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1, default=_json_default),
                     encoding='utf-8')
        return p

    @classmethod
    def load(cls, path) -> 'PipelineSpec':
        return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))

    def copy(self) -> 'PipelineSpec':
        return PipelineSpec.from_dict(json.loads(json.dumps(self.to_dict(), default=_json_default)))

    def objects_before(self, index) -> list:
        """Object names made by the enabled stages before stage ``index``."""
        names = []
        for st in self.stages[:index]:
            if not st.get('enabled', True):
                continue
            for n in produced(st):
                if n and n not in names:
                    names.append(n)
        return names


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


V1_KINDS = {'load': 'start.load', 'auto_group': 'start.auto_group', 'cells': 'detect.cells', 'roi': 'detect.cells',
            'particles': 'detect.particles', 'particle': 'detect.particles', 'mito': 'detect.mito',
            'track': 'track.particles', 'cyto_track': 'track.cytosol', 'bands': 'measure.bands',
            'coloc': 'measure.coloc', 'frap': 'measure.frap', 'review': 'human.review', 'graph': 'end.graph',
            'export': 'end.export'}


def upgrade_stage(st) -> dict | None:
    """v1 stage kinds (roi / particle / …) → v2 kinds."""
    k = st.get('kind', '')
    if k in STAGES:
        return st
    if k in V1_KINDS:
        st = dict(st, kind=V1_KINDS[k])
        return st
    if k == 'measure':
        return dict(st, kind='measure.intensity', settings={'targets': [{'object': '세포질', 'channels': []}]})
    return None


def from_batch(d) -> PipelineSpec:
    """An old 일괄 분석 settings file: the checked steps, no review."""
    stages = []
    for step in d.get('steps') or []:
        k = V1_KINDS.get(step) or {'roi_measure': 'measure.intensity', 'particle_measure': 'measure.intensity'}.get(step)
        if k and k in STAGES and not any(s['kind'] == k for s in stages):
            st = default_stage(k)
            panel = STAGES[k]['panel']
            if panel and (d.get('panels') or {}).get(panel):
                st['settings']['panel'] = d['panels'][panel]
            stages.append(st)
    stages.sort(key=lambda s: GROUP_ORDER[STAGES[s['kind']]['group']])
    return PipelineSpec(d.get('name') or '일괄 분석', stages)


def stage_rank(stages, i) -> int:
    """Group order of stage i; a 검토 stage stays after the stage before it."""
    while i >= 0:
        g = STAGES[stages[i]['kind']]['group']
        if g != 'human':
            return GROUP_ORDER[g]
        i -= 1
    return 0


def produced(st) -> list:
    k = st['kind']
    if k == 'op':
        s = st['settings']
        return [x for x in (s.get('out'), s.get('rest')) if x]
    return list(st.get('out') or STAGES.get(k, {}).get('out', ()))


def validate(spec: PipelineSpec, channels=None) -> list[str]:
    """Problems before running: unknown kinds, objects used before they are
    made, stages out of group order, channel names the images don't have."""
    errs = []
    last = -1
    for i, st in enumerate(spec.stages, start=1):
        k = st.get('kind')
        if k not in STAGES:
            errs.append(f'{i}단계: 모르는 단계 종류 {k}')
            continue
        if not st.get('enabled', True):
            continue
        g = GROUP_ORDER[STAGES[k]['group']]
        if g < last and STAGES[k]['group'] not in ('human',):
            errs.append(f'{i}단계 {stage_title(st)}: 순서가 {GROUPS[g][1]} 묶음 앞 단계보다 뒤에 있습니다.')
        if STAGES[k]['group'] != 'human':
            last = max(last, g)
        have = spec.objects_before(i - 1)
        need = list(STAGES[k]['needs'])
        s = st.get('settings', {})
        if k == 'op':
            need.append(s.get('input'))
            a = s.get('action', {})
            if a.get('do') in ('subtract', 'add', 'intersect') and a.get('with'):
                need.append(a['with'])
            for c in (s.get('where') or {}).get('conds') or []:
                f = str(c[0]) if c else ''
                if f.startswith(('overlap:', 'inside:')):
                    need.append(f.split(':', 1)[1])
            if not s.get('out'):
                errs.append(f'{i}단계 연산: 결과 이름이 없습니다.')
        if k == 'measure.intensity':
            need += [t.get('object') for t in s.get('targets', [])]
            bg = s.get('bg', 'none')
            if bg.startswith('ring:'):
                need.append(bg.split(':', 1)[1])
            if channels:
                for t in s.get('targets', []):
                    for ch in t.get('channels') or []:
                        if ch not in channels:
                            errs.append(f'{i}단계 측정: 채널 {ch}이(가) 이미지에 없습니다 ({", ".join(channels)}).')
        if k == 'measure.count':
            need += [s.get('object'), s.get('parent')]
        for n in need:
            if n and n not in have:
                errs.append(f'{i}단계 {stage_title(st)}: object "{n}"이(가) 앞 단계에 없습니다.')
    return errs


# ---------------------------------------------------------------------------
# objects
# ---------------------------------------------------------------------------

@dataclass
class PipeObject:
    """A named set of regions of one image: labels (H, W) int32, each label's
    parent (cell number), or a set of tracks (cell / particle IDs)."""
    name: str
    kind: str = 'region'            # region / track
    labels: np.ndarray | None = None
    parent: dict = field(default_factory=dict)
    source: str = ''
    tracks: list | None = None      # track kind: IDs
    track_of: str = ''              # 'cell' (세포질 강도 추적) / 'particle' (입자 추적)

    def ids(self) -> list:
        if self.kind == 'track':
            return list(self.tracks or [])
        return [int(i) for i in np.unique(self.labels) if i > 0] if self.labels is not None else []


def _parents(lab, cells) -> dict:
    if cells is None:
        return {}
    out = {}
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        if sl is None:
            continue
        v = cells[sl][lab[sl] == i]
        v = v[v > 0]
        out[i] = int(np.bincount(v).argmax()) if v.size else 0
    return out


def base_objects(it) -> dict:
    """Objects made by the detection / tracking results the image has."""
    out = {}
    c = it.cells
    if c is not None and len(c):
        lab = np.asarray(c.labels, np.int32)
        out['세포'] = PipeObject('세포', labels=lab, parent={i: i for i in c.ids()}, source='detect.cells')
        if c.nuclei is not None:
            nuc = np.where(np.asarray(c.nuclei) > 0, lab, 0).astype(np.int32)
            out['핵'] = PipeObject('핵', labels=nuc, parent={i: i for i in np.unique(nuc) if i > 0},
                                   source='detect.cells')
            cyto = np.where(np.asarray(c.nuclei) > 0, 0, lab).astype(np.int32)
        else:
            cyto = lab.copy()
        out['세포질'] = PipeObject('세포질', labels=cyto, parent={i: i for i in np.unique(cyto) if i > 0},
                                  source='detect.cells')
    if getattr(it, 'particles', None) is not None or getattr(it, 'particle_settings', None) is not None:
        try:
            win_cells = c
            if win_cells is None or not len(win_cells):
                from .intensity import whole_image_cells
                win_cells = whole_image_cells(it.image.shape[-2:], it.pixel_um)
            p = it.particles
            if p is not None:
                comp = p.components(win_cells).astype(np.int32)
                out['입자'] = PipeObject('입자', labels=comp, parent=_parents(comp, win_cells.labels),
                                        source='detect.particles')
        except Exception:  # noqa: BLE001
            traceback.print_exc()
    m = getattr(it, 'mito', None)
    if m is not None and m.mlab is not None:
        ml = np.asarray(m.mlab, np.int32)
        out['미토 조각'] = PipeObject('미토 조각', labels=ml,
                                     parent=_parents(ml, c.labels if c is not None else None), source='detect.mito')
    ct = getattr(it, 'cell_tracks', None)
    if ct is not None:
        out['세포 트랙'] = PipeObject('세포 트랙', 'track', tracks=sorted(ct.cells()), track_of='cell',
                                    source='track.cytosol')
    tr = getattr(it, 'tracks', None)
    if tr is not None and tr.points:
        out['입자 트랙'] = PipeObject('입자 트랙', 'track', tracks=sorted(tr.tracks()), track_of='particle',
                                    source='track.particles')
    return out


def objects_of(it) -> dict:
    o = base_objects(it)
    o.update(getattr(it, 'pipe_objects', None) or {})
    return o


# ---------------------------------------------------------------------------
# values used by conditions and measurement
# ---------------------------------------------------------------------------

def _plane(it, ch):
    planes = it.planes()
    chs = list(it.channels)
    if ch in chs:
        return np.asarray(planes[chs.index(ch)], float)
    try:
        return np.asarray(planes[int(ch)], float)
    except (ValueError, IndexError):
        raise ValueError(f'채널 {ch}이(가) {it.label}에 없습니다.') from None


def region_values(it, obj: PipeObject, fields, objs) -> dict:
    """label -> {field: value} for the fields named (see FIELDS)."""
    from skimage import measure
    px = float(it.pixel_um or 1.0)
    lab = obj.labels
    H, W = lab.shape
    out = {i: {} for i in obj.ids()}
    props = {r.label: r for r in measure.regionprops(lab)}
    for f in fields:
        head, _, arg = f.partition(':')
        if head in ('Area', 'Perimeter', 'Circularity', 'Solidity', 'Feret', 'AR'):
            for i, r in props.items():
                a = r.area * px * px
                per = r.perimeter * px
                v = {'Area': a, 'Perimeter': per,
                     'Circularity': min(1.0, 4 * math.pi * a / per ** 2) if per > 0 else 0.0,
                     'Solidity': r.solidity, 'Feret': r.feret_diameter_max * px,
                     'AR': r.axis_major_length / max(r.axis_minor_length, 1e-9)}[head]
                out[i][f] = float(v)
        elif head in ('Mean', 'IntDen', 'Max', 'Min', 'Median'):
            img = _plane(it, arg)
            ids = list(props)
            if head == 'Mean':
                vals = ndi.mean(img, lab, ids)
            elif head == 'Max':
                vals = ndi.maximum(img, lab, ids)
            elif head == 'Min':
                vals = ndi.minimum(img, lab, ids)
            elif head == 'Median':
                vals = ndi.median(img, lab, ids)
            else:
                vals = np.asarray(ndi.sum(img, lab, ids)) * px * px
            for i, v in zip(ids, np.atleast_1d(vals)):
                out[i][f] = float(v)
        elif head in ('overlap', 'inside'):
            other = objs.get(arg)
            if other is None or other.labels is None:
                raise ValueError(f'object "{arg}"이(가) 없습니다.')
            om = other.labels > 0
            for i, r in props.items():
                sl = r.slice
                m = lab[sl] == i
                if head == 'overlap':
                    out[i][f] = float(om[sl][m].mean() * 100)
                else:
                    cy, cx = (int(round(x)) for x in r.centroid)
                    out[i][f] = bool(om[min(cy, H - 1), min(cx, W - 1)])
        elif head == 'edge':
            for i, r in props.items():
                y0, x0, y1, x1 = r.bbox
                out[i][f] = bool(y0 == 0 or x0 == 0 or y1 >= H or x1 >= W)
        elif head == 'cell':
            for i in props:
                out[i][f] = obj.parent.get(i, 0)
    return out


def track_values(it, obj: PipeObject, fields) -> dict:
    """track id -> {field: value} (frames, divided, edge, change:<값>, class)."""
    out = {i: {} for i in obj.ids()}
    if obj.track_of == 'cell':
        st = it.cell_tracks
        cells = st.cells()
        div = set(st.divided)
        from . import cell_track as CT
        for i in out:
            rs = sorted(cells.get(i, []), key=lambda r: r['frame'])
            for f in fields:
                head, _, arg = f.partition(':')
                if head == 'frames':
                    out[i][f] = len(rs)
                elif head == 'divided':
                    out[i][f] = i in div
                elif head == 'edge':
                    out[i][f] = any(r['edge'] for r in rs)
                elif head == 'change':
                    col = CT.VALUE_COL.get(arg or 'thr', arg or 'I_thr')
                    v = [r.get(col, np.nan) for r in rs]
                    v = [x for x in v if x is not None and np.isfinite(x)]
                    out[i][f] = (np.mean(v[-3:]) / np.mean(v[:3])) if len(v) >= 2 and np.mean(v[:3]) else np.nan
        if any(f == 'class' for f in fields):
            win = getattr(it, '_pipe_win', None)
            if win is not None:
                cls = {k[1]: v for k, v in win.cell_track_panel.classes().items() if k[0] == it.image_id}
                for i in out:
                    out[i]['class'] = CT.class_text(cls.get(i, 'short'))
    else:
        tracks = it.tracks.tracks()
        cls = {}
        win = getattr(it, '_pipe_win', None)
        if 'class' in fields and win is not None:
            cls = {r['track_id']: r['class'] for r in win.track_panel.summary_of(it)}
        for i in out:
            pts = tracks.get(i, [])
            for f in fields:
                if f == 'frames':
                    out[i][f] = len(pts)
                elif f == 'class':
                    out[i][f] = cls.get(i, pts[0].get('class', '') if pts else '')
    return out


def _cmp(v, op, val) -> bool:
    if op == 'yes':
        return bool(v)
    if op == 'no':
        return not bool(v)
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return False
    if op == 'between':
        lo, hi = val
        return float(lo) <= float(v) <= float(hi)
    if op == '=':
        return str(v) == str(val) if isinstance(v, str) else float(v) == float(val)
    v, val = float(v), float(val)
    return {'>=': v >= val, '<=': v <= val, '>': v > val, '<': v < val}[op]


def _bg_value(it, ch):
    """Median of the image outside every cell (배경)."""
    img = _plane(it, ch)
    if it.cells is not None and len(it.cells):
        m = np.asarray(it.cells.labels) == 0
        return float(np.median(img[m])) if m.any() else 0.0
    return float(np.median(img))


def matching(it, obj, where, objs) -> set:
    conds = (where or {}).get('conds') or []
    if not conds:
        return set(obj.ids())
    fields = [str(c[0]) for c in conds]
    vals = track_values(it, obj, fields) if obj.kind == 'track' else region_values(it, obj, fields, objs)
    mode = (where or {}).get('mode', 'all')
    keep = set()
    for i, v in vals.items():
        res = []
        for c in conds:
            f, op = str(c[0]), c[1]
            val = c[2] if len(c) > 2 else None
            if isinstance(val, str) and val.startswith('bg*') and f.startswith('Mean:'):
                val = _bg_value(it, f.split(':', 1)[1]) * float(val[3:])
            res.append(_cmp(v.get(f), op, val))
        if (all(res) if mode == 'all' else any(res)):
            keep.add(i)
    return keep


# ---------------------------------------------------------------------------
# 연산
# ---------------------------------------------------------------------------

def _subset(obj, ids, name) -> PipeObject:
    if obj.kind == 'track':
        return PipeObject(name, 'track', tracks=sorted(ids), track_of=obj.track_of, source='op')
    keep = np.zeros(int(obj.labels.max()) + 1, bool)
    keep[[i for i in ids if i < len(keep)]] = True
    lab = np.where(keep[obj.labels], obj.labels, 0).astype(np.int32)
    return PipeObject(name, labels=lab, parent={i: p for i, p in obj.parent.items() if i in ids}, source='op')


def _pair_mask(a: PipeObject, b: PipeObject, pair):
    """For each label of a, the mask of b it is combined with."""
    if pair == 'image':
        bm = b.labels > 0
        return lambda i: bm
    if pair == 'overlap':
        def f(i):
            m = a.labels == i
            ids = np.unique(b.labels[m])
            ids = ids[ids > 0]
            return np.isin(b.labels, ids)
        return f
    bpar = np.zeros(int(b.labels.max()) + 1, np.int64)
    for j, p in b.parent.items():
        if j < len(bpar):
            bpar[j] = p
    bp = bpar[b.labels]

    def g(i):
        return (bp == a.parent.get(i, -1)) & (b.labels > 0)
    return g


def apply_op(it, settings, objs) -> dict:
    """One 연산 stage on one image → {name: PipeObject}."""
    s = settings
    src = objs.get(s.get('input'))
    if src is None:
        raise ValueError(f'object "{s.get("input")}"이(가) 없습니다.')
    a = s.get('action') or {}
    do = a.get('do', 'keep')
    name = s.get('out') or f'{src.name} 연산'
    hit = matching(it, src, s.get('where'), objs)
    out = {}
    rest_ids = set(src.ids()) - hit
    if do in ('keep', 'drop'):
        ids = hit if do == 'keep' else rest_ids
        out[name] = _subset(src, ids, name)
        if s.get('rest'):
            out[s['rest']] = _subset(src, rest_ids if do == 'keep' else hit, s['rest'])
        return out
    if src.kind == 'track':
        raise ValueError('트랙 object에는 거르기(남기기 · 버리기)만 됩니다.')
    base = _subset(src, hit, name)
    lab = base.labels
    px = float(it.pixel_um or 1.0)
    if do in ('subtract', 'add', 'intersect'):
        other = objs.get(a.get('with'))
        if other is None or other.labels is None:
            raise ValueError(f'object "{a.get("with")}"이(가) 없습니다.')
        pm = _pair_mask(base, other, a.get('pair', 'cell'))
        res = np.zeros_like(lab)
        for i in base.ids():
            m = lab == i
            o = pm(i)
            if do == 'subtract':
                r = m & ~o
            elif do == 'intersect':
                r = m & o
            else:
                r = m | (o & (res == 0) & (lab == 0))
            res[r] = i
        out[name] = PipeObject(name, labels=res.astype(np.int32), parent=dict(base.parent), source='op')
    elif do == 'merge':
        par = np.zeros(int(lab.max()) + 1, np.int64)
        for i, p in base.parent.items():
            par[i] = p
        res = np.where(lab > 0, par[lab], 0).astype(np.int32)
        out[name] = PipeObject(name, labels=res, parent={i: i for i in np.unique(res) if i > 0}, source='op')
    elif do in ('dilate', 'erode', 'ring'):
        res = np.zeros_like(lab)
        d_out, inds = ndi.distance_transform_edt(lab == 0, return_indices=True)
        near = lab[inds[0], inds[1]]
        if do == 'dilate':
            r = float(a.get('um', 1.0)) / px
            res = np.where((lab > 0) | (d_out <= r), np.where(lab > 0, lab, near), 0)
        elif do == 'erode':
            r = float(a.get('um', 1.0)) / px
            d_in = ndi.distance_transform_edt(lab > 0)
            # erode each label separately: distance to the label's own edge
            res = lab.copy()
            for i, sl in enumerate(ndi.find_objects(lab), start=1):
                if sl is None:
                    continue
                m = np.pad(lab[sl] == i, 1)
                d = ndi.distance_transform_edt(m)[1:-1, 1:-1]
                res[sl][(lab[sl] == i) & (d <= r)] = 0
            del d_in
        else:
            rin, rout = float(a.get('inner', 2.0)) / px, float(a.get('outer', 6.0)) / px
            # a ring around cells stays outside every cell (배경 고리); a ring
            # around a nucleus / particle may lie inside its cell
            block = np.zeros(lab.shape, bool)
            cells = objs.get('세포')
            if a.get('outside_cells', s.get('input') == '세포') and cells is not None and cells.labels is not None:
                block = cells.labels > 0
            res = np.where((d_out > rin) & (d_out <= rout) & ~block & (src.labels == 0), near, 0)
        res = res.astype(np.int32)
        out[name] = PipeObject(name, labels=res, parent={i: base.parent.get(i, i) for i in np.unique(res) if i > 0},
                               source='op')
    elif do == 'bands':
        n = max(1, int(a.get('n', 4)))
        nuc = objs.get('핵')
        res = np.zeros_like(lab)
        par = {}
        for i, sl in enumerate(ndi.find_objects(lab), start=1):
            if sl is None:
                continue
            m = lab[sl] == i
            d_mem = ndi.distance_transform_edt(np.pad(m, 1))[1:-1, 1:-1]
            if nuc is not None and nuc.labels is not None and (nuc.labels[sl][m] > 0).any():
                nm = (nuc.labels[sl] > 0) & m
                d_nuc = ndi.distance_transform_edt(~nm)
                rel = d_nuc / np.maximum(d_nuc + d_mem, 1e-9)
                inside = m & ~nm
            else:
                rel = 1 - d_mem / max(d_mem.max(), 1e-9)
                inside = m
            k = np.clip((rel * n).astype(int), 0, n - 1)
            for b in range(n):
                lid = (i - 1) * n + b + 1
                res[sl][inside & (k == b)] = lid
                par[lid] = base.parent.get(i, i)
        out[name] = PipeObject(name, labels=res.astype(np.int32), parent=par, source='op')
    if s.get('rest'):
        out[s['rest']] = _subset(src, rest_ids, s['rest'])
    return out


# ---------------------------------------------------------------------------
# 측정
# ---------------------------------------------------------------------------

def measure_intensity(it, settings, objs) -> list:
    """Rows of object × channel: ImageJ Measure values per region (or per
    time point for track objects)."""
    rows = []
    stats = settings.get('stats') or ['Area', 'Mean', 'IntDen']
    bg = settings.get('bg', 'none')
    px = float(it.pixel_um or 1.0)
    head = {'image': it.label, 'image_id': it.image_id, 'group': it.group or ''}
    missing = []
    for t in settings.get('targets') or []:
        obj = objs.get(t.get('object'))
        if obj is None:
            missing.append(t.get('object'))
            continue
        chans = t.get('channels') or list(it.channels)
        if obj.kind == 'track':
            if obj.track_of == 'cell':
                keep = set(obj.ids())
                for r in it.cell_tracks.rows:
                    if r['cell_id'] in keep:
                        rows.append({**head, 'object': obj.name, 'label': r['cell_id'], **r})
            else:
                keep = set(obj.ids())
                for p in it.tracks.points:
                    if p['track_id'] in keep:
                        rows.append({**head, 'object': obj.name, 'label': p['track_id'],
                                     **{k: v for k, v in p.items() if not k.startswith('_')}})
            continue
        lab = obj.labels
        ids = obj.ids()
        if not ids:
            continue
        shape = region_values(it, obj, ['Area', 'Perimeter', 'Circularity'], objs) \
            if any(x in stats for x in ('Area', 'Perimeter', 'Circularity')) else {}
        per_ch = {}
        for ch in chans:
            img = _plane(it, ch)
            b = 0.0
            ring_lab = None
            if bg == 'outside':
                b = _bg_value(it, ch)
            elif bg.startswith('ring:'):
                ring = objs.get(bg.split(':', 1)[1])
                ring_lab = ring
            d = {}
            for st in stats:
                if st == 'Mean':
                    d[st] = ndi.mean(img, lab, ids)
                elif st == 'StdDev':
                    d[st] = ndi.standard_deviation(img, lab, ids)
                elif st == 'Min':
                    d[st] = ndi.minimum(img, lab, ids)
                elif st == 'Max':
                    d[st] = ndi.maximum(img, lab, ids)
                elif st == 'Median':
                    d[st] = ndi.median(img, lab, ids)
                elif st == 'RawIntDen':
                    d[st] = ndi.sum(img, lab, ids)
                elif st == 'IntDen':
                    d[st] = np.asarray(ndi.sum(img, lab, ids)) * px * px
            bvals = {}
            if ring_lab is not None and ring_lab.labels is not None:
                rp = np.zeros(int(ring_lab.labels.max()) + 1, np.int64)
                for j, p in ring_lab.parent.items():
                    rp[j] = p
                rpar = np.where(ring_lab.labels > 0, rp[ring_lab.labels], 0)
                for i in ids:
                    m = rpar == obj.parent.get(i, -1)
                    bvals[i] = float(np.median(img[m])) if m.any() else np.nan
            per_ch[ch] = (d, b, bvals)
        counts = np.bincount(lab.ravel(), minlength=int(lab.max()) + 1)
        for k, i in enumerate(ids):
            r = {**head, 'object': obj.name, 'label': int(i), 'cell': int(obj.parent.get(i, 0))}
            for st in ('Area', 'Perimeter', 'Circularity'):
                if st in stats:
                    r[st] = shape.get(i, {}).get(st, np.nan)
            for ch, (d, b, bvals) in per_ch.items():
                bb = bvals.get(i, b) if bvals else b
                for st, arr in d.items():
                    v = float(np.atleast_1d(arr)[k])
                    if st in ('Mean', 'Median', 'Min', 'Max') and bg != 'none':
                        v -= bb
                    elif st in ('IntDen', 'RawIntDen') and bg != 'none':
                        v -= bb * counts[i] * (px * px if st == 'IntDen' else 1)
                    r[f'{st} ({ch})'] = v
                if bg != 'none':
                    r[f'bg ({ch})'] = bb
            rows.append(r)
    if missing:
        raise PartialResult(rows, f'object {", ".join(map(str, missing))}이(가) 이 이미지에 없어 건너뜀')
    return rows


class PartialResult(Exception):
    def __init__(self, rows, msg):
        super().__init__(msg)
        self.rows = rows


def measure_count(it, settings, objs) -> list:
    obj, par = objs.get(settings.get('object')), objs.get(settings.get('parent'))
    if obj is None or par is None:
        raise ValueError('개수: object 또는 부모가 없습니다.')
    px = float(it.pixel_um or 1.0)
    rows = []
    counts = {}
    for i in obj.ids():
        p = obj.parent.get(i, 0)
        counts[p] = counts.get(p, 0) + 1
    areas = np.bincount(par.labels.ravel()) * px * px
    for p in par.ids():
        n = counts.get(p, 0)
        a = float(areas[p]) if p < len(areas) else np.nan
        rows.append({'image': it.label, 'image_id': it.image_id, 'group': it.group or '', 'object': obj.name,
                     'parent': par.name, 'cell': p, 'count': n, 'parent_area_um2': a,
                     'density_per_um2': n / a if a else np.nan})
    return rows


def mina_rows(it) -> list:
    from .mina_panel import measure
    r = measure(it)
    it.mina = r
    return [{'image': it.label, 'image_id': it.image_id, 'group': it.group or '', **x} for x in r.cells]


# ---------------------------------------------------------------------------
# 검토 칩
# ---------------------------------------------------------------------------

NUC_SHAPE = {'strict': 0.90, 'normal': 0.85, 'loose': 0.80}
CHIP_TEXT = {'count': '세포 수 범위 밖', 'touching': '핵 붙은 세포', 'nuc_shape': '핵 모양 이상', 'failed': '검출 실패',
             'no_nucleus': '핵 없는 세포', 'edge': '가장자리 세포'}
CHIP_KIND = {'count': 'warning', 'touching': 'warning', 'nuc_shape': 'warning', 'failed': 'error',
             'no_nucleus': 'warning', 'edge': 'neutral'}


def nucleus_odd(mask, solidity_min=0.85) -> bool:
    """A hole (filled − area > 2 %), a notch deeper than 15 % of the nucleus
    diameter from its convex hull, or solidity below the limit."""
    from skimage import measure, morphology
    m = np.asarray(mask, bool)
    a = m.sum()
    if a < 9:
        return False
    filled = ndi.binary_fill_holes(m)
    if filled.sum() - a > 0.02 * a:
        return True
    hull = morphology.convex_hull_image(filled)
    if a / max(hull.sum(), 1) < solidity_min:
        return True
    dia = 2 * math.sqrt(filled.sum() / math.pi)
    notch = hull & ~filled
    if notch.any():
        d = ndi.distance_transform_edt(notch)
        if d.max() > 0.15 * dia:
            return True
    del measure
    return False


def review_chips(it, settings) -> dict:
    """chip key -> count for one image (only the keys switched on)."""
    on = settings.get('chips') or {}
    lo, hi = (settings.get('cells') or [3, 40])[:2]
    c = it.cells
    out = {}
    if c is None or not len(c):
        if on.get('failed', True):
            out['failed'] = 1
        return out
    n = len(c)
    if on.get('count') and not (lo <= n <= hi):
        out['count'] = n
    nuc = np.asarray(c.nuclei) if c.nuclei is not None else None
    sol = NUC_SHAPE.get(settings.get('nuc_shape', 'normal'), 0.85)
    t = odd = none = edge = 0
    for i in c.ids():
        if nuc is not None:
            m = (np.asarray(c.labels) == i) & (nuc > 0)
            k = ndi.label(m)[1]
            if k >= 2:
                t += 1
            if k == 0:
                none += 1
            elif on.get('nuc_shape') and nucleus_odd(m, sol):
                odd += 1
        if c.touches_frame(i):
            edge += 1
    for key, v in (('touching', t), ('nuc_shape', odd), ('no_nucleus', none), ('edge', edge)):
        if on.get(key) and v:
            out[key] = v
    return out


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

def _panel_obj(win, panel):
    return {'roi': win.roi_panel, 'particle': win.particle_panel, 'mito': win.mito_panel, 'track': win.track_panel,
            'bands': win.bands_panel, 'coloc': win.coloc_panel, 'frap': win.frap_panel}.get(panel)


class _Settings:
    """Apply a stage's panel settings for the run, put the tab's back after."""

    def __init__(self, win, stage):
        self.win, self.stage = win, stage
        self.saved = None
        self.obj = None

    def __enter__(self):
        from .project import restore_widgets, widget_state
        k = STAGES[self.stage['kind']]
        s = self.stage.get('settings') or {}
        if k['panel'] == 'cyto_track':
            if s.get('cell_track'):
                self.saved = self.win.cell_track_panel.settings().to_dict()
                self.win.cell_track_panel.set_settings(s['cell_track'])
            return self
        self.obj = _panel_obj(self.win, k['panel'])
        if self.obj is not None and s.get('panel'):
            self.saved = widget_state(self.obj)
            restore_widgets(self.obj, s['panel'])
        return self

    def __exit__(self, *a):
        from .project import restore_widgets
        if self.saved is None:
            return False
        if self.obj is None:
            self.win.cell_track_panel.set_settings(self.saved)
        else:
            restore_widgets(self.obj, self.saved)
        return False


def capture_settings(win, kind) -> dict | None:
    """The tab's current settings for a stage (탭 설정 가져오기)."""
    from .project import widget_state
    p = STAGES[kind]['panel']
    if p == 'cyto_track':
        return win.cell_track_panel.settings().to_dict()
    o = _panel_obj(win, p)
    return widget_state(o) if o is not None else None


def result_folder(spec: PipelineSpec, items, dest='processed', pattern=None, now=None) -> Path:
    """<데이터 폴더의 상위>/Processed/<데이터 폴더>_<파이프라인>_<날짜>_<시각> (numbered when taken)."""
    now = now or time.localtime()
    paths = [Path(it.path) for it in items if getattr(it, 'path', None)]
    data = paths[0].parent if paths else Path.home()
    base = data.parent / 'Processed' if dest in ('processed', '', None) else Path(dest).expanduser()
    pattern = pattern or '<데이터 폴더>_<파이프라인>_<날짜>_<시각>'
    name = (pattern.replace('<데이터 폴더>', data.name).replace('<파이프라인>', spec.name)
            .replace('<날짜>', time.strftime('%Y-%m-%d', now)).replace('<시각>', time.strftime('%H%M', now)))
    name = re.sub(r'[\\/:*?"<>|]+', '_', name).strip() or 'pipeline'
    out = base / name
    k = 2
    while out.exists():
        out = base / f'{name} ({k})'
        k += 1
    return out


@dataclass
class RunState:
    stage: int = 0                       # next stage to run
    done: list = field(default_factory=list)
    status: str = 'new'                  # new / running / review / done / failed
    review_stage: int = -1
    review_images: list = field(default_factory=list)
    confirmed: list = field(default_factory=list)
    chips: dict = field(default_factory=dict)       # image id -> {chip: n}
    excluded: list = field(default_factory=list)    # image ids left out of this run
    out: str = ''
    errors: list = field(default_factory=list)
    started: float = 0.0
    tables: dict = field(default_factory=dict)      # table name -> rows

    def to_dict(self):
        d = dict(self.__dict__)
        d['tables'] = {k: len(v) for k, v in self.tables.items()}
        return d


class Runner:
    """Runs a pipeline stage by stage over every image (a stage on all images
    before the next); stops at a 검토 stage with images picked when
    ``interactive``. Progress lines go to ``<out>/progress.jsonl``."""

    def __init__(self, win, spec: PipelineSpec, items=None, out=None, interactive=True, progress=None):
        self.win, self.spec = win, spec
        self.items = list(items if items is not None else win.items)
        self.state = RunState(out=str(out or ''))
        self.interactive = interactive
        self.progress = progress
        self.review_log = []

    # ---- logging ----
    def _log(self, **d):
        d['t'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        if self.progress:
            try:
                self.progress(d)
            except Exception:  # noqa: BLE001
                pass
        if self.state.out:
            p = Path(self.state.out)
            p.mkdir(parents=True, exist_ok=True)
            with open(p / 'progress.jsonl', 'a', encoding='utf-8') as f:
                f.write(json.dumps(d, ensure_ascii=False, default=_json_default) + '\n')

    def active_items(self):
        ex = set(self.state.excluded)
        return [it for it in self.items if it.image_id not in ex]

    # ---- run ----
    def run(self, only=None) -> str:
        """Run from the current stage; 'review' when it stopped, 'done' at the end."""
        st = self.state
        if not st.started:
            st.started = time.time()
        st.status = 'running'
        n = len(self.spec.stages)
        while st.stage < n:
            i = st.stage
            stage = self.spec.stages[i]
            if not stage.get('enabled', True) or (only is not None and i + 1 not in only):
                st.stage += 1
                continue
            self._log(event='stage', index=i + 1, kind=stage['kind'], title=stage_title(stage))
            try:
                stop = self.run_stage(i, stage)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                st.errors.append(f'{i + 1}단계 {stage_title(stage)}: {exc}')
                self._log(event='error', index=i + 1, message=str(exc))
                stop = False
            st.done.append(i)
            st.stage += 1
            if stop:
                st.status = 'review'
                st.review_stage = i
                self._log(event='review', index=i + 1, images=st.review_images)
                return 'review'
        st.status = 'done'
        self._log(event='done', errors=st.errors)
        if st.out and (Path(st.out) / 'summary.json').exists():
            try:  # the export stage wrote it while still 'running'
                self.write_meta()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        return 'done'

    def resume(self) -> str:
        """검토 끝내고 계속."""
        self._log(event='resume', confirmed=self.state.confirmed)
        self.state.review_images = []
        return self.run()

    def rerun_from(self, index) -> str:
        self.state.stage = index
        self.state.done = [d for d in self.state.done if d < index]
        return self.run()

    def run_stage(self, i, stage) -> bool:
        from . import batch
        k = stage['kind']
        s = stage.get('settings') or {}
        items = self.active_items()
        win = self.win
        for it in items:
            it._pipe_win = win
        if k == 'start.load':
            folder = s.get('folder') or self.spec.input.get('folder')
            if folder:
                files = find_images(folder, s.get('glob', '*'), s.get('recursive', True))
                if not files:
                    raise ValueError(f'{folder}에 이미지가 없습니다.')
                win.import_paths(files)
                self.items = list(win.items)
            return False
        if k == 'start.auto_group':
            from .groups import auto_groups
            g = auto_groups([it.label for it in items])
            for j, it in enumerate(items):
                if j in g:
                    it.group = g[j]
            win.file_list.rebuild(win.items)
            return False
        meta = STAGES[k]
        if meta['batch']:
            with _Settings(win, stage):
                state = batch.BatchState()
                state.steps = [meta['batch']]
                state.redo = bool(s.get('redo', True))
                errs = batch.run(win, state, items)
            for e in errs:
                self.state.errors.append(f'{i + 1}단계: {e}')
            if meta['group'] in ('detect', 'track'):
                for it in items:      # objects made from the old ROIs are gone
                    it.pipe_objects = {}
            if k == 'detect.cells':
                review = next((x for x in self.spec.stages[i + 1:] if x['kind'] == 'human.review'), None)
                rs = (review or {}).get('settings') or default_stage('human.review')['settings']
                for it in items:
                    self.state.chips[it.image_id] = review_chips(it, rs)
            self._log(event='stage_done', index=i + 1, images=len(items), errors=len(errs))
            return False
        if k == 'op':
            n = 0
            for it in items:
                objs = objects_of(it)
                try:
                    new = apply_op(it, s, objs)
                except Exception as exc:  # noqa: BLE001
                    self.state.errors.append(f'{it.label} {i + 1}단계 연산: {exc}')
                    continue
                if getattr(it, 'pipe_objects', None) is None:
                    it.pipe_objects = {}
                it.pipe_objects.update(new)
                n += sum(len(o.ids()) for o in new.values())
            self._log(event='stage_done', index=i + 1, objects=n)
            return False
        if k in ('measure.intensity', 'measure.count', 'measure.mina'):
            name = s.get('name') or {'measure.intensity': '측정 · ' + ' · '.join(t['object'] for t in
                                                                               s.get('targets') or []),
                                     'measure.count': f'개수 · {s.get("object")}',
                                     'measure.mina': '미토 형태 (MiNA)'}[k]
            rows = []
            for it in items:
                try:
                    objs = objects_of(it)
                    rows += (measure_intensity(it, s, objs) if k == 'measure.intensity' else
                             measure_count(it, s, objs) if k == 'measure.count' else mina_rows(it))
                except PartialResult as exc:
                    rows += exc.rows
                    self.state.errors.append(f'{it.label} {i + 1}단계 {stage_title(stage)}: {exc}')
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    self.state.errors.append(f'{it.label} {i + 1}단계 {stage_title(stage)}: {exc}')
            self.state.tables[name] = rows
            self._log(event='stage_done', index=i + 1, table=name, rows=len(rows))
            return False
        if k == 'human.review':
            ids = [x for x in (s.get('images') or []) if any(it.image_id == x for it in items)]
            if s.get('images') == ['*']:
                ids = [it.image_id for it in items]
            if s.get('images') == ['chips']:
                ids = [it.image_id for it in items if self.state.chips.get(it.image_id)]
            self.state.review_images = list(dict.fromkeys(ids))
            self.state.confirmed = []
            return bool(ids) and self.interactive
        if k == 'end.graph':
            self.write_graphs(s)
            return False
        if k == 'end.export':
            self.write_export(s)
            return False
        return False

    # ---- outputs ----
    def out_dir(self, s=None) -> Path:
        if not self.state.out:
            s = s or next((x['settings'] for x in self.spec.stages if x['kind'] == 'end.export'), {})
            self.state.out = str(result_folder(self.spec, self.items, s.get('dest', 'processed'), s.get('name')))
        p = Path(self.state.out)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def all_tables(self) -> dict:
        """Pipeline tables + the 통합 데이터 categories."""
        from . import graph as G
        out = {name: G.Table.from_dicts(name, rows) for name, rows in self.state.tables.items() if rows}
        try:
            from . import integrate
            for t in integrate.tables(self.win):
                out.setdefault(t.name, t)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        return out

    def write_graphs(self, s):
        from . import graph as G
        out = self.out_dir() / '2_그래프'
        out.mkdir(parents=True, exist_ok=True)
        tables = self.all_tables()
        for k, gd in enumerate(s.get('graphs') or [], start=1):
            try:
                spec = G.GraphSpec.from_dict(gd) if hasattr(G.GraphSpec, 'from_dict') else G.load_spec_dict(gd)
                name = re.sub(r'[\\/:*?"<>|]+', '_', gd.get('title') or spec.title or f'graph{k}') or f'graph{k}'
                need = {x.table for x in spec.series} | ({spec.mapping.table} if spec.mapping.on else set())
                missing = [t for t in need if t and t not in tables]
                if missing:
                    self.state.errors.append(f'그래프 {name}: 표 {", ".join(missing)}가 없어 건너뜀')
                    continue
                if spec.mapping.on:
                    G.build_series(spec, tables)
                for fmt in s.get('formats') or ['png']:
                    G.save_figure(out / f'{name}.{fmt}', spec, tables)
                if s.get('csv', True):
                    t = G.plotted_table(spec, tables)
                    _write_rows(out / f'{name}.csv', [dict(zip(t.columns, r)) for r in t.rows])
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self.state.errors.append(f'그래프 {k}: {exc}')
        self._log(event='graphs', count=len(s.get('graphs') or []))

    def write_export(self, s):
        from . import exporter
        out = self.out_dir(s)
        items = self.active_items()
        opts = dict(s.get('opts') or {})
        opts.setdefault('per_image', True)
        if opts:
            r = exporter.run(self.win, items, out / '3_이미지', opts)
            self.state.errors += r.errors
        if s.get('integrated', True):
            try:
                exporter.run(self.win, items, out / '1_통합데이터', {'integrated_csv': True, 'per_image': False})
            except Exception as exc:  # noqa: BLE001
                self.state.errors.append(f'통합 데이터: {exc}')
        tdir = out / '1_통합데이터'
        for name, rows in self.state.tables.items():
            _write_rows(tdir / f'{_safe(name)}.csv', rows)
        if s.get('project', True):
            try:
                self.win.write_project_to(out / 'project.cyproj')
            except Exception as exc:  # noqa: BLE001
                self.state.errors.append(f'프로젝트: {exc}')
        self.write_meta()

    def write_meta(self):
        out = self.out_dir()
        from .version import __version__
        (out / 'pipeline.json').write_text(json.dumps(self.spec.to_dict(), ensure_ascii=False, indent=1,
                                                      default=_json_default), encoding='utf-8')
        if self.review_log:
            _write_rows(out / 'review_log.csv', self.review_log)
        try:
            self.win.worklog.write_csv(out / 'work_log.csv')
        except Exception:  # noqa: BLE001
            pass
        lines = [f'Cytosol Viewer {__version__} · 파이프라인 {self.spec.name}',
                 f'이미지 {len(self.active_items())}개 · 걸린 시간 {time.time() - self.state.started:.0f}초', '']
        for i, st in enumerate(self.spec.stages, start=1):
            if st.get('enabled', True):
                lines.append(f'{i}. [{dict(GROUPS)[STAGES[st["kind"]]["group"]]}] {stage_title(st)}: {stage_summary(st)}')
        if self.state.errors:
            lines += ['', '경고:'] + self.state.errors
        try:
            readme = Path(__file__).resolve().parents[1] / 'README.md'
            m = re.search(r'Methods statement\**\s*\n+(.+?)\n\n', readme.read_text(encoding='utf-8'), re.S)
            if m:
                lines += ['', 'Methods:', m.group(1).strip()]
        except Exception:  # noqa: BLE001
            pass
        (out / 'README.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        summary = {'pipeline': self.spec.name, 'images': len(self.active_items()), 'status': self.state.status,
                   'stages': len(self.spec.stages), 'errors': self.state.errors,
                   'tables': {k: len(v) for k, v in self.state.tables.items()},
                   'objects': {it.label: {n: len(o.ids()) for n, o in objects_of(it).items()}
                               for it in self.active_items()},
                   'out': str(out), 'seconds': round(time.time() - self.state.started, 1)}
        (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=_json_default),
                                          encoding='utf-8')
        return summary

    def note_review(self, it, action, roi=''):
        self.review_log.append({'image': it.label, 'image_id': it.image_id,
                                'stage': self.state.review_stage + 1, 'action': action, 'roi': roi,
                                'time': time.strftime('%Y-%m-%d %H:%M:%S')})


def _safe(name):
    return re.sub(r'[\\/:*?"<>|]+', '_', name).strip() or 'table'


def _write_rows(path, rows):
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f'{v:.6g}' if isinstance(v, float) else v) for k, v in r.items()})


IMAGE_EXTS = ('.tcf', '.czi', '.oir', '.tif', '.tiff', '.nd2', '.lsm')


def find_images(folder, glob='*', recursive=True) -> list:
    folder = Path(folder).expanduser()
    it = folder.rglob(glob) if recursive else folder.glob(glob)
    out = []
    for f in sorted(it):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS and not f.name.startswith('._') \
                and 'Processed' not in f.relative_to(folder).parts:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# library (보관함) and presets
# ---------------------------------------------------------------------------

def library_dir() -> Path:
    d = Path.home() / '.cytosol' / 'pipelines'
    try:
        from . import view_settings
        v = view_settings.flag('pipeline_dir') if hasattr(view_settings, 'flag') else None
        if isinstance(v, str) and v:
            d = Path(v)
    except Exception:  # noqa: BLE001
        pass
    return d


def library() -> list[tuple[str, Path | None, PipelineSpec]]:
    """(name, path or None for a built-in preset, spec): the user's .cypipe files, then the presets."""
    from .pipeline_presets import PRESETS
    out = []
    d = library_dir()
    if d.exists():
        for p in sorted(d.glob(f'*{EXT}')):
            try:
                s = PipelineSpec.load(p)
                out.append((s.name, p, s))
            except Exception:  # noqa: BLE001
                traceback.print_exc()
    have = {n for n, _p, _s in out}
    for d in PRESETS:
        s = PipelineSpec.from_dict(d)
        if s.name not in have:
            out.append((s.name, None, s))
    return out


def find_preset(name) -> PipelineSpec:
    for n, p, s in library():
        if n == name or (p is not None and (p.stem == name or str(p) == name)):
            return s.copy()
    if Path(name).exists():
        return PipelineSpec.load(name)
    raise KeyError(f'프리셋 "{name}"이(가) 없습니다.')


def chip_summary(spec: PipelineSpec) -> dict:
    """group title -> stage titles, for the library cards."""
    out = {}
    for st in spec.stages:
        g = dict(GROUPS)[STAGES[st['kind']]['group']]
        out.setdefault(g, []).append(stage_title(st) if st['kind'] != 'op' else (st['settings'].get('out') or '연산'))
    return out


def set_path(d: dict, path: str, value):
    """edit helper: stages[3].settings.k=8 style paths."""
    parts = re.findall(r'[^.\[\]]+|\[\d+\]', path)
    cur = d
    for k, p in enumerate(parts):
        last = k == len(parts) - 1
        key = int(p[1:-1]) if p.startswith('[') else p
        if last:
            cur[key] = value
        else:
            if isinstance(key, str) and key not in cur:
                cur[key] = {}
            cur = cur[key]
    return d
