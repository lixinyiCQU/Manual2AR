"""Readable diagnostic evidence and optional human labels; never changes task progress."""
import html
import json
from pathlib import Path
import shutil
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import Field

from .gt import Digest, Identity, Strict, digest, encoded


class Labels(Strict):
    schema_version: Literal["baseline-photo-labels-v1"]
    source_sha256: Digest
    task_sha256: Digest
    protocol_sha256: Digest
    reviewer: str = ""
    independent_review: bool | None = None
    labels: dict[Identity, Literal["true", "false", "unknown", "unrated"]] = Field(min_length=1)


def render(folder: Path):
    request = json.loads((folder / "request.json").read_bytes())
    evaluated = json.loads((folder / "evaluated.json").read_bytes())
    plan = json.loads((folder / "plan.json").read_bytes())
    labels = Labels(schema_version="baseline-photo-labels-v1", source_sha256=request["source_sha256"], task_sha256=request["task_sha256"],
                    protocol_sha256=request["protocol_sha256"], labels={cid: "unrated" for cid in evaluated["readings"]})
    (folder / "labels.template.json").write_bytes(encoded(labels.model_dump()))
    image = Image.open(folder / "scene.jpg").convert("RGB")
    draw = ImageDraw.Draw(image)
    lines = ["# 现场视觉观察审核", "", "这是模型观察和程序判定的审核包，尚无独立人工评分；框是模型候选，不是定位真值。", "",
             "当前下一步：" + plan["reason"], "", "![模型候选证据框](evidence-overlay.jpg)", "",
             "原始提交图：[scene.jpg](scene.jpg)。如需人工评分，请复制 `labels.template.json` 为新文件，填写标注者与各项 true/false/unknown；未审核项保持 unrated。", "",
             "| 编号 | 检查条件 | 程序判定 | 模型说明 |", "| --- | --- | --- | --- |"]
    for i, row in enumerate(evaluated["details"], 1):
        finding = row["finding"]
        boxes = finding["evidence_boxes"] + [x["box"] for x in finding["instances"]]
        if not boxes and finding["region"]:
            boxes = [finding["region"]]
        color = {"true": (25, 180, 70), "false": (230, 45, 45), "unknown": (225, 150, 20)}[row["value"]]
        for box in boxes:
            a, b, c, d = box["xyxy"]
            rect = [round(a * image.width / 1000), round(b * image.height / 1000), round(c * image.width / 1000), round(d * image.height / 1000)]
            draw.rectangle(rect, outline=color, width=2)
            draw.text((rect[0], max(0, rect[1] - 11)), str(i) + ":" + row["value"], fill=color, stroke_width=1, stroke_fill=(0, 0, 0))
        text = html.escape(row["evidence"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {row['condition_id']} | {row['value']} / {row['reason']} | {text} |")
    image.save(folder / "evidence-overlay.jpg", "JPEG", quality=95)
    lines += ["", "方向和紧固仍须按已审核方法人工确认。此包不含相机实测、三维定位或 AR 精度结论。", ""]
    (folder / "REVIEW.md").write_text("\n".join(lines), encoding="utf-8")


def review_saved(run: Path, output: Path):
    from .photos import check_run
    check_run(run)
    if not (run / "evaluated.json").exists():
        raise ValueError("Choose a photo observation run, not a manual confirmation")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("scene.jpg", "request.json", "evaluated.json", "plan.json"):
        shutil.copyfile(run / name, output / name)
    render(output)
    (output / "review-source.json").write_bytes(encoded(dict(schema_version="baseline-photo-review-v1",
        source_run_manifest_sha256=digest((run / "manifest.json").read_bytes()), source_run=str(run.resolve()),
        independent_labels="not_provided", note="derived_review_only_not_a_resumable_session")))


def score(run: Path, labels_path: Path, output: Path):
    from .photos import check_run
    check_run(run)
    request = json.loads((run / "request.json").read_bytes())
    evaluated = json.loads((run / "evaluated.json").read_bytes())["readings"]
    labels = Labels.model_validate_json(labels_path.read_bytes())
    if (labels.source_sha256, labels.task_sha256, labels.protocol_sha256) != (request["source_sha256"], request["task_sha256"], request["protocol_sha256"]):
        raise ValueError("Labels belong to another image, task or observation protocol")
    if labels.labels.keys() != evaluated.keys():
        raise ValueError("Label conditions must cover exactly this run's visual conditions")
    rated = {cid: value for cid, value in labels.labels.items() if value != "unrated"}
    if rated and not labels.reviewer.strip():
        raise ValueError("Rated labels require a declared reviewer")
    counts = dict(agreement=0, false_accept=0, unsupported_accept=0, false_reject=0, unsupported_reject=0, abstention=0)
    details = []
    for cid, actual in rated.items():
        predicted = evaluated[cid]["value"]
        category = ("agreement" if actual == predicted else "abstention" if predicted == "unknown" else
                    "false_accept" if predicted == "true" and actual == "false" else "unsupported_accept" if predicted == "true" else
                    "false_reject" if actual == "true" else "unsupported_reject")
        counts[category] += 1
        details.append(dict(condition_id=cid, prediction=predicted, label=actual, category=category))
    result = dict(schema_version="baseline-photo-score-v1", source_sha256=labels.source_sha256, labels_sha256=digest(labels_path.read_bytes()),
                  reviewer=labels.reviewer, independent_review=labels.independent_review, rated=len(rated), unrated=len(evaluated) - len(rated),
                  label_agreement=counts["agreement"] / len(rated) if rated else None, counts=counts, details=details,
                  scope="this_photo_and_declared_labels_only_not_general_accuracy")
    output.mkdir(parents=True, exist_ok=False)
    (output / "score.json").write_bytes(encoded(result))
    (output / "labels.json").write_bytes(labels_path.read_bytes())
    return result
