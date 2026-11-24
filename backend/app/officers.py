"""Officer accounts, sign-in sessions and the audit log.

How access works:
* The master officer key (EXLEX_OFFICER_KEY, or the key stored in data/officer_key.txt) signs in as an administrator.
  The admin can then create an account for each officer, so work is attributed to a person and the key can stay private.
* Passwords are stored as scrypt hashes with a per-account salt; sessions are random tokens of which only the hash is kept.
* Every action that changes something is written to the audit log with who did it. The log is append-only through this module.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROLES = ("admin", "officer")
SESSION_HOURS = 12
MIN_PASSWORD = 10
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS officers (
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL,
        pw_salt TEXT NOT NULL, pw_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, last_login TEXT)""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, officer_id TEXT NOT NULL, username TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL)""",
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
            if "agencies" not in {r[1] for r in c.execute("PRAGMA table_info(officers)")}:
                c.execute("ALTER TABLE officers ADD COLUMN agencies TEXT NOT NULL DEFAULT ''")

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

    def create(self, username: str, name: str, role: str, password: str, agencies: list[str] | None = None) -> dict:
        username = username.strip().lower()
        if not USERNAME_RE.fullmatch(username):
            raise ValueError("Username: 3 to 32 characters, lower-case letters, digits, dot, dash or underscore.")
        if role not in ROLES:
            raise ValueError(f"Role must be one of {ROLES}.")
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
                c.execute("INSERT INTO officers (id, username, name, role, pw_salt, pw_hash, created_at, agencies) VALUES (?,?,?,?,?,?,?,?)",
                          (oid, username, name, role, salt, h, iso(now()), self._agencies(agencies)))
        except sqlite3.IntegrityError:
            raise ValueError("That username is taken.")
        return self.get(oid)

    @staticmethod
    def _public(r) -> dict:
        return {"id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"], "active": bool(r["active"]),
                "created_at": r["created_at"], "last_login": r["last_login"], "agencies": [a for a in r["agencies"].split(",") if a]}

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
    def login(self, username: str, password: str) -> tuple[str, dict] | None:
        with self.db() as c:
            r = c.execute("SELECT * FROM officers WHERE username=?", (username.strip().lower(),)).fetchone()
        # always run a hash so a wrong username costs the same time as a wrong password
        if r:
            ok = check_password(password, r["pw_salt"], r["pw_hash"])
        else:
            hash_password(password)
            ok = False
        if not r or not ok or not r["active"]:
            return None
        with self.db() as c:
            c.execute("UPDATE officers SET last_login=? WHERE id=?", (iso(now()), r["id"]))
        ident = {"id": r["id"], "username": r["username"], "name": r["name"], "role": r["role"], "agencies": [a for a in r["agencies"].split(",") if a]}
        return self.open_session(ident), ident

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
