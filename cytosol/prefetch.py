"""Background read-ahead of a time series.

While an image with several timepoints is shown, a worker thread reads the
plane of the current Z (or MIP) for every timepoint, nearest to the current
one first, and keeps them in memory up to a byte budget. Dragging the T
slider then only has to draw a plane that is already there.
"""

from __future__ import annotations

import threading
import time
import traceback

import numpy as np
from PySide6.QtCore import QObject, Signal

BUDGET_BYTES = 2 << 30  # planes kept in memory for one image and Z
# after switching image or Z, wait this long before reading ahead, so browsing
# Z (which reads from the same file) does not queue behind the worker
START_DELAY_S = 0.4


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
    """Planes of every timepoint of one image at one Z, read ahead in a thread."""

    ready = Signal(object, int)  # item, t: that timepoint's plane is now cached

    def __init__(self, budget: int = BUDGET_BYTES, parent=None):
        super().__init__(parent)
        self.budget = budget
        self._cv = threading.Condition()
        self._item = None
        self._z = None
        self._center = 0
        self._store: dict[int, np.ndarray] = {}
        self._failed: set[int] = set()
        self._plane_bytes = 0
        self._not_before = 0.0
        threading.Thread(target=self._run, name='time-read-ahead', daemon=True).start()

    # ---- main thread ------------------------------------------------------

    def follow(self, item, t: int | None = None):
        """Read ahead for item at its current Z around timepoint t (None: stop)."""
        with self._cv:
            if item is None or item.nt < 2:
                self._item, self._z = None, None
                self._store.clear()
            else:
                if item is not self._item or item.z != self._z:
                    self._item, self._z = item, item.z
                    self._store.clear()
                    self._failed.clear()
                    self._not_before = time.monotonic() + START_DELAY_S
                self._center = item.t if t is None else int(t)
                self._trim()
            self._cv.notify()

    def get(self, item, t: int):
        """The cached plane of timepoint t at the item's current Z, or None."""
        with self._cv:
            if item is self._item and item.z == self._z:
                return self._store.get(int(t))
        return None

    def put(self, item, t: int, z, planes: np.ndarray):
        """Offer a plane read elsewhere (kept when it is the one being read ahead)."""
        with self._cv:
            if item is self._item and z == self._z and int(t) in self._window():
                self._keep(int(t), planes)

    def cached(self, item) -> int:
        with self._cv:
            return len(self._store) if item is self._item else 0

    # ---- shared ------------------------------------------------------------

    def _capacity(self) -> int:
        if not self._plane_bytes:
            return 1
        return max(1, self.budget // self._plane_bytes)

    def _window(self) -> list[int]:
        """Timepoints to keep, nearest to the current one first."""
        nt = self._item.nt
        order = sorted(range(nt), key=lambda t: (abs(t - self._center), t < self._center))
        return order[:self._capacity()]

    def _trim(self):
        if self._item is None:
            return
        keep = set(self._window())
        for t in [t for t in self._store if t not in keep]:
            del self._store[t]

    def _keep(self, t, planes):
        self._plane_bytes = self._plane_bytes or planes.nbytes
        self._store[t] = planes
        self._trim()

    # ---- worker thread -------------------------------------------------------

    def _next(self):
        """(item, z, t) to read next, or None when everything wanted is cached."""
        if self._item is None:
            return None
        for t in self._window():
            if t not in self._store and t not in self._failed:
                return self._item, self._z, t
        return None

    def _run(self):
        while True:
            with self._cv:
                while True:
                    job = self._next()
                    wait = self._not_before - time.monotonic()
                    if job is not None and wait <= 0:
                        break
                    self._cv.wait(wait if job is not None else None)
            item, z, t = job
            try:
                planes = np.asarray(plane_at(item.image, t, z), np.float32)
            except Exception:
                traceback.print_exc()
                with self._cv:
                    if item is self._item:
                        self._failed.add(t)
                continue
            with self._cv:
                if item is not self._item or z != self._z:
                    continue
                self._keep(t, planes)
                stored = t in self._store
            if stored:
                self.ready.emit(item, t)
