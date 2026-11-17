import os

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
