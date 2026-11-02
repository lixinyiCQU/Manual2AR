"""Synthetic-provider server for Unity integration verification; no external inference."""
from pathlib import Path
import tempfile
import time
import uvicorn
from manual2ar.application.config import load
from manual2ar.application.server import create_app
from tests.backend.test_application import configuration,ComponentVLM
from tests.backend.guidance.test_workflow import VisualClient
from tests.backend.inspection.test_pipeline import FakeVLM,FakeTracker

class DelayedTracker(FakeTracker):
    def prepare(self,*args):time.sleep(3)
    def start(self,image,component_id,box,guidance_target=None):
        # Unlike the fixed-size unit fixture, editor frames exercise all camera crops.
        import io
        import numpy as np
        from PIL import Image
        key,_=super().start(image,component_id,box,guidance_target)
        with Image.open(io.BytesIO(image)) as picture:width,height=picture.size
        left,top,right,bottom=box
        mask=np.zeros((height,width),bool)
        mask[top*height//1000:bottom*height//1000,left*width//1000:right*width//1000]=True
        self.shared_masks[key]=mask
        return key,self.result(key)

if __name__=='__main__':
    c=configuration(Path(tempfile.mkdtemp(prefix='manual2ar-controlled-')))
    real=load();c['paths']['wiki_archive']=real['paths']['wiki_archive']
    c['gpu']['connection_file']=str(Path(c['paths']['runtime']).parent/'missing-gpu.connection.local.json')
    c['backend'].update(public_url='http://127.0.0.1:18010',port=18010)
    uvicorn.run(create_app(c,{'learning':ComponentVLM(),'guidance':VisualClient(),'inspection':FakeVLM()},tracker_factory=lambda _:DelayedTracker()),host='0.0.0.0',port=18010)
