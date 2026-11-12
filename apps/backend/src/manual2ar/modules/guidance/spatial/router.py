from fastapi import APIRouter
from fastapi.responses import Response
from .models import Begin,Frame,Author,Save,Verify,Interaction,Orientation,MachineAuthor,MotionCommand,ReuseSaved,PrintedReference,AutomaticPair
from .service import SpatialService
from .printing import sheets,workboard


def router(config,registry,client,experience=None,*,service=None,prefix='/api/guidance/spatial'):
    service=service if service is not None else SpatialService(config,registry,client,experience)
    api=APIRouter(prefix=prefix,tags=['desktop-spatial-guidance'])

    @api.get('/config')
    def config_view():return service.catalog()

    @api.get('/sequence')
    def sequence_status(tutorial_run_id:str=''):
        return service.sequence_status(tutorial_run_id)

    @api.get('/capabilities')
    def capabilities():return service.capabilities()

    @api.get('/print.pdf')
    def print_pdf():return Response(sheets(),media_type='application/pdf')

    @api.get('/workboard.pdf')
    def workboard_pdf():return Response(workboard(),media_type='application/pdf')

    @api.get('/replay/{index}.jpg')
    def replay(index:int):
        from .simulation import jpeg
        return Response(jpeg(index%240),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @api.post('/sessions',status_code=201)
    def begin(command:Begin):return service.begin(command)

    @api.post('/sessions/{identity}/reuse')
    def reuse(identity:str,command:ReuseSaved):return service.reuse_saved(identity)

    @api.post('/sessions/{identity}/frames')
    def frame(identity:str,command:Frame):return service.frame(identity,command)

    @api.post('/sessions/{identity}/frames/{frame_id}/pin')
    def pin(identity:str,frame_id:int):return service.pin(identity,frame_id)

    @api.post('/sessions/{identity}/calibration')
    def calibrate(identity:str):return service.calibrate(identity)

    @api.post('/sessions/{identity}/targets')
    def author(identity:str,command:Author):return service.author(identity,command)

    @api.post('/sessions/{identity}/targets/confirm')
    def save(identity:str,command:Save):return service.save(identity,command)

    @api.post('/sessions/{identity}/verify')
    def verify(identity:str,command:Verify):return service.verify(identity,command)

    @api.post('/sessions/{identity}/locate')
    def locate(identity:str,command:Verify):return service.locate(identity,command)

    @api.get('/references/{kind}')
    def part_reference(kind:str):
        from fastapi import HTTPException
        if kind not in service.references:raise HTTPException(404,'Unknown reference')
        return Response(service.references[kind],media_type='image/jpeg')

    @api.get('/sessions/{identity}/parts/{job_id}')
    def parts_status(identity:str,job_id:str):
        with service.session(identity):return service.part_tracking.status(identity,job_id)

    @api.post('/sessions/{identity}/parts/{job_id}/frames')
    def parts_frame(identity:str,job_id:str,command:Verify):
        return service.part_tracking.track(identity,job_id,service.photo_frame(identity,command))

    @api.delete('/sessions/{identity}/parts',status_code=204)
    def parts_close(identity:str,job_id:str|None=None):service.part_tracking.cancel(identity,job_id)

    @api.post('/sessions/{identity}/orientation')
    def orient(identity:str,command:Orientation):return service.orient(identity,command)

    @api.post('/sessions/{identity}/machine/candidates')
    def machine_author(identity:str,command:MachineAuthor):return service.machine.author(identity,command)

    @api.post('/sessions/{identity}/machine/confirm')
    def machine_confirm(identity:str,command:Save):return service.machine.confirm(identity,command)

    @api.post('/sessions/{identity}/motion')
    def motion(identity:str,command:MotionCommand):return service.machine.save_motion(identity,command)

    @api.post('/sessions/{identity}/automatic/reference')
    def printed_reference(identity:str,command:PrintedReference):return service.automatic.reference(identity,command)

    @api.post('/sessions/{identity}/automatic/reset')
    def reset_profiles(identity:str,command:ReuseSaved):return service.automatic.reset(identity)

    @api.post('/sessions/{identity}/automatic/views')
    def automatic_view(identity:str,command:Verify):return service.automatic.observe(identity,command)

    @api.post('/sessions/{identity}/automatic/candidates')
    def automatic_candidate(identity:str,command:AutomaticPair):return service.automatic.candidate(identity,command)

    @api.post('/sessions/{identity}/automatic/confirm')
    def automatic_confirm(identity:str,command:Save):return service.automatic.confirm(identity,command)

    @api.post('/sessions/{identity}/events')
    def event(identity:str,command:Interaction):return service.interaction(identity,command)

    @api.delete('/sessions/{identity}',status_code=204)
    def close(identity:str):service.close(identity)

    return api,service
