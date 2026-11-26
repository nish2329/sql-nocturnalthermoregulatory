"""Shared database helpers."""
import os

import psycopg2

DSN = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/thermo")


def connect():
    return psycopg2.connect(DSN)


def run_sql_file(path):
    """Run a multi-statement .sql file in one transaction."""
    with open(path) as f, connect() as conn, conn.cursor() as cur:
        cur.execute(f.read())

# pandas warns when given a raw DBAPI connection; psycopg2 works fine here.
import warnings
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
