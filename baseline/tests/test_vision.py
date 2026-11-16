from copy import deepcopy
import io
import json
from pathlib import Path
import urllib.error

from PIL import Image
import pytest

from manual2ar_baseline.gt import digest, encoded, load_bundle
from manual2ar_baseline.photos import check_run, confirm, observe, prepare_session
from manual2ar_baseline.provider import CompatibleClient, ModelError, Settings, load_settings
from manual2ar_baseline.photo_review import review_saved, score
from manual2ar_baseline.state import Session
from manual2ar_baseline.vision import EvidenceIdentityError, Findings, Protocol, evaluate, photo, prompt_for, reference_images


BASELINE = Path(__file__).resolve().parents[1]
ROOT = BASELINE.parent
GT = BASELINE / "ground_truth/u7/v1"
BUNDLE = GT / "state-validation"
PROTOCOL = GT / "visual-protocol.json"
ROI_PROTOCOL = GT / "visual-protocol-roi.json"


@pytest.fixture
def setup(tmp_path):
    sources, protocol, session = prepare_session(BUNDLE, PROTOCOL, intent="我已完成底座安装，现在希望安装支架")
    path = tmp_path / "scene.png"
    Image.new("RGB", (640, 480), "white").save(path)
    return sources, protocol, session, path


def body(query):
    rows = []
    values = dict(mount_relation="seated", connection_relation="connected", appearance="no_visible_anomaly", fastener_instances="instances")
    for q in query["queries"]:
        row = dict(query_id=q["id"], observability="observable", coverage="complete", region={"xyxy": [0, 0, 1000, 1000]},
                   value=values[q["kind"]], evidence_boxes=[{"xyxy": [100, 100, 900, 900]}], instances=[], evidence="受控事实，不是视觉质量标注")
        if q["kind"] == "fastener_instances":
            row.update(evidence_boxes=[], instances=[dict(box={"xyxy": [200, 200, 300, 300]}, location="upper_hole"),
                                                        dict(box={"xyxy": [200, 600, 300, 700]}, location="lower_hole")])
        rows.append(row)
    return dict(evidence_image_id="current_scene", source_sha256=query["source_sha256"], findings=rows)


class FakeClient:
    kind = "controlled_provider"

    def __init__(self, mutation=None):
        self.calls = []
        self.mutation = mutation

    def call(self, prompt, schema, images):
        self.calls.append(dict(prompt=prompt, schema=schema, images=images))
        query = json.JSONDecoder().raw_decode(prompt.split("QUERY:", 1)[1])[0]
        result = body(query)
        if self.mutation:
            self.mutation(result, len(self.calls))
        return json.dumps(result), dict(model="controlled-test", elapsed_ms=0, usage={})


def sample(setup):
    sources, protocol, session, path = setup
    refs = reference_images(sources, protocol, ROOT)
    current, _ = photo(path.read_bytes())
    prompt, query = prompt_for(session.task, protocol, digest(current), refs)
    return prompt, query, body(query)


def test_query_excludes_expected_rules_claims_and_manual_conditions(setup):
    prompt, query, response = sample(setup)
    assert "expected" not in prompt and "rules" not in query
    assert "我已完成底座安装" not in prompt
    assert not any(c in prompt for c in ("c.base.secure", "c.base.direction", "c.holder.direction"))
    assert query["images"][0]["role"] == "current_scene"
    assert all(i["role"] == "identity_reference" for i in query["images"][1:])
    assert "completed" not in Findings.model_json_schema()["properties"]


def test_scoped_photo_keeps_full_protocol_but_observes_only_selected_operation(tmp_path):
    from manual2ar_baseline.state import Session
    sources, task = load_bundle(BUNDLE)
    protocol = Protocol.model_validate_json(ROI_PROTOCOL.read_bytes())
    session = Session.from_bundle(BUNDLE, 'photo.scoped', '安装支架底座', evidence_mode='experimental_photo_analysis',
                                  target_node_ids=['install_base'], guidance_policy='scene_guided')
    path = tmp_path/'scene.png'
    Image.new('RGB',(640,480),'white').save(path)
    conditions = {c for c in session.nodes['install_base'].completion_ids if session.conditions[c].channel=='vision'}
    client = FakeClient()
    output = tmp_path/'base-photo'
    plan = observe(session,sources,protocol,path,ROOT,output,client,condition_ids=conditions)
    assert plan['mode']=='ask_manual'
    actual = json.loads((output/'evaluated.json').read_bytes())['readings']
    assert set(actual)==conditions and all('holder' not in k for k in actual)
    assert json.loads((output/'protocol.json').read_bytes())==protocol.model_dump()
    request = json.loads((output/'request.json').read_bytes())
    assert request['observation_protocol_sha256']!=request['protocol_sha256']
    assert '安装支架底座' in client.calls[0]['prompt']
    assert len(client.calls)==2
    fragments = [dict(source_id=r.source_id, quote=r.quote) for r in task.requirements
                 if r.id in set(task.policy_requirement_ids) | set(session.nodes['install_base'].requirement_ids)]
    for filename in ('query.json', 'detail-query.json'):
        context = json.loads((output/filename).read_bytes())['task_context']
        assert context['user_claims_are_not_evidence']
        assert context['official_operations']==[dict(node_id='install_base', instruction=session.nodes['install_base'].instruction)]
        assert context['official_fragments']==fragments
        assert '底座会被装好的支架遮住' in ''.join(r['quote'] for r in context['official_fragments'])
    for index in range(2):
        output = tmp_path/('manual-'+str(index))
        confirm(session,protocol,session.plan()['condition_ids'],'受控操作者确认，不是实际验收',output)
    assert session.plan()['mode']=='complete'
    _, _, resumed = prepare_session(BUNDLE,ROI_PROTOCOL,resume=output,same_context=True)
    assert resumed.target_node_ids==('install_base',) and resumed.guidance_policy=='scene_guided'
    assert resumed.plan()['mode']=='complete' and resumed.needed=={'install_base'}
    with pytest.raises(ValueError,match='unknown/nonvisual'):
        observe(session,sources,protocol,path,ROOT,tmp_path/'bad',client,condition_ids=['c.base.secure'])


@pytest.mark.parametrize('reason', ['occluded', 'unresolved_identity'])
def test_policy_context_does_not_promote_hidden_current_facts(setup, tmp_path, reason):
    sources, _, session, path = setup
    protocol = Protocol.model_validate_json(ROI_PROTOCOL.read_bytes())
    session.guidance_policy = 'evidence_guided'
    def hidden(reply, number):
        for row in reply['findings']:
            if row['query_id'].startswith('base_') and not (number==1 and row['query_id']=='base_mount'):
                row.update(observability=reason, coverage='unknown', region=None, value='unresolved', evidence_boxes=[], instances=[])
    client = FakeClient(hidden)
    output = tmp_path/'hidden'
    plan = observe(session,sources,protocol,path,ROOT,output,client)
    assert len(client.calls)==2 and plan['mode']=='request_view'
    assert not plan['completed_node_ids']
    readings = json.loads((output/'evaluated.json').read_bytes())['readings']
    assert all(readings[cid]==dict(value='unknown', reason=reason)
               for cid in ('c.base.mount', 'c.base.screws', 'c.base.appearance'))
    assert all(fact.value=='unknown' for cid,fact in session.facts.items() if cid.startswith('c.base.'))
    assert readings['c.holder.connection']['value']=='true'
    for call in client.calls:
        assert 'observability=occluded' in call['prompt'] and 'observability=unresolved_identity' in call['prompt']
        assert '历史观察或操作记录不能替代当前图像中未见的事实' in call['prompt']


@pytest.mark.parametrize('policy', ['scene_guided', 'evidence_guided'])
@pytest.mark.parametrize('local_identity', ['seated', 'unresolved_identity'])
def test_scene_guided_coarse_negative_requires_local_identity_recheck(tmp_path,local_identity,policy):
    sources,task=load_bundle(BUNDLE)
    protocol=Protocol.model_validate_json(ROI_PROTOCOL.read_bytes())
    session=Session.from_bundle(BUNDLE,'photo.negative-recheck','安装支架底座',evidence_mode='experimental_photo_analysis',
        target_node_ids=['install_base'],guidance_policy=policy)
    path=tmp_path/'scene.png'
    Image.new('RGB',(640,480),'white').save(path)
    def observations(result,attempt):
        mount=next(f for f in result['findings'] if f['query_id']=='base_mount')
        if attempt==1:
            mount['value']='absent'
        elif local_identity=='unresolved_identity':
            mount.update(observability='unresolved_identity',coverage='unknown',region=None,
                         value='unresolved',evidence_boxes=[],instances=[])
    client=FakeClient(observations)
    conditions={c for c in session.nodes['install_base'].completion_ids if session.conditions[c].channel=='vision'}
    out=tmp_path/'recheck'
    result=observe(session,sources,protocol,path,ROOT,out,client,condition_ids=conditions)
    assert len(client.calls)==2
    detail=json.loads((out/'detail-query.json').read_bytes())
    assert any(q['kind']=='mount_relation' for q in detail['queries'])
    assert json.loads((out/'request.json').read_bytes())['source_identity_recheck']
    assert not result['completed_node_ids']
    if local_identity=='seated':
        assert result['mode']=='ask_manual' and session.facts['c.base.mount'].value=='true'
    else:
        assert result['mode']=='request_view' and session.facts['c.base.mount'].value=='unknown'


def test_scene_guided_tiny_negative_region_cannot_authorize_reinstallation(tmp_path):
    sources,_=load_bundle(BUNDLE)
    protocol=Protocol.model_validate_json(ROI_PROTOCOL.read_bytes())
    session=Session.from_bundle(BUNDLE,'photo.tiny-negative','安装支架底座',evidence_mode='experimental_photo_analysis',
        target_node_ids=['install_base'],guidance_policy='scene_guided')
    path=tmp_path/'scene.png'
    Image.new('RGB',(640,480),'white').save(path)
    def tiny(result,attempt):
        mount=next(f for f in result['findings'] if f['query_id']=='base_mount')
        mount.update(value='absent',region={'xyxy':[0,0,1,1]},evidence_boxes=[])
    out=tmp_path/'small'
    result=observe(session,sources,protocol,path,ROOT,out,FakeClient(tiny))
    assert result['mode']=='request_view' and session.facts['c.base.mount'].value=='unknown'
    assert (out/'detail-skipped.json').is_file()


def test_locally_verified_absence_can_receive_guidance_without_absent_fastener_identity(tmp_path):
    sources,_=load_bundle(BUNDLE)
    protocol=Protocol.model_validate_json(ROI_PROTOCOL.read_bytes())
    session=Session.from_bundle(BUNDLE,'photo.checked-absence','安装支架底座',evidence_mode='experimental_photo_analysis',
        target_node_ids=['install_base'],guidance_policy='scene_guided')
    path=tmp_path/'scene.png'
    Image.new('RGB',(640,480),'white').save(path)
    def absent(result,attempt):
        for row in result['findings']:
            if row['query_id']=='base_mount':row['value']='absent'
            elif attempt==2:
                row.update(observability='unresolved_identity',coverage='unknown',region=None,
                    value='unresolved',evidence_boxes=[],instances=[])
    plan=observe(session,sources,protocol,path,ROOT,tmp_path/'absent',FakeClient(absent))
    assert plan['mode']=='operate' and not plan['completed_node_ids']
    assert session.facts['c.base.mount'].value=='false' and session.facts['c.base.screws'].value=='unknown'


@pytest.mark.parametrize("change", ["wrong_task", "missing_visual", "manual_rule", "bad_locations", "unknown_reference"])
def test_protocol_is_bound_complete_and_channel_correct(setup, change):
    sources, protocol, session, _ = setup
    p = protocol.model_copy(deep=True)
    if change == "wrong_task":
        p.task_sha256 = "0" * 64
    elif change == "missing_visual":
        p.rules.pop()
    elif change == "manual_rule":
        p.rules[0].condition_id = "c.base.secure"
    elif change == "bad_locations":
        p.rules[1].expected_locations = ["upper_hole", "upper_hole"]
    else:
        p.queries[0].reference_ids = ["invented"]
    with pytest.raises(ValueError):
        p.check(sources, session.task)


@pytest.mark.parametrize("mutation,expected", [("good", "true"), ("one_screw", "false"), ("empty_complete", "false"),
    ("occluded", "unknown"), ("partial", "unknown"), ("no_region", "unknown"), ("unknown_slot", "unknown")])
def test_joint_fastener_rule_counts_visible_distinct_slots(setup, mutation, expected):
    _, protocol, _, _ = setup
    _, query, reply = sample(setup)
    finding = reply["findings"][1]
    if mutation == "one_screw":
        finding["instances"] = finding["instances"][:1]
    elif mutation == "empty_complete":
        finding["instances"] = []
    elif mutation == "occluded":
        finding["observability"] = "occluded"
    elif mutation == "partial":
        finding["coverage"] = "partial"
    elif mutation == "no_region":
        finding["region"] = None
    elif mutation == "unknown_slot":
        finding["instances"][1]["location"] = "unresolved"
    readings, _ = evaluate(protocol, Findings.model_validate(reply), query["source_sha256"])
    assert readings["c.base.screws"]["value"] == expected


@pytest.mark.parametrize("mutation", ["duplicate_instance", "duplicate_slot", "outside_region", "wrong_kind", "extra_verdict", "wrong_photo", "duplicate_query"])
def test_bad_evidence_never_becomes_state(setup, tmp_path, mutation):
    sources, protocol, session, path = setup

    def change(reply, number):
        row = reply["findings"][1]
        if mutation == "duplicate_instance":
            row["instances"][1]["box"] = deepcopy(row["instances"][0]["box"])
        elif mutation == "duplicate_slot":
            row["instances"][1]["location"] = "upper_hole"
        elif mutation == "outside_region":
            row["region"]["xyxy"] = [0, 0, 10, 10]
        elif mutation == "wrong_kind":
            row["value"] = "connected"
        elif mutation == "extra_verdict":
            reply["status"] = "completed"
        elif mutation == "wrong_photo":
            reply["source_sha256"] = "f" * 64
        else:
            reply["findings"][1] = deepcopy(reply["findings"][0])

    client = FakeClient(change)
    before = session.plan()
    out = tmp_path / "bad"
    with pytest.raises(ValueError):
        observe(session, sources, protocol, path, ROOT, out, client)
    assert session.plan() == before
    assert json.loads((out / "manifest.json").read_bytes())["status"] == "failed"
    assert not (out / "session.json").exists()
    if mutation == "wrong_photo":
        assert len(client.calls) == 1
    with pytest.raises(ValueError, match="failed"):
        check_run(out)


def test_one_recorded_format_repair_without_silent_field_dropping(setup, tmp_path):
    sources, protocol, session, path = setup

    def change(reply, number):
        if number == 1:
            reply["unexpected"] = "not silently removed"

    client = FakeClient(change)
    out = tmp_path / "repair"
    plan = observe(session, sources, protocol, path, ROOT, out, client)
    assert plan["mode"] == "ask_manual" and len(client.calls) == 2
    assert (out / "response-0.txt").exists() and (out / "response-1.txt").exists()
    assert "unexpected" in (out / "response-0.txt").read_text()
    assert "c.base.secure" not in json.loads((out / "evaluated.json").read_bytes())["readings"]
    check_run(out)


@pytest.mark.parametrize('repaired', [True, False])
def test_missing_grounding_repairs_once_and_never_promotes_ungrounded_claims(setup, tmp_path, repaired):
    sources, protocol, session, path = setup
    def missing(reply, number):
        if number==1 or not repaired:
            reply['findings'][0]['evidence_boxes']=[]
    client=FakeClient(missing)
    output=tmp_path/'grounding'
    plan=observe(session,sources,protocol,path,ROOT,output,client)
    assert len(client.calls)==2
    assert (output/'grounding-0.json').is_file() and (output/'response-0.txt').is_file()
    evaluated=json.loads((output/'evaluated.json').read_bytes())['readings']['c.base.mount']
    if repaired:
        assert evaluated['value']=='true' and plan['mode']=='ask_manual'
    else:
        assert evaluated=={'value':'unknown','reason':'insufficient_detail'}
        assert json.loads((output/'evaluated.json').read_bytes())['details'][0]['diagnostic']=='missing_evidence_box'
        assert plan['mode']=='request_view' and (output/'grounding-1.json').is_file()


def test_honest_unknown_does_not_trigger_grounding_repair(setup,tmp_path):
    sources,protocol,session,path=setup
    def unknown(reply,number):
        reply['findings'][0].update(observability='insufficient_detail',coverage='unknown',region=None,value='unresolved',evidence_boxes=[])
    client=FakeClient(unknown)
    plan=observe(session,sources,protocol,path,ROOT,tmp_path/'unknown',client)
    assert len(client.calls)==1 and plan['mode']=='request_view'


def test_real_photo_session_resumes_and_confirms_without_reinstalling(setup, tmp_path):
    sources, protocol, session, path = setup
    first = tmp_path / "first"
    plan = observe(session, sources, protocol, path, ROOT, first, FakeClient())
    assert plan["scope"] == "experimental_photo_analysis" and plan["mode"] == "ask_manual"
    partial = tmp_path / "partial"
    plan = confirm(session, protocol, ["c.base.direction"], "明确确认方向（受控测试）", partial)
    assert plan["condition_ids"] == ["c.base.secure"]
    sources, protocol, resumed = prepare_session(BUNDLE, PROTOCOL, resume=partial, same_context=True)
    base = tmp_path / "base-confirmed"
    confirm(resumed, protocol, ["c.base.secure"], "明确确认紧固（受控测试）", base)

    def hidden(reply, _):
        for row in reply["findings"][:3]:
            row.update(observability="occluded", coverage="partial", value="unresolved", region=None, evidence_boxes=[], instances=[])

    sources, protocol, resumed = prepare_session(BUNDLE, PROTOCOL, resume=base, same_context=True)
    second = tmp_path / "second"
    plan = observe(resumed, sources, protocol, path, ROOT, second, FakeClient(hidden))
    assert plan["node_id"] == "install_holder" and plan["mode"] == "ask_manual"
    assert plan["completed_node_ids"] == ["install_base"]
    last = tmp_path / "last"
    assert confirm(resumed, protocol, ["c.holder.direction"], "明确确认支架方向（受控测试）", last)["mode"] == "complete"
    _, _, loaded = prepare_session(BUNDLE, PROTOCOL, resume=last, same_context=True)
    assert loaded.plan() == resumed.plan()


def test_resume_requires_context_and_detects_tampering(setup, tmp_path):
    sources, protocol, session, path = setup
    out = tmp_path / "photo"
    observe(session, sources, protocol, path, ROOT, out, FakeClient())
    with pytest.raises(ValueError, match="explicit"):
        prepare_session(BUNDLE, PROTOCOL, resume=out)
    _, _, reset = prepare_session(BUNDLE, PROTOCOL, resume=out, context_id="moved_device")
    assert reset.epoch == 1 and all(f.value == "unknown" for f in reset.facts.values())
    p = out / "session.json"
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed"):
        prepare_session(BUNDLE, PROTOCOL, resume=out, same_context=True)


def test_late_photo_cannot_overwrite_context_change(setup, tmp_path):
    sources, protocol, session, path = setup

    def mutate(_, number):
        session.apply(dict(id="new.context", **session.stamp(), kind="context_change", context_id="changed", reason="现场变更"))

    with pytest.raises(ValueError, match="Stale"):
        observe(session, sources, protocol, path, ROOT, tmp_path / "late", FakeClient(mutate))
    assert session.epoch == 1 and all(f.value == "unknown" for f in session.facts.values())


def test_invalid_photo_is_rejected_before_model_call(setup, tmp_path):
    sources, protocol, session, path = setup
    path.write_bytes(b"not an image")
    client = FakeClient()
    with pytest.raises(ValueError):
        observe(session, sources, protocol, path, ROOT, tmp_path / "bad", client)
    assert not client.calls and not (tmp_path / "bad").exists()


def test_review_generation_failure_does_not_commit_photo_facts(setup, tmp_path, monkeypatch):
    sources, protocol, session, path = setup
    before = session.plan()

    def fail(_):
        raise ValueError("Review rendering failed")

    monkeypatch.setattr("manual2ar_baseline.photo_review.render", fail)
    out = tmp_path / "render-failure"
    with pytest.raises(ValueError, match="rendering"):
        observe(session, sources, protocol, path, ROOT, out, FakeClient())
    assert session.plan() == before and not session.events
    assert json.loads((out / "manifest.json").read_bytes())["status"] == "failed"
    with pytest.raises(ValueError, match="failed"):
        check_run(out)


def test_exif_orientation_and_original_identity_are_preserved(setup, tmp_path):
    sources, protocol, session, path = setup
    image = Image.new("RGB", (640, 480), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(path, "JPEG", exif=exif)
    original = path.read_bytes()
    out = tmp_path / "oriented"
    observe(session, sources, protocol, path, ROOT, out, FakeClient())
    request = json.loads((out / "request.json").read_bytes())
    assert request["submitted_size"] == [480, 640]
    assert request["capture_sha256"] == digest(original)
    assert request["source_sha256"] == digest((out / "scene.jpg").read_bytes())
    assert (out / "capture.original").read_bytes() == original


def test_controlled_and_photo_origins_cannot_mix(setup):
    _, _, photo_session, _ = setup
    controlled = Session.from_bundle(BUNDLE, "controlled", "安装")
    for session, origin in [(controlled, "vlm_findings"), (photo_session, "controlled_annotation")]:
        with pytest.raises(ValueError, match="Cannot mix"):
            session.apply(dict(id="cross.origin", **session.stamp(), kind="observation", origin=origin, frame_id=1, source_sha256="a" * 64,
                               values={"c.base.mount": dict(value="true", reason="observed")}))


def test_provider_uses_real_image_content_and_redacts_failure(monkeypatch):
    settings = Settings(base_url="https://example.invalid/v1", model="configured-model", api_key="test-private-credential", proxy_mode="direct")
    calls = []

    class Transport:
        def open(self, request, timeout):
            calls.append(request)
            raise urllib.error.HTTPError(request.full_url, 401, "test-private-credential", {}, io.BytesIO(b"test-private-credential"))

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Transport())
    with pytest.raises(ModelError) as error:
        CompatibleClient(settings).call("Observe JSON facts", {}, [b"image bytes"])
    assert "test-private-credential" not in str(error.value) and "401" in str(error.value)
    payload = json.loads(calls[0].data)
    assert payload["messages"][0]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert payload["response_format"] == {"type": "json_object"}


def test_invalid_private_settings_do_not_echo_key(tmp_path):
    path = tmp_path / "private.json"
    path.write_bytes(encoded(dict(vlm=dict(api_key="never-print-this-key", base_url="http://invalid"))))
    with pytest.raises(ModelError) as error:
        load_settings(path)
    assert "never-print-this-key" not in str(error.value)


def roi_setup(tmp_path):
    sources, protocol, session = prepare_session(BUNDLE, ROI_PROTOCOL)
    path = tmp_path / "scene.png"
    Image.new("RGB", (640, 480), "white").save(path)
    return sources, protocol, session, path


def test_coarse_to_detail_maps_boxes_back_to_the_same_capture(tmp_path):
    sources, protocol, session, path = roi_setup(tmp_path)

    def narrow(reply, number):
        if number == 1:
            reply["findings"][0]["evidence_boxes"] = [{"xyxy": [200, 200, 400, 600]}]

    client = FakeClient(narrow)
    output = tmp_path / "roi"
    plan = observe(session, sources, protocol, path, ROOT, output, client)
    assert len(client.calls) == 2 and len(client.calls[1]["images"]) == 2
    transform = json.loads((output / "detail-transform.json").read_bytes())
    assert transform["crop_rect_pixels"] == [108, 76, 275, 307]
    assert transform["same_capture_not_independent_frame"] is True
    assert transform["crop_sha256"] != transform["source_sha256"]
    combined = json.loads((output / "findings.json").read_bytes())
    detail = json.loads((output / "detail-findings.json").read_bytes())
    assert combined["source_sha256"] == transform["source_sha256"]
    assert detail["source_sha256"] == transform["crop_sha256"]
    row = next(r for r in combined["findings"] if r["query_id"] == "base_fasteners")
    assert row["instances"][0]["box"]["xyxy"] == [221, 255, 247, 303]
    assert plan["mode"] == "ask_manual" and session.last_frame == 1
    assert len(session.events) == 1
    check_run(output)


def test_detail_identity_failure_revokes_related_coarse_claims(tmp_path):
    sources, protocol, session, path = roi_setup(tmp_path)

    def wrong_part(reply, number):
        if number == 1:
            reply["findings"][0]["evidence_boxes"] = [{"xyxy": [200, 200, 400, 600]}]
        else:
            reply["findings"][0].update(observability="unresolved_identity", coverage="unknown", region=None,
                                          value="unresolved", evidence_boxes=[], instances=[], evidence="这是立柱开口，无法确认是底座")

    out = tmp_path / "wrong-part"
    plan = observe(session, sources, protocol, path, ROOT, out, FakeClient(wrong_part))
    assert plan["condition_ids"] == ["c.base.mount"] and plan["mode"] == "request_view"
    assert plan["conditions"]["c.base.appearance"]["value"] == "unknown"
    assert json.loads((out / "coarse-findings.json").read_bytes())["findings"][0]["value"] == "seated"


def test_tiny_roi_never_falls_back_to_coarse_screw_pass(tmp_path):
    sources, protocol, session, path = roi_setup(tmp_path)

    def tiny(reply, _):
        reply["findings"][0]["evidence_boxes"] = [{"xyxy": [400, 400, 410, 410]}]

    client = FakeClient(tiny)
    out = tmp_path / "tiny"
    plan = observe(session, sources, protocol, path, ROOT, out, client)
    assert len(client.calls) == 1 and (out / "detail-skipped.json").exists()
    assert plan["conditions"]["c.base.screws"]["value"] == "unknown" and plan["mode"] == "request_view"


def test_detail_photo_identity_cannot_be_substituted(tmp_path):
    sources, protocol, session, path = roi_setup(tmp_path)

    def mismatch(reply, number):
        if number == 1:
            reply["findings"][0]["evidence_boxes"] = [{"xyxy": [200, 200, 400, 600]}]
        else:
            reply["source_sha256"] = "f" * 64

    client = FakeClient(mismatch)
    with pytest.raises(EvidenceIdentityError):
        observe(session, sources, protocol, path, ROOT, tmp_path / "mismatch", client)
    assert len(client.calls) == 2 and session.revision == 0


@pytest.mark.parametrize("reason,mode", [("occluded", "ask_manual"), ("unresolved_identity", "request_view"), ("insufficient_detail", "request_view")])
def test_skipped_detail_preserves_only_normal_occlusion_after_full_base_verification(tmp_path, reason, mode):
    sources, protocol, session, path = roi_setup(tmp_path)
    observe(session, sources, protocol, path, ROOT, tmp_path / "first", FakeClient())
    confirm(session, protocol, ["c.base.direction", "c.base.secure"], "受控操作者确认方向和紧固", tmp_path / "manual")

    def hidden(reply, _):
        for row in reply["findings"][:3]:
            row.update(observability=reason, coverage="unknown", region=None, value="unresolved", evidence_boxes=[], instances=[])

    client = FakeClient(hidden)
    plan = observe(session, sources, protocol, path, ROOT, tmp_path / "next", client)
    assert len(client.calls) == 1 and plan["mode"] == mode
    assert plan["conditions"]["c.base.screws"]["value"] == ("true" if reason == "occluded" else "unknown")
    if reason == "occluded":
        assert plan["condition_ids"] == ["c.holder.direction"]


def test_review_templates_are_unrated_and_do_not_change_original_evidence(setup, tmp_path):
    sources, protocol, session, path = setup
    out = tmp_path / "run"
    observe(session, sources, protocol, path, ROOT, out, FakeClient())
    before = (out / "manifest.json").read_bytes()
    derived = tmp_path / "review"
    review_saved(out, derived)
    assert (derived / "scene.jpg").read_bytes() == (out / "scene.jpg").read_bytes()
    assert (derived / "evidence-overlay.jpg").exists() and (derived / "REVIEW.md").exists()
    labels = json.loads((derived / "labels.template.json").read_bytes())
    assert set(labels["labels"].values()) == {"unrated"} and labels["reviewer"] == ""
    result = score(out, derived / "labels.template.json", tmp_path / "score-unrated")
    assert result["rated"] == 0 and result["unrated"] == 5 and result["label_agreement"] is None
    assert (out / "manifest.json").read_bytes() == before
    check_run(out)


def test_scores_use_explicit_bound_labels_without_updating_state(setup, tmp_path):
    sources, protocol, session, path = setup
    out = tmp_path / "run"
    observe(session, sources, protocol, path, ROOT, out, FakeClient())
    before = session.plan()
    labels = json.loads((out / "labels.template.json").read_bytes())
    labels.update(reviewer="controlled-test-reviewer", independent_review=False)
    labels["labels"]["c.base.mount"] = "false"
    labels["labels"]["c.base.screws"] = "unknown"
    labels["labels"]["c.base.appearance"] = "true"
    p = tmp_path / "labels.json"
    p.write_bytes(encoded(labels))
    report = score(out, p, tmp_path / "score")
    assert report["rated"] == 3 and report["unrated"] == 2
    assert report["counts"]["false_accept"] == report["counts"]["unsupported_accept"] == report["counts"]["agreement"] == 1
    assert session.plan() == before
    labels["source_sha256"] = "0" * 64
    p.write_bytes(encoded(labels))
    with pytest.raises(ValueError, match="another image"):
        score(out, p, tmp_path / "bad-score")


def test_fastener_locations_are_data_driven_not_limited_to_u7_two_slots(setup):
    _, protocol, _, _ = setup
    protocol = protocol.model_copy(deep=True)
    regions = ["corner_a", "corner_b", "corner_c", "corner_d"]
    protocol.queries[1].location_ids = regions
    protocol.rules[1].expected_locations = regions
    _, query, response = sample(setup)
    row = response["findings"][1]
    row["instances"] = [dict(location=identity, box={"xyxy": box}) for identity, box in zip(regions,
        [[100, 100, 200, 200], [700, 100, 800, 200], [100, 700, 200, 800], [700, 700, 800, 800]])]
    readings, _ = evaluate(protocol, Findings.model_validate(response), query["source_sha256"])
    assert readings["c.base.screws"]["value"] == "true"
