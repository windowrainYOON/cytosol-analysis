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
print('done')
