FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/manual2ar
COPY apps/inference/requirements-gpu.txt /tmp/requirements.txt
RUN pip install --no-cache-dir torch==2.7.1 torchvision==0.22.1 --index-url https://download.pytorch.org/whl/cu126
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY packages/contracts /tmp/contracts
COPY apps/inference /tmp/inference
RUN pip install --no-deps /tmp/contracts /tmp/inference
COPY configs/inference.example.json /tmp/inference.example.json
RUN python -c "import json,subprocess; c=json.load(open('/tmp/inference.example.json')); repos={'cutie':'https://github.com/hkchengrex/Cutie.git','ultralytics':'https://github.com/ultralytics/ultralytics.git'}; [(subprocess.run(['git','clone','--filter=blob:none',url,'/opt/'+name],check=True),subprocess.run(['git','checkout',c['revisions'][name]],cwd='/opt/'+name,check=True),subprocess.run(['pip','install','--no-deps','--no-build-isolation','/opt/'+name],check=True)) for name,url in repos.items()]"
# Mount prepared checkpoints and a private config under /data; never copy credentials into the image.
WORKDIR /data
EXPOSE 8021
CMD ["python", "-m", "manual2ar_inference.app", "--config", "/data/configs/inference.local.json", "--work-dir", "/data"]
