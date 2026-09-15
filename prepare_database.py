"""Restore the verified archive on the first hosted run; never replace an existing DB."""
import datetime as dt
import json
import sqlite3
from scraper import DB, ROOT, create_db, save

if not DB.exists():
    rows = json.loads((ROOT / 'data/seed.json').read_text(encoding='utf-8'))
    with sqlite3.connect(DB) as connection:
        create_db(connection)
        save(connection, rows, dt.date.fromisoformat(min(r['date'] for r in rows)), dt.date.fromisoformat(max(r['date'] for r in rows)))
    print(f'Restored {len(rows)} verified historical draws')
