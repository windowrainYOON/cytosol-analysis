"""Liquid Glass / sidebar material behind the main window (macOS).

The design system's materials.md puts glass only on the functional layer
floating over the content (sidebar, toolbar, inspector) and, on the Desktop,
blends the sidebar material with what is behind the window.  Qt cannot blur
by itself, so on macOS the window gets an AppKit ``NSVisualEffectView``
(material *sidebar*, blending *behind window*, following the window's active
state) under the Qt view, and the style sheet paints the side panes with a
see-through tint while the centre content layer stays opaque.

It is skipped (opaque ``background-secondary`` fallback, as materials.md asks)
when pyobjc is missing, on other platforms, and when the user turned on
Reduce Transparency.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt

_active = False


def available() -> bool:
    if sys.platform != 'darwin':
        return False
    try:
        import AppKit  # noqa: F401, PLC0415
        import objc  # noqa: F401, PLC0415
    except Exception:
        return False
    return not reduce_transparency()


def reduce_transparency() -> bool:
    try:
        from AppKit import NSWorkspace  # noqa: PLC0415

        return bool(NSWorkspace.sharedWorkspace()
                    .accessibilityDisplayShouldReduceTransparency())
    except Exception:
        return False


def active() -> bool:
    return _active


def prepare(window) -> bool:
    """Before the window is first shown: let the window be see-through."""
    if not available():
        return False
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    return True


def attach(window) -> bool:
    """After the window is shown: put the sidebar material under the Qt view."""
    global _active
    if not available():
        return False
    try:
        import objc  # noqa: PLC0415
        from AppKit import (  # noqa: PLC0415
            NSColor,
            NSViewHeightSizable,
            NSViewWidthSizable,
            NSVisualEffectBlendingModeBehindWindow,
            NSVisualEffectMaterialSidebar,
            NSVisualEffectStateFollowsWindowActiveState,
            NSVisualEffectView,
            NSWindowBelow,
        )

        view = objc.objc_object(c_void_p=int(window.winId()))
        ns_window = view.window()
        if ns_window is None:
            return False
        content = ns_window.contentView()
        frame = content.superview() or content
        fx = NSVisualEffectView.alloc().initWithFrame_(frame.bounds())
        fx.setMaterial_(NSVisualEffectMaterialSidebar)
        fx.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        fx.setState_(NSVisualEffectStateFollowsWindowActiveState)
        fx.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        if frame is content:
            content.addSubview_positioned_relativeTo_(fx, NSWindowBelow, None)
        else:
            frame.addSubview_positioned_relativeTo_(fx, NSWindowBelow, content)
        ns_window.setOpaque_(False)
        ns_window.setBackgroundColor_(NSColor.clearColor())
        _active = True
    except Exception:
        import traceback  # noqa: PLC0415

        traceback.print_exc()
        _active = False
    return _active
