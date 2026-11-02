Shader "Manual2AR/InspectionCapture" {
 Properties { _MainTex ("Camera", 2D) = "white" {} }
 SubShader { Cull Off ZWrite Off ZTest Always
  Pass { CGPROGRAM
   #pragma vertex vert_img
   #pragma fragment frag
   #include "UnityCG.cginc"
   sampler2D _MainTex;float _Rotation,_MirrorY;
   fixed4 frag(v2f_img i):SV_Target {
    float2 p=i.uv;
    if(_Rotation==90)p=float2(1-i.uv.y,i.uv.x);
    else if(_Rotation==180)p=1-i.uv;
    else if(_Rotation==270)p=float2(i.uv.y,1-i.uv.x);
    if(_MirrorY>.5)p.y=1-p.y;
    return tex2D(_MainTex,p);
   }
  ENDCG }
 }
}
