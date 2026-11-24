"""PDF version of the case report, built with reportlab (no browser needed). It carries the same facts as the HTML report:
the recovered plate with per-slot confidence, the second reader's verdict, the images used, ranked candidates with reasons,
unreadable vehicles, models, and the honesty notes. Unknown characters are shown as ? and nothing is inferred."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from .brains import brain_status
from .config import get_department
from .report import STATUS_LABEL, VERDICT_TEXT, is_readable
from .schemas import AnalysisResult, TrackAnalysis


MAX_FRAMES = 30


def available() -> bool:
    try:
        import reportlab  # noqa: F401
    except ImportError:
        return False
    return True


def _t(text) -> str:
    """Text safe for a core PDF font (Latin-1) and for reportlab's mini-markup."""
    return escape(str(text)).encode("latin-1", "replace").decode("latin-1")


def _top(dist) -> str:
    if not dist:
        return "unknown"
    k = max(dist, key=dist.get)
    return f"{k} ({dist[k]:.2f})"


def render_pdf(result: AnalysisResult, job_dir: Path | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=9.5, leading=13)
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#5f6368"), fontSize=8.5, leading=11.5)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=18, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontSize=10.5, spaceBefore=8, spaceAfter=3)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=9)
    width = A4[0] - 30 * mm

    def img(name, max_w, max_h):
        if job_dir is None or not name or not (job_dir / name).exists():
            return None
        try:
            from PIL import Image as PILImage

            im = PILImage.open(job_dir / name).convert("RGB")
            iw, ih = im.size
            k = min(max_w / iw, max_h / ih, 1.0 if iw > 400 else max_h / ih)
            dpi_px = 1.5 * max(iw * k, ih * k) / 72 * 150          # about 150 dpi at the printed size; bigger sources are shrunk
            if max(iw, ih) > dpi_px:
                im.thumbnail((int(dpi_px), int(dpi_px)))
            buf = BytesIO()
            im.save(buf, "JPEG", quality=82)
            buf.seek(0)
            return Image(buf, width=iw * k, height=ih * k)
        except Exception:  # noqa: BLE001 - an unreadable image is left out, not fatal
            return None

    def slots_table(track: TrackAnalysis):
        cells = [[], []]
        style = [("FONT", (0, 0), (-1, 0), "Courier-Bold", 15), ("FONT", (0, 1), (-1, 1), "Helvetica", 7), ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                 ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5d7da")), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i, s in enumerate(track.match.fused.slots):
            if s.char == "-":
                cells[0].append("-")
                cells[1].append("none")
            else:
                cells[0].append(s.char or "?")
                cells[1].append(f"{s.confidence:.2f}" if s.char else "unread")
            if not s.char:
                style += [("BACKGROUND", (i, 0), (i, 1), colors.HexColor("#fff3f1")), ("TEXTCOLOR", (i, 0), (i, 0), colors.HexColor("#a4281b"))]
        t = Table(cells, colWidths=[min(11 * mm, width / 10)] * 10, hAlign="LEFT")
        t.setStyle(TableStyle(style))
        return t

    story = []
    story.append(Paragraph("ExLex analysis report", h1))
    bits = [f"Job {_t(result.job_id)}", f"agency: {_t(result.department)}", f"{result.frames_sampled} frames sampled", f"{len(result.tracks)} vehicle track(s)"]
    if result.created_at:
        bits.append(f"analysed {_t(result.created_at)}")
    if result.processing_seconds is not None:
        bits.append(f"{result.processing_seconds:.0f} s to process")
    story.append(Paragraph(" - ".join(bits), muted))
    meta = []
    if result.source_filename:
        meta.append(f"File: {_t(result.source_filename)}")
    if result.video:
        v = result.video
        meta.append((f"{v.width}x{v.height} still image" if v.kind == "image" else f"{v.width}x{v.height} at {v.fps:g} fps" + (f", {v.duration_s:g} s" if v.duration_s else "")))
    if result.body_model:
        meta.append(f"Body type: {_t(result.body_model)}")
    if result.second_reader_used:
        meta.append(f"Second reader: {_t(result.second_reader_used)}")
    if meta:
        story.append(Paragraph(" - ".join(meta), muted))
    story.append(Paragraph(f"Input SHA-256: <font name='Courier'>{_t(result.source_sha256)}</font>", muted))

    shown = [t for t in result.tracks if is_readable(t)]
    unread = [t for t in result.tracks if not is_readable(t)]
    if not result.tracks:
        story.append(Paragraph("No vehicles were tracked in this clip.", body))
    elif not shown:
        story.append(Paragraph("No plate could be read for any vehicle in this clip.", body))

    for t in shown:
        m = t.match
        head = [Paragraph(f"Vehicle track {t.track_id} ({_t(t.vehicle_label)})", h2),
                Paragraph(f"Seen in {t.frames_seen} sampled frames; plate located in {t.frames_with_plate}. "
                          f"Detected colour: {_t(_top(t.colour))}. Detected body type: {_t(_top(t.body_type))}.", muted)]
        if t.plate_layout == "two-row":
            head.append(Paragraph("Two-row plate (typical of two-wheelers): each row was read as its own line, then joined.", muted))
        if t.merged_from:
            head.append(Paragraph(f"Merged with track(s) {', '.join(map(str, t.merged_from))}: their plates agree on 6 or more characters and clash on none.", muted))
        story.append(KeepTogether(head))
        veh = img(t.vehicle_crop, 55 * mm, 40 * mm)
        if veh:
            story += [Spacer(1, 4), veh]
        colour = {"match": "#1b6e3c", "ambiguous": "#9a6700", "insufficient_evidence": "#9a6700", "no_confident_match": "#a4281b"}[m.status]
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<font color='{colour}'><b>{STATUS_LABEL[m.status]}.</b></font> {_t(m.message)}", body))
        story.append(Paragraph("Recovered plate (fused across frames)", h3))
        story.append(slots_table(t))
        story.append(Paragraph(f"Positions marked ? could not be read reliably and are reported as unknown, never guessed. Pattern: "
                               f"<font name='Courier'>{_t(m.fused.display)}</font>", muted))
        if t.rto:
            r = t.rto
            story.append(Spacer(1, 3))
            story.append(Paragraph("<b>RTO code check</b> (public code list, a region lookup, not a registry match): " + _t(r["message"])
                                   + (f" Confidence {r['confidence']:.2f}." if r.get("confidence") is not None and r["status"] == "match" else ""), body))
        if t.second_reader:
            s = t.second_reader
            story.append(Spacer(1, 3))
            story.append(Paragraph(f"<b>Second reader</b> ({_t(s.reader)}) read <font name='Courier'>{_t(s.reading) or 'nothing readable'}</font>: "
                                   f"{_t(VERDICT_TEXT[s.verdict])} ({s.agree} characters agree, {s.clash} clash). It never changes the fused plate.", body))
        crops = [c for c in (img(n, 45 * mm, 16 * mm) for n in t.plate_crops[:3]) if c]
        if crops:
            story.append(Paragraph("Sharpest plate crops used", h3))
            story.append(Table([crops], hAlign="LEFT"))
        ev = img(t.evidence_frame, width, 85 * mm)
        if ev:
            story += [Paragraph("Frame the plate was read from", h3), ev,
                      Paragraph("The vehicle is outlined in white and the plate in red.", muted)]
        if m.candidates:
            story.append(Paragraph("Ranked candidates", h3))
            for rank, c in enumerate(m.candidates, 1):
                flags = f" <font color='#a4281b'>[{_t(', '.join(c.flags))}]</font>" if c.flags else ""
                story.append(KeepTogether([
                    Paragraph(f"<b>#{rank} <font name='Courier'>{_t(c.plate)}</font></b> - confidence {c.confidence:.2f}{flags}", body),
                    Paragraph(f"{_t(c.make)} {_t(c.model)}, {_t(c.colour)}, {_t(c.body_type)} (registry {_t(c.reg_id)})", muted),
                    Paragraph("Score parts: " + ", ".join(f"{k.replace('_', ' ')} {v:.2f}" for k, v in c.components.items()), muted),
                    *[Paragraph(f"- {_t(r)}", muted) for r in c.reasons]]))
                story.append(Spacer(1, 3))
        shown_frames = t.frame_reads[:MAX_FRAMES]
        more = f" (first {MAX_FRAMES} of {len(t.frame_reads)})" if len(t.frame_reads) > MAX_FRAMES else ""
        story.append(Paragraph(f"Characters read per frame, with confidence{more}", h3))
        story.append(Paragraph("Each cell is the character read in that frame; the small number under it is the reader's confidence (0 to 1). "
                               "A dash means nothing was read at that position in that frame.", muted))
        cs = ParagraphStyle("cell", parent=muted, fontName="Courier-Bold", fontSize=8.5, leading=9.5, alignment=1, textColor=colors.black)
        cs_lo = ParagraphStyle("celllo", parent=cs, textColor=colors.HexColor("#a4281b"))
        rows = [["Frame", "Sharp."] + [str(i) for i in range(1, 11)]]
        cell_style = []
        for r, fr in enumerate(shown_frames, 1):
            row_cells = [str(fr.frame_id), f"{fr.sharpness:.0f}"]
            for i, c in enumerate(fr.chars):
                if c is None:
                    row_cells.append("-")
                else:
                    low = c.conf < 0.5
                    row_cells.append(Paragraph(f"{_t(c.char)}<br/><font size='6' name='Helvetica'>{c.conf:.2f}</font>", cs_lo if low else cs))
            rows.append(row_cells)
        ft = Table(rows, hAlign="LEFT", colWidths=[14 * mm, 14 * mm] + [11 * mm] * 10, repeatRows=1)
        ft.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Courier", 7.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f5f7")),
                                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d5d7da")), ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(ft)
        story.append(Paragraph("Confidences in red are below 0.50.", muted))

    if unread:
        story.append(Paragraph(f"Vehicles without a readable plate ({len(unread)})", h2))
        rows = [["Track", "Vehicle", "Frames", "Why no plate was read"]] + [
            [str(t.track_id), t.vehicle_label, str(t.frames_seen), Paragraph(_t(t.plate_note or "No readable plate characters."), muted)] for t in unread]
        ut = Table(rows, hAlign="LEFT", colWidths=[14 * mm, 24 * mm, 16 * mm, width - 54 * mm], repeatRows=1)
        ut.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f5f7")),
                                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d5d7da")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(ut)

    story.append(Paragraph("Models and settings", h2))
    try:
        d = get_department(result.department)
        story.append(Paragraph(f"Agency settings used: needs at least {d.min_known_chars} readable characters, a score of {d.match_threshold:.2f} or more, "
                               f"and at most {d.max_known_mismatches} mismatching known character(s).", body))
    except KeyError:
        pass
    rows = [["Part", "Job", "Model", "Licence"]] + [[Paragraph(_t(b["id"].replace("_", " ")), muted), Paragraph(_t(b["role"]), muted),
                                                      Paragraph(_t(b["source"]), muted), Paragraph(_t(b["license"]), muted)] for b in brain_status()]
    mt = Table(rows, hAlign="LEFT", colWidths=[width * 0.16, width * 0.34, width * 0.3, width * 0.2], repeatRows=1)
    mt.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, 0), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f5f7")),
                            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d5d7da")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [mt, Paragraph("All models are pretrained and were used as published. The list shows what is installed now.", muted), Spacer(1, 10),
              Paragraph("Confidence scores are uncalibrated estimates. Candidates are leads for an investigator to verify, not identifications. "
                        "Unknown characters are shown as ? and were not inferred.", muted)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#5f6368"))
        canvas.drawString(15 * mm, 9 * mm, f"Case {result.job_id}")
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
                            title=f"Analysis report {result.job_id}", author="ExLex")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
