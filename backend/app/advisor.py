"""Plate-quality advisor: why a vehicle's plate could not be read (fully), and what would help.

It only restates what was measured for each vehicle (frames, plate width, characters read). It never guesses a cause that was not seen.
"""

from __future__ import annotations

from .schemas import AnalysisResult, TrackAnalysis
from .vision.pipeline import MIN_PLATE_PX


def advise_track(t: TrackAnalysis) -> list[str]:
    known = t.match.fused.known_count
    if known >= 10 or (known and "?" not in t.match.fused.pattern):
        return []
    tips: list[str] = []
    if t.frames_with_plate == 0:
        tips.append("The plate was never located. It may be hidden, outside the picture or at a steep angle. A camera aimed along the lane rather than across it helps.")
    elif t.max_plate_width_px is not None and t.max_plate_width_px < MIN_PLATE_PX:
        tips.append(f"The plate was at most {t.max_plate_width_px} px wide and about {MIN_PLATE_PX} px or more is needed. "
                    "A camera mounted closer, zoomed in or at a higher resolution would help.")
    if 0 < t.frames_with_plate < 3:
        tips.append(f"The plate was found in only {t.frames_with_plate} frame{'s' if t.frames_with_plate != 1 else ''}, so there was little to combine. "
                    "A higher frame rate, or a view where the vehicle stays in sight longer, gives more frames to vote across.")
    if known:
        tips.append(f"{known} of 10 characters were read. The rest stay unknown, and more or sharper frames are the only thing that would fill them.")
    elif t.frames_with_plate and not tips:
        tips.append("The plate was found but its characters could not be read reliably: look for blur, a sharp angle or something covering the plate. "
                    "Better light or a faster shutter reduces blur.")
    return tips


def advise_job(result: AnalysisResult) -> dict:
    per = {t.track_id: advise_track(t) for t in result.tracks}
    per = {k: v for k, v in per.items() if v}
    unread = [t for t in result.tracks if t.match.fused.known_count == 0]
    small = sum(1 for t in unread if t.frames_with_plate and t.max_plate_width_px is not None and t.max_plate_width_px < MIN_PLATE_PX)
    never = sum(1 for t in unread if t.frames_with_plate == 0)
    summary: list[str] = []
    if unread:
        summary.append(f"{len(unread)} of {len(result.tracks)} vehicles had no readable plate.")
    if small:
        summary.append(f"{small} of them had a plate under {MIN_PLATE_PX} px wide: the camera was too far away or the resolution too low for those plates.")
    if never:
        summary.append(f"{never} of them never had a plate located at all.")
    return {"tracks": per, "summary": summary}
