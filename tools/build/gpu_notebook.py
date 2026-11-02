"""Generate the single shared SAM3.1/Cutie notebook with Drive cache and V1 fixes."""
from pathlib import Path
import tempfile
from .gpu_base import build as base_build
from .gpu_cache import build as cache_build

def build():
    root=Path(__file__).resolve().parents[2]
    base_build()
    source=Path(tempfile.gettempdir())/'Manual2AR-GPU-base.ipynb'
    cache_build(source,root/'deploy/colab/Manual2AR_GPU.ipynb')
    source.unlink(missing_ok=True)

if __name__=='__main__':build()
