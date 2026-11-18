import os
from contextlib import closing
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row

from app import Handler


class PostgresConnection(psycopg.Connection):
    def execute(self, query, params=None, *, prepare=None, binary=False):
        query = query.replace("COLLATE NOCASE", "").replace("?", "%s")
        return super().execute(query, params, prepare=prepare, binary=binary)


def connect():
    return PostgresConnection.connect(os.environ["DATABASE_URL"], row_factory=dict_row,
                                      prepare_threshold=None, connect_timeout=8)


class handler(Handler):
    database = staticmethod(connect)
    duplicate_error = psycopg.errors.UniqueViolation

    def do_GET(self):
        if urlsplit(self.path).path != "/api/catalogo":
            super().do_GET()
            return
        import json
        from app import CATEGORIES
        with closing(connect()) as db:
            profiles = list(db.execute("""SELECT id,name,phone,category,premium,description,photo,reviews
                FROM providers WHERE status='active' ORDER BY name"""))
            photos = list(db.execute("""SELECT f.id,f.provider_id FROM professional_photos f
                JOIN providers p ON p.id=f.provider_id WHERE p.status='active' AND p.premium=1 ORDER BY f.id"""))
        grouped = {}
        for photo in photos:
            grouped.setdefault(photo["provider_id"], []).append("/api/foto?id="+str(photo["id"]))
        for profile in profiles:
            profile["reviews"] = json.loads(profile["reviews"]) if profile["premium"] else []
            if profile["premium"]:
                gallery = grouped.get(profile["id"], [])
                profile["photos"] = ([profile["photo"]] if profile["photo"] else []) + gallery
                if not profile["photo"] and gallery:
                    profile["photo"] = gallery[0]
            else:
                profile["description"], profile["photo"], profile["photos"] = "", "", []
        self.json_reply(200, {"categories": CATEGORIES, "providers": profiles})

