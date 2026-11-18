import base64
import hashlib
import hmac
import io
import json
import re
import secrets
from contextlib import closing
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from PIL import Image, UnidentifiedImageError

from app import CATEGORIES, Handler
from api.catalogo import connect


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000).hex()


def phone_number(value):
    phone = re.sub(r"[ ()+.-]", "", value)
    if re.fullmatch(r"55[0-9]{10,11}", phone):
        phone = phone[2:]
    if not re.fullmatch(r"[1-9][0-9]{9,10}", phone):
        raise ValueError
    return phone


class handler(Handler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def session_phone(self, db):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["professional_session"].value
        except (KeyError, ValueError):
            return None
        row = db.execute("""SELECT phone FROM professional_sessions
            WHERE token_hash=? AND expires_at > CURRENT_TIMESTAMP""",
                         (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return row["phone"] if row else None

    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query)
        if not query:
            page = Path(__file__).resolve().parent.parent / "templates" / "profissional.html"
            self.reply(200, page.read_bytes(), "text/html; charset=utf-8")
            return
        with closing(connect()) as db:
            phone = self.session_phone(db)
            if not phone:
                self.json_reply(401, {"error": "Entre com seu telefone e senha."})
                return
            rows = list(db.execute("""SELECT id,name,category,status,premium,description,photo
                FROM providers WHERE phone=? ORDER BY id""", (phone,)))
            for row in rows:
                row["photos"] = [dict(id=p["id"], url="/api/foto?id="+str(p["id"]))
                                 for p in db.execute("SELECT id FROM professional_photos WHERE provider_id=? ORDER BY id", (row["id"],))]
        self.json_reply(200, {"phone": phone, "providers": rows, "categories": CATEGORIES})

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 700000 or self.headers.get_content_type() != "application/json":
                raise ValueError
            if self.headers.get("X-Professional-Request") != "1":
                raise ValueError
            data = json.loads(self.rfile.read(size))
            action = data["action"]
        except (ValueError, KeyError, TypeError):
            self.json_reply(400, {"error": "Solicitação inválida."})
            return
        if action in ("login", "register"):
            self.authenticate(data, action)
            return
        if action == "logout":
            with closing(connect()) as db, db:
                phone = self.session_phone(db)
                if phone:
                    cookie = SimpleCookie(self.headers.get("Cookie", ""))
                    token = cookie["professional_session"].value
                    db.execute("DELETE FROM professional_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
            self.send_response(200)
            self.send_header("Set-Cookie", "professional_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0")
            self.end_headers()
            return
        if action == "password":
            with closing(connect()) as db, db:
                phone = self.session_phone(db)
                if not phone:
                    self.json_reply(401, {"error": "Entre novamente."})
                    return
                current, password = data.get("current"), data.get("password")
                if not isinstance(current,str) or not isinstance(password,str) or not 15 <= len(password) <= 128 or len(current)>128:
                    self.json_reply(400, {"error": "Use entre 15 e 128 caracteres."})
                    return
                row=db.execute("SELECT * FROM professional_accounts WHERE phone=? FOR UPDATE",(phone,)).fetchone()
                if not hmac.compare_digest(password_hash(current,bytes.fromhex(row["salt"])),row["password_hash"]):
                    self.json_reply(400, {"error":"Senha atual incorreta."})
                    return
                salt=secrets.token_bytes(16)
                db.execute("UPDATE professional_accounts SET salt=?,password_hash=? WHERE phone=?",(salt.hex(),password_hash(password,salt),phone))
                db.execute("DELETE FROM professional_sessions WHERE phone=?",(phone,))
            self.json_reply(200, {"message":"Senha alterada. Entre novamente."})
            return
        try:
            provider_id = data["id"]
            if type(provider_id) is not int:
                raise ValueError
            with closing(connect()) as db, db:
                phone = self.session_phone(db)
                if not phone:
                    self.json_reply(401, {"error": "Sua sessão expirou. Entre novamente."})
                    return
                profile = db.execute("SELECT * FROM providers WHERE id=? AND phone=? FOR UPDATE",
                                     (provider_id, phone)).fetchone()
                if not profile:
                    self.json_reply(404, {"error": "Perfil não encontrado."})
                    return
                if action == "save":
                    name, category = data["name"].strip(), data["category"]
                    description = data["description"].strip()
                    if not 2 <= len(name) <= 80 or category not in CATEGORIES or len(description) > 1000:
                        raise ValueError
                    if not profile["premium"]:
                        description = profile["description"]
                    db.execute("UPDATE providers SET name=?, category=?, description=? WHERE id=?",
                               (name, category, description, provider_id))
                elif action == "upload":
                    if not profile["premium"]:
                        self.json_reply(403, {"error": "O envio de fotos está disponível no plano pago. Solicite a ativação ao administrador."})
                        return
                    count = db.execute("SELECT count(*) AS n FROM professional_photos WHERE provider_id=?", (provider_id,)).fetchone()["n"]
                    if count >= 10:
                        self.json_reply(400, {"error": "Você pode manter até 10 fotos. Exclua uma para adicionar outra."})
                        return
                    raw = base64.b64decode(data["image"], validate=True)
                    if len(raw) > 500000:
                        raise ValueError
                    with Image.open(io.BytesIO(raw)) as photo:
                        if photo.width * photo.height > 16000000:
                            raise ValueError
                        photo.thumbnail((1400, 1400))
                        output = io.BytesIO()
                        photo.convert("RGB").save(output, format="JPEG", quality=82)
                    db.execute("INSERT INTO professional_photos(provider_id,image) VALUES(?,?)", (provider_id, output.getvalue()))
                elif action == "delete-photo":
                    photo_id = data["photo"]
                    if type(photo_id) is not int:
                        raise ValueError
                    db.execute("DELETE FROM professional_photos WHERE id=? AND provider_id=?", (photo_id, provider_id))
                else:
                    raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError, UnidentifiedImageError, OSError):
            self.json_reply(400, {"error": "Confira os dados e use uma foto JPG, PNG ou WebP de até 16 megapixels."})
            return
        except Exception as error:
            from psycopg.errors import UniqueViolation
            if not isinstance(error, UniqueViolation):
                raise
            self.json_reply(409, {"error": "Você já tem um cadastro nesta categoria."})
            return
        self.json_reply(200, {"message": "Alteração salva."})

    def authenticate(self, data, action):
        try:
            phone, password = phone_number(data["phone"]), data["password"]
            if not isinstance(password, str) or not 15 <= len(password) <= 128:
                raise ValueError
            name = data.get("name", "").strip()
            category = data.get("category")
            if action == "register" and (not 2 <= len(name) <= 80 or category not in CATEGORIES or data.get("consent") is not True):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            self.json_reply(400, {"error": "Confira os dados. A senha deve ter entre 15 e 128 caracteres."})
            return
        with closing(connect()) as db, db:
            db.execute("""INSERT INTO professional_login_attempts(phone) VALUES(?)
                ON CONFLICT(phone) DO NOTHING""", (phone,))
            attempt = db.execute("SELECT *, window_start > CURRENT_TIMESTAMP - INTERVAL '15 minutes' AS recent FROM professional_login_attempts WHERE phone=? FOR UPDATE", (phone,)).fetchone()
            if attempt["recent"] and attempt["attempts"] >= 10:
                self.json_reply(429, {"error": "Muitas tentativas. Aguarde 15 minutos."})
                return
            db.execute("""UPDATE professional_login_attempts SET attempts=CASE WHEN
                window_start > CURRENT_TIMESTAMP - INTERVAL '15 minutes' THEN attempts+1 ELSE 1 END,
                window_start=CASE WHEN window_start > CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                THEN window_start ELSE CURRENT_TIMESTAMP END WHERE phone=?""", (phone,))
            account = db.execute("SELECT * FROM professional_accounts WHERE phone=?", (phone,)).fetchone()
            if action == "register":
                existing = db.execute("SELECT id FROM providers WHERE phone=?", (phone,)).fetchone()
                if account or existing:
                    self.json_reply(409, {"error": "Este telefone já possui cadastro. Se você ainda não tem senha, solicite ao administrador a habilitação do acesso."})
                    return
                salt = secrets.token_bytes(16)
                db.execute("INSERT INTO professional_accounts(phone,salt,password_hash) VALUES(?,?,?)",
                           (phone, salt.hex(), password_hash(password, salt)))
                db.execute("INSERT INTO providers(name,phone,category) VALUES(?,?,?)", (name, phone, category))
            else:
                salt = bytes.fromhex(account["salt"]) if account else bytes(16)
                hashed = password_hash(password, salt)
                if not account or not hmac.compare_digest(hashed, account["password_hash"]):
                    self.json_reply(401, {"error": "Telefone ou senha incorretos."})
                    return
            token = secrets.token_urlsafe(32)
            db.execute("INSERT INTO professional_sessions(token_hash,phone) VALUES(?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), phone))
            db.execute("DELETE FROM professional_login_attempts WHERE phone=?", (phone,))
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "professional_session="+token+"; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=604800")
        self.end_headers()
        self.wfile.write(json.dumps({"message": "Acesso liberado."}).encode())
