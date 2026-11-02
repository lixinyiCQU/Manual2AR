using System;
namespace Manual2AR
{
    // Clearing is allowed during inference. An old response can never restore
    // masks after its revision was invalidated, even after clearing finishes.
    public sealed class LearningInteractionState {
        public bool Busy { get; set; }
        public bool Clearing { get; private set; }
        public int Revision { get; private set; }
        public bool CanStartInference { get { return !Busy&&!Clearing; } }
        public bool TryBeginClear() {
            if(Clearing)return false;
            Clearing=true;Revision++;return true;
        }
        public bool AcceptsReply(int revision) { return !Clearing&&revision==Revision; }
        public void InvalidateReplies() { Revision++; }
        public bool CanUseControls(bool trackingInFlight,bool userActionPending) { return !Clearing&&!userActionPending&&(!Busy||trackingInFlight); }
        public void FinishClear() { Busy=false;Clearing=false; }
    }
    [Serializable] public class LearningSettings {
        public string backend_url="http://127.0.0.1:8010",camera_name="",default_provider="sam31_cutie",knowledge_file="LearningKnowledge.json";
        public int camera_width=960,camera_height=720,camera_fps=15,request_timeout_seconds=450;
        public float tracking_interval_seconds=.1f;
        public int capture_max_side=640,jpeg_quality=78,tracking_request_timeout_seconds=3;
        public float cutie_tracking_interval_seconds=.125f;
        public int cutie_tracking_request_timeout_seconds=40;
        public string preview_mode="live";public float max_overlay_age_ms=1500,telemetry_seconds=2;public int target_render_fps=60;
        public int ui_width=1920,ui_height=1080;public string ui_version="V3.1";
    }
    [Serializable] public class LearningKnowledge {
        public string schema_version,revision,title,device_name;
        public LearningCard[] cards; public string[] device_description;public LearningSource[] device_more_information;
    }
    [Serializable] public class LearningPhoto { public string id,local_file,url,caption; }
    [Serializable] public class LearningSource { public string title,url,category,page_id,anchor; }
    [Serializable] public class LearningCard {
        public string id,target_id,name,english;
        public string[] description;
        public LearningPhoto[] images; public LearningSource[] more_information;
    }
    [Serializable] public class LearningWikiDocument {
        public string state,title,page_id,message;public int width,height,tile_height;
        public LearningWikiTile[] tiles;public LearningWikiAnchor[] anchors;public LearningWikiLink[] links;
    }
    [Serializable] public class LearningWikiTile { public int index,y,height;public string url; }
    [Serializable] public class LearningWikiAnchor { public string id,title;public float y;public bool is_heading; }
    [Serializable] public class LearningWikiLink { public string page_id,anchor,title;public float x,y,width,height; }
    [Serializable] public class LearningImages { public LearningInputImage[] images; }
    [Serializable] public class LearningInputImage { public string id,name,preview_url; }
    [Serializable] public class LearningBegin { public string provider,source; }
    [Serializable] public class LearningRun { public string run_id,knowledge_revision,provider;public bool fallback_used; }
    [Serializable] public class LearningFrame { public string image_base64,source_image_id,expected_source_sha256; public int client_frame_id; public float capture_time_ms; }
    [Serializable] public class LearningCandidate { public bool found; public int[] bbox_0_1000,target_point_0_1000; public float confidence; public string visible_evidence; }
    [Serializable] public class LearningTracked {
        public string component_id,status,provider,overlay_png_base64;public float quality,mask_area_ratio,prompt_containment,drift_ratio;
        public bool requires_redetection,mask_quality_passed;public int[] bbox_0_1000,centroid_0_1000;public string[] mask_quality_reasons;
        public int frame_index,relocalization_count;
        public string tracking_state;public bool retained_for_recovery;
        public int[] mask_roi_xywh;public int mask_frame_width,mask_frame_height;
    }
    [Serializable] public class LearningResult {
        public string component_id,session_id,error,stage; public bool found,tracking_ready,retained_for_recovery;
        public LearningCandidate candidate; public LearningTracked tracked;
    }
    [Serializable] public class LearningReply { public bool fallback_used;
        public string run_id,check_id,source_sha256,knowledge_revision,first_mask_provider;
        public LearningLabelMap label_map;public int client_frame_id,frame_id,active_sessions; public float elapsed_ms,vlm_ms; public LearningResult[] results;
    }
    [Serializable] public class LearningLabel { public string component_id;public int label_id; }
    [Serializable] public class LearningLabelMap { public string png_base64;public int width,height;public LearningLabel[] labels; }
    [Serializable] public class LearningImageBody { public string image_base64; }
    [Serializable] public class LearningError { public string detail; }
    [Serializable] public class LearningEvent { public string @event; public LearningReceipt data; }
    [Serializable] public class LearningReceipt {
        public string check_id,component_id,card_id,citation_id,source,device,reason,knowledge_revision,source_sha256;
        public float request_ms,capture_time_ms,capture_encode_ms,frame_age_ms;
        public int client_frame_id,frame_id,image_width,image_height,rotation;
        public bool vertically_mirrored,stale_rejected,overlay_expired,tracking_active,tracking_paused,inference_inflight;public float expired_seconds;public float overlay_apply_ms,render_fps,camera_fps,result_fps,applied_fps,unity_frame_p50_ms,unity_frame_p95_ms;
        public int gc_collections,frames_over_33_ms,request_upload_bytes,request_download_bytes,skipped_camera_frames;
        public long managed_heap_bytes;public string preview_mode; public LearningRenderItem[] results;
    }
    [Serializable] public class LearningRenderItem {
        public string component_id,reason; public bool attempted,passed; public float decode_ms;
        public int[] bbox_0_1000; public float[] image_rect;
    }
}
