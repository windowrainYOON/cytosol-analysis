"""MP4 export of RGB frame series (time series, rotation series).

Encodes with the ffmpeg binary bundled by imageio-ffmpeg, so no system
ffmpeg is needed (the built app carries it too).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# file formats offered for RGB outputs of a frame series
RGB_FORMATS = {'tif': 'TIFF', 'mp4': 'MP4 (동영상)', 'both': 'TIFF + MP4'}


def wants_tif(fmt: str) -> bool:
    return fmt in ('tif', 'both')


def wants_mp4(fmt: str) -> bool:
    return fmt in ('mp4', 'both')


def _even(frame: np.ndarray) -> np.ndarray:
    """Pad to even width/height (H.264 with 4:2:0 chroma needs it)."""
    h, w = frame.shape[:2]
    ph, pw = h % 2, w % 2
    if ph or pw:
        frame = np.pad(frame, ((0, ph), (0, pw), (0, 0)), mode='edge')
    return frame


def write_mp4(path, frames, fps: float = 10.0, quality: int = 18) -> str:
    """Write uint8 (Y, X, 3) frames to an H.264 MP4 and return the path.

    quality: x264 CRF (lower = better; 18 is visually lossless). The output is
    yuv420p so it plays in QuickTime, PowerPoint and browsers.
    """
    import imageio_ffmpeg

    frames = [np.ascontiguousarray(_even(np.asarray(f, np.uint8)[..., :3])) for f in frames]
    if not frames:
        raise ValueError('no frames to write')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    h, w = frames[0].shape[:2]
    writer = imageio_ffmpeg.write_frames(
        str(path), (w, h), fps=float(fps), codec='libx264', pix_fmt_out='yuv420p',
        macro_block_size=1, quality=None,
        output_params=['-crf', str(int(quality)), '-preset', 'medium',
                       '-movflags', '+faststart'],
    )
    writer.send(None)  # start ffmpeg
    try:
        for f in frames:
            if f.shape[:2] != (h, w):  # frames of a series share one size; guard anyway
                f = np.ascontiguousarray(_fit(f, h, w))
            writer.send(f)
    finally:
        writer.close()
    return str(path)


def _fit(frame, h, w):
    out = np.zeros((h, w, 3), np.uint8)
    hh, ww = min(h, frame.shape[0]), min(w, frame.shape[1])
    out[:hh, :ww] = frame[:hh, :ww]
    return out
