using System;
namespace Manual2AR
{
    [Serializable] public class U7Sequence {public bool enforced=true,base_approved,holder_approved;public string message;}
    [Serializable] public class GuidanceThumbnail {public string url,local_file,sha256;}
    [Serializable] public class GuidanceVariant {public string id,title,task_revision;public int step_count;}
    [Serializable] public class GuidanceTaskEntry {public string id,title,description,default_variant;public GuidanceVariant[] variants;public GuidanceThumbnail thumbnail;}
    [Serializable] public class GuidanceCatalog {public string title,scope;public GuidanceTaskEntry[] tasks;}
    [Serializable] public class GuidanceStart {public string task_id,variant_id;}
    [Serializable] public class GuidanceAction {public string id,label;}
    [Serializable] public class GuidanceReceipt {public string run_id,task_id,title,status,task_revision,recorded_at;}
    [Serializable] public class GuidanceBrowse {public string state_id,target_state_id,substep_id;public int revision;}
    [Serializable] public class SpatialLearningRecord {public string action_id,chapter_id,target_id,mode,at;public string @event;public bool operation_verified;}
    [Serializable] public class TutorialSpatialGuidance {public bool available;public string scope_label,record_url;public string[] current_action_ids;public Spatial.ActionUnit[] actions;public SpatialLearningRecord[] learning_records;}
    [Serializable] public class ChapterCompletion {public string state_id,source;public bool completed;}
    [Serializable] public class GuidanceRun : UnboxingRun {
        public string task_id,variant_id,status,parent_run_id,device_context_id,flow_label,completion_scope,flow_notice;
        public string navigation_policy,verification_role,selected_substep_id,completion_source;
        public string[] visited_step_ids,user_marked_step_ids;public UnboxingSubstep[] substeps;
        public bool can_cancel;public int last_client_frame_id;
        public UnboxingTask task_info;public GuidanceAction[] available_actions;public GuidanceReceipt[] child_receipts;
        public ChapterCompletion[] chapter_completion;public TutorialSpatialGuidance spatial_guidance;public U7Sequence u7_sequence;
    }
    [Serializable] public class GuidanceActionCommand {public string state_id;public int revision;public bool confirmed;}
}
