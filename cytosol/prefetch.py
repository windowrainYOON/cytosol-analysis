"""Background loading of timepoints while the T slider is dragged.

A worker thread reads the plane of the current Z (or MIP) for the timepoint
the slider points at, so the window never freezes during a drag: when the
slider moves on before a read finishes, only the newest position is read
next. The last few planes are kept, so going back and forth is instant;
nothing else is read ahead, so memory use stays small.
"""

from __future__ import annotations

import threading
import traceback
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QObject, Signal

KEEP = 4  # recent planes kept for one image and Z


def plane_at(image, t: int, z) -> np.ndarray:
    """(C, Y, X) float32 plane z of timepoint t, without changing image.t."""
    if image.lazy:
        return image.plane_loader(t, z)
    vol = image.data if t == image.t else image.loader(t)
    if z == 'mip':
        return vol.max(axis=1)
    if z == 'mid':
        return vol[:, vol.shape[1] // 2]
    return vol[:, int(z)]


class TimeCache(QObject):
    """Loads the wanted timepoint of one image at one Z in a thread."""

    ready = Signal(object, int)  # item, t: that timepoint's plane is now loaded

    def __init__(self, keep: int = KEEP, parent=None):
        super().__init__(parent)
        self.keep = keep
        self._cv = threading.Condition()
        self._item = None
        self._z = None
        self._want = None  # timepoint to load next (the newest slider position)
        self._store: OrderedDict[int, np.ndarray] = OrderedDict()
        threading.Thread(target=self._run, name='time-loader', daemon=True).start()

    # ---- main thread ------------------------------------------------------

    def follow(self, item, t: int | None = None):
        """Load timepoint t (None: just track item and its Z) of item; None stops."""
        with self._cv:
            if item is None or item.nt < 2:
                self._item, self._z, self._want = None, None, None
                self._store.clear()
            else:
                if item is not self._item or item.z != self._z:
                    self._item, self._z = item, item.z
                    self._store.clear()
                self._want = None if t is None else int(t)
            self._cv.notify()

    def get(self, item, t: int):
        """The loaded plane of timepoint t at the item's current Z, or None."""
        with self._cv:
            if item is self._item and item.z == self._z:
                planes = self._store.get(int(t))
                if planes is not None:
                    self._store.move_to_end(int(t))
                return planes
        return None

    def put(self, item, t: int, z, planes: np.ndarray):
        """Keep a plane read elsewhere (the current timepoint)."""
        with self._cv:
            if item is self._item and z == self._z:
                self._keep(int(t), planes)

    def cached(self, item) -> int:
        with self._cv:
            return len(self._store) if item is self._item else 0

    # ---- shared ------------------------------------------------------------

    def _keep(self, t, planes):
        self._store[t] = planes
        self._store.move_to_end(t)
        while len(self._store) > self.keep:
            self._store.popitem(last=False)

    # ---- worker thread -------------------------------------------------------

    def _run(self):
        while True:
            with self._cv:
                while self._item is None or self._want is None or self._want in self._store:
                    self._cv.wait()
                item, z, t = self._item, self._z, self._want
            try:
                planes = np.asarray(plane_at(item.image, t, z), np.float32)
            except Exception:
                traceback.print_exc()
                with self._cv:
                    if item is self._item and self._want == t:
                        self._want = None
                continue
            with self._cv:
                if item is not self._item or z != self._z:
                    continue
                self._keep(t, planes)
            self.ready.emit(item, t)
