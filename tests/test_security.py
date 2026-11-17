import base64
import http.client
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import app
import security
from api import admin


@contextmanager
def run_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    all_headers = dict(headers or {})
    if data is not None:
        all_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=data, headers=all_headers)
    response = connection.getresponse()
    raw = response.read()
    status = response.status
    kind = response.getheader("Content-Type", "")
    connection.close()
    return status, json.loads(raw) if raw and "application/json" in kind else {}


class SecurityHelperTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE security_throttle (throttle_key text PRIMARY KEY, window_start bigint, attempts integer)")

    def tearDown(self):
        self.db.close()

    def test_password_policy(self):
        self.assertFalse(security.valid_admin_password("short"))
        self.assertTrue(security.valid_admin_password("senha-com-15-caracteres"))
        self.assertFalse(security.valid_admin_password("😀" * 200))

    def test_atomic_limit_and_window_reset(self):
        key = "client"
        for n in range(8):
            self.assertFalse(security.attempts_exceeded(self.db, key, 8, 900, now=1000))
            self.assertEqual(security.record_attempt(self.db, key, 900, now=1000), n + 1)
        self.assertTrue(security.attempts_exceeded(self.db, key, 8, 900, now=1000))
        self.assertFalse(security.attempts_exceeded(self.db, key, 8, 900, now=1900))
        self.assertEqual(security.record_attempt(self.db, key, 900, now=1900), 1)
        security.clear_attempts(self.db, key)
        self.assertFalse(security.attempts_exceeded(self.db, key, 8, 900, now=1900))

    def test_ip_header_not_trusted_outside_vercel(self):
        fake = type("Fake", (), {"headers": {"X-Vercel-Forwarded-For": "198.51.100.10"}, "client_address": ("127.0.0.1", 1234)})()
        with mock.patch.dict(os.environ, {"VERCEL": ""}):
            self.assertEqual(security.request_ip(fake), "127.0.0.1")
        with mock.patch.dict(os.environ, {"VERCEL": "1"}):
            self.assertEqual(security.request_ip(fake), "198.51.100.10")

    def test_keys_do_not_expose_ip(self):
        with mock.patch.dict(os.environ, {"THROTTLE_SECRET": "test-secret"}):
            value = security.throttle_key("admin", "198.51.100.10")
            self.assertEqual(len(value), 64)
            self.assertNotIn("198.51.100.10", value)
            self.assertNotEqual(value, security.throttle_key("cadastro", "198.51.100.10"))


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old_db = app.DB
        app.DB = str(Path(self.directory.name) / "test.sqlite3")
        app.init()

    def tearDown(self):
        app.DB = self.old_db
        self.directory.cleanup()

    def payload(self, number=0, **changes):
        data = {
            "category": app.CATEGORIES[0],
            "name": "Pessoa de teste",
            "phone": f"899999{number:05d}",
            "consent": True
        }
        data.update(changes)
        return data

    def test_registration_pending_and_only_active_visible(self):
        with run_server(app.Handler) as port:
            status, _ = request(port, "POST", "/api/cadastro", self.payload())
            self.assertEqual(status, 201)
            status, data = request(port, "GET", "/api/catalogo")
            self.assertEqual(status, 200)
            self.assertEqual(data["providers"], [])
            status, _ = request(port, "POST", "/api/cadastro", self.payload())
            self.assertEqual(status, 409)

    def test_registration_rejects_missing_consent_and_invalid_number(self):
        with run_server(app.Handler) as port:
            self.assertEqual(request(port, "POST", "/api/cadastro", self.payload(consent=False))[0], 400)
            self.assertEqual(request(port, "POST", "/api/cadastro", self.payload(phone="123"))[0], 400)

    def test_registration_limit_persists_across_requests(self):
        with run_server(app.Handler) as port:
            for index in range(12):
                self.assertEqual(request(port, "POST", "/api/cadastro", self.payload(index))[0], 201)
            status, _ = request(port, "POST", "/api/cadastro", self.payload(12))
            self.assertEqual(status, 429)


class AdminTests(unittest.TestCase):
    password = "uma-senha-segura-de-teste"

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "admin.sqlite3")
        db = self.connect()
        db.execute("CREATE TABLE admin_credential (id integer PRIMARY KEY, recovery_fingerprint text, salt text, password_hash text)")
        db.execute("CREATE TABLE security_throttle (throttle_key text PRIMARY KEY, window_start bigint, attempts integer)")
        db.execute("""CREATE TABLE providers (id integer PRIMARY KEY, name text, phone text, category text,
            status text, premium int, description text, photo text, reviews text)""")
        db.commit()
        db.close()
        self.patch_env = mock.patch.dict(os.environ, {"ADMIN_PASSWORD": self.password, "VERCEL": ""})
        self.patch_connect = mock.patch.object(admin, "connect", side_effect=self.connect)
        self.patch_env.start()
        self.patch_connect.start()

    def tearDown(self):
        self.patch_connect.stop()
        self.patch_env.stop()
        self.directory.cleanup()

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def basic(password):
        value = base64.b64encode(("admin:" + password).encode()).decode()
        return {"Authorization": "Basic " + value}

    def test_admin_denies_anonymous_login_and_allows_strong_secret(self):
        with run_server(admin.handler) as port:
            self.assertEqual(request(port, "GET", "/api/admin?dados=1")[0], 401)
            self.assertEqual(request(port, "GET", "/api/admin?dados=1", headers=self.basic(self.password))[0], 200)

    def test_admin_throttles_incorrect_passwords(self):
        with run_server(admin.handler) as port:
            for _ in range(8):
                self.assertEqual(request(port, "GET", "/api/admin", headers=self.basic("errada"))[0], 401)
            self.assertEqual(request(port, "GET", "/api/admin", headers=self.basic("errada"))[0], 429)
            # Even a correct password is throttled temporarily from the same IP.
            self.assertEqual(request(port, "GET", "/api/admin", headers=self.basic(self.password))[0], 429)

    def test_admin_rejects_weak_bootstrap_password(self):
        with mock.patch.dict(os.environ, {"ADMIN_PASSWORD": "12345"}):
            with run_server(admin.handler) as port:
                self.assertEqual(request(port, "GET", "/api/admin", headers=self.basic("12345"))[0], 503)

    def test_existing_strong_password_with_legacy_short_recovery_secret(self):
        import hashlib
        legacy_secret = "segredo-curto"
        new_password = "senha-redefinida-16"
        salt = b"e" * 16
        fingerprint = hashlib.sha256(legacy_secret.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT INTO admin_credential (id, recovery_fingerprint, salt, password_hash) VALUES (?, ?, ?, ?)",
                (1, fingerprint, salt.hex(), admin.handler.hash_password(new_password, salt)),
            )
        with mock.patch.dict(os.environ, {"ADMIN_PASSWORD": legacy_secret}):
            with run_server(admin.handler) as port:
                self.assertEqual(request(port, "GET", "/api/admin?dados=1",
                                         headers=self.basic(new_password))[0], 200)
                self.assertEqual(request(port, "GET", "/api/admin?dados=1",
                                         headers=self.basic(legacy_secret))[0], 401)

    def test_password_change_uses_hash_and_invalidates_old_password(self):
        with run_server(admin.handler) as port:
            status, _ = request(port, "POST", "/api/admin?senha=1",
                                {"current": self.password, "password": "nova-senha-segura-mais-longa"},
                                {**self.basic(self.password), "X-Admin-Request": "1"})
            self.assertEqual(status, 200)
            db = self.connect()
            saved_hash = db.execute("SELECT password_hash FROM admin_credential WHERE id=1").fetchone()["password_hash"]
            db.close()
            self.assertNotEqual(saved_hash, "nova-senha-segura-mais-longa")
            self.assertEqual(request(port, "GET", "/api/admin", headers=self.basic("nova-senha-segura-mais-longa"))[0], 200)
            self.assertEqual(request(port, "GET", "/api/admin", headers=self.basic(self.password))[0], 401)


if __name__ == "__main__":
    unittest.main()
