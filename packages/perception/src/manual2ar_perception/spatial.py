"""Metric RGB geometry. No task knowledge, storage, network or model dependencies.

Coordinates: OpenCV camera (right, down, forward), metres; marker origin at
centre, +X right, +Y towards its printed top, +Z out of the paper.
T_camera_from_marker maps marker column vectors into camera coordinates.
"""
import cv2
import numpy as np


def marker_corners(length):
    h = length / 2
    return np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]], np.float64)


def detect_pose(image, matrix, distortion, length=.08, marker_id=23):
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    parameters=cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod=cv2.aruco.CORNER_REFINE_SUBPIX
    parameters.cornerRefinementWinSize=5
    corners, ids, _ = cv2.aruco.ArucoDetector(dictionary,parameters).detectMarkers(image)
    if ids is None or list(ids.flatten()).count(marker_id) != 1:
        return None, 'marker_missing'
    pixels = corners[list(ids.flatten()).index(marker_id)].reshape(4, 2).astype(np.float64)
    if min(np.linalg.norm(pixels - np.roll(pixels, 1, axis=0), axis=1)) < 45:
        return None, 'marker_too_small'
    objects = marker_corners(length)
    ok, rv, tv, _ = cv2.solvePnPGeneric(objects, pixels, matrix, distortion, flags=cv2.SOLVEPNP_IPPE_SQUARE)
    if not ok:
        return None, 'pose_failed'
    candidates = []
    for r, t in zip(rv, tv):
        rotation = cv2.Rodrigues(r)[0]
        depths = (objects @ rotation.T + t.reshape(3))[:, 2]
        if min(depths) <= .03 or not .08 < float(np.linalg.norm(t)) < 2.0:
            continue
        # The printed face must face the camera, not its reflected backside.
        if np.dot(rotation[:, 2], t.reshape(3)) >= 0:
            continue
        projected = cv2.projectPoints(objects, r, t, matrix, distortion)[0].reshape(4, 2)
        rms = float(np.sqrt(np.mean(np.sum((pixels - projected) ** 2, axis=1))))
        transform = np.eye(4)
        transform[:3, :3], transform[:3, 3] = rotation, t.reshape(3)
        candidates.append((rms, transform))
    if not candidates or min(x[0] for x in candidates) > 2.5:
        return None, 'pose_reprojection'
    error, transform = min(candidates, key=lambda x: x[0])
    return {'transform': transform, 'corners': pixels, 'reprojection_px': error}, 'tracking'


def project(points, transform, matrix, distortion):
    points = np.asarray(points, np.float64).reshape(-1, 3)
    camera = points @ transform[:3, :3].T + transform[:3, 3]
    if np.any(camera[:, 2] <= .03):
        raise ValueError('Guide is behind the camera')
    return cv2.projectPoints(points, cv2.Rodrigues(transform[:3, :3])[0],
                             transform[:3, 3], matrix, distortion)[0].reshape(-1, 2)


def ray(pixel, transform, matrix, distortion):
    xy = cv2.undistortPoints(np.asarray(pixel, np.float64).reshape(1, 1, 2), matrix, distortion).reshape(2)
    origin = -transform[:3, :3].T @ transform[:3, 3]
    direction = transform[:3, :3].T @ np.r_[xy, 1.]
    return origin, direction / np.linalg.norm(direction)


def triangulate(first_pixels, first_pose, second_pixels, second_pose, matrix, distortion):
    """Two explicitly authored endpoints; reject weak baseline and inconsistent clicks."""
    result, errors, angles = [], [], []
    for p, q in zip(first_pixels, second_pixels):
        a, u = ray(p, first_pose, matrix, distortion)
        b, v = ray(q, second_pose, matrix, distortion)
        angle = float(np.degrees(np.arccos(np.clip(np.dot(u, v), -1, 1))))
        if angle < 5 or angle > 100:
            raise ValueError('两次视角差太小；保持标记不动，将摄像头横移约 15–25 厘米后重新取景。')
        distances = np.linalg.lstsq(np.stack([u, -v], axis=1), b - a, rcond=None)[0]
        if min(distances) <= .03:
            raise ValueError('目标在相机后方，请重新选点。')
        point = (a + distances[0] * u + b + distances[1] * v) / 2
        if np.linalg.norm(point) > 1:
            raise ValueError('目标距离标记超过一米，请将标记靠近操作区域。')
        error = max(float(np.linalg.norm(project([point], pose, matrix, distortion)[0] - pixel))
                    for pose, pixel in [(first_pose, p), (second_pose, q)])
        if error > 3:
            raise ValueError('两次选点不能对应同一位置，请重新选择同一对起点和终点。')
        result.append(point.tolist()); errors.append(error); angles.append(angle)
    length = float(np.linalg.norm(np.asarray(result[1]) - result[0]))
    if not .008 <= length <= .4:
        raise ValueError('方向线应长于 8 毫米且短于 40 厘米。')
    return result, {'maximum_reprojection_px': max(errors), 'minimum_ray_angle_deg': min(angles)}


def guide_lines(points, kind):
    """Authored metric segment plus 3D arrow / tool axis and tightening ring."""
    start, end = np.asarray(points, np.float64)
    if kind in ('align','highlight','cut'):return [[start.tolist(),end.tolist()]]
    direction = end - start; length = np.linalg.norm(direction); direction /= length
    other = np.array([0., 0., 1.]) if abs(direction[2]) < .9 else np.array([1., 0., 0.])
    side = np.cross(direction, other); side /= np.linalg.norm(side)
    up = np.cross(direction, side)
    head = min(.018, length * .3)
    lines = [[start, end], [end, end - direction * head + side * head * .55],
             [end, end - direction * head - side * head * .55]]
    if kind == 'fasten':
        # Axis is authored from tool handle towards screw; no invented torque/angle.
        radius = .012
        ring = [end + radius * (side * np.cos(a) + up * np.sin(a))
                for a in np.linspace(0, 2 * np.pi, 25)]
        lines.extend([[a, b] for a, b in zip(ring, ring[1:])])
    return np.asarray(lines).tolist()


def visual_geometry(points,kind,transform,matrix,distortion):
    """Project a metric path and procedural hex-tool reference in the same RGB domain.

    Sample the 3D segment before projection: screen-linear interpolation alone
    would produce the wrong speed/position on paths with a depth change.
    """
    start,end=np.asarray(points,np.float64)
    result={'kind':kind,'anchor':None,'trajectory':[],'tool_lines':[]}
    pixel=lambda p:{'x':float(p[0]),'y':float(p[1])}
    result['anchor']=pixel(project([end],transform,matrix,distortion)[0])
    if kind=='slide':
        samples=[start+(end-start)*t for t in np.linspace(0,1,33)]
        result['trajectory']=[pixel(p) for p in project(samples,transform,matrix,distortion)]
    elif kind=='fasten':
        axis=(end-start)/np.linalg.norm(end-start)
        basis=np.array([0.,0.,1.]) if abs(axis[2])<.9 else np.array([1.,0.,0.])
        side=np.cross(axis,basis);side/=np.linalg.norm(side)
        # An L-shaped reference, not a calibrated tool model or a torque claim.
        handle=start+side*min(.025,np.linalg.norm(end-start)*.7)
        projected=project([handle,start,end],transform,matrix,distortion)
        result['tool_lines']=[{'a':pixel(a),'b':pixel(b)} for a,b in zip(projected,projected[1:])]
    elif kind=='cut':
        axis=(end-start)/np.linalg.norm(end-start)
        basis=np.array([0.,0.,1.]) if abs(axis[2])<.9 else np.array([1.,0.,0.])
        side=np.cross(axis,basis);side/=np.linalg.norm(side)
        length=min(.025,np.linalg.norm(end-start)*.5)
        # Two open reference blades. No cutting motion, force or inferred wire identity.
        lines=np.array([[end-axis*length+side*length*.4,end],
                        [end-axis*length-side*length*.4,end]])
        projected=project(lines.reshape(-1,3),transform,matrix,distortion).reshape(-1,2,2)
        result['tool_lines']=[{'a':pixel(a),'b':pixel(b)} for a,b in projected]
    return result
