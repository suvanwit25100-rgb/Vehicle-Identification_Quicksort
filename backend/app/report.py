"""Self-contained HTML report: frames used, characters per frame with confidence, and reasoning per match."""

import base64
from html import escape
from pathlib import Path

from .brains import brain_status
from .config import get_department
from .schemas import AnalysisResult, TrackAnalysis

STATUS_LABEL = {
    "match": "Match",
    "ambiguous": "Ambiguous - verify manually",
    "no_confident_match": "No confident match",
    "insufficient_evidence": "Insufficient evidence",
}
VERDICT_TEXT = {
    "agrees": "agrees with the fused plate",
    "disagrees": "disagrees with the fused plate - verify manually",
    "inconclusive": "inconclusive (too little to compare)",
}

CSS = """
:root{--bg:#fff;--fg:#1a1b1e;--muted:#5f6368;--rule:#d5d7da;--ok:#1b6e3c;--warn:#9a6700;--bad:#a4281b;--soft:#f4f5f7}
*{box-sizing:border-box}body{font:14px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);margin:0;padding:32px;max-width:960px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-top:2px solid var(--fg);padding-top:10px}
h3{font-size:14px;margin:18px 0 6px}.muted{color:var(--muted)}.mono{font-family:ui-monospace,Menlo,monospace}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border:1px solid var(--rule);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}.slots{display:flex;gap:4px;margin:8px 0}
.slot{width:44px;border:1px solid var(--rule);text-align:center;padding:4px 0}.slot b{display:block;font:600 20px ui-monospace,Menlo,monospace}
.slot.absent{border-style:dashed;opacity:.6}.slot.unk{background:#fff3f1;border-color:var(--bad)}.slot.unk b{color:var(--bad)}.slot small{color:var(--muted)}
.banner{padding:8px 12px;border-left:4px solid;margin:8px 0;background:var(--soft)}
.banner.match{border-color:var(--ok)}.banner.ambiguous,.banner.insufficient_evidence{border-color:var(--warn)}.banner.no_confident_match{border-color:var(--bad)}
img.crop{height:56px;border:1px solid var(--rule);margin-right:6px}img.veh{height:130px;border:1px solid var(--rule);margin-right:8px}
img.ev{max-width:100%;height:auto;border:1px solid var(--rule);margin:6px 0}ul{margin:4px 0;padding-left:20px}
.flag{color:var(--bad);font-weight:600}.foot{margin-top:32px;color:var(--muted);font-size:12px;border-top:1px solid var(--rule);padding-top:10px}
.second{padding:6px 10px;border:1px solid var(--rule);background:var(--soft);margin:8px 0}.second.agrees{border-color:var(--ok)}.second.disagrees{border-color:var(--bad)}
@media print{body{padding:0}h2{break-after:avoid}table,.slots,img{break-inside:avoid}}
"""


def _slots_html(track: TrackAnalysis) -> str:
    cells = []
    for s in track.match.fused.slots:
        cls = "slot absent" if s.char == "-" else "slot" if s.char else "slot unk"
        shown = "-" if s.char == "-" else (s.char or "?")
        cells.append(f'<div class="{cls}"><b>{escape(shown)}</b><small>{"none" if s.char == "-" else f"{s.confidence:.2f}"}</small></div>')
    return f'<div class="slots">{"".join(cells)}</div>'


def _img(job_dir: Path | None, name: str | None, cls: str, alt: str) -> str:
    if job_dir is None or not name or not (job_dir / name).exists():
        return ""
    data = base64.b64encode((job_dir / name).read_bytes()).decode()
    return f'<img class="{cls}" alt="{escape(alt)}" src="data:image/jpeg;base64,{data}">'


def _crop_img(job_dir: Path | None, name: str) -> str:
    return _img(job_dir, name, "crop", f"plate crop {name}")


def _top(dist: dict[str, float] | None) -> str:
    if not dist:
        return "unknown"
    k = max(dist, key=dist.get)
    return f"{escape(k)} ({dist[k]:.2f})"


def _track_html(track: TrackAnalysis, job_dir: Path | None) -> str:
    m = track.match
    out = [f"<h2>Vehicle track {track.track_id} ({escape(track.vehicle_label)})</h2>"]
    out.append(
        f'<p class="muted">Seen in {track.frames_seen} sampled frames; plate located in {track.frames_with_plate}. '
        f"Detected colour: {_top(track.colour)}. Detected body type: {_top(track.body_type)}.</p>"
    )
    if track.plate_layout == "two-row":
        out.append('<p class="muted">Two-row plate (typical of two-wheelers): each row was read as its own line, then joined.</p>')
    if track.merged_from:
        ids = ", ".join(str(i) for i in track.merged_from)
        out.append(f'<p class="muted">Merged with track(s) {ids}: their plates agree on 6 or more characters and clash on none.</p>')
    media = _img(job_dir, track.vehicle_crop, "veh", f"vehicle {track.track_id}")
    if media:
        out.append(f"<p>{media}</p>")
    out.append(f'<div class="banner {m.status}"><b>{STATUS_LABEL[m.status]}.</b> {escape(m.message)}</div>')
    out.append("<h3>Recovered plate (fused across frames)</h3>")
    out.append(_slots_html(track))
    out.append(
        '<p class="muted">Positions marked ? could not be read reliably and are reported as unknown, never guessed. '
        f'Pattern: <span class="mono">{escape(m.fused.display)}</span></p>'
    )
    s = track.second_reader
    if s:
        reading = escape(s.reading) if s.reading else "nothing readable"
        out.append(f'<div class="second {s.verdict}"><b>Second reader</b> ({escape(s.reader)}) read '
                   f'<span class="mono">{reading}</span>: {VERDICT_TEXT[s.verdict]}'
                   f' ({s.agree} characters agree, {s.clash} clash). It never changes the fused plate.</div>')
    if track.plate_crops:
        out.append("<h3>Sharpest plate crops used</h3>" + "".join(_crop_img(job_dir, n) for n in track.plate_crops))
    ev = _img(job_dir, track.evidence_frame, "ev", f"frame the plate of track {track.track_id} was read from")
    if ev:
        out.append("<h3>Frame the plate was read from</h3>" + ev
                   + '<p class="muted">The vehicle is outlined in white and the plate in red.</p>')

    if m.candidates:
        out.append("<h3>Ranked candidates</h3>")
        for rank, c in enumerate(m.candidates, 1):
            flags = f' <span class="flag">[{escape(", ".join(c.flags))}]</span>' if c.flags else ""
            out.append(
                f'<p><b>#{rank} <span class="mono">{escape(c.plate)}</span></b> - confidence {c.confidence:.2f}{flags}<br>'
                f'<span class="muted">{escape(c.make)} {escape(c.model)}, {escape(c.colour)}, {escape(c.body_type)} '
                f"(registry {escape(c.reg_id)})</span></p><ul>"
                + "".join(f"<li>{escape(r)}</li>" for r in c.reasons)
                + "</ul>"
            )

    out.append("<h3>Characters read per frame</h3>")
    has_raw = any(fr.raw is not None for fr in track.frame_reads)
    rows = []
    for fr in track.frame_reads:
        cells = "".join(
            f'<td class="mono">{escape(c.char)}<br><small class="muted">{c.conf:.2f}</small></td>' if c else '<td class="muted">-</td>'
            for c in fr.chars
        )
        raw = f'<td class="mono">{escape(fr.raw or "")}</td>' if has_raw else ""
        rows.append(f"<tr><td>{fr.frame_id}</td><td>{fr.sharpness:.0f}</td>{raw}{cells}</tr>")
    head = ("<tr><th>Frame</th><th>Sharpness</th>" + ("<th>Whole read</th>" if has_raw else "")
            + "".join(f"<th>{i}</th>" for i in range(1, 11)) + "</tr>")
    out.append(f"<table>{head}{''.join(rows)}</table>" if rows else '<p class="muted">No plate was located in any frame.</p>')
    if has_raw:
        out.append('<p class="muted">"Whole read" is the plate exactly as the reader returned it, before it was fitted to the ten slots.</p>')
    return "\n".join(out)


def is_readable(track: TrackAnalysis) -> bool:
    return track.match.fused.known_count > 0


def _unread_html(tracks: list[TrackAnalysis]) -> str:
    rows = "".join(
        f"<tr><td>{t.track_id}</td><td>{escape(t.vehicle_label)}</td><td>{t.frames_seen}</td>"
        f"<td>{escape(t.plate_note or 'No readable plate characters.')}</td></tr>"
        for t in tracks
    )
    return (f"<h2>Vehicles without a readable plate ({len(tracks)})</h2>"
            "<table><tr><th>Track</th><th>Vehicle</th><th>Frames seen</th><th>Why no plate was read</th></tr>"
            f"{rows}</table>")


def _provenance_html(result: AnalysisResult) -> str:
    models = "".join(
        f"<tr><td>{escape(b['id'].replace('_', ' '))}</td><td>{escape(b['role'])}</td><td>{escape(b['source'])}</td><td>{escape(b['license'])}</td></tr>"
        for b in brain_status())
    try:
        d = get_department(result.department)
        dept = (f"<p>Agency settings used: needs at least {d.min_known_chars} readable characters, a score of {d.match_threshold:.2f} or more, "
                f"and at most {d.max_known_mismatches} mismatching known character(s).</p>")
    except KeyError:
        dept = ""
    return ("<h2>Models and settings</h2>" + dept
            + "<table><tr><th>Part</th><th>Job</th><th>Model</th><th>Licence</th></tr>" + models + "</table>"
            + '<p class="muted">All models are pretrained and were used as published. The list shows what is installed now.</p>')


def render_report(result: AnalysisResult, job_dir: Path | None = None) -> str:
    shown = [t for t in result.tracks if is_readable(t)]
    unread = [t for t in result.tracks if not is_readable(t)]
    if not result.tracks:
        body = "<p>No vehicles were tracked in this clip.</p>"
    else:
        body = "\n".join(_track_html(t, job_dir) for t in shown) or "<p>No plate could be read for any vehicle in this clip.</p>"
        if unread:
            body += "\n" + _unread_html(unread)
    bits = [f"Job <span class='mono'>{escape(result.job_id)}</span>", f"department: {escape(result.department)}",
            f"{result.frames_sampled} frames sampled", f"{len(result.tracks)} vehicle track(s)"]
    if result.created_at:
        bits.append(f"analysed {escape(result.created_at)}")
    if result.processing_seconds is not None:
        bits.append(f"{result.processing_seconds:.0f} s to process")
    meta2 = []
    if result.source_filename:
        meta2.append(f"File: {escape(result.source_filename)}")
    if result.video:
        v = result.video
        meta2.append(f"{v.width}x{v.height} at {v.fps:g} fps" + (f", {v.duration_s:g} s" if v.duration_s else ""))
    if result.body_model:
        meta2.append(f"Body type: {escape(result.body_model)}")
    if result.second_reader_used:
        meta2.append(f"Second reader: {escape(result.second_reader_used)}")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Netra report {escape(result.job_id)}</title>
<style>{CSS}</style></head><body>
<h1>Netra analysis report</h1>
<p class="muted">{" - ".join(bits)}</p>
<p class="muted">{" - ".join(meta2)}</p>
<p class="muted">Input SHA-256: <span class="mono">{escape(result.source_sha256)}</span></p>
{body}
{_provenance_html(result)}
<p class="foot">Confidence scores are uncalibrated estimates. Candidates are leads for an investigator to verify, not identifications.
Unknown characters are shown as ? and were not inferred.</p>
</body></html>"""
