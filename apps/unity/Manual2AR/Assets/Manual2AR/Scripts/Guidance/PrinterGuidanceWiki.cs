using System;
using System.Collections;
using UnityEngine;
namespace Manual2AR {
 public sealed partial class PrinterGuidanceController {
  GameObject wikiDialog;int wikiGeneration;
  IEnumerator OpenOfficialWiki(string url){
   CloseWiki();int version=wikiGeneration;
   var dialog=AppDialog.Open(root,"Official offline Wiki","官方 Wiki 指南",AppDialogSize.Large,CloseWiki);wikiDialog=dialog.gameObject;var panel=dialog.Panel;
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
