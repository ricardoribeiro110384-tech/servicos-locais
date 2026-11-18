from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from app import Handler
from api.catalogo import connect


class handler(Handler):
    def do_GET(self):
        try:
            photo_id = int(parse_qs(urlsplit(self.path).query)["id"][0])
            if not 0 < photo_id < 2**63:
                raise ValueError
        except (ValueError, KeyError):
            self.json_reply(404, {"error": "Foto não encontrada."})
            return
        with closing(connect()) as db:
            row = db.execute("""SELECT f.image FROM professional_photos f
                JOIN providers p ON p.id=f.provider_id
                WHERE f.id=? AND p.status='active' AND p.premium=1""", (photo_id,)).fetchone()
        if not row:
            self.json_reply(404, {"error": "Foto não encontrada."})
            return
        self.reply(200, bytes(row["image"]), "image/jpeg")
