"""Officer accounts, sign-in sessions and the audit log.

How access works:
* The master officer key (EXLEX_OFFICER_KEY, or the key stored in data/officer_key.txt) signs in as an administrator.
  The admin can then create an account for each officer, so work is attributed to a person and the key can stay private.
* Passwords are stored as scrypt hashes with a per-account salt; sessions are random tokens of which only the hash is kept.
* Every action that changes something is written to the audit log with who did it. The log is append-only through this module.
"""

from __future__ import annotations

import hashlib
import json
import hmac
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import totp

ROLES = ("admin", "officer")
SESSION_HOURS = 12
MIN_PASSWORD = 10
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS officers (
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
        pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, last_login TEXT)""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, officer_id TEXT NOT NULL, username TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS challenges (
        token_hash TEXT PRIMARY KEY, officer_id TEXT NOT NULL, expires_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS resets (
        token_hash TEXT PRIMARY KEY, officer_id TEXT NOT NULL, expires_at TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS mail (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
        link TEXT, department TEXT)""",
    """CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL,
        action TEXT NOT NULL, target TEXT, detail TEXT)""",
]

KEY_IDENTITY = {"id": "key", "username": "key", "name": "Key holder", "role": "admin", "agencies": []}   # no agencies listed = all of them


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return salt.hex(), h.hex()


def check_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, h = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(h, hash_hex)


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if password.lower() == password or not any(c.isdigit() for c in password):
        return "Mix upper and lower case letters and include a digit."
    return None


def load_or_create_key(data_dir: Path, env_value: str | None) -> tuple[str, str]:
    """The master officer key and where it came from. Never a built-in default: it is from the environment, or generated once and kept in data/officer_key.txt."""
    if env_value:
        return env_value, "environment"
    path = data_dir / "officer_key.txt"
    if path.exists() and path.read_text().strip():
        return path.read_text().strip(), str(path)
    data_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(12)
    path.write_text(key + "\n")
    path.chmod(0o600)
    return key, str(path)


class OfficerStore:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "netra.db"
        with self.db() as c:
            for ddl in SCHEMA:
                c.execute(ddl)
            have = {r[1] for r in c.execute("PRAGMA table_info(officers)")}
            for col, ddl in (("agencies", "TEXT NOT NULL DEFAULT ''"), ("email", "TEXT NOT NULL DEFAULT ''"), ("totp_secret", "TEXT NOT NULL DEFAULT ''"),
                             ("totp_enabled", "INTEGER NOT NULL DEFAULT 0"), ("totp_last_step", "INTEGER NOT NULL DEFAULT 0"), ("recovery", "TEXT NOT NULL DEFAULT '[]'")):
                if col not in have:
                    c.execute(f"ALTER TABLE officers ADD COLUMN {col} {ddl}")

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- accounts
    @staticmethod
    def _agencies(value) -> str:
        return ",".join(sorted({a.strip() for a in (value or []) if a.strip()}))

    def create(self, username: str, name: str, role: str, password: str, agencies: list[str] | None = None, email: str = "") -> dict:
        username = username.strip().lower()
        if not USERNAME_RE.fullmatch(username):
            raise ValueError("Username: 3 to 32 characters, lower-case letters, digits, dot, dash or underscore.")
        if role not in ROLES:
            raise ValueError(f"Role must be one of {ROLES}.")
        if email and not EMAIL_RE.fullmatch(email.strip()):
            raise ValueError("That does not look like an email address.")
        name = " ".join(name.split())
        if not (2 <= len(name) <= 80):
            raise ValueError("Give the officer's name (2 to 80 characters).")
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        salt, h = hash_password(password)
        oid = uuid.uuid4().hex[:10]
        try:
            with self.db() as c:
                c.execute("INSERT INTO officers (id, username, name, role, pw_salt, pw_hash, created_at, agencies, email) VALUES (?,?,?,?,?,?,?,?,?)",
                          (oid, username, name, role, salt, h, iso(now()), self._agencies(agencies), email.strip().lower()))
        except sqlite3.IntegrityError:
            raise ValueError("That username is taken.")
        return self.get(oid)

    @staticmethod
    def _public(r) -> dict:
        return {"id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"], "active": bool(r["active"]),
                "created_at": r["created_at"], "last_login": r["last_login"], "agencies": [a for a in r["agencies"].split(",") if a],
                "email": r["email"], "two_factor": bool(r["totp_enabled"]), "recovery_left": len(json.loads(r["recovery"] or "[]")) if r["totp_enabled"] else 0}

    def get(self, oid: str) -> dict | None:
        with self.db() as c:
            r = c.execute("SELECT * FROM officers WHERE id=?", (oid,)).fetchone()
        return self._public(r) if r else None

    def by_username(self, username: str) -> dict | None:
        with self.db() as c:
            r = c.execute("SELECT * FROM officers WHERE username=?", (username.strip().lower(),)).fetchone()
        return self._public(r) if r else None

    def team(self) -> list[dict]:
        with self.db() as c:
            return [self._public(r) for r in c.execute("SELECT * FROM officers ORDER BY created_at")]

    def update(self, oid: str, *, role: str | None = None, active: bool | None = None, password: str | None = None,
               agencies: list[str] | None = None) -> dict | None:
        cur = self.get(oid)
        if cur is None:
            return None
        sets, args = [], []
        if role is not None:
            if role not in ROLES:
                raise ValueError(f"Role must be one of {ROLES}.")
            sets.append("role=?"); args.append(role)
        if active is not None:
            sets.append("active=?"); args.append(int(active))
        if agencies is not None:
            sets.append("agencies=?"); args.append(self._agencies(agencies))
        if password is not None:
            problem = password_problem(password)
            if problem:
                raise ValueError(problem)
            salt, h = hash_password(password)
            sets += ["pw_salt=?", "pw_hash=?"]; args += [salt, h]
        if sets:
            with self.db() as c:
                c.execute(f"UPDATE officers SET {', '.join(sets)} WHERE id=?", (*args, oid))
                if active is False or password is not None or role is not None or agencies is not None:
                    c.execute("DELETE FROM sessions WHERE officer_id=?", (oid,))      # a changed account signs out everywhere
        return self.get(oid)

    def admins_active(self) -> int:
        with self.db() as c:
            return c.execute("SELECT COUNT(*) FROM officers WHERE role='admin' AND active=1").fetchone()[0]

    # ---- sessions
    def check_credentials(self, username: str, password: str):
        """The account row if the username and password are right and the account is on, else None. Costs the same time either way."""
        with self.db() as c:
            r = c.execute("SELECT * FROM officers WHERE username=?", (username.strip().lower(),)).fetchone()
        if r:
            ok = check_password(password, r["pw_salt"], r["pw_hash"])
        else:
            hash_password(password)
            ok = False
        return r if (r and ok and r["active"]) else None

    @staticmethod
    def _ident(r) -> dict:
        return {"id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"], "agencies": [a for a in r["agencies"].split(",") if a]}

    def login(self, username: str, password: str) -> dict | None:
        """{"session": token, "officer": ident}, or {"challenge": token} when the account needs a second step, or None."""
        r = self.check_credentials(username, password)
        if r is None:
            return None
        if r["totp_enabled"]:
            return {"challenge": self.start_challenge(r["id"])}
        return {"session": self._finish(r), "officer": self._ident(r)}

    def _finish(self, r) -> str:
        with self.db() as c:
            c.execute("UPDATE officers SET last_login=? WHERE id=?", (iso(now()), r["id"]))
        return self.open_session(self._ident(r))

    # ---- second step (authenticator app)
    def start_challenge(self, oid: str) -> str:
        token = secrets.token_urlsafe(24)
        with self.db() as c:
            c.execute("DELETE FROM challenges WHERE expires_at < ?", (iso(now()),))
            c.execute("INSERT INTO challenges VALUES (?,?,?,0)", (hashlib.sha256(token.encode()).hexdigest(), oid, iso(now() + timedelta(minutes=5))))
        return token

    def finish_challenge(self, token: str, code: str) -> tuple[str, dict, str] | None:
        """Check the code for a pending sign-in. Five wrong tries end the challenge. Returns (session, ident, how) with how = "app" or "recovery"."""
        th = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as c:
            ch = c.execute("SELECT * FROM challenges WHERE token_hash=?", (th,)).fetchone()
            if not ch or ch["expires_at"] < iso(now()):
                return None
            r = c.execute("SELECT * FROM officers WHERE id=?", (ch["officer_id"],)).fetchone()
            if not r or not r["active"] or not r["totp_enabled"]:
                return None
            how = None
            step = totp.verify(r["totp_secret"], code, r["totp_last_step"])
            if step is not None:
                c.execute("UPDATE officers SET totp_last_step=? WHERE id=?", (step, r["id"])); how = "app"
            else:
                rec = json.loads(r["recovery"] or "[]")
                h = hashlib.sha256(code.strip().lower().replace(" ", "").encode()).hexdigest()
                if any(hmac.compare_digest(h, x) for x in rec):
                    rec = [x for x in rec if not hmac.compare_digest(h, x)]
                    c.execute("UPDATE officers SET recovery=? WHERE id=?", (json.dumps(rec), r["id"])); how = "recovery"
            if how is None:
                if ch["attempts"] + 1 >= 5:
                    c.execute("DELETE FROM challenges WHERE token_hash=?", (th,))
                else:
                    c.execute("UPDATE challenges SET attempts=attempts+1 WHERE token_hash=?", (th,))
                return None
            c.execute("DELETE FROM challenges WHERE token_hash=?", (th,))
        return self._finish(r), self._ident(r), how

    def totp_begin(self, oid: str) -> str:
        secret = totp.new_secret()
        with self.db() as c:
            c.execute("UPDATE officers SET totp_secret=?, totp_enabled=0, totp_last_step=0, recovery='[]' WHERE id=?", (secret, oid))
        return secret

    def totp_enable(self, oid: str, code: str) -> list[str] | None:
        with self.db() as c:
            r = c.execute("SELECT totp_secret, totp_enabled FROM officers WHERE id=?", (oid,)).fetchone()
            if not r or not r["totp_secret"] or r["totp_enabled"]:
                return None
            step = totp.verify(r["totp_secret"], code)
            if step is None:
                return None
            codes = [f"{secrets.token_hex(3)}-{secrets.token_hex(3)}" for _ in range(8)]
            c.execute("UPDATE officers SET totp_enabled=1, totp_last_step=?, recovery=? WHERE id=?",
                      (step, json.dumps([hashlib.sha256(x.encode()).hexdigest() for x in codes]), oid))
        return codes

    def totp_secret(self, oid: str) -> str:
        with self.db() as c:
            r = c.execute("SELECT totp_secret FROM officers WHERE id=?", (oid,)).fetchone()
        return r["totp_secret"] if r else ""

    def sign_out(self, oid: str) -> None:
        with self.db() as c:
            c.execute("DELETE FROM sessions WHERE officer_id=?", (oid,))

    def totp_clear(self, oid: str) -> None:
        with self.db() as c:
            c.execute("UPDATE officers SET totp_secret='', totp_enabled=0, totp_last_step=0, recovery='[]' WHERE id=?", (oid,))

    # ---- email and password reset
    def set_email(self, oid: str, email: str) -> None:
        email = email.strip().lower()
        if email and not EMAIL_RE.fullmatch(email):
            raise ValueError("That does not look like an email address.")
        with self.db() as c:
            c.execute("UPDATE officers SET email=? WHERE id=?", (email, oid))

    def reset_begin(self, identifier: str) -> tuple[str, dict] | None:
        """A single-use token (valid 30 minutes) for the active account with this username or email that has an email on file, else None."""
        ident = identifier.strip().lower()
        with self.db() as c:
            r = c.execute("SELECT * FROM officers WHERE active=1 AND email != '' AND (username=? OR email=?)", (ident, ident)).fetchone()
            if not r:
                return None
            token = secrets.token_urlsafe(32)
            c.execute("DELETE FROM resets WHERE expires_at < ? OR officer_id=?", (iso(now()), r["id"]))
            c.execute("INSERT INTO resets VALUES (?,?,?,0)", (hashlib.sha256(token.encode()).hexdigest(), r["id"], iso(now() + timedelta(minutes=30))))
        return token, self._public(r)

    def reset_finish(self, token: str, new_password: str) -> dict | None:
        problem = password_problem(new_password)
        if problem:
            raise ValueError(problem)
        th = hashlib.sha256(token.encode()).hexdigest()
        with self.db() as c:
            row = c.execute("SELECT * FROM resets WHERE token_hash=?", (th,)).fetchone()
            if not row or row["used"] or row["expires_at"] < iso(now()):
                return None
            salt, h = hash_password(new_password)
            c.execute("UPDATE officers SET pw_salt=?, pw_hash=? WHERE id=?", (salt, h, row["officer_id"]))
            c.execute("UPDATE resets SET used=1 WHERE token_hash=?", (th,))
            c.execute("DELETE FROM sessions WHERE officer_id=?", (row["officer_id"],))
        return self.get(row["officer_id"])

    def mail_add(self, recipient: str, subject: str, body: str, state: str) -> None:
        with self.db() as c:
            c.execute("INSERT INTO mail (at, recipient, subject, body, state) VALUES (?,?,?,?,?)", (iso(now()), recipient, subject, body, state))

    def mail_list(self, limit: int = 100) -> list[dict]:
        with self.db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM mail ORDER BY id DESC LIMIT ?", (limit,))]

    # ---- live alerts
    def alert(self, kind: str, title: str, detail: str = "", link: str | None = None, department: str | None = None) -> None:
        with self.db() as c:
            c.execute("INSERT INTO alerts (at, kind, title, detail, link, department) VALUES (?,?,?,?,?,?)", (iso(now()), kind, title[:200], detail[:400], link, department))
            c.execute("DELETE FROM alerts WHERE id <= (SELECT MAX(id) FROM alerts) - 2000")

    def alerts_since(self, since: int, agencies: list[str] | None, limit: int = 50) -> tuple[list[dict], int]:
        q, args = "SELECT * FROM alerts WHERE id > ?", [since]
        if agencies:
            q += f" AND (department IS NULL OR department IN ({','.join('?' * len(agencies))}))"
            args += list(agencies)
        with self.db() as c:
            rows = [dict(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]
            latest = c.execute("SELECT COALESCE(MAX(id), 0) FROM alerts").fetchone()[0]
        return rows, latest

    def open_session(self, ident: dict) -> str:
        token = secrets.token_urlsafe(32)
        with self.db() as c:
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (iso(now()),))
            c.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
                      (hashlib.sha256(token.encode()).hexdigest(), ident["id"], ident["username"], ident["name"], ident["role"],
                       iso(now()), iso(now() + timedelta(hours=SESSION_HOURS))))
        return token

    def identity(self, token: str) -> dict | None:
        with self.db() as c:
            r = c.execute("SELECT * FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            if not r or r["expires_at"] < iso(now()):
                return None
            if r["officer_id"] != "key":
                o = c.execute("SELECT role, active, agencies FROM officers WHERE id=?", (r["officer_id"],)).fetchone()
                if not o or not o["active"]:
                    return None
                role, agencies = o["role"], [a for a in o["agencies"].split(",") if a]
            else:
                role, agencies = r["role"], []
        return {"id": r["officer_id"], "username": r["username"], "name": r["name"], "role": role, "agencies": agencies}

    def sessions(self, current_token: str | None = None) -> list[dict]:
        """Active sign-ins. The id is a short prefix of the stored hash: enough to revoke one, useless as a credential."""
        cur = hashlib.sha256(current_token.encode()).hexdigest() if current_token else None
        with self.db() as c:
            c.execute("DELETE FROM sessions WHERE expires_at < ?", (iso(now()),))
            rows = c.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [{"id": r["token_hash"][:12], "username": r["username"], "name": r["name"], "role": r["role"], "created_at": r["created_at"],
                 "expires_at": r["expires_at"], "current": r["token_hash"] == cur} for r in rows]

    def revoke(self, sid: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{12}", sid):
            return False
        with self.db() as c:
            return c.execute("DELETE FROM sessions WHERE substr(token_hash,1,12)=?", (sid,)).rowcount > 0

    def logout(self, token: str) -> None:
        with self.db() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    # ---- audit
    def log(self, actor: dict, action: str, target: str | None = None, detail: str | None = None) -> None:
        with self.db() as c:
            c.execute("INSERT INTO audit (at, actor, role, action, target, detail) VALUES (?,?,?,?,?,?)",
                      (iso(now()), actor["username"], actor["role"], action, target, (detail or "")[:500]))

    def audit(self, limit: int = 200, actor: str | None = None, action: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM audit WHERE 1=1", []
        if actor:
            q += " AND actor=?"; args.append(actor)
        if action:
            q += " AND action LIKE ?"; args.append(action + "%")
        with self.db() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY id DESC LIMIT ?", (*args, limit))]
