"""표 가져오기 (owner request 2026-11-20, v0.74): CSV / TSV / TXT and Excel
(.xlsx / .xlsm, .xls when xlrd is installed) files that this app did not
write become graph `Table`s.

Pure reading code (no Qt): `read_grid(path, sheet)` gives the raw cells,
`ImportOptions` says which row holds the column names, where the data starts,
the decimal mark and whether a wide table (one column per group, as in Prism
or Excel sheets) is turned into a long one, and `build_table(grid, opts)`
makes the `Table`. `guess_header` picks the header row the way a person would:
the first row of mostly text cells that is followed by rows of numbers.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass
from pathlib import Path

from . import graph as G

TEXT_EXT = ('.csv', '.tsv', '.txt', '.tab')
EXCEL_EXT = ('.xlsx', '.xlsm', '.xls')
FILTER = '표 파일 (*.csv *.tsv *.txt *.tab *.xlsx *.xlsm *.xls);;CSV · 텍스트 (*.csv *.tsv *.txt *.tab);;Excel (*.xlsx *.xlsm *.xls)'
ENCODINGS = ('utf-8-sig', 'cp949', 'utf-16', 'latin-1')


@dataclass
class ImportOptions:
    sheet: str = ''          # Excel sheet ('' = first)
    header: int = -1         # 0-based header row; -1 = automatic; None = no header row
    decimal_comma: bool = False
    wide: bool = False       # every value column is a group: rows → (그룹, 값)
    skip_empty: bool = True  # leave out empty rows and columns


def is_table_file(path) -> bool:
    return Path(path).suffix.lower() in TEXT_EXT + EXCEL_EXT


def sheets(path) -> list[str]:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in ('.xlsx', '.xlsm'):
        import openpyxl  # noqa: PLC0415

        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()
    if ext == '.xls' and not _is_text(p):
        xlrd = _xlrd()
        return xlrd.open_workbook(str(p), on_demand=True).sheet_names()
    return []


def _is_text(p: Path) -> bool:
    """Old Excel and other programs save text tables with an .xls name."""
    head = p.read_bytes()[:8]
    return not (head.startswith(b'\xd0\xcf\x11\xe0') or head.startswith(b'PK'))


def _xlrd():
    try:
        import xlrd  # noqa: PLC0415
    except ImportError as exc:
        raise ValueError('예전 Excel 형식(.xls)은 읽을 수 없습니다. Excel에서 .xlsx 또는 CSV로 저장한 뒤 불러오세요.') from exc
    return xlrd


def _decode(raw: bytes) -> str:
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', errors='replace')


def read_grid(path, sheet: str = '') -> list[list]:
    """The file's cells as rows of str / float / int ('' for empty)."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in ('.xlsx', '.xlsm'):
        import openpyxl  # noqa: PLC0415

        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        try:
            ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
            rows = [[_cell(v) for v in r] for r in ws.iter_rows(values_only=True)]
        finally:
            wb.close()
        return _trim(rows)
    if ext == '.xls' and not _is_text(p):
        xlrd = _xlrd()
        book = xlrd.open_workbook(str(p))
        ws = book.sheet_by_name(sheet) if sheet and sheet in book.sheet_names() else book.sheet_by_index(0)
        return _trim([[_cell(v) for v in ws.row_values(i)] for i in range(ws.nrows)])
    text = _decode(p.read_bytes())
    sample = text[:8192]
    delims = '\t' if ext in ('.tsv', '.tab') else ',;\t'
    if ext == '.xls' and '\t' in sample:
        delims = '\t'
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=delims)
    except csv.Error:
        dialect = csv.excel_tab if ext in ('.tsv', '.tab') else csv.excel
    return _trim([list(r) for r in csv.reader(io.StringIO(text), dialect)])


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return v
    if hasattr(v, 'isoformat'):  # dates / times
        return v.isoformat(sep=' ') if hasattr(v, 'hour') and hasattr(v, 'day') else v.isoformat()
    return str(v)


def _trim(rows):
    """Square the grid and drop trailing empty rows / columns."""
    n = max((len(r) for r in rows), default=0)
    rows = [list(r) + [''] * (n - len(r)) for r in rows]
    while rows and all(_empty(v) for v in rows[-1]):
        rows.pop()
    while n and all(_empty(r[n - 1]) for r in rows):
        n -= 1
        rows = [r[:n] for r in rows]
    return rows


def _empty(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


_NUM = re.compile(r'^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?%?$')


def to_number(v, decimal_comma=False):
    """A number for numeric text ('1,5' with decimal_comma, '12%' = 12), else None."""
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(float(v)) else None
    s = str(v).strip().replace('−', '-')
    if not s:
        return None
    if decimal_comma:
        s = s.replace('.', '').replace(',', '.') if s.count(',') == 1 else s
    else:
        s = s.replace(',', '') if re.fullmatch(r'[+-]?\d{1,3}(,\d{3})+(\.\d*)?', s) else s
    if not _NUM.match(s.replace(',', '.') if decimal_comma else s):
        return None
    try:
        x = float(s.rstrip('%'))
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def guess_header(grid, decimal_comma=False):
    """0-based row of the column names, None when the table starts with data.
    Title / note rows above it (few filled cells) are skipped."""
    width = max((len(r) for r in grid), default=0)
    for i, r in enumerate(grid[:40]):
        filled = [v for v in r if not _empty(v)]
        if len(filled) < min(2, width):
            continue  # a title or note in one cell
        if not _mostly_text(r, decimal_comma):
            return None  # the first full row is already data
        nxt = next((x for x in grid[i + 1:i + 6] if any(not _empty(v) for v in x)), [])
        if not nxt or any(to_number(v, decimal_comma) is not None for v in nxt) or _mostly_text(nxt, decimal_comma):
            return i
    return None


def _mostly_text(r, decimal_comma):
    filled = [v for v in r if not _empty(v)]
    return bool(filled) and sum(1 for v in filled if to_number(v, decimal_comma) is None) * 2 >= len(filled)


def header_row(grid, opts: ImportOptions):
    return guess_header(grid, opts.decimal_comma) if opts.header == -1 else opts.header


def _names(head, n):
    out, seen = [], {}
    for j in range(n):
        v = head[j] if head is not None and j < len(head) else ''
        name = str(v).strip() if not _empty(v) else f'열 {j + 1}'
        if isinstance(v, float) and v.is_integer():
            name = str(int(v))
        k = seen.get(name, 0)
        seen[name] = k + 1
        out.append(name if k == 0 else f'{name} ({k + 1})')
    return out


def build_table(grid, opts: ImportOptions, name='표') -> G.Table:
    h = header_row(grid, opts)
    head = grid[h] if h is not None and h < len(grid) else None
    body = grid[(h + 1) if h is not None else 0:]
    n = max((len(r) for r in grid), default=0)
    cols = _names(head, n)
    keep = list(range(n))
    if opts.skip_empty:
        body = [r for r in body if any(not _empty(v) for v in r)]
        keep = [j for j in keep if any(not _empty(r[j]) for r in body if j < len(r)) or
                (head is not None and not _empty(head[j]))]

    def conv(v):
        x = to_number(v, opts.decimal_comma)
        return x if x is not None else ('' if _empty(v) else str(v).strip())

    rows = [[conv(r[j]) if j < len(r) else '' for j in keep] for r in body]
    cols = [cols[j] for j in keep]
    t = G.Table(name, cols, rows)
    if opts.wide:
        t = to_long(t)
    return t


def to_long(t: G.Table) -> G.Table:
    """Wide table (one column per group) → rows of 그룹 / 값 (+ the text
    columns, + 행 = the row number), so 범주 charts work on it."""
    nums = [c for c in t.columns if t.is_numeric(c)]
    texts = [c for c in t.columns if c not in nums]
    cols = texts + ['그룹', '값', '행']
    rows = []
    for j, c in enumerate(nums):
        k = t.index(c)
        for i, r in enumerate(t.rows):
            v = r[k]
            if v == '' or v is None:
                continue
            rows.append([r[t.index(x)] for x in texts] + [c, v, i + 1])
    out = G.Table(t.name, cols, rows)
    out.labels = {}
    return out


def summary(t: G.Table) -> str:
    nums = sum(1 for c in t.columns if t.is_numeric(c))
    return f'{len(t.rows)}행 · 열 {len(t.columns)}개 (숫자 {nums}, 글자 {len(t.columns) - nums})'


def read_table(path, opts: ImportOptions | None = None) -> G.Table:
    opts = opts or ImportOptions()
    p = Path(path)
    grid = read_grid(p, opts.sheet)
    if not grid:
        raise ValueError('빈 파일입니다.')
    name = p.stem if not opts.sheet else f'{p.stem} · {opts.sheet}'
    return build_table(grid, opts, name)


# ---------------------------------------------------------------------------
# 역할 (owner request 2026-11-20, mockup v2): which column / row is the sample
# name, which is the group, which are measured values; groups from names
# ---------------------------------------------------------------------------

ROLES = ('name', 'group', 'cat', 'value', 'off')
GROUP_NAMES = ('group', 'groups', '그룹', 'condition', 'conditions', '조건', 'treatment', '처리')
ROLE_TEXT = {'name': '이름', 'group': '그룹', 'cat': '범주', 'value': '값', 'off': '빼기'}

_CHANNEL = re.compile(r'\s*[-_ ]\s*(C|Ch|ch|channel)\s*=?\s*\d+\s*$')
_EXT = re.compile(r'\.(oir|czi|tcf|tiff?|nd2|lif|lsm|png|jpe?g)\b', re.I)
_TRAIL = re.compile(r'([ _\-.]+#?\d+|\s*\(\d+\))$')
_LEAD_NUM = re.compile(r'^\d+[ _\-.]+')


def transpose(grid):
    n = max((len(r) for r in grid), default=0)
    return [[r[j] if j < len(r) else '' for r in grid] for j in range(n)]


def guess_roles(t: G.Table) -> dict:
    """column -> role: the first text column with many different values is the
    name, a text column with few values the group, numbers are values."""
    roles, name = {}, None
    for c in t.columns:
        if t.is_numeric(c):
            roles[c] = 'value'
            continue
        if str(c).strip().lower() in GROUP_NAMES and 'group' not in roles.values():
            roles[c] = 'group'
            continue
        vals = [str(v) for v in t.values(c) if str(v).strip()]
        k = len(set(vals))
        if name is None and k > max(2, len(vals) // 10):
            roles[c], name = 'name', c
        else:
            roles[c] = 'cat'
    if name is None:
        texts = [c for c in t.columns if roles[c] not in ('value', 'group')]
        if texts:
            roles[texts[0]] = 'name'
    return roles


def group_key(name: str, rule='auto', sep=',', parts=1) -> str:
    """Group of one sample name. auto: without channel tags (- C=1), file
    extensions and the trailing number (_0001); split: the first `parts`
    pieces between `sep`."""
    s = str(name).strip()
    prev = None
    while prev != s:
        prev = s
        s = _CHANNEL.sub('', s)
        s = _EXT.sub('', s)
        s = _TRAIL.sub('', s).rstrip(' _-.,')
    s = s or str(name).strip()
    if rule == 'split' and sep:
        bits = [b.strip() for b in s.split(sep)]
        s = (sep + ' ' if sep == ',' else sep).join(bits[:max(1, parts)])
    return s


def name_groups(names, rule='auto', sep=',', parts=1, short=True) -> dict:
    """sample name -> group. short: the words every group starts with are
    left out (Split mNG, BafA1 / Split mNG, DMSO → BafA1 / DMSO)."""
    keys = {n: group_key(n, rule, sep, parts) for n in names}
    groups = sorted(set(keys.values()))
    if short and len(groups) > 1:
        pre = groups[0]
        for g in groups[1:]:
            k = 0
            while k < min(len(pre), len(g)) and pre[k] == g[k]:
                k += 1
            pre = pre[:k]
        cut = max(pre.rfind(','), pre.rfind(' '), pre.rfind('_'), pre.rfind('-'))
        if cut > 0 and all(len(g) > cut + 1 for g in groups):
            keys = {n: k[cut + 1:].strip(' ,_-') for n, k in keys.items()}
    return keys


def apply_roles(t: G.Table, roles: dict, groups: dict | None = None) -> G.Table:
    """Columns in role order: 이름, 그룹 (from the group column or `groups`
    = name -> group), then the values; '빼기' columns are left out."""
    name = next((c for c in t.columns if roles.get(c) == 'name'), None)
    gcol = next((c for c in t.columns if roles.get(c) == 'group'), None)
    vals = [c for c in t.columns if roles.get(c, 'value') == 'value']
    extra = [c for c in t.columns if roles.get(c) == 'cat']
    cols = ([name] if name and name != 'group' else ([] if not name else ['name'])) + ['group'] + extra + vals
    rows = []
    for r in t.rows:
        nm = r[t.index(name)] if name else ''
        if groups is not None and name:
            g = groups.get(nm, '')
        else:
            g = r[t.index(gcol)] if gcol else ''
        rows.append(([nm] if name else []) + [g] + [r[t.index(c)] for c in extra + vals])
    out = G.Table(t.name, cols, rows)
    out.labels = {'group': '그룹'}
    return out
