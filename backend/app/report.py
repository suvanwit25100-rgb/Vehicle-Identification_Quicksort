"""Self-contained HTML report: frames used, characters per frame with confidence, and reasoning per match."""

import base64
from html import escape
from pathlib import Path

from .schemas import AnalysisResult, TrackAnalysis

STATUS_LABEL = {
    "match": "Match",
    "ambiguous": "Ambiguous - verify manually",
    "no_confident_match": "No confident match",
    "insufficient_evidence": "Insufficient evidence",
}

CSS = """
:root{--bg:#fff;--fg:#1a1b1e;--muted:#5f6368;--rule:#d5d7da;--ok:#1b6e3c;--warn:#9a6700;--bad:#a4281b;--soft:#f4f5f7}
*{box-sizing:border-box}body{font:14px/1.5 system-ui,sans-serif;color:var(--fg);background:var(--bg);margin:0;padding:32px;max-width:960px;margin-inline:auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-top:2px solid var(--fg);padding-top:10px}
h3{font-size:14px;margin:18px 0 6px}.muted{color:var(--muted)}.mono{font-family:ui-monospace,Menlo,monospace}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border:1px solid var(--rule);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}.slots{display:flex;gap:4px;margin:8px 0}
.slot{width:44px;border:1px solid var(--rule);text-align:center;padding:4px 0}.slot b{display:block;font:600 20px ui-monospace,Menlo,monospace}
.slot.unk{background:#fff3f1;border-color:var(--bad)}.slot.unk b{color:var(--bad)}.slot small{color:var(--muted)}
.banner{padding:8px 12px;border-left:4px solid;margin:8px 0;background:var(--soft)}
.banner.match{border-color:var(--ok)}.banner.ambiguous,.banner.insufficient_evidence{border-color:var(--warn)}.banner.no_confident_match{border-color:var(--bad)}
img.crop{height:56px;border:1px solid var(--rule);margin-right:6px}ul{margin:4px 0;padding-left:20px}
.flag{color:var(--bad);font-weight:600}.foot{margin-top:32px;color:var(--muted);font-size:12px;border-top:1px solid var(--rule);padding-top:10px}
@media print{body{padding:0}h2{break-after:avoid}table,.slots{break-inside:avoid}}
"""


def _slots_html(track: TrackAnalysis) -> str:
    cells = []
    for s in track.match.fused.slots:
        cls = "slot" if s.char else "slot unk"
        cells.append(f'<div class="{cls}"><b>{escape(s.char or "?")}</b><small>{s.confidence:.2f}</small></div>')
    return f'<div class="slots">{"".join(cells)}</div>'


def _crop_img(job_dir: Path | None, name: str) -> str:
    if job_dir is None or not (job_dir / name).exists():
        return ""
    data = base64.b64encode((job_dir / name).read_bytes()).decode()
    return f'<img class="crop" alt="plate crop {escape(name)}" src="data:image/jpeg;base64,{data}">'


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
    if track.merged_from:
        ids = ", ".join(str(i) for i in track.merged_from)
        out.append(f'<p class="muted">Merged with track(s) {ids}: their plates agree on 6 or more characters and clash on none.</p>')
    out.append(f'<div class="banner {m.status}"><b>{STATUS_LABEL[m.status]}.</b> {escape(m.message)}</div>')
    out.append("<h3>Recovered plate (fused across frames)</h3>")
    out.append(_slots_html(track))
    out.append(
        '<p class="muted">Positions marked ? could not be read reliably and are reported as unknown, never guessed. '
        f'Pattern: <span class="mono">{escape(m.pattern)}</span></p>'
    )
    if track.plate_crops:
        out.append("<h3>Sharpest plate crops used</h3>" + "".join(_crop_img(job_dir, n) for n in track.plate_crops))

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
    rows = []
    for fr in track.frame_reads:
        cells = "".join(
            f'<td class="mono">{escape(c.char)}<br><small class="muted">{c.conf:.2f}</small></td>' if c else '<td class="muted">-</td>'
            for c in fr.chars
        )
        rows.append(f"<tr><td>{fr.frame_id}</td><td>{fr.sharpness:.0f}</td>{cells}</tr>")
    head = "<tr><th>Frame</th><th>Sharpness</th>" + "".join(f"<th>{i}</th>" for i in range(1, 11)) + "</tr>"
    out.append(f"<table>{head}{''.join(rows)}</table>" if rows else '<p class="muted">No plate was located in any frame.</p>')
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


def render_report(result: AnalysisResult, job_dir: Path | None = None) -> str:
    shown = [t for t in result.tracks if is_readable(t)]
    unread = [t for t in result.tracks if not is_readable(t)]
    if not result.tracks:
        body = "<p>No vehicles were tracked in this clip.</p>"
    else:
        body = "\n".join(_track_html(t, job_dir) for t in shown) or "<p>No plate could be read for any vehicle in this clip.</p>"
        if unread:
            body += "\n" + _unread_html(unread)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Netra report {escape(result.job_id)}</title>
<style>{CSS}</style></head><body>
<h1>Netra analysis report</h1>
<p class="muted">Job <span class="mono">{escape(result.job_id)}</span> - department: {escape(result.department)} -
{result.frames_sampled} frames sampled - {len(result.tracks)} vehicle track(s)</p>
<p class="muted">Input SHA-256: <span class="mono">{escape(result.source_sha256)}</span></p>
{body}
<p class="foot">Confidence scores are uncalibrated estimates. Candidates are leads for an investigator to verify, not identifications.
Unknown characters are shown as ? and were not inferred.</p>
</body></html>"""
