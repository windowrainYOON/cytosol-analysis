# cytosol-analysis

Microscopy image-based cytosol ROI determination and analysis.

## Reading raw files

`cytosol.io.read_image(path)` opens Tomocube `.TCF`, Zeiss `.czi` and
Olympus/Evident `.oir` files and returns an `Image` with `data` shaped
`(C, Z, Y, X)`, channel names, voxel size in micrometers and the raw metadata.

| Format | Reader | Notes |
|---|---|---|
| TCF (HDF5) | `h5py` | `modality='3D'` (default) or `'2DMIP'` gives refractive index (stored uint16 / 10000); `'3DFL'` / `'2DFLMIP'` gives fluorescence per channel. HT and FL have different XY pixel sizes and Z ranges (`Data/3DFL` `OffsetZ`). |
| CZI | `czifile` | `scene=` selects a scene in multi-scene files. |
| OIR | `oirfile` | |

```
pip install -r requirements.txt
python scripts/inspect_file.py FILE --out format-check/
```

`inspect_file.py` prints key metadata as JSON and writes preview PNGs
(mid-slice, MIP and XZ section for TCF; per-channel MIP and composite for CZI/OIR).

## Colored images with a scale bar

```
python scripts/render_image.py FILE --out figures/
```

Writes one PNG per channel plus a composite, at the original pixel size,
with a scale bar burned in. The bar length is picked automatically from the
pixel size in the file (about 20% of the width, rounded to 1/2/5/10/20/25/50…
µm) and channel colors come from the file itself: ZEN display colors for CZI,
the FluoView LUT for OIR, and the HTX channel colors for TCF (RI is gray).
For TCF both the HT (`3D`) and fluorescence (`3DFL`) volumes are rendered as
max projections by default.

Options: `--scale-um 10`, `--scale-position "upper left"`,
`--color 0=magenta --color DAPI-T3=#0050FF`, `--z mid` or `--z 12`,
`--modality 2DMIP`, `--no-labels`, `--low/--high` contrast percentiles.

From Python:

```python
from cytosol.io import read_image
from cytosol.render import render
render(read_image('cells.czi'), 'figures/', prefix='cells', scale_um=10,
       colors={'DAPI-T3': 'blue'})
```

## Cytosol Viewer (desktop app)

A GUI for working on a whole set of images at once:

- Add TCF / CZI / OIR files with **파일 추가…** or by dragging files or folders
  onto the window. A TCF becomes two entries, HT (RI) and FL.
- **Per-channel LUT** with a live preview: show/hide, color, min/max (slider,
  number or histogram), gamma, `Auto` (0.5–99.8 percentile) and `Min/Max`.
- **Z**: MIP or any single slice.
- **Crop** per image: press `Crop 그리기` and drag on the image. You can copy the
  crop to every image with the same pixel size, and preview only the cropped area.
- **Batch LUT**: `전체 이미지에 적용` on a channel copies its LUT to the same
  channel of every loaded image (matched by channel name; by index only between
  files of the same type and channel count). LUTs can be saved and loaded as JSON presets.
- **Batch TIFF export** of every image, cropped:
  - composite RGB with the LUTs and scale bar applied (8-bit, µm calibration),
  - optional per-channel RGB,
  - an ImageJ hyperstack of the original values for all Z, carrying the channel
    LUTs, display ranges and µm calibration, ready for measurement in Fiji.

Run from source: `python -m cytosol.app [files…]`

Build the macOS app: `./build_mac.sh` → `dist/Cytosol Viewer.app`
