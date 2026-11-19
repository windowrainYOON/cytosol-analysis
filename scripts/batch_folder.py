"""Headless 일괄 분석 of a data folder with the app's own code (no window).

usage:
  python scripts/batch_folder.py FOLDER [--glob '*.TCF'] [--match T001P]
         [--steps track] [--out NAME] [--no-movies] [--pt-ref CH1] [--pt-measure CH0]
         [--settings batch_settings.json] [--list]

Finds image files under FOLDER (recursive glob), opens them as the app would,
runs the batch steps (cytosol/batch.py STEPS keys: cells, particles,
roi_measure, particle_measure, intensity, bands, coloc, frap, track, mito)
one image at a time with each tab's default settings (or a batch settings
JSON saved from the app), and writes into FOLDER/OUT:
  - per image folder <stem>_<ID>: the export kinds of those steps (export
    window defaults; for 입자 추적 also the ParticleTracker result folder with
    graphs and, unless --no-movies, its MP4s)
  - project.cyproj (rewritten after every image, so a crash keeps the rest),
    combined tables, batch/ results + settings, work_log.csv, run_log.txt
Prints one line per image: '[k/n] label OK|FAIL ...'.  Use scripts/run_batch_bg.sh
to run it in the background with caffeinate and the CW Data mount check."""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

EXTS = ('*.TCF', '*.tcf', '*.czi', '*.oir')
KIND_OF = {'cells': 'roi', 'roi_measure': 'roi', 'particles': 'particle', 'particle_measure': 'particle',
           'intensity': 'intensity', 'bands': 'bands', 'coloc': 'coloc', 'frap': 'frap',
           'track': 'track', 'mito': 'mito'}


def find_files(folder: Path, globs, match, out_dir):
    seen, files = set(), []
    for g in globs:
        for f in sorted(folder.rglob(g)):
            if f in seen or out_dir in f.parents or any(p.name.startswith('.') for p in f.parents):
                continue
            if match and not any(m in f.name for m in match):
                continue
            seen.add(f)
            files.append(f)
    return sorted(files)


def kind_defaults(kinds) -> dict:
    from cytosol.export_dialog import KINDS
    opts = {}
    for k in kinds:
        for sec in KINDS[k][1]:
            rows = sec[1] if isinstance(sec, tuple) and len(sec) > 1 and isinstance(sec[1], list) else [sec]
            for o in rows:
                if isinstance(o, tuple) and isinstance(o[0], str):
                    opts[o[0]] = bool(o[-1])
    return opts


def pick(combo, name, by_text=False):
    for k in range(combo.count()):
        v = combo.itemText(k).split(': ', 1)[-1] if by_text else str(combo.itemData(k) or '')
        if v.startswith(name):
            combo.setCurrentIndex(k)
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder', type=Path)
    ap.add_argument('--glob', action='append', help='file pattern(s), default TCF/CZI/OIR')
    ap.add_argument('--match', action='append', help='keep files whose name contains this (repeatable)')
    ap.add_argument('--steps', default='track', help='comma list of batch steps')
    ap.add_argument('--out', default='', help='output folder name inside FOLDER')
    ap.add_argument('--no-movies', action='store_true')
    ap.add_argument('--pt-ref', default='CH1', help='입자 추적 reference / particle channel')
    ap.add_argument('--pt-measure', default='CH0')
    ap.add_argument('--settings', type=Path, help='batch settings JSON from the app (tab settings)')
    ap.add_argument('--list', action='store_true', help='only list the files')
    a = ap.parse_args()

    steps = [s.strip() for s in a.steps.split(',') if s.strip()]
    out = a.folder / (a.out or f"CytosolViewer {'+'.join(steps)} {time.strftime('%y%m%d-%H%M')}")
    files = find_files(a.folder, a.glob or EXTS, a.match, out)
    print(f'{len(files)} files in {a.folder}', flush=True)
    for f in files:
        print('  ', f.relative_to(a.folder), flush=True)
    if a.list or not files:
        return 0
    out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtWidgets import QApplication, QMessageBox
    QMessageBox.information = staticmethod(lambda *x, **k: print('INFO:', x[1:3], flush=True))
    QMessageBox.warning = staticmethod(lambda *x, **k: print('WARN:', x[1:3], flush=True))
    from cytosol import batch, exporter
    from cytosol.app import MainWindow

    app = QApplication.instance() or QApplication([sys.argv[0]])
    win = MainWindow()
    win.import_paths(files)
    app.processEvents()
    if a.settings:
        win.load_batch_settings(a.settings)
    items = list(win.items)
    tp, pp = win.track_panel, win.particle_panel
    if 'track' in steps:
        tp.pt_engine.setChecked(True)
        tp.z_proj.setChecked(True)
        tp.z_method.setCurrentIndex(max(tp.z_method.findData('mip'), 0))
        pick(pp.part_channel, a.pt_ref, by_text=True)
        pick(tp.ratio_b, a.pt_measure)
        pick(tp.ratio_a, a.pt_ref)
        if items:
            print('track: PT engine', tp.uses_pt(items[0]), 'ref/measure', tp.pt_channels(items[0]), flush=True)

    st = win.batch
    st.steps = [k for k, *_ in batch.STEPS if k in steps]
    st.groups = sorted({batch.group_key(it) for it in items})
    st.redo = True
    kinds = sorted({KIND_OF[s] for s in st.steps if s in KIND_OF})
    per = kind_defaults(kinds)
    per = {k: v for k, v in per.items() if k != 'track_all' and k != 'mito_all'}
    if 'track' in steps:
        per['track_ptmovie'] = not a.no_movies
    per.update(per_image=True, info_csv=True, graph_format='png')

    done, t_all = [], time.perf_counter()
    for n, it in enumerate(items, 1):
        t0 = time.perf_counter()
        try:
            errs = batch.run(win, st, [it])
            r = exporter.run(win, [it], out, per)
            ok = not errs and not r.errors
            done.append(it.label)
            print(f'[{n}/{len(items)}] {it.label} {"OK" if ok else "WARN"} {st.results.get(it.label)} '
                  f'files {len(r.files)} {time.perf_counter() - t0:.0f}s'
                  + (f' errors {errs + r.errors}' if not ok else ''), flush=True)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            print(f'[{n}/{len(items)}] {it.label} FAIL {exc}', flush=True)
        st.images, st.ran_at = list(done), batch.stamp()
        try:
            win.write_project_to(out / 'project.cyproj')
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        it.image.release()

    final = {k: v for k, v in kind_defaults(kinds).items() if k in ('track_all', 'mito_all')}
    final.update(per_image=True, integrated_csv=True, batch_results=True, project=True, log=True)
    r = exporter.run(win, items, out, final)
    nfiles = sum(1 for _ in out.rglob('*') if _.is_file())
    print(f'DONE {len(done)}/{len(items)} images, {nfiles} files in {out} '
          f'({time.perf_counter() - t_all:.0f}s)' + (f' errors {r.errors}' if r.errors else ''), flush=True)
    win.set_dirty(False)
    os._exit(0)


if __name__ == '__main__':
    sys.exit(main())
