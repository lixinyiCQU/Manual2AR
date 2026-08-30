from __future__ import annotations

import base64
import io
import os
import threading
from contextlib import nullcontext

import cv2
import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Response
from PIL import Image
from pydantic import BaseModel, Field
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from app.models import (
    ComponentBox,
    TrackedComponent,
    TrackingFrameRequest,
    TrackingSessionRequest,
    TrackingSessionResponse,
)
from app.tracking import OpenCvMaskTracker, decode_base64_image
from sam2.sam2_image_predictor import SAM2ImagePredictor


class GroundingRequest(BaseModel):
    image_base64: str
    component_ids: list[str] = Field(min_length=1)
    box_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    text_threshold: float = Field(default=0.30, ge=0.0, le=1.0)


class GroundingResponse(BaseModel):
    boxes: list[ComponentBox]
    provider: str


class Sam2ImageLkTracker(OpenCvMaskTracker):
    """SAM 2.1 box-prompt mask followed by low-latency LK propagation."""

    def __init__(self, predictor: SAM2ImagePredictor, model_id: str) -> None:
        super().__init__()
        self.predictor = predictor
        self.provider_name = f"{model_id}+box-mask+lk"
        self._predictor_lock = threading.Lock()

    def _initial_mask(
        self,
        image: np.ndarray,
        component_id: str,
        box: tuple[int, int, int, int],
    ) -> np.ndarray:
        del component_id
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        prompt = np.asarray(box, dtype=np.float32)
        autocast = (
            torch.autocast(device_type="cuda", dtype=torch.bfloat16)
            if torch.cuda.is_available()
            else nullcontext()
        )
        with self._predictor_lock, torch.inference_mode(), autocast:
            self.predictor.set_image(rgb)
            masks, scores, _ = self.predictor.predict(
                point_coords=None,
                point_labels=None,
                box=prompt,
                multimask_output=True,
            )
        if masks is None or len(masks) == 0:
            raise RuntimeError("SAM2 returned no mask for the supplied box prompt")
        best_index = int(np.argmax(np.asarray(scores).reshape(-1)))
        selected = np.asarray(masks[best_index]).squeeze().astype(bool)
        result = np.where(selected, 255, 0).astype(np.uint8)
        contours, _ = cv2.findContours(
            result,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            raise RuntimeError("SAM2 returned an empty foreground mask")
        largest = max(contours, key=cv2.contourArea)
        result.fill(0)
        cv2.drawContours(result, [largest], -1, 255, thickness=-1)
        return result


class GpuRuntime:
    def __init__(self) -> None:
        if not torch.cuda.is_available():
            raise RuntimeError(
                "CUDA is required for the selected Manual2AR GPU baseline"
            )
        self.device = "cuda"
        self.sam_model_id = os.getenv(
            "MANUAL2AR_SAM2_MODEL",
            "facebook/sam2.1-hiera-tiny",
        )
        self.grounding_model_id = os.getenv(
            "MANUAL2AR_GROUNDING_MODEL",
            "IDEA-Research/grounding-dino-tiny",
        )
        self.sam_predictor = SAM2ImagePredictor.from_pretrained(
            self.sam_model_id,
            device=self.device,
        )
        self.tracker = Sam2ImageLkTracker(
            self.sam_predictor,
            self.sam_model_id,
        )
        self.processor = AutoProcessor.from_pretrained(self.grounding_model_id)
        self.grounder = AutoModelForZeroShotObjectDetection.from_pretrained(
            self.grounding_model_id
        ).to(self.device)
        self.grounder.eval()
        self._grounder_lock = threading.Lock()

    def ground(self, request: GroundingRequest) -> GroundingResponse:
        image_bytes = decode_base64_image(request.image_base64)
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        boxes: list[ComponentBox] = []
        for component_id in request.component_ids:
            query = self._grounding_query(component_id)
            inputs = self.processor(
                images=image,
                text=query,
                return_tensors="pt",
            ).to(self.device)
            with self._grounder_lock, torch.inference_mode():
                outputs = self.grounder(**inputs)
            result = self.processor.post_process_grounded_object_detection(
                outputs,
                inputs.input_ids,
                threshold=request.box_threshold,
                text_threshold=request.text_threshold,
                target_sizes=[image.size[::-1]],
            )[0]
            candidate_boxes = result.get("boxes")
            candidate_scores = result.get("scores")
            if candidate_boxes is None or len(candidate_boxes) == 0:
                continue
            best = int(torch.argmax(candidate_scores).item())
            x1, y1, x2, y2 = candidate_boxes[best].detach().cpu().tolist()
            width, height = image.size
            normalized = [
                round(max(0.0, min(width, x1)) / width * 1000),
                round(max(0.0, min(height, y1)) / height * 1000),
                round(max(0.0, min(width, x2)) / width * 1000),
                round(max(0.0, min(height, y2)) / height * 1000),
            ]
            if normalized[0] >= normalized[2] or normalized[1] >= normalized[3]:
                continue
            boxes.append(
                ComponentBox(
                    component_id=component_id,
                    bbox_0_1000=normalized,
                    observation=(
                        f"{self.grounding_model_id} open-vocabulary grounding"
                    ),
                )
            )
        return GroundingResponse(
            boxes=boxes,
            provider=self.grounding_model_id,
        )

    @staticmethod
    def _grounding_query(component_id: str) -> str:
        value = component_id.split(":", 1)[-1].strip().lower()
        translations = {
            "蓝色笔": "blue pen",
            "笔": "pen",
            "书": "book",
            "书的下半部": "book",
            "书的右半部": "book",
            "打印机": "3d printer",
            "a1 mini整机": "Bambu Lab A1 mini 3d printer",
            "料盘支架底座": "spool holder base plate",
            "z轴立柱右侧安装位": "right side mount on z axis column",
            "料盘支架": "external spool holder arm",
            "料盘支架底座插槽": "spool holder base slot",
            "最短ptfe管": "short translucent PTFE filament tube",
            "工具头进料口": "filament inlet on top of print head",
            "外置料卷": "external filament spool",
            "耗材头": "filament end",
            "ptfe管自由端": "free end of PTFE filament tube",
            "完整外置进料路径": "external spool and PTFE filament path",
        }
        return translations.get(value, value).rstrip(".") + "."


runtime = GpuRuntime()
app = FastAPI(
    title="Manual2AR GroundingDINO + SAM2 GPU Service",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "tracking_provider": runtime.tracker.provider_name,
        "grounding_provider": runtime.grounding_model_id,
        "device": runtime.device,
    }


@app.post("/api/ground", response_model=GroundingResponse)
def ground(request: GroundingRequest) -> GroundingResponse:
    try:
        return runtime.ground(request)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/tracking/sessions",
    response_model=TrackingSessionResponse,
    status_code=201,
)
def create_tracking_session(
    request: TrackingSessionRequest,
) -> TrackingSessionResponse:
    try:
        session_id, tracked = runtime.tracker.start(
            decode_base64_image(request.image_base64),
            request.component_id,
            request.bbox_0_1000,
        )
        return TrackingSessionResponse(session_id=session_id, tracked=tracked)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/tracking/sessions/{session_id}/frames",
    response_model=TrackedComponent,
)
def update_tracking_session(
    session_id: str,
    request: TrackingFrameRequest,
) -> TrackedComponent:
    try:
        return runtime.tracker.update(
            session_id,
            decode_base64_image(request.image_base64),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tracking session not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete(
    "/api/tracking/sessions/{session_id}",
    status_code=204,
    response_class=Response,
)
def delete_tracking_session(session_id: str) -> Response:
    if not runtime.tracker.close(session_id):
        raise HTTPException(status_code=404, detail="Tracking session not found")
    return Response(status_code=204)
