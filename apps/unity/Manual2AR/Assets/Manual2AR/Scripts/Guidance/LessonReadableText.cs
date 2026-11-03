using System;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
    /// <summary>Width-based CJK wrapping, independent of Unity's word-sized CJK runs.
    /// Canonical text is retained so resize/reflow never accumulates hard line breaks.</summary>
    [RequireComponent(typeof(Text))]
    public sealed class LessonReadableText:MonoBehaviour {
        Text label;string source="",rendered="";float width=-1,scale=-1;int size;FontStyle style;Font lastFont;
        readonly Dictionary<string,float> advances=new Dictionary<string,float>();
        readonly TextGenerator metrics=new TextGenerator();
        public string Source {get{return source;}}
        public static LessonReadableText Attach(Text text){
            var reader=text.GetComponent<LessonReadableText>();if(reader==null)reader=text.gameObject.AddComponent<LessonReadableText>();
            reader.label=text;reader.source=Prepare(text.text);reader.rendered=text.text;reader.Reflow(true);return reader;
        }
        public static string Prepare(string text){
            text=(text??"").Replace("\u200b","").Replace("\u2060","").Replace("\r\n","\n").Replace('\r','\n');
            text=text.Replace("A1 mini","A1\u00a0mini").Replace("AMS lite","AMS\u00a0lite").Replace("Micro SD","Micro\u00a0SD");
            text=Regex.Replace(text,@"([XYZ]) +轴","$1\u00a0轴");
            return Regex.Replace(text,@"(?<=\d) +(?=(?:mm|cm|GB|层|颗|根|个|号口)(?:\b|(?=[\u3400-\u9fff])))","\u00a0");
        }
        void LateUpdate(){Reflow(false);}
        void OnRectTransformDimensionsChange(){if(label!=null&&isActiveAndEnabled)Reflow(false);}
        public void Reflow(bool force){
            if(label==null)label=GetComponent<Text>();if(label==null||label.font==null)return;
            if(label.text!=rendered){source=Prepare(label.text);force=true;}
            float available=label.rectTransform.rect.width-6;
            if(available<32)return;
            float pixels=label.pixelsPerUnit;
            if(!force&&Mathf.Abs(available-width)<.25f&&size==label.fontSize&&style==label.fontStyle&&lastFont==label.font&&Mathf.Abs(scale-pixels)<.001f)return;
            width=available;size=label.fontSize;style=label.fontStyle;lastFont=label.font;scale=pixels;advances.Clear();
            label.horizontalOverflow=HorizontalWrapMode.Overflow;
            var settings=label.GetGenerationSettings(Vector2.zero);settings.horizontalOverflow=HorizontalWrapMode.Overflow;
            Func<string,float> measure=token=>{float value;if(!advances.TryGetValue(token,out value)){value=metrics.GetPreferredWidth(token,settings)/Mathf.Max(.001f,pixels);advances[token]=value;}return value;};
            rendered=Wrap(source,available,measure);label.text=rendered;
        }
        public static string Wrap(string text,float available,Func<string,float> measure){
            var output=new StringBuilder();
            var lines=text.Split('\n');
            for(int line=0;line<lines.Length;line++){
                if(line>0)output.Append('\n');
                var tokens=new List<string>();
                foreach(Match match in Regex.Matches(lines[line],@"[A-Za-z0-9]+(?:[-./][A-Za-z0-9]+)*(?:\u00a0(?:[A-Za-z0-9°℃%]+|层|颗|根|个|号口|轴))*|[^\r\n]")){
                    string token=match.Value;
                    if(tokens.Count>0&&"，。！？；：、）》】’”.,!?;:%）".Contains(token))tokens[tokens.Count-1]+=token;
                    else if(tokens.Count>0&&tokens[tokens.Count-1].Length==1&&"（《【‘“(".Contains(tokens[tokens.Count-1]))tokens[tokens.Count-1]+=token;
                    else tokens.Add(token);
                }
                float used=0;
                foreach(string token in tokens){
                    float advance=measure(token);
                    if(string.IsNullOrWhiteSpace(token)){if(used>0&&used+advance<available){output.Append(token);used+=advance;}continue;}
                    if(used>0&&used+advance>available){while(output.Length>0&&output[output.Length-1]==' ')output.Length--;output.Append('\n');used=0;}
                    // Oversized URLs/identifiers can split; normal model names and units stay together.
                    if(advance>available){foreach(char ch in token){float glyph=measure(ch.ToString());if(used>0&&used+glyph>available){output.Append('\n');used=0;}output.Append(ch);used+=glyph;}}
                    else{output.Append(token);used+=advance;}
                }
            }
            return output.ToString();
        }
        void OnDestroy(){((IDisposable)metrics).Dispose();}
    }
}
