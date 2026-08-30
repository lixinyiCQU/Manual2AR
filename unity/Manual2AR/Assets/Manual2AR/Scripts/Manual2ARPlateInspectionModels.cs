using System;

namespace Manual2AR
{
    [Serializable]
    public sealed class BuildPlateInspectionRequest
    {
        public string image_base64;
        public int image_rotation_degrees;
        public string profile_id = "preprint_plate_inspection_v1";
        public bool start_tracking = true;
    }

    [Serializable]
    public sealed class BuildPlateInspectionResponse
    {
        public string profile_id;
        public string profile_version;
        public string prompt_version;
        public string method_label;
        public bool exemplar_guided;
        public string provider;
        public string model;
        public string status;
        public bool safe_to_print;
        public string headline;
        public string[] correction_instructions;
        public InspectionPredicateResult[] predicates;
        public BuildPlateObservation plate;
        public InspectionMaskResult plate_mask;
        public InspectionMaskResult[] anomalies;
        public InspectionRejectedCandidate[] rejected_candidates;
        public ReferenceHashes reference_hashes;
        public string error;
    }

    [Serializable]
    public sealed class BuildPlateObservation
    {
        public string present;
        public string aligned;
        public string fully_visible;
        public int[] bbox_0_1000;
        public int[] target_point_0_1000;
        public float confidence;
        public string visible_evidence;
    }

    [Serializable]
    public sealed class InspectionPredicateResult
    {
        public string predicate_id;
        public bool passed;
        public float confidence;
        public string evidence;
    }

    [Serializable]
    public sealed class InspectionMaskResult
    {
        public string object_id;
        public string object_type;
        public int[] semantic_box_0_1000;
        public int[] compiled_box_0_1000;
        public int[] target_point_0_1000;
        public string session_id;
        public TrackedComponent tracked;
        public bool tracking_ready;
        public float mask_containment_in_plate;
        public string error;
    }

    [Serializable]
    public sealed class InspectionRejectedCandidate
    {
        public string reason;
        public bool benign_exclusion;
    }

    [Serializable]
    public sealed class ReferenceHashes
    {
        public string clean_p2_sha256;
        public string dirty_p1_sha256;
    }

    [Serializable]
    public sealed class PlateInspectionEvidenceLog
    {
        public string figure_id;
        public string backend_base_url;
        public string profile_id;
        public string profile_version;
        public string prompt_version;
        public string method_label;
        public bool exemplar_guided;
        public string provider;
        public string model;
        public bool safe_to_print;
        public string inspection_status;
        public string[] session_ids;
        public string clean_reference_sha256;
        public string dirty_reference_sha256;
        public string camera_device;
        public int image_rotation_degrees;
        public bool image_vertically_mirrored;
        public string guidance_space;
        public string captured_at;
    }
}

