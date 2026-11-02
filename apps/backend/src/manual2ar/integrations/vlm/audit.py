"""Log each actual API attempt, including automatic retries; never log auth headers."""
from contextvars import ContextVar
from copy import deepcopy
from time import perf_counter
import base64, hashlib, re
from manual2ar.integrations.vlm.client import QwenChatCompletionsClient
from manual2ar.infrastructure.diagnostics import dump
context = ContextVar('component_vlm_audit',default=None)

class AuditedQwen(QwenChatCompletionsClient):
    def _request_and_parse(self,payload):
        state=context.get()
        if state is None: return super()._request_and_parse(payload)
        state['attempt']+=1
        attempt=state['attempt']; folder=state['folder']; log=state['log']
        safe=deepcopy(payload)
        for message in safe.get('messages',[]):
            if not isinstance(message.get('content'),list): continue
            for part in message['content']:
                if part.get('type')=='image_url':
                    encoded=part['image_url']['url'].split(',',1)[1]
                    part['image_url']['url']='[stored in input.jpg; sha256='+hashlib.sha256(base64.b64decode(encoded)).hexdigest()+']'
        dump(folder/f'api_attempt_{attempt}.json',safe)
        t0=perf_counter()
        try:
            result=super()._request_and_parse(payload)
            log.event('vlm.api_attempt',{'check_id':folder.name,'attempt':attempt,'success':True,
                'elapsed_ms':round((perf_counter()-t0)*1000,1)})
            return result
        except Exception as error:
            summary=str(error).replace(self.api_key,'[REDACTED]') if self.api_key else str(error)
            summary=re.sub(r'sk-[A-Za-z0-9_-]+','[REDACTED]',summary)[:600]
            log.event('vlm.api_attempt',{'check_id':folder.name,'attempt':attempt,'success':False,
                'error_type':type(error).__name__,'error_summary':summary,'elapsed_ms':round((perf_counter()-t0)*1000,1)})
            raise

class AuditedVision:
    def __init__(self,config):
        self._client=AuditedQwen(config)
        self.provider='qwen';self.model=self._client.model;self.base_url=self._client.base_url

    def chat_structured(self,**kwargs):return self._client.chat_structured(**kwargs)
    def configuration_status(self):
        if not self._client.api_key:return False,'VLM credentials are not configured'
        if not self.base_url:return False,'VLM endpoint is not configured'
        return True,None
