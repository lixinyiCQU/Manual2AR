"""Module-one CPU tracking. Initial semantics stay immutable; motion is audited.

One decoded frame and batched forward/backward LK per reference-frame group.
Uncertain objects are hidden while their last accepted state is retained briefly.
This is image-space propagation, not semantic re-detection or video SAM.
"""
from dataclasses import dataclass, field
from time import monotonic, perf_counter
import base64
import math
import cv2
import numpy as np
from manual2ar_contracts.perception import TrackedComponent
from manual2ar_perception.segmentation import ComponentMaskTracker
from .cpu_settings import validate


class CpuTracked(TrackedComponent):
    tracking_state: str = 'tracking'
    retained_for_recovery: bool = False
    mask_roi_xywh: list[int] = []
    mask_frame_width: int = 0
    mask_frame_height: int = 0
    motion_diagnostics: dict = {}


@dataclass
class MotionState:
    initial_box: tuple
    current_box: np.ndarray
    initial_point: list | None
    last_accepted: float
    initial_mask: np.ndarray | None = None
    transform: np.ndarray = field(default_factory=lambda:np.eye(3,dtype=np.float64))
    reference_group: int = 0
    failed_since: float | None = None
    failed_frames: int = 0
    recovered: int = 0
    diagnostics: dict = field(default_factory=dict)


class CpuLearningTracker(ComponentMaskTracker):
    provider_name = 'module-one-cpu-lk-fb-v2'

    def __init__(self, settings=None):
        super().__init__()
        self.settings = validate(settings or {})
        self.motion = {}
        self.external_masks = None
        self.sequence = 0
        self.last_batch_metrics = {}

    def _initial_mask(self, image, component_id, box, guidance_target=None):
        if self.external_masks is None:
            return super()._initial_mask(image, component_id, box, guidance_target)
        from manual2ar_perception.segmentation import mask_context
        mask = self.external_masks.get(component_id.removeprefix('intro_'))
        if isinstance(mask, Exception):
            raise ValueError('Remote initial mask failed')
        if mask is None or mask.shape != image.shape[:2]:
            raise ValueError('Missing or mismatched remote initial mask')
        folder = mask_context.get()
        if folder is not None:
            cv2.imwrite(str(folder / (component_id + '_initial_raw.png')), mask)
        return mask.copy()

    def _points(self, gray, mask):
        # Interior corners are less likely to jump to the surrounding background.
        interior = cv2.erode(mask, np.ones((3, 3), np.uint8))
        if cv2.countNonZero(interior) < 12:
            interior = mask
        points=cv2.goodFeaturesToTrack(gray, maxCorners=self.settings['max_corners'],
            qualityLevel=0.01, minDistance=5, mask=interior, blockSize=5)
        if points is not None and len(points)>=self.settings['minimum_points']:
            return points
        # Thin rails/screens can have most real corners on their silhouette.
        # Use actual foreground corners before declaring them untrackable;
        # never replace missing texture with arbitrary foreground grid points.
        return cv2.goodFeaturesToTrack(gray,maxCorners=self.settings['max_corners'],
            qualityLevel=0.003,minDistance=2,mask=mask,blockSize=3)

    def start(self, image_bytes, component_id, bbox_0_1000, guidance_target=None):
        # Keep the existing initial segmentation/semantic quality gates intact.
        session, tracked = super().start(image_bytes, component_id, bbox_0_1000, guidance_target)
        state = self._states[session]
        state.points = self._points(state.gray, state.mask)
        x1, y1, x2, y2 = state.prompt_box
        corners = np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], np.float32)
        self.motion[session] = MotionState(tuple(state.prompt_box), corners,
            list(guidance_target.target_point_0_1000) if guidance_target and guidance_target.target_point_0_1000 else None,
            monotonic(),initial_mask=state.mask.copy())
        return session, tracked

    def close(self, session):
        with self._lock:
            self.motion.pop(session, None)
            return self._states.pop(session, None) is not None

    def update(self, session, image_bytes):
        return self.update_many([session], image_bytes)[session]

    def _flows(self, sessions, gray):
        """Batch objects that share the same last-accepted frame."""
        groups = {}
        for session in sessions:
            state, motion = self._states[session], self.motion[session]
            if state.points is not None and len(state.points) >= self.settings['minimum_points']:
                groups.setdefault(motion.reference_group, []).append(session)
        output = {}
        for members in groups.values():
            reference = self._states[members[0]].gray
            points = np.concatenate([self._states[s].points for s in members]).astype(np.float32)
            params = dict(winSize=(25,25), maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.01))
            nxt, forward, error = cv2.calcOpticalFlowPyrLK(reference, gray, points, None, **params)
            if nxt is None:
                continue
            back, backward, _ = cv2.calcOpticalFlowPyrLK(gray, reference, nxt, None, **params)
            if back is None:
                continue
            fb = np.linalg.norm(back.reshape(-1,2) - points.reshape(-1,2), axis=1)
            valid = forward.reshape(-1).astype(bool) & backward.reshape(-1).astype(bool)
            valid &= np.isfinite(fb) & (fb <= self.settings['forward_backward_error'])
            if error is not None:
                valid &= np.isfinite(error.reshape(-1)) & (error.reshape(-1) < 35)
            q = nxt.reshape(-1,2)
            valid &= np.isfinite(q).all(axis=1)
            valid &= (q[:,0]>=0) & (q[:,0]<gray.shape[1]) & (q[:,1]>=0) & (q[:,1]<gray.shape[0])
            offset = 0
            for session in members:
                count = len(self._states[session].points)
                sl = slice(offset, offset + count)
                output[session] = (points.reshape(-1,2)[sl], q[sl], valid[sl], fb[sl])
                offset += count
        return output

    @staticmethod
    def _appearance(previous, current, mask, matrix):
        kernel=np.ones((3,3),np.uint8)
        supports=(('interior',cv2.erode(mask,kernel)),('foreground',mask),
                  ('silhouette_1px',cv2.dilate(mask,kernel)))
        for name,support in supports:
            ys,xs=np.nonzero(support)
            if len(xs)<12:
                continue
            take=np.linspace(0,len(xs)-1,min(1200,len(xs))).astype(int)
            xy=np.stack([xs[take],ys[take]],axis=1).astype(np.float32)
            transformed=cv2.transform(xy[None],matrix)[0]
            x,y=np.rint(transformed[:,0]).astype(int),np.rint(transformed[:,1]).astype(int)
            valid=(x>=0)&(x<current.shape[1])&(y>=0)&(y<current.shape[0])
            if valid.sum()<12:
                continue
            a=previous[xy[valid,1].astype(int),xy[valid,0].astype(int)].astype(float)
            b=current[y[valid],x[valid]].astype(float)
            if a.std()<5 or b.std()<5:
                continue
            # Expand support only for insufficient variance, never to override a
            # contradictory textured interior. FB/RANSAC must also pass.
            return float(np.corrcoef(a,b)[0,1]),name
        return None,'insufficient_variance'

    def _estimate(self, state, gray, flow):
        info = dict(points_total=0 if state.points is None else len(state.points))
        if flow is None:
            return None, ['insufficient_trackable_points'], info
        previous, current, valid, fb = flow
        info.update(points_valid=int(valid.sum()), valid_ratio=round(float(valid.mean()),4),
            fb_median_px=round(float(np.median(fb[valid])),3) if valid.any() else None)
        if valid.sum() < self.settings['minimum_points'] or valid.mean() < 0.35:
            return None, ['forward_backward_points_rejected'], info
        a, b = previous[valid], current[valid]
        matrix, inliers = cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,
            ransacReprojThreshold=2.5, maxIters=500, confidence=0.99)
        if matrix is None or inliers is None or not np.isfinite(matrix).all():
            return None, ['motion_transform_invalid'], info
        keep = inliers.reshape(-1).astype(bool)
        ratio = float(keep.mean())
        projected = cv2.transform(a[None], matrix)[0]
        residual = float(np.sqrt(np.mean(np.sum((projected[keep]-b[keep])**2, axis=1)))) if keep.any() else math.inf
        scale = float(np.hypot(matrix[0,0],matrix[1,0]))
        appearance,appearance_support = self._appearance(state.gray, gray, state.mask, matrix)
        center = np.mean(a,axis=0)
        moved = cv2.transform(center[None,None].astype(np.float32),matrix)[0,0]
        displacement = float(np.linalg.norm(moved-center)/np.hypot(*gray.shape))
        info.update(inlier_ratio=round(ratio,4), residual_px=round(residual,3),
            scale=round(scale,4), displacement_ratio=round(displacement,4),
            appearance_correlation=round(appearance,4) if appearance is not None and math.isfinite(appearance) else None,
            appearance_support=appearance_support)
        reasons = []
        if keep.sum() < self.settings['minimum_points'] or ratio < self.settings['minimum_inlier_ratio']:
            reasons.append('ransac_inliers_rejected')
        if residual > self.settings['maximum_residual']:
            reasons.append('motion_residual_rejected')
        if not self.settings['minimum_scale'] <= scale <= self.settings['maximum_scale']:
            reasons.append('motion_scale_rejected')
        if displacement > self.settings['maximum_motion_ratio']:
            reasons.append('motion_jump_rejected')
        if appearance is None or not math.isfinite(appearance) or appearance < self.settings['minimum_appearance_correlation']:
            reasons.append('appearance_not_supported')
        return matrix, reasons, info

    def _describe_current(self, state, motion, quality, tracking_state, reasons, roi=True):
        h, w = state.mask.shape
        valid = tracking_state == 'tracking'
        points = cv2.findNonZero(state.mask)
        box = cv2.boundingRect(points) if points is not None else (0,0,1,1)
        x,y,bw,bh = box
        center = self._mask_centroid(state.mask) or (x+bw/2,y+bh/2)
        encoded = ''
        if valid:
            overlay = np.zeros((bh if roi else h,bw if roi else w,4),np.uint8)
            visible = state.mask[y:y+bh,x:x+bw] if roi else state.mask
            overlay[visible>0] = [233,215,22,130]
            ok, png = cv2.imencode('.png', overlay, [cv2.IMWRITE_PNG_COMPRESSION,self.settings['png_compression']])
            if ok:
                encoded = base64.b64encode(png).decode('ascii')
        footprint=np.zeros_like(state.mask)
        cv2.fillConvexPoly(footprint,np.rint(motion.current_box).astype(np.int32),255)
        containment=cv2.countNonZero(cv2.bitwise_and(footprint,state.mask))/max(1,cv2.countNonZero(state.mask))
        return CpuTracked(component_id=state.component_id,status='tracking' if valid else 'lost',
            tracking_state=tracking_state,retained_for_recovery=tracking_state=='recovering',
            quality=quality if valid else 0,requires_redetection=not valid,
            mask_quality_passed=valid,mask_quality_reasons=reasons,
            mask_area_ratio=cv2.countNonZero(state.mask)/(w*h),prompt_containment=containment,
            bbox_0_1000=[round(x/w*1000),round(y/h*1000),round((x+bw)/w*1000),round((y+bh)/h*1000)],
            centroid_0_1000=[round(center[0]/w*1000),round(center[1]/h*1000)],
            overlay_png_base64=encoded,provider=self.provider_name,frame_index=state.frame_index,
            relocalization_count=motion.recovered,world_anchor_status='client_pending',
            mask_roi_xywh=list(box) if roi and valid else [],mask_frame_width=w,mask_frame_height=h,
            motion_diagnostics={**motion.diagnostics,'initial_box_pixels':list(motion.initial_box),
                'initial_target_point_0_1000':motion.initial_point,
                'current_motion_box_pixels':np.rint(motion.current_box).astype(int).tolist(),
                'containment_semantics':'not a semantic confidence; motion/appearance gate used'},
            overlay_semantic='next_action' if valid else 'insufficient')

    def update_many(self, sessions, image_bytes, now=None):
        started = perf_counter()
        image = self._decode(image_bytes)
        gray = cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        decode_ms = (perf_counter()-started)*1000
        now = monotonic() if now is None else now
        with self._lock:
            sessions = list(sessions)
            for session in sessions:
                if session not in self._states:
                    raise KeyError(session)
            matching = [s for s in sessions if self._states[s].gray.shape == gray.shape]
            flow_started = perf_counter()
            flows = self._flows(matching,gray)
            flow_groups=len({self.motion[s].reference_group for s in matching})
            flow_ms = (perf_counter()-flow_started)*1000
            self.sequence += 1
            output = {}
            for session in sessions:
                state, motion = self._states[session], self.motion[session]
                state.frame_index += 1
                if state.gray.shape != gray.shape:
                    matrix, reasons, info = None,['frame_dimensions_changed'],{}
                else:
                    matrix, reasons, info = self._estimate(state,gray,flows.get(session))
                if not reasons:
                    h,w = gray.shape
                    transform=np.vstack([matrix,[0,0,1]]) @ motion.transform
                    # Re-rasterize the original silhouette once per frame instead
                    # of repeatedly warping an already rounded/eroded bitmap.
                    mask = cv2.warpAffine(motion.initial_mask,transform[:2],(w,h),flags=cv2.INTER_NEAREST)
                    ratio = cv2.countNonZero(mask)/(h*w)
                    contract = state.guidance_target
                    if not ratio or (contract and not contract.expected_area_ratio_min <= ratio <= contract.expected_area_ratio_max):
                        reasons.append('current_mask_area_rejected')
                elapsed = 0 if motion.failed_since is None else now-motion.failed_since
                # A retained state cannot recover after its deadline, even on a good frame.
                expired = motion.failed_since is not None and (elapsed >= self.settings['recovery_seconds'] or motion.failed_frames >= self.settings['recovery_max_frames'])
                if expired:
                    reasons.append('recovery_deadline_exceeded')
                motion.diagnostics = {**info,'last_accepted_age_ms':round((now-motion.last_accepted)*1000,1)}
                if reasons:
                    if motion.failed_since is None:
                        motion.failed_since = now
                    motion.failed_frames += 1
                    terminal = expired or 'frame_dimensions_changed' in reasons
                    output[session] = self._describe_current(state,motion,0,'lost' if terminal else 'recovering',reasons)
                    continue
                if motion.failed_since is not None:
                    motion.recovered += 1
                motion.failed_since, motion.failed_frames = None, 0
                motion.transform=transform
                x1,y1,x2,y2=motion.initial_box
                motion.current_box=cv2.transform(np.array([[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]],np.float32),transform[:2])[0]
                motion.last_accepted = now
                motion.reference_group = self.sequence
                state.gray, state.mask = gray, mask
                state.points = self._points(gray,mask)
                quality = min(info['inlier_ratio'], max(0,info['appearance_correlation']))
                output[session] = self._describe_current(state,motion,quality,'tracking',[])
            self.last_batch_metrics = dict(decode_ms=round(decode_ms,2),flow_ms=round(flow_ms,2),
                total_ms=round((perf_counter()-started)*1000,2),objects=len(sessions),
                flow_groups=flow_groups,
                decoded_frames=1,provider=self.provider_name)
            return output
