using System;
namespace Manual2AR.Spatial {
 [Serializable] public class TargetInstance {public string id,label,short_label;}
 [Serializable] public class ActionUnit {public string action_id,chapter_id,substep_id,title,kind,instruction,authoring_instruction,official_text,source_url,verification_mode,applicability_note,relocation_note,playback_caption;public int primary_reference_index;public string[] reference_images,citation_ids;public TargetInstance[] target_instances;}
 [Serializable] public class SpatialChapter {public string id,title;}
 [Serializable] public class Plan {public string task_id,variant_id,snapshot_id,print_url;public ActionUnit[] actions;public SpatialChapter[] chapters;}
 [Serializable] public class Begin {public string camera_id,rig_id="a1-mini",mode="camera",tutorial_run_id="";public bool reuse_targets;}
 [Serializable] public class Session {public string session_id,mode;public bool calibrated,has_saved_targets,target_reuse_confirmed;}
 [Serializable] public class CaptureSnapshot {public string schema_version="manual2ar-capture-v1",provider_id,source_sha256,pixel_domain="upright_unmirrored",reference_space_id="";public int client_frame_id,width,height;public double capture_monotonic_ms;public float[] camera_intrinsics=new float[0],world_from_camera=new float[0];}
 [Serializable] public class Frame {public int client_frame_id;public string image_base64,source_sha256,action_id,target_id="main";public bool calibration_sample;public CaptureSnapshot snapshot;}
 [Serializable] public class Pixel {public float x,y;public Pixel(float a,float b){x=a;y=b;}}
 [Serializable] public class Segment {public Pixel a,b;}
 [Serializable] public class Pose {public float[] matrix;public float reprojection_px;public Pixel[] corners;}
 [Serializable] public class GuidanceVisual {public string kind,label,schema_version;public Pixel anchor;public Pixel[] trajectory;public Segment[] tool_lines;public float duration_seconds=3;public bool illustrative_only;}
 [Serializable] public class Reply {public string session_id,source_sha256,action_id,state,target_id,target_label;public int client_frame_id,width,height,sample_count;public float processing_ms;public bool target_ready,target_configured,requires_relocation,calibrated;public Pose pose;public Segment[] lines;public GuidanceVisual visual;}
 [Serializable] public class Author {public string action_id,target_id="main";public int first_frame,second_frame;public Pixel[] first_points,second_points;}
 [Serializable] public class Candidate {public string candidate_id,action_id,message;public float maximum_reprojection_px,minimum_ray_angle_deg;}
 [Serializable] public class Save {public string candidate_id;public bool confirmed=true;}
 [Serializable] public class Verify {public string action_id,target_id="main";public int client_frame_id;}
 [Serializable] public class Check {public string status,evidence,next_action,source_sha256,action_id;public int client_frame_id;}
 [Serializable] public class Failure {public string detail;}
 [Serializable] public class Interaction {public string event_id,action_id,target_id="main",name,source_sha256="";public int client_frame_id;public float progress,request_ms,presentation_fps;}
 [Serializable] public class InteractionResult {public bool relocation_required;}
 [Serializable] public class Outline {public Pixel[] points;}
 [Serializable] public class LocationPreview {public string status,session_id,action_id,target_id,source_sha256,segmentation;public int client_frame_id,width,height;public Segment[] box_lines;public Outline[] outlines;}
}
