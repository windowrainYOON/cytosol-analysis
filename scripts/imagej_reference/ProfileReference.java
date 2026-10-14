import ij.*; import ij.process.*; import ij.gui.*;
import java.nio.*; import java.nio.file.*;
public class ProfileReference { public static void main(String[] a) throws Exception {
  int w=Integer.parseInt(a[1]), h=Integer.parseInt(a[2]);
  ByteBuffer bb=ByteBuffer.wrap(Files.readAllBytes(Paths.get(a[0]))).order(ByteOrder.LITTLE_ENDIAN);
  FloatProcessor fp=new FloatProcessor(w,h); for(int i=0;i<w*h;i++) fp.setf(i, bb.getFloat());
  ImagePlus imp=new ImagePlus("t", fp);
  Line l=new Line(Double.parseDouble(a[3]),Double.parseDouble(a[4]),Double.parseDouble(a[5]),Double.parseDouble(a[6]));
  l.setStrokeWidth(Double.parseDouble(a[7])); imp.setRoi(l);
  double[] p=new ProfilePlot(imp).getProfile();
  StringBuilder sb=new StringBuilder(); for(double v:p) sb.append(v).append(' '); System.out.println(sb);
}}
