import ij.*; import ij.gui.*; import ij.process.*; import ij.measure.*; import java.io.*; import java.nio.*; import java.nio.file.*;
/** args: raw.f32 T H W  roi-spec...   roi spec: oval:x,y,w,h | poly:x1,y1,x2,y2,...   ; or "fit" x.txt y.txt */
public class FrapReference {
  public static void main(String[] a) throws Exception {
    if (a[0].equals("fit")) {
      double[] x=read(a[1]), y=read(a[2]);
      CurveFitter cf=new CurveFitter(x,y); cf.doFit(CurveFitter.EXP_RECOVERY);
      double[] p=cf.getParams(); System.out.println("fit "+p[0]+" "+p[1]+" "+p[2]+" r2 "+cf.getRSquared()); return;
    }
    int T=Integer.parseInt(a[1]),H=Integer.parseInt(a[2]),W=Integer.parseInt(a[3]);
    byte[] b=Files.readAllBytes(Paths.get(a[0])); FloatBuffer fb=ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer();
    ImageStack st=new ImageStack(W,H);
    for(int t=0;t<T;t++){ float[] px=new float[W*H]; fb.get(px); st.addSlice(new FloatProcessor(W,H,px)); }
    ImagePlus imp=new ImagePlus("s",st);
    for(int r=4;r<a.length;r++){
      String[] kv=a[r].split(":"); String[] n=kv[1].split(","); Roi roi;
      if(kv[0].equals("oval")) roi=new OvalRoi(Integer.parseInt(n[0]),Integer.parseInt(n[1]),Integer.parseInt(n[2]),Integer.parseInt(n[3]));
      else { float[] xs=new float[n.length/2], ys=new float[n.length/2]; for(int i=0;i<xs.length;i++){xs[i]=Float.parseFloat(n[2*i]); ys[i]=Float.parseFloat(n[2*i+1]);} roi=new PolygonRoi(xs,ys,Roi.POLYGON); }
      StringBuilder sb=new StringBuilder(a[r].substring(0,Math.min(20,a[r].length()))+" ");
      for(int t=1;t<=T;t++){ imp.setSlice(t); imp.setRoi(roi); sb.append(imp.getStatistics(Measurements.MEAN).mean).append(' '); }
      System.out.println(sb);
    }
  }
  static double[] read(String f) throws Exception { String[] s=new String(Files.readAllBytes(Paths.get(f))).trim().split("\\s+"); double[] d=new double[s.length]; for(int i=0;i<s.length;i++) d[i]=Double.parseDouble(s[i]); return d; }
}
