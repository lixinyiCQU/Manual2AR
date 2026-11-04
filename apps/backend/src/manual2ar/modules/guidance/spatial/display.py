"""Task display composition, separate from perception, animation and acceptance."""
import json
from manual2ar_contracts.guidance_display import GuidanceDisplay

class DisplayCatalog:
    def __init__(self,path,library,actions):
        self.profiles={}
        for identity,data in json.loads(path.read_text()).items():
            profile=GuidanceDisplay.model_validate(data)
            if identity!=profile.action_id or identity not in actions:raise ValueError('Unknown display action')
            for item in profile.legend:
                if item.kind=='model' and item.asset_id not in library.assets:raise ValueError('Unknown legend asset')
            self.profiles[identity]=profile
    def bundle(self):return [p.model_dump() for p in self.profiles.values()]
    def at(self,identity,position):
        if identity not in self.profiles:return None
        data=self.profiles[identity].model_dump();data['instruction']['position_m']=list(position)
        return GuidanceDisplay.model_validate(data).model_dump()
