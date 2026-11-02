"""Serve a prepared GPU worker and export its protocol-compatible connection file."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['serve','connection'])
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,required=True)
    parser.add_argument('--public-url')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    config=args.config.absolute();work=args.work_dir.absolute()
    if args.command=='serve':
        os.execv(sys.executable,[sys.executable,'-B','-m','manual2ar_inference.app','--config',str(config),'--work-dir',str(work)])
    if not args.public_url or not args.output:parser.error('connection requires --public-url and --output')
    from urllib.parse import urlsplit
    url=urlsplit(args.public_url)
    if url.scheme not in ('http','https') or not url.netloc or url.query or url.fragment or url.username or url.password:
        parser.error('Supply an HTTP(S) origin without credentials')
    token=json.loads(config.read_text())['api_token']
    if len(token)<24:raise ValueError('Private service token is missing; prepare the service first')
    from manual2ar_contracts.gpu import PROTOCOL
    args.output.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    os.fchmod(fd,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(dict(url=args.public_url.rstrip('/'),api_token=token,protocol=PROTOCOL),stream,indent=2)
    print('Connection file exported; token was not printed.')

if __name__=='__main__':main()
