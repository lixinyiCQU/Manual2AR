"""A catalog entry binds imported evidence to a reusable teaching workspace."""
from urllib.parse import urlsplit
from fastapi import HTTPException
from pydantic import BaseModel,Field,ConfigDict
from manual2ar.resources import ResourceStore
from .contracts import MODULES
from .config import for_module

class ServiceDefinition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^[a-z][a-z0-9-]{0,63}$')
    title:str
    description:str
    teaching_title:str
    headline:str
    introduction:str
    content_version:str
    source_title:str
    snapshot_resource:str
    backend_url:str=''
    module_ids:list[str]=Field(min_length=1)

class ServiceRegistry:
    def __init__(self,config):
        self.origin=config['backend']['public_url'].rstrip('/')
        self.resources=ResourceStore.configured(for_module(config,'learning'))
        value=self.resources.json('app.services')
        if value['schema_version']!='manual2ar-services-v1':raise ValueError('Unsupported service catalog')
        self.entries=[ServiceDefinition.model_validate(item) for item in value['services']]
        if len({e.id for e in self.entries})!=len(self.entries):raise ValueError('Duplicate teaching service')
        supported={m.id for m in MODULES}
        for entry in self.entries:
            if len(set(entry.module_ids))!=len(entry.module_ids) or not set(entry.module_ids)<=supported:
                raise ValueError('Unsupported or duplicate teaching module')
            parsed=urlsplit(entry.backend_url or self.origin)
            if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
                raise ValueError('Teaching service URL must be a public HTTP(S) origin')
            snapshot=self.resources.json(entry.snapshot_resource)
            if not snapshot.get('snapshot_id') or not snapshot.get('archive_sha256'):raise ValueError('Teaching service requires a versioned evidence snapshot')

    def catalog(self,availability=None):
        availability=availability or {}
        services=[]
        for entry in self.entries:
            snapshot=self.resources.json(entry.snapshot_resource)
            origin=(entry.backend_url or self.origin).rstrip('/')
            modules=[]
            for identity in entry.module_ids:
                module=next(m for m in MODULES if m.id==identity)
                status=availability.get(identity,{}) if origin==self.origin else {}
                modules.append(module.model_copy(update=status).model_dump())
            services.append({**entry.model_dump(exclude={'module_ids','snapshot_resource'}),
                'backend_url':origin,'snapshot_version':snapshot['snapshot_id'],
                'modules':modules})
        return {'schema_version':'manual2ar-services-v1','import_available':False,'services':services}

    def detail(self,identity,availability=None):
        found=next((s for s in self.catalog(availability)['services'] if s['id']==identity),None)
        if found is None:raise HTTPException(404,'该教学服务尚未导入。')
        return found
