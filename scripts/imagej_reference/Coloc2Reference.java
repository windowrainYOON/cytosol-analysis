import java.io.*;
import java.nio.*;
import java.nio.file.*;
import java.util.*;
import net.imglib2.*;
import net.imglib2.view.Views;
import net.imglib2.img.Img;
import net.imglib2.img.array.*;
import net.imglib2.type.numeric.*;
import net.imglib2.type.numeric.integer.*;
import net.imglib2.type.numeric.real.*;
import net.imglib2.type.NativeType;
import sc.fiji.coloc.algorithms.*;
import sc.fiji.coloc.gadgets.*;
import sc.fiji.coloc.results.*;

// usage: Coloc2Reference <dir> <float|uint16|uint8> <regression> <psf> <nrand> [nz]
public class Coloc2Reference {
  static <T extends RealType<T> & NativeType<T>> void go(Img<T> a, Img<T> b, Img<T> m, long[] off, long[] size, String regr, int psf, int nrand) throws Exception {
    DataContainer<T> c = new DataContainer<>(a, b, 1, 1, "A", "B", m, off, size);
    PearsonsCorrelation<T> pc = new PearsonsCorrelation<>(PearsonsCorrelation.Implementation.Fast);
    List<Algorithm<T>> jobs = new ArrayList<>();
    jobs.add(c.setInputCheck(new InputCheck<T>()));
    jobs.add(c.setAutoThreshold(new AutoThresholdRegression<>(pc, AutoThresholdRegression.Implementation.valueOf(regr))));
    jobs.add(pc);
    jobs.add(new LiHistogram2D<T>("Li - Ch1", true));
    jobs.add(new LiHistogram2D<T>("Li - Ch2", false));
    jobs.add(new LiICQ<T>());
    jobs.add(new SpearmanRankCorrelation<T>());
    jobs.add(new MandersColocalization<T>());
    jobs.add(new KendallTauRankCorrelation<T>());
    jobs.add(new Histogram2D<T>("2D intensity histogram"));
    if (nrand > 0) jobs.add(new CostesSignificanceTest<T>(pc, psf, nrand, false));
    ResultHandler<T> h = new ResultHandler<T>() {
      public void handleImage(RandomAccessibleInterval<T> image, String name) {}
      public void handleHistogram(Histogram2D<T> hist, String name) {
        RandomAccessibleInterval<LongType> p = hist.getPlotImage();
        Cursor<LongType> cur = Views.iterable(p).localizingCursor();
        long tot = 0, w = 0;
        while (cur.hasNext()) { cur.fwd(); long v = cur.get().get(); tot += v; w += v * (cur.getLongPosition(0) * 1000 + cur.getLongPosition(1)); }
        System.out.println("HIST\t" + name + "\t" + tot + "\t" + w + "\t" + hist.getXBinWidth() + "\t" + hist.getYBinWidth());
      }
      public void handleWarning(Warning w) { System.out.println("WARN\t" + w.getShortMessage()); }
      public void handleValue(String n, String v) { System.out.println("VAL\t" + n + "\t" + v); }
      public void handleValue(String n, double v) { System.out.println("VAL\t" + n + "\t" + v); }
      public void handleValue(String n, double v, int d) { System.out.println("VAL\t" + n + "\t" + v); }
      public void process() {}
    };
    for (Algorithm<T> j : jobs) {
      try { j.execute(c); } catch (MissingPreconditionException e) { h.handleWarning(new Warning("Probem with input data", e.getMessage())); }
    }
    for (Algorithm<T> j : jobs) j.processResults(h);
  }
  static ByteBuffer read(String p) throws IOException { return ByteBuffer.wrap(Files.readAllBytes(Paths.get(p))).order(ByteOrder.LITTLE_ENDIAN); }
  public static void main(String[] args) throws Exception {
    String dir = args[0];
    long[] dims = Arrays.stream(new String(Files.readAllBytes(Paths.get(dir, "dims.txt"))).trim().split(" ")).mapToLong(Long::parseLong).toArray(); // x y [z]
    long[] bb = Arrays.stream(new String(Files.readAllBytes(Paths.get(dir, "bbox.txt"))).trim().split(" ")).mapToLong(Long::parseLong).toArray(); // x y w h
    long[] off = {bb[0], bb[1]}, size = {bb[2], bb[3]};
    int n = 1; for (long d : dims) n *= d;
    ByteBuffer mb = read(dir + "/mask.raw");
    if (args[1].equals("float")) {
      ArrayImg<FloatType, ?> a = ArrayImgs.floats(dims), b = ArrayImgs.floats(dims), m = ArrayImgs.floats(dims);
      fill(a, read(dir + "/a.raw"), true); fill(b, read(dir + "/b.raw"), true);
      Cursor<FloatType> mc = m.cursor(); for (int i = 0; i < n; i++) mc.next().set(mb.get(i));
      go(a, b, m, off, size, args[2], Integer.parseInt(args[3]), Integer.parseInt(args[4]));
    } else if (args[1].equals("uint8")) {
      ArrayImg<UnsignedByteType, ?> a = ArrayImgs.unsignedBytes(dims), b = ArrayImgs.unsignedBytes(dims), m = ArrayImgs.unsignedBytes(dims);
      fill(a, read(dir + "/a.raw"), false); fill(b, read(dir + "/b.raw"), false);
      Cursor<UnsignedByteType> mc = m.cursor(); for (int i = 0; i < n; i++) mc.next().set(mb.get(i));
      go(a, b, m, off, size, args[2], Integer.parseInt(args[3]), Integer.parseInt(args[4]));
    } else {
      ArrayImg<UnsignedShortType, ?> a = ArrayImgs.unsignedShorts(dims), b = ArrayImgs.unsignedShorts(dims), m = ArrayImgs.unsignedShorts(dims);
      fill(a, read(dir + "/a.raw"), false); fill(b, read(dir + "/b.raw"), false);
      Cursor<UnsignedShortType> mc = m.cursor(); for (int i = 0; i < n; i++) mc.next().set(mb.get(i));
      go(a, b, m, off, size, args[2], Integer.parseInt(args[3]), Integer.parseInt(args[4]));
    }
  }
  static <T extends RealType<T> & NativeType<T>> void fill(ArrayImg<T, ?> img, ByteBuffer bb, boolean flt) {
    Cursor<T> c = img.cursor();
    while (c.hasNext()) { T t = c.next(); t.setReal(flt ? bb.getFloat() : img.firstElement() instanceof UnsignedByteType ? (bb.get() & 0xff) : (bb.getShort() & 0xffff)); }
  }
}
