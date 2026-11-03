using System;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
 /// <summary>One scrollable selector for variable-length teaching lists.</summary>
 public static class AppDropdown {
  public static Dropdown Create(Transform parent,string name,Vector2 min,Vector2 max,Action<int> changed=null){
   var box=AppTheme.Panel(parent,name,min,max);box.GetComponent<Image>().color=AppTheme.ButtonBackground;
   var dropdown=box.gameObject.AddComponent<Dropdown>();dropdown.targetGraphic=box.GetComponent<Image>();
   dropdown.captionText=AppTheme.Label(box,"",new Vector2(.035f,.04f),new Vector2(.90f,.96f),23);
   AppTheme.Label(box,"▾",new Vector2(.91f,.04f),new Vector2(.98f,.96f),23);
   var template=AppTheme.Panel(box,"Template",new Vector2(0,0),new Vector2(1,0));template.pivot=new Vector2(.5f,1);template.sizeDelta=new Vector2(0,260);
   var scroll=template.gameObject.AddComponent<ScrollRect>();scroll.horizontal=false;scroll.scrollSensitivity=38;scroll.movementType=ScrollRect.MovementType.Clamped;
   var viewport=AppTheme.Rect(template,"Viewport",Vector2.zero,Vector2.one);viewport.gameObject.AddComponent<RectMask2D>();
   var content=AppTheme.Rect(viewport,"Content",new Vector2(0,1),new Vector2(1,1));content.pivot=new Vector2(.5f,1);content.sizeDelta=new Vector2(0,52);
   var item=AppTheme.Panel(content,"Item",new Vector2(0,.5f),new Vector2(1,.5f));item.sizeDelta=new Vector2(0,52);
   var toggle=item.gameObject.AddComponent<Toggle>();toggle.targetGraphic=item.GetComponent<Image>();
   var check=AppTheme.Rect(item,"Selected",new Vector2(.015f,.22f),new Vector2(.025f,.78f)).gameObject.AddComponent<Image>();check.color=AppTheme.TargetCyan;toggle.graphic=check;
   dropdown.itemText=AppTheme.Label(item,"",new Vector2(.045f,0),new Vector2(.98f,1),23);
   scroll.viewport=viewport;scroll.content=content;dropdown.template=template;template.gameObject.SetActive(false);
   if(changed!=null)dropdown.onValueChanged.AddListener(index=>changed(index));return dropdown;
  }
 }
}
