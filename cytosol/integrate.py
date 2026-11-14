"""통합 데이터: every measurement merged into one table per 점 하나
(owner request 2026-11-15, design v4 in /mnt/project-files/data-join/).

Categories: 이미지별, 세포별, 세포 × 띠별, 입자별, 미토 조각별, 시점별.  Nothing
is measured again: the tables are built from the results the tabs already
have (MeasureBox rows, Coloc 2 records, mitoROI results, tracks, FRAP
curves) whenever they are asked for, so they always equal the originals and
an image measured again changes only its own rows.

- Columns are named ``기능 › 열`` (``입자 ROI › area_um2``); the key columns
  (image, image_id, group, cell, band, particle, mito, frame) come first.
- Objects (particles, mito fragments, branch / end points, puncta) get their
  cell and the 등거리 띠 band of their position; band rows count and average
  the objects inside the band (MiNA lengths for mitochondria).
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

import numpy as np

CATEGORIES = [
    # key, shown name, 점 하나 =, CSV file
    ('images', '이미지별', '이미지', 'integrated_images.csv'),
    ('cells', '세포별', '세포', 'integrated_cells.csv'),
    ('cell_bands', '세포 × 띠별', '세포 × 띠', 'integrated_cell_bands.csv'),
    ('particles', '입자별', '입자', 'integrated_particles.csv'),
    ('mito', '미토 조각별', '미토 조각', 'integrated_mito_fragments.csv'),
    ('timepoints', '시점별', '시점', 'integrated_timepoints.csv'),
]
FEATURE = '통합 데이터'
# which 통합 데이터 tables each feature fills (data cards say so)
FEEDS = {'세포질 ROI': ('세포별', '이미지별'), '입자 ROI': ('입자별', '세포별', '세포 × 띠별', '이미지별'),
         '강도 측정': ('세포별', '이미지별'), '등거리 띠': ('세포 × 띠별',), 'Coloc 2': ('세포별', '이미지별'),
         'mitoROI': ('미토 조각별', '세포 × 띠별', '세포별', '이미지별'), '입자 추적': ('세포별', '시점별'),
         'FRAP': ('시점별', '이미지별')}


def feeds_text(feature: str) -> str:
    cats = FEEDS.get(feature)
    if not cats:
        return ''
    return (f'측정하면 통합 데이터의 {" · ".join(cats)} 표에 저절로 들어갑니다. 다시 재면 그 이미지의 '
            f'값만 바뀝니다.')
SEP = ' › '
KEYS = ('image', 'image_id', 'group', 'cell', 'band', 'particle', 'mito', 'frame', 'time_s')
# columns of the tab tables that are keys or bookkeeping, not values
SKIP = {'image', 'image_id', 'source', 'timepoint', 'plane', 'roi', 'status', 'region', 'particle_channel',
        'particle', 'band', 'intensity_roi', 'shape_outline', 'group', 'cell', 'mito', 'punctum', 'cell_id',
        'centroid_x', 'centroid_y', 'x_um', 'y_um', 'x_px', 'y_px', 'touches_border', 'weak_border_with'}


def table_name(cat_name: str) -> str:
    return f'통합 · {cat_name}'


def cell_no(v) -> int | None:
    """cell001 / cell01 / 3 / 'cell 3' -> 3."""
    if isinstance(v, (int, np.integer)):
        return int(v) if v > 0 else None
    m = re.search(r'(\d+)', str(v or ''))
    return int(m.group(1)) if m else None


def _num(v):
    if isinstance(v, (bool, np.bool_)):
        return float(v)
    if isinstance(v, (int, float, np.integer, np.floating)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mean(vals):
    v = [x for x in (_num(a) for a in vals) if x is not None and math.isfinite(x)]
    return float(np.mean(v)) if v else float('nan')


def _median(vals):
    v = [x for x in (_num(a) for a in vals) if x is not None and math.isfinite(x)]
    return float(np.median(v)) if v else float('nan')


class Integrator:
    """Builds the six tables from a MainWindow's results."""

    def __init__(self, win):
        self.win = win
        self._bands = {}  # image id -> (key, band map)

    # ---- positions -> band ------------------------------------------------------

    def band_map(self, it):
        """Band number (1..n) of every pixel of the image (0 outside), from the
        등거리 띠 tab's settings; None without nuclei."""
        from .radial import band_labels
        cells = it.cells
        if cells is None or not len(cells) or getattr(cells, 'nuclei', None) is None:
            return None
        try:
            s = self.win.bands_panel.band_settings()
        except Exception:  # noqa: BLE001
            return None
        key = (id(cells), int(cells.labels.max()), int(cells.labels.sum()), str(s), it.pixel_um)
        old = self._bands.get(it.image_id)
        if old is not None and old[0] == key:
            return old[1]
        b = band_labels(cells, it.pixel_um, s)
        self._bands[it.image_id] = (key, b)
        return b

    @staticmethod
    def _at(arr, x, y):
        if arr is None or x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
            return 0
        iy, ix = int(round(y)), int(round(x))
        if 0 <= iy < arr.shape[0] and 0 <= ix < arr.shape[1]:
            return int(arr[iy, ix])
        return 0

    # ---- helpers ----------------------------------------------------------------

    def _items(self):
        return {it.image_id: it for it in self.win.items}

    @staticmethod
    def _head(it):
        return {'image': it.label, 'image_id': it.image_id, 'group': it.group or ''}

    @staticmethod
    def _first_t(rows):
        """Cell values use one timepoint per image (the first measured)."""
        first = {}
        for r in rows:
            t = r.get('timepoint', 1)
            iid = r.get('image_id')
            if iid not in first or (_num(t) or 0) < (_num(first[iid]) or 0):
                first[iid] = t
        return [r for r in rows if r.get('timepoint', 1) == first.get(r.get('image_id'))]

    # ---- build ------------------------------------------------------------------

    def build(self) -> dict[str, list[dict]]:
        items = self._items()
        cells = defaultdict(dict)       # (image_id, cell) -> row
        bands = defaultdict(dict)       # (image_id, cell, band) -> row
        particles, frags, times = [], [], []
        w = self.win

        def cell_row(iid, c):
            r = cells[(iid, c)]
            if not r:
                it = items.get(iid)
                r.update({**(self._head(it) if it else {'image_id': iid}), 'cell': c})
            return r

        # measuring tabs (MeasureBox rows)
        boxes = [('세포질 ROI', w.roi_panel.measure), ('입자 ROI', w.particle_panel.measure),
                 ('강도 측정', w.intensity_panel.measure)]
        part_rows = []
        for feat, box in boxes:
            rows = list(box.batch_rows or [])
            if not rows:
                continue
            if box.suffix == 'particle_shape':
                part_rows = rows
                continue
            regions = {r.get('region') for r in rows if r.get('region')}
            for r in self._first_t(rows):
                c = cell_no(r.get('roi'))
                iid = r.get('image_id')
                if c is None or iid not in items:
                    continue
                reg = r.get('region') or ''
                pre = f'{feat}{SEP}' + (f'{reg} ' if reg and len(regions) > 1 else '')
                row = cell_row(iid, c)
                for k, v in r.items():
                    if k not in SKIP:
                        row[pre + k] = v

        # particles: one row each, with cell and band; counts per cell and band
        if part_rows:
            for r in self._first_t(part_rows):
                iid = r.get('image_id')
                it = items.get(iid)
                c = cell_no(r.get('roi'))
                if it is None:
                    continue
                cal = it.pixel_um or 1.0
                if r.get('x_um') not in (None, ''):
                    x, y = _num(r.get('x_um')), _num(r.get('y_um'))
                    x = x / cal - 0.5 if x is not None else None
                    y = y / cal - 0.5 if y is not None else None
                else:
                    x, y = _num(r.get('x_px')), _num(r.get('y_px'))
                    x = x - 0.5 if x is not None else None
                    y = y - 0.5 if y is not None else None
                b = self._at(self.band_map(it), x, y)
                row = {**self._head(it), 'cell': c or '', 'band': b or '', 'particle': r.get('particle', '')}
                for k, v in r.items():
                    if k not in SKIP:
                        row[f'입자 ROI{SEP}{k}'] = v
                particles.append(row)

        # Coloc 2 per cell (whole cell / cytosol / nucleus as the region)
        from .coloc_panel import SUMMARY
        for it in items.values():
            recs = it.coloc or []
            regions = {getattr(rc, 'region', '') for rc in recs}
            for rc in recs:
                if rc.t not in (0, None) and any(x.t == 0 for x in recs):
                    continue
                c = cell_no(rc.label) if rc.label else cell_no(rc.roi)
                if c is None:
                    continue
                reg = rc.region if len(regions) > 1 else ''
                row = cell_row(it.image_id, c)
                for short, name in SUMMARY:
                    v = rc.result.value(name, None)
                    if v is not None:
                        row[f'Coloc 2{SEP}' + (f'{reg} ' if reg else '') + short] = v

        # mitoROI: cells, fragments (with band), points / puncta per band
        for it in items.values():
            res = getattr(it, 'mito', None)
            if res is None:
                continue
            for r in res.cells:
                c = cell_no(r.get('cell'))
                if c is None:
                    continue
                row = cell_row(it.image_id, c)
                for k, v in r.items():
                    if k not in SKIP:
                        row[f'mitoROI{SEP}{k}'] = v
            bm = self.band_map(it)
            for r in res.mito:
                c = cell_no(r.get('cell'))
                b = self._at(bm, _num(r.get('centroid_x')), _num(r.get('centroid_y')))
                row = {**self._head(it), 'cell': c or '', 'band': b or '', 'mito': r.get('mito', '')}
                nb = _num(r.get('n_branches')) or 0
                row[f'mitoROI{SEP}network'] = 'network' if nb >= 2 else 'individual'
                for k, v in r.items():
                    if k not in SKIP:
                        row[f'mitoROI{SEP}{k}'] = v
                frags.append(row)

        # 세포 × 띠: the 등거리 띠 tab's rows, else the bands of the map
        brow = list(w.bands_panel.bands_measure.batch_rows or [])
        for r in self._first_t(brow):
            c, iid = cell_no(r.get('roi')), r.get('image_id')
            b = _num(r.get('band'))
            if c is None or iid not in items or b is None:
                continue
            row = bands[(iid, c, int(b))]
            row.update({**self._head(items[iid]), 'cell': c, 'band': int(b)})
            for k, v in r.items():
                if k not in SKIP:
                    row[f'등거리 띠{SEP}{k}'] = v
        need = {p['image_id'] for p in particles} | {f['image_id'] for f in frags}
        for iid in need:
            it = items[iid]
            bm = self.band_map(it)
            if bm is None:
                continue
            lab = it.cells.labels
            px2 = (it.pixel_um or 1.0) ** 2
            ok = bm > 0
            if not ok.any():
                continue
            idx = lab[ok].astype(np.int64) * 10000 + bm[ok]
            u, n = np.unique(idx, return_counts=True)
            for key, cnt in zip(u, n):
                c, b = int(key // 10000), int(key % 10000)
                row = bands[(iid, c, b)]
                if not row:
                    row.update({**self._head(it), 'cell': c, 'band': b})
                row['band_area_um2'] = float(cnt * px2)
        self._band_objects(items, bands, particles, frags)
        # no object in a band / cell of a measured image = 0, not empty
        p_img, m_img = {p['image_id'] for p in particles}, {f['image_id'] for f in frags}
        zero_p = [f'입자 ROI{SEP}입자 수', f'입자 ROI{SEP}입자 밀도 (/µm²)']
        zero_m = [f'mitoROI{SEP}{c}' for c in ('조각 수', 'networks', 'individuals', '조각 길이 합 (µm)',
                                               '미토 면적 합 (µm²)', '미토 밀도 (조각 /µm²)', '분기점 수',
                                               '끝점 수', '분기점 밀도 (/µm²)')]
        for (iid, _c, _b), row in bands.items():
            for cols, imgs in ((zero_p, p_img), (zero_m, m_img)):
                if iid in imgs:
                    for c in cols:
                        row.setdefault(c, 0)
            if iid in m_img and 'puncta' in (getattr(items[iid].mito, 'layers', None) or {}):
                row.setdefault(f'mitoROI{SEP}점 수', 0)

        # cells: particle counts, track summaries
        by_cell = defaultdict(list)
        for p in particles:
            if p['cell'] != '':
                by_cell[(p['image_id'], p['cell'])].append(p)
        for (iid, c), ps in by_cell.items():
            row = cell_row(iid, c)
            row[f'입자 ROI{SEP}입자 수'] = len(ps)
            row[f'입자 ROI{SEP}입자 면적 평균 (µm²)'] = _mean(p.get(f'입자 ROI{SEP}area_um2') for p in ps)
        for (iid, c), row in cells.items():
            if iid in p_img:
                row.setdefault(f'입자 ROI{SEP}입자 수', 0)
        tp = getattr(w, 'track_panel', None)
        for it in items.values():
            st = getattr(it, 'tracks', None)
            if tp is None or st is None or not st.points:
                continue
            try:
                summ = tp.summary_of(it)
            except Exception:  # noqa: BLE001
                summ = []
            acc = defaultdict(list)
            for s in summ:
                if s.get('main_cell_id'):
                    acc[int(s['main_cell_id'])].append(s)
            for c, ss in acc.items():
                row = cell_row(it.image_id, c)
                row[f'입자 추적{SEP}트랙 수'] = len(ss)
                row[f'입자 추적{SEP}mean_speed_um_min'] = _mean(s.get('mean_speed_um_min') for s in ss)
            from . import tracking as tk
            for r in tk.per_cell(st.points, st.ratio):
                times.append({**self._head(it), 'cell': r.get('cell_id', ''), 'frame': r.get('frame', ''),
                              'time_s': '', **{f'입자 추적{SEP}{k}': v for k, v in r.items()
                                               if k not in ('cell_id', 'frame')}})

        # FRAP: curve per image (시점별) and its fit (이미지별)
        frap_img = {}
        fp = getattr(w, 'frap_panel', None)
        for it in items.values():
            entry = getattr(fp, '_curves', {}).get(id(it)) if fp is not None else None
            if not entry:
                continue
            curve = entry[1]
            try:
                vals = np.asarray(curve.values(), float)
            except Exception:  # noqa: BLE001
                continue
            for i, (t, v) in enumerate(zip(np.asarray(curve.times, float), vals)):
                times.append({**self._head(it), 'cell': '', 'frame': i + 1, 'time_s': float(t),
                              f'FRAP{SEP}recovery': float(v)})
            f = curve.fit
            if f is not None and f.ok:
                frap_img[it.image_id] = {f'FRAP{SEP}mobile_fraction': f.mobile, f'FRAP{SEP}half_time_s': f.half_time,
                                         f'FRAP{SEP}fit_r2': f.r2}

        cell_rows = [cells[k] for k in sorted(cells, key=lambda k: (self._order(k[0]), k[1]))]
        band_rows = [bands[k] for k in sorted(bands, key=lambda k: (self._order(k[0]), k[1], k[2]))]
        images = self._images(items, cell_rows, particles, frap_img)
        return {'images': images, 'cells': cell_rows, 'cell_bands': band_rows,
                'particles': particles, 'mito': frags, 'timepoints': times}

    def _order(self, iid):
        ids = [it.image_id for it in self.win.items]
        return ids.index(iid) if iid in ids else len(ids)

    def _band_objects(self, items, bands, particles, frags):
        """Counts and means of the objects inside each cell's band (no new
        measurement: positions only)."""
        acc_p = defaultdict(list)
        for p in particles:
            if p['cell'] != '' and p['band'] != '':
                acc_p[(p['image_id'], p['cell'], p['band'])].append(p)
        for k, ps in acc_p.items():
            row = bands[k]
            if not row:
                row.update({**self._head(items[k[0]]), 'cell': k[1], 'band': k[2]})
            area = row.get('band_area_um2') or _num(row.get(f'등거리 띠{SEP}area_um2'))
            row[f'입자 ROI{SEP}입자 수'] = len(ps)
            row[f'입자 ROI{SEP}입자 밀도 (/µm²)'] = len(ps) / area if area else float('nan')
            row[f'입자 ROI{SEP}입자 면적 평균 (µm²)'] = _mean(p.get(f'입자 ROI{SEP}area_um2') for p in ps)
            for col in {c for p in ps for c in p if c.endswith('_Mean')}:
                row[col + ' (입자 평균)'] = _mean(p.get(col) for p in ps)
        acc_m = defaultdict(list)
        for f in frags:
            if f['cell'] != '' and f['band'] != '':
                acc_m[(f['image_id'], f['cell'], f['band'])].append(f)
        L, NB = f'mitoROI{SEP}length_um', f'mitoROI{SEP}n_branches'
        for k, fs in acc_m.items():
            row = bands[k]
            if not row:
                row.update({**self._head(items[k[0]]), 'cell': k[1], 'band': k[2]})
            area = row.get('band_area_um2') or _num(row.get(f'등거리 띠{SEP}area_um2'))
            lens = [_num(f.get(L)) or 0.0 for f in fs]
            nbs = [_num(f.get(NB)) or 0.0 for f in fs]
            m = f'mitoROI{SEP}'
            row[m + '조각 수'] = len(fs)
            row[m + 'networks'] = sum(1 for n in nbs if n >= 2)
            row[m + 'individuals'] = sum(1 for n in nbs if n < 2)
            row[m + '조각 길이 평균 (µm)'] = float(np.mean(lens)) if lens else float('nan')
            row[m + '조각 길이 중앙값 (µm)'] = float(np.median(lens)) if lens else float('nan')
            row[m + '조각 길이 합 (µm)'] = float(np.sum(lens))
            row[m + '가지 길이 평균 (µm)'] = float(np.sum(lens) / np.sum(nbs)) if np.sum(nbs) else float('nan')
            row[m + '조각당 가지 수 평균'] = float(np.mean(nbs)) if nbs else float('nan')
            row[m + '미토 면적 합 (µm²)'] = float(np.nansum([_num(f.get(m + 'area_um2')) or 0 for f in fs]))
            row[m + '미토 밀도 (조각 /µm²)'] = len(fs) / area if area else float('nan')
            g = [f.get(m + 'green_mean') for f in fs if f.get(m + 'green_mean') not in (None, '')]
            if g:
                row[m + 'green_mean (조각 평균)'] = _mean(g)
        # branch / end points and puncta of the mitoROI layers, by position
        from scipy import ndimage as ndi
        for it in items.values():
            res = getattr(it, 'mito', None)
            layers = getattr(res, 'layers', None) or {}
            bm = self.band_map(it) if res is not None else None
            if bm is None:
                continue
            lab = it.cells.labels
            for layer, col in (('junctions', '분기점 수'), ('ends', '끝점 수'), ('puncta', '점 수')):
                arr = layers.get(layer)
                if arr is None:
                    continue
                cc, n = ndi.label(np.asarray(arr) > 0, structure=np.ones((3, 3)))
                if not n:
                    continue
                cen = ndi.center_of_mass(np.ones_like(cc), cc, np.arange(1, n + 1))
                cnt = defaultdict(int)
                for (y, x) in cen:
                    c, b = self._at(lab, x, y), self._at(bm, x, y)
                    if c and b:
                        cnt[(c, b)] += 1
                for (c, b), v in cnt.items():
                    row = bands[(it.image_id, c, b)]
                    if not row:
                        row.update({**self._head(it), 'cell': c, 'band': b})
                    row[f'mitoROI{SEP}{col}'] = v
                    area = row.get('band_area_um2')
                    if area and layer == 'junctions':
                        row[f'mitoROI{SEP}분기점 밀도 (/µm²)'] = v / area

    def _images(self, items, cell_rows, particles, frap_img):
        """One row per image: number of cells, the mean over its cells of
        every numeric cell column, particle count, FRAP fit."""
        by = defaultdict(list)
        for r in cell_rows:
            by[r['image_id']].append(r)
        npart = defaultdict(int)
        for p in particles:
            npart[p['image_id']] += 1
        out = []
        for it in self.win.items:
            rows = by.get(it.image_id, [])
            if not rows and it.image_id not in frap_img and not npart.get(it.image_id):
                continue
            row = {**self._head(it), '세포 수': len(it.cells) if it.cells is not None else 0}
            cols = []
            for r in rows:
                cols += [c for c in r if SEP in c and c not in cols]
            for c in cols:
                vals = [_num(r.get(c)) for r in rows]
                vals = [v for v in vals if v is not None]
                if vals:
                    row[c + ' (세포 평균)'] = _mean(vals)
            if npart.get(it.image_id):
                row[f'입자 ROI{SEP}입자 수'] = npart[it.image_id]
            row.update(frap_img.get(it.image_id, {}))
            out.append(row)
        return out


def tables(win) -> list:
    """The six categories as graph `Table`s (empty ones left out), with the
    columns grouped by feature (column sets)."""
    from . import graph as G
    integ = getattr(win, '_integrator', None)
    if integ is None:
        integ = win._integrator = Integrator(win)
    data = integ.build()
    out = []
    for key, name, _unit, _csv in CATEGORIES:
        rows = data.get(key) or []
        if not rows:
            continue
        cols = [k for k in KEYS if any(k in r for r in rows)]
        t = G.Table.from_dicts(table_name(name), rows, columns=cols)
        sets = {}
        for c in t.columns:
            if SEP in c:
                sets.setdefault(c.split(SEP, 1)[0], []).append(c)
        t.column_sets = sets
        t.labels = {c: c.split(SEP, 1)[1] + f' ({c.split(SEP, 1)[0]})' for c in t.columns if SEP in c}
        t.key = key
        out.append(t)
    return out


def column_notes(t) -> list[dict]:
    """integrated_columns.csv: category, column, feature, source column, how."""
    out = []
    for c in t.columns:
        if SEP in c:
            feat, src = c.split(SEP, 1)
            how = ('세포 평균' if src.endswith('(세포 평균)') else '입자 평균' if src.endswith('(입자 평균)') else
                   '띠 안의 개수 · 평균 (위치)' if t.name.endswith('띠별') and feat in ('입자 ROI', 'mitoROI') else
                   '그대로')
        else:
            feat, src, how = '', c, '키'
        out.append({'table': t.name, 'column': c, 'feature': feat, 'source_column': src, 'how': how})
    return out


def write_csv(win, folder, image_ids=None) -> list[str]:
    """integrated_*.csv + integrated_columns.csv into the folder (only the
    rows of image_ids when given)."""
    import csv
    from pathlib import Path
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    files, notes = [], []
    names = {table_name(n): f for _k, n, _u, f in CATEGORIES}
    for t in tables(win):
        if image_ids is not None and 'image_id' in t.columns:
            i = t.columns.index('image_id')
            t.rows = [r for r in t.rows if r[i] in image_ids]
            if not t.rows:
                continue
        path = folder / names[t.name]
        with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
            wr = csv.writer(fh)
            wr.writerow(t.columns)
            for r in t.rows:
                wr.writerow(['' if (isinstance(v, float) and not math.isfinite(v)) else v for v in r])
        files.append(str(path))
        notes += column_notes(t)
    if files:
        path = folder / 'integrated_columns.csv'
        with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
            wr = csv.DictWriter(fh, ['table', 'column', 'feature', 'source_column', 'how'])
            wr.writeheader()
            wr.writerows(notes)
        files.append(str(path))
    return files
