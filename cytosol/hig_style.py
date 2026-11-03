"""The app-wide style sheet of the Apple HIG design system (Desktop profile).

Every value comes from the design system: colours from the tokens in
`theme.TOKENS` (light / dark), sizes from `proportions.md` (Desktop column)
and the component READMEs.  The sheet is built once per colour scheme and
re-applied when the system switches between light and dark.

Component mapping (design system component → Qt widget):

==================  ==========================================================
Button              QPushButton: 28 high, radius 6, 12 padding, gray fill +
                    1 px separator; ``prominent`` = accent fill (1–2 a screen);
                    ``destructive`` = plain red text; checkable = tinted
TextField           QLineEdit / QPlainTextEdit: background-tertiary, 1 px
                    separator-opaque, radius 6, 8 padding, accent focus border
Select              QComboBox: TextField shape + chevron.up.chevron.down
NumberInput+Stepper QSpinBox / QDoubleSpinBox: end-aligned digits, stacked
                    chevrons 20 wide inside the field end
Toggle              QCheckBox: switch 38 × 22 (instant settings); inside a
                    dialog (applied on OK) a 16 px check box; QRadioButton 16
Box                 QGroupBox: background-tertiary (raised-2), radius 10, title
                    above the box (subhead 600, label-secondary)
TabView             QTabBar: segmented track (fill-secondary, radius 6), the
                    selected tab raised with weight 600
List / Table        item views: radius 10 wrapper (clipped), rows 28 (+ 2 px
                    inset highlight radius 6), selection = accent 16 % tint +
                    label text, hover 6 % tint (always different)
Menu / Tooltip      QMenu radius 12 (items 24, radius 6), QToolTip radius 6
Progress / Slider   6 px capsule, accent fill; slider knob 18
Surfaces            window and side panes background-secondary (level 1,
                    the material fallback), groups background-tertiary
                    (level 2), the centre content area ``background`` (0)
==================  ==========================================================

Not styled here (design system exclusion ``measurement-plots.md``): the image
canvas, matplotlib graphs and the Figure / graph previews.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from . import theme

# Desktop proportions (proportions.md, px)
CTL = 28  # control-md
CTL_SM = 24
PAD = 12  # control-pad
FIELD_PAD = 8
R_CTL = 6
R_GROUP = 10
R_WINDOW = 12
ROW = 28
SW_W, SW_H = 38, 22
CHECK = 16
STEPPER_W = 20
GAP_GROUP = 12
TH_H = 24
PROGRESS_H = 6


def rgba(name: str, scheme: str) -> str:
    c = theme._hex(theme.TOKENS[scheme][name])
    return f'rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})'


def _tint(name: str, alpha: float, scheme: str) -> str:
    """A colour token at a fixed share (states-and-interaction.md: hover 6 %,
    selection 16 %, chip 26 %)."""
    c = theme._hex(theme.TOKENS[scheme][name])
    return f'rgba({c.red()}, {c.green()}, {c.blue()}, {round(alpha * 255)})'


# ---- SF Symbols-style glyphs, written as SVG files for the style sheet ----

def _svg(body: str, w: int, h: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">{body}</svg>')


def _icons(scheme: str) -> dict[str, str]:
    t = theme.TOKENS[scheme]
    accent, white = t['blue'][:7], '#ffffff'
    fill = theme._hex(t['fill'])
    track = f'rgb({fill.red()},{fill.green()},{fill.blue()})'
    track_op = f'{fill.alphaF():.2f}'
    border = t['separator-opaque'][:7]
    sec = theme._hex(t['label-secondary'])
    chev = f'rgb({sec.red()},{sec.green()},{sec.blue()})'
    chev_op = f'{sec.alphaF():.2f}'
    knob_shadow = '<circle cx="{cx}" cy="11.5" r="9" fill="#000" fill-opacity="0.12"/>'
    base = t['background-tertiary'][:7]

    def switch(on: bool, disabled: bool = False):
        op = '0.4' if disabled else '1'
        cx = 27 if on else 11
        bg = (f'<rect x="0" y="0" width="38" height="22" rx="11" fill="{accent}"/>' if on else
              f'<rect x="0" y="0" width="38" height="22" rx="11" fill="{track}" '
              f'fill-opacity="{track_op}"/>')
        knob = (knob_shadow.format(cx=cx)
                + f'<circle cx="{cx}" cy="11" r="9" fill="{white}"/>')
        return _svg(f'<g opacity="{op}">{bg}{knob}</g>', SW_W, SW_H)

    def check(state: str, disabled: bool = False):
        op = '0.4' if disabled else '1'
        if state == 'off':
            body = (f'<rect x="0.5" y="0.5" width="15" height="15" rx="4" fill="{base}" '
                    f'stroke="{border}"/>')
        else:
            mark = ('<path d="M4 8.2 L6.8 11 L12 5" fill="none" stroke="#fff" '
                    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
                    if state == 'on' else
                    '<path d="M4.5 8 H11.5" stroke="#fff" stroke-width="2" '
                    'stroke-linecap="round"/>')
            body = f'<rect x="0" y="0" width="16" height="16" rx="4" fill="{accent}"/>{mark}'
        return _svg(f'<g opacity="{op}">{body}</g>', CHECK, CHECK)

    def radio(on: bool, disabled: bool = False):
        op = '0.4' if disabled else '1'
        body = (f'<circle cx="8" cy="8" r="8" fill="{accent}"/><circle cx="8" cy="8" r="3" '
                f'fill="#fff"/>' if on else
                f'<circle cx="8" cy="8" r="7.5" fill="{base}" stroke="{border}"/>')
        return _svg(f'<g opacity="{op}">{body}</g>', CHECK, CHECK)

    stroke = (f'fill="none" stroke="{chev}" stroke-opacity="{chev_op}" stroke-width="1.6" '
              'stroke-linecap="round" stroke-linejoin="round"')
    return {
        'switch_on': switch(True), 'switch_off': switch(False),
        'switch_on_dis': switch(True, True), 'switch_off_dis': switch(False, True),
        'check_on': check('on'), 'check_off': check('off'), 'check_mixed': check('mixed'),
        'check_on_dis': check('on', True), 'check_off_dis': check('off', True),
        'radio_on': radio(True), 'radio_off': radio(False),
        'radio_on_dis': radio(True, True), 'radio_off_dis': radio(False, True),
        'menu_check': _svg(f'<path d="M2.5 7.5 L5.5 10.5 L11.5 3.5" fill="none" '
                           f'stroke="{t["label"]}" stroke-width="1.8" stroke-linecap="round" '
                           'stroke-linejoin="round"/>', 14, 14),
        'menu_check_sel': _svg('<path d="M2.5 7.5 L5.5 10.5 L11.5 3.5" fill="none" '
                               'stroke="#ffffff" stroke-width="1.8" stroke-linecap="round" '
                               'stroke-linejoin="round"/>', 14, 14),
        'xmark': _svg(f'<path d="M3 3 L9 9 M9 3 L3 9" {stroke}/>', 12, 12),
        # chevron.up.chevron.down (Select)
        'updown': _svg(f'<path d="M3 5.5 L6 2.5 L9 5.5 M3 8.5 L6 11.5 L9 8.5" {stroke}/>', 12, 14),
        # Stepper halves
        'up': _svg(f'<path d="M2.5 5 L5 2.5 L7.5 5" {stroke}/>', 10, 7),
        'down': _svg(f'<path d="M2.5 2 L5 4.5 L7.5 2" {stroke}/>', 10, 7),
        # disclosure triangles (closed: pointing to the start → end; open: down)
        'tri_closed': _svg(f'<path d="M3.5 2 L7.5 5 L3.5 8 Z" fill="{chev}" '
                           f'fill-opacity="{chev_op}"/>', 10, 10),
        'tri_open': _svg(f'<path d="M2 3.5 L8 3.5 L5 7.5 Z" fill="{chev}" '
                         f'fill-opacity="{chev_op}"/>', 10, 10),
    }


def icon_dir(scheme: str) -> Path:
    d = Path(tempfile.gettempdir()) / f'cytosol-hig-{scheme}'
    d.mkdir(parents=True, exist_ok=True)
    for name, svg in _icons(scheme).items():
        p = d / f'{name}.svg'
        if not p.exists() or p.read_text(encoding='utf-8') != svg:
            p.write_text(svg, encoding='utf-8')
    return d


# ---- the style sheet ----------------------------------------------------------

# materials.md: regular sidebar material over the blurred desktop (macOS)
GLASS_ALPHA = 0.45


def stylesheet(scheme: str | None = None, glass: bool | None = None) -> str:
    from . import glass as _glass  # noqa: PLC0415

    s = scheme or theme.scheme()
    glass = _glass.active() if glass is None else glass
    c = lambda n: rgba(n, s)  # noqa: E731
    tint = lambda n, a: _tint(n, a, s)  # noqa: E731
    d = icon_dir(s).as_posix()
    url = lambda n: f'url("{d}/{n}.svg")'  # noqa: E731
    accent = c('blue')
    pressed_btn = tint('gray', 0.30)
    if glass:  # functional layer (side panes, status bar) see-through, content opaque
        surfaces = f"""
QMainWindow {{ background: transparent; }}
QWidget#hig_sidebar, QTabWidget#hig_inspector {{
    background: {tint('background-secondary', GLASS_ALPHA)}; }}
QStatusBar {{ background: {tint('background-secondary', GLASS_ALPHA)}; }}
"""
    else:
        surfaces = ''
    return f"""
/* ---- surfaces: grouped background → raised groups ---- */
QMainWindow, QDialog {{ background: {c('background-secondary')}; }}
QWidget#hig_content {{ background: {c('background')}; }}
QScrollArea, QScrollArea > QWidget > QWidget#qt_scrollarea_viewport,
QScrollArea > QWidget#qt_scrollarea_viewport {{ background: transparent; border: none; }}
QSplitter::handle {{ background: {c('separator-opaque')}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QStatusBar {{ background: {c('background-secondary')}; color: {c('label-secondary')}; }}
QStatusBar QLabel {{ color: {c('label-secondary')}; }}

/* ---- Box: grouped, rounded section with its title above ---- */
QGroupBox {{
    background: {c('background-tertiary')};
    border: 1px solid {c('separator')};
    border-radius: {R_GROUP}px;
    margin-top: 22px;
    padding: {GAP_GROUP}px {GAP_GROUP}px {GAP_GROUP - 2}px {GAP_GROUP}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 4px; top: 2px; padding: 0;
    color: {c('label-secondary')}; font-weight: 600;
}}
QGroupBox::indicator {{ width: {SW_W}px; height: {SW_H}px; }}
QGroupBox::indicator:checked {{ image: {url('switch_on')}; }}
QGroupBox::indicator:unchecked {{ image: {url('switch_off')}; }}

/* ---- Button ---- */
QPushButton {{
    min-height: {CTL - 2}px; padding: 0 {PAD}px;
    border: 1px solid {c('separator')}; border-radius: {R_CTL}px;
    background: {c('background-tertiary')}; color: {c('label')};
}}
QPushButton:hover {{ background: {tint('gray', 0.14)}; }}
QPushButton:pressed {{ background: {pressed_btn}; }}
QPushButton:checked {{
    background: {tint('blue', 0.16)}; border-color: {accent}; font-weight: 600;
}}
QPushButton:disabled {{ color: {c('label-tertiary')}; background: {c('fill-quaternary')}; }}
QPushButton:focus {{ border: 2px solid {accent}; padding: 0 {PAD - 1}px; }}
QPushButton[hig_prominent="true"] {{
    background: {accent}; color: {c('on-accent')}; border: 1px solid {accent};
    font-weight: 500;
}}
QPushButton[hig_prominent="true"]:hover {{ background: {tint('blue', 0.86)}; }}
QPushButton[hig_prominent="true"]:pressed {{ background: {tint('blue', 0.60)}; }}
QPushButton[hig_prominent="true"]:disabled {{ background: {tint('blue', 0.40)}; }}
QPushButton[hig_destructive="true"] {{
    background: transparent; border: 1px solid transparent; color: {c('red')};
}}
QPushButton[hig_destructive="true"]:hover {{ background: {tint('red', 0.08)}; }}
QPushButton[hig_destructive="true"]:pressed {{ background: {tint('red', 0.16)}; }}
QPushButton[hig_destructive="true"]:disabled {{ color: {tint('red', 0.40)}; }}
QDialogButtonBox QPushButton {{ min-width: 64px; }}
QToolButton {{
    min-height: {CTL - 2}px; min-width: {CTL - 2}px; border-radius: {R_CTL}px;
    border: 1px solid transparent; background: transparent; color: {c('label')};
}}
QToolButton:hover {{ background: {tint('gray', 0.14)}; }}
QToolButton:checked {{ background: {tint('blue', 0.16)}; }}

/* ---- TextField / Select / NumberInput ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox,
QAbstractSpinBox {{
    background: {c('background-tertiary')}; color: {c('label')};
    border: 1px solid {c('separator-opaque')}; border-radius: {R_CTL}px;
    selection-background-color: {tint('blue', 0.30)}; selection-color: {c('label')};
}}
QLineEdit, QComboBox {{ min-height: {CTL - 2}px; padding: 0 {FIELD_PAD}px; }}
QPlainTextEdit, QTextEdit {{ padding: 4px {FIELD_PAD - 2}px; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QAbstractSpinBox:focus {{ border: 2px solid {accent}; }}
QLineEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {{
    color: {c('label-tertiary')}; background: {c('fill-quaternary')};
}}
QComboBox {{ padding-right: {FIELD_PAD + 22}px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none;
}}
QComboBox::down-arrow {{ image: {url('updown')}; width: 12px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {c('background-tertiary')}; border: 1px solid {c('separator')};
    border-radius: {R_CTL}px; padding: 4px; outline: none;
    selection-background-color: {tint('blue', 0.16)}; selection-color: {c('label')};
}}
QAbstractSpinBox {{
    min-height: {CTL - 2}px; padding: 0 {STEPPER_W + 4}px 0 {FIELD_PAD}px;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border; width: {STEPPER_W}px; border: none;
    border-left: 1px solid {c('separator')}; background: transparent;
}}
QAbstractSpinBox::up-button {{ subcontrol-position: top right;
    border-top-right-radius: {R_CTL}px; border-bottom: 1px solid {c('separator')}; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right;
    border-bottom-right-radius: {R_CTL}px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: {tint('gray', 0.14)}; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{
    background: {pressed_btn}; }}
QAbstractSpinBox::up-arrow {{ image: {url('up')}; width: 10px; height: 7px; }}
QAbstractSpinBox::down-arrow {{ image: {url('down')}; width: 10px; height: 7px; }}

/* ---- Toggle: switch for instant settings, check box in dialogs ---- */
QCheckBox {{ spacing: 8px; min-height: {SW_H}px; }}
QCheckBox::indicator {{ width: {SW_W}px; height: {SW_H}px; }}
QCheckBox::indicator:checked {{ image: {url('switch_on')}; }}
QCheckBox::indicator:unchecked, QCheckBox::indicator:indeterminate {{
    image: {url('switch_off')}; }}
QCheckBox::indicator:checked:disabled {{ image: {url('switch_on_dis')}; }}
QCheckBox::indicator:unchecked:disabled {{ image: {url('switch_off_dis')}; }}
QDialog QCheckBox {{ spacing: 6px; min-height: {CHECK}px; }}
QDialog QCheckBox::indicator {{ width: {CHECK}px; height: {CHECK}px; }}
QDialog QCheckBox::indicator:checked {{ image: {url('check_on')}; }}
QDialog QCheckBox::indicator:unchecked {{ image: {url('check_off')}; }}
QDialog QCheckBox::indicator:indeterminate {{ image: {url('check_mixed')}; }}
QDialog QCheckBox::indicator:checked:disabled {{ image: {url('check_on_dis')}; }}
QDialog QCheckBox::indicator:unchecked:disabled {{ image: {url('check_off_dis')}; }}
QRadioButton {{ spacing: 6px; }}
QRadioButton::indicator {{ width: {CHECK}px; height: {CHECK}px; }}
QRadioButton::indicator:checked {{ image: {url('radio_on')}; }}
QRadioButton::indicator:unchecked {{ image: {url('radio_off')}; }}
QRadioButton::indicator:checked:disabled {{ image: {url('radio_on_dis')}; }}
QRadioButton::indicator:unchecked:disabled {{ image: {url('radio_off_dis')}; }}

/* ---- TabView: segmented tab row ---- */
QTabWidget::pane {{ border: none; background: transparent; top: 0; }}
QTabWidget::tab-bar {{ alignment: center; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    min-height: {CTL_SM}px; padding: 0 {PAD - 2}px; margin: 4px 1px 8px 1px;
    border: none; border-radius: {R_CTL - 2}px;
    background: {c('fill-secondary')}; color: {c('label')};
}}
QTabBar::tab:hover {{ background: {c('fill')}; }}
QTabBar::tab:selected {{
    background: {c('background-tertiary')}; font-weight: 600;
    border: 1px solid {c('separator')};
}}
QTabBar::close-button {{ subcontrol-position: right; }}
QTabBar QToolButton {{ background: {c('background-secondary')}; }}
QTabBar::close-button {{ image: {url('xmark')}; width: 12px; height: 12px;
    border-radius: 3px; margin-left: 4px; }}
QTabBar::close-button:hover {{ background: {c('fill')}; }}

/* ---- List / Table / Tree ---- */
QAbstractItemView {{
    background: {c('background-tertiary')}; color: {c('label')};
    alternate-background-color: {c('fill-quaternary')};
    border: 1px solid {c('separator')}; border-radius: {R_GROUP}px;
    outline: none; padding: 2px;
    selection-background-color: {tint('blue', 0.16)}; selection-color: {c('label')};
}}
QListView::item, QTreeView::item {{
    min-height: {ROW - 4}px; padding: 2px {FIELD_PAD}px; border-radius: {R_CTL}px;
}}
QListView::item:hover, QTreeView::item:hover, QTableView::item:hover {{
    background: {tint('blue', 0.06)}; }}
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {{
    background: {tint('blue', 0.16)}; color: {c('label')};
}}
QTreeView::branch {{ background: transparent; }}
QTreeView::branch:has-children:closed {{ image: {url('tri_closed')}; }}
QTreeView::branch:has-children:open {{ image: {url('tri_open')}; }}
QTableView {{ gridline-color: {c('separator')}; }}
QTableView QTableCornerButton::section {{ background: transparent; border: none; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{
    min-height: {TH_H}px; padding: 0 {FIELD_PAD + 2}px;
    background: {c('background-tertiary')}; color: {c('label-secondary')};
    font-weight: 600; border: none; border-bottom: 1px solid {c('separator')};
}}
QHeaderView::section:vertical {{ border-bottom: none; border-right: 1px solid {c('separator')}; }}

/* ---- Menu / Tooltip ---- */
QMenuBar {{ background: {c('background-secondary')}; }}
QMenuBar::item {{ padding: 4px 8px; border-radius: {R_CTL}px; background: transparent; }}
QMenuBar::item:selected {{ background: {c('fill-secondary')}; }}
QMenu {{
    background: {c('background-tertiary')}; border: 1px solid {c('separator')};
    border-radius: {R_WINDOW}px; padding: 4px;
}}
QMenu::item {{ min-height: {CTL_SM}px; padding: 0 24px 0 22px; border-radius: {R_CTL}px; }}
QMenu::item:selected {{ background: {accent}; color: {c('on-accent')}; }}
QMenu::item:disabled {{ color: {c('label-tertiary')}; }}
QMenu::separator {{ height: 1px; background: {c('separator')}; margin: 4px 10px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 4px; }}
QMenu::indicator:checked {{ image: {url('menu_check')}; }}
QMenu::indicator:checked:selected {{ image: {url('menu_check_sel')}; }}
QAbstractItemView::indicator {{ width: {CHECK}px; height: {CHECK}px; }}
QAbstractItemView::indicator:checked {{ image: {url('check_on')}; }}
QAbstractItemView::indicator:unchecked {{ image: {url('check_off')}; }}
QAbstractItemView::indicator:indeterminate {{ image: {url('check_mixed')}; }}
QToolTip {{
    background: {c('background-tertiary')}; color: {c('label')};
    border: 1px solid {c('separator')}; border-radius: {R_CTL}px; padding: 3px 8px;
}}

/* ---- Progress / Slider / Scroll bars ---- */
QProgressBar {{
    max-height: {PROGRESS_H}px; min-height: {PROGRESS_H}px; border: none;
    border-radius: {PROGRESS_H // 2}px; background: {c('fill')}; text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {accent}; border-radius: {PROGRESS_H // 2}px; }}
QSlider::groove:horizontal {{ height: 4px; background: {c('fill')}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::groove:vertical {{ width: 4px; background: {c('fill')}; border-radius: 2px; }}
QSlider::add-page:vertical {{ background: {accent}; border-radius: 2px; }}
QSlider::handle {{
    background: {c('on-accent')}; border: 1px solid {c('separator-opaque')};
    width: 16px; height: 16px; border-radius: 9px;
}}
QSlider::handle:horizontal {{ margin: -7px 0; }}
QSlider::handle:vertical {{ margin: 0 -7px; }}
QSlider::handle:hover {{ border-color: {accent}; }}
QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
QScrollBar::handle {{ background: {c('fill')}; border-radius: 3px; min-height: 24px;
    min-width: 24px; }}
QScrollBar::handle:hover {{ background: {c('gray')}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- materials ---- */
{surfaces}
/* ---- excluded: measurement plots and the image canvas keep their look ---- */
QGraphicsView {{ border: none; border-radius: 0; padding: 0; }}
"""
