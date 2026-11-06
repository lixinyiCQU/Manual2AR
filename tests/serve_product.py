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

def install_u7_fixture(app):
    """Only this controlled test server exposes seeding; production never imports this module."""
    import numpy as np
    from manual2ar.modules.guidance.spatial.simulation import calibration,targets
    from manual2ar_contracts.machine_frame import MachineFrame
    from tests.backend.guidance.test_u7_parts import GPU,VLM
    spatial=app.state.modules['guidance'].state.spatial
    original=spatial.part_tracking.vlm
    recognition_count=0;next_failure={}
    class PartsClient:
        def chat_structured(self,**kwargs):
            nonlocal recognition_count
            if 'parts' in kwargs['schema'].get('properties',{}):
                recognition_count+=1
                if next_failure.pop('recognition',False):raise ValueError('Controlled recognition failure')
                return VLM().chat_structured(**kwargs)
            if next_failure.pop('verification',False):return VLM('not_completed').chat_structured(**kwargs)
            return original.chat_structured(**kwargs)
    spatial.client=PartsClient();spatial.part_tracking.vlm=spatial.client;spatial.part_tracking.client_factory=GPU
    # The fixture client reads a connection descriptor, but GPU above performs no network I/O.
    connection=Path(spatial.config['runtime_dir'])/'controlled-gpu.json';connection.parent.mkdir(parents=True,exist_ok=True);connection.write_text('{}');spatial.part_tracking.config={**spatial.part_tracking.config,'gpu_connection_file':str(connection)}
    # Deterministic feature provider for the real configuration UI; no external model calls.
    from manual2ar.modules.guidance.spatial import automatic_vision
    def controlled_features(client,config,raw,reference,folder):
        import cv2
        from manual2ar_perception.spatial import detect_pose,project
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        calib=calibration();matrix=np.array(calib['matrix']);dist=np.array(calib['distortion'])
        pose,status=detect_pose(image,matrix,dist)
        if pose is None:raise ValueError('Controlled marker missing')
        names=['screw_upper','screw_lower','guide_top','guide_bottom']
        points=[[.04,.05,.18],[.04,.05,.15],[.055,.05,.19],[.055,.05,.14]]
        if next_failure.get('guide_absent',0)>0:
            next_failure['guide_absent']-=1;names=names[:2];points=points[:2]
        return dict(zip(names,project(points,pose['transform'],matrix,dist).tolist())),'Controlled functional points'
    automatic_vision.observe=controlled_features
    @app.post('/test/spatial/next-failure')
    def fail_next(command:dict):
        assert command['kind'] in ('recognition','verification','guide_absent')
        next_failure[command['kind']]=2 if command['kind']=='guide_absent' else True;return {'ready':True}
    @app.get('/test/spatial/recognition-count')
    def count():return {'count':recognition_count}
    @app.post('/test/spatial/seed')
    def seed(command:dict):
        camera_id=command['camera_id']
        if not isinstance(camera_id,str) or len(camera_id)!=24 or any(c not in '0123456789abcdef' for c in camera_id):raise ValueError('Invalid fixture camera')
        spatial.store_profile(spatial.profile('cameras',camera_id),calibration())
        spatial.store_profile(spatial.profile('rigs','a1-mini'),targets(spatial.actions))
        spatial.store_profile(spatial.profile('machines','a1-mini'),MachineFrame(marker_id=23,marker_length_m=.08,marker_from_machine=np.eye(4).ravel().tolist(),frame_id='a'*32,source_frame_sha256=['b'*64,'c'*64],quality={}).model_dump())
        spatial.rig_validity.pop('a1-mini',None);spatial.profile('rig-validity','a1-mini').unlink(missing_ok=True)
        return {'status':'seeded'}


if __name__=='__main__':
    c=configuration(Path(tempfile.mkdtemp(prefix='manual2ar-controlled-')))
    real=load();c['paths']['wiki_archive']=real['paths']['wiki_archive']
    c['gpu']['connection_file']=str(Path(c['paths']['runtime']).parent/'missing-gpu.connection.local.json')
    c['backend'].update(public_url='http://127.0.0.1:18010',port=18010)
    app=create_app(c,{'learning':ComponentVLM(),'guidance':VisualClient(),'inspection':FakeVLM()},tracker_factory=lambda _:DelayedTracker())
    install_u7_fixture(app)
    uvicorn.run(app,host='0.0.0.0',port=18010)
