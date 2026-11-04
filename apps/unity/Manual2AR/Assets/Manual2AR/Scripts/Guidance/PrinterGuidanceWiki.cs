using System;
using System.Collections;
using UnityEngine;
namespace Manual2AR {
 public sealed partial class PrinterGuidanceController {
  GameObject wikiDialog;int wikiGeneration;
  IEnumerator OpenOfficialWiki(string url){
   CloseWiki();int version=wikiGeneration;
   var panel=Frame("Official offline Wiki",root,new Vector2(.055f,.045f),new Vector2(.945f,.95f));wikiDialog=panel.gameObject;AppModalBackdrop.Attach(wikiDialog);
   TextAt(panel,"官方 Wiki 指南",new Vector2(.025f,.92f),new Vector2(.86f,.99f),30);
   ButtonAt(panel,"关闭",new Vector2(.88f,.925f),new Vector2(.98f,.99f),CloseWiki);
   var message=TextAt(panel,"正在打开离线指南…",new Vector2(.05f,.40f),new Vector2(.95f,.65f),26);
   yield return Request("/api/learning/wiki/resolve?url="+Uri.EscapeDataString(url),"GET",null,(raw,error)=>{
    if(wikiDialog==null||version!=wikiGeneration)return;
    if(error!=null){message.text="离线指南暂时无法打开，请稍后重试。";return;}
    var source=Parse<LearningSource>(raw);if(source==null||string.IsNullOrEmpty(source.page_id)){message.text="该指南尚未包含在离线资料中。";return;}
    message.gameObject.SetActive(false);var reader=panel.gameObject.AddComponent<PrinterLearningWikiView>();reader.Initialize(panel,font,settings.backend_url,source,CloseWiki,"返回步骤总览");
   });
  }
  void CloseWiki(){wikiGeneration++;if(wikiDialog!=null){wikiDialog.SetActive(false);Destroy(wikiDialog);wikiDialog=null;}}
 }
}
