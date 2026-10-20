"""User-named image groups and summaries of measurement rows per image and
per group (n, mean, SD, min, max of every measured parameter)."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

GROUP_FILE = 'image_groups.csv'  # image -> group, saved with measurements, read on folder load
UNGROUPED = 'ungrouped'


def _number(v):
    if isinstance(v, bool) or not isinstance(v, (int, float, np.integer, np.floating)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def summary_params(rows) -> list[str]:
    """Numeric columns worth summarising: not the time point, the position of
    a particle or an angle (a mean of those means nothing)."""
    params = []
    for r in rows:
        for k, v in r.items():
            if k in params or k == 'timepoint' or k.startswith(('x_', 'y_')) or k.endswith('angle'):
                continue
            if _number(v) is not None:
                params.append(k)
    return params


def summarize(rows, by_image: bool) -> list[dict]:
    """Long table: one row per (group[, image][, region]) and parameter with
    n (rows that have the value: particles or cells), mean, SD (n - 1), min
    and max. Per-cell particle rows keep their regions apart."""
    keys = ['group'] + (['image', 'image_id'] if by_image else [])
    if any('region' in r for r in rows):
        keys.append('region')
    params = summary_params(rows)
    sets: dict[tuple, list[dict]] = {}
    for r in rows:
        k = tuple((r.get(c) or UNGROUPED) if c == 'group' else r.get(c, '') for c in keys)
        sets.setdefault(k, []).append(r)
    out = []
    for k, rs in sets.items():
        n_img = len({r.get('image_id') or r.get('image') for r in rs})
        for p in params:
            v = np.array([x for x in (_number(r.get(p)) for r in rs) if x is not None])
            row = dict(zip(keys, k))
            if not by_image:
                row['n_images'] = n_img
            row.update(parameter=p, n=len(v),
                       mean=round(float(v.mean()), 6) if len(v) else '',
                       sd=round(float(v.std(ddof=1)), 6) if len(v) > 1 else '',
                       min=round(float(v.min()), 6) if len(v) else '',
                       max=round(float(v.max()), 6) if len(v) else '')
            out.append(row)
    return out


def write_groups(path, items) -> bool:
    """image_groups.csv of every image with a group; nothing when none has one."""
    rows = [(it.label, it.image_id, it.group) for it in items if it.group]
    if not rows:
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['image', 'image_id', 'group'])
        w.writerows(rows)
    return True


def read_groups(path) -> list[tuple[str, str, str]]:
    """(image, image_id, group) rows of an image_groups.csv."""
    with open(path, newline='', encoding='utf-8-sig') as f:
        return [(r.get('image', ''), r.get('image_id', ''), r.get('group', '').strip())
                for r in csv.DictReader(f) if r.get('group', '').strip()]


def apply_groups(items, rows) -> int:
    """Give images without a group the group saved for them (by image ID,
    else by name). Returns how many got one."""
    n = 0
    for name, iid, group in rows:
        for it in items:
            if not it.group and ((iid and it.image_id == iid) or (not iid and it.label == name)):
                it.group = group
                n += 1
    return n
