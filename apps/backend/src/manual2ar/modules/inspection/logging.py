"""Bounded evidence storage; no headers or private config enter the log."""
from pathlib import Path
from datetime import datetime,timezone
import json,threading

def now():return datetime.now(timezone.utc).isoformat()
def dump(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')

class InspectionLog:
    def __init__(self,path):self.path=Path(path);self.path.mkdir(parents=True);self.lock=threading.Lock()
    def event(self,event,data):
        line=json.dumps({'at':now(),'event':event,**data},ensure_ascii=False,default=str)
        with self.lock:
            with (self.path/'events.jsonl').open('a') as file:file.write(line+'\n')
        if event not in ('tracking.frame','frontend.render'):print('[Inspection] '+line,flush=True)
