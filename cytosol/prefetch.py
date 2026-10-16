"""Background loading of timepoints for the T slider.

A worker thread first serves the timepoint the dragged slider points at, so
the window never freezes during a drag (when the slider moves on before a
read finishes, only the newest position is read next). Where the image has a
faster approximate reader (``Image.preview_loader``, the TCF FL MIP), the
drag draws with it and the exact plane is read when the slider stops.

Images with a Z stack and a time axis also get read-ahead: once the slider
is idle, the worker reads the current Z (or MIP) of every timepoint, nearest
first: a quick preview of each one first where the image has one, then the
exact planes, up to READ_AHEAD_BYTES, so scrubbing only
draws. Planes are kept per (Z, t): after moving Z and back (right-drag on
the image moves both), the planes read for the earlier Z are still there
until the budget needs their room. A Z stack is what makes a timepoint slow to compute (FL resampling,
projections); single-plane time series are cheap and keep only the last few
planes, so they use little memory.
"""

from __future__ import annotations

import threading
import time
import traceback
from collections import OrderedDict

import numpy as np
from PySide6.QtCore import QObject, Signal

KEEP = 4  # recent planes kept when there is no read-ahead
READ_AHEAD_BYTES = 1536 << 20  # planes of one image and Z read ahead (Z-stack files)
# after switching image or Z, wait this long before reading ahead, so browsing
# Z (which reads from the same file) does not queue behind the worker
START_DELAY_S = 0.4
# while the slider moves, read ahead only after it has rested this long, so a
# slow exact read never holds up the next slider position
SLIDER_QUIET_S = 0.15


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


def preview_at(image, t: int, z):
    """(planes, exact): the quickest plane z of timepoint t for drawing."""
    if image.preview_loader is not None and z == 'mip':
        return image.preview_loader(t, z), False
    return plane_at(image, t, z), True


def reads_ahead(item) -> bool:
    """Whether the item's timepoints are read ahead: a time series with a Z stack."""
    return item.nt > 1 and item.nz > 1


class TimeCache(QObject):
    """Planes of one image at one Z for the T slider, loaded in a thread."""

    ready = Signal(object, int)  # item, t: that timepoint's plane is now loaded

    def __init__(self, keep: int = KEEP, budget: int = READ_AHEAD_BYTES, parent=None):
        super().__init__(parent)
        self.keep = keep
        self.budget = budget
        self._cv = threading.Condition()
        self._item = None
        self._z = None
        self._ahead = False
        self._center = 0
        self._want = None  # timepoint to load next (the newest slider position)
        # (z, t) -> (planes, exact), least recently used first
        self._store: OrderedDict[tuple, tuple] = OrderedDict()
        self._failed: set[int] = set()
        self._plane_bytes = 0
        self._not_before = 0.0
        threading.Thread(target=self._run, name='time-loader', daemon=True).start()

    # ---- main thread ------------------------------------------------------

    def follow(self, item, t: int | None = None):
        """Track item at its current Z; t is the timepoint to show next (the
        slider position), None when the current one is already shown.
        item None stops."""
        with self._cv:
            if item is None or item.nt < 2:
                self._item, self._z, self._want = None, None, None
                self._store.clear()
            else:
                if item is not self._item:
                    self._store.clear()
                if item is not self._item or item.z != self._z:
                    self._item, self._z = item, item.z
                    self._ahead = reads_ahead(item)
                    self._failed.clear()
                    self._not_before = time.monotonic() + START_DELAY_S
                self._want = None if t is None else int(t)
                self._center = item.t if t is None else int(t)
                if t is not None:
                    self._not_before = max(self._not_before,
                                           time.monotonic() + SLIDER_QUIET_S)
                self._trim()
            self._cv.notify()

    def get(self, item, t: int, exact: bool = True):
        """The loaded plane of timepoint t at the item's current Z, or None;
        with exact=False a preview plane counts too."""
        found = self.get_entry(item, t)
        if found is None or (exact and not found[1]):
            return None
        return found[0]

    def get_entry(self, item, t: int):
        """(planes, exact) of timepoint t at the item's current Z, or None."""
        with self._cv:
            if item is self._item:
                key = (item.z, int(t))
                found = self._store.get(key)
                if found is not None:
                    self._store.move_to_end(key)
                return found
        return None

    def put(self, item, t: int, z, planes: np.ndarray):
        """Keep a plane read elsewhere (the current timepoint)."""
        with self._cv:
            if item is self._item:
                self._keep((z, int(t)), (planes, True))

    def cached(self, item, exact: bool = False) -> int:
        """Number of timepoints loaded for item (exact ones only if exact)."""
        with self._cv:
            if item is not self._item:
                return 0
            return sum(1 for (z, _), (_, ok) in self._store.items()
                       if z == item.z and (ok or not exact))

    def reading_ahead(self, item) -> bool:
        with self._cv:
            return item is self._item and self._ahead

    # ---- shared ------------------------------------------------------------

    def _capacity(self) -> int:
        return max(1, self.budget // self._plane_bytes) if self._plane_bytes else 1 << 30

    def _window(self) -> list[int]:
        """Read-ahead: timepoints of the current Z to keep, nearest first."""
        order = sorted(range(self._item.nt),
                       key=lambda t: (abs(t - self._center), t < self._center))
        return order[:self._capacity()]

    def _trim(self):
        if self._item is None:
            return
        if not self._ahead:
            while len(self._store) > self.keep:
                self._store.popitem(last=False)
            return
        cap = self._capacity()
        if len(self._store) <= cap:
            return
        keep = {(self._z, t) for t in self._window()}
        if self._want is not None:
            keep.add((self._z, self._want))
        for key in [k for k in self._store if k not in keep][:len(self._store) - cap]:
            del self._store[key]  # least recently used, other Z or far timepoints

    def _keep(self, key, entry):
        if entry[1]:
            self._plane_bytes = self._plane_bytes or entry[0].nbytes
        self._store[key] = entry
        self._store.move_to_end(key)
        self._trim()

    # ---- worker thread -------------------------------------------------------

    def _next(self):
        """(t, quick, wait_s) of the next read, or None when nothing is left:
        first the slider position (quick: a preview is fine), then on an idle
        slider the exact planes of the read-ahead window."""
        if self._item is None:
            return None
        z = self._z
        if self._want is not None and (z, self._want) not in self._store \
                and self._want not in self._failed:
            return self._want, True, 0.0
        if not self._ahead:
            return None
        wait = self._not_before - time.monotonic()
        window = [t for t in self._window() if t not in self._failed]
        # first a quick plane for every timepoint (so all of them can be
        # dragged through soon), then the exact ones
        for t in window:
            if (z, t) not in self._store:
                return t, True, wait
        for t in window:
            if not self._store[(z, t)][1]:
                return t, False, wait
        return None

    def _run(self):
        while True:
            with self._cv:
                while True:
                    job = self._next()
                    if job is not None and job[2] <= 0:
                        break
                    self._cv.wait(job[2] if job is not None else None)
                item, z = self._item, self._z
                t, quick = job[0], job[1]
            try:
                if quick:
                    planes, exact = preview_at(item.image, t, z)
                else:
                    planes, exact = plane_at(item.image, t, z), True
                planes = np.asarray(planes, np.float32)
            except Exception:
                traceback.print_exc()
                with self._cv:
                    if item is self._item:
                        self._failed.add(t)
                continue
            with self._cv:
                if item is not self._item or z != self._z:
                    continue
                old = self._store.get((z, t))
                if old is not None and old[1] and not exact:
                    continue  # the exact plane arrived meanwhile
                self._keep((z, t), (planes, exact))
                stored = (z, t) in self._store
            if stored:
                self.ready.emit(item, t)
