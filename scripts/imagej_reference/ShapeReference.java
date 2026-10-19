import ij.*;
import ij.measure.*;
import ij.plugin.filter.*;
import ij.process.*;
import java.nio.*;
import java.nio.file.*;

/** For each label of an int32 label image: ImageJ Analyze Particles on that
 *  label alone with Area, Centroid, Perimeter, Fit ellipse, Shape descriptors
 *  and Feret's diameter (uncalibrated).  args: labels.raw width height */
public class ShapeReference {
    public static void main(String[] a) throws Exception {
        int w = Integer.parseInt(a[1]), h = Integer.parseInt(a[2]);
        ByteBuffer lb = ByteBuffer.wrap(Files.readAllBytes(Paths.get(a[0]))).order(ByteOrder.LITTLE_ENDIAN);
        int n = w * h, maxl = 0;
        int[] lab = new int[n];
        for (int i = 0; i < n; i++) { lab[i] = lb.getInt(); maxl = Math.max(maxl, lab[i]); }
        int meas = Measurements.AREA | Measurements.CENTROID | Measurements.PERIMETER
            | Measurements.ELLIPSE | Measurements.SHAPE_DESCRIPTORS | Measurements.FERET;
        System.out.println("label,n,Area,X,Y,Perim,Major,Minor,Angle,Circ,AR,Round,Solidity,Feret,FeretAngle,MinFeret");
        for (int l = 1; l <= maxl; l++) {
            ByteProcessor bp = new ByteProcessor(w, h);
            boolean any = false;
            for (int i = 0; i < n; i++) if (lab[i] == l) { bp.set(i % w, i / w, 255); any = true; }
            if (!any) continue;
            bp.setThreshold(255, 255, ImageProcessor.NO_LUT_UPDATE);
            ImagePlus imp = new ImagePlus("l", bp);
            ResultsTable rt = new ResultsTable();
            ParticleAnalyzer pa = new ParticleAnalyzer(0, meas, rt, 0, Double.POSITIVE_INFINITY);
            pa.setHideOutputImage(true);
            pa.analyze(imp, bp);
            for (int r = 0; r < rt.size(); r++) {
                StringBuilder sb = new StringBuilder(l + "," + rt.size());
                for (String c : new String[]{"Area","X","Y","Perim.","Major","Minor","Angle","Circ.","AR","Round","Solidity","Feret","FeretAngle","MinFeret"})
                    sb.append(",").append(rt.getValue(c, r));
                System.out.println(sb);
            }
        }
    }
}
