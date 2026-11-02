"""Identity of the submitted image, independent of task and GPU frame counters."""
from pydantic import BaseModel, ConfigDict, Field

class FrameIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_frame_id: int = Field(ge=1, le=10_000_000)
    source_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
