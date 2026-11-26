"""Run the SQL steps in order: clean, baseline, score, detect, person-nights."""
import glob
import os
import time

from db import run_sql_file

HERE = os.path.dirname(os.path.abspath(__file__))

for path in sorted(glob.glob(os.path.join(HERE, "..", "sql", "0[1-9]_*.sql"))):
    t = time.time()
    run_sql_file(path)
    print(f"{os.path.basename(path):<24} {time.time() - t:6.1f}s")
