import base64
import hmac
import json
import os
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

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
        expected = "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()
        if hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Servicos Locais Admin", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

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
            provider_id = data["id"]
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
