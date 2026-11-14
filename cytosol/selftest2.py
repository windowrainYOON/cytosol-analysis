"""Self-test steps of the features built from the 2026-11-14 proposals
(이미지 묶기, graph correlation tools, measurement data display, particle
tracking, mitoROI).  `selftest.run` calls them like its own steps."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([sys.argv[0]])


def _window():
    from .app import MainWindow

    app = _app()
    win = MainWindow()
    app.processEvents()
    return app, win


def _close(win):
    win.set_dirty(False)
    win.close()
    win.deleteLater()
    _app().processEvents()


def _rgb_tiffs(folder: Path, sample: str, seed=0) -> list[Path]:
    import tifffile

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    out = []
    for k, col in enumerate(('Red', 'Green', 'Blue')):
        a = (rng.random((40, 48)) * 50 + 20 * k).astype(np.uint8)
        p = folder / f'{sample}_Ch{k + 1}_{col}.tif'
        tifffile.imwrite(p, a, imagej=True, resolution=(10.0, 10.0), metadata={'unit': 'um'})
        out.append(p)
    return out


def stacking_step(out: Path):
    """이미지 묶기: RGB splits stacked on load, the dialog for C / T stacks,
    the same naming pattern, 묶음 풀기, the project round trip."""
    from . import stacking
    from .stack_dialog import StackDialog

    app, win = _window()
    d = out / 'stacking'
    a = _rgb_tiffs(d, 'Control_01', 1)
    b = _rgb_tiffs(d, 'Control_02', 2)
    win.add_files(a)
    if len(win.items) != 1 or win.items[0].stack is None or len(win.items[0].channels) != 3:
        raise AssertionError(f'RGB set not stacked on load: {[it.label for it in win.items]}')
    st = win.items[0]
    if st.label != 'Control_01':
        raise AssertionError(f'stack name {st.label}')
    plane = st.planes()
    if plane.shape != (3, 40, 48):
        raise AssertionError(f'stack plane {plane.shape}')
    import tifffile
    if not np.array_equal(plane[1], tifffile.imread(a[1]).astype(np.float32)):
        raise AssertionError('stack channel 2 is not the Green file')
    # the tree shows the files greyed under the stack
    leaf = win.file_list.item(0)
    if leaf.childCount() != 3 or '(3채널)' not in leaf.text(0):
        raise AssertionError(f'tree row {leaf.text(0)} / {leaf.childCount()}')
    # 묶음 풀기, then the dialog with the same naming pattern
    win.unstack([st])
    if len(win.items) != 3 or any(it.stack for it in win.items):
        raise AssertionError('묶음 풀기')
    win.add_files(b, explicit=True)
    win.unstack([it for it in win.items if it.stack is not None])
    if len(win.items) != 6:
        raise AssertionError(f'items {len(win.items)}')
    items = [it for it in win.items if it.path in a]
    dlg = StackDialog(win, [it.path for it in items], [it.image for it in items],
                      [it.path for it in win.items if it not in items])
    if not dlg.more_sets or dlg.more_sets[0][0] != 'Control_02':
        raise AssertionError(f'same naming pattern {dlg.more_sets}')
    dlg.move_row(0, 2)  # order Green, Blue, Red
    specs = [dlg.spec()] + dlg.extra_specs()
    if [Path(s.path).name for s in specs[1].sources][0] != 'Control_02_Ch2_Green.tif':
        raise AssertionError('other set not in the dialog order')
    made = win.make_stacks(specs)
    if len(made) != 2 or len(win.items) != 2:
        raise AssertionError(f'make_stacks {len(made)} / {len(win.items)}')
    if made[0].channels[0] != 'Green':
        raise AssertionError(f'channel order {made[0].channels}')
    # T stack
    t_spec = stacking.StackSpec(axis='T', interval_s=5.0, name='time', fold=False,
                                sources=[stacking.StackSource(str(p)) for p in a])
    t_item = stacking.load_item(t_spec)
    if t_item.nt != 3 or t_item.image.times[2] != 10.0:
        raise AssertionError('T stack')
    t_item.set_t(2)
    if not np.array_equal(t_item.planes()[0], tifffile.imread(a[2]).astype(np.float32)):
        raise AssertionError('T stack plane 3')
    # mismatch
    import tifffile as tf
    odd = d / 'odd.tif'
    tf.imwrite(odd, np.zeros((30, 30), np.uint8))
    try:
        stacking.load_item(stacking.StackSpec(sources=[stacking.StackSource(str(a[0])),
                                                       stacking.StackSource(str(odd))]))
        raise AssertionError('different sizes stacked')
    except stacking.StackError:
        pass
    pad = stacking.load_item(stacking.StackSpec(mismatch='pad', sources=[
        stacking.StackSource(str(a[0])), stacking.StackSource(str(odd))]))
    if pad.planes().shape != (2, 40, 48):
        raise AssertionError('pad')
    # project round trip
    proj = d / 'stack.cyproj'
    win.write_project_to(proj)
    win.set_dirty(False)
    win.open_project(proj)
    if len(win.items) != 2 or win.items[0].stack is None or win.items[0].channels[0] != 'Green':
        raise AssertionError('stack not restored from the project')
    _close(win)
    app.processEvents()
    return '2 RGB sets stacked, dialog order, same pattern, T stack, pad, project'


STEPS = [
    ('image stacking', stacking_step),
]
