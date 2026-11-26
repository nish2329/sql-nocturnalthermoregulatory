"""Shared database helpers."""
import os
import subprocess

import psycopg2

DSN = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost:5432/thermo")


def connect():
    return psycopg2.connect(DSN)


def run_sql_file(path):
    """Run a .sql file through psql so meta-commands and multi-statement files work."""
    subprocess.run(["psql", DSN, "-v", "ON_ERROR_STOP=1", "-q", "-f", path], check=True)

# pandas warns when given a raw DBAPI connection; psycopg2 works fine here.
import warnings
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")
