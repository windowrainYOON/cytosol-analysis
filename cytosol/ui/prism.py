"""PrismStyle — the fixed look of every measurement graph (design system
exception "Prism 양식", measurement-plots.md, owner decision 2026-11-25).

Graphs keep the GraphPad-Prism-like paper look the app has always drawn;
the UI tokens (accent, label colours, fonts of the windows) do not apply to
them. Used by the graph window, the live-box plots, the wizard / statistics
previews and the FRAP / band / track figures (PNG / PDF). The window,
inspector and chips around a graph follow the design system as usual.

These values are the defaults of ``graph.GraphSpec`` / ``graph.Series``;
a graph's own settings (모양 tab) can still change them per graph.
"""
from __future__ import annotations

BACKGROUND = '#ffffff'
SIZE_IN = (5.0, 3.6)
DPI = 300
SPINE_TOP = False
SPINE_RIGHT = False
SPINE_W = 0.8           # left + bottom axes only
GRID = False
GRID_COLOR = '#d9d9d9'
TICK_DIR = 'out'
TICK_MAJOR = 3.5
TICK_MINOR = 2.0
PALETTE = ['#000000', '#d62728', '#1f77b4', '#2ca02c', '#9467bd', '#ff7f0e', '#8c564b',
           '#e377c2', '#17becf', '#7f7f7f', '#bcbd22']  # black first
LINE_W = 1.0
MARKER = 'o'
MARKER_SIZE = 4.0
MARKER_EDGE = 0.8
ERR_W = 0.8
CAPSIZE = 2.0
TITLE_PT = 11.0
LABEL_PT = 9.0
TICK_PT = 8.0
LEGEND_PT = 8.0
LEGEND_FRAME = False
STATS_LINE_W = 1.0      # significance brackets (bent ends)
STATS_PT = 10.0         # stars / p
