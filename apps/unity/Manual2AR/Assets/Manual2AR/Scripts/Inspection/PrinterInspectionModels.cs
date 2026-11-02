using System;
namespace Manual2AR {
 [Serializable] public class InspectionSettings {
  public string backend_url="http://127.0.0.1:8010",default_provider="sam31_cutie",camera_name="";
  public int camera_width=960,camera_height=720,camera_fps=15,capture_max_side=640,jpeg_quality=78,request_timeout_seconds=690,tracking_request_timeout_seconds=35;
  public float tracking_interval_seconds=.125f,rescan_seconds=15,max_overlay_age_ms=1500;
  public float progress_poll_seconds=.25f,telemetry_seconds=5;public int target_render_fps=60;public bool live_preview_inset=true;
  public bool continuous_monitoring;
 }
 [Serializable] public class InspectionTask {public string id,title,description,capture_instruction;public bool available;}
 [Serializable] public class InspectionCatalog {public string title;public InspectionTask[] tasks;}
 [Serializable] public class InspectionBegin {public string task_id="plate_surface",provider,source;}
 [Serializable] public class InspectionRun {public string run_id,provider,source;}
 [Serializable] public class InspectionFrame {public string image_base64,source_sha256,check_id;public int client_frame_id;}
 [Serializable] public class InspectionCheckStart {public string request_id,image_base64,source_sha256;public int client_frame_id;}
 [Serializable] public class InspectionProgress {public string job_id,run_id,check_id,source_sha256,phase,error;public int client_frame_id,revision;public bool finished,cancelled;public InspectionReply result;}
 [Serializable] public class InspectionImages {public InspectionImage[] images;}
 [Serializable] public class InspectionImage {public string id,name,url;}
 [Serializable] public class InspectionDecision {public string status,message,scope,checked_at,next_action;public string[] limitations,semantic_anomaly_ids,unresolved;}
 [Serializable] public class InspectionObject {public string id,kind,label,evidence,semantic_status,segmentation_status,tracking_state;public int[] bbox_0_1000;public float confidence;public bool found,tracking_ready;public string[] reasons;}
 [Serializable] public class InspectionLabels {public string png_base64;public int width,height;public InspectionLabel[] labels;}
 [Serializable] public class InspectionLabel {public string component_id;public int label_id;}
 [Serializable] public class InspectionPublicResult {public string status,plate_state,foreign_object_state,residue_state,visual_state,recheck_reason,failure_code;public bool location_available,requires_occlusion_confirmation,occlusion_confirmed;public string inspection_source_sha256;public int unclassified_count;}
 [Serializable] public class InspectionSceneCandidate {public string id,label_code,proposal_source;public int[] bbox_0_1000;public int pixel_area;}
 [Serializable] public class InspectionReply {public string run_id,check_id,source_sha256,stage,tracking_state;public int client_frame_id,active_tracks;public bool segmentation_skipped;public float elapsed_ms,vlm_ms,segmentation_ms;public InspectionDecision decision;public InspectionObject[] objects;public InspectionLabels label_map;public InspectionPublicResult public_result;public InspectionSceneCandidate[] scene_candidates;}
 [Serializable] public class InspectionConfirmation {public string check_id,inspection_source_sha256;public bool confirmed=true;}
 [Serializable] public class InspectionConfirmationReply {public string check_id,inspection_source_sha256;public InspectionDecision decision;public InspectionPublicResult public_result;}
 [Serializable] public class InspectionSave {public string check_id;}
 [Serializable] public class InspectionSaved {public bool saved;}
 [Serializable] public class InspectionError {public string detail;}
 [Serializable] public class InspectionEvent {public string @event;public InspectionRender data;}
 [Serializable] public class InspectionRender {public string run_id,check_id,source_sha256,job_id,progress_phase;public int client_frame_id,progress_revision;public float request_ms,frame_age_ms,overlay_apply_ms,capture_encode_ms,render_fps,camera_fps,result_fps,applied_fps,unity_frame_p95_ms;public long managed_heap_bytes;public int gc_collections,request_upload_bytes,request_download_bytes,pooled_labels,pooled_boxes;public bool identity_matched,stale_hidden;}
}
