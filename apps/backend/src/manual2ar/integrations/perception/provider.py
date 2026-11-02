"""Two shared visual engines: local CPU, or real persistent SAM3.1 + Cutie."""
from manual2ar_perception.cpu_tracker import CpuLearningTracker


class LearningTracker:
    def __init__(self,provider,config):
        if provider not in ('opencv','sam31_cutie'):raise ValueError('Select opencv or sam31_cutie')
        self.provider=provider;self.config=config
        if provider=='sam31_cutie':
            from .remote_tracker import CutieTracker
            self.engine=CutieTracker(config)
            self.local=self.engine.local
        else:
            self.local=CpuLearningTracker(config.get('cpu_tracking'));self.engine=self.local

    def prepare(self,image,candidates,folder,log,minimum_confidence):
        if self.provider=='sam31_cutie':return self.engine.prepare(image,candidates,folder,log,minimum_confidence)
        log.event('learning.segmenter',{'check_id':folder.name,'first_mask':'opencv-seeded-grabcut','tracking':self.local.provider_name})

    def start(self,*args,**kwargs):return self.engine.start(*args,**kwargs)
    def update(self,*args,**kwargs):return self.engine.update(*args,**kwargs)
    def update_many(self,*args,**kwargs):return self.engine.update_many(*args,**kwargs)
    def close(self,*args,**kwargs):return self.engine.close(*args,**kwargs)
    def shutdown(self):
        if self.provider=='sam31_cutie':self.engine.shutdown()
    def health(self):return {'first_mask':self.provider,'tracking':self.engine.provider_name}
