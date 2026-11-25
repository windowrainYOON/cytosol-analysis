"""cytosol-pipe: 파이프라인을 명령줄에서 (design v3.1 ch. 8).

  python -m cytosol.pipe stages                      단계 종류 · 설정 · object 규칙
  python -m cytosol.pipe presets                     보관함 (사용자 파일 + 기본 프리셋)
  python -m cytosol.pipe show NAME|FILE              단계 목록
  python -m cytosol.pipe new FILE [--from PRESET] [--name N]
  python -m cytosol.pipe edit FILE --set 'stages[2].settings.out=세포 (안쪽)' …
  python -m cytosol.pipe add FILE KIND [--at N]      단계 넣기 (끝 또는 N번째)
  python -m cytosol.pipe validate FILE [--folder F]  object · 순서 · 채널 확인
  python -m cytosol.pipe inspect FOLDER              이미지 · 채널 · 크기 · 그룹
  python -m cytosol.pipe run FILE|PRESET FOLDER [--out DIR] [--only 1,3] [--images a,b]
                         [--dry-run] [--json] [--background] [--review stop|skip]
  python -m cytosol.pipe status OUT                  progress.jsonl / summary.json
  python -m cytosol.pipe resume OUT                  검토에서 멈춘 실행을 이어서
  python -m cytosol.pipe rerun OUT --from N          N단계부터 다시

Every command prints plain text, or one JSON object with --json, so another
program (or Claude Code) can drive it: inspect → presets → new / edit →
validate → run --dry-run → run → read summary.json."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _out(args, obj, text):
    if getattr(args, 'json', False):
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    else:
        print(text)


def _value(v: str):
    try:
        return json.loads(v)
    except ValueError:
        return v


def _spec(name):
    from . import pipeline as P
    return P.find_preset(name)


_APP = None


def headless():
    """Offscreen QApplication + MainWindow (no dialogs)."""
    global _APP
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QMessageBox
    QMessageBox.information = staticmethod(lambda *x, **k: print('INFO:', *x[1:3], file=sys.stderr))
    QMessageBox.warning = staticmethod(lambda *x, **k: print('WARN:', *x[1:3], file=sys.stderr))
    QMessageBox.critical = staticmethod(lambda *x, **k: print('ERROR:', *x[1:3], file=sys.stderr))
    QMessageBox.question = staticmethod(lambda *x, **k: QMessageBox.StandardButton.No)
    from .ui import dialogs

    def _say(kind, title, text):  # the app's alerts / questions on stderr, answered No
        tag = {'warning': 'WARN', 'critical': 'ERROR'}.get(kind, 'INFO')
        print(f'{tag}:', title, text, file=sys.stderr)
        return QMessageBox.StandardButton.No if kind == 'question' else (
            False if kind == 'destructive' else None if kind == 'choose'
            else QMessageBox.StandardButton.Ok)
    dialogs.HEADLESS = _say
    _APP = QApplication.instance() or QApplication([sys.argv[0]])
    from . import i18n
    i18n.install()
    from .app import MainWindow
    win = MainWindow()
    win.set_dirty(False)
    return win


def cmd_stages(a):
    from . import pipeline as P
    d = {k: {kk: v[kk] for kk in ('group', 'title', 'desc', 'settings', 'out', 'needs')} for k, v in P.STAGES.items()}
    rules = {'groups': [t for _g, t in P.GROUPS], 'actions': dict(P.ACTIONS), 'pairs': dict(P.PAIRS),
             'condition_ops': list(P.OPS), 'condition_fields': list(P.FIELDS), 'stats': list(P.STATS),
             'bg': ['none', 'outside', 'ring:<object>'],
             'note': '연산: input object → where {mode all|any, conds [[field, op, value]]} → action → out (+ rest). '
                     'Mean 기준 값 "bg*1.5" = 배경의 1.5배.'}
    lines = []
    for g, t in P.GROUPS:
        lines.append(f'[{t}]')
        for k, v in P.STAGES.items():
            if v['group'] == g:
                o = f'  → {", ".join(v["out"])}' if v['out'] else ''
                lines.append(f'  {k:20s} {v["title"]}{o}\n  {"":20s} {v["desc"]}')
    lines += ['', '연산 동작: ' + ', '.join(f'{k} ({t})' for k, t in P.ACTIONS),
              '조건 필드: ' + ', '.join(P.FIELDS), '조건 비교: ' + ' '.join(P.OPS)]
    _out(a, {'stages': d, 'rules': rules}, '\n'.join(lines))


def cmd_presets(a):
    from . import pipeline as P
    rows = [{'name': n, 'file': str(p) if p else '', 'builtin': p is None, 'note': s.note,
             'stages': [st['kind'] for st in s.stages]} for n, p, s in P.library()]
    _out(a, {'presets': rows, 'library': str(P.library_dir())},
         '\n'.join(f'{"·" if r["builtin"] else "★"} {r["name"]}: {r["note"]}' for r in rows))


def _show_text(spec):
    from . import pipeline as P
    lines = [spec.name + (f'  ({spec.note})' if spec.note else '')]
    for i, st in enumerate(spec.stages, start=1):
        g = dict(P.GROUPS)[P.STAGES[st['kind']]['group']]
        off = '' if st.get('enabled', True) else '  (꺼짐)'
        lines.append(f'{i:2d}. [{g}] {P.stage_title(st)}: {P.stage_summary(st)}{off}')
    return '\n'.join(lines)


def cmd_show(a):
    spec = _spec(a.name)
    _out(a, spec.to_dict(), _show_text(spec))


def cmd_new(a):
    from . import pipeline as P
    spec = _spec(a.from_) if a.from_ else P.PipelineSpec()
    if a.name:
        spec.name = a.name
    p = spec.save(a.file)
    _out(a, {'file': str(p), **spec.to_dict()}, f'{p}\n' + _show_text(spec))


def cmd_edit(a):
    from . import pipeline as P
    d = P.PipelineSpec.load(a.file).to_dict()
    for s in a.set or []:
        path, _, v = s.partition('=')
        P.set_path(d, path.strip(), _value(v))
    spec = P.PipelineSpec.from_dict(d)
    errs = P.validate(spec)
    spec.save(a.file)
    _out(a, {'file': a.file, 'errors': errs}, _show_text(spec) + ('\n' + '\n'.join(errs) if errs else ''))


def cmd_add(a):
    from . import pipeline as P
    spec = P.PipelineSpec.load(a.file)
    st = P.default_stage(a.kind)
    at = len(spec.stages) if a.at is None else max(0, a.at - 1)
    spec.stages.insert(at, st)
    spec.save(a.file)
    _out(a, spec.to_dict(), _show_text(spec))


def _channels(folder):
    from . import io
    from . import pipeline as P
    out = []
    for f in P.find_images(folder)[:200]:
        try:
            im = io.read_image(f)
            out.append({'file': str(f), 'channels': list(im.channels), 'nt': im.nt,
                        'pixel_um': im.voxel_size_um.get('X'), 'pixel_z_um': im.voxel_size_um.get('Z')})
            im.release()
        except Exception as exc:  # noqa: BLE001
            out.append({'file': str(f), 'error': str(exc)})
    return out


def cmd_validate(a):
    from . import pipeline as P
    spec = P.PipelineSpec.load(a.file) if Path(a.file).exists() else _spec(a.file)
    chans = None
    if a.folder:
        info = _channels(a.folder)
        chans = sorted({c for r in info for c in r.get('channels', [])})
    errs = P.validate(spec, chans)
    _out(a, {'ok': not errs, 'errors': errs}, '문제 없음' if not errs else '\n'.join(errs))
    return 1 if errs else 0


def cmd_inspect(a):
    from .groups import auto_groups
    info = _channels(a.folder)
    g = auto_groups([Path(r['file']).name for r in info])
    for i, r in enumerate(info):
        r['group'] = g.get(i, '')
    text = '\n'.join(f'{Path(r["file"]).name}: {r.get("error") or " / ".join(r["channels"])} '
                     f'T {r.get("nt", "?")} {r.get("group", "")}' for r in info)
    _out(a, {'folder': a.folder, 'images': info}, text or '이미지가 없습니다.')


def _runner(a, spec, win, out):
    from . import pipeline as P

    def prog(d):
        if not a.json:
            ev = d.get('event')
            if ev == 'stage':
                print(f'[{d["index"]}] {d["title"]} …', flush=True)
            elif ev == 'error':
                print(f'    ! {d["message"]}', flush=True)
            elif ev == 'review':
                print(f'    검토: 이미지 {len(d["images"])}개', flush=True)
    return P.Runner(win, spec, out=out, interactive=a.review == 'stop', progress=prog)


def cmd_run(a):
    from . import pipeline as P
    spec = P.PipelineSpec.load(a.pipeline) if Path(a.pipeline).exists() else _spec(a.pipeline)
    spec.input['folder'] = str(Path(a.folder).expanduser().resolve())
    files = P.find_images(spec.input['folder'])
    if a.images:
        keys = a.images.split(',')
        files = [f for f in files if any(k in f.name for k in keys)]
    if a.dry_run:
        errs = P.validate(spec, sorted({c for r in _channels(a.folder) for c in r.get('channels', [])}))
        out = a.out or str(P.result_folder(spec, [type('I', (), {'path': files[0]})] if files else []))
        _out(a, {'images': [str(f) for f in files], 'stages': spec.to_dict()['stages'], 'out': out, 'errors': errs},
             _show_text(spec) + f'\n이미지 {len(files)}개 → {out}' + ('\n' + '\n'.join(errs) if errs else ''))
        return 1 if errs else 0
    if a.background:
        out = Path(a.out) if a.out else P.result_folder(spec, [type('I', (), {'path': files[0]})] if files else [])
        out.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, '-m', 'cytosol.pipe', 'run', a.pipeline, a.folder, '--json', '--out', str(out)]
        for k in ('only', 'images'):
            if getattr(a, k):
                args += [f'--{k}', getattr(a, k)]
        log = open(out / 'pipe_run.log', 'w')
        p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                             cwd=str(Path(__file__).resolve().parents[1]))
        _out(a, {'pid': p.pid, 'out': str(out)}, f'백그라운드 실행 pid {p.pid} → {out}\n'
                                                 f'상태: python -m cytosol.pipe status "{out}"')
        return 0
    if not files:
        _out(a, {'error': 'no images'}, f'{a.folder}에 이미지가 없습니다.')
        return 1
    win = headless()
    win.import_paths(files)
    for st in spec.stages:     # images are open: the load stage needs nothing more
        if st['kind'] == 'start.load':
            st['enabled'] = False
    out = a.out or str(P.result_folder(spec, win.items))
    r = _runner(a, spec, win, out)
    only = {int(x) for x in a.only.split(',')} if a.only else None
    res = r.run(only=only)
    if res == 'review':
        save_state(r, out)
        _out(a, {'status': 'review', 'out': out, 'images': r.state.review_images},
             f'검토에서 멈춤 ({len(r.state.review_images)}개). 앱에서 고친 뒤: python -m cytosol.pipe resume "{out}"')
        return 2
    summ = r.write_meta()
    _out(a, summ, f'끝: {out}\n' + (('경고 ' + str(len(r.state.errors)) + '개:\n' + '\n'.join(r.state.errors))
                                   if r.state.errors else '경고 없음'))
    return 0


def save_state(r, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    r.win.write_project_to(out / 'project.cyproj')
    (out / 'run_state.json').write_text(json.dumps({'spec': r.spec.to_dict(), 'state': r.state.to_dict()},
                                                   ensure_ascii=False, indent=1, default=str), encoding='utf-8')


def _restore(out):
    from . import pipeline as P
    out = Path(out)
    d = json.loads((out / 'run_state.json').read_text(encoding='utf-8'))
    win = headless()
    win.open_project(out / 'project.cyproj')
    spec = P.PipelineSpec.from_dict(d['spec'])
    return win, spec, d['state']


def cmd_status(a):
    out = Path(a.out)
    summ = out / 'summary.json'
    if summ.exists():
        d = json.loads(summ.read_text(encoding='utf-8'))
        _out(a, d, f'{d["status"]}: 이미지 {d["images"]}개, 경고 {len(d["errors"])}개, {d["seconds"]}초')
        return 0
    prog = out / 'progress.jsonl'
    if not prog.exists():
        _out(a, {'status': 'none'}, '아직 시작 전이거나 폴더가 다릅니다.')
        return 1
    lines = [json.loads(x) for x in prog.read_text(encoding='utf-8').splitlines() if x.strip()]
    last = lines[-1] if lines else {}
    st = next((x for x in reversed(lines) if x.get('event') == 'stage'), {})
    _out(a, {'status': 'running' if last.get('event') != 'review' else 'review', 'last': last, 'stage': st},
         f'{"검토 대기" if last.get("event") == "review" else "실행 중"}: {st.get("index", "?")}단계 '
         f'{st.get("title", "")} ({last.get("t", "")})')
    return 0


def _continue(a, start):
    from . import pipeline as P
    win, spec, state = _restore(a.out)
    for st in spec.stages:
        if st['kind'] == 'start.load':
            st['enabled'] = False
    r = _runner(a, spec, win, a.out)
    r.state.tables = {}
    r.state.started = time.time()
    r.state.stage = start if start is not None else state.get('stage', 0)
    res = r.run() if start is None else r.rerun_from(start)
    if res == 'review':
        save_state(r, a.out)
        return 2
    summ = r.write_meta()
    _out(a, summ, f'끝: {a.out}')
    del P
    return 0


def cmd_resume(a):
    return _continue(a, None)


def cmd_rerun(a):
    return _continue(a, a.from_ - 1)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='cytosol-pipe', description=__doc__.split('\n\n')[0])
    ap.add_argument('--json', action='store_true')
    sub = ap.add_subparsers(dest='cmd', required=True)

    def add(name, fn, *spec):
        p = sub.add_parser(name)
        p.add_argument('--json', action='store_true')
        for args, kw in spec:
            p.add_argument(*args, **kw)
        p.set_defaults(fn=fn)
        return p

    add('stages', cmd_stages)
    add('presets', cmd_presets)
    add('show', cmd_show, (('name',), {}))
    add('new', cmd_new, (('file',), {}), (('--from',), {'dest': 'from_'}), (('--name',), {}))
    add('edit', cmd_edit, (('file',), {}), (('--set',), {'action': 'append'}))
    add('add', cmd_add, (('file',), {}), (('kind',), {}), (('--at',), {'type': int}))
    add('validate', cmd_validate, (('file',), {}), (('--folder',), {}))
    add('inspect', cmd_inspect, (('folder',), {}))
    add('run', cmd_run, (('pipeline',), {}), (('folder',), {}), (('--out',), {}), (('--only',), {}),
        (('--images',), {}), (('--dry-run',), {'action': 'store_true'}), (('--background',), {'action': 'store_true'}),
        (('--review',), {'choices': ['stop', 'skip'], 'default': 'skip'}))
    add('status', cmd_status, (('out',), {}))
    add('resume', cmd_resume, (('out',), {}))
    add('rerun', cmd_rerun, (('out',), {}), (('--from',), {'dest': 'from_', 'type': int, 'required': True}))
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == '__main__':
    sys.exit(main())
