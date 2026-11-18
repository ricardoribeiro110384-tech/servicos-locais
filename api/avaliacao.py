import json
from contextlib import closing

from app import Handler
from api.catalogo import connect


class handler(Handler):
    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 4096 or self.headers.get_content_type() != "application/json":
                raise ValueError
            data = json.loads(self.rfile.read(size))
            provider_id, name, stars = data["id"], data["name"].strip(), data["stars"]
            comment = data.get("comment", "").strip()
            if (type(provider_id) is not int or not 0 < provider_id < 2**63
                    or type(stars) is not int or not 1 <= stars <= 5
                    or not 2 <= len(name) <= 80 or len(comment) > 500
                    or data.get("confirmed") is not True):
                raise ValueError
        except (ValueError, KeyError, AttributeError, TypeError):
            self.json_reply(400, {"error": "Informe seu nome, selecione as estrelas e confirme o atendimento."})
            return
        with closing(connect()) as db, db:
            provider = db.execute("SELECT id, premium FROM providers WHERE id = ? AND status = 'active' FOR UPDATE",
                                  (provider_id,)).fetchone()
            if not provider or not provider["premium"]:
                self.json_reply(404, {"error": "Este perfil não está recebendo avaliações."})
                return
            duplicate = db.execute("""SELECT id FROM customer_reviews WHERE provider_id = ?
                AND lower(name) = lower(?) AND created_at > CURRENT_TIMESTAMP - INTERVAL '1 day'""",
                                   (provider_id, name)).fetchone()
            if duplicate:
                self.json_reply(409, {"error": "Uma avaliação com este nome já foi enviada hoje para este profissional."})
                return
            db.execute("INSERT INTO customer_reviews(provider_id,name,stars,comment) VALUES(?,?,?,?)",
                       (provider_id, name, stars, comment))
        self.json_reply(201, {"message": "Avaliação enviada! Ela será publicada após aprovação."})
