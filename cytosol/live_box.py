"""실시간 값 박스 (owner request 2026-11-14, data-display proposal ch. 11):
one rounded card under the canvas (below the T slider) for the tabs whose
settings are tuned while looking at the result: big numbers on the left, a
small graph on the right, a fold button.  Only the current image and plane
are computed; the box follows the tab shown and hides for other tabs.  The
FRAP curve, line profile and Coloc 2 plots moved here from their tabs."""

from __future__ import annotations

import traceback

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

TITLES = {'roi_tab': '세포질 ROI · 현재 이미지', 'particle_tab': '입자 ROI · 현재 이미지',
          'intensity_tab': '강도 측정 · 현재 이미지', 'bands_tab': '등거리 띠 · 현재 이미지',
          'frap_tab': 'FRAP · 현재 이미지', 'profile_tab': '라인 프로파일 · 현재 선',
          'coloc_tab': 'Coloc 2 · 고른 ROI', 'track_tab': '입자 추적 · 현재 이미지',
          'mito_tab': 'mitoROI · 현재 이미지'}
BORROWED = {'frap_tab': 'frap_panel', 'profile_tab': 'profile_panel', 'coloc_tab': 'coloc_panel'}
PLOT_H = 150


def _fmt(v) -> str:
    if v is None:
        return '–'
    if isinstance(v, str):
        return v
    if isinstance(v, (int, np.integer)):
        return f'{int(v):,}'
    v = float(v)
    if not np.isfinite(v):
        return '–'
    return f'{v:.3g}' if abs(v) < 1000 else f'{v:,.0f}'


class LiveBox(QGroupBox):
    def __init__(self, win):
        super().__init__('')
        self.win = win
        self.tab = None
        self.folded = False
        self.tiles: list[tuple] = []
        self._prev = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        self.title = QLabel()
        theme.text_style(self.title, 'headline')
        head.addWidget(self.title)
        head.addStretch()
        self.fold_btn = QToolButton()
        self.fold_btn.setText('⌄')
        self.fold_btn.setToolTip('접기 / 펴기')
        self.fold_btn.setAutoRaise(True)
        self.fold_btn.clicked.connect(self.toggle_fold)
        head.addWidget(self.fold_btn)
        lay.addLayout(head)
        self.body = QWidget()
        bl = QHBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(16)
        self.grid_w = QWidget()
        self.grid = QGridLayout(self.grid_w)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(2)
        bl.addWidget(self.grid_w)
        self.note = theme.StatusLabel('')
        self.plots = QStackedWidget()
        self.plots.setFixedHeight(PLOT_H)
        self.plots.setMinimumWidth(260)
        bl.addWidget(self.plots, 1)
        lay.addWidget(self.body)
        lay.addWidget(self.note)
        self._own = {}  # tab -> (FigureCanvas, Figure)
        self._pages = {}
        self.setVisible(False)

    # ---- plots --------------------------------------------------------------

    def _own_plot(self, tab):
        if tab not in self._own:
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
            from matplotlib.figure import Figure

            fig = Figure(figsize=(3, 1.5), dpi=100, layout='constrained')
            cv = FigureCanvasQTAgg(fig)
            cv.setMinimumHeight(PLOT_H - 10)
            self._own[tab] = (cv, fig)
            self.plots.addWidget(cv)
            self._pages[tab] = cv
        return self._own[tab]

    def _borrow(self, tab):
        """The tab's own plot (FRAP curve, profile, Coloc 2) shown here."""
        if tab in self._pages:
            return self._pages[tab]
        panel = getattr(self.win, BORROWED[tab], None)
        cv = getattr(panel, 'plot', None)
        if cv is None:
            return None
        cv.setMinimumHeight(PLOT_H - 10)
        self.plots.addWidget(cv)
        self._pages[tab] = cv
        return cv

    def adopt_plots(self):
        """Move the tab plots here once (the inspector keeps settings only)."""
        for tab in BORROWED:
            self._borrow(tab)

    # ---- state ------------------------------------------------------------------

    def toggle_fold(self):
        self.folded = not self.folded
        self.body.setVisible(not self.folded)
        self.note.setVisible(not self.folded and bool(self.note.text()))
        self.fold_btn.setText('⌃' if self.folded else '⌄')

    def schedule(self, *_):
        self._timer.start()

    def current_tab(self):
        for tab in TITLES:
            try:
                if self.win.tab_current(tab):
                    return tab
            except Exception:  # noqa: BLE001
                return None
        return None

    def refresh(self):
        tab = self.current_tab()
        it = self.win.current
        if tab is None or it is None:
            self.setVisible(False)
            self.tab = None
            return
        try:
            tiles, note, draw = getattr(self, f'_{tab}')(it)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            tiles, note, draw = [], ('', None), None
        if tab != self.tab:
            self._prev = {}
        self.tab = tab
        self.title.setText(TITLES[tab])
        self._show_tiles(tiles)
        self.note.setText(note[0])
        self.note.set_kind(note[1])
        self.note.setVisible(bool(note[0]) and not self.folded)
        page = self._pages.get(tab)
        if tab in BORROWED:
            page = self._borrow(tab)
        elif draw is not None:
            cv, fig = self._own_plot(tab)
            fig.clear()
            try:
                draw(fig)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            cv.draw_idle()
            page = cv
        if page is not None:
            self.plots.setCurrentWidget(page)
        self.plots.setVisible(page is not None)
        self.setVisible(True)

    def values(self) -> dict:
        return {k: v for k, v, _d in self.tiles}

    def _show_tiles(self, tiles):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.tiles = []
        for i, (label, v) in enumerate(tiles):
            prev = self._prev.get(label)
            delta = ''
            if isinstance(v, (int, float, np.integer, np.floating)) and isinstance(prev, (int, float, np.integer,
                                                                                            np.floating)):
                d = float(v) - float(prev)
                if np.isfinite(d) and abs(d) > 1e-12:
                    delta = f'{"+" if d > 0 else "−"}{_fmt(abs(d))}'
            big = QLabel(_fmt(v))
            theme.text_style(big, 'title-2')
            small = QLabel(label + (f'  ({delta})' if delta else ''))
            theme.secondary(small)
            r, c = divmod(i, 2)
            self.grid.addWidget(big, 2 * r, c)
            self.grid.addWidget(small, 2 * r + 1, c)
            self.tiles.append((label, v, delta))
            self._prev[label] = v

    # ---- per tab: (tiles, (note, kind), draw(fig) or None) ---------------------

    @staticmethod
    def _areas(labels, px_um):
        a = np.bincount(labels.ravel())[1:]
        return a[a > 0] * (px_um or 1.0) ** 2

    def _roi_tab(self, it):
        c = it.cells
        if c is None or not len(c):
            return [('세포', 0)], ('세포질 ROI 탭에서 ROI를 검출하세요.', None), None
        lab = c.labels
        areas = self._areas(lab, it.pixel_um)
        edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
        no_nuc = 0
        if c.nuclei is not None:
            have = set(np.unique(np.where(c.nuclei > 0, lab, 0))) - {0}
            no_nuc = len(set(np.unique(lab)) - {0} - have)
        rp = self.win.roi_panel
        lo, hi = getattr(rp, 'live_size_range', lambda: (None, None))()
        out = int(((areas < lo) | (areas > hi)).sum()) if lo is not None else None
        tiles = [('세포', len(c)), ('크기 범위 밖', out), ('가장자리 세포', len(edge)), ('핵 없는 세포', no_nuc)]
        unit = 'µm²' if it.pixel_um else 'px'

        def draw(fig):
            ax = fig.add_subplot(111)
            ax.hist(areas, bins=min(30, max(5, len(areas))), color='#7f7f7f')
            if lo is not None:
                for v in (lo, hi):
                    ax.axvline(v, color='#d62728', lw=1)
            ax.set_xlabel(f'세포 면적 ({unit})', fontsize=8)
            ax.tick_params(labelsize=7)
            for s in ('top', 'right'):
                ax.spines[s].set_visible(False)
        return tiles, ('', None), draw

    def _particle_tab(self, it):
        pp = self.win.particle_panel
        cells = pp.cells_for(it)
        parts = pp.particles_for(it) if cells is not None and len(cells) else None
        if parts is None or cells is None:
            return [('입자', 0)], ('입자 ROI 탭에서 입자 설정을 정하세요.', None), None
        comp = parts.components(cells)
        areas = self._areas(comp, it.pixel_um) if comp.max() else np.zeros(0)
        n = int(areas.size)
        px = (it.pixel_um or 1.0) ** 2
        small = int((areas <= 2 * px).sum())
        tiles = [('입자', n), ('세포당 입자', n / max(len(cells), 1)),
                 ('면적 중앙값', float(np.median(areas)) if n else None), ('작은 조각 (≤ 2 px)', small)]
        note = ('작은 조각이 많습니다 · 노이즈 의심', 'warning') if n and small > 0.3 * n else ('', None)
        unit = 'µm²' if it.pixel_um else 'px'

        def draw(fig):
            ax = fig.add_subplot(111)
            if n:
                ax.hist(areas, bins=np.geomspace(max(areas.min(), 1e-6), max(areas.max(), areas.min() * 1.01), 30),
                        color='#7f7f7f')
                ax.set_xscale('log')
            ax.axvline(2 * px, color='#d62728', lw=1)
            ax.set_xlabel(f'입자 면적 ({unit})', fontsize=8)
            ax.tick_params(labelsize=7)
            for s in ('top', 'right'):
                ax.spines[s].set_visible(False)
        return tiles, note, draw

    def _intensity_tab(self, it):
        ip = self.win.intensity_panel
        rows = ip.measure.current_rows()
        regs = {}
        for r in rows:
            a = r.get('Area', r.get('area_um2'))
            if isinstance(a, (int, float)):
                regs[str(r.get('region', ''))] = regs.get(str(r.get('region', '')), 0.0) + float(a)
        tiles = [(f'{k} 넓이', v) for k, v in list(regs.items())[:4]] or [('영역', 0)]
        return tiles, ('', None), None

    def _bands_tab(self, it):
        bp = self.win.bands_panel
        rows = bp.bands_measure.current_rows()
        cells = {r.get('roi') for r in rows}
        bands = {r.get('band') for r in rows}
        tiles = [('띠', len(bands)), ('잰 세포', len(cells))]
        x = 'distance_rel' if rows and 'distance_rel' in rows[0] else next(
            (k for k in (rows[0] if rows else {}) if k.startswith('distance')), '')
        y = next((k for k in (rows[0] if rows else {}) if k.endswith('_Mean') and '_particle_' not in k), '')
        roi = getattr(self.win.roi_panel, 'selected', None)
        sel = f'cell{roi:03d}' if isinstance(roi, int) and roi else None

        def draw(fig):
            ax = fig.add_subplot(111)
            if rows and x and y:
                by = {}
                for r in rows:
                    by.setdefault(r.get('roi'), []).append((r.get(x), r.get(y)))
                for k, v in by.items():
                    v = sorted(p for p in v if isinstance(p[0], (int, float)))
                    ax.plot([p[0] for p in v], [p[1] for p in v], color='#d62728' if k == sel else '#999999',
                            lw=1.5 if k == sel else 0.7)
                ax.set_xlabel(x, fontsize=8)
                ax.set_ylabel(y, fontsize=8)
            ax.tick_params(labelsize=7)
            for s in ('top', 'right'):
                ax.spines[s].set_visible(False)
        return tiles, ('', None), draw

    def _mito_tab(self, it):
        from .mito_panel import mito_live
        got = mito_live(self.win.mito_panel)
        if got is None:
            return [], ('분석 실행을 누르면 세포 · 조각 · 점 수가 여기 나옵니다.', 'info'), None
        tiles, r = got
        fp = [x.get('footprint_fraction') for x in r.cells]

        def draw(fig):
            ax = fig.add_subplot(111)
            v = [x for x in fp if isinstance(x, float) and x == x]
            if v:
                ax.hist(v, bins=min(20, max(5, len(v))), color='#c040c0')
            ax.set_xlabel('footprint fraction', fontsize=8)
            ax.set_ylabel('cells', fontsize=8)
            ax.tick_params(labelsize=7)
            for s_ in ('top', 'right'):
                ax.spines[s_].set_visible(False)
        return tiles, ('', None), draw

    def _track_tab(self, it):
        from .track_panel import track_live
        tp = self.win.track_panel
        got = track_live(tp)
        if got is None:
            return [], ('추적 실행을 누르면 트랙 수와 속도가 여기 나옵니다.' if it.nt > 1 else '', 'info'), None
        tiles, sel, ratio = got
        st = it.tracks
        y = ratio or next((k for k in (st.points[0] if st.points else {}) if k.startswith('I_')
                           and not k.endswith('_raw')), '')
        f_now = it.t + 1

        def draw(fig):
            ax = fig.add_subplot(111)
            tracks = st.tracks()
            pick = [sel] if sel else [v for _k, v in sorted(tracks.items(), key=lambda kv: -len(kv[1]))[:12]]
            for pts in pick:
                xs = [p['time_min'] for p in pts]
                ys = [p.get(y, np.nan) for p in pts]
                ax.plot(xs, ys, color='#d62728' if sel else '#999999', lw=1.5 if sel else 0.7)
            now = next((p['time_min'] for p in st.points if p['frame'] == f_now), None)
            if now is not None:
                ax.axvline(now, color='#555555', lw=0.6, ls=':')
            ax.set_xlabel('time (min)', fontsize=8)
            ax.set_ylabel(y, fontsize=8)
            ax.tick_params(labelsize=7)
            for s_ in ('top', 'right'):
                ax.spines[s_].set_visible(False)
        note = (f'선택한 트랙 T{sel[0]["track_id"]:03d} · {len(sel)} 프레임', 'info') if sel else ('', None)
        return tiles, note, draw if y else None

    def _frap_tab(self, it):
        fp = self.win.frap_panel
        c = fp.curve
        if c is None:
            return [('이동 분율', None)], ('FRAP 측정 탭에서 측정하세요.', None), None
        s = c.summary()
        drift = c.max_drift() if c.drift else None
        k = it.t
        cur = float(c.values[k]) if 0 <= k < len(c.values) else None
        tiles = [('이동 분율', s.get('mobile_fraction')), ('t½ (s)', s.get('half_time_s')),
                 ('현재 시점 회복', cur), ('최대 드리프트 (px)', drift)]
        note = ('피팅을 쓸 수 없습니다', 'warning') if c.fit is not None and not c.fit.ok else ('', None)
        return tiles, note, None

    def _profile_tab(self, it):
        p = self.win.profile_panel.profile
        if p is None:
            return [('선 길이', None)], ('이미지 위에 선을 그리세요.', None), None
        tiles = [(f'선 길이 ({p.unit})', p.length)]
        for name, v in list(zip(p.channels, p.values))[:3]:
            tiles.append((f'{name} 최대', float(np.nanmax(v)) if len(v) else None))
        return tiles, ('', None), None

    def _coloc_tab(self, it):
        rec = self.win.coloc_panel.current_record()
        if rec is None:
            return [('Pearson r', None)], ('Coloc 2 탭에서 계산하고 ROI를 고르세요.', None), None
        vals = {n: v for n, v, _ in rec.result.values}
        tiles = [('Pearson r', vals.get("Pearson's R value (no threshold)")),
                 ('Manders M1', vals.get("Manders' M1 (Above zero intensity of Ch2)")),
                 ('Manders M2', vals.get("Manders' M2 (Above zero intensity of Ch1)")), ('ROI', rec.roi)]
        return tiles, ('', None), None
