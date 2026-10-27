"""Project files (.cyproj): everything set or measured in a session, so
opening the project brings the work back.

A project is a zip file:

* ``project.json``: the images (path relative to the project file and the
  absolute path; how each was read), per image its LUTs, crops, group, Z /
  timepoint, profile line, channel roles and particle settings; the settings
  of every tab, which tabs are open, the all-image measurement tables, the
  figure layout and the work log.
* ``images/<n>/cells.npz``: cell and nucleus label images (exact, with the
  detection's saturation / thresholds), ``particles.zip`` (particles loaded
  as fixed outlines), ``bleach_rois.zip`` (loaded bleach regions),
  ``coloc.pkl`` (Coloc 2 results), ``figure/<r>_<c>.npy`` (external figure images).

The image files themselves are not copied: only where they are.
"""

from __future__ import annotations

import io
import json
import os
import pickle
import tempfile
import zipfile
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

import numpy as np

FORMAT = 'cytosol-viewer-project'
VERSION = 1
EXT = '.cyproj'


def is_project_file(path) -> bool:
    path = Path(path)
    if path.suffix.lower() != EXT:
        return False
    try:
        with zipfile.ZipFile(path) as z:
            return 'project.json' in z.namelist()
    except Exception:
        return False


def _default(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, (set, frozenset)):
        return list(o)
    return str(o)


def dumps(obj) -> str:
    return json.dumps(obj, default=_default, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------------------
# widget settings of a panel
# ---------------------------------------------------------------------------


def _leaf_state(w):
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                                   QComboBox, QGroupBox, QLineEdit, QTabWidget)

    if isinstance(w, QAction):
        return {'checked': w.isChecked()} if w.isCheckable() else None
    if isinstance(w, QComboBox):
        data = w.currentData()
        if not isinstance(data, (str, int, float, bool)) and data is not None:
            data = None
        return {'index': w.currentIndex(), 'text': w.currentText(), 'data': data}
    if isinstance(w, QLineEdit):
        return {'text': w.text()}
    if isinstance(w, QTabWidget):  # sub-tabs such as 자동 / 수동
        return {'tab': w.currentIndex()}
    if isinstance(w, (QAbstractSpinBox, QAbstractSlider)) and hasattr(w, 'value'):
        return {'value': w.value()}
    if isinstance(w, QGroupBox):
        return {'checked': w.isChecked()} if w.isCheckable() else None
    if hasattr(w, 'rgb') and hasattr(w, 'set_rgb'):  # marker color buttons
        return {'rgb': list(w.rgb)}
    if isinstance(w, QAbstractButton):
        return {'checked': w.isChecked(), 'radio': w.autoExclusive()} if w.isCheckable() else None
    return None


def widget_state(obj, skip=()) -> dict:
    """Settings of the widgets an object holds as attributes (and in dicts of
    them, one or two levels deep), keyed by attribute name."""
    out = {}
    for name, w in vars(obj).items():
        if name in skip or name.startswith('_'):
            continue
        if isinstance(w, dict):
            sub = {}
            for k, v in w.items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        st = _leaf_state(v2)
                        if st is not None:
                            sub[f'{k}.{k2}'] = st
                else:
                    st = _leaf_state(v)
                    if st is not None:
                        sub[str(k)] = st
            if sub:
                out[name] = {'items': sub}
        else:
            st = _leaf_state(w)
            if st is not None:
                out[name] = st
    return out


def _set_leaf(w, st):
    from PySide6.QtWidgets import QComboBox, QLineEdit

    if 'rgb' in st:
        w.set_rgb(st['rgb'])
        if hasattr(w, 'changed'):
            w.changed.emit()
    elif 'checked' in st:
        if st.get('radio') and not st['checked']:
            return  # the checked button of the group sets it
        w.setChecked(bool(st['checked']))
    elif isinstance(w, QComboBox):
        i = w.findData(st.get('data')) if st.get('data') is not None else -1
        if i < 0:
            i = w.findText(st.get('text', ''))
        if i < 0 and 0 <= st.get('index', -1) < w.count():
            i = st['index']
        if i >= 0:
            w.setCurrentIndex(i)
    elif isinstance(w, QLineEdit):
        w.setText(st.get('text', ''))
    elif 'tab' in st:
        if 0 <= st['tab'] < w.count():
            w.setCurrentIndex(st['tab'])
    elif 'value' in st:
        w.setValue(type(w.value())(st['value']))


def restore_widgets(obj, state: dict) -> list[str]:
    """Put saved settings back; returns the ones that could not be set."""
    failed = []
    attrs = vars(obj)
    jobs = []
    for name, st in (state or {}).items():
        w = attrs.get(name)
        if w is None:
            continue
        if 'items' in st and isinstance(w, dict):
            for key, leaf in st['items'].items():
                k, _, k2 = key.partition('.')
                target = w.get(k) if k in w else w.get(_int(k))
                if k2 and isinstance(target, dict):
                    target = target.get(k2)
                if target is not None:
                    jobs.append((f'{name}.{key}', target, leaf))
        else:
            jobs.append((name, w, st))
    # spin boxes before the switches that read them; checked radios last
    jobs.sort(key=lambda j: ('checked' in j[2], bool(j[2].get('radio'))))
    for name, w, st in jobs:
        try:
            _set_leaf(w, st)
        except Exception:
            failed.append(name)
    return failed


def _int(k):
    try:
        return int(k)
    except ValueError:
        return k


# ---------------------------------------------------------------------------
# per-image data
# ---------------------------------------------------------------------------


def cells_bytes(cells) -> tuple[bytes, dict]:
    buf = io.BytesIO()
    arrays = {'labels': cells.labels}
    if cells.nuclei is not None:
        arrays['nuclei'] = cells.nuclei
    np.savez_compressed(buf, **arrays)
    meta = {'px_um': cells.px_um, 'status': {str(k): v for k, v in cells.status.items()},
            'saturation': cells.saturation, 'nuc_threshold': cells.nuc_threshold,
            'cell_threshold': cells.cell_threshold,
            'nuc_thr': {str(k): [t, auto] for k, (t, auto) in cells.nuc_thr.items()}}
    return buf.getvalue(), meta


def cells_from(data: bytes, meta: dict):
    from .cellroi import CellRois

    z = np.load(io.BytesIO(data))
    nuc = z['nuclei'] if 'nuclei' in z.files else None
    return CellRois(z['labels'].astype(np.int32), None if nuc is None else nuc.astype(np.int32),
                    meta.get('px_um'), {int(k): v for k, v in (meta.get('status') or {}).items()},
                    meta.get('saturation'), meta.get('nuc_threshold'), meta.get('cell_threshold'),
                    {int(k): (v[0], bool(v[1])) for k, v in (meta.get('nuc_thr') or {}).items()})


def _rel(path: Path, base: Path) -> str:
    try:
        return os.path.relpath(path, base)
    except ValueError:  # another drive (Windows)
        return str(path)


def image_entry(it, base: Path) -> dict:
    p = Path(it.path).resolve()
    return {
        'path': _rel(p, base),
        'abs_path': str(p),
        'name': p.name,
        'label': it.label,
        'id_suffix': it.id_suffix,
        'image_id': it.image_id,
        'source_name': it.source_name,
        'load': dict(it.load_kwargs),
        'z': it.z,
        't': it.t,
        'luts': [lut.to_dict() for lut in it.luts],
        'crops': [list(map(int, c)) for c in it.crops],
        'group': it.group,
        'profile_line': list(it.profile_line) if it.profile_line is not None else None,
        'roi_roles': dict(it.roi_roles),
        'particle_settings': asdict(it.particle_settings) if it.particle_settings is not None
        else None,
        'linked': [_rel(Path(f).resolve(), base) for f in it.linked],
    }


def resolve_image(entry: dict, base: Path, search_dirs=()) -> Path | None:
    """Where an image is now: next to the project as before, at its old
    absolute path, or by name in a folder the user pointed to."""
    for cand in (base / entry['path'], Path(entry['abs_path'])):
        if cand.exists():
            return cand
    for d in search_dirs:
        direct = Path(d) / entry['name']
        if direct.exists():
            return direct
        for hit in Path(d).rglob(entry['name']):
            return hit
    return None


# ---------------------------------------------------------------------------
# figure layout
# ---------------------------------------------------------------------------


def figure_dict(spec, items, files: dict) -> dict:
    """The figure table; external images go to files[name] = array."""
    index = {id(it): i for i, it in enumerate(items)}
    cells = []
    for r, row in enumerate(spec.cells):
        out_row = []
        for c, cell in enumerate(row):
            d = {'item': index.get(id(cell.item)) if cell.item is not None else None,
                 'region': list(cell.region) if cell.region is not None else None,
                 'channels': cell.channels, 'name': cell.name,
                 'rgb_pixel_um': cell.rgb_pixel_um,
                 'insets': [asdict(i) for i in cell.insets], 'rgb': None,
                 'zoom_src': None, 'zoom_inset': None}
            if cell.rgb is not None:
                d['rgb'] = f'figure/{r}_{c}.npy'
                files[d['rgb']] = np.asarray(cell.rgb, np.float32)
            if cell.zoom_src is not None:
                pos = spec.find(cell.zoom_src)
                if pos is not None:
                    d['zoom_src'] = list(pos)
                    src = cell.zoom_src
                    d['zoom_inset'] = next((k for k, i in enumerate(src.insets)
                                            if i is cell.zoom_inset), None)
            out_row.append(d)
        cells.append(out_row)
    other = {f.name: getattr(spec, f.name) for f in fields(spec)
             if f.name not in ('rows', 'cols', 'cells')}
    return {'rows': [asdict(l) for l in spec.rows], 'cols': [asdict(l) for l in spec.cols],
            'cells': cells, 'settings': other}


def figure_from(spec, d: dict, items, read):
    """Fill spec from figure_dict output; read(name) -> bytes of a zip entry."""
    from .figure import FigureCell, Inset, Label

    def label(x):
        return Label(x.get('text', ''), tuple(x['color']) if x.get('color') else None)

    spec.rows = [label(x) for x in d.get('rows', [])] or spec.rows
    spec.cols = [label(x) for x in d.get('cols', [])] or spec.cols
    grid = []
    for row in d.get('cells', []):
        out = []
        for c in row:
            cell = FigureCell()
            i = c.get('item')
            if i is not None and 0 <= i < len(items) and items[i] is not None:
                cell.item = items[i]
            cell.region = tuple(c['region']) if c.get('region') else None
            cell.channels = c.get('channels')
            cell.name = c.get('name', '')
            cell.rgb_pixel_um = c.get('rgb_pixel_um')
            if c.get('rgb'):
                try:
                    cell.rgb = np.load(io.BytesIO(read(c['rgb'])))
                except Exception:
                    cell.rgb = None
            cell.insets = [Inset(tuple(x['rect']), x.get('corner', 'upper left'),
                                 x.get('size', 0.45), x.get('placement', 'inside'),
                                 tuple(x.get('offset', (0, 1)))) for x in c.get('insets', [])]
            out.append(cell)
        grid.append(out)
    for r, row in enumerate(d.get('cells', [])):
        for c, cd in enumerate(row):
            pos, k = cd.get('zoom_src'), cd.get('zoom_inset')
            if pos is None or k is None:
                continue
            try:
                src = grid[pos[0]][pos[1]]
                grid[r][c].zoom_src, grid[r][c].zoom_inset = src, src.insets[k]
            except (IndexError, TypeError):
                pass
    if grid and len(grid) == len(spec.rows) and all(len(r) == len(spec.cols) for r in grid):
        spec.cells = grid
    for k, v in (d.get('settings') or {}).items():
        if hasattr(spec, k):
            setattr(spec, k, tuple(v) if isinstance(v, list) else v)


# ---------------------------------------------------------------------------
# writing / reading
# ---------------------------------------------------------------------------


def write_project(path, data: dict, files: dict):
    """data -> project.json; files: zip name -> bytes, ndarray (.npy) or a
    path on disk. Written next to the target first, then moved in place."""
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json', dumps(data))
        for name, v in files.items():
            if isinstance(v, np.ndarray):
                buf = io.BytesIO()
                np.save(buf, v)
                z.writestr(name, buf.getvalue())
            elif isinstance(v, (bytes, bytearray)):
                z.writestr(name, bytes(v))
            else:
                z.write(v, name)
    os.replace(tmp, path)


def read_project(path) -> tuple[dict, dict]:
    """(project.json content, {zip name: bytes})."""
    with zipfile.ZipFile(path) as z:
        data = json.loads(z.read('project.json').decode('utf-8'))
        if data.get('format') != FORMAT:
            raise ValueError('Cytosol Viewer 프로젝트 파일이 아닙니다.')
        files = {n: z.read(n) for n in z.namelist() if n != 'project.json'}
    return data, files


def header() -> dict:
    from .version import __version__

    return {'format': FORMAT, 'version': VERSION, 'app_version': __version__,
            'saved': datetime.now().isoformat(timespec='seconds')}


def item_files(it, n: int, panel_particles, files: dict, tmpdir: Path) -> dict:
    """Binary per-image data into files; returns the names used."""
    names = {}
    pre = f'images/{n}/'
    if it.cells is not None and len(it.cells):
        data, meta = cells_bytes(it.cells)
        files[pre + 'cells.npz'] = data
        names['cells'] = pre + 'cells.npz'
        names['cells_meta'] = meta
    if it.particle_settings is None and it.particles is not None and it.particles.mask.any():
        from .intensity import save_particles

        cells = panel_particles(it)
        if cells is not None:
            f = tmpdir / f'{n}_particles.zip'
            save_particles(f, cells, it.particles, it.id_properties())
            files[pre + 'particles.zip'] = f.read_bytes()
            names['particles'] = pre + 'particles.zip'
    if it._bleach is not None and it._bleach:
        from .imageinfo import save_bleach_rois

        f = tmpdir / f'{n}_bleach.zip'
        save_bleach_rois(f, it._bleach, it.id_properties())
        files[pre + 'bleach_rois.zip'] = f.read_bytes()
        names['bleach'] = pre + 'bleach_rois.zip'
    if it.coloc:
        try:
            files[pre + 'coloc.pkl'] = pickle.dumps(it.coloc)
            names['coloc'] = pre + 'coloc.pkl'
        except Exception:
            pass
    return names


def restore_item_files(it, names: dict, files: dict, tmpdir: Path, notes: list):
    if names.get('cells') in files:
        try:
            it.cells = cells_from(files[names['cells']], names.get('cells_meta') or {})
        except Exception as exc:
            notes.append(f'{it.label}: 세포 ROI 복원 실패 ({exc})')
    if names.get('particles') in files:
        from .intensity import load_particles

        f = tmpdir / f'{id(it)}_particles.zip'
        f.write_bytes(files[names['particles']])
        try:
            p, s = load_particles(f, it.image.shape[-2:])
            it.particles = p if s is None else None
            it.particle_settings = s if s is not None else it.particle_settings
        except Exception as exc:
            notes.append(f'{it.label}: 입자 ROI 복원 실패 ({exc})')
    if names.get('bleach') in files:
        from .imageinfo import load_bleach_rois

        f = tmpdir / f'{id(it)}_bleach.zip'
        f.write_bytes(files[names['bleach']])
        try:
            it.bleach_rois = load_bleach_rois(f)
        except Exception as exc:
            notes.append(f'{it.label}: bleach ROI 복원 실패 ({exc})')
    if names.get('coloc') in files:
        try:
            it.coloc = pickle.loads(files[names['coloc']])
        except Exception as exc:
            notes.append(f'{it.label}: Coloc 2 결과 복원 실패 ({exc})')


def temp_dir():
    return tempfile.TemporaryDirectory(prefix='cyproj_')
