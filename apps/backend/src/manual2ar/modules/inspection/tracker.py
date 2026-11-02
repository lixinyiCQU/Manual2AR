"""Reuse module-one engines with a task-scoped large-plate area contract."""
from manual2ar.integrations.perception.provider import LearningTracker
from manual2ar_perception.cpu_tracker import CpuLearningTracker
from .rules import initial_mask_quality
import json
import numpy as np

class PlateCpuTracker(CpuLearningTracker):
    def __init__(self,settings,rules):
        super().__init__(settings);self.rules=rules

    def _mask_quality(self,state):
        if state.component_id.startswith(('intro_build_plate','intro_foreign_object_','intro_residue_')) and state.guidance_target is not None:
            return initial_mask_quality(state,self.rules)
        return super()._mask_quality(state)

class InspectionTracker(LearningTracker):
    def __init__(self,provider,config):
        super().__init__(provider,config)
        local=PlateCpuTracker(config['cpu_tracking'],config['inspection'])
        if provider=='sam31_cutie':self.engine.local=local;self.local=local
        else:self.local=local;self.engine=local

    def prepare(self,image,candidates,folder,log,minimum_confidence):
        # Legacy GPU services break initial overlap ties by target order. Put
        # foreground instances before their supporting plate. Updated services
        # also resolve overlap before constructing Cutie's persistent memory.
        ordered=sorted(candidates,key=lambda c:(c.component_id=='build_plate',
            (c.bbox_0_1000[2]-c.bbox_0_1000[0])*(c.bbox_0_1000[3]-c.bbox_0_1000[1])))
        result=super().prepare(image,ordered,folder,log,minimum_confidence)
        report=folder/'cutie/initialization.json'
        if report.is_file():
            metrics=json.loads(report.read_text()).get('metrics',{})
            initial={x['component_id']:x for x in metrics.get('initialization',{}).get('targets',[])}
            for identity,mask in (getattr(self.local,'external_masks',None) or {}).items():
                sam=initial.get(identity,{});ratio=float(np.asarray(mask,bool).mean())
                log.event('inspection.initial_mask_integrity',{'check_id':folder.name,'component_id':identity,
                    'sam_area_ratio':sam.get('area_ratio'),'sam_point_in_mask':sam.get('point_in_mask'),
                    'cutie_area_ratio':ratio,'cutie_pixels':int(np.count_nonzero(mask)),
                    'exclusive_initialization':metrics.get('exclusive_initialization'),
                    'possible_initialization_loss':bool(sam.get('area_ratio',0)>0 and ratio<sam['area_ratio']*.1)})
        return result
