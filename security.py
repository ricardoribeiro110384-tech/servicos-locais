"""Small, shared security controls for the SQLite demo and PostgreSQL production."""
import hashlib
import hmac
import ipaddress
import os
import time


def valid_admin_password(password):
    return isinstance(password, str) and 15 <= len(password) and len(password.encode("utf-8")) <= 512


def request_ip(handler):
    # Vercel overwrites forwarded address headers; never trust a user-supplied header locally.
    raw = (handler.headers.get("X-Vercel-Forwarded-For", "")
           if os.environ.get("VERCEL") else handler.client_address[0])
    try:
        return str(ipaddress.ip_address(raw.split(",")[0].strip()))
    except (ValueError, AttributeError, IndexError):
        return "unknown"


def throttle_key(purpose, ip):
    secret = os.environ.get("THROTTLE_SECRET") or os.environ.get("ADMIN_PASSWORD") or "local-development"
    payload = (purpose + ":" + ip).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def attempts_exceeded(db, key, maximum, window_seconds, now=None):
    if now is None:
        now = int(time.time())
    row = db.execute(
        "SELECT attempts, window_start FROM security_throttle WHERE throttle_key = ?", (key,)
    ).fetchone()
    return bool(row and row["window_start"] > now - window_seconds
                and row["attempts"] >= maximum)


def record_attempt(db, key, window_seconds, now=None):
    if now is None:
        now = int(time.time())
    expired = now - window_seconds
    row = db.execute("""INSERT INTO security_throttle (throttle_key, window_start, attempts)
        VALUES (?, ?, 1)
        ON CONFLICT (throttle_key) DO UPDATE SET
        attempts = CASE WHEN security_throttle.window_start <= ? THEN 1
                        ELSE security_throttle.attempts + 1 END,
        window_start = CASE WHEN security_throttle.window_start <= ? THEN ?
                            ELSE security_throttle.window_start END
        RETURNING attempts""", (key, now, expired, expired, now)).fetchone()
    return row["attempts"]


def clear_attempts(db, key):
    db.execute("DELETE FROM security_throttle WHERE throttle_key = ?", (key,))
