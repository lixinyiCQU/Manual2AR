using System;

namespace Manual2AR
{
    [Serializable]
    public sealed class EmptySpindleLocateRequest
    {
        public string image_base64;
        public int preferred_slot_id = 4;
    }

    [Serializable]
    public sealed class EmptySpindleLocateResponse
    {
        public bool found;
        public EmptySpindleCandidate candidate;
        public string session_id;
        public TrackedComponent tracked;
        public string provider;
        public string model;
        public bool tracking_ready;
        public string error;
    }

    [Serializable]
    public sealed class EmptySpindleCandidate
    {
        public bool found;
        public int slot_id;
        public string label;
        public int[] bbox_0_1000;
        public int[] target_point_0_1000;
        public float confidence;
        public string visible_evidence;
        public string failure_reason;
        public string proposal_source;
    }

    [Serializable]
    public sealed class TrackedComponent
    {
        public string component_id;
        public string status;
        public float quality;
        public int[] bbox_0_1000;
        public int[] polygon_0_1000;
        public int[] centroid_0_1000;
        public string overlay_png_base64;
        public string provider;
        public bool requires_redetection;
        public bool mask_quality_passed;
        public string[] mask_quality_reasons;
        public float mask_area_ratio;
        public float prompt_containment;
        public string overlay_semantic;
        public int frame_index;
        public string world_anchor_status;
        public float drift_ratio;
        public int relocalization_count;
    }

    [Serializable]
    public sealed class TrackingFrameRequest
    {
        public string image_base64;
        public string world_anchor_status;
        public float client_drift_ratio;
        public int client_relocalization_count;
    }

    [Serializable]
    public sealed class TrackingFrameResponse
    {
        public string session_id;
        public TrackedComponent tracked;
        public string error;
    }

    [Serializable]
    public sealed class MultiComponentLocateRequest
    {
        public string image_base64;
        public string[] component_ids;
    }

    [Serializable]
    public sealed class MultiComponentLocateResponse
    {
        public LocatedComponentResult[] results;
        public string provider;
        public string model;
        public string error;
    }

    [Serializable]
    public sealed class LocatedComponentResult
    {
        public string component_id;
        public string english_label;
        public bool found;
        public SemanticComponentCandidate candidate;
        public string session_id;
        public TrackedComponent tracked;
        public bool tracking_ready;
        public string error;
    }

    [Serializable]
    public sealed class SemanticComponentCandidate
    {
        public string component_id;
        public bool found;
        public int[] bbox_0_1000;
        public int[] target_point_0_1000;
        public float confidence;
        public string visible_evidence;
        public string failure_reason;
    }
}
