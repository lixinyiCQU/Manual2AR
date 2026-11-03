using System;
namespace Manual2AR
{
    [Serializable] public class UnboxingSettings {
        public string backend_url="http://127.0.0.1:8010",camera_name="";
        public int ui_width=1920,ui_height=1080;
        public int camera_width=1280,camera_height=720,camera_fps=15,request_timeout_seconds=330;
    }
    [Serializable] public class UnboxingTask { public string task_id,task_revision,title,scope;public UnboxingStep[] steps;public string[] entry_requirements;public UnboxingOfficialSection[] official_sections;public UnboxingOfficialSource official_source; }
    [Serializable] public class UnboxingStep {public string id,title,channel,spatial_mode;public bool optional;public UnboxingSubstep[] substeps;}
    [Serializable] public class UnboxingSubstep {public string id,title,display_title;}
    [Serializable] public class UnboxingOfficialSource {public string title,url;}
    [Serializable] public class UnboxingAnimationFrame {public string url,local_file,sha256;public int duration_ms;public float[] uv;}
    [Serializable] public class UnboxingOfficialSection {public string title,url,quote,citation_id,captured_at;}
    [Serializable] public class UnboxingPhoto {public string id,url,local_file,caption,source_url,sha256;public UnboxingAnimationFrame[] animation_frames;}
    [Serializable] public class UnboxingSource {public string id,text,url,captured_at,body_sha256;}
    [Serializable] public class UnboxingDisplayCondition {public string id,text;}
    [Serializable] public class LessonBlock {public string kind,text;public string[] citation_ids;}
    [Serializable] public class LessonSection {public string kind,title;public LessonBlock[] blocks;}
    [Serializable] public class LessonDocument {public string schema_version,chapter_title,step_title,revision;public bool reviewed;public LessonSection[] sections;}
    [Serializable] public class UnboxingPresentation {
        public string title,instruction,substep_title,applicability_note,chapter_context;public bool optional;public string[] warnings,tools,materials;
        public UnboxingPhoto[] images;public UnboxingSource[] sources;
        public UnboxingDisplayCondition[] display_conditions;
        public LessonDocument lesson;
    }
    [Serializable] public class UnboxingObservation {
        public string id,condition,channel,status,evidence,correction,image_url,source_sha256,segmentation,failure_kind;
        public float elapsed_ms;
        public float confidence;public int frame_id;
    }
    [Serializable] public class UnboxingRun {
        public string run_id,task_revision,state_id,pending_id,channel,capture_instruction,current_condition;
        public int revision,step_index,step_count;public bool completed,can_advance,can_back;
        public UnboxingPresentation presentation;public UnboxingObservation[] observations;
    }
    [Serializable] public class UnboxingCommand {public string state_id;public int revision;}
    [Serializable] public class UnboxingConfirmation {public string state_id,inspection_id;public int revision;public bool confirmed;}
    [Serializable] public class UnboxingCapture {
        public string state_id,inspection_id,image_base64,source_sha256;
        public int revision,client_frame_id;
    }
    [Serializable] public class UnboxingError {public string detail;}
}
