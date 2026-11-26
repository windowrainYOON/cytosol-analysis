"""Run a cytosol-pipe pipeline with a LUT preset used ONLY for image exports.

    .venv/bin/python scripts/pipe_lut_export.py "261118 TCF" <FOLDER> --lut <FOLDER>/lut_preset.json \
        [--out DIR] [--no-movies] [--images P01,P02]

- Detection, tracking and measurement run exactly as `cytosol.pipe run` (LUTs untouched).
- 입자 추적 › 5 신호 기준 keeps the stage's fixed threshold (signal_thr, e.g. 5) even while the
  preset (whose Min may be 0) is applied for the export.
- Image exports: the app-side image exports (3_이미지) are rendered with the preset LUTs, and
  ParticleTracker's MP4s (on by default here, as in the 2026-11-19 batch run) use the preset per
  role (reference / measure / RI). The item LUTs are restored before 통합데이터 / project.cyproj.
- The preset file and lut_roles.json are copied into the result folder.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pipeline')
    ap.add_argument('folder')
    ap.add_argument('--lut', required=True)
    ap.add_argument('--out')
    ap.add_argument('--images')
    ap.add_argument('--no-movies', action='store_true')
    a = ap.parse_args()
    lut_path = Path(a.lut).expanduser().resolve()

    from cytosol import exporter, pipe, pt_engine
    from cytosol import pipeline as P
    from cytosol import track_signal
    from cytosol.lut import load_preset
    from cytosol.ptcore import lut as plut
    from cytosol.ptcore import movies as mv
    from cytosol.ptcore.io_utils import RI_CHANNEL, make_source, split_source

    spec = P.PipelineSpec.load(a.pipeline) if Path(a.pipeline).exists() else pipe._spec(a.pipeline)
    thr = next((st['settings']['signal_thr'] for st in spec.stages
                if st['kind'] == 'track.particles' and (st.get('settings') or {}).get('signal_thr') is not None), None)
    print(f'LUT preset (exports only): {lut_path}; fixed signal threshold: {thr}', flush=True)

    # 1. movies on (export defaults otherwise)
    _def = P.default_export_opts

    def default_export_opts(kinds):
        o = _def(kinds)
        if 'track_ptmovie' in o and not a.no_movies:
            o['track_ptmovie'] = True
        return o
    P.default_export_opts = default_export_opts

    # 2. app-side image exports with the preset, threshold pinned
    _run = exporter.run
    _thr = track_signal.threshold_of

    def run(win, items, out, opts, progress=None):
        if Path(out).name != '3_이미지':
            return _run(win, items, out, opts, progress)
        saved = {id(it): list(it.luts) for it in items}
        n = load_preset(items, lut_path)
        print(f'LUT preset applied to {n} channels of {len(items)} images for 3_이미지', flush=True)
        if thr is not None:
            track_signal.threshold_of = lambda item, ch: float(thr)
        try:
            return _run(win, items, out, opts, progress)
        finally:
            track_signal.threshold_of = _thr
            for it in items:
                it.luts[:] = saved[id(it)]
    exporter.run = run

    # 3. ParticleTracker movies with the preset per role
    cur = {}
    _fm = pt_engine._figures_movies

    def _figures_movies(pt, arr, out, figures, movies, progress=None):
        path, _ = split_source(pt['sources']['reference'])
        cur['sources'] = {'reference': pt['sources']['reference'], 'measure': pt['sources']['measure'],
                          'ri': make_source(path, RI_CHANNEL)}
        cur['luts'] = None
        cur['out'] = out
        return _fm(pt, arr, out, figures, movies, progress)
    pt_engine._figures_movies = _figures_movies

    _cm = mv.channel_movie

    def channel_movie(stack, pts, path_noext, fl_coords, S, CID, reg, dt_min, title, *args, **kw):
        role = 'ri' if title.startswith('RI') else 'reference' if title.startswith('reference') else \
            'measure' if title.startswith('measure') else None
        if role and cur.get('sources') and kw.get('lut') is None:
            if cur['luts'] is None or role not in cur['luts']:
                luts = plut.role_luts(lut_path, {role: cur['sources'][role]}, {role: stack})
                cur['luts'] = {**(cur['luts'] or {}), **luts}
                plut.save_with_outputs(lut_path, cur['out'], cur['luts'])
            if role in cur['luts']:
                kw['lut'] = cur['luts'][role]
        return _cm(stack, pts, path_noext, fl_coords, S, CID, reg, dt_min, title, *args, **kw)
    mv.channel_movie = channel_movie

    argv = ['run', a.pipeline, a.folder]
    if a.out:
        argv += ['--out', a.out]
    if a.images:
        argv += ['--images', a.images]
    rc = pipe.main(argv)
    if a.out:
        shutil.copyfile(lut_path, Path(a.out) / 'lut_preset_used_for_exports.json')
    return rc


if __name__ == '__main__':
    sys.exit(main())
