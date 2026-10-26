"""강도 측정 tab: regions set by logic over every cell's cell / nucleus /
cytosol / particle ROIs (cytosol.intensity), drawn on the image, and their
ImageJ Measure values. The current image's table follows the ROIs, plane and
particle settings as they change; a button runs the same on every image, and
both can be saved together with the regions as ImageJ ROIs."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .intensity import (
    ExpressionError,
    make_regions,
    parse_region,
    region_names,
    region_outlines,
    save_regions,
)
from .measure_box import MeasureBox, uses_particles

EXPR_HELP = ('세미콜론(;)으로 여러 식을 나눕니다. 이름: cell(세포), nuc(핵), cyto(세포질), '
             'particle(입자). 연산: & 교집합, | 합집합, - 빼기, 괄호. '
             '예: cyto - particle;  cell & particle;  (cell - nuc) | particle')


class IntensityPanel(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.item = None
        self._hidden = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self.draw_regions)
        lay = QVBoxLayout(self)

        help_ = QLabel('세포질 ROI와 입자 ROI를 논리식으로 묶어 새 영역을 만들고, 세포마다 그 영역의 '
                       '채널별 강도를 원본값으로 잽니다 (ImageJ Measure와 같은 값). 세포·핵·세포질은 '
                       '세포질 ROI 탭에서, 입자는 입자 ROI 탭에서 따로 잴 수 있습니다.')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray; font-size: 11px;')
        lay.addWidget(help_)

        reg = QGroupBox('논리식 영역')
        rl = QVBoxLayout(reg)
        self.expr = QLineEdit()
        self.expr.setPlaceholderText('예: cyto - particle; cell & particle')
        self.expr.setToolTip(EXPR_HELP)
        self.expr.textChanged.connect(self.schedule)
        rl.addWidget(self.expr)
        self.expr_info = QLabel(EXPR_HELP)
        self.expr_info.setWordWrap(True)
        self.expr_info.setStyleSheet('color: gray; font-size: 11px;')
        rl.addWidget(self.expr_info)
        self.show_regions = QCheckBox('이미지에 영역 표시 (청록색)')
        self.show_regions.setChecked(True)
        self.show_regions.toggled.connect(self.schedule)
        rl.addWidget(self.show_regions)
        lay.addWidget(reg)

        self.measure = MeasureBox(win, 'intensity_tab', self.regions_for, 'intensity',
                                  '논리 영역 강도 측정', extra_files=self._region_file,
                                  overlay_regions=self.regions_for)
        lay.addWidget(self.measure, 1)

    # ---- helpers ----------------------------------------------------------

    def schedule(self, *_):
        self._timer.start()
        self.measure.schedule()

    def visible_tab(self) -> bool:
        return self.measure.visible_tab()

    def overlay_changed(self, hidden=False):
        """Called whenever the ROI overlay is redrawn (edits, plane changes)."""
        self._hidden = hidden
        self.schedule()

    def expressions(self) -> tuple[list[str], list[str]]:
        """(valid expressions, error messages)."""
        ok, bad = [], []
        for e in self.expr.text().split(';'):
            e = e.strip()
            if not e:
                continue
            try:
                parse_region(e)
                ok.append(e)
            except ExpressionError as exc:
                bad.append(f'“{e}”: {exc}')
        return ok, bad

    def regions_for(self, item):
        """Logic regions of an image; ones using particles only when it has them."""
        exprs, _ = self.expressions()
        regions = make_regions([], exprs)
        if item.particles is None and item.particle_settings is None:
            regions = [r for r in regions if 'particle' not in region_names(r.tree)]
        return regions

    def _region_file(self, it, stem) -> list[str]:
        regions = self.regions_for(it)
        if not regions:
            return []
        particles = self.measure.particles_for(it) if uses_particles(regions) else None
        f = save_regions(f'{stem}_regions.zip', it.cells, regions, particles,
                         it.id_properties())
        return [f] if f else []

    def draw_regions(self):
        _, bad = self.expressions()
        self.expr_info.setText('\n'.join(bad) if bad else EXPR_HELP)
        self.expr_info.setStyleSheet(f'color: {"#b35c00" if bad else "gray"}; font-size: 11px;')
        canvas = self.win.canvas
        it = self.win.current
        if (self._hidden or it is None or it.cells is None or not len(it.cells)
                or not self.show_regions.isChecked() or not self.visible_tab()
                or self.win._stack_on()):
            canvas.show_regions([])
            return
        regions = self.regions_for(it)
        particles = self.measure.particles_for(it) if uses_particles(regions) else None
        canvas.show_regions(region_outlines(it.cells, regions, particles) if regions else [])

    def bind(self, item):
        self.item = item
        self.draw_regions()
        self.measure.bind(item)
