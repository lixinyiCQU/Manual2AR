# Frozen MLLM Baseline Prompt v1

## Purpose

Test whether an untrained MLLM can align one observation with the proxy manual,
verify the state, and ground the relevant components. This is the baseline
before LoRA fine-tuning.

## System prompt

You are a conservative manual-grounded equipment state verifier. Use only the
provided manual and image evidence. Do not infer a hidden state from hand
motion or from what normally happens. If a required component or prerequisite
cannot be verified, return `uncertain` and set `safe_to_advance` to false.
Return only valid JSON matching the requested fields.

## User prompt

The attached PDF is the complete equipment manual. The attached camera image
shows the equipment at one moment during the procedure.

Determine:

1. whether the scene matches this equipment;
2. the most likely current procedure state;
3. whether the active step is not started, in progress, completed, a wrong
   operation, or uncertain;
4. the visible evidence supporting the decision;
5. the relevant manual page and section;
6. the target component bounding boxes using normalized coordinates from 0 to
   1000 in `[x_min, y_min, x_max, y_max]` format;
7. whether automatic advancement is safe;
8. the next instruction or recovery action.

Required output:

```json
{
  "device_match": true,
  "current_state_id": "S0",
  "active_step_id": "S1",
  "status": "not_started",
  "evidence": [
    {
      "component_id": "access_cover",
      "observation": "The cover is closed.",
      "bbox_0_1000": [0, 0, 0, 0]
    }
  ],
  "manual_page": 2,
  "manual_section": "Step 1",
  "safe_to_advance": false,
  "next_action": "Open the access cover.",
  "confidence": 0.0
}
```

## What to record

For each test image, save:

- expected state and status;
- raw model JSON;
- whether the step was correct;
- whether `safe_to_advance` was safe;
- whether each box touched the correct component;
- one short failure reason.

The first result is a failure table, not a training dataset and not a paper
claim.
