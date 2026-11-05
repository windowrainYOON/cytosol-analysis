"""파일 › 내보내기: write every chosen output of the chosen images into one
folder, without a file dialog per output (the window of export_dialog.py
collects the choices, ``run`` writes them).

``opts`` holds the output keys of ``export_dialog.KINDS`` (True = write it)
plus the format values (rgb_format, fps, all_times, markers, crop_which,
roi_format, graph_format) and ``per_image`` (one folder <stem>_<ID> per
image, else every file in the destination with unique stems)."""

from __future__ import annotations

import csv
import traceback
from pathlib import Path

from .lut import export_item, item_folder, item_stem, unique_stems


class Result:
    def __init__(self):
        self.files: list[str] = []
        self.errors: list[str] = []
        self.skipped: list[str] = []

    def add(self, f):
        if not f:
            return
        if isinstance(f, (list, tuple)):
            self.files += [str(x) for x in f if x]
        else:
            self.files.append(str(f))


def _kind_on(opts, *keys):
    return any(opts.get(k) for k in keys)


def run(win, items, out, opts, progress=None) -> Result:
    """Write the outputs; progress(i, n, label) -> False cancels."""
    from .coloc_panel import save_pdf_report, write_coloc_csv
    from .groups import GROUP_FILE, write_groups
    from .imageinfo import summarize
    from .info_panel import raw_metadata
    from .roi_panel import write_csv
    from .intensity import write_rows

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    res = Result()
    per = opts.get('per_image', True)
    stems = unique_stems(items)
    rp, pp, ip = win.roi_panel, win.particle_panel, win.intensity_panel
    bands = rp.bands
    roi_rows, coloc = [], []
    measured = {}  # box suffix -> rows of every image
    fmt = opts.get('graph_format', 'png')

    def where(it):
        return (out / item_folder(it), item_stem(it)) if per else (out, stems[id(it)])

    for i, it in enumerate(items):
        if progress is not None and progress(i, len(items), it.label) is False:
            res.skipped.append('취소됨')
            break
        folder, stem = where(it)
        try:
            # ---- images and crops ----
            img = _kind_on(opts, 'composite', 'channels', 'raw')
            crop_img = opts.get('crop_images') and it.crops
            if img or crop_img:
                crop_list = None
                if crop_img and opts.get('crop_which') == 'selected':
                    k = win._crop_sel if it is win.current else None
                    crop_list = [(k + 1, it.crops[k])] if k is not None and k < len(it.crops) else []
                kw = dict(scale=win.markers.scale_style() if opts.get('markers', True) else _no_scale(),
                          time=win.markers.time_style() if opts.get('markers', True) else _no_time(),
                          outline=win.markers.outline_style(export=True),
                          all_times=opts.get('all_times', True),
                          rgb_format=opts.get('rgb_format', 'tif'), fps=opts.get('fps', 10),
                          composite=opts.get('composite', True), per_channel=opts.get('channels', False),
                          raw_stack=opts.get('raw', True), stem=stem, bleach_file=img)
                if img:
                    res.add(export_item(it, folder, full=True, crops=False, **kw))
                if crop_img and (crop_list is None or crop_list):
                    res.add(export_item(it, folder, full=False, crops=True, crop_list=crop_list,
                                        crop_rois=False, **(kw | {'bleach_file': False})))
            if opts.get('crop_rois') and it.crops:
                from .crops import polys_of, save_crop_rois

                res.add(save_crop_rois(folder / f'{stem}_crops.zip', it.crops, it.id_properties(),
                                       polys_of(it)))
            # ---- 세포질 ROI ----
            has_cells = it.cells is not None and len(it.cells)
            if has_cells and _kind_on(opts, 'cell', 'nuc', 'cyto'):
                folder.mkdir(parents=True, exist_ok=True)
                kw = dict(cells=bool(opts.get('cell')), nuclei=bool(opts.get('nuc')),
                          cytosol=bool(opts.get('cyto')), properties=it.id_properties())
                if opts.get('roi_format') == 'roi':
                    res.add(it.cells.save(str(folder / f'{stem}.roi'), **kw))
                else:
                    res.add(it.cells.save(str(folder / f'{stem}_RoiSet.zip'), **kw))
                rows = [{'image': it.label, 'image_id': it.image_id, **r}
                        for r in it.cells.measurements()]
                write_csv(folder / f'{stem}_cell_rois.csv', rows)
                res.add(folder / f'{stem}_cell_rois.csv')
                roi_rows += rows
            for key, box in (('roi_csv', rp.measure), ('particle_csv', pp.measure),
                             ('intensity_csv', ip.measure), ('bands_csv', bands.bands_measure)):
                if opts.get(key) and box.has_rois(it):
                    folder.mkdir(parents=True, exist_ok=True)
                    rows = box.measure_item(it)
                    companions = bool(opts.get('roi_png')) if key == 'roi_csv' else False
                    res.add(box.save_item(it, folder, rows, companions=companions))
                    measured.setdefault(box.suffix, (box, []))[1].extend(rows)
            # ---- 입자 ROI ----
            if opts.get('particles'):
                pcells = pp.cells_for(it)
                p = pp.particles_for(it) if pcells is not None and len(pcells) else None
                if p is not None and p.mask.any():
                    folder.mkdir(parents=True, exist_ok=True)
                    res.add(pp.save_particle_files(it, folder / f'{stem}_particles.zip', pcells, p))
            if opts.get('regions') and has_cells:
                folder.mkdir(parents=True, exist_ok=True)
                res.add(ip._region_file(it, folder / stem))
            # ---- Coloc 2 ----
            if it.coloc and _kind_on(opts, 'coloc_csv', 'coloc_pdf'):
                folder.mkdir(parents=True, exist_ok=True)
                if opts.get('coloc_csv'):
                    write_coloc_csv(folder / f'{stem}_coloc2.csv', it.coloc)
                    res.add(folder / f'{stem}_coloc2.csv')
                    coloc += it.coloc
                if opts.get('coloc_pdf'):
                    for rec in it.coloc:
                        path = folder / f'{stem}_{rec.roi}_coloc2.pdf'
                        save_pdf_report(path, rec)
                        res.add(path)
            # ---- 이미지 정보 ----
            if opts.get('info_csv'):
                folder.mkdir(parents=True, exist_ok=True)
                path = folder / f'{stem}_info.csv'
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    csv.writer(f).writerows(summarize(it).rows_csv())
                res.add(path)
            if opts.get('info_raw'):
                folder.mkdir(parents=True, exist_ok=True)
                ext, text = raw_metadata(it)
                path = folder / f'{stem}_metadata.{ext}'
                path.write_text(text, encoding='utf-8')
                res.add(path)
        except Exception as exc:
            traceback.print_exc()
            res.errors.append(f'{it.label}: {exc}')
        if it is not win.current:
            it.image.release()

    # ---- files for the whole set ----
    try:
        if roi_rows:
            write_csv(out / 'cell_rois.csv', roi_rows)
            res.add(out / 'cell_rois.csv')
        if coloc:
            write_coloc_csv(out / 'coloc2.csv', coloc)
            res.add(out / 'coloc2.csv')
        for suffix, (box, rows) in measured.items():
            if len(items) > 1 and write_rows(out / f'{suffix}.csv', rows):
                res.add(out / f'{suffix}.csv')
            if box is pp.measure and not opts.get('particle_summary'):
                continue
            res.add(box.write_summaries(out, rows))
        if items and (per or len(items) > 1):
            write_groups(out / GROUP_FILE, items)
    except Exception as exc:
        traceback.print_exc()
        res.errors.append(str(exc))

    cur = win.current
    current_in = cur is not None and any(it is cur for it in items)
    # ---- the current image's views: bands graph, line profile, stack ----
    if current_in:
        folder, stem = where(cur)
        _try(res, lambda: _bands_plot(win, folder, stem, fmt) if opts.get('bands_plot') else None)
        _try(res, lambda: _profile(win, folder, stem, opts, fmt))
        _try(res, lambda: _stack(win, folder, stem, opts))
    elif _kind_on(opts, 'bands_plot', 'profile_csv', 'profile_plot', 'line_roi', 'projection', 'rotation') \
            and items:
        res.skipped.append('그래프 · 라인 프로파일 · 스택 투영은 현재 이미지가 대상에 있을 때만 저장합니다')
    # ---- FRAP ----
    if _kind_on(opts, 'frap_summary', 'frap_csv', 'frap_plot', 'frap_rois'):
        _try(res, lambda: _frap(win, items, out, opts))
    # ---- 그래프 편집 창 ----
    graphs = opts.get('graphs') or []
    if graphs:
        _try(res, lambda: _graphs(win, graphs, out, opts, fmt))
    # ---- 일괄 분석 ----
    if opts.get('batch_results') and win.batch.ran_at:
        from . import batch

        files, errors = batch.save_results(win, out / 'batch')
        res.add(files)
        res.errors += errors
    elif opts.get('batch_settings'):
        from . import batch

        batch.save_settings(win, out / 'batch_settings.json')
        res.add(out / 'batch_settings.json')
    # ---- project, work log ----
    if opts.get('project'):
        _try(res, lambda: (win.write_project_to(out / 'project.cyproj'), out / 'project.cyproj')[1])
    if opts.get('log'):
        _try(res, lambda: (win.worklog.write_csv(out / 'work_log.csv'), out / 'work_log.csv')[1])
    return res


def _try(res, fn):
    try:
        res.add(fn())
    except Exception as exc:
        traceback.print_exc()
        res.errors.append(str(exc))


def _no_scale():
    from .render import ScaleBarStyle

    s = ScaleBarStyle()
    s.enabled = False
    return s


def _no_time():
    from .render import TimeStampStyle

    s = TimeStampStyle()
    s.enabled = False
    return s


def _bands_plot(win, folder, stem, fmt):
    bp = win.roi_panel.bands
    if not bp.bands_measure._rows_shown()[0]:
        return None
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{stem}_bands.{fmt}'
    bp.fig.savefig(path, dpi=300)
    return path


def _profile(win, folder, stem, opts, fmt):
    from .lineprofile import write_profile_csv
    from .profile_panel import save_profile_companions, save_profile_figure

    pp = win.profile_panel
    if pp.profile is None or not _kind_on(opts, 'profile_csv', 'profile_plot', 'line_roi'):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    base = folder / f'{stem}_profile'
    if opts.get('profile_csv'):
        files.append(write_profile_csv(f'{base}.csv', pp.profile,
                                       dict(pp.item.id_properties(), plane=pp._z_text())))
    if opts.get('profile_plot'):
        path = f'{base}.{fmt}'
        save_profile_figure(path, pp.profile, pp._colors(), pp._visible(), pp.normalize.isChecked())
        files.append(path)
    if opts.get('line_roi'):
        files += save_profile_companions(f'{base}.csv', pp.item, pp.profile)
    return files


def _stack(win, folder, stem, opts):
    if not _kind_on(opts, 'projection', 'rotation'):
        return None
    files = []
    folder.mkdir(parents=True, exist_ok=True)
    if opts.get('projection'):
        files += win.save_projection('projection', stem=str(folder / stem), ask=False,
                                     movie=bool(opts.get('stack_mp4')))
    if opts.get('rotation') and win.stack_panel.mode_3d.isChecked():
        files += win.save_projection('rotation', stem=str(folder / stem), ask=False,
                                     movie=bool(opts.get('stack_mp4')))
    return files


def _frap(win, items, out, opts):
    from . import frap
    from .frap import FrapState

    fp = win.frap_panel
    gs = [g for g in fp.groups(items=items) if g is not None]
    if not gs:
        return None
    per = opts.get('per_image', True)
    by_label = {it.label: it for it in win.items}
    curves = [c for g in gs for c in g.members]
    files = []
    for c in curves:
        it = by_label.get(c.label)
        folder = out / item_folder(it) if (per and it is not None) else out
        stem = item_stem(it) if it is not None else c.label
        if opts.get('frap_csv'):
            files.append(frap.write_curve_csv(folder / f'{stem}_frap.csv', c))
        if opts.get('frap_plot'):
            files.append(frap.save_figure(folder / f'{stem}_frap.png',
                                          lambda ax, c=c: frap.draw_curve(ax, c, fp.fit.isChecked(), False)))
        if opts.get('frap_rois') and it is not None and isinstance(it.frap, FrapState):
            files.append(frap.save_rois(folder / f'{stem}_frap_rois.zip', it.frap.rois, it.id_properties()))
    if opts.get('frap_summary'):
        files.append(frap.write_summary_csv(out / 'frap_summary.csv', curves, gs))
        files.append(frap.write_group_curves_csv(out / 'frap_group_curves.csv', gs, fp.error.currentData()))
        files.append(fp.write_formulas(out / 'frap_formulas.txt', curves))
        for ext in ('.png', '.pdf'):
            files.append(fp.write_plot(out / f'frap_groups{ext}', groups=gs))
        files.append(frap.save_summary_figure(out / 'frap_summary.png', gs, fp.error.currentData()))
    return files


def _graphs(win, keys, out, opts, fmt):
    from . import graph as G

    files = []
    folder = out / 'graphs'
    docs = {d.key: d for d in win.graph_docs()}
    for key in keys:
        d = docs.get(key)
        tabs = d.tables() if d is not None else {}
        if not tabs:
            continue
        name = G.safe_name(d.title) or key
        folder.mkdir(parents=True, exist_ok=True)
        files.append(G.save_figure(folder / f'{name}.{fmt}', d.spec, tabs))
        if opts.get('g_data'):
            path = folder / f'{name}_plotted.csv'
            G.write_csv(path, G.plotted_table(d.spec, tabs))
            files.append(str(path))
            for t in tabs.values():
                path = folder / f'{name}_{G.safe_name(t.name)}.csv'
                G.write_csv(path, t)
                files.append(str(path))
        if opts.get('g_spec'):
            files.append(G.save_spec(folder / f'{name}_graph.json', d.spec))
    return files
