Shader "Manual2AR/InspectionMask"
{
    Properties
    {
        [PerRendererData] _MainTex ("Mask", 2D) = "white" {}
        _Color ("Tint", Color) = (1,1,1,1)
        _UseLabels ("Use ID labels", Float) = 0
        _LabelOpacity ("Label opacity", Float) = 0.40
        _LabelId ("Label ID", Float) = 0
        _Palette1 ("Part 1", Color) = (1,1,1,1)
        _Palette2 ("Part 2", Color) = (1,1,1,1)
        _Palette3 ("Part 3", Color) = (1,1,1,1)
        _Palette4 ("Part 4", Color) = (1,1,1,1)
        _Palette5 ("Part 5", Color) = (1,1,1,1)
        _Palette6 ("Part 6", Color) = (1,1,1,1)
        _Palette7 ("Part 7", Color) = (1,1,1,1)
        _Palette8 ("Part 8", Color) = (1,1,1,1)

        _StencilComp ("Stencil Comparison", Float) = 8
        _Stencil ("Stencil ID", Float) = 0
        _StencilOp ("Stencil Operation", Float) = 0
        _StencilWriteMask ("Stencil Write Mask", Float) = 255
        _StencilReadMask ("Stencil Read Mask", Float) = 255
        _ColorMask ("Color Mask", Float) = 15
        [Toggle(UNITY_UI_ALPHACLIP)] _UseUIAlphaClip ("Use Alpha Clip", Float) = 0
    }
    SubShader
    {
        Tags { "Queue"="Transparent" "IgnoreProjector"="True" "RenderType"="Transparent" "PreviewType"="Plane" "CanUseSpriteAtlas"="True" }
        Stencil { Ref [_Stencil] Comp [_StencilComp] Pass [_StencilOp] ReadMask [_StencilReadMask] WriteMask [_StencilWriteMask] }
        Cull Off
        Lighting Off
        ZWrite Off
        ZTest [unity_GUIZTestMode]
        Blend SrcAlpha OneMinusSrcAlpha
        ColorMask [_ColorMask]
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 2.0
            #pragma multi_compile_local _ UNITY_UI_CLIP_RECT
            #pragma multi_compile_local _ UNITY_UI_ALPHACLIP
            #include "UnityCG.cginc"
            #include "UnityUI.cginc"

            struct appdata { float4 vertex:POSITION; fixed4 color:COLOR; float2 uv:TEXCOORD0; UNITY_VERTEX_INPUT_INSTANCE_ID };
            struct v2f { float4 vertex:SV_POSITION; fixed4 color:COLOR; float2 uv:TEXCOORD0; float4 localPosition:TEXCOORD1; UNITY_VERTEX_OUTPUT_STEREO };
            sampler2D _MainTex;
            float4 _MainTex_TexelSize;
            fixed4 _Color;
            float4 _ClipRect;
            float _UseLabels,_LabelId,_LabelOpacity;
            fixed4 _Palette1,_Palette2,_Palette3,_Palette4,_Palette5,_Palette6,_Palette7,_Palette8;

            v2f vert(appdata input)
            {
                v2f output;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                output.localPosition=input.vertex;
                output.vertex=UnityObjectToClipPos(input.vertex);
                output.uv=input.uv;
                output.color=input.color*_Color;
                return output;
            }
            fixed4 frag(v2f input):SV_Target
            {
                fixed4 color=input.color;
                float4 mask=tex2D(_MainTex,input.uv);
                float label=floor(mask.r*255.0+0.5);
                if(_UseLabels>0.5){
                    fixed4 tint=label<1.5?_Palette1:label<2.5?_Palette2:label<3.5?_Palette3:label<4.5?_Palette4:label<5.5?_Palette5:label<6.5?_Palette6:label<7.5?_Palette7:_Palette8;
                    color*=tint;
                    color.a*=label>0.5&&label<8.5&&(_LabelId==0||abs(label-_LabelId)<0.25)?_LabelOpacity:0.0;
                    if(color.a>0.0){
                        float2 d=_MainTex_TexelSize.xy*1.25;
                        float4 neighbors=float4(tex2D(_MainTex,input.uv+float2(d.x,0)).r,tex2D(_MainTex,input.uv-float2(d.x,0)).r,tex2D(_MainTex,input.uv+float2(0,d.y)).r,tex2D(_MainTex,input.uv-float2(0,d.y)).r);
                        float4 difference=abs(floor(neighbors*255.0+0.5)-label);
                        if(max(max(difference.x,difference.y),max(difference.z,difference.w))>0.5){color.a=0.92*input.color.a;color.rgb=lerp(color.rgb,float3(1,1,1),0.12);}
                    }
                } else color.a*=mask.a;
                #ifdef UNITY_UI_CLIP_RECT
                    color.a*=UnityGet2DClipping(input.localPosition.xy,_ClipRect);
                #endif
                #ifdef UNITY_UI_ALPHACLIP
                    clip(color.a-0.001);
                #endif
                return color;
            }
            ENDCG
        }
    }
}
