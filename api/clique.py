import json
import uuid
from contextlib import closing

from app import Handler
from api.catalogo import connect


class handler(Handler):
    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 1024 or self.headers.get_content_type() != "application/json":
                raise ValueError
            data = json.loads(self.rfile.read(size))
            event_id = str(uuid.UUID(data["event"]))
            visitor_id = str(uuid.UUID(data["visitor"]))
            provider_id, action = data["id"], data["action"]
            if type(provider_id) is not int or not 0 < provider_id < 2**63 or action not in ("photos", "whatsapp"):
                raise ValueError
        except (ValueError, AttributeError, KeyError, TypeError):
            self.json_reply(400, {"error": "Evento inválido."})
            return
        with closing(connect()) as db, db:
            db.execute("""INSERT INTO provider_clicks(event_id,provider_id,action,visitor_id)
                SELECT ?::uuid,id,?,?::uuid FROM providers WHERE id=? AND status='active'
                ON CONFLICT(event_id) DO NOTHING""", (event_id, action, visitor_id, provider_id))
        self.json_reply(200, {"ok": True})
