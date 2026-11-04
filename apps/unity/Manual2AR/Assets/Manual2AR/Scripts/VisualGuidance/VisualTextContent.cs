using UnityEngine;
using System;
using System.Text;
using System.Collections.Generic;
namespace Manual2AR.VisualGuidance {
 /// <summary>Same teaching information on desktop projections and registered AR world labels.</summary>
 public static class VisualTextContent {
  public static VisualTextLabel Directive(GuidanceDisplay display){
   if(display?.schema_version!="manual2ar-guidance-display-v1"||display.instruction?.position_m==null||display.instruction.position_m.Length!=3)return null;
   return new VisualTextLabel{id=display.action_id+":instruction",text=display.instruction.sentence,kind="directive",reference_space_id="calibrated-marker",position_m=display.instruction.position_m,color_legend=display.legend};
  }
  public static string Format(VisualTextLabel item){
   string text=item.kind=="directive"?item.text.Replace("，","，\n"):item.text;
   if(item.kind=="context"){
    text=string.IsNullOrEmpty(item.brief)?item.text:item.brief;
    if(item.state=="passed")text+="\n上次可见检查通过";
    else if(item.state=="needs_attention")text+="\n请调整后重新检查";
   }else if(!string.IsNullOrEmpty(item.brief))text+="\n"+item.brief;
   return Colorize(text,item.color_legend);
  }
  public static Color LegendColor(LegendItem item){return item?.color!=null&&item.color.Length==3?new Color(item.color[0],item.color[1],item.color[2]):Color.white;}
  static string Colorize(string text,LegendItem[] legend){
   if(legend==null)return AppTheme.Readable(text);
   var terms=new List<KeyValuePair<string,Color>>();foreach(var item in legend)foreach(var term in item.terms??new string[0])if(!string.IsNullOrEmpty(term))terms.Add(new KeyValuePair<string,Color>(term,LegendColor(item)));
   terms.Sort((a,b)=>b.Key.Length.CompareTo(a.Key.Length));var output=new StringBuilder();
   for(int i=0;i<text.Length;){bool matched=false;foreach(var pair in terms)if(i+pair.Key.Length<=text.Length&&string.CompareOrdinal(text,i,pair.Key,0,pair.Key.Length)==0){output.Append("<color=#").Append(ColorUtility.ToHtmlStringRGB(pair.Value)).Append(">").Append(AppTheme.Readable(pair.Key)).Append("</color>");i+=pair.Key.Length;matched=true;break;}if(!matched)output.Append(text[i++]);}
   return AppTheme.Readable(output.ToString());
  }
  public static Color ColorFor(VisualTextLabel item){return item.kind!="context"?Color.white:item.state=="passed"?AppTheme.SuccessGreen:item.state=="needs_attention"?new Color(1,.73f,.3f):Color.white;}
 }
}
