"""Significance tests for the graph editor (owner request 2026-11-09): look
at the data (Shapiro-Wilk per group, Levene), recommend a test, compare the
chosen pairs of categories, turn p values into star marks and write a
caption sentence. Everything is computed with SciPy."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

# key: (name in the window, name in the caption, kind)
#  kind 'omni' = omnibus test + its own post hoc (two-sided, own correction)
#       'omni-corr' = omnibus + post hoc corrected with the chosen correction
#       'pair' = one test per pair (two groups), corrected over the pairs shown
METHODS = {
    'anova_tukey': ('One-way ANOVA + Tukey', "one-way ANOVA with Tukey's post hoc test", 'omni'),
    'welch_gh': ('Welch ANOVA + Games-Howell', "Welch's ANOVA with Games-Howell post hoc test", 'omni'),
    'kw_dunn': ('Kruskal-Wallis + Dunn', "Kruskal-Wallis test with Dunn's post hoc test", 'omni-corr'),
    't': ('t-검정 (Student)', "Student's t-test", 'pair'),
    'welch': ('Welch t-검정', "Welch's t-test", 'pair'),
    'mwu': ('Mann-Whitney U', 'Mann-Whitney U test', 'pair'),
    'paired_t': ('짝지은 t-검정', 'paired t-test', 'pair'),
    'wilcoxon': ('Wilcoxon 부호 순위', 'Wilcoxon signed-rank test', 'pair'),
}
PAIRED = ('paired_t', 'wilcoxon')
CORRECTIONS = {'holm': 'Holm', 'bonferroni': 'Bonferroni', 'bh': 'Benjamini-Hochberg (FDR)', 'none': '없음'}
CORR_CAPTION = {'holm': 'Holm', 'bonferroni': 'Bonferroni', 'bh': 'Benjamini-Hochberg'}
TAILS = {'two': '양측 (two-tailed)', 'greater': '단측: 비교 그룹 > 기준', 'less': '단측: 비교 그룹 < 기준'}
DISPLAYS = {'stars': '별표', 'p': 'p 값', 'both': '별표 + p 값'}
STAR_LEVELS = (0.05, 0.01, 0.001, 0.0001)


@dataclass
class Check:
    """What the data look like."""

    names: list
    n: list
    normal_p: list          # Shapiro-Wilk p per group (nan: n < 3)
    levene_p: float = math.nan
    normal: bool = True
    equal_var: bool = True
    paired_ok: bool = False  # every group has the same n


@dataclass
class Result:
    method: str
    tail: str
    correction: str
    check: Check
    omnibus: tuple = ()     # (name, statistic, p)
    pairs: list = field(default_factory=list)  # (a, b, p)
    recommended: str = ''
    reason: str = ''
    note: str = ''


def _clean(v) -> np.ndarray:
    v = np.asarray(v, float)
    return v[np.isfinite(v)]


def check(groups: dict, alpha=0.05) -> Check:
    from scipy import stats as st

    names = list(groups)
    vals = [_clean(groups[k]) for k in names]
    ps = []
    for v in vals:
        if v.size >= 3 and np.ptp(v) > 0:
            ps.append(float(st.shapiro(v).pvalue))
        else:
            ps.append(math.nan)
    lev = math.nan
    ok = [v for v in vals if v.size >= 2]
    if len(ok) >= 2 and any(np.ptp(v) > 0 for v in ok):
        lev = float(st.levene(*ok, center='median').pvalue)
    normal = all(not (p < alpha) for p in ps)
    equal = not (lev < alpha)
    same_n = len({v.size for v in vals}) == 1 and bool(vals) and vals[0].size >= 2
    return Check(names, [int(v.size) for v in vals], ps, lev, normal, equal, same_n)


def recommend(c: Check, paired=False) -> tuple[str, str]:
    """(method key, reason) for the data."""
    k = len(c.names)
    norm = '정규분포' if c.normal else '정규분포 아님'
    var = '분산 비슷' if c.equal_var else '분산 다름'
    if paired:
        m = 'paired_t' if c.normal else 'wilcoxon'
        return m, f'짝지은 표본 · {norm} → {METHODS[m][0]}'
    if k <= 2:
        m = ('t' if c.equal_var else 'welch') if c.normal else 'mwu'
        return m, f'2개 그룹 · {norm}{" · " + var if c.normal else ""} → {METHODS[m][0]}'
    m = ('anova_tukey' if c.equal_var else 'welch_gh') if c.normal else 'kw_dunn'
    return m, f'{k}개 그룹 · {"모두 " if c.normal else ""}{norm}{" · " + var if c.normal else ""} → {METHODS[m][0]}'


def correct(ps, how: str) -> list:
    p = np.asarray(ps, float)
    n = p.size
    if how == 'none' or n <= 1:
        return [float(x) for x in p]
    if how == 'bonferroni':
        return [float(min(1.0, x * n)) for x in p]
    order = np.argsort(p)
    out = np.empty(n)
    if how == 'holm':
        run = 0.0
        for rank, i in enumerate(order):
            run = max(run, min(1.0, (n - rank) * p[i]))
            out[i] = run
    else:  # Benjamini-Hochberg
        run = 1.0
        for rank in range(n - 1, -1, -1):
            i = order[rank]
            run = min(run, p[i] * n / (rank + 1))
            out[i] = min(1.0, run)
    return [float(x) for x in out]


def _welch_anova(vals):
    from scipy import stats as st

    k = len(vals)
    n = np.array([v.size for v in vals], float)
    m = np.array([v.mean() for v in vals])
    var = np.array([v.var(ddof=1) for v in vals])
    w = n / var
    mw = (w * m).sum() / w.sum()
    a = (w * (m - mw) ** 2).sum() / (k - 1)
    lam = ((1 - w / w.sum()) ** 2 / (n - 1)).sum()
    b = 1 + 2 * (k - 2) / (k ** 2 - 1) * lam
    f = a / b
    df2 = (k ** 2 - 1) / (3 * lam)
    return float(f), float(st.f.sf(f, k - 1, df2))


def _games_howell(vals, i, j):
    from scipy import stats as st

    a, b = vals[i], vals[j]
    va, vb = a.var(ddof=1) / a.size, b.var(ddof=1) / b.size
    se = math.sqrt(va + vb)
    if se == 0:
        return 1.0
    t = abs(a.mean() - b.mean()) / se
    df = (va + vb) ** 2 / (va ** 2 / (a.size - 1) + vb ** 2 / (b.size - 1))
    return float(min(1.0, st.studentized_range.sf(t * math.sqrt(2), len(vals), df)))


def _dunn(vals):
    """Two-sided p of Dunn's test for every pair (i, j) (ties corrected)."""
    from scipy import stats as st

    allv = np.concatenate(vals)
    ranks = st.rankdata(allv)
    nn = allv.size
    _, counts = np.unique(allv, return_counts=True)
    tie = (counts ** 3 - counts).sum() / (12 * (nn - 1)) if nn > 1 else 0.0
    mean_r, start = [], 0
    for v in vals:
        mean_r.append(ranks[start:start + v.size].mean())
        start += v.size
    out = {}
    for i, j in combinations(range(len(vals)), 2):
        se = math.sqrt(max((nn * (nn + 1) / 12 - tie) * (1 / vals[i].size + 1 / vals[j].size), 1e-300))
        z = (mean_r[i] - mean_r[j]) / se
        out[(i, j)] = float(2 * st.norm.sf(abs(z)))
    return out


def _pair_p(method, a, b, tail):
    """p of b vs a (a = the reference side; 'greater' = b > a)."""
    from scipy import stats as st

    alt = {'two': 'two-sided', 'greater': 'greater', 'less': 'less'}[tail]
    if a.size < 2 or b.size < 2:
        return math.nan
    try:
        if method == 't':
            return float(st.ttest_ind(b, a, equal_var=True, alternative=alt).pvalue)
        if method == 'welch':
            return float(st.ttest_ind(b, a, equal_var=False, alternative=alt).pvalue)
        if method == 'mwu':
            return float(st.mannwhitneyu(b, a, alternative=alt).pvalue)
        n = min(a.size, b.size)
        if method == 'paired_t':
            return float(st.ttest_rel(b[:n], a[:n], alternative=alt).pvalue)
        if method == 'wilcoxon':
            d = b[:n] - a[:n]
            if not np.any(d):
                return 1.0
            return float(st.wilcoxon(b[:n], a[:n], alternative=alt).pvalue)
    except ValueError:
        return math.nan
    return math.nan


def pairs_for(names: list, mode: str, ref: str = '', chosen=None) -> list:
    """The pairs to compare: 'all', 'ref' (reference vs the others) or the
    chosen ones (custom) that exist."""
    if mode == 'ref':
        r = ref if ref in names else (names[0] if names else '')
        return [(r, n) for n in names if n != r]
    if mode == 'custom':
        out = []
        for p in chosen or []:
            if len(p) == 2 and p[0] in names and p[1] in names and p[0] != p[1]:
                out.append((p[0], p[1]))
        return out
    return list(combinations(names, 2))


def run(groups: dict, method='auto', pairs=None, tail='two', correction='holm', paired=False,
        alpha=0.05) -> Result:
    """Compare the groups ({name: values}); pairs = [(a, b)] (None = all)."""
    from scipy import stats as st

    names = [k for k in groups if _clean(groups[k]).size]
    groups = {k: _clean(groups[k]) for k in names}
    c = check(groups, alpha)
    rec, why = recommend(c, paired)
    m = rec if method == 'auto' or method not in METHODS else method
    kind = METHODS[m][2]
    if kind == 'omni':
        tail, correction = 'two', m
    elif kind == 'omni-corr':
        tail = 'two'
    pairs = pairs_for(names, 'all') if pairs is None else [p for p in pairs if p[0] in groups and p[1] in groups]
    res = Result(m, tail, correction, c, recommended=rec, reason=why)
    vals = [groups[k] for k in names]
    if len(names) < 2:
        res.note = '비교할 그룹이 둘 이상 있어야 합니다.'
        return res
    idx = {k: i for i, k in enumerate(names)}
    big = all(v.size >= 2 for v in vals)
    if kind in ('omni', 'omni-corr') and big and len(names) >= 2:
        try:
            if m == 'anova_tukey':
                f = st.f_oneway(*vals)
                res.omnibus = ('one-way ANOVA', float(f.statistic), float(f.pvalue))
                tk = st.tukey_hsd(*vals).pvalue
                ps = [float(tk[idx[a], idx[b]]) for a, b in pairs]
            elif m == 'welch_gh':
                f, p = _welch_anova(vals)
                res.omnibus = ("Welch's ANOVA", f, p)
                ps = [_games_howell(vals, idx[a], idx[b]) for a, b in pairs]
            else:
                h = st.kruskal(*vals)
                res.omnibus = ('Kruskal-Wallis', float(h.statistic), float(h.pvalue))
                dn = _dunn(vals)
                raw = [dn[tuple(sorted((idx[a], idx[b])))] for a, b in pairs]
                ps = correct(raw, correction)
        except (ValueError, ZeroDivisionError, FloatingPointError):
            ps = [math.nan] * len(pairs)
    else:
        raw = [_pair_p(m, groups[a], groups[b], tail) for a, b in pairs]
        fin = [i for i, p in enumerate(raw) if math.isfinite(p)]
        cor = correct([raw[i] for i in fin], correction)
        ps = [math.nan] * len(raw)
        for i, p in zip(fin, cor):
            ps[i] = p
    res.pairs = [(a, b, p) for (a, b), p in zip(pairs, ps)]
    if not big:
        res.note = '값이 2개 미만인 그룹이 있어 검정할 수 없는 쌍이 있습니다.'
    return res


def stars(p: float, levels=4, alpha=0.05, ns='ns') -> str:
    if not math.isfinite(p) or p >= alpha:
        return ns
    n = sum(1 for t in STAR_LEVELS[:levels] if p < t)
    return '*' * max(n, 1)


def p_text(p: float) -> str:
    if not math.isfinite(p):
        return 'p = n/a'
    if p < 0.0001:
        return 'p < 0.0001'
    return f'p = {p:.2g}' if p < 0.01 else f'p = {p:.3f}'.rstrip('0').rstrip('.')


def mark(p: float, display='stars', levels=4, alpha=0.05, show_ns=True) -> str:
    """The text over a bracket ('' = not drawn)."""
    s = stars(p, levels, alpha)
    if s == 'ns' and not show_ns:
        return ''
    if display == 'p':
        return p_text(p)
    if display == 'both':
        return f'{s} ({p_text(p)})' if math.isfinite(p) else s
    return s


def caption(res: Result, levels=4, alpha=0.05, unit='') -> str:
    """A sentence for the figure legend."""
    name = METHODS[res.method][1]
    kind = METHODS[res.method][2]
    parts = [name[0].upper() + name[1:]]
    if kind == 'pair' and len(res.pairs) > 1 and res.correction in CORR_CAPTION:
        parts[0] += f' with {CORR_CAPTION[res.correction]} correction'
    elif kind == 'omni-corr' and res.correction in CORR_CAPTION:
        parts[0] += f' ({CORR_CAPTION[res.correction]}-adjusted)'
    tail = {'two': 'two-tailed', 'greater': 'one-tailed', 'less': 'one-tailed'}[res.tail]
    ns = [n for n in res.check.n if n]
    if ns:
        rng = f'{min(ns)}' if min(ns) == max(ns) else f'{min(ns)}–{max(ns)}'
        nn = f'n = {rng}{" " + unit if unit else ""} per group'
    else:
        nn = ''
    lv = [f'{"*" * (i + 1)}p < {t:g}' for i, t in enumerate(STAR_LEVELS[:levels])]
    sig = f'ns, p ≥ {alpha:g}; ' + ', '.join(lv)
    return f'{parts[0]} ({tail}){", " + nn if nn else ""}; {sig}.'
