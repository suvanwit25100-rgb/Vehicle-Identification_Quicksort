import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

PLATE_LEN = 10
ABSENT = "-"        # the second series slot of a plate that has only one series letter: not unreadable, simply not there
ABSENT_SLOT = 5
_ONE_SERIES_LETTER = re.compile(r"^[A-Z]{2}\d[0-9A-Z][A-Z]\d{4}$")   # SS D A L NNNN: nine characters


def to_slots(plate: str) -> str:
    """A plate as the ten slots the engine works in. A nine-character plate gets an absent marker in the second series slot."""
    p = "".join(plate.upper().split())
    return p[:ABSENT_SLOT] + ABSENT + p[ABSENT_SLOT:] if len(p) == PLATE_LEN - 1 and _ONE_SERIES_LETTER.match(p) else p


class CharRead(BaseModel):
    char: str = Field(min_length=1, max_length=1)
    conf: float = Field(ge=0.0, le=1.0)


class FrameRead(BaseModel):
    frame_id: int
    sharpness: float = Field(ge=0.0)
    plate_area: float = Field(ge=0.0)
    chars: list[CharRead | None]
    raw: str | None = None  # the whole plate as the reader returned it, before it was fitted to ten slots
    rows: int | None = None  # 1 if read as one line, 2 if split into two rows (most two-wheelers)

    @field_validator("chars")
    @classmethod
    def _length(cls, v):
        if len(v) != PLATE_LEN:
            raise ValueError(f"chars must have exactly {PLATE_LEN} slots (use null for unread)")
        return v


class SlotResult(BaseModel):
    index: int
    char: str | None
    confidence: float
    support_frames: list[int] = []
    alternatives: dict[str, float] = {}


class FusedPlate(BaseModel):
    slots: list[SlotResult]

    @property
    def pattern(self) -> str:
        return "".join(s.char or "?" for s in self.slots)

    @property
    def display(self) -> str:
        """The plate as a person writes it: the absent marker is left out (DL1LR2711, not DL1LR-2711)."""
        return self.pattern.replace(ABSENT, "")

    @property
    def known_count(self) -> int:
        """Characters actually read. The absent marker is knowledge about the layout, not a readable character."""
        return sum(1 for s in self.slots if s.char and s.char != ABSENT)


class Evidence(BaseModel):
    department: str = "police"
    frames: list[FrameRead]
    colour: dict[str, float] | None = None
    body_type: dict[str, float] | None = None


class RegistryRow(BaseModel):
    reg_id: str
    plate: str
    colour: str
    body_type: str
    make: str
    model: str
    flags: list[str] = []


class Candidate(BaseModel):
    reg_id: str
    plate: str
    slots: str = ""   # the plate in the engine's ten slots (a nine-character plate has an absent marker); the mismatch positions refer to this
    colour: str
    body_type: str
    make: str
    model: str
    flags: list[str]
    confidence: float
    components: dict[str, float]
    matched_slots: list[int]
    mismatched_slots: list[int]
    unknown_slots: list[int]
    reasons: list[str]


class SecondReading(BaseModel):
    reader: str
    reading: str
    verdict: Literal["agrees", "disagrees", "inconclusive"]
    agree: int
    clash: int


class VideoInfo(BaseModel):
    width: int
    height: int
    fps: float
    duration_s: float | None = None
    frames_total: int | None = None


class TrackAnalysis(BaseModel):
    track_id: int
    vehicle_label: str
    frames_seen: int
    frames_with_plate: int
    colour: dict[str, float] | None
    body_type: dict[str, float] | None
    frame_reads: list[FrameRead]
    plate_crops: list[str]
    max_plate_width_px: int | None = None
    plate_note: str | None = None
    merged_from: list[int] = []
    vehicle_crop: str | None = None
    evidence_frame: str | None = None
    plate_layout: str | None = None  # "one-row" or "two-row", from how most frames of this vehicle were read
    second_reader: SecondReading | None = None
    match: "MatchResult"


class AnalysisResult(BaseModel):
    job_id: str
    department: str
    source_sha256: str
    frames_sampled: int
    tracks: list[TrackAnalysis]
    # everything below is optional so jobs saved by earlier versions still load
    source_filename: str | None = None
    created_at: str | None = None
    video: VideoInfo | None = None
    processing_seconds: float | None = None
    body_model: str | None = None
    second_reader_used: str | None = None


class MatchResult(BaseModel):
    status: Literal["match", "ambiguous", "no_confident_match", "insufficient_evidence"]
    message: str
    pattern: str
    fused: FusedPlate
    candidates: list[Candidate]


TrackAnalysis.model_rebuild()
