# ImageJ reference comparisons

Run the original ImageJ / Fiji code headless on the same data as `cytosol`
and print the differences.

- `Coloc2Reference.java` runs Fiji Coloc 2's algorithm classes
  (`sc.fiji.coloc.algorithms`: InputCheck, AutoThresholdRegression,
  PearsonsCorrelation, Li, Spearman, Manders, Kendall, Histogram2D,
  CostesSignificanceTest) on raw files written by `compare_coloc2.py`.
- `IntensityReference.java` gives, per labelled ROI, ImageJ's
  `setAutoThreshold("Otsu dark")` level and the Measure values for
  `compare_intensity.py` (needs only `ij.jar`; synthetic 8/16/32-bit cases, or
  `plane.npy labels.npy bits`).
- `ShapeReference.java` runs ImageJ Analyze Particles (area, centroid,
  perimeter, fit ellipse, shape descriptors, Feret's diameter) on every label
  of a label image for `compare_shape.py` (needs only `ij.jar`; random blobs,
  or `labels.npy`).
- `ProfileReference.java` gets ImageJ's line profile (`ProfilePlot`, what
  Plot Profile and RGB Profiler plot) for `compare_profile.py`.
- `FrapReference.java` gives ImageJ's Measure mean of oval / polygon ROIs on
  every slice of a float stack and the `CurveFitter` "Exponential recovery"
  fit for `compare_frap.py` (needs only `ij.jar`).

Build: compile the sources of
[Colocalisation_Analysis](https://github.com/fiji/Colocalisation_Analysis)
(`src/main/java/sc/fiji/coloc/{algorithms,gadgets,results}`) together with
the few imglib2-algorithm / imglib2-roi classes they use (Gaussian,
multithreading helpers) and these two files against `ij-1.54f.jar` and
`imglib2-6.1.0.jar`, e.g. `javac -d build -cp ij.jar:imglib2.jar ...`. Then

    python scripts/imagej_reference/compare_coloc2.py ij.jar:imglib2.jar:build
    python scripts/imagej_reference/compare_profile.py ij.jar:imglib2.jar:build
    python scripts/imagej_reference/compare_intensity.py ij.jar:build
    python scripts/imagej_reference/compare_shape.py ij.jar:build
    python scripts/imagej_reference/compare_frap.py ij.jar:build

`COLOC2_REAL=<dir>` (with `a.npy`, `b.npy`, `masks.npz`) adds a real image
and its ROI masks to the Coloc 2 cases.
