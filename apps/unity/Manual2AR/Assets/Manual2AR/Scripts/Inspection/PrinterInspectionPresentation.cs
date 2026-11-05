using UnityEngine;
using UnityEngine.UI;
namespace Manual2AR {
 // User-facing states only; raw model text remains in the research log.
 public sealed class PrinterInspectionPresentation:MonoBehaviour {
  RectTransform panel,banner,badge;
  Text headline,actionText,badgeText,bannerText;
  readonly Text[] rows=new Text[3];readonly AppIconGraphic[] rowIcons=new AppIconGraphic[3];
  AppIconGraphic bannerIcon;Font font;
  bool unclassifiedVisible,partialVisible,lastKnownPending;
  static readonly Color Cyan=AppTheme.TargetCyan,Green=AppTheme.SuccessGreen,Red=AppTheme.ErrorRed,Amber=AppTheme.WarningAmber,Muted=AppTheme.Muted;
  public string Status {get;private set;}
  public bool Visible {get{return panel!=null&&panel.gameObject.activeInHierarchy;}}
  RectTransform Rect(string name,Transform parent,Vector2 min,Vector2 max){var g=new GameObject(name,typeof(RectTransform));g.transform.SetParent(parent,false);var r=g.GetComponent<RectTransform>();r.anchorMin=min;r.anchorMax=max;r.offsetMin=r.offsetMax=Vector2.zero;return r;}
  RectTransform Card(string name,Transform parent,Vector2 min,Vector2 max,Color color){var r=Rect(name,parent,min,max);var g=r.gameObject.AddComponent<AppRoundedImage>();g.radius=20;g.color=color;return r;}
  Text TextAt(Transform parent,string name,Vector2 min,Vector2 max,int size,Color color,bool bold=false){var r=Rect(name,parent,min,max);var t=r.gameObject.AddComponent<Text>();t.font=font;t.fontSize=size;t.fontStyle=bold?FontStyle.Bold:FontStyle.Normal;t.color=color;t.supportRichText=false;t.raycastTarget=false;t.alignment=TextAnchor.MiddleLeft;t.verticalOverflow=VerticalWrapMode.Truncate;return t;}
  AppIconGraphic Icon(Transform parent,AppIcon symbol,Vector2 min,Vector2 max,Color color){var r=Rect("状态图标",parent,min,max);var icon=r.gameObject.AddComponent<AppIconGraphic>();icon.symbol=symbol;icon.color=color;icon.raycastTarget=false;return icon;}
  public void Initialize(RectTransform cameraContent,Transform screenUiRoot,Font typeface,AppWorkspace workspace){
   font=typeface;
   panel=workspace.Aside;
   var title=TextAt(panel,"检查结果",new Vector2(.07f,.88f),new Vector2(.93f,.98f),32,Cyan,true);title.text="检查结果";
   var line=Rect("分隔线",panel,new Vector2(.07f,.875f),new Vector2(.93f,.877f));line.gameObject.AddComponent<Image>().color=new Color(.13f,.4f,.5f);
   headline=TextAt(panel,"结果标题",new Vector2(.07f,.76f),new Vector2(.93f,.86f),32,Cyan,true);
   for(int i=0;i<3;i++){float y=.64f-i*.13f;rowIcons[i]=Icon(panel,AppIcon.Info,new Vector2(.07f,y),new Vector2(.145f,y+.065f),Muted);rows[i]=TextAt(panel,"检查项目",new Vector2(.19f,y-.012f),new Vector2(.94f,y+.078f),28,Muted);}
   var divider=Rect("建议分隔线",panel,new Vector2(.07f,.325f),new Vector2(.93f,.327f));divider.gameObject.AddComponent<Image>().color=new Color(.13f,.25f,.33f);
   var label=TextAt(panel,"操作提示",new Vector2(.07f,.25f),new Vector2(.93f,.32f),25,Muted);label.text="操作提示";
   actionText=TextAt(panel,"操作建议",new Vector2(.07f,.055f),new Vector2(.93f,.25f),27,Color.white);
   badge=Card("Inspection State",workspace.HeaderActions,Vector2.zero,Vector2.one,new Color(.035f,.18f,.22f));badge.gameObject.AddComponent<LayoutElement>().preferredHeight=AppTheme.ButtonHeight;badgeText=TextAt(badge,"状态",new Vector2(.08f,0),new Vector2(.95f,1),26,Cyan,true);badgeText.alignment=TextAnchor.MiddleCenter;
   banner=Card("Inspection Status Banner",workspace.FooterLeft,Vector2.zero,Vector2.one,new Color(.035f,.17f,.21f));var bannerSize=banner.gameObject.AddComponent<LayoutElement>();bannerSize.preferredHeight=AppTheme.ButtonHeight;bannerSize.flexibleWidth=1;
   bannerIcon=Icon(banner,AppIcon.Info,new Vector2(.025f,.23f),new Vector2(.068f,.77f),Cyan);
   bannerText=TextAt(banner,"检查提示",new Vector2(.09f,.1f),new Vector2(.97f,.9f),AppTheme.CaptionSize,Cyan,true);
   Clear();
  }
  void Style(string status,string title,string badgeValue,string bannerValue,Color color){
   Status=status;headline.text=title;headline.color=color;badgeText.text=badgeValue;badgeText.color=color;bannerText.text=bannerValue;bannerText.color=color;bannerIcon.color=color;
   bannerIcon.symbol=status=="anomaly_detected"?AppIcon.Warning:status=="no_visible_anomaly"?AppIcon.Check:AppIcon.Info;
   banner.GetComponent<AppRoundedImage>().color=Color.Lerp(new Color(.025f,.07f,.115f),color,.12f);
  }
  void Row(int index,string state,string passed,string failed,string unknown){
   bool clear=state=="pass"||state=="visible_pass"||state=="removed";
   rows[index].text=state=="removed"?(index==1?"异物已移出板面":"残料已移出板面"):state=="visible_pass"?(index==1?"可见区域未见异物":"可见区域未见残料"):state=="not_observed"?(index==1?"暂未检出明显异物":"暂未检出明显残料"):state=="last_detected"?(index==1?"上次检出异物，待复检":"上次检出残料，待复检"):state=="unclassified"?"发现未识别物体":state=="pass"?passed:state=="fail"?failed:unknown;
   var color=clear?Green:state=="fail"?Red:Amber;rows[index].color=color;rowIcons[index].color=color;rowIcons[index].symbol=clear?AppIcon.Check:state=="fail"?AppIcon.Close:AppIcon.Info;rowIcons[index].SetVerticesDirty();
  }
  public void SetCaptureHint(string hint){if(Status=="not_checked")bannerText.text=hint;}
  public void Clear(){
   unclassifiedVisible=partialVisible=lastKnownPending=false;
   Style("not_checked","等待检查","等待检查","请将整块打印板置于画面中",Cyan);
   string[] lines={"拍全打印板及四周边缘","避免遮挡与强反光","点击检查按钮开始"};for(int i=0;i<3;i++){rows[i].text=lines[i];rows[i].color=Muted;rowIcons[i].symbol=AppIcon.Info;rowIcons[i].color=Muted;rowIcons[i].SetVerticesDirty();}
   actionText.text="先检查板面，再清理异物。\n处理完成后可随时重新检查。";
  }
  public void ShowProcessing(){Clear();Style("processing","正在识别打印板","识别中","正在识别当前照片中的打印板与物体",Cyan);actionText.text="识别完成后先显示定位框，\n再生成分割高亮。";}
  public void ShowLocalization(InspectionPublicResult result){
   unclassifiedVisible=partialVisible=lastKnownPending=false;
   bool anomaly=result!=null&&(result.foreign_object_state=="fail"||result.residue_state=="fail");
   Style("localizing",anomaly?"发现异常，生成高亮中":"正在生成板面高亮","生成高亮中","已完成识别 · 正在生成分割高亮",anomaly?Red:Cyan);
   Row(0,result==null?"unknown":result.plate_state,"已识别打印板","","打印板情况待确认");
   Row(1,result!=null&&result.foreign_object_state=="fail"?"fail":"unknown","","发现板面异物","异物检查尚未完成");
   Row(2,result!=null&&result.residue_state=="fail"?"fail":"unknown","","发现板面残料","残料检查尚未完成");
   actionText.text="虚线框为初步定位。\n生成后自动更新检查结果。";
  }
  public void ShowLocalizationUnavailable(InspectionPublicResult result){
   ShowLocalization(result);Style("localization_only","已保留初步定位","高亮暂不可用","初步定位已保留 · 请重新检查",Amber);
   actionText.text="高亮暂时无法生成。\n请参考定位框并重新检查。";
  }
  public void ShowResult(InspectionPublicResult result,int[] plateBox){
   lastKnownPending=false;actionText.rectTransform.anchorMin=new Vector2(.07f,.055f);
   unclassifiedVisible=result!=null&&result.unclassified_count>0;partialVisible=result!=null&&result.recheck_reason=="incomplete_view";
   if(result==null||result.status=="service_unavailable"){
    Style("service_unavailable","检查暂不可用","请稍后重试","检查暂未完成，请稍后重试",Amber);
    Row(0,"unknown","","","打印板情况待确认");Row(1,"unknown","","","异物情况待确认");Row(2,"unknown","","","残料情况待确认");
    string code=result==null?"unknown":result.failure_code;
    actionText.text=code=="network"?"检查服务连接中断。\n请检查网络或本机代理后重试。":code=="timeout"?"检查服务响应超时。\n请稍后重新检查。":code=="credentials"?"检查服务配置需要更新。\n请联系维护人员检查服务凭据。":code=="rate_limited"?"检查服务暂时繁忙。\n请稍后重新检查。":code=="invalid_response"?"本次检查结果未能确认。\n请保持画面清晰后重新检查。":"请稍后点击重新检查。";return;
   }
   if(result.status=="known_anomalies_removed"){
    Style("known_anomalies_removed","检测目标已移除","处理完成","已移出打印板 · 检测到的目标已处理",Green);
    Row(0,result.plate_state,"已识别打印板","","打印板待确认");Row(1,result.foreign_object_state,"未见明显异物","发现板面异物","异物情况待确认");Row(2,result.residue_state,"未见明显残料","发现板面残料","残料情况待确认");actionText.text="已检测目标均已移出板面。\n可点击复检确认当前板面。";return;
   }
   if(result.status=="needs_user_confirmation"){
    actionText.rectTransform.anchorMin=new Vector2(.07f,.135f);
    Style("needs_user_confirmation","遮挡区域待人工确认","请人工确认","可见板面未见异常 · 左上角待人工确认",Amber);
    Row(0,result.plate_state,"已识别打印板","","打印板待确认");Row(1,"visible_pass","","","");Row(2,"visible_pass","","","");actionText.text="打印头遮住左上角。\n请确认该区域的板面情况。";return;
   }
   if(result.status=="recheck_required"){
    Style("recheck_required","画面已变化","需要重新检查","场景已变化 · 请重新检查",Amber);Row(0,result.plate_state,"已识别打印板","","打印板待确认");Row(1,"unknown","","","异物情况待复检");Row(2,"unknown","","","残料情况待复检");actionText.text="当前场景已有变化。\n请点击重新检查。";return;
   }
   bool anomaly=result.status=="anomaly_detected",clear=result.status=="no_visible_anomaly",visibleClear=result.status=="visible_surface_clear";
   string title=unclassifiedVisible?"发现待确认物体":anomaly?"需要清理打印板":clear?"本次未见明显异常":visibleClear?"可见板面未见异常":partialVisible?"部分板面未确认":"需要重新检查";
   Style(result.status,title,unclassifiedVisible?"物体待确认":anomaly?"发现异常":clear?"本次检查完成":partialVisible?"边缘需补拍":"需要重新检查",unclassifiedVisible?"发现未识别物体 · 请重新检查":anomaly?"需要清理 · 请处理标注区域":clear?"本次照片未见明显异物或残料":partialVisible?"部分边缘被遮挡或未入镜 · 请补拍":"请调整画面后重新检查",unclassifiedVisible?Amber:anomaly?Red:clear?Green:Amber);
   if(visibleClear)headline.color=Green;
   Row(0,result.plate_state,"已识别打印板","","打印板情况待确认");Row(1,result.foreign_object_state,"未见明显异物","发现板面异物","异物情况待确认");Row(2,result.residue_state,"未见明显残料","发现板面残料","残料情况待确认");
   actionText.text=unclassifiedVisible?"板面出现待确认区域。\n点击重新检查确认物体类型。":anomaly?"清理板面上的异物及残料。\n处理完成后点击重新检查。":clear?"场景变化或放入物品后，\n请重新检查。":visibleClear?"可见区域未见明显异常。\n请补拍被遮挡或未入镜的边缘。":partialVisible?"部分板面被遮挡或未入镜。\n请调整角度补拍该区域。":"让整块打印板及边缘入镜，\n再点击重新检查。";
   if(result.occlusion_confirmed){headline.text="本次检查通过";badgeText.text="人工确认通过";bannerText.text="可见板面检查完成 · 遮挡区域已人工确认";actionText.text="已记录本次人工确认。\n场景变化后请重新检查。";}
   bool missingKnown=result.foreign_object_state=="last_detected"||result.residue_state=="last_detected";
   lastKnownPending=anomaly&&missingKnown&&!unclassifiedVisible&&result.foreign_object_state!="fail"&&result.residue_state!="fail";
   if(lastKnownPending){headline.text="上次异常待复检";headline.color=Amber;badgeText.text="等待复检";badgeText.color=Amber;bannerText.text="上次异常尚未复检 · 请重新检查";actionText.text="上次检出的目标位置已丢失。\n处理完成后请重新检查。";}
   if(result.visual_state=="unavailable"){bannerText.text=anomaly?"发现异常 · 位置标注暂不可用":clear?"检查完成 · 位置标注暂不可用":"位置标注暂不可用 · 请复检";if(anomaly)actionText.text="请清理可见异物及残料。\n高亮服务恢复后可重新检查。";}
   else if(result.visual_state=="recovering"||result.visual_state=="partial")ShowTrackingState(result.visual_state);
   else if(result.visual_state=="tracking"&&anomaly&&!lastKnownPending)bannerText.text="需要清理 · 标注持续更新";
  }
  public void ShowTrackingState(string state){
   if(Status=="needs_user_confirmation"||Status=="recheck_required"||Status=="known_anomalies_removed"||lastKnownPending)return;
   if(unclassifiedVisible){bannerText.text="发现未识别物体 · 请重新检查";return;}
   if(partialVisible){bannerText.text="可见区域持续标注 · 请补拍被遮挡的边缘";return;}
   if(state=="tracking")return;
   if(state=="recovering"){bannerText.text="正在恢复标注 · 请保持画面稳定";actionText.text="暂时隐藏不稳定的位置标注。\n检查结论仍来自最近一次检查。";}
   else if(state=="partial"){bannerText.text="部分标注更新中 · 请保持画面稳定";}
   else{bannerText.text=Status=="anomaly_detected"?"异常尚未复检 · 请重新检查":"画面已变化 · 请重新检查";actionText.text="位置已变化，请重新检查。";}
  }
  public void ShowPositionUnavailable(){ShowTrackingState("needs_reinspection");}
 }
}
