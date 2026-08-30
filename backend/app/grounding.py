from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .models import ComponentBox


@dataclass(frozen=True)
class PixelBox:
    x1: int
    y1: int
    x2: int
    y2: int


class DemoGrounder:
    """Replaceable 2D grounding baseline for the book-and-blue-pen demo.

    It intentionally lives behind one interface so SAM/GroundingDINO can replace
    it later without changing the API or Unity rendering code.
    """

    def ground(
        self,
        image_bytes: bytes,
        target_components: list[str],
        rotation_degrees: int = 0,
    ) -> list[ComponentBox]:
        raw = cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if raw is None:
            return []

        rotation = self._normalize_rotation(rotation_degrees)
        upright = self._rotate_to_upright(raw, rotation)
        height, width = upright.shape[:2]
        pen = self._find_blue_pen(upright)
        # This contour result is only a spatial prompt, never state evidence.
        # GrabCut/SAM-style segmentation refines it before it is shown as a
        # pixel highlight, while the VLM independently decides task state.
        book = self._find_book(upright, pen)

        grounded: list[ComponentBox] = []
        for component in target_components:
            normalized = component.lower().replace(" ", "")
            box: PixelBox | None = None
            method = ""
            if "笔" in normalized or "pen" in normalized:
                box = pen
                method = "颜色分割定位蓝色笔"
            elif "书" in normalized or "book" in normalized:
                box = self._book_region(book, normalized)
                method = "轮廓定位书本区域"
            if box is None:
                continue

            raw_box = self._upright_box_to_raw_normalized(
                box,
                width,
                height,
                rotation,
            )
            grounded.append(
                ComponentBox(
                    component_id=component,
                    bbox_0_1000=raw_box,
                    observation=method,
                )
            )
        return grounded

    @staticmethod
    def _normalize_rotation(value: int) -> int:
        value = int(round(value / 90.0) * 90) % 360
        return value if value in (0, 90, 180, 270) else 0

    @staticmethod
    def _rotate_to_upright(image: np.ndarray, rotation: int) -> np.ndarray:
        if rotation == 90:
            return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        if rotation == 180:
            return cv2.rotate(image, cv2.ROTATE_180)
        if rotation == 270:
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return image

    @staticmethod
    def _find_blue_pen(image: np.ndarray) -> PixelBox | None:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array([35, 40, 35], dtype=np.uint8),
            np.array([85, 255, 255], dtype=np.uint8),
        )
        open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        join_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, join_kernel)
        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        height, width = image.shape[:2]
        candidates: list[tuple[float, PixelBox]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < max(25.0, width * height * 0.00015):
                continue
            x, y, w, h = cv2.boundingRect(contour)
            elongation = max(w, h) / max(1.0, min(w, h))
            if elongation < 1.8:
                continue
            touches_edge = (
                x <= 2 or y <= 2 or x + w >= width - 2 or y + h >= height - 2
            )
            center_distance = abs((x + w / 2) / width - 0.5)
            score = area * min(elongation, 8.0)
            score *= 0.25 if touches_edge else 1.0
            score *= max(0.45, 1.0 - center_distance)
            candidate = PixelBox(x, y, x + w, y + h)
            candidates.append((score, candidate))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        merged = candidates[0][1]
        for _, candidate in candidates[1:]:
            if DemoGrounder._collinear_pen_parts(merged, candidate):
                merged = PixelBox(
                    min(merged.x1, candidate.x1),
                    min(merged.y1, candidate.y1),
                    max(merged.x2, candidate.x2),
                    max(merged.y2, candidate.y2),
                )
        return merged

    @staticmethod
    def _collinear_pen_parts(left: PixelBox, right: PixelBox) -> bool:
        left_width = left.x2 - left.x1
        left_height = left.y2 - left.y1
        right_width = right.x2 - right.x1
        right_height = right.y2 - right.y1
        left_horizontal = left_width >= left_height
        right_horizontal = right_width >= right_height
        if left_horizontal != right_horizontal:
            return False
        if left_horizontal:
            perpendicular_offset = abs(
                (left.y1 + left.y2) / 2 - (right.y1 + right.y2) / 2
            )
            gap = max(0, max(left.x1, right.x1) - min(left.x2, right.x2))
            thickness = max(left_height, right_height)
            length = max(left_width, right_width)
        else:
            perpendicular_offset = abs(
                (left.x1 + left.x2) / 2 - (right.x1 + right.x2) / 2
            )
            gap = max(0, max(left.y1, right.y1) - min(left.y2, right.y2))
            thickness = max(left_width, right_width)
            length = max(left_height, right_height)
        return bool(
            perpendicular_offset <= max(8.0, thickness * 0.85)
            and gap <= max(45.0, length * 0.75)
        )

    @staticmethod
    def _find_book(
        image: np.ndarray,
        pen: PixelBox | None,
    ) -> PixelBox | None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 45, 135)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            edges,
            # Internal rectangular cover/page regions are valuable prompts when
            # the outer book boundary touches a laptop, hand, or table edge.
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        height, width = image.shape[:2]
        image_area = float(width * height)
        best: tuple[float, PixelBox] | None = None
        for contour in contours:
            area = cv2.contourArea(contour)
            ratio = area / image_area
            if ratio < 0.035 or ratio > 0.72:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            rectangularity = area / max(1.0, float(w * h))
            if rectangularity < 0.35:
                continue
            aspect = w / max(1.0, float(h))
            if aspect < 0.45 or aspect > 2.8:
                continue
            touches_edge = (
                x <= width * 0.015
                or y <= height * 0.015
                or x + w >= width * 0.985
                or y + h >= height * 0.985
            )
            center_x = (x + w / 2) / width
            center_y = (y + h / 2) / height
            center_score = 1.0 - min(
                1.0,
                ((center_x - 0.5) ** 2 + (center_y - 0.5) ** 2) ** 0.5,
            )
            contains_pen_bonus = 0.0
            if pen is not None:
                pen_x = (pen.x1 + pen.x2) / 2
                pen_y = (pen.y1 + pen.y2) / 2
                if x <= pen_x <= x + w and y <= pen_y <= y + h:
                    contains_pen_bonus = 0.35
            score = ratio * 3.0 + rectangularity + center_score + contains_pen_bonus
            if touches_edge:
                score -= 1.0
            candidate = PixelBox(x, y, x + w, y + h)
            if best is None or score > best[0]:
                best = (score, candidate)
        return best[1] if best else None

    @staticmethod
    def _book_region(book: PixelBox | None, component: str) -> PixelBox | None:
        if book is None:
            return None
        width = book.x2 - book.x1
        height = book.y2 - book.y1
        if "下半" in component or "lower" in component:
            return PixelBox(book.x1, book.y1 + height // 2, book.x2, book.y2)
        if "右半" in component or "right" in component:
            return PixelBox(book.x1 + width // 2, book.y1, book.x2, book.y2)
        if "左半" in component or "left" in component:
            return PixelBox(book.x1, book.y1, book.x1 + width // 2, book.y2)
        return book

    @staticmethod
    def _upright_box_to_raw_normalized(
        box: PixelBox,
        upright_width: int,
        upright_height: int,
        rotation: int,
    ) -> list[int]:
        points = [
            (box.x1 / upright_width, box.y1 / upright_height),
            (box.x2 / upright_width, box.y1 / upright_height),
            (box.x2 / upright_width, box.y2 / upright_height),
            (box.x1 / upright_width, box.y2 / upright_height),
        ]

        def to_raw(point: tuple[float, float]) -> tuple[float, float]:
            x, y = point
            if rotation == 90:
                return y, 1.0 - x
            if rotation == 180:
                return 1.0 - x, 1.0 - y
            if rotation == 270:
                return 1.0 - y, x
            return x, y

        raw_points = [to_raw(point) for point in points]
        xs = [point[0] for point in raw_points]
        ys = [point[1] for point in raw_points]
        x1 = int(round(max(0.0, min(xs)) * 1000))
        y1 = int(round(max(0.0, min(ys)) * 1000))
        x2 = int(round(min(1.0, max(xs)) * 1000))
        y2 = int(round(min(1.0, max(ys)) * 1000))
        if x2 <= x1:
            x2 = min(1000, x1 + 1)
        if y2 <= y1:
            y2 = min(1000, y1 + 1)
        return [x1, y1, x2, y2]


def rotate_jpeg_for_vlm(image_bytes: bytes, rotation_degrees: int) -> bytes:
    rotation = DemoGrounder._normalize_rotation(rotation_degrees)
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        if rotation:
            image = image.rotate(-rotation, expand=True)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()
