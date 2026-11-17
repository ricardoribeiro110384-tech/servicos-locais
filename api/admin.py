import base64
import hashlib
import hmac
import secrets
import json
import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.errors import ForeignKeyViolation

from app import Handler
from api.catalogo import connect
from security import (attempts_exceeded, clear_attempts, record_attempt,
                      request_ip, throttle_key, valid_admin_password)


class handler(Handler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def authorize(self):
        password = os.environ.get("ADMIN_PASSWORD")
        if not valid_admin_password(password):
            self.json_reply(503, {"error": "Configure ADMIN_PASSWORD com pelo menos 15 caracteres na Vercel."})
            return False
        self.recovery_fingerprint = hashlib.sha256(password.encode()).hexdigest()
        key = throttle_key("admin", request_ip(self))
        with closing(connect()) as db:
            if attempts_exceeded(db, key, 8, 900):
                self.json_reply(429, {"error": "Muitas tentativas de acesso. Tente novamente mais tarde."})
                return False
            credential = db.execute(
                "SELECT salt, password_hash FROM admin_credential WHERE id = 1 AND recovery_fingerprint = ?",
                (self.recovery_fingerprint,),
            ).fetchone()
        try:
            scheme, value = self.headers.get("Authorization", "").split(" ", 1)
            user, supplied = base64.b64decode(value, validate=True).decode().split(":", 1)
        except (ValueError, UnicodeError):
            scheme, user, supplied = "", "", ""
        if scheme.lower() == "basic" and user == "admin" and 0 < len(supplied.encode()) <= 512:
            if credential:
                valid = hmac.compare_digest(
                    self.hash_password(supplied, bytes.fromhex(credential["salt"])),
                    credential["password_hash"],
                )
            else:
                valid = hmac.compare_digest(supplied.encode(), password.encode())
            if valid:
                with closing(connect()) as db, db:
                    clear_attempts(db, key)
                self.current_password = supplied
                return True
        with closing(connect()) as db, db:
            record_attempt(db, key, 900)
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Servicos Locais Admin", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    @staticmethod
    def hash_password(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000).hex()

    def change_password(self, data):
        current = data.get("current")
        password = data.get("password")
        if not isinstance(current, str) or not hmac.compare_digest(
            current.encode(), self.current_password.encode()
        ):
            self.json_reply(400, {"error": "A senha atual está incorreta."})
            return
        if (not isinstance(password, str) or len(password) < 15
                or len(password.encode()) > 512 or password == current):
            self.json_reply(400, {"error": "Use uma senha diferente com pelo menos 15 caracteres e até 512 bytes."})
            return
        salt = secrets.token_bytes(16)
        with closing(connect()) as db, db:
            db.execute("""INSERT INTO admin_credential (id, recovery_fingerprint, salt, password_hash)
                VALUES (1, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET
                recovery_fingerprint = EXCLUDED.recovery_fingerprint,
                salt = EXCLUDED.salt, password_hash = EXCLUDED.password_hash""",
                       (self.recovery_fingerprint, salt.hex(), self.hash_password(password, salt)))
        self.json_reply(200, {"message": "Senha alterada. Abra o painel em uma janela anônima e entre com a nova senha."})

    def do_GET(self):
        if not self.authorize():
            return
        if urlsplit(self.path).query != "dados=1":
            page = Path(__file__).resolve().parent.parent / "templates" / "admin.html"
            self.reply(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        with closing(connect()) as db:
            rows = list(db.execute("""SELECT id, name, phone, category, status,
                premium, description, photo, reviews FROM providers
                ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC"""))
        self.json_reply(200, {"providers": rows})

    def delete_provider(self, provider_id):
        if type(provider_id) is not int or not 0 < provider_id < 2**63:
            self.json_reply(400, {"error": "Cadastro inválido."})
            return
        try:
            with closing(connect()) as db, db:
                deleted = db.execute("DELETE FROM providers WHERE id = ? RETURNING id",
                                     (provider_id,)).fetchone()
        except ForeignKeyViolation:
            self.json_reply(409, {"error": "Este cadastro tem registros vinculados. Você pode ocultá-lo."})
            return
        if deleted is None:
            self.json_reply(404, {"error": "Cadastro não encontrado."})
            return
        self.json_reply(200, {"message": "Prestador excluído."})

    def do_POST(self):
        if not self.authorize():
            return
        if (self.headers.get("X-Admin-Request") != "1"
                or self.headers.get_content_type() != "application/json"):
            self.json_reply(403, {"error": "Solicitação inválida."})
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 8192:
                raise ValueError
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError
            if urlsplit(self.path).query == "senha=1":
                self.change_password(data)
                return
            provider_id = data["id"]
            if urlsplit(self.path).query == "excluir=1":
                self.delete_provider(provider_id)
                return
            status, premium = data["status"], data["premium"]
            description, photo = data["description"].strip(), data["photo"].strip()
            review, stars = data["review"].strip(), data["stars"]
            if (type(provider_id) is not int or not 0 < provider_id < 2**63
                    or status not in ("pending", "active", "hidden")
                    or type(premium) is not bool or len(description) > 1000 or len(photo) > 2048
                    or (photo and (urlsplit(photo).scheme != "https" or not urlsplit(photo).hostname))
                    or (review and (not premium or len(review) > 500
                                    or type(stars) is not int or not 1 <= stars <= 5))):
                raise ValueError
        except (ValueError, KeyError, AttributeError, TypeError):
            self.json_reply(400, {"error": "Confira os dados. A foto deve usar uma URL HTTPS."})
            return
        with closing(connect()) as db, db:
            row = db.execute("SELECT reviews FROM providers WHERE id = ? FOR UPDATE",
                             (provider_id,)).fetchone()
            if row is None:
                self.json_reply(404, {"error": "Cadastro não encontrado."})
                return
            reviews = json.loads(row["reviews"])
            if review:
                reviews.append({"stars": stars, "text": review})
            db.execute("""UPDATE providers SET status = ?, premium = ?, description = ?,
                photo = ?, reviews = ? WHERE id = ?""",
                       (status, int(premium), description, photo, json.dumps(reviews), provider_id))
        self.json_reply(200, {"message": "Cadastro atualizado.", "reviews": len(reviews)})
