"""Agency tools: what each agency is told to do with a confirmed match, and a DRAFT e-challan for document violations.

Rules this module keeps:
- Actions are suggested only for a "match". An ambiguous result gets a "verify manually" note and nothing else; a refusal gets nothing.
- Everything is driven by the registry flags. The demo registry is synthetic, so the flags are demonstration data, not real records.
- The challan is a DRAFT for an officer to check and complete. It is not an official e-challan, has no fine amount, is not submitted anywhere,
  and says so on every page.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from .schemas import AnalysisResult, Candidate, MatchResult, TrackAnalysis

DOC_FLAGS = {
    "insurance_expired": "Motor insurance is recorded as expired",
    "puc_expired": "Pollution-under-control certificate is recorded as expired",
}
CHALLAN_AGENCIES = {"police", "morth_nhai"}
VERIFY = "Check the registry record, the vehicle and the video before acting; this is a lead, not a finding."


def _action(kind: str, title: str, detail: str, challan: bool = False) -> dict:
    return {"kind": kind, "title": title, "detail": detail, "challan": challan}


def suggest(dept: str, match: MatchResult) -> list[dict]:
    """Suggested next steps for one vehicle, from its match and its agency."""
    if match.status == "ambiguous":
        return [_action("verify", "Several registry entries fit", "Do not act on any one of them until a person has checked the plate against the video.")]
    if match.status != "match" or not match.candidates:
        return []
    top: Candidate = match.candidates[0]
    docs = [f for f in top.flags if f in DOC_FLAGS]
    stolen = "stolen" in top.flags
    out: list[dict] = []
    if stolen:
        if dept == "police":
            out.append(_action("alert", "Registry marks this vehicle as stolen",
                               "Confirm against the live national records and the FIR before any stop. " + VERIFY))
        else:
            out.append(_action("refer", "Registry marks this vehicle as stolen", "This is for the police. Pass it on through your control room; do not act on it yourself. " + VERIFY))
    if docs:
        listed = "; ".join(DOC_FLAGS[f] for f in docs)
        if dept in CHALLAN_AGENCIES:
            out.append(_action("document", "Document violation lead", f"{listed}. A draft e-challan can be prepared for an officer to check and complete.", challan=True))
        else:
            out.append(_action("note", "Document status noted", f"{listed}. Enforcement belongs to the transport authorities; this is recorded for information."))
    if not out:
        out.append(_action("clear", "No flags on this registry record", "The matched vehicle has no stolen or document flag. Nothing further is suggested."))
    return out


def actions_for(result: AnalysisResult) -> dict[int, list[dict]]:
    return {t.track_id: suggest(result.department, t.match) for t in result.tracks if suggest(result.department, t.match)}


def challan_available(dept: str, match: MatchResult) -> bool:
    return any(a["challan"] for a in suggest(dept, match)) and dept in CHALLAN_AGENCIES


def render_challan(result: AnalysisResult, track: TrackAnalysis, job_dir: Path | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .config import get_department

    top = track.match.candidates[0]
    docs = [DOC_FLAGS[f] for f in top.flags if f in DOC_FLAGS]
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=14)
    muted = ParagraphStyle("m", parent=body, fontSize=8.5, leading=11.5, textColor=colors.HexColor("#5f6368"))
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=17, spaceAfter=2)
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11, spaceBefore=12, spaceAfter=4)
    ref = f"DRAFT-{result.job_id}-{track.track_id}"
    t = lambda x: escape(str(x)).encode("latin-1", "replace").decode("latin-1")  # noqa: E731

    def img(name, max_w, max_h):
        if job_dir is None or not name or not (job_dir / name).exists():
            return None
        try:
            from PIL import Image as PILImage

            im = PILImage.open(job_dir / name).convert("RGB")
            iw, ih = im.size
            k = min(max_w / iw, max_h / ih)
            im.thumbnail((1200, 1200))
            buf = BytesIO()
            im.save(buf, "JPEG", quality=82)
            buf.seek(0)
            return Image(buf, width=iw * k, height=ih * k)
        except Exception:  # noqa: BLE001
            return None

    agency = get_department(result.department).name
    story = [Paragraph("DRAFT e-challan: for an officer to check and complete", h1),
             Paragraph(f"<b>Not an official e-challan.</b> Prepared from the demonstration registry (synthetic data). Nothing has been sent, filed or charged. Reference {t(ref)}.", muted),
             Spacer(1, 8)]
    rows = [["Vehicle plate", Paragraph(f"<font name='Courier-Bold' size='13'>{t(track.match.fused.display)}</font> "
                                        f"(read from video; registry plate {t(top.plate)})", body)],
            ["Registry record", Paragraph(f"{t(top.make)} {t(top.model)}, {t(top.colour)}, {t(top.body_type)} (entry {t(top.reg_id)}, match confidence {top.confidence:.2f})", body)],
            ["Issuing agency", Paragraph(t(agency), body)],
            ["Recorded violation(s)", Paragraph("<br/>".join(f"- {t(d)}" for d in docs), body)],
            ["Place of observation", ""], ["Date and time of observation", Paragraph(t(result.created_at or "to be entered by the officer"), body)],
            ["Fine amount", Paragraph("To be set by the issuing officer under the applicable rules.", body)],
            ["Officer name and ID", ""], ["Officer's check of the registry record", Paragraph("[ ] checked    [ ] not confirmed", body)]]
    tb = Table(rows, colWidths=[52 * mm, 118 * mm], rowHeights=None)
    tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b8bcc2")), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f5f7")),
                            ("FONTSIZE", (0, 0), (0, -1), 9), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [tb, Paragraph("Evidence", h3)]
    shots = [i for i in (img(track.evidence_frame, 105 * mm, 62 * mm), img(track.plate_crops[0] if track.plate_crops else None, 60 * mm, 22 * mm)) if i]
    if shots:
        story.append(Table([shots], hAlign="LEFT"))
    story += [Paragraph(f"Video: {t(result.source_filename or result.job_id)}. Video SHA-256: <font name='Courier' size='7'>{t(result.source_sha256)}</font>. "
                        f"Analysis case {t(result.job_id)}, vehicle {track.track_id}.", muted),
              Paragraph("How sure is the plate", h3),
              Paragraph(f"{track.match.fused.known_count} of 10 plate characters were read; the others are unknown and were not guessed. "
                        + (f"A second, independent reader {t(track.second_reader.verdict)} with the plate. " if track.second_reader else "")
                        + "The registry flags are demonstration data. The officer must confirm the plate on the video and the vehicle's document status against the live "
                          "records before this is used.", body)]

    def mark(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 70)
        canvas.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.10))
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "DRAFT")
        canvas.restoreState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5f6368"))
        canvas.drawString(15 * mm, 9 * mm, f"{ref}  -  draft, not an official document")

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=16 * mm,
                      title=f"Draft e-challan {ref}", author="Netra").build(story, onFirstPage=mark, onLaterPages=mark)
    return buf.getvalue()
