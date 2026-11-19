"""ParticleTracker 통합 분석 + 특이 입자 on the Cytosol Viewer result folders (ParticleTracker's own code).

usage: <particle-tracking>/.venv/bin/python -I scripts/track_pt_risefall.py PT_REPO ROOT OUT [green_ids_csv] [label]
(scripts/batch_folder.py runs it at the end of a 입자 추적 batch when the ParticleTracker repo is found)
A) as ParticleTracker: groups inside / outside
B) with the green split: long tracks of green_ids = 'inside' slot (shown as 신호 있음), other long tracks = 'outside'."""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
sys.argv = sys.argv[1:]
import pandas as pd  # noqa: E402

from ptracker import plots  # noqa: E402
from ptracker.config import Config  # noqa: E402
from ptracker.pipeline import combine_and_plot, run_risefall  # noqa: E402

root, out = Path(sys.argv[1]), Path(sys.argv[2])
dirs = {}
for pt in sorted(root.glob('*_*/*_ParticleTracker')):
    if pt.name.startswith('._') or pt.parent.name.startswith('._'):
        continue
    if (pt / 'tracks_points_A_B_HT.csv').exists():
        dirs[pt.parent.name.split('.A1.')[-1].split('_')[0]] = pt
cfg = Config()
print('datasets', list(dirs))
import os  # noqa: E402
if os.environ.get('SKIP_A'):
    pts = pd.read_csv(out / 'A 세포 안·밖 (ParticleTracker 그대로)' / 'combined' / 'combined_tracks_points_A_B_HT.csv')
else:
    pts = combine_and_plot(dirs, out / 'A 세포 안·밖 (ParticleTracker 그대로)' / 'combined', cfg)
    run_risefall(pts, cfg, out / 'A 세포 안·밖 (ParticleTracker 그대로)' / 'risefall', dirs=dirs)

if len(sys.argv) > 3:
    gid = set(pd.read_csv(sys.argv[3]).track_id)
    allp = pd.read_csv(Path(sys.argv[3]).with_name('all_tracks_points_A_B_HT.csv'),
                       usecols=['dataset', 'track_id', 'track_id_image'])
    allp = allp[allp.track_id.isin(gid)].drop_duplicates('track_id')
    green = set(zip(allp.dataset, allp.track_id_image.astype(int)))
    print('green tracks', len(green))
    p = pts.copy()
    long_ = p.group.isin(['inside', 'outside'])
    is_g = [(d, int(t)) in green for d, t in zip(p.dataset, p.track_id)]
    p.loc[long_, 'group'] = ['inside' if g else 'outside' for g, l in zip(is_g, long_) if l]
    plots.GNAME.update({'inside': '신호 있음', 'outside': '신호 없음'})
    o = out / f"B 신호 있음·없음 ({sys.argv[4] if len(sys.argv) > 4 else 'green'})"
    (o / 'combined').mkdir(parents=True, exist_ok=True)
    p.to_csv(o / 'combined' / 'combined_tracks_points_A_B_HT_signal_groups.csv', index=False)
    lp = p[p.group.isin(['inside', 'outside'])]
    plots.ratio_figures(lp, str(o / 'combined'), 'combined_', idcol='track_uid')
    plots.per_dataset_medians(lp, str(o / 'combined' / 'combined_per_dataset_medians.png'))
    run_risefall(p, cfg, o / 'risefall', dirs=dirs)


# ---- 크롭 영상 + 곡선 (ParticleTracker 특이 입자 탭의 '크롭 영상 + 그래프'), every kept particle -------------------
def crops(pts, rdir, out_dir, cfg, dirs):
    """make_crop() for each kept track, loading each dataset once."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    from ptracker import movies, registration
    from ptracker.io_utils import DatasetSpec, load_dataset
    R = pd.read_csv(rdir / 'risefall_classification_all_tracks.csv')
    kept = R[R.keep]
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for ds, rows in kept.groupby('dataset'):
        spec = DatasetSpec.load(Path(dirs[ds]) / 'dataset.json')
        A, B, HT = load_dataset(spec)
        reg = pd.read_csv(Path(dirs[ds]) / 'registration.csv')
        Bal = registration.align_b(B, reg)
        for _, r in rows.iterrows():
            u = r.track_uid
            t = pts[pts.track_uid == u]
            safe = u.replace('::', '_').replace('/', '_')
            cat = plots.CNAME.get(getattr(r, 'category', ''), '')
            info = f"{ds} | {u.split('::')[-1]} | {plots.GNAME.get(t.group.iloc[0], t.group.iloc[0])} {cat}"
            if (out_dir / f'trace_{safe}.png').exists():
                n += 1
                continue
            try:   # as ParticleTracker's crops task: one failure does not stop the rest
                movies.crop_movie(A, Bal, HT, t, HT.shape[1] / A.shape[1], str(out_dir / f'crop_{safe}'), info, r,
                                  cfg.output.crop_half, cfg.output.movie_fps, {})
            except Exception as e:  # noqa: BLE001
                print('crop failed', u, e, flush=True)
            fig, ax = plt.subplots(figsize=(9, 4))
            plots.track_trace(ax, t, r, show_channels=True)
            ax.set_title(info)
            fig.savefig(out_dir / f'trace_{safe}.png', dpi=110, bbox_inches='tight')
            plt.close(fig)
            n += 1
        print('crops', ds, len(rows), flush=True)
        del A, B, HT, Bal
    return n


if not os.environ.get('NO_CROPS'):
    if len(sys.argv) > 3:
        cp, crd = p, o / 'risefall'
    else:
        cp, crd = pts, out / 'A 세포 안·밖 (ParticleTracker 그대로)' / 'risefall'
    print('crop movies', crops(cp, crd, out / '크롭 영상 (선별 입자)', cfg, dirs))
print('done')
