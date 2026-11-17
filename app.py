import argparse
import json
import os
import re
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
DB = os.environ.get("SERVICOS_DB", str(ROOT / "servicos.sqlite3"))
# Read the same taxonomy the frontend can display while the API is unavailable.
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
GROUPS = json.loads(HTML.split('id="service-groups">', 1)[1].split("</script>", 1)[0])
CATEGORIES = tuple(service for services in GROUPS.values() for service in services)


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def init():
    with closing(connect()) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS providers (
            id INTEGER PRIMARY KEY, category TEXT NOT NULL, name TEXT NOT NULL,
            phone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            premium INTEGER NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '',
            photo TEXT NOT NULL DEFAULT '', reviews TEXT NOT NULL DEFAULT '[]',
            UNIQUE(category, phone)
        )""")


class Handler(BaseHTTPRequestHandler):
    database = staticmethod(connect)
    duplicate_error = sqlite3.IntegrityError
    def reply(self, status, body, kind):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, status, data):
        self.reply(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.reply(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/catalogo":
            with closing(self.database()) as db:
                rows = db.execute("SELECT * FROM providers WHERE status = 'active' ORDER BY name COLLATE NOCASE")
                providers = []
                for row in rows:
                    profile = {key: row[key] for key in ("category", "name", "phone", "premium")}
                    if row["premium"]:
                        profile.update(description=row["description"], photo=row["photo"],
                                       reviews=json.loads(row["reviews"]))
                    providers.append(profile)
            self.json_reply(200, dict(categories=CATEGORIES, providers=providers))
        else:
            self.json_reply(404, dict(error="Página indisponível."))

    def do_POST(self):
        if self.path != "/api/cadastro":
            self.json_reply(404, dict(error="Página indisponível."))
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 4096 or self.headers.get_content_type() != "application/json":
                raise ValueError
            data = json.loads(self.rfile.read(size))
            category, name, phone = (data[key].strip() for key in ("category", "name", "phone"))
            phone = re.sub(r"[ ()+.-]", "", phone)
            if re.fullmatch(r"55[0-9]{10,11}", phone):
                phone = phone[2:]
            if (category not in CATEGORIES or not 2 <= len(name) <= 80
                    or not re.fullmatch(r"[1-9][0-9][0-9]{8,9}", phone)
                    or data.get("consent") is not True):
                raise ValueError
        except (ValueError, AttributeError, KeyError, TypeError):
            self.json_reply(400, dict(error="Confira o nome, o telefone com DDD e a autorização de publicação."))
            return
        try:
            with closing(self.database()) as db, db:
                db.execute("INSERT INTO providers(category, name, phone) VALUES (?, ?, ?)",
                           (category, name, phone))
        except self.duplicate_error:
            self.json_reply(409, dict(error="Este telefone já foi cadastrado nesta categoria."))
            return
        self.json_reply(201, dict(message="Cadastro recebido. Seu perfil será publicado após a conferência do contato."))


def main():
    parser = argparse.ArgumentParser(description="Catálogo de serviços de São Raimundo Nonato")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("servir")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--porta", type=int, default=8000)
    commands.add_parser("listar")
    for action in ("aprovar", "ocultar", "gratuito", "premium"):
        command = commands.add_parser(action)
        command.add_argument("id", type=int)
        if action == "premium":
            command.add_argument("--descricao", default=None)
            command.add_argument("--foto", default=None)
    review = commands.add_parser("avaliacao")
    review.add_argument("id", type=int)
    review.add_argument("nota", type=int, choices=range(1, 6))
    review.add_argument("texto")
    args = parser.parse_args()
    init()
    if args.command == "servir":
        with ThreadingHTTPServer((args.host, args.porta), Handler) as server:
            print(f"http://{args.host}:{args.porta}", flush=True)
            server.serve_forever()
        return
    with closing(connect()) as db, db:
        if args.command == "listar":
            for row in db.execute("SELECT id, category, name, phone, status, premium FROM providers ORDER BY id"):
                print(*row, sep=" | ")
            return
        row = db.execute("SELECT * FROM providers WHERE id = ?", (args.id,)).fetchone()
        if row is None:
            parser.error("Prestador não encontrado.")
        if args.command in ("aprovar", "ocultar"):
            status = "active" if args.command == "aprovar" else "hidden"
            db.execute("UPDATE providers SET status = ? WHERE id = ?", (status, args.id))
        elif args.command == "gratuito":
            db.execute("UPDATE providers SET premium = 0 WHERE id = ?", (args.id,))
        elif args.command == "premium":
            if args.foto and urlsplit(args.foto).scheme != "https":
                parser.error("Use um endereço HTTPS para a foto.")
            db.execute("""UPDATE providers SET premium = 1,
                       description = COALESCE(?, description), photo = COALESCE(?, photo) WHERE id = ?""",
                       (args.descricao, args.foto, args.id))
        else:
            if not row["premium"]:
                parser.error("Avaliações estão disponíveis no plano pago.")
            if not 1 <= len(args.texto.strip()) <= 500:
                parser.error("Informe uma avaliação de até 500 caracteres.")
            reviews = json.loads(row["reviews"])
            reviews.append(dict(stars=args.nota, text=args.texto.strip()))
            db.execute("UPDATE providers SET reviews = ? WHERE id = ?", (json.dumps(reviews), args.id))
    print("Alteração salva.")


if __name__ == "__main__":
    main()
