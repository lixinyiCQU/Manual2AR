# Manual2AR Research Blueprint v0.2

Date: 2026-07-30

## 1. One-sentence project definition

Manual2AR fine-tunes a multimodal large language model (MLLM) to perform
bidirectional, evidence-grounded alignment between equipment manuals and live
equipment states, then uses calibrated state verification to control whether
an AR guide advances, corrects the user, or abstains.

AR is the interaction layer. The main research object is the
manual-scene-state model and its evaluation.

## 2. Core research question

How can an MLLM be trained to convert multimodal equipment manuals into
provenance-linked, verifiable state transitions and, in the reverse direction,
map live visual observations back to the correct manual state so that
closed-loop AR guidance can advance safely across devices?

### Operational sub-questions

- RQ1: Can fine-tuning improve scene-to-manual step retrieval and equipment
  state recognition over frozen-MLLM prompting and retrieval baselines?
- RQ2: Does joint forward and reverse training improve completion and
  wrong-operation detection compared with one-direction training?
- RQ3: Can confidence calibration and an explicit `uncertain` outcome reduce
  unsafe automatic advancement without making the system unusably conservative?
- RQ4: How much accuracy and onboarding effort are required to transfer the
  trained model to a held-out device or procedure?

## 3. What "bidirectional" means

### Forward: manual to expected scene

Input:

- manual page, figure, warning, and current step;
- prior verified state;
- device and task identity.

Output:

- structured action;
- preconditions and postconditions;
- target component and visual query;
- expected before/after appearance;
- safety constraints;
- allowed next states and recovery states;
- source page/region for every critical claim.

### Reverse: observed scene to manual state

Input:

- current image or short temporal window;
- candidate manual/state graph;
- optional device display, API, or sensor values.

Output:

- current step and equipment state;
- `not_started`, `in_progress`, `completed`, `wrong_operation`, or `uncertain`;
- visible evidence with component box/mask when applicable;
- supporting manual page/region;
- next step, correction step, or request for another view.

The reverse output updates the manual state machine. It does not rewrite the
manual or invent a new safety procedure.

## 4. What will actually be trained

Do not pre-train a foundation model from scratch. Start from an open MLLM and
fine-tune it with parameter-efficient training such as LoRA/QLoRA.

The first model is a multi-task state aligner with four supervised objectives:

1. **Step retrieval:** retrieve the correct manual step from an observation.
2. **State verification:** classify completion, error, progress, or uncertainty.
3. **Evidence grounding:** identify the relevant component/region.
4. **Forward structuring:** convert a manual step into a constrained state
   transition record with source provenance.

Optional consistency objective:

- the scene retrieved for a step should satisfy that step's visual predicates;
- adjacent-step, wrong-state, wrong-device, and skipped-step pairs are hard
  negatives.

An abstract training loss is:

`L = L_retrieval + L_state + L_grounding + L_structure + L_consistency`

The weights are an experiment, not a fixed design claim.

## 5. Target device and pre-laboratory proxy

The first real equipment target is a Bambu Lab 3D printer. Its exact model,
official manual, and target procedure will be frozen after laboratory access.
No model-specific operating or safety claim should be invented before that.

Before laboratory access, use a book-based proxy device to validate the
software and model contract. The proxy contains:

- a fixed paper tracking marker placed beside, not on, the moving book cover;
- the book cover as an access cover;
- a paper arrow disk as a two-orientation control;
- a yellow card as removable module A;
- a green paper pocket as the target slot.

The proxy procedure is:

1. confirm the initial closed state;
2. open the cover to the marked setup page;
3. rotate the arrow disk to the UP position;
4. remove yellow module A from its holder;
5. insert module A fully into the green target slot;
6. close the cover.

This proxy validates manual parsing, reverse step retrieval, visible state
verification, error detection, uncertainty, and 2D component grounding. It
does not demonstrate real-printer safety, full 3D pose estimation, or
cross-device generalization.

## 6. Minimum data unit

Each annotated sample contains:

- device and task identifiers;
- manual source page and region;
- current and previous step;
- one image or a short before/after sequence;
- state label and error type;
- component box/mask when visible;
- structured preconditions and postconditions;
- confidence eligibility and whether automatic advancement is safe.

Collect five kinds of execution:

1. correct;
2. incomplete;
3. skipped step;
4. wrong component or wrong direction;
5. ambiguous/occluded view.

The ambiguous set is essential because a safety-oriented system needs to learn
when not to claim success.

## 7. Evaluation contract

### Offline model metrics

- step retrieval: Recall@1, Recall@3, MRR;
- state/completion/error recognition: macro-F1 and per-class recall;
- component grounding: pointing accuracy and mask IoU when masks exist;
- unsafe auto-advance rate;
- coverage at a fixed unsafe-advance threshold;
- confidence calibration: ECE or risk-coverage curve;
- cross-device generalization: held-out-device scores;
- adaptation cost: labeled samples and person-minutes needed for a new device.

### System metrics

- task success and task error rate;
- number of unsafe or premature advances;
- completion time;
- number of manual confirmations and repeated camera views;
- NASA-TLX or a similarly validated workload scale;
- trust calibration: whether users rely on the guide when it is right and
  question it when it is uncertain.

### Required baselines

1. static/manual-only guidance;
2. frozen MLLM with prompting;
3. manual retrieval plus frozen MLLM;
4. one-direction fine-tuning;
5. full bidirectional fine-tuning;
6. full model without the uncertainty gate.

## 8. Publication contribution boundary

The contribution is not merely:

- showing manual text in AR;
- adding a "next" button;
- using Vuforia to register an object;
- calling a VLM to describe a camera frame;
- claiming the first state-aware or bidirectional AR system.

The paper becomes defensible if it demonstrates:

- a reproducible manual-scene-state training task and dataset;
- joint forward/reverse training that beats fair baselines;
- evidence and provenance for state decisions;
- calibrated abstention that reduces unsafe progression;
- transfer to a held-out device with measured onboarding cost;
- an AR study showing that the model improvement matters to users.

## 9. Relationship to nearby work

- Guided Reality is a strong reference for generating and rendering visually
  enriched AR guidance, but its core contribution is not our trained
  manual-state verifier.
- JARVIS describes state feedback and adaptive guidance; its current paper also
  states that video/state feedback is user-triggered and that automatic
  real-time state verification remains future work.
- Chain-of-Procedure already studies visual-state-to-instruction retrieval and
  next-step generation. Therefore, reverse retrieval alone is not novel enough.
- IndustReal and CheckManual show that procedure-step recognition, execution
  errors, and manual-based appliance tasks already have established benchmarks.

Our novelty must therefore be evaluated as the combination of manual
provenance, executable visual predicates, bidirectional training, calibrated
automatic verification, AR loop integration, and held-out-device transfer.

## 10. Two-week execution plan

### Week 1: freeze the task and create ground truth

Day 1:

- assemble the book-based proxy from colored paper;
- print or display the proxy manual;
- photograph one clear example of every state;
- photograph all components separately.

Day 2:

- audit `procedure.json`;
- annotate preconditions, postconditions, errors, and manual provenance;
- decide which states are visual and which require a sensor/manual check.

Day 3:

- fix one phone/camera protocol;
- record several correct sequences from multiple viewpoints;
- record incomplete and wrong-order examples.

Day 4:

- annotate step/state labels and target boxes;
- write train, validation, and held-out-view splits by recording session.

Day 5:

- run a frozen-MLLM prompt baseline;
- produce the first confusion matrix and failure table.

### Week 2: first trained model and offline loop

- convert annotations to the chosen model's conversation format;
- fine-tune one small open MLLM with LoRA;
- compare frozen, retrieval, and fine-tuned baselines;
- add the `uncertain` threshold and risk-coverage plot;
- expose a minimal inference API returning the procedure schema;
- only then connect the API to a Unity step player.

### Laboratory migration gate

After gaining access to the printer:

- record the brand, exact model, firmware/interface version, and available APIs;
- obtain the official manual and the laboratory-approved SOP;
- choose one short, safe, visually observable procedure;
- have the state graph and safety constraints reviewed by the supervisor;
- collect real-printer data as a separate device package and split;
- measure zero-shot transfer first, then few-shot adaptation.

## 11. Stop/go gate before AR integration

Do not spend the next week polishing AR visuals until the offline model can:

- retrieve the correct step substantially above adjacent-step chance;
- distinguish completed from incomplete and wrong operation;
- provide usable component evidence;
- abstain on occluded or unsupported observations.

If it cannot, the next task is data/failure analysis, not UI work.
