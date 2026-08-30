using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace Manual2AR
{
    public sealed class Manual2ARBackendClient : MonoBehaviour
    {
        [SerializeField]
        string m_BackendBaseUrl = "http://127.0.0.1:8010";

        [SerializeField]
        int m_RequestTimeoutSeconds = 45;

        public string backendBaseUrl
        {
            get => m_BackendBaseUrl;
            set => m_BackendBaseUrl = string.IsNullOrWhiteSpace(value) ? "http://127.0.0.1:8010" : value.TrimEnd('/');
        }

        public IEnumerator LocateEmptySpindle(
            string imageBase64,
            int slotId,
            Action<EmptySpindleLocateResponse, string> onComplete)
        {
            var request = new EmptySpindleLocateRequest
            {
                image_base64 = imageBase64,
                preferred_slot_id = slotId
            };

            yield return PostJson(
                "/api/ams-lite/empty-spool-axle/locate",
                JsonUtility.ToJson(request),
                raw =>
                {
                    var parsed = JsonUtility.FromJson<EmptySpindleLocateResponse>(raw);
                    onComplete?.Invoke(parsed, raw);
                },
                error => onComplete?.Invoke(new EmptySpindleLocateResponse { found = false, error = error }, null));
        }

        public IEnumerator LocateComponents(
            string imageBase64,
            string[] componentIds,
            Action<MultiComponentLocateResponse, string> onComplete)
        {
            var request = new MultiComponentLocateRequest
            {
                image_base64 = imageBase64,
                component_ids = componentIds
            };

            yield return PostJson(
                "/api/components/locate",
                JsonUtility.ToJson(request),
                raw =>
                {
                    var parsed = JsonUtility.FromJson<MultiComponentLocateResponse>(raw);
                    onComplete?.Invoke(parsed, raw);
                },
                error => onComplete?.Invoke(
                    new MultiComponentLocateResponse { error = error },
                    null));
        }

        public IEnumerator InspectBuildPlate(
            string imageBase64,
            int imageRotationDegrees,
            Action<BuildPlateInspectionResponse, string> onComplete)
        {
            var request = new BuildPlateInspectionRequest
            {
                image_base64 = imageBase64,
                image_rotation_degrees = imageRotationDegrees,
                profile_id = "preprint_plate_inspection_v1",
                start_tracking = true
            };

            yield return PostJson(
                "/api/a1-mini/build-plate/inspect",
                JsonUtility.ToJson(request),
                raw =>
                {
                    var parsed = JsonUtility.FromJson<BuildPlateInspectionResponse>(raw);
                    onComplete?.Invoke(parsed, raw);
                },
                error => onComplete?.Invoke(
                    new BuildPlateInspectionResponse
                    {
                        status = "uncertain",
                        safe_to_print = false,
                        headline = "INSPECTION UNCERTAIN · REFRAME BUILD PLATE",
                        error = error
                    },
                    null));
        }

        public IEnumerator InspectFilamentLoading(
            string imageBase64,
            int imageRotationDegrees,
            Action<FilamentLoadingInspectionResponse, string> onComplete)
        {
            var request = new FilamentLoadingInspectionRequest
            {
                image_base64 = imageBase64,
                image_rotation_degrees = imageRotationDegrees,
                profile_id = "ams_lite_filament_loading_v1",
                start_tracking = true
            };

            yield return PostJson(
                "/api/ams-lite/filament-loading/inspect",
                JsonUtility.ToJson(request),
                raw =>
                {
                    var parsed = JsonUtility.FromJson<FilamentLoadingInspectionResponse>(raw);
                    onComplete?.Invoke(parsed, raw);
                },
                error => onComplete?.Invoke(
                    new FilamentLoadingInspectionResponse
                    {
                        status = "uncertain",
                        headline = "LOADING STATE UNCERTAIN",
                        primary_instruction = "REFRAME FEEDER + FILAMENT PATH",
                        secondary_instruction = "KEEP INLET, TIP AND PTFE TUBE VISIBLE",
                        error = error
                    },
                    null));
        }

        public IEnumerator SendTrackingFrame(
            string sessionId,
            string imageBase64,
            string worldAnchorStatus,
            float driftRatio,
            int relocalizationCount,
            Action<TrackingFrameResponse, string> onComplete)
        {
            if (string.IsNullOrEmpty(sessionId))
            {
                onComplete?.Invoke(new TrackingFrameResponse { error = "missing session_id" }, null);
                yield break;
            }

            var request = new TrackingFrameRequest
            {
                image_base64 = imageBase64,
                world_anchor_status = worldAnchorStatus,
                client_drift_ratio = driftRatio,
                client_relocalization_count = relocalizationCount
            };

            yield return PostJson(
                $"/api/tracking/sessions/{sessionId}/frames",
                JsonUtility.ToJson(request),
                raw =>
                {
                    // The backend returns TrackedComponent directly for frame
                    // updates (not { tracked: ... }).  Parsing the old wrapper
                    // silently produced a null mask after every successful call.
                    var tracked = JsonUtility.FromJson<TrackedComponent>(raw);
                    onComplete?.Invoke(new TrackingFrameResponse
                    {
                        session_id = sessionId,
                        tracked = tracked
                    }, raw);
                },
                error => onComplete?.Invoke(new TrackingFrameResponse { error = error }, null));
        }

        public IEnumerator CloseTrackingSession(string sessionId)
        {
            if (string.IsNullOrEmpty(sessionId))
                yield break;

            var url = $"{backendBaseUrl}/api/tracking/sessions/{sessionId}";
            using var request = UnityWebRequest.Delete(url);
            request.timeout = 8;
            yield return request.SendWebRequest();
        }

        IEnumerator PostJson(string path, string json, Action<string> onSuccess, Action<string> onError)
        {
            var url = $"{backendBaseUrl}{path}";
            using var request = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST);
            var payload = Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(payload);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = m_RequestTimeoutSeconds;
            request.SetRequestHeader("Content-Type", "application/json");
            request.SetRequestHeader("Accept", "application/json");

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                var body = request.downloadHandler?.text;
                onError?.Invoke($"{request.responseCode} {request.error} {body}");
                yield break;
            }

            try
            {
                onSuccess?.Invoke(request.downloadHandler.text);
            }
            catch (Exception exception)
            {
                onError?.Invoke($"invalid JSON response: {exception.Message}");
            }
        }
    }
}
