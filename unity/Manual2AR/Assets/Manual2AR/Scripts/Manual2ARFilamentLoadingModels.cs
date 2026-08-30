using System;

namespace Manual2AR
{
    [Serializable]
    public sealed class FilamentLoadingInspectionRequest
    {
        public string image_base64;
        public int image_rotation_degrees;
        public string profile_id = "ams_lite_filament_loading_v1";
        public bool start_tracking = true;
    }

    [Serializable]
    public sealed class FilamentLoadingInspectionResponse
    {
        public string profile_id;
        public string profile_version;
        public string prompt_version;
        public string method_label;
        public bool exemplar_guided;
        public string provider;
        public string model;
        public string status;
        public string headline;
        public string primary_instruction;
        public string secondary_instruction;
        public FilamentLoadingPredicateResult[] predicates;
        public FilamentRegionObservation feeder_module;
        public FilamentRegionObservation filament_inlet;
        public FilamentRegionObservation loose_filament_tip;
        public FilamentRegionObservation inserted_filament_at_inlet;
        public FilamentRegionObservation filament_visible_in_ptfe;
        public FilamentLoadingMaskResult[] masks;
        public FilamentLoadingRejectedRegion[] rejected_regions;
        public FilamentLoadingReferenceHashes reference_hashes;
        public string error;
    }

    [Serializable]
    public sealed class FilamentRegionObservation
    {
        public string visible;
        public int[] bbox_0_1000;
        public int[] target_point_0_1000;
        public float confidence;
        public string visible_evidence;
    }

    [Serializable]
    public sealed class FilamentLoadingPredicateResult
    {
        public string predicate_id;
        public bool passed;
        public float confidence;
        public string evidence;
    }

    [Serializable]
    public sealed class FilamentLoadingMaskResult
    {
        public string object_id;
        public string object_type;
        public int[] semantic_box_0_1000;
        public int[] compiled_box_0_1000;
        public int[] target_point_0_1000;
        public string session_id;
        public TrackedComponent tracked;
        public bool tracking_ready;
        public string error;
    }

    [Serializable]
    public sealed class FilamentLoadingRejectedRegion
    {
        public string object_type;
        public string reason;
    }

    [Serializable]
    public sealed class FilamentLoadingReferenceHashes
    {
        public string loaded_sha256;
        public string not_inserted_sha256;
    }

    [Serializable]
    public sealed class FilamentLoadingEvidenceLog
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
        public string loading_status;
        public string[] session_ids;
        public string loaded_reference_sha256;
        public string not_inserted_reference_sha256;
        public string camera_device;
        public int image_rotation_degrees;
        public bool image_vertically_mirrored;
        public string guidance_space;
        public string captured_at;
    }
}
