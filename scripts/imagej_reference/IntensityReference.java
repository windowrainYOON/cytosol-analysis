import ij.process.*;
import java.io.*;
import java.nio.*;
import java.nio.file.*;

/** For each label of a region image: ImageJ's setAutoThreshold("Otsu dark")
 *  lower threshold with that label's pixels as the ROI mask, and the
 *  Measure values (pixel count, mean, StdDev, min, max) of the raw pixels.
 *  args: plane.raw width height bits labels.raw(int32) */
public class IntensityReference {
    public static void main(String[] a) throws Exception {
        int w = Integer.parseInt(a[1]), h = Integer.parseInt(a[2]), bits = Integer.parseInt(a[3]);
        ByteBuffer pb = ByteBuffer.wrap(Files.readAllBytes(Paths.get(a[0]))).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer lb = ByteBuffer.wrap(Files.readAllBytes(Paths.get(a[4]))).order(ByteOrder.LITTLE_ENDIAN);
        int n = w * h;
        int[] lab = new int[n];
        int maxl = 0;
        for (int i = 0; i < n; i++) { lab[i] = lb.getInt(); maxl = Math.max(maxl, lab[i]); }
        ImageProcessor ip;
        if (bits == 8) { byte[] p = new byte[n]; pb.get(p); ip = new ByteProcessor(w, h, p); }
        else if (bits == 16) { short[] p = new short[n]; for (int i = 0; i < n; i++) p[i] = pb.getShort(); ip = new ShortProcessor(w, h, p, null); }
        else { float[] p = new float[n]; for (int i = 0; i < n; i++) p[i] = pb.getFloat(); ip = new FloatProcessor(w, h, p); }
        for (int l = 1; l <= maxl; l++) {
            int x0 = w, y0 = h, x1 = -1, y1 = -1;
            for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) if (lab[y * w + x] == l) {
                x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y);
            }
            if (x1 < 0) continue;
            int rw = x1 - x0 + 1, rh = y1 - y0 + 1;
            ByteProcessor m = new ByteProcessor(rw, rh);
            for (int y = 0; y < rh; y++) for (int x = 0; x < rw; x++)
                if (lab[(y + y0) * w + x + x0] == l) m.set(x, y, 255);
            ImageProcessor ip2 = ip.duplicate();
            ip2.setRoi(new java.awt.Rectangle(x0, y0, rw, rh));
            ip2.setMask(m);
            ImageStatistics st = ImageStatistics.getStatistics(ip2,
                ImageStatistics.MEAN | ImageStatistics.STD_DEV | ImageStatistics.MIN_MAX | ImageStatistics.AREA, null);
            ip2.setAutoThreshold("Otsu dark");
            System.out.println(l + "," + ip2.getMinThreshold() + "," + st.pixelCount + "," + st.mean + ","
                + st.stdDev + "," + st.min + "," + st.max);
        }
    }
}
