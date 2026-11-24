import sys
sys.path.insert(0, '/Users/changwooyoon/Developer/cytosol-analysis')
W = sys.argv[1]; OUT = sys.argv[2]; FILE = sys.argv[3]; SHEET = sys.argv[4] if len(sys.argv) > 4 else ''
sys.path.insert(0, W)
from cytosol import selftest2 as S
app = S._app()
from cytosol import theme; theme.apply(app)
app, win = S._window()
from cytosol import i18n; i18n.install(); i18n.set_language('ko')
from PySide6.QtWidgets import QScrollArea, QFrame, QLabel, QVBoxLayout
from cytosol import graph as G, graph_editors as E
import import_page as IP
gw = win.graph_window()
page = IP.ImportPage(FILE)
if SHEET:
    page.sheet.setCurrentText(SHEET)
t = page.result()
data = G.GraphData(t.name, [t], G.GraphSpec(), G.safe_name(t.name))
wz = E.GraphWizard(t.name, data, gw)
wz.bar.steps = ('표 가져오기',) + E.GraphWizard.STEPS
wz.bar.set_step(0)
sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame); sc.setWidget(page); theme.unify(page)
wz.pages.insertWidget(0, sc); wz.pages.setCurrentIndex(0)
wz.pages.setFixedWidth(760)
wz.prev_b.setEnabled(False)
right = next(l for l in wz.findChildren(QVBoxLayout) if l.indexOf(wz.preview) >= 0)
wz.preview.hide()
for k in range(right.count()):
    w = right.itemAt(k).widget()
    if isinstance(w, QLabel):
        w.hide()
gc = IP.GroupCard(page); theme.unify(gc)
right.insertWidget(0, gc, 1)
wz.resize(1240, 900)
wz.show()
for _ in range(10): app.processEvents()
wz.grab().save(OUT)
print('saved', page.result(gc.groups()).columns)
