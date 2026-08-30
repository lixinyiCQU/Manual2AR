using System;
using System.Text;
using UnityEngine;

namespace Manual2AR
{
    public enum Manual2ARCameraMode
    {
        Auto = 0,
        MacBuiltIn = 1,
        External = 2,
        IPhoneContinuity = 3
    }

    /// <summary>
    /// Persists the camera category chosen on the demo hub and resolves it
    /// against the devices Unity can actually see when a feature scene starts.
    /// iPhone means macOS Continuity Camera; it does not claim ARKit capture.
    /// </summary>
    public static class Manual2ARCameraSelection
    {
        const string PreferenceKey = "Manual2AR.CameraMode";

        public static Manual2ARCameraMode mode
        {
            get
            {
                var stored = PlayerPrefs.GetInt(PreferenceKey, (int)Manual2ARCameraMode.Auto);
                return Enum.IsDefined(typeof(Manual2ARCameraMode), stored)
                    ? (Manual2ARCameraMode)stored
                    : Manual2ARCameraMode.Auto;
            }
        }

        public static void SetMode(Manual2ARCameraMode value)
        {
            PlayerPrefs.SetInt(PreferenceKey, (int)value);
            PlayerPrefs.Save();
        }

        public static bool TryResolve(
            WebCamDevice[] devices,
            out int index,
            out string message)
        {
            index = -1;
            if (devices == null || devices.Length == 0)
            {
                message = "NO CAMERA DEVICE DETECTED";
                return false;
            }

            switch (mode)
            {
                case Manual2ARCameraMode.MacBuiltIn:
                    index = Find(devices, IsBuiltIn);
                    break;
                case Manual2ARCameraMode.External:
                    index = Find(devices, IsExternal);
                    break;
                case Manual2ARCameraMode.IPhoneContinuity:
                    index = Find(devices, IsIPhone);
                    break;
                default:
                    // Prefer a dedicated external camera, then Continuity
                    // Camera, and use the Mac camera as the safe fallback.
                    index = Find(devices, IsExternal);
                    if (index < 0) index = Find(devices, IsIPhone);
                    if (index < 0) index = Find(devices, IsBuiltIn);
                    if (index < 0) index = 0;
                    break;
            }

            if (index < 0)
            {
                message = $"{ModeLabel(mode)} NOT DETECTED · RETURN TO DEMO HUB";
                return false;
            }
            message = $"{ModeLabel(mode)} · {devices[index].name}";
            return true;
        }

        public static bool IsAvailable(Manual2ARCameraMode requestedMode, WebCamDevice[] devices)
        {
            if (requestedMode == Manual2ARCameraMode.Auto)
                return devices != null && devices.Length > 0;
            if (devices == null)
                return false;
            switch (requestedMode)
            {
                case Manual2ARCameraMode.MacBuiltIn: return Find(devices, IsBuiltIn) >= 0;
                case Manual2ARCameraMode.External: return Find(devices, IsExternal) >= 0;
                case Manual2ARCameraMode.IPhoneContinuity: return Find(devices, IsIPhone) >= 0;
                default: return false;
            }
        }

        public static string ModeLabel(Manual2ARCameraMode value)
        {
            switch (value)
            {
                case Manual2ARCameraMode.MacBuiltIn: return "MAC BUILT-IN";
                case Manual2ARCameraMode.External: return "EXTERNAL CAMERA";
                case Manual2ARCameraMode.IPhoneContinuity: return "IPHONE CONTINUITY";
                default: return "AUTO";
            }
        }

        public static string DeviceSummary(WebCamDevice[] devices)
        {
            if (devices == null || devices.Length == 0)
                return "NO CAMERA DEVICES DETECTED";
            var builder = new StringBuilder();
            for (var index = 0; index < devices.Length; index++)
            {
                if (index > 0) builder.Append("  ·  ");
                builder.Append(devices[index].name);
            }
            return builder.ToString();
        }

        static int Find(WebCamDevice[] devices, Func<string, bool> predicate)
        {
            for (var index = 0; index < devices.Length; index++)
                if (predicate(devices[index].name))
                    return index;
            return -1;
        }

        static bool IsBuiltIn(string deviceName)
        {
            var name = deviceName.ToLowerInvariant();
            return name.Contains("facetime") || name.Contains("built-in") ||
                name.Contains("macbook") || name.Contains("integrated") ||
                name.Contains("内置");
        }

        static bool IsIPhone(string deviceName)
        {
            var name = deviceName.ToLowerInvariant();
            return name.Contains("iphone") || name.Contains("continuity");
        }

        static bool IsExternal(string deviceName)
        {
            return !IsBuiltIn(deviceName) && !IsIPhone(deviceName);
        }
    }
}
