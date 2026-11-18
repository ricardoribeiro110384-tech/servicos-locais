import base64
import hashlib
import hmac
import secrets
import json
import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from psycopg.errors import ForeignKeyViolation

from app import Handler
from api.catalogo import connect


class handler(Handler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def authorize(self):
        password = os.environ.get("ADMIN_PASSWORD")
        if not password:
            self.json_reply(503, {"error": "Acesso administrativo ainda não configurado."})
            return False
        self.recovery_fingerprint = hashlib.sha256(password.encode()).hexdigest()
        with closing(connect()) as db:
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
                self.current_password = supplied
                return True
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
        query = parse_qs(urlsplit(self.path).query)
        if "metricas" in query:
            days = 7 if query.get("dias") == ["7"] else 30
            with closing(connect()) as db:
                rows = list(db.execute("""SELECT p.id, p.name, p.category,
                    count(c.event_id) FILTER (WHERE c.action='photos') AS photos,
                    count(DISTINCT c.visitor_id) FILTER (WHERE c.action='photos') AS photos_unique,
                    count(c.event_id) FILTER (WHERE c.action='whatsapp') AS whatsapp,
                    count(DISTINCT c.visitor_id) FILTER (WHERE c.action='whatsapp') AS whatsapp_unique
                    FROM providers p LEFT JOIN provider_clicks c ON c.provider_id=p.id
                        AND c.created_at >= CURRENT_TIMESTAMP - (? * INTERVAL '1 day')
                    GROUP BY p.id ORDER BY count(c.event_id) DESC, p.name""", (days,)))
            self.json_reply(200, {"days": days, "rows": rows})
            return
        if query.get("dados") != ["1"]:
            page = Path(__file__).resolve().parent.parent / "templates" / "admin.html"
            self.reply(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        with closing(connect()) as db:
            rows = list(db.execute("""SELECT id, name, phone, category, status,
                premium, description, photo, reviews FROM providers
                ORDER BY CASE WHEN status = 'pending' THEN 0 ELSE 1 END, id DESC"""))
        with closing(connect()) as db:
            pending = list(db.execute("""SELECT r.id, r.name, r.stars, r.comment, p.name AS provider_name
                FROM customer_reviews r JOIN providers p ON p.id = r.provider_id
                WHERE r.status = 'pending' ORDER BY r.created_at"""))
        self.json_reply(200, {"providers": rows, "pending_reviews": pending})

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

    def moderate_review(self, data):
        review_id, action = data.get("id"), data.get("action")
        if type(review_id) is not int or not 0 < review_id < 2**63 or action not in ("approve", "reject"):
            self.json_reply(400, {"error": "Avaliação inválida."})
            return
        with closing(connect()) as db, db:
            review = db.execute("SELECT * FROM customer_reviews WHERE id = ? FOR UPDATE", (review_id,)).fetchone()
            if not review or review["status"] != "pending":
                self.json_reply(409, {"error": "Esta avaliação já foi moderada ou removida. Recarregue a página."})
                return
            if action == "approve":
                provider = db.execute("SELECT reviews FROM providers WHERE id = ? FOR UPDATE",
                                      (review["provider_id"],)).fetchone()
                entries = json.loads(provider["reviews"])
                entries.append({"stars": review["stars"], "text": review["comment"], "name": review["name"]})
                db.execute("UPDATE providers SET reviews = ? WHERE id = ?",
                           (json.dumps(entries), review["provider_id"]))
            db.execute("UPDATE customer_reviews SET status = ? WHERE id = ?",
                       ("approved" if action == "approve" else "rejected", review_id))
        self.json_reply(200, {"message": "Avaliação aprovada." if action == "approve" else "Avaliação rejeitada."})

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
            if urlsplit(self.path).query == "acesso=1":
                from api.profissional import password_hash
                provider_id, password = data["id"], data["password"]
                if type(provider_id) is not int or not 0 < provider_id < 2**63 or not isinstance(password, str) or not 15 <= len(password) <= 128:
                    raise ValueError
                with closing(connect()) as db, db:
                    profile = db.execute("SELECT phone FROM providers WHERE id=?", (provider_id,)).fetchone()
                    if not profile:
                        self.json_reply(404, {"error": "Prestador não encontrado."})
                        return
                    salt = secrets.token_bytes(16)
                    db.execute("""INSERT INTO professional_accounts(phone,salt,password_hash) VALUES(?,?,?)
                        ON CONFLICT(phone) DO UPDATE SET salt=EXCLUDED.salt,password_hash=EXCLUDED.password_hash""",
                               (profile["phone"], salt.hex(), password_hash(password,salt)))
                    db.execute("DELETE FROM professional_sessions WHERE phone=?", (profile["phone"],))
                self.json_reply(200, {"message": "Acesso habilitado. Informe ao prestador a senha provisória e o endereço /profissional."})
                return
            if urlsplit(self.path).query == "avaliacao=1":
                self.moderate_review(data)
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
