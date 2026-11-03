from fastapi import APIRouter
from fastapi.responses import Response
from .models import Begin,Frame,Author,Save,Verify,Interaction
from .service import SpatialService
from .printing import sheets


def router(config,registry,client,experience=None):
    service=SpatialService(config,registry,client,experience)
    api=APIRouter(prefix='/api/guidance/spatial',tags=['desktop-spatial-guidance'])

    @api.get('/config')
    def config_view():return service.catalog()

    @api.get('/capabilities')
    def capabilities():return service.capabilities()

    @api.get('/print.pdf')
    def print_pdf():return Response(sheets(),media_type='application/pdf')

    @api.get('/replay/{index}.jpg')
    def replay(index:int):
        from .simulation import jpeg
        return Response(jpeg(index%240),media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @api.post('/sessions',status_code=201)
    def begin(command:Begin):return service.begin(command)

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

    @api.post('/sessions/{identity}/events')
    def event(identity:str,command:Interaction):return service.interaction(identity,command)

    @api.delete('/sessions/{identity}',status_code=204)
    def close(identity:str):service.close(identity)

    return api,service
