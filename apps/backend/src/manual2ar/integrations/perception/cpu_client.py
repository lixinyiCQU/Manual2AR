"""Local GrabCut/LK adapter for the persistent multi-part mask interface."""
import cv2
import numpy as np
from manual2ar_contracts.perception import GuidanceTarget
from manual2ar_perception.cpu_tracker import CpuLearningTracker


class CpuMaskClient:
    provider_name = 'opencv'

    def __init__(self, settings=None):
        self.tracker = CpuLearningTracker(settings)
        self.sessions = {}
        self.shape = None

    def start(self, image, targets, masks=None):
        decoded = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise ValueError('Invalid CPU segmentation image')
        self.shape = decoded.shape[:2]
        self.tracker.external_masks = None if masks is None else {
            name: mask.astype(np.uint8) * 255 for name, mask in masks.items()}
        try:
            output = {}
            for target in targets:
                name = target['component_id']
                box = target['bbox_0_1000']
                point = target['target_point_0_1000']
                if masks is not None and masks[name].any():
                    # GPU may have moved far from the original VLM proposal.
                    mask = masks[name].astype(np.uint8)
                    h, w = self.shape
                    x, y, bw, bh = cv2.boundingRect(mask)
                    box = [round(x/w*1000), round(y/h*1000), round((x+bw)/w*1000), round((y+bh)/h*1000)]
                    yy, xx = np.nonzero(mask)
                    k = np.argmin((xx-xx.mean())**2 + (yy-yy.mean())**2)
                    point = [round(xx[k]/w*1000), round(yy[k]/h*1000)]
                contract = GuidanceTarget(expected_component_id='intro_' + name,
                    target_point_0_1000=point,
                    expected_area_ratio_min=.00008, expected_area_ratio_max=.45)
                session, value = self.tracker.start(image, 'intro_' + name,
                    box, contract)
                self.sessions[name] = session
                output[name] = self._mask(session, value)
            return output, {'metrics': {'provider': self.provider_name}}
        except Exception:
            self.close()
            raise
        finally:
            self.tracker.external_masks = None

    def _mask(self, session, value):
        # Never expose retained recovery masks as a current successful detection.
        if not value.mask_quality_passed or value.status != 'tracking':
            return np.zeros(self.shape, bool)
        return self.tracker._states[session].mask.astype(bool).copy()

    def step(self, image, frame_id):
        values = self.tracker.update_many(list(self.sessions.values()), image)
        return {name: self._mask(session, values[session]) for name, session in self.sessions.items()}, {
            'metrics': {'provider': self.provider_name, **self.tracker.last_batch_metrics}}

    def close(self):
        for session in self.sessions.values():
            self.tracker.close(session)
        self.sessions.clear()
