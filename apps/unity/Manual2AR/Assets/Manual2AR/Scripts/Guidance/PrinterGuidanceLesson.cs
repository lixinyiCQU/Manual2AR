using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace Manual2AR {
    /// <summary>Typed lesson sections, independent of verification and official image loading.</summary>
    public sealed partial class PrinterGuidanceController {
        readonly HashSet<string> expandedLessonNotes=new HashSet<string>();
        static readonly Color CautionInk=new Color(1,.82f,.48f),ReadingInk=new Color(.91f,.95f,.98f);

        protected override void RebuildBody(){
            foreach(Transform child in body){child.gameObject.SetActive(false);Destroy(child.gameObject);}
            var lesson=run.presentation.lesson;
            chapterHeading.text=AppTheme.Readable(lesson==null?run.presentation.title:lesson.chapter_title);
            if(lesson!=null&&lesson.sections!=null){
                foreach(var section in lesson.sections){
                    if(section.blocks==null||section.blocks.Length==0)continue;
                    if(section.kind=="note")BuildSupplement(section);else BuildLessonSection(section);
                }
            }else{
                // Older backends remain readable; never concatenate notes into operations.
                BuildLessonSection(new LessonSection{kind="action",title="操作指导",blocks=new[]{new LessonBlock{text=run.presentation.instruction}}});
                if(run.presentation.warnings!=null&&run.presentation.warnings.Length>0){
                    var blocks=new List<LessonBlock>();foreach(string warning in run.presentation.warnings)blocks.Add(new LessonBlock{text=warning});
                    BuildLessonSection(new LessonSection{kind="caution",title="注意事项",blocks=blocks.ToArray()});
                }
            }
            if(!Free&&run.channel=="manual"&&!run.completed){
                BuildLessonSection(new LessonSection{kind="scope",title="完成后请确认",blocks=new[]{new LessonBlock{text=ConditionLabel(run.pending_id,run.current_condition)}}});
                if(!string.IsNullOrEmpty(Current.flow_notice))Paragraph(body,Current.flow_notice,23,AppTheme.Muted);
            }
            var layout=body.GetComponent<VerticalLayoutGroup>();layout.spacing=28;layout.padding=new RectOffset(12,22,10,28);
            LayoutRebuilder.ForceRebuildLayoutImmediate(body);
            var scroll=body.parent.parent.GetComponent<ScrollRect>();scroll.movementType=ScrollRect.MovementType.Clamped;scroll.scrollSensitivity=45;scroll.verticalNormalizedPosition=1;
        }

        RectTransform ReadingGroup(string name,Color? background=null){
            var panel=Rect(name,body,Vector2.zero,Vector2.one);
            if(background.HasValue)panel.gameObject.AddComponent<AppRoundedImage>().color=background.Value;
            var layout=panel.gameObject.AddComponent<VerticalLayoutGroup>();layout.childControlHeight=layout.childControlWidth=true;layout.childForceExpandHeight=false;
            layout.spacing=32;layout.padding=background.HasValue?new RectOffset(22,22,20,24):new RectOffset(0,0,4,8);
            return panel;
        }

        void SectionHeading(RectTransform parent,string title,Color color,AppIcon? symbol){
            var row=Rect(title,parent,Vector2.zero,Vector2.one);row.gameObject.AddComponent<LayoutElement>().preferredHeight=38;
            float left=0;
            if(symbol.HasValue){var icon=Rect("注意图标",row,new Vector2(0,.15f),new Vector2(.06f,.85f)).gameObject.AddComponent<AppIconGraphic>();icon.symbol=symbol.Value;icon.color=color;icon.raycastTarget=false;left=.085f;}
            var text=TextAt(row,title,new Vector2(left,0),Vector2.one,25);text.color=color;text.fontStyle=FontStyle.Bold;
        }

        void BuildLessonSection(LessonSection section){
            bool caution=section.kind=="caution"||section.kind=="precondition";
            bool scope=section.kind=="scope";
            var panel=ReadingGroup(section.title,caution?(Color?)new Color(.16f,.105f,.045f):(scope||section.kind=="action")?(Color?)new Color(.035f,.14f,.19f):null);
            SectionHeading(panel,section.title,caution?CautionInk:Cyan,caution?(AppIcon?)AppIcon.Warning:section.kind=="action"?(AppIcon?)AppIcon.Tool:null);
            int number=0;
            foreach(var block in section.blocks){
                if(section.kind=="action")NumberedInstruction(panel,++number,block.text);
                else Paragraph(panel,(section.kind=="materials"?"•  ":"")+block.text,caution?24:25,caution?new Color(1,.92f,.78f):ReadingInk);
            }
        }

        void NumberedInstruction(RectTransform parent,int number,string instruction){
            var row=Rect("操作 "+number,parent,Vector2.zero,Vector2.one);var layout=row.gameObject.AddComponent<HorizontalLayoutGroup>();layout.childControlWidth=layout.childControlHeight=true;layout.childForceExpandWidth=layout.childForceExpandHeight=false;layout.spacing=14;layout.childAlignment=TextAnchor.UpperLeft;
            var badge=Rect("步骤编号",row,Vector2.zero,Vector2.one).gameObject.AddComponent<Text>();badge.font=font;badge.fontSize=26;badge.color=Cyan;badge.text=number.ToString("00");badge.alignment=TextAnchor.UpperLeft;
            var width=badge.gameObject.AddComponent<LayoutElement>();width.minWidth=width.preferredWidth=40;width.minHeight=38;
            Paragraph(row,instruction,26,ReadingInk);row.GetChild(row.childCount-1).GetComponent<LayoutElement>().flexibleWidth=1;
        }

        void BuildSupplement(LessonSection section){
            var panel=ReadingGroup("补充说明",new Color(.035f,.09f,.13f));
            var toggle=AppTheme.Button(panel,"补充说明",Vector2.zero,Vector2.one,()=>{},AppIcon.Info);
            toggle.gameObject.AddComponent<LayoutElement>().preferredHeight=54;
            var content=Rect("补充说明正文",panel,Vector2.zero,Vector2.one);var layout=content.gameObject.AddComponent<VerticalLayoutGroup>();layout.childControlHeight=layout.childControlWidth=true;layout.childForceExpandHeight=false;layout.spacing=28;
            foreach(var block in section.blocks)Paragraph(content,block.text,24,AppTheme.Muted);
            string key=presentationKey;bool open=expandedLessonNotes.Contains(key);content.gameObject.SetActive(open);
            System.Action update=()=>toggle.GetComponentInChildren<Text>().text="补充说明（"+section.blocks.Length+" 项） · "+(content.gameObject.activeSelf?"收起":"展开");
            update();toggle.onClick.AddListener(()=>{bool show=!content.gameObject.activeSelf;content.gameObject.SetActive(show);if(show)expandedLessonNotes.Add(key);else expandedLessonNotes.Remove(key);update();LayoutRebuilder.ForceRebuildLayoutImmediate(body);});
        }
    }
}
