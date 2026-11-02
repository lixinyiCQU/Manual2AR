"""Release UI receives enumerated states, never model-authored descriptions."""
STATUSES={'anomaly_detected','no_visible_anomaly','known_anomalies_removed','insufficient_evidence','service_unavailable'}

def public_result(decision,objects,scene_candidates=None):
    status=decision.get('status')
    if status not in STATUSES:status='insufficient_evidence'
    confirmed=set(decision.get('semantic_anomaly_ids',[]))
    ready={o['id'] for o in objects if o.get('tracking_ready')}
    checks=decision.get('clear_checks',{})
    visible_sufficient=all(checks.get(k,False) for k in ('plate_found','plate_self_confidence_sufficient','scene_self_confidence_sufficient')) and checks.get('plate_localization_usable',checks.get('plate_boundary_mask_usable',False))
    sufficient=visible_sufficient and checks.get('full_surface_visible',False)
    partial=checks.get('plate_found',False) and not checks.get('full_surface_visible',False)
    visible_clear=partial and visible_sufficient and checks.get('vlm_surface_clear',False) and checks.get('no_confirmed_or_uncertain_anomaly',False)
    # A complete-plate conclusion is unchanged. The UI can state the more
    # limited observation without calling the unobserved edge clean.
    if visible_clear and not decision.get('occlusion_confirmed'):status='visible_surface_clear'
    confirmable=decision.get('occlusion_confirmation_eligible',False) and not decision.get('occlusion_confirmed',False)
    if confirmable:status='needs_user_confirmation'
    def kind_state(kind):
        findings=[o for o in objects if o['id'] in confirmed and o.get('kind')==kind]
        if findings:
            if all(not o.get('tracking_ready') and o.get('tracking_state') in ('lost','recovering') for o in findings):return 'last_detected'
            return 'fail'
        if any(o.get('kind')==kind and o.get('semantic_status')=='candidate' for o in objects):return 'unknown'
        if any(o['id'] in decision.get('removed_anomaly_ids',[]) and o.get('kind')==kind for o in objects):return 'removed'
        if status=='visible_surface_clear':return 'visible_pass'
        if confirmable:return 'visible_pass'
        if status in ('no_visible_anomaly','known_anomalies_removed') or (sufficient and (confirmed or decision.get('snapshot_semantic_anomaly_ids'))):return 'pass'
        return 'not_observed' if partial and not confirmed else 'unknown'
    # Recognition is a semantic observation; a stopped segmenter must not erase it.
    plate_identified=checks.get('plate_found',False) and checks.get('plate_self_confidence_sufficient',False)
    visual_state='tracking' if ready else 'unavailable' if any(o.get('segmentation_status')=='service_error' for o in objects) else 'needs_reinspection'
    reason='none' if status in ('no_visible_anomaly','known_anomalies_removed') else 'incomplete_view' if partial else 'mask_unavailable' if not checks.get('plate_localization_usable',checks.get('plate_boundary_mask_usable',False)) else 'surface_uncertain'
    result=dict(status=status,plate_state='pass' if plate_identified else 'unknown',visual_state=visual_state,recheck_reason=reason,
                foreign_object_state=kind_state('foreign_object'),residue_state=kind_state('residue'),
                location_available=bool(confirmed.issubset(ready)) if confirmed else 'build_plate' in ready,
                requires_occlusion_confirmation=confirmable,occlusion_confirmed=bool(decision.get('occlusion_confirmed')),
                inspection_source_sha256=decision.get('inspection_source_sha256',''))
    if status=='service_unavailable':
        code=decision.get('failure_code','unknown')
        result['failure_code']=code if code in ('credentials','rate_limited','timeout','network','invalid_response','upstream') else 'unknown'
    if confirmable:result['recheck_reason']='toolhead_upper_left'
    if scene_candidates:
        result.update(status='scene_changed' if status!='anomaly_detected' else status,recheck_reason='new_object',unclassified_count=len(scene_candidates),foreign_object_state='unclassified',location_available=False,requires_occlusion_confirmation=False,occlusion_confirmed=False)
        if result['residue_state']!='fail':result['residue_state']='unknown'
    return result

def user_title(status):
    return {'anomaly_detected':'发现板面异物或残料','no_visible_anomaly':'本次检查未见明显异常',
            'known_anomalies_removed':'检测到的异物或残料已移出打印板',
            'needs_user_confirmation':'打印头遮挡区域待人工确认','recheck_required':'画面已变化，请重新检查',
            'visible_surface_clear':'可见板面未见明显异常，边缘需补拍','scene_changed':'发现未识别物体，请重新检查',
            'insufficient_evidence':'请调整画面后重新检查','service_unavailable':'检查暂未完成，请稍后重试'}.get(status,'尚未完成检查')
