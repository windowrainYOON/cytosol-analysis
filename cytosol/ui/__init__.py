"""Component library of Cytosol Viewer (design system "Apple HIG", v0.75).

Screens (panels, windows) only assemble these components; a difference
between two places is a variant value, never a new widget class in a screen
file (reuse rules, design system ``reuse.md``). The modules:

==================  ========================================================
``window``          Window: alert / prompt / progress / task / settings /
                    wizard / results / document (``RoundedDialog`` …)
``dialogs``         the alert / prompt / progress variants as functions
                    with the Qt static-dialog signatures
``fields``          Field variants ``FloatEdit``, ``TextArea``
``color_well``      ColorWell (row / header / inline), ``RgbColorWell``
``histogram``       Histogram (lut / threshold / mini)
``steps``           Steps (hig-steps chip row)
``segmented``       Segmented (two to four choices on one capsule)
``empty``           EmptyState
``overlay``         CanvasOverlay pen table (data colours, measurement-plots)
``scrubber``        Scrubber (canvas Z / T capsule)
``tables``          Table variant ``check`` (check column with select-all)
``legend``          Legend (beside a live plot)
``prism``           PrismStyle: the fixed look of every measurement graph
==================  ========================================================

The existing shared modules keep their place and are part of the library:
``hig_widgets`` (IconButton, Chip, ChipTabs, PaneSplitter), ``flow``
(FlowLayout), ``measure_bar`` (ActionBar = MeasureBar, DataRows),
``theme`` (switch, chip, slider_field, auto_value, StatusLabel, hint …).
"""
from .dialogs import (  # noqa: F401
    Alert, Progress, Prompt, choose, confirm_destructive, critical, destructive_alert,
    get_double, get_int, get_item, get_multiline_text, get_text, information, question,
    warning)
from .window import (  # noqa: F401
    DocumentWindow, ResultsWindow, RoundedDialog, SettingsWindow, WizardWindow, ask)
