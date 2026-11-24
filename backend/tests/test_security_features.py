"""Two-factor sign-in (authenticator app codes), password reset by email, live alerts."""
import base64
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import mailer, main, totp

from .test_case_export import client, stored_case  # noqa: F401  (fixtures)
from .test_officer_portal import KEY, PW, a_report, bearer, make_officer  # noqa: F401


@pytest.fixture(autouse=True)
def _reset():
    main.limiter.reset()
    yield
    main.limiter.reset()


def now_code(secret):
    return totp.code_at(secret.replace(" ", ""), int(time.time() // totp.STEP))


def enrol(client, username="asha"):
    """An officer with two-factor on. Returns (session token, secret, recovery codes)."""
    tok = make_officer(client, username)
    s = client.post("/api/officer/2fa/setup", headers=bearer(tok)).json()
    secret = s["secret"].replace(" ", "")
    r = client.post("/api/officer/2fa/enable", json={"code": now_code(secret)}, headers=bearer(tok))
    assert r.status_code == 200, r.text
    return tok, secret, r.json()["recovery_codes"]


# ---------------------------------------------------------------- the code maths
def test_totp_matches_the_rfc_6238_reference_values():
    secret = base64.b32encode(b"12345678901234567890").decode()
    for t, want in ((59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (1234567890, "89005924"), (2000000000, "69279037")):
        assert totp.code_at(secret, t // 30, digits=8) == want
    assert totp.code_at(secret, 59 // 30) == "287082"                       # the same value as the app shows: the last 6 digits


def test_a_code_is_accepted_once_with_a_little_clock_drift_and_not_replayed():
    secret = totp.new_secret()
    t = 1_700_000_000
    step = int(t // 30)
    code = totp.code_at(secret, step)
    assert totp.verify(secret, code, at=t) == step
    assert totp.verify(secret, code, last_step=step, at=t) is None              # replay of a used step
    assert totp.verify(secret, totp.code_at(secret, step - 1), at=t) == step - 1  # one step of drift is fine
    assert totp.verify(secret, totp.code_at(secret, step - 3), at=t) is None     # three is not
    assert totp.verify(secret, "12345", at=t) is None and totp.verify(secret, "abcdef", at=t) is None


def test_the_otpauth_link_and_qr_are_what_the_apps_expect():
    uri = totp.otpauth_uri("ABCDEFGH", "asha")
    assert uri.startswith("otpauth://totp/ExLex:asha?secret=ABCDEFGH&issuer=ExLex") and "period=30" in uri and "digits=6" in uri
    svg = totp.qr_svg(uri)
    assert svg is None or svg.lstrip().startswith("<svg")


# ---------------------------------------------------------------- sign-in with a second step
def test_enrolment_needs_a_valid_code_and_gives_eight_recovery_codes(client):
    tok = make_officer(client)
    setup = client.post("/api/officer/2fa/setup", headers=bearer(tok)).json()
    assert setup["uri"].startswith("otpauth://") and (setup["qr"] is None or setup["qr"].startswith("data:image/svg+xml;base64,"))
    assert client.post("/api/officer/2fa/enable", json={"code": "000000"}, headers=bearer(tok)).status_code == 422
    assert client.get("/api/officer/me", headers=bearer(tok)).json()["two_factor"] is False          # not on until confirmed
    ok = client.post("/api/officer/2fa/enable", json={"code": now_code(setup["secret"])}, headers=bearer(tok)).json()
    assert len(ok["recovery_codes"]) == 8 and len(set(ok["recovery_codes"])) == 8
    assert client.get("/api/officer/me", headers=bearer(tok)).json()["two_factor"] is True
    assert client.post("/api/officer/2fa/setup", headers=bearer(tok)).status_code == 409             # already on


def test_with_two_factor_on_a_password_alone_gives_no_session(client):
    _, secret, _ = enrol(client)
    first = client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()
    assert first["needs_2fa"] is True and "token" not in first
    assert client.post("/api/officer/login/2fa", json={"challenge": first["challenge"], "code": "000000"}).status_code == 401
    # (the last used step is remembered, so wait out the replay guard by using the next step's code)
    nxt = totp.code_at(secret, int(time.time() // 30) + 1)
    done = client.post("/api/officer/login/2fa", json={"challenge": first["challenge"], "code": nxt})
    assert done.status_code == 200 and client.get("/api/officer/me", headers=bearer(done.json()["token"])).json()["username"] == "asha"
    assert client.post("/api/officer/login/2fa", json={"challenge": first["challenge"], "code": nxt}).status_code == 401      # a challenge works once


def test_five_wrong_codes_end_the_sign_in(client):
    enrol(client)
    ch = client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()["challenge"]
    for _ in range(5):
        assert client.post("/api/officer/login/2fa", json={"challenge": ch, "code": "111111"}).status_code == 401
    assert client.post("/api/officer/login/2fa", json={"challenge": ch, "code": "222222"}).status_code == 401      # the challenge is gone
    assert client.post("/api/officer/login/2fa", json={"challenge": "nonsense", "code": "000000"}).status_code == 401


def test_a_recovery_code_works_once(client):
    _, _, recovery = enrol(client)
    ch = client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()["challenge"]
    assert client.post("/api/officer/login/2fa", json={"challenge": ch, "code": recovery[0]}).status_code == 200
    ch2 = client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()["challenge"]
    assert client.post("/api/officer/login/2fa", json={"challenge": ch2, "code": recovery[0]}).status_code == 401      # used up
    ch3 = client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()["challenge"]
    assert client.post("/api/officer/login/2fa", json={"challenge": ch3, "code": recovery[1]}).status_code == 200
    me_left = client.get("/api/officer/team/all", headers=KEY).json()[0]["recovery_left"]
    assert me_left == 6


def test_turning_it_off_needs_the_password_and_a_code_and_an_admin_can_reset_it(client):
    tok, secret, _ = enrol(client)
    h = bearer(tok)
    assert client.post("/api/officer/2fa/disable", json={"password": "wrong", "code": now_code(secret)}, headers=h).status_code == 401
    assert client.post("/api/officer/2fa/disable", json={"password": PW, "code": "000000"}, headers=h).status_code == 401
    # lost phone: an admin resets it, which signs the officer out and lets them sign in with the password again
    oid = client.get("/api/officer/team/all", headers=KEY).json()[0]["id"]
    assert client.patch(f"/api/officer/team/{oid}", json={"reset_2fa": True}, headers=KEY).json()["two_factor"] is False
    assert client.get("/api/officer/me", headers=h).status_code == 401
    assert "token" in client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()
    assert ("key", "team.update") in [(a["actor"], a["action"]) for a in client.get("/api/officer/audit", headers=KEY).json()]


def test_the_master_key_has_no_second_step_and_cannot_enrol(client):
    assert client.post("/api/officer/2fa/setup", headers=KEY).status_code == 409
    assert "token" in client.post("/api/officer/login", json={"key": main.OFFICER_KEY}).json()


# ---------------------------------------------------------------- password reset by email
def officer_with_email(client, email="asha@example.com"):
    make_officer(client)
    oid = client.get("/api/officer/team/all", headers=KEY).json()[0]["id"]
    assert client.patch(f"/api/officer/team/{oid}", json={"email": email}, headers=KEY).json()["email"] == email
    return oid


def reset_token(client):
    body = client.get("/api/officer/mail", headers=KEY).json()["messages"][0]["body"]
    return body.split("/officer/#/reset/")[1].split()[0]


def test_forgot_answers_the_same_for_everyone_and_queues_mail_only_when_there_is_an_account(client):
    officer_with_email(client)
    a = client.post("/api/officer/password/forgot", json={"who": "asha"}).json()
    b = client.post("/api/officer/password/forgot", json={"who": "nobody@nowhere.com"}).json()
    assert a == b                                                                                  # cannot be used to find accounts
    mail = client.get("/api/officer/mail", headers=KEY).json()
    assert mail["smtp_configured"] is False and len(mail["messages"]) == 1
    m = mail["messages"][0]
    assert m["recipient"] == "asha@example.com" and m["state"].startswith("queued") and "nothing was sent" in m["state"]
    assert "/officer/#/reset/" in m["body"] and "30 minutes" in m["body"]


def test_reset_sets_the_new_password_once_signs_out_and_is_audited(client):
    tok_before = None
    officer_with_email(client)
    old = client.post("/api/officer/login", json={"username": "asha", "password": PW}).json()["token"]
    client.post("/api/officer/password/forgot", json={"who": "asha@example.com"})
    token = reset_token(client)
    assert client.post("/api/officer/password/reset", json={"token": token, "new": "weak"}).status_code == 422
    assert client.post("/api/officer/password/reset", json={"token": token, "new": "Brand-New-Pass-9"}).status_code == 200
    assert client.get("/api/officer/me", headers=bearer(old)).status_code == 401                    # old sessions end
    assert client.post("/api/officer/login", json={"username": "asha", "password": PW}).status_code == 401
    assert client.post("/api/officer/login", json={"username": "asha", "password": "Brand-New-Pass-9"}).status_code == 200
    assert client.post("/api/officer/password/reset", json={"token": token, "new": "Another-Pass-77"}).status_code == 410    # single use
    assert client.post("/api/officer/password/reset", json={"token": "bogus", "new": "Another-Pass-77"}).status_code == 410
    actions = [a["action"] for a in client.get("/api/officer/audit", headers=KEY).json()]
    assert "password.reset_requested" in actions and "password.reset_done" in actions


def test_an_expired_link_and_a_switched_off_account_do_not_reset(client, tmp_path):
    oid = officer_with_email(client)
    client.post("/api/officer/password/forgot", json={"who": "asha"})
    token = reset_token(client)
    con = sqlite3.connect(tmp_path / "netra.db")
    con.execute("UPDATE resets SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds"),))
    con.commit(); con.close()
    assert client.post("/api/officer/password/reset", json={"token": token, "new": "Brand-New-Pass-9"}).status_code == 410
    client.patch(f"/api/officer/team/{oid}", json={"active": False}, headers=KEY)
    before = len(client.get("/api/officer/mail", headers=KEY).json()["messages"])
    client.post("/api/officer/password/forgot", json={"who": "asha"})
    assert len(client.get("/api/officer/mail", headers=KEY).json()["messages"]) == before


def test_the_mail_queue_is_admin_only_and_requests_are_limited(client):
    tok = make_officer(client)
    assert client.get("/api/officer/mail", headers=bearer(tok)).status_code == 403
    codes = [client.post("/api/officer/password/forgot", json={"who": "x"}).status_code for _ in range(7)]
    assert codes[0] == 200 and codes[-1] == 429


def test_with_smtp_configured_the_mail_is_really_sent_and_a_failure_is_reported(client, monkeypatch):
    sent = []
    monkeypatch.setenv("EXLEX_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EXLEX_SMTP_FROM", "exlex@example.com")
    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda host, port, timeout=0: FakeSMTP(sent))
    officer_with_email(client)
    client.post("/api/officer/password/forgot", json={"who": "asha"})
    m = client.get("/api/officer/mail", headers=KEY).json()
    assert m["smtp_configured"] is True and m["messages"][0]["state"] == "sent"
    assert sent and sent[0]["To"] == "asha@example.com" and "reset" in sent[0]["Subject"].lower()
    monkeypatch.setattr(mailer.smtplib, "SMTP", lambda *a, **k: (_ for _ in ()).throw(OSError("no route")))
    client.post("/api/officer/password/forgot", json={"who": "asha@example.com"})
    assert client.get("/api/officer/mail", headers=KEY).json()["messages"][0]["state"] == "failed: OSError"


class FakeSMTP:
    def __init__(self, sent):
        self.sent = sent

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, u, p):
        pass

    def send_message(self, msg):
        self.sent.append(msg)


def test_email_addresses_are_validated(client):
    tok = make_officer(client)
    assert client.post("/api/officer/email", json={"email": "not-an-email"}, headers=bearer(tok)).status_code == 422
    assert client.post("/api/officer/email", json={"email": "Asha@Example.com"}, headers=bearer(tok)).json() == {"email": "asha@example.com"}
    assert client.post("/api/officer/team", json={"username": "bad", "name": "Bad Mail", "role": "officer", "password": PW, "email": "nope"}, headers=KEY).status_code == 422


# ---------------------------------------------------------------- live alerts
def test_alerts_arrive_for_new_reports_and_respect_agencies_and_since(client, tmp_path):
    tok = make_officer(client)
    first = client.get("/api/officer/alerts", headers=bearer(tok)).json()
    assert first == {"alerts": [], "latest": 0}
    cid = a_report(client, tmp_path)                                         # a flag: police
    got = client.get("/api/officer/alerts?since=0", headers=bearer(tok)).json()
    assert [a["kind"] for a in got["alerts"]] == ["report"] and cid in got["alerts"][0]["link"] and got["latest"] == got["alerts"][0]["id"]
    assert client.get(f"/api/officer/alerts?since={got['latest']}", headers=bearer(tok)).json()["alerts"] == []
    client.post("/api/officer/team", json={"username": "bor", "name": "Bor Der", "role": "officer", "password": PW, "agencies": ["bsf"]}, headers=KEY)
    bsf = client.post("/api/officer/login", json={"username": "bor", "password": PW}).json()["token"]
    assert client.get("/api/officer/alerts?since=0", headers=bearer(bsf)).json()["alerts"] == []        # a police report is not for BSF
    assert client.get("/api/officer/alerts").status_code == 401


def test_a_watchlist_hit_in_a_new_analysis_raises_an_alert(client, tmp_path):
    from .test_watchlist import job

    client.post("/api/desk/watchlist", json={"plate": "UP14CA0914", "reason": "Stolen, FIR 12"}, headers=KEY)
    r = job("aaaaaaaaaaa1", "a.mp4", ["UP14CA0914", "MH12AB3456"])
    main._alert_watch_hits(r)
    alerts = client.get("/api/officer/alerts?since=0", headers=KEY).json()["alerts"]
    assert len(alerts) == 1 and alerts[0]["kind"] == "watchlist" and "exact" in alerts[0]["title"] and alerts[0]["link"] == "/console/?job=aaaaaaaaaaa1"
    assert "UP14CA0914" in alerts[0]["title"]
