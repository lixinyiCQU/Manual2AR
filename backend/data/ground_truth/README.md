# Human ground truth for baseline evaluation

Do not label from the model's evidence text. Watch the original consented screen
recording or inspect the physical setup, then add one JSON object per line to
`labels.jsonl`.

For a current-state localization decision:

```json
{"decision_id":"copy from guidance_events","expected_step_id":"S2"}
```

For a step verification decision:

```json
{"decision_id":"copy from guidance_events","expected_status":"wrong_operation","should_advance":false}
```

Allowed verification labels are `not_started`, `in_progress`, `completed`,
`wrong_operation`, and `uncertain`. Set `should_advance=true` only when the
requested action is visibly complete and all safety conditions are satisfied.

The evaluator joins labels to predictions by `decision_id`; never use timestamps
or array position as a substitute. Keep the screen recording and annotation
reviewer id in the experiment log, but do not put personal identifiers here.

