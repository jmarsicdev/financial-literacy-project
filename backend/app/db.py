import os
from contextlib import contextmanager
import psycopg

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://team5:local_dev_only@localhost:5432/financial_literacy")

@contextmanager
def get_connection():
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn
