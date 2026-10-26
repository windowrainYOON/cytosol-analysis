"""Acquisition metadata: a readable summary per image (the 이미지 정보 tab)
and the bleach regions / events of Zeiss CZI files.

``summarize(item)`` returns an ``InfoSummary``: general rows (section, item,
value) and one column per channel (fluorophore, excitation/emission, laser,
laser intensity, exposure / pixel dwell, detector gain, pinhole, ...), from
what each format stores: CZI (ZEN XML), OIR (FluoView XML), TCF (HDF5
attributes) and TIFF (ImageJ / OME metadata).

Laser intensities are what the software stores: a percentage of the laser
line (and, where the file has it, the line's rated maximum in mW). The power
reaching the sample is never in the file.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np

BLEACH_PREFIX = 'bleach'  # name prefix of the ImageJ ROIs holding bleach regions
# order of the sections in the summary table
SECTIONS = ('파일', '크기', '공간', '시간', '대물렌즈', '스캔', 'HT (굴절률)', 'Bleaching',
            'Bleach ROI', 'ImageJ', 'ImageJ Info')


@dataclass
class InfoSummary:
    general: list = field(default_factory=list)  # (section, item, value)
    channels: list = field(default_factory=list)  # channel names (columns)
    channel_rows: list = field(default_factory=list)  # (item, [value per channel])

    def add(self, section, item, value):
        if value not in (None, '', []):
            self.general.append((section, item, str(value)))

    def rows_csv(self) -> list[list[str]]:
        """Both tables as CSV rows (general first, then per channel)."""
        out = [['section', 'item', 'value']]
        out += [list(r) for r in self.general]
        if self.channels:
            out.append([])
            out.append(['channel item'] + list(self.channels))
            out += [[name] + list(vals) for name, vals in self.channel_rows]
        return out


@dataclass
class BleachRoi:
    """One bleach region in image pixel coordinates."""

    name: str
    shape: str  # 'circle', 'ellipse', 'rectangle', 'polygon'
    polygons: list  # [(N, 2) float array of x, y], outer outline first
    lasers: list = field(default_factory=list)  # [(wavelength nm, intensity %)]

    @property
    def xy(self) -> np.ndarray:
        return self.polygons[0]

    def bounds(self):
        xy = np.concatenate(self.polygons)
        return xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max()

    def center(self):
        x0, y0, x1, y1 = self.bounds()
        return (x0 + x1) / 2, (y0 + y1) / 2


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(v, digits=3, unit=''):
    """Number with up to `digits` significant decimals, '' for None."""
    if v is None or v == '':
        return ''
    if isinstance(v, str):
        f = _num(v)
        if f is None:
            return v + (f' {unit}' if unit else '')
        v = f
    if isinstance(v, (bool, np.bool_)):
        return '예' if v else '아니오'
    v = float(v)
    if v == int(v) and abs(v) < 1e12:
        s = str(int(v))
    else:
        s = f'{v:.{digits}g}' if abs(v) < 1e-3 or abs(v) >= 1e5 else f'{v:.{digits}f}'.rstrip('0').rstrip('.')
    return f'{s} {unit}' if unit else s


def _text(node, path, default=None):
    if node is None:
        return default
    t = node.findtext(path)
    return t.strip() if t is not None and t.strip() else default


def _yes(v) -> bool:
    return str(v).strip().lower() == 'true'


# ---------------------------------------------------------------------------
# WPF path geometry (ZEN BleachRegionGeometryString)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r'[A-Za-z]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def parse_wpf_path(s: str, steps: int = 16) -> list[np.ndarray]:
    """Polygons of a WPF path mini-language string ('F1M x,y C ... z').

    Curves are sampled with `steps` points; arcs are replaced by a line to
    their end point. Returns one (N, 2) array per closed or open subpath.
    """
    toks = _TOKEN.findall(s or '')
    polys, cur, pos, start = [], [], np.zeros(2), np.zeros(2)
    cmd, i, last_ctrl = None, 0, None

    def nums(k):
        nonlocal i
        vals = [float(t) for t in toks[i:i + k]]
        if len(vals) < k or any(re.match('[A-Za-z]', t) for t in toks[i:i + k]):
            raise ValueError('bad path')
        i += k
        return vals

    def flush():
        nonlocal cur
        if len(cur) >= 2:
            polys.append(np.asarray(cur, float))
        cur = []

    while i < len(toks):
        t = toks[i]
        if re.match('[A-Za-z]', t):
            cmd = t
            i += 1
            if cmd in 'Ff':
                i += 1  # fill rule number
                continue
            if cmd in 'Zz':
                flush()
                pos = start.copy()
                continue
        if cmd is None:
            break
        rel = cmd.islower()
        c = cmd.upper()
        base = pos if rel else np.zeros(2)
        try:
            if c == 'M':
                flush()
                pos = base + nums(2)
                start = pos.copy()
                cur = [pos.copy()]
                cmd = 'l' if rel else 'L'  # further pairs are lines
            elif c == 'L':
                pos = base + nums(2)
                cur.append(pos.copy())
            elif c == 'H':
                x, = nums(1)
                pos = np.array([pos[0] + x if rel else x, pos[1]])
                cur.append(pos.copy())
            elif c == 'V':
                y, = nums(1)
                pos = np.array([pos[0], pos[1] + y if rel else y])
                cur.append(pos.copy())
            elif c in 'CS':
                if c == 'C':
                    v = nums(6)
                    p1, p2, p3 = base + v[0:2], base + v[2:4], base + v[4:6]
                else:
                    v = nums(4)
                    p1 = 2 * pos - last_ctrl if last_ctrl is not None else pos.copy()
                    p2, p3 = base + v[0:2], base + v[2:4]
                for u in np.linspace(0, 1, steps + 1)[1:]:
                    cur.append((1 - u) ** 3 * pos + 3 * (1 - u) ** 2 * u * p1
                               + 3 * (1 - u) * u ** 2 * p2 + u ** 3 * p3)
                last_ctrl = p2
                pos = p3
                continue
            elif c == 'Q':
                v = nums(4)
                p1, p2 = base + v[0:2], base + v[2:4]
                for u in np.linspace(0, 1, steps + 1)[1:]:
                    cur.append((1 - u) ** 2 * pos + 2 * (1 - u) * u * p1 + u ** 2 * p2)
                pos = p2
            elif c == 'A':
                v = nums(7)
                pos = base + v[5:7]
                cur.append(pos.copy())
            else:
                i += 1
        except ValueError:
            break
        last_ctrl = None
    flush()
    return polys


def _ellipse(cx, cy, rx, ry, n=96) -> np.ndarray:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([cx + rx * np.cos(a), cy + ry * np.sin(a)], 1)


# ---------------------------------------------------------------------------
# CZI
# ---------------------------------------------------------------------------


def _czi_root(xml):
    if xml is None:
        return None
    if isinstance(xml, ET.Element):
        return xml
    try:
        return ET.fromstring(xml)
    except ET.ParseError:
        return None


def _layer_shape(el):
    """(shape, polygon) of a ZEN graphics element in image pixels, or None."""
    g = el.find('Geometry')
    if g is None:
        return None
    tag = el.tag
    f = lambda k: _num(g.findtext(k))  # noqa: E731
    if tag == 'Circle' and None not in (f('CenterX'), f('CenterY'), f('Radius')):
        return 'circle', _ellipse(f('CenterX'), f('CenterY'), f('Radius'), f('Radius'))
    if tag == 'Ellipse' and None not in (f('CenterX'), f('CenterY'), f('RadiusX'), f('RadiusY')):
        return 'ellipse', _ellipse(f('CenterX'), f('CenterY'), f('RadiusX'), f('RadiusY'))
    if tag in ('Rectangle', 'Square') and None not in (f('Left'), f('Top'), f('Width'), f('Height')):
        x0, y0, w, h = f('Left'), f('Top'), f('Width'), f('Height')
        return 'rectangle', np.array([[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]], float)
    pts = g.findtext('Points')
    if pts:
        xy = [tuple(map(float, p.split(','))) for p in pts.split() if ',' in p]
        if len(xy) >= 3:
            return 'polygon', np.asarray(xy, float)
    return None


def czi_bleach_rois(xml) -> list[BleachRoi]:
    """Bleach regions of a CZI in image pixels.

    From the executed bleach events (BleachRegion geometry strings), else
    from the experiment regions marked for bleaching, drawn on the image's
    annotation layer.
    """
    root = _czi_root(xml)
    if root is None:
        return []
    # region items marked for bleaching: key -> (name, type)
    items = {}
    for ri in root.iter('RegionItem'):
        if _yes(ri.get('IsForBleach')):
            items[ri.get('Key')] = (ri.get('Name') or '', (ri.get('RegionType') or '').lower())
    types = [t for _, t in items.values()]
    out, seen = [], set()
    for br in root.iter('BleachRegion'):
        geo = _text(br, 'BleachRegionGeometryString')
        name = _text(br, 'Name', f'Region {len(out) + 1}')
        if not geo or (name, geo) in seen:
            continue
        seen.add((name, geo))
        polys = parse_wpf_path(geo)
        if not polys:
            continue
        lasers = []
        for ll in br.iter('Laserline'):
            wl, it = _num(ll.findtext('Wavelength')), _num(ll.findtext('Intensity'))
            if wl is not None and it:
                lasers.append((wl, it))
        k = len(out)
        rtype = types[k] if k < len(types) else 'polygon'
        shape = {'circular': 'circle', 'elliptical': 'ellipse', 'rectangular': 'rectangle'}.get(
            rtype, 'polygon')
        out.append(BleachRoi(name, shape, polys, lasers))
    if out or not items:
        return out
    for layer in root.iter('Layer'):
        elements = layer.find('Elements')
        if elements is None:
            continue
        for el in elements:
            uid = _text(el, 'Attributes/UniqueName')
            if uid in items:
                got = _layer_shape(el)
                if got:
                    name = items[uid][0] or f'Region {len(out) + 1}'
                    out.append(BleachRoi(name, got[0], [got[1]]))
    return out


def czi_bleach_info(xml, events=(), frame_times=()) -> dict | None:
    """Bleach settings and events of a CZI; None when no bleaching ran.

    events: (time s, 'BLEACH_START' / 'BLEACH_STOP') from the EventList
    attachment; frame_times: acquisition time (s) of each frame on the same
    clock (the TimeStamps attachment).
    """
    root = _czi_root(xml)
    if root is None:
        return None
    setup = next(root.iter('BleachingSetup'), None)
    starts = [t for t, k in events if k == 'BLEACH_START']
    stops = [t for t, k in events if k == 'BLEACH_STOP']
    timeline = [te for te in root.iter('TimelineElement') if te.find('.//Bleaching') is not None]
    active = setup is not None and _yes(setup.get('IsActivated'))
    if not (starts or timeline):
        return None if not active else {'active': True, 'ran': False}
    info = {'active': active, 'ran': True}
    ext = setup.find('ExtensionSettings') if setup is not None else None
    if ext is not None:
        for key in ('Iterations', 'Repetition', 'StartIndex', 'SpotBleachDuration',
                    'IntensityThreshold'):
            info[key] = _num(ext.findtext(key))
        for key in ('HasRepetition', 'HasStartIndex', 'StopOnIntensityDrop', 'ZoomBleach',
                    'ProtectDetectorDuringBleach', 'SetAlternateScanSpeed', 'RegionSpecificSettings'):
            if ext.findtext(key) is not None:
                info[key] = _yes(ext.findtext(key))
    btype = next((b.findtext('BleachingType') for b in root.iter('Bleaching')), None)
    info['type'] = btype
    # lasers used, from the executed regions (fallback: the setup)
    lasers = {}
    for ll in root.iter('Laserline'):
        wl, it = _num(ll.findtext('Wavelength')), _num(ll.findtext('Intensity'))
        if wl is not None and it:
            lasers[wl] = it
    info['lasers'] = sorted(lasers.items())
    # durations: event pairs, else the timeline
    durations = [b - a for a, b in zip(starts, stops) if b >= a]
    if not durations:
        durations = [_num(te.findtext('Duration')) for te in timeline if _num(te.findtext('Duration'))]
    info['count'] = len(starts) or len(timeline)
    info['durations'] = durations
    t0 = frame_times[0] if len(frame_times) else None
    if starts and t0 is not None:
        info['start_times'] = [a - t0 for a in starts]
        # first frame acquired after each bleach started (0-based); the
        # frame's time stamp can be a fraction of a ms before the stop event
        ft = np.asarray(frame_times)
        info['frames_after'] = [int(np.searchsorted(ft, a)) for a in starts]
    else:
        info['frames_after'] = [int(_num(te.find('Bounds').get('StartT')) or 0)
                                for te in timeline if te.find('Bounds') is not None
                                and te.find('Bounds').get('StartT') is not None]
    return info


def _czi_devices(root) -> dict:
    """Device Id -> attributes (laser lines carry Wavelength / MaxPowerMilliWatts)."""
    return {d.get('Id'): dict(d.attrib) for d in root.iter('Device') if d.get('Id')}


def _czi_summary(s: InfoSummary, item, meta):
    root = _czi_root(meta.get('xml'))
    if root is None:
        return
    info = root.find('Metadata/Information')
    app = info.find('Application') if info is not None else None
    if app is not None:
        s.add('파일', '소프트웨어', ' '.join(x for x in (_text(app, 'Name'), _text(app, 'Version')) if x))
    system = _text(root, 'Metadata/Scaling/AutoScaling/CameraName')
    mic = next(root.iter('Microscope'), None)
    if mic is not None and (mic.get('Name') or _text(mic, 'System')):
        system = ' / '.join(x for x in (mic.get('Name') or _text(mic, 'System'), system) if x)
    s.add('파일', '장비', system)
    s.add('파일', '사용자', _text(root, 'Metadata/Information/Document/UserName'))
    img = info.find('Image') if info is not None else None
    s.add('파일', '픽셀 형식', _text(img, 'PixelType'))
    # objective
    obj = next(root.iter('Objective'), None) if info is None else info.find('Instrument/Objectives/Objective')
    if obj is not None:
        s.add('대물렌즈', '이름', obj.get('Name') or _text(obj, 'Manufacturer/Model'))
        s.add('대물렌즈', '배율', fmt(_text(obj, 'NominalMagnification'), unit='x'))
        s.add('대물렌즈', 'NA', fmt(_text(obj, 'LensNA')))
        s.add('대물렌즈', '침지액', _text(obj, 'Immersion'))
        s.add('대물렌즈', '침지액 굴절률', fmt(_text(obj, 'ImmersionRefractiveIndex')))
        s.add('대물렌즈', '작동 거리', fmt(_text(obj, 'WorkingDistance'), unit='µm'))
    s.add('대물렌즈', '총 배율', fmt(_text(img, 'MicroscopeSettings/EyepieceSettings/TotalMagnification'),
                                    unit='x'))
    devices = _czi_devices(root)
    detectors = {d.get('Id'): d for d in root.iter('Detector') if d.get('Name') or d.find('Type') is not None}
    chans = img.findall('Dimensions/Channels/Channel') if img is not None else []
    names = list(item.channels) if item is not None else []
    if chans and len(chans) == len(names):
        cols = []
        for ch in chans:
            col = {}
            col['이름 (파일)'] = ch.get('Name') or ''
            col['형광체'] = _text(ch, 'Fluor', '')
            ex, em = _text(ch, 'ExcitationWavelength'), _text(ch, 'EmissionWavelength')
            col['형광체 Ex / Em'] = f'{fmt(ex)} / {fmt(em)} nm' if ex or em else ''
            col['촬영 방식'] = _text(ch, 'AcquisitionMode', '')
            col['조명'] = ' / '.join(x for x in (_text(ch, 'IlluminationType'), _text(ch, 'ContrastMethod')) if x)
            wls, pct, mws, nom = [], [], [], []
            for ls in ch.findall('LightSourcesSettings/LightSourceSettings'):
                wl = _num(ls.findtext('Wavelength'))
                tr = _num(ls.findtext('Transmission'))
                if tr is None and _num(ls.findtext('Attenuation')) is not None:
                    tr = 1 - _num(ls.findtext('Attenuation'))
                ref = ls.find('LightSource')
                dev = devices.get(ref.get('Id') if ref is not None else None, {})
                wl = wl if wl is not None else _num(dev.get('Wavelength'))
                mx = _num(dev.get('MaxPowerMilliWatts'))
                wls.append(fmt(wl, unit='nm'))
                pct.append(fmt(tr * 100, 3, '%') if tr is not None else '')
                mws.append(fmt(mx, unit='mW') if mx else '')
                nom.append(fmt(mx * tr, 3, 'mW') if mx and tr is not None else '')
            col['레이저 파장'] = ', '.join(x for x in wls if x)
            col['레이저 세기 (설정값)'] = ', '.join(x for x in pct if x)
            col['레이저 최대 출력 (정격)'] = ', '.join(x for x in mws if x)
            col['레이저 명목 출력 (최대 × 세기)'] = ', '.join(x for x in nom if x)
            exp = _num(_text(ch, 'ExposureTime'))
            col['노출 시간'] = fmt(exp / 1e6, 4, 'ms') if exp else ''  # ZEN stores ns
            lsi = ch.find('LaserScanInfo')
            if lsi is not None:
                col['Pixel dwell time'] = fmt((_num(_text(lsi, 'PixelTime')) or 0) * 1e6, 3, 'µs')
                col['Frame time'] = fmt(_text(lsi, 'FrameTime'), 4, 's')
                avg = _text(lsi, 'Averaging')
                col['평균 (averaging)'] = ' '.join(x for x in (avg, _text(lsi, 'AveragingMode'),
                                                              _text(lsi, 'AveragingMethod')) if x)
                col['스캔 방향'] = _text(lsi, 'ScanDirection', '')
                col['스캔 속도'] = _text(lsi, 'ScanSpeed', '')
                col['줌'] = _text(lsi, 'ZoomX', '')
            ds = ch.find('DetectorSettings')
            if ds is not None:
                ref = ds.find('Detector')
                did = ref.get('Id') if ref is not None else None
                det = detectors.get(did)
                dname = det.get('Name') if det is not None else (did or '')
                dtype = _text(det, 'Type') if det is not None else None
                col['검출기'] = f'{dname} ({dtype})' if dtype and dtype not in (dname or '') else (dname or '')
                col['검출기 전압 (gain)'] = fmt(_text(ds, 'Voltage'), 1, 'V')
                col['Digital gain'] = fmt(_text(ds, 'DigitalGain'))
                col['Offset'] = fmt(_text(ds, 'Offset'))
                col['검출 모드'] = _text(ds, 'DetectorMode', '')
                col['Binning'] = _text(ds, 'Binning', '')
                col['카메라 gain'] = fmt(_text(ds, 'Gain'))
            col['검출 파장 범위'] = fmt(_text(ch, 'DetectionWavelength/Ranges'), unit='nm')
            ph, au = _text(ch, 'PinholeSize'), _text(ch, 'PinholeSizeAiry')
            col['핀홀'] = (f'{fmt(ph, 4, "µm")}' + (f' ({fmt(au, 3)} AU)' if au else '')) if ph else ''
            col['비트 깊이'] = fmt(_text(ch, 'ComponentBitCount'), unit='bit')
            col['표시 색'] = _text(ch, 'Color', '')
            cols.append(col)
        _set_columns(s, names, cols)
    # bleaching
    b = meta.get('bleach')
    if b and b.get('ran'):
        sec = 'Bleaching'
        s.add(sec, '실행 여부', '예')
        s.add(sec, '방식', b.get('type'))
        s.add(sec, 'Bleach 레이저', ', '.join(f'{fmt(w)} nm {fmt(i, 3)} %' for w, i in b.get('lasers', [])))
        mx = []
        for w, i in b.get('lasers', []):
            for d in devices.values():
                if _num(d.get('Wavelength')) == w and _num(d.get('MaxPowerMilliWatts')):
                    m = _num(d['MaxPowerMilliWatts'])
                    mx.append(f'{fmt(w)} nm: 정격 {fmt(m)} mW, 명목 {fmt(m * i / 100, 3)} mW')
                    break
        s.add(sec, 'Bleach 레이저 출력', '; '.join(mx))
        s.add(sec, '반복 (iterations)', fmt(b.get('Iterations')))
        s.add(sec, 'Bleach 횟수', fmt(b.get('count')))
        d = b.get('durations') or []
        if d:
            s.add(sec, 'Bleach 1회 시간', fmt(float(np.mean(d)), 4, 's'))
        st = b.get('start_times') or []
        if st:
            s.add(sec, '첫 bleach 시각', f'첫 프레임 {fmt(-st[0], 3)} s 전' if st[0] < 0
                  else f'첫 프레임 후 {fmt(st[0], 3)} s')
        fa = b.get('frames_after') or []
        if fa:
            s.add(sec, 'Bleach 직후 프레임', _frame_list(fa, item.nt if item is not None else None))
        if fa:
            s.add(sec, 'Pre-bleach 프레임 수', fmt(min(fa)))
        if b.get('HasStartIndex'):
            s.add(sec, '시작 프레임 (StartIndex)', fmt(b.get('StartIndex')))
        if b.get('HasRepetition'):
            s.add(sec, '반복 주기 (Repetition)', f'{fmt(b.get("Repetition"))} 프레임마다')
        for key, label in (('StopOnIntensityDrop', '강도 감소 시 중단'), ('ZoomBleach', 'Zoom bleach'),
                           ('ProtectDetectorDuringBleach', 'Bleach 중 검출기 보호')):
            if key in b:
                s.add(sec, label, fmt(b[key]))
    elif b and b.get('active'):
        s.add('Bleaching', '실행 여부', '설정은 켜져 있지만 bleach 이벤트 기록 없음')
    else:
        s.add('Bleaching', '실행 여부', '아니오 (기록 없음)')


def _frame_list(frames, nt=None) -> str:
    """'1–19 (매 프레임)' / '6' / '6, 11, 16' (1-based)."""
    f = [k + 1 for k in frames]
    if len(f) > 2 and f == list(range(f[0], f[0] + len(f))):
        txt = f'{f[0]}–{f[-1]}'
        if nt and f[0] == 1 and f[-1] >= nt:
            txt += ' (매 프레임)'
        return txt
    return ', '.join(map(str, f[:30])) + (' …' if len(f) > 30 else '')


def _set_columns(s: InfoSummary, names, cols):
    s.channels = list(names)
    keys = []
    for col in cols:
        keys += [k for k in col if k not in keys]
    for k in keys:
        vals = [str(c.get(k, '') or '') for c in cols]
        if any(vals):
            s.channel_rows.append((k, vals))


# ---------------------------------------------------------------------------
# OIR
# ---------------------------------------------------------------------------


def _oir_summary(s: InfoSummary, item, meta):
    xml = '\n'.join(str(v) for v in (meta.get('xml') or {}).values())
    xml = xml.replace('\\r\\n', '\n')
    s.add('파일', '장비', meta.get('system'))
    s.add('파일', '비트 깊이', fmt(meta.get('bitspersample'), unit='bit'))
    m = re.search(r'<commonimage:objectiveLens[^>]*>(.*?)</commonimage:objectiveLens>', xml, re.S)
    if m:
        o = m.group(1)
        g = lambda tag: (re.search(rf'<opticalelement:{tag}>([^<]*)<', o) or [None, None])[1]  # noqa: E731
        s.add('대물렌즈', '이름', g('name'))
        s.add('대물렌즈', '배율', fmt(g('magnification'), unit='x'))
        s.add('대물렌즈', 'NA', fmt(g('naValue')))
        s.add('대물렌즈', '작동 거리', fmt(g('wdValue'), unit='mm'))
    sc = meta.get('scanner')
    if sc is not None:
        s.add('스캔', '스캐너', getattr(sc, 'type', None))
        ps = _num(getattr(sc, 'pixel_speed', None))
        s.add('스캔', 'Pixel dwell time', fmt(ps * 1000, 3, 'µs') if ps else '')
        s.add('스캔', 'Line time', fmt(getattr(sc, 'line_speed', None), 4, 'ms'))
        fs = _num(getattr(sc, 'frame_speed', None))
        s.add('스캔', 'Frame time', fmt(fs / 1000, 4, 's') if fs else '')
        s.add('스캔', '왕복 스캔', fmt(getattr(sc, 'roundtrip', None)))
    # laser data id -> (wavelength, transmissivity %)
    lasers = {}
    for lm in re.finditer(r'<lsmparam:mainLaser laserDataId="([^"]+)">\s*<commonparam:power>([^<]*)<'
                          r'/commonparam:power>\s*<commonparam:transmissivity>([^<]*)<', xml):
        lasers.setdefault(lm.group(1), (_num(lm.group(2)), _num(lm.group(3))))
    wl_of = {lm.group(1): _num(lm.group(2)) for lm in re.finditer(
        r'id="([^"]+)"[^>]*>\s*<commonimage:wavelength>([^<]*)<', xml)}
    chans = list(meta.get('channel_info') or [])
    names = list(item.channels) if item is not None else []
    cols = []
    for name in names:
        cands = [c for c in chans if c.name == name]
        cands = [c for c in cands if c.start_wavelength is not None] or cands
        c = cands[-1] if cands else None
        col = {}
        if c is not None:
            cid = c.id
            block = re.search(rf'<commonphase:channel id="{re.escape(cid)}".*?</commonphase:channel>', xml, re.S)
            block = block.group(0) if block else ''
            doc = re.search(rf'<lsmimage:lsmChannel[^>]*id="{re.escape(cid)}".*?</lsmimage:lsmChannel>',
                            xml, re.S)
            doc = doc.group(0) if doc else ''
            dye = re.search(r'<lsmimage:dyeName>([^<]*)<', doc)
            col['형광체'] = dye.group(1) if dye else ''
            ex = re.search(r'<dye:excitationWavelength>([^<]*)<.*?<dye:emissionWavelength>([^<]*)<', doc, re.S)
            col['형광체 Ex / Em'] = f'{fmt(ex.group(1))} / {fmt(ex.group(2))} nm' if ex and dye else ''
            ld = re.search(r'<commonphase:laserDataId>([^<]*)<', block)
            if ld and ld.group(1) in lasers:
                power, tr = lasers[ld.group(1)]
                wl = wl_of.get(ld.group(1))
                col['레이저 파장'] = fmt(wl, unit='nm')
                col['레이저 세기 (설정값)'] = fmt(tr, 3, '%')
                if power is not None and power != 100:
                    col['레이저 출력 설정'] = fmt(power, 3, '%')
            pmt = re.search(rf'<lsmparam:pmt channelId="{re.escape(cid)}"[^>]*>\s*<lsmparam:voltage>([^<]*)<'
                            r'/lsmparam:voltage>\s*<lsmparam:offset>([^<]*)</lsmparam:offset>\s*'
                            r'<lsmparam:gain>([^<]*)<', xml)
            if pmt:
                col['검출기 전압 (HV)'] = fmt(pmt.group(1), unit='V')
                col['Offset'] = fmt(pmt.group(2))
                col['Gain'] = fmt(pmt.group(3))
            if c.start_wavelength is not None:
                col['검출 파장 범위'] = f'{fmt(c.start_wavelength)}–{fmt(c.end_wavelength)} nm'
            ph = re.search(r'<fvCommonphase:pinholeDiameter>([^<]*)<', block)
            col['핀홀'] = fmt(ph.group(1), unit='µm') if ph else ''
        cols.append(col)
    if names:
        _set_columns(s, names, cols)
    stim = re.search(r'<fvCommonimage:stimulationParam.*?</fvCommonimage:stimulationParam>', xml, re.S)
    if stim:
        on = [(lm.group(1), _num(lm.group(2))) for lm in re.finditer(
            r'laserDataId="LD(\d+)_\d+Stimulating[^"]*">\s*<commonparam:power>[^<]*</commonparam:power>\s*'
            r'<commonparam:transmissivity>([^<]*)<', stim.group(0)) if _num(lm.group(2))]
        if on:
            s.add('Bleaching', '자극/bleach 레이저', ', '.join(f'{w} nm {fmt(t, 3)} %' for w, t in on))
        else:
            s.add('Bleaching', '실행 여부', '아니오 (자극 레이저 0 %)')


# ---------------------------------------------------------------------------
# TCF
# ---------------------------------------------------------------------------


def _tcf_summary(s: InfoSummary, item, meta):
    f, dev = meta.get('file') or {}, meta.get('device') or {}
    s.add('파일', '장비', ' '.join(str(x) for x in (f.get('DeviceModelType'), f.get('DeviceSerial')) if x))
    s.add('파일', '소프트웨어', f.get('SoftwareVersion'))
    s.add('파일', '촬영 시각', f.get('RecordingTime'))
    s.add('파일', '사용자', f.get('UserID'))
    s.add('파일', 'TCF 버전', f.get('FormatVersion'))
    s.add('파일', '모달리티', meta.get('modality'))
    s.add('대물렌즈', '배율', fmt(dev.get('Magnification'), unit='x'))
    s.add('대물렌즈', 'NA', fmt(dev.get('NA')))
    s.add('대물렌즈', '배지 굴절률', fmt(dev.get('RI'), 4))
    g = meta.get('group') or {}
    if 'RIMin' in g:
        s.add('HT (굴절률)', 'RI 범위', f'{fmt(g.get("RIMin"), 4)} – {fmt(g.get("RIMax"), 4)}')
    flc = meta.get('fl_channels') or {}
    names = list(item.channels) if item is not None else []
    cols = []
    for name in names:
        key = name.split()[0]
        a = flc.get(key)
        col = {}
        if a is None:
            col['종류'] = 'HT (굴절률)' if name == 'RI' else ''
        else:
            col['종류'] = '형광 (FL)'
            ex, em = _num(a.get('Excitation')), _num(a.get('Emission'))
            col['Ex / Em'] = f'{fmt(ex * 1000 if ex else None)} / {fmt(em * 1000 if em else None)} nm'
            col['광원 세기 (설정값)'] = fmt(a.get('Intensity'), 3, '%')
            exp = _num(a.get('ExposureTime'))
            col['노출 시간'] = fmt(exp / 1000, 4, 'ms') if exp else ''  # stored in µs
            for k in ('Gain', 'Binning'):
                if k in a:
                    col[k] = fmt(a.get(k))
        cols.append(col)
    if names:
        _set_columns(s, names, cols)


# ---------------------------------------------------------------------------
# TIFF
# ---------------------------------------------------------------------------


def _tiff_summary(s: InfoSummary, item, meta):
    s.add('파일', '축', meta.get('axes'))
    s.add('파일', 'OME-TIFF', fmt(bool(meta.get('ome'))))
    s.add('파일', '비트', fmt(meta.get('bits'), unit='bit'))
    s.add('파일', '원본 파일', meta.get('source_name'))
    ij = meta.get('imagej') or {}
    for k in ('ImageJ', 'unit', 'finterval', 'spacing', 'mode'):
        if ij.get(k) not in (None, ''):
            s.add('ImageJ', k, ij.get(k))
    info = ij.get('Info')
    if isinstance(info, str):
        for line in info.splitlines()[:40]:
            if '=' in line:
                k, v = line.split('=', 1)
                s.add('ImageJ Info', k.strip(), v.strip())


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def summarize(item) -> InfoSummary:
    """Summary of an ImageItem (or anything with .image / .channels)."""
    image = item.image
    meta = image.metadata or {}
    s = InfoSummary()
    fmt_name = meta.get('format', '')
    s.add('파일', '이름', getattr(item, 'source_name', None) or getattr(item, 'label', ''))
    s.add('파일', '형식', fmt_name)
    s.add('파일', '이미지 ID', getattr(item, 'image_id', None))
    if meta.get('datetime') is not None:
        s.add('파일', '획득 시각', str(meta['datetime']).replace('T', ' ')[:23])
    c, z, h, w = image.shape
    s.add('크기', 'X × Y', f'{w} × {h} px')
    s.add('크기', 'Z', fmt(z))
    s.add('크기', '채널 수', fmt(c))
    s.add('크기', '시점 수 (T)', fmt(image.nt))
    vx = image.voxel_size_um or {}
    if vx.get('X'):
        s.add('공간', '픽셀 크기', f'{fmt(vx["X"], 4)} × {fmt(vx.get("Y") or vx["X"], 4)} µm')
        s.add('공간', '시야', f'{fmt(vx["X"] * w, 4)} × {fmt((vx.get("Y") or vx["X"]) * h, 4)} µm')
    if vx.get('Z') and z > 1:
        s.add('공간', 'Z 간격', fmt(vx['Z'], 4, 'µm'))
        s.add('공간', 'Z 범위', fmt(vx['Z'] * (z - 1), 4, 'µm'))
    times = list(image.times or [])
    if len(times) > 1:
        dt = np.diff(times)
        s.add('시간', '프레임 간격', fmt(float(np.mean(dt)), 4, 's')
              + (f' (min {fmt(float(dt.min()), 4)} – max {fmt(float(dt.max()), 4)} s)'
                 if float(dt.max() - dt.min()) > 1e-3 * max(1e-9, float(np.mean(dt))) else ''))
        s.add('시간', '총 길이', fmt(times[-1] - times[0], 4, 's'))
    rng = image.ranges[0] if image.ranges else None
    if rng is not None:
        note = image.range_notes[0] if image.range_notes else ''
        s.add('크기', '값 범위', f'{fmt(rng[0])} – {fmt(rng[1])}' + (f' ({note})' if note else ''))
    try:
        if fmt_name == 'CZI':
            _czi_summary(s, item, meta)
        elif fmt_name == 'OIR':
            _oir_summary(s, item, meta)
        elif fmt_name == 'TCF':
            _tcf_summary(s, item, meta)
        elif fmt_name == 'TIFF':
            _tiff_summary(s, item, meta)
    except Exception as exc:  # metadata is best effort; never break the tab
        s.add('파일', '메타데이터 읽기 오류', repr(exc))
    if not s.channels:
        s.channels = list(item.channels)
        s.channel_rows = []
    s.channel_rows.insert(0, ('채널', list(item.channels)))
    rois = getattr(item, 'bleach_rois', None) or []
    px = vx.get('X')
    for k, r in enumerate(rois, 1):
        cx, cy = r.center()
        x0, y0, x1, y1 = r.bounds()
        size = f'{fmt(x1 - x0, 4)} × {fmt(y1 - y0, 4)} px'
        if px:
            size += f' ({fmt((x1 - x0) * px, 4)} × {fmt((y1 - y0) * px, 4)} µm)'
        label = {'circle': '원', 'ellipse': '타원', 'rectangle': '사각형'}.get(r.shape, '다각형')
        s.add('Bleach ROI', f'{k}. {r.name}', f'{label}, 중심 ({fmt(cx, 5)}, {fmt(cy, 5)}) px, 크기 {size}')
    rank = {k: i for i, k in enumerate(SECTIONS)}
    s.general.sort(key=lambda r: rank.get(r[0], len(rank)))
    return s


def csv_text(summary: InfoSummary) -> str:
    import csv
    import io

    buf = io.StringIO()
    csv.writer(buf).writerows(summary.rows_csv())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# bleach ROIs <-> ImageJ
# ---------------------------------------------------------------------------


def bleach_imagej_rois(rois: list[BleachRoi], properties=None) -> list:
    """ImageJ ROIs (oval for circles/ellipses, else sub-pixel polygon) named bleachN."""
    import roifile

    out = []
    for k, r in enumerate(rois, 1):
        name = f'{BLEACH_PREFIX}{k}'
        if r.shape in ('circle', 'ellipse', 'rectangle'):
            x0, y0, x1, y1 = r.bounds()
            roi = roifile.ImagejRoi()
            roi.roitype = roifile.ROI_TYPE.OVAL if r.shape != 'rectangle' else roifile.ROI_TYPE.RECT
            roi.version = 228
            roi.name = name
            roi.left, roi.top = int(round(x0)), int(round(y0))
            roi.right, roi.bottom = int(round(x1)), int(round(y1))
        else:
            roi = roifile.ImagejRoi.frompoints(np.asarray(r.xy, np.float32), name=name)
            roi.roitype = roifile.ROI_TYPE.POLYGON
        props = dict(properties or {})
        props['bleach_region'] = r.name
        props['bleach_shape'] = r.shape
        if r.lasers:
            props['bleach_lasers'] = '; '.join(f'{w:g} nm {i:g} %' for w, i in r.lasers)
        roi.properties = props
        out.append(roi)
    return out


def save_bleach_rois(path, rois: list[BleachRoi], properties=None) -> str:
    import roifile
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    roifile.roiwrite(path, bleach_imagej_rois(rois, properties))
    return str(path)


def _read(path) -> list:
    import roifile

    try:
        r = roifile.roiread(path)
    except Exception:
        return []
    return r if isinstance(r, list) else [r]


def is_bleach_file(path) -> bool:
    rois = _read(path)
    return bool(rois) and all((x.name or '').lower().startswith(BLEACH_PREFIX)
                              and 'bleach_region' in (x.properties or {}) for x in rois)


def load_bleach_rois(path) -> list[BleachRoi]:
    from .cellroi import _roi_polygons

    out = []
    for r in _read(path):
        props = r.properties or {}
        lasers = []
        for part in str(props.get('bleach_lasers', '')).split(';'):
            m = re.match(r'\s*([\d.]+) nm ([\d.]+) %', part)
            if m:
                lasers.append((float(m.group(1)), float(m.group(2))))
        out.append(BleachRoi(props.get('bleach_region', r.name), props.get('bleach_shape', 'polygon'),
                             [np.asarray(p, float) for p in _roi_polygons(r)], lasers))
    return out
