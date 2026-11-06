using System;
namespace Manual2AR.Spatial {
 [Serializable] public class TargetInstance {public string id,label,short_label;}
 [Serializable] public class ActionUnit {public string action_id,chapter_id,substep_id,title,kind,instruction,authoring_instruction,official_text,source_url,verification_mode,applicability_note,relocation_note,playback_caption,capture_guidance,ready_hint;public int primary_reference_index;public string[] reference_images,citation_ids,authoring_points;public TargetInstance[] target_instances;public MotionParameters machine_motion;}
 [Serializable] public class SpatialChapter {public string id,title;}
 [Serializable] public class Plan {public bool automatic_configuration;public string task_id,variant_id,snapshot_id,print_url,visual_revision,required_client_revision;public Manual2AR.VisualGuidance.AssetLibraryDescriptor asset_library;public Manual2AR.VisualGuidance.GuidanceDisplay[] display_profiles;public ActionUnit[] actions;public SpatialChapter[] chapters;}
 [Serializable] public class Begin {public string camera_id,rig_id="a1-mini",mode="camera",tutorial_run_id="",visual_client_revision="machine-workframe-v1";public bool reuse_targets;}
 [Serializable] public class Session {public string session_id,mode;public bool calibrated,has_saved_targets,has_saved_machine_frame,target_reuse_confirmed;public U7Sequence u7_sequence;}
 [Serializable] public class CaptureSnapshot {public string schema_version="manual2ar-capture-v1",provider_id,source_sha256,pixel_domain="upright_unmirrored",reference_space_id="";public int client_frame_id,width,height;public double capture_monotonic_ms;public float[] camera_intrinsics=new float[0],world_from_camera=new float[0];}
 [Serializable] public class Frame {public int client_frame_id;public string image_base64,source_sha256,action_id,target_id="main";public bool calibration_sample;public CaptureSnapshot snapshot;}
 [Serializable] public class Pixel {public float x,y;public Pixel(float a,float b){x=a;y=b;}}
 [Serializable] public class Segment {public Pixel a,b;}
 [Serializable] public class Pose {public float[] matrix;public float reprojection_px;public Pixel[] corners;}
 [Serializable] public class SpatialProjection {public float[] camera_from_marker,intrinsics,distortion;}
 [Serializable] public class GuidanceAsset {public string asset_id,motion;public float[] marker_from_asset,translation_m;}
 [Serializable] public class GuidanceVisual {public Manual2AR.VisualGuidance.GuidanceDisplay display;public Manual2AR.VisualGuidance.VisualTextLabel[] text_labels;public string kind,label,schema_version;public Pixel anchor;public Pixel[] trajectory;public Segment[] tool_lines;public float duration_seconds=3;public bool illustrative_only;public SpatialProjection projection;public GuidanceAsset asset;public Axis[] axes;public MotionParameters motion_parameters;public string machine_frame_id;public Manual2AR.VisualGuidance.VisualPresentation presentation;}
 [Serializable] public class Preflight {public bool has_cached_target,has_cached_machine,marker_visible,can_start;public Pixel anchor;}
 [Serializable] public class Reply {public GuidanceVisual[] companion_visuals;public Preflight preflight;public string session_id,source_sha256,action_id,state,target_id,target_label,placement_method,placement_note;public int client_frame_id,width,height,sample_count;public float processing_ms;public bool target_ready,target_configured,requires_relocation,calibrated;public Pose pose;public Segment[] lines;public GuidanceVisual visual;public Axis[] reference_axes;public Orientation orientation;public MachineFrame machine_frame;public Axis[] machine_axes;public MotionParameters motion_parameters;public U7Sequence u7_sequence;}
 [Serializable] public class Author {public string action_id,target_id="main";public int first_frame,second_frame;public Pixel[] first_points,second_points;}
 [Serializable] public class Candidate {public string candidate_id,action_id,message;public float maximum_reprojection_px,minimum_ray_angle_deg;public Axis[] preview_axes;}
 [Serializable] public class Save {public string candidate_id;public bool confirmed=true;}
 [Serializable] public class Verify {public string action_id,target_id="main";public int client_frame_id;}
 [Serializable] public class Check {public U7Sequence u7_sequence;public string status,evidence,next_action,source_sha256,action_id;public int client_frame_id;}
 [Serializable] public class Failure {public string detail;}
 [Serializable] public class Interaction {public string event_id,action_id,target_id="main",name,source_sha256="";public int client_frame_id;public float progress,request_ms,presentation_fps;public int visible_triangles;public string renderer_id;}
 [Serializable] public class InteractionResult {public bool relocation_required;}
 [Serializable] public class Outline {public Pixel[] points;}
 [Serializable] public class LocationPreview {public string evidence,next_action,status,session_id,action_id,target_id,source_sha256,segmentation;public int client_frame_id,width,height;public Segment[] box_lines;public Outline[] outlines;}
 [Serializable] public class Axis {public string id;public Pixel a,b;}
 [Serializable] public class Orientation {public string action_id,target_id="main";public float[] rotation_degrees=new float[3];public int rotation_sign=1;}
 [Serializable] public class ImageProxy {public string asset_id,coordinate_space;public int[] bbox_0_1000;public float angle_degrees;public bool illustrative_only;}
 [Serializable] public class LocatedPart {public string component_id,status,evidence;public int[] bbox_0_1000;public ImageProxy proxy;}
 [Serializable] public class PartStatus {public string job_id,session_id,phase,source_sha256,next_action,guidance,overlay_png_base64;public int client_frame_id,width,height;public LocatedPart[] parts;}
 [Serializable] public class MachineFrame {public string schema_version,frame_id,reference_space_id,placement_method,reference_profile_id;public float[] marker_from_machine;}
 [Serializable] public class MotionParameters {public string schema_version="manual2ar-teaching-motion-v1",axis="Z";public bool enabled=true;public int direction=-1,rotation_sign=1;public float distance_mm=60,duration_seconds=1.2f,rotation_degrees=360;public ComponentMotion[] components=new ComponentMotion[0];}
 [Serializable] public class ComponentMotion {public string id;public bool visible=true,playing=true;public float[] rotation_degrees=new float[3],offset_mm=new float[3];public float scale=1,speed=1;public int rotation_sign=0;}
 [Serializable] public class MotionCommand {public string action_id;public MotionParameters parameters;}
 [Serializable] public class MachineAuthor {public int first_frame,second_frame;public Pixel[] first_points,second_points;}
 [Serializable] public class PrintedReference {public int client_frame_id;public bool placement_confirmed=true;}
 [Serializable] public class AutomaticPoint {public string id;public Pixel point;}
 [Serializable] public class AutomaticView {public string view_id,session_id,source_sha256,action_id,message;public int client_frame_id;public AutomaticPoint[] points;}
 [Serializable] public class AutomaticPair {public string action_id,first_view,second_view;public int second_frame;}
 [Serializable] public class AutomaticCandidate {public string candidate_id,session_id,source_sha256,message;public int client_frame_id,target_count;public bool slide_ready,slide_illustrative;public AutomaticPoint[] points;}
}
