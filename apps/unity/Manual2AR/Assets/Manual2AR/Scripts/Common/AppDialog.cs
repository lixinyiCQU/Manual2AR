using System;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace Manual2AR {
 public enum AppDialogSize {Compact,Standard,Large}
 /// <summary>Common modal sizing, focus and dismissal. Closing never implies task approval.</summary>
 public sealed class AppDialog:MonoBehaviour {
  public RectTransform Panel {get;private set;}
  Action dismiss;GameObject previousFocus;
  public static AppDialog Open(Transform parent,string name,string title,AppDialogSize size,Action close){
   var root=AppTheme.Rect(parent,name,Vector2.zero,Vector2.one);var dialog=root.gameObject.AddComponent<AppDialog>();dialog.dismiss=close;
   dialog.previousFocus=EventSystem.current==null?null:EventSystem.current.currentSelectedGameObject;
   AppModalBackdrop.Attach(root.gameObject);
   Vector2 min=size==AppDialogSize.Compact?new Vector2(.28f,.30f):size==AppDialogSize.Large?new Vector2(.055f,.05f):new Vector2(.18f,.16f);
   dialog.Panel=AppTheme.Panel(root,"Dialog content",min,Vector2.one-min);
   AppTheme.Label(dialog.Panel,title,new Vector2(.04f,.86f),new Vector2(.86f,.98f),AppTheme.TitleSize,AppTheme.TargetCyan);
   var button=AppTheme.Button(dialog.Panel,"关闭",new Vector2(.88f,.87f),new Vector2(.97f,.97f),dialog.Dismiss,AppIcon.Close);
   button.GetComponentInChildren<Text>().gameObject.SetActive(false);
   var icon=button.GetComponentInChildren<AppIconGraphic>();icon.rectTransform.anchorMin=new Vector2(.2f,.2f);icon.rectTransform.anchorMax=new Vector2(.8f,.8f);
   return dialog;
  }
  void Dismiss(){if(dismiss!=null)dismiss();else Close();}
  public void Close(){gameObject.SetActive(false);Destroy(gameObject);}
  void Update(){
   if(!Input.GetKeyDown(KeyCode.Escape))return;
   int order=GetComponent<Canvas>().sortingOrder;
   foreach(var other in FindObjectsOfType<AppModalBackdrop>())if(other.gameObject!=gameObject&&other.GetComponent<Canvas>().sortingOrder>order)return;
   Dismiss();
  }
  void OnDisable(){if(EventSystem.current!=null&&previousFocus!=null&&previousFocus.activeInHierarchy)EventSystem.current.SetSelectedGameObject(previousFocus);}
 }
}
