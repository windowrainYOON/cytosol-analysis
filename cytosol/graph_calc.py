"""Correlation and regression calculations of the graph window (owner
request 2026-11-14, proposal mito-tracking ch. 6): the functions of Mito
Analyzer 1.8.0 `stats.py` (regression, Spearman, correlation matrices,
Fisher z difference, Cochran Q heterogeneity, Holm, why a value is undefined,
per-image means, the long group summary), unchanged, for any result table."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

METHODS = {'r': 'Pearson r', 'rho': 'Spearman ρ'}
CORRECTIONS = {'none': '없음', 'holm': 'Holm', 'fdr': 'FDR (Benjamini–Hochberg)'}
UNITS = {'rows': '행 그대로', 'image': '이미지 평균', 'group': '그룹 평균'}


def why_nan(x, y, xl='X', yl='Y'):
    """Why a regression / correlation of x and y is undefined ('' if it is defined)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    if n < 3:
        return f'n = {n}: 값이 3개 이상 있어야 합니다'
    for v, lab in ((x, xl), (y, yl)):
        if np.ptp(v[ok]) == 0:
            return f'{lab}의 값이 {n}개 모두 같습니다 ({v[ok][0]:.4g})'
    return ''


def spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    if n < 3 or np.ptp(x[ok]) == 0 or np.ptp(y[ok]) == 0:
        return math.nan, math.nan, n
    res = stats.spearmanr(x[ok], y[ok])
    return float(res.statistic), float(res.pvalue), n


def regression(x, y, through_origin=False):
    """Least-squares line y = slope * x + intercept with Pearson r, R² and the
    two-sided p of the slope.  `through_origin`: intercept fixed at 0."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    n = int(ok.sum())
    nan = dict(slope=math.nan, intercept=math.nan, r=math.nan, r2=math.nan, p=math.nan, n=n)
    if n < 3 or np.ptp(x[ok]) == 0 or np.ptp(y[ok]) == 0:
        return nan
    res = stats.linregress(x[ok], y[ok])
    out = dict(slope=float(res.slope), intercept=float(res.intercept), r=float(res.rvalue),
               r2=float(res.rvalue ** 2), p=float(res.pvalue), n=n)
    if through_origin:
        xo, yo = x[ok], y[ok]
        slope = float((xo * yo).sum() / (xo * xo).sum())
        resid = yo - slope * xo
        ss = float((yo * yo).sum())
        r2 = 1.0 - float((resid * resid).sum()) / ss if ss > 0 else math.nan
        se = math.sqrt(float((resid * resid).sum()) / (n - 1) / float((xo * xo).sum()))
        p = float(2 * stats.t.sf(abs(slope / se), n - 1)) if se > 0 else 0.0
        out.update(slope=slope, intercept=0.0, r2=r2, p=p)
    return out


def pair_stats(x, y):
    reg = regression(x, y)
    rho, p_s, _ = spearman(x, y)
    return dict(pearson_r=reg['r'], r2=reg['r2'], slope=reg['slope'], intercept=reg['intercept'],
                p_value=reg['p'], spearman_rho=rho, spearman_p=p_s, n=reg['n'], note=why_nan(x, y))


def corr_matrix(cols_x: dict, cols_y: dict, method='r'):
    """(len(ys), len(xs)) matrix of Pearson r ('r') or Spearman rho ('rho')
    and the n behind each value.  cols_*: {name: array}."""
    xs, ys = list(cols_x), list(cols_y)
    vals = np.full((len(ys), len(xs)), np.nan)
    ns = np.zeros(vals.shape, int)
    for j, xk in enumerate(xs):
        x = cols_x[xk]
        for i, yk in enumerate(ys):
            y = cols_y[yk]
            if method == 'r':
                reg = regression(x, y)
                vals[i, j], ns[i, j] = reg['r'], reg['n']
            else:
                vals[i, j], _, ns[i, j] = spearman(x, y)
    return vals, ns


def corr_p(vals, ns):
    """Two-sided p of each correlation (t test of r with n - 2 df)."""
    r = np.clip(np.asarray(vals, float), -0.999999, 0.999999)
    n = np.asarray(ns, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = r * np.sqrt((n - 2) / (1 - r * r))
    p = 2 * stats.t.sf(np.abs(t), np.maximum(n - 2, 1))
    return np.where((n > 2) & np.isfinite(r), p, np.nan)


def corr_diff_p(r1, n1, r2, n2):
    """Two-sided p that two independent correlations differ (Fisher z test); nan where not computable."""
    r1, r2 = np.clip(np.asarray(r1, float), -0.999999, 0.999999), np.clip(np.asarray(r2, float), -0.999999, 0.999999)
    n1, n2 = np.asarray(n1, float), np.asarray(n2, float)
    with np.errstate(divide='ignore', invalid='ignore'):
        se = np.sqrt(1 / (n1 - 3) + 1 / (n2 - 3))
        z = (np.arctanh(r2) - np.arctanh(r1)) / se
    p = 2 * stats.norm.sf(np.abs(z))
    return np.where((n1 > 3) & (n2 > 3), p, np.nan)


def corr_heterogeneity_p(vals, ns):
    """Cochran's Q test that k independent correlations (one matrix per group) are equal; per cell of the
    matrices. Groups with n <= 3 or a missing value are left out of that cell. nan where < 2 groups remain."""
    V = np.clip(np.asarray(vals, float), -0.999999, 0.999999)
    N = np.asarray(ns, float)
    ok = np.isfinite(V) & (N > 3)
    z = np.where(ok, np.arctanh(np.where(ok, V, 0)), 0)
    w = np.where(ok, N - 3, 0)
    sw = w.sum(0)
    with np.errstate(divide='ignore', invalid='ignore'):
        zbar = (w * z).sum(0) / sw
        q = (w * (z - zbar) ** 2).sum(0)
    df = ok.sum(0) - 1
    p = stats.chi2.sf(q, np.maximum(df, 1))
    return np.where(df >= 1, p, np.nan)


def holm(pvals):
    """Holm-Bonferroni adjusted p values (nan entries are ignored and stay nan)."""
    p = np.asarray(pvals, float)
    out = np.full(p.shape, np.nan)
    flat, of = p.ravel(), out.ravel()
    idx = [i for i in np.argsort(flat) if np.isfinite(flat[i])]
    m = len(idx)
    run = 0.0
    for r, i in enumerate(idx):
        run = max(run, min(1.0, (m - r) * flat[i]))
        of[i] = run
    return of.reshape(p.shape)


def fdr(pvals):
    """Benjamini-Hochberg adjusted p values (nan entries stay nan)."""
    p = np.asarray(pvals, float)
    flat = p.ravel()
    out = np.full(flat.shape, np.nan)
    idx = [i for i in np.argsort(flat) if np.isfinite(flat[i])]
    m = len(idx)
    run = 1.0
    for r in range(m - 1, -1, -1):
        i = idx[r]
        run = min(run, flat[i] * m / (r + 1))
        out[i] = min(run, 1.0)
    return out.reshape(p.shape)


def correct(pvals, how: str):
    if how == 'holm':
        return holm(pvals)
    if how == 'fdr':
        return fdr(pvals)
    return np.asarray(pvals, float)


def stars(p) -> str:
    if not np.isfinite(p):
        return ''
    return '**' if p < 0.01 else '*' if p < 0.05 else ''


def pair_test(a, b):
    """Welch t and Mann-Whitney U p values for two samples (nan if not computable)."""
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2 or np.ptp(np.concatenate([a, b])) == 0:
        return math.nan, math.nan
    return (float(stats.ttest_ind(a, b, equal_var=False).pvalue),
            float(stats.mannwhitneyu(a, b, alternative='two-sided').pvalue))


def describe(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    n = len(v)
    if not n:
        return dict(n=0, mean=math.nan, sd=math.nan, sem=math.nan, ci95=math.nan, median=math.nan,
                    q1=math.nan, q3=math.nan)
    sd = float(np.std(v, ddof=1)) if n > 1 else math.nan
    sem = sd / math.sqrt(n) if n > 1 else math.nan
    ci = float(stats.t.ppf(0.975, n - 1) * sem) if n > 1 else math.nan
    q1, med, q3 = np.percentile(v, [25, 50, 75])
    return dict(n=n, mean=float(v.mean()), sd=sd, sem=sem, ci95=ci, median=float(med), q1=float(q1),
                q3=float(q3))


def group_test(arrays):
    """Welch t + Mann-Whitney U for two groups, one-way ANOVA + Kruskal-Wallis
    for more. Returns (p_param, p_rank, name_param, name_rank)."""
    arrays = [np.asarray(a, float)[np.isfinite(a)] for a in arrays]
    arrays = [a for a in arrays if len(a)]
    two = len(arrays) == 2
    names = ('Welch t', 'Mann-Whitney U') if two else ('ANOVA', 'Kruskal-Wallis')
    if len(arrays) < 2 or any(len(a) < 2 for a in arrays):
        return math.nan, math.nan, *names
    allv = np.concatenate(arrays)
    if np.ptp(allv) == 0:
        return math.nan, math.nan, *names
    if two:
        p1 = stats.ttest_ind(*arrays, equal_var=False).pvalue
        p2 = stats.mannwhitneyu(*arrays, alternative='two-sided').pvalue
    else:
        p1 = stats.f_oneway(*arrays).pvalue
        p2 = stats.kruskal(*arrays).pvalue
    return float(p1), float(p2), *names


def group_summary_long(cols: dict, labels: list, groups: list, control=None) -> list[dict]:
    """One row per column × group: n, mean, SD, SEM, 95 % CI, median, IQR, the
    across-group tests and, with a `control`, each group vs the control
    (Welch, Mann-Whitney; Holm over the groups).  cols: {column: array},
    labels: the group of each row."""
    labels = [str(v) for v in labels]
    out = []
    for mk, vals in cols.items():
        vals = np.asarray(vals, float)
        arrays = {g: vals[[i for i, lab in enumerate(labels) if lab == g]] for g in groups}
        p1, p2, n1, n2 = group_test(list(arrays.values()))
        vs = {}
        if control in arrays:
            others = [g for g in groups if g != control]
            raw = [pair_test(arrays[g], arrays[control]) for g in others]
            adj_t, adj_u = holm([r[0] for r in raw]), holm([r[1] for r in raw])
            vs = {g: (raw[i][0], raw[i][1], adj_t[i], adj_u[i]) for i, g in enumerate(others)}
        for g in groups:
            d = dict(column=mk, group=g, **describe(arrays[g]))
            d[f'p 전체 ({n1})'] = p1
            d[f'p 전체 ({n2})'] = p2
            if control in arrays:
                t, u, ta, ua = vs.get(g, (math.nan,) * 4)
                d.update({'대조군': control if g != control else '(대조군)', 'p Welch 대 대조군': t,
                          'p MWU 대 대조군': u, 'p Welch 대 대조군 (Holm)': ta, 'p MWU 대 대조군 (Holm)': ua})
            out.append(d)
    return out


def sample_means(keys: list, cols: dict) -> tuple[list, dict, list]:
    """One row per key (image / group): the mean of each column.  Returns
    (unique keys in order, {column: means}, n rows per key)."""
    order, idx = [], {}
    for i, k in enumerate(keys):
        if k not in idx:
            idx[k] = []
            order.append(k)
        idx[k].append(i)
    means = {}
    for c, v in cols.items():
        v = np.asarray(v, float)
        m = []
        for k in order:
            s = v[idx[k]]
            s = s[np.isfinite(s)]
            m.append(float(s.mean()) if len(s) else math.nan)
        means[c] = np.array(m)
    return order, means, [len(idx[k]) for k in order]
