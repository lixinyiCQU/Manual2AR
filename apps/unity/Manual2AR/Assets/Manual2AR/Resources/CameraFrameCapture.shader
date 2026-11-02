Shader "Manual2AR/CameraFrameCapture" {
 Properties { _MainTex ("Camera",2D)="white" {} _CropRect("Upright crop",Vector)=(0,0,1,1) }
 SubShader { Cull Off ZWrite Off ZTest Always
  Pass { CGPROGRAM
   #pragma vertex vert_img
   #pragma fragment frag
   #include "UnityCG.cginc"
   sampler2D _MainTex;float _Rotation,_MirrorY;float4 _CropRect;
   fixed4 frag(v2f_img i):SV_Target {
    float2 p=_CropRect.xy+i.uv*_CropRect.zw;
    if(_Rotation==90)p=float2(1-p.y,p.x);
    else if(_Rotation==180)p=1-p;
    else if(_Rotation==270)p=float2(p.y,1-p.x);
    if(_MirrorY>.5)p.y=1-p.y;
    return tex2D(_MainTex,p);
   }
  ENDCG }
 }
}
