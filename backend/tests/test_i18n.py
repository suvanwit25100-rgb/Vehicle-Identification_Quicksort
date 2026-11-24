"""Hindi and English: every English entry in the dictionary must still be a string the product really shows."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
APP = Path(__file__).resolve().parents[1] / "app"
DYNAMIC = re.compile(r"^Status changed to “.+”\.$")        # built from a status label at run time


def entries():
    src = (STATIC / "i18n.js").read_text()
    body = src[src.index("const HI = {"):src.index("const ATTRS")]
    pairs = re.findall(r'"((?:[^"\\]|\\.)+)":\s*"((?:[^"\\]|\\.)*)"', body)
    assert len(pairs) > 100
    return pairs


def corpus():
    files = list(STATIC.rglob("*.html")) + list(STATIC.rglob("*.js")) + [APP / "main.py", APP / "complaints.py", APP / "config.py", APP / "departments.yaml"]
    text = " ".join(f.read_text() for f in files if f.name != "i18n.js")
    return re.sub(r"\s+", " ", text.replace('\\"', '"').replace("\\u2019", "’"))


def test_every_translation_has_text_and_every_english_key_is_still_shown_somewhere():
    text = corpus()
    missing = []
    for en, hi in entries():
        assert hi.strip(), f"empty Hindi for {en!r}"
        key = re.sub(r"\s+", " ", en.replace('\\"', '"')).strip()
        if DYNAMIC.match(key):
            continue
        probe = key.lstrip(": ").strip()
        if probe not in text:
            missing.append(key)
    assert not missing, "dictionary entries that no page or server text contains any more: " + "; ".join(missing[:8])


def test_the_dynamic_status_sentences_cover_every_public_status_label():
    from app.main import PUBLIC_WORDS

    keys = {en for en, _ in entries()}
    for label, meaning in PUBLIC_WORDS.values():
        assert label in keys and meaning in keys, label
        assert f"Status changed to “{label}”." in keys, label


def test_the_citizen_pages_load_the_switch_before_the_page_script():
    for page in ("index.html", "report-issue/index.html", "status/index.html"):
        html = (STATIC / page).read_text()
        assert html.index("/i18n.js") < html.index("/ui.js"), page


def test_categories_and_agencies_are_covered():
    from app.complaints import CATEGORIES
    from app.config import load_departments

    keys = {en for en, _ in entries()}
    assert all(label in keys for label, _ in CATEGORIES.values())
    assert all(d.name in keys for d in load_departments().values())
