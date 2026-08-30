FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SAM2_BUILD_CUDA=0 \
    PYTHONPATH=/workspace/backend:/workspace/gpu_tracking_service

WORKDIR /workspace

COPY third_party/grounded-sam-2 /opt/grounded-sam-2
RUN python -m pip install --upgrade pip && \
    python -m pip install -e /opt/grounded-sam-2

COPY gpu_tracking_service/requirements.txt /tmp/manual2ar-gpu-requirements.txt
RUN python -m pip install -r /tmp/manual2ar-gpu-requirements.txt

COPY backend /workspace/backend
COPY gpu_tracking_service /workspace/gpu_tracking_service

EXPOSE 8020
CMD ["python", "-m", "uvicorn", "gpu_service.main:app", "--host", "0.0.0.0", "--port", "8020"]
