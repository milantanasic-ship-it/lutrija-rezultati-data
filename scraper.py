"""Archive the public API used by https://lutrija.rs/rezultati.

Fetching and validation finish before a transaction changes the database.
Only the standard library is required (tzdata is needed on Windows).
"""
import argparse
import calendar
import datetime as dt
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

BASE = "https://lutrija.rs/rezultati"
API = "https://lutrija.rs/api/results"
ROOT = Path(__file__).resolve().parent
DB = ROOT / "data/results.sqlite3"
EXPORT = ROOT / "data/results.json"
GAMES = {"loto": ("loto_7_39", "LotoNumbers", 7, 39),
         "loto5": ("loto_5", "MainNumbers", 5, 35),
         "bingo": ("bingo", "BingoNumbers", None, 90)}


def six_months_ago(today):
    year, month = divmod(today.year * 12 + today.month - 1 - 6, 12)
    month += 1
    return dt.date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


def windows(start, end):
    while start <= end:
        stop = min(start + dt.timedelta(days=29), end)
        yield start, stop
        start = stop + dt.timedelta(days=1)


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get_page(game, start, end, page, archive):
    body = {"game": game, "startDate": start.isoformat(), "endDate": end.isoformat(),
            "page": page, "pageSize": 10, "lang": "sr-Latn-RS"}
    request = Request(API, data=packed(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json",
        "User-Agent": "RezultatiArchive/1.0", "Referer": BASE})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=40) as response:
                result = json.load(response)
            break
        except (HTTPError, URLError, TimeoutError) as error:
            if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))
    if not isinstance(result, dict) or result.get("Err") != "OK" or not isinstance(result.get("data"), list):
        raise ValueError(f"Unexpected results response for {game}: {str(result)[:200]}")
    archive.mkdir(parents=True, exist_ok=True)
    (archive / f"{game}-{start}-{end}-p{page}.json").write_text(
        packed({"request": body, "response": result}) + "\n", encoding="utf-8")
    time.sleep(0.3)
    return result


def number_list(values, expected, maximum, field):
    if not isinstance(values, list) or not values or (expected is not None and len(values) != expected):
        raise ValueError(f"Invalid number count: {field}")
    if any(type(n) is not int or not 1 <= n <= maximum for n in values) or len(set(values)) != len(values):
        raise ValueError(f"Invalid or duplicate numbers: {field}")
    return values


def normalize(game, row, start, end):
    slug, field, count, maximum = GAMES[game]
    date = dt.date.fromisoformat(row["Date"][:10])
    if not start <= date <= end:
        raise ValueError(f"Source ignored requested date range: {date}, {start}..{end}")
    if type(row["Round"]) is not int or row["Round"] < 1 or row["Year"] != date.year:
        raise ValueError("Invalid draw identity")
    result = {"game": slug, "date": str(date), "year": date.year, "draw": row["Round"],
              "numbers": number_list(row[field], count, maximum, field), "source": BASE,
              "report": urljoin(BASE, row["ReportUrl"]) if row.get("ReportUrl") else None,
              "details": row}
    if game == "loto5":
        bonus = row.get("Broj_Plus")
        if type(bonus) is not int or bonus < 1:
            raise ValueError("Missing Loto 5 bonus number")
        result["bonus"] = bonus
    return result


def fetch_game(game, start, end, archive, fetch=get_page):
    found = {}
    for first, last in windows(start, end):
        first_page = fetch(game, first, last, 1, archive)
        count, pages = first_page.get("TotalCount"), first_page.get("TotalPages")
        if type(count) is not int or count < 0 or type(pages) is not int or not 0 <= pages <= 1000:
            raise ValueError("Invalid pagination metadata")
        if pages != (count + 9) // 10 and not (count == 0 and pages == 1):
            raise ValueError("Inconsistent pagination metadata")
        chunk = []
        for page in range(1, max(1, pages) + 1):
            response = first_page if page == 1 else fetch(game, first, last, page, archive)
            if response.get("Err") != "OK" or response.get("TotalCount") != count or response.get("TotalPages") != pages:
                raise ValueError("Results changed during pagination; retry the import")
            chunk.extend(normalize(game, row, first, last) for row in response["data"])
        if len(chunk) != count:
            raise ValueError(f"Incomplete response for {game}: {len(chunk)} of {count}")
        for row in chunk:
            key = (row["year"], row["draw"])
            if key in found:
                raise ValueError(f"Duplicate draw returned across pages: {game} {key}")
            found[key] = row
    return list(found.values())


def create_db(connection):
    connection.executescript("""
    CREATE TABLE IF NOT EXISTS draws (
      game TEXT NOT NULL, draw_date TEXT NOT NULL, draw_no INTEGER NOT NULL,
      numbers TEXT NOT NULL, source_url TEXT NOT NULL, checked_at TEXT NOT NULL,
      payload TEXT, content_hash TEXT, PRIMARY KEY(game, draw_date, draw_no));
    CREATE TABLE IF NOT EXISTS revisions (
      id INTEGER PRIMARY KEY, game TEXT, draw_date TEXT, draw_no INTEGER,
      previous_payload TEXT NOT NULL, replaced_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS import_runs (
      id INTEGER PRIMARY KEY, checked_at TEXT NOT NULL, date_from TEXT NOT NULL,
      date_to TEXT NOT NULL, fetched INTEGER NOT NULL, changed INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS draws_by_date ON draws(game, draw_date DESC);
    """)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(draws)")}
    for column in ("payload", "content_hash"):
        if column not in columns:
            connection.execute(f"ALTER TABLE draws ADD COLUMN {column} TEXT")
    connection.commit()


def save(connection, records, start, end):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    changed = 0
    with connection:
        for row in records:
            payload = packed(row)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            key = (row["game"], row["date"], row["draw"])
            old = connection.execute("SELECT payload,content_hash,draw_date FROM draws WHERE game=? AND substr(draw_date,1,4)=? AND draw_no=?",
                                     (row["game"], str(row["year"]), row["draw"])).fetchone()
            if old and old[1] == digest:
                continue
            if old and old[0]:
                connection.execute("INSERT INTO revisions(game,draw_date,draw_no,previous_payload,replaced_at) VALUES(?,?,?,?,?)", (row["game"], old[2], row["draw"], old[0], now))
            if old and old[2] != row["date"]:
                connection.execute("UPDATE draws SET draw_date=? WHERE game=? AND draw_date=? AND draw_no=?",
                                   (row["date"], row["game"], old[2], row["draw"]))
            connection.execute("""INSERT INTO draws(game,draw_date,draw_no,numbers,source_url,checked_at,payload,content_hash)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(game,draw_date,draw_no) DO UPDATE SET
              numbers=excluded.numbers,source_url=excluded.source_url,checked_at=excluded.checked_at,
              payload=excluded.payload,content_hash=excluded.content_hash""",
              (*key, packed(row["numbers"]), BASE, now, payload, digest))
            changed += 1
        connection.execute("INSERT INTO import_runs(checked_at,date_from,date_to,fetched,changed) VALUES(?,?,?,?,?)",
                           (now, str(start), str(end), len(records), changed))
    return changed


def export(connection, target=EXPORT):
    data = [json.loads(r[0]) for r in connection.execute("SELECT payload FROM draws WHERE payload IS NOT NULL ORDER BY draw_date DESC,game,draw_no DESC")]
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(packed(data) + "\n", encoding="utf-8")
    temporary.replace(target)
    return len(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--from-date", type=dt.date.fromisoformat)
    parser.add_argument("--to-date", type=dt.date.fromisoformat)
    args = parser.parse_args()
    today = dt.datetime.now(ZoneInfo("Europe/Belgrade")).date()
    end = args.to_date or today
    start = args.from_date or (six_months_ago(end) if args.backfill else end - dt.timedelta(days=14))
    if start > end or end > today:
        parser.error("Invalid or future date range")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = ROOT / "data/raw" / stamp
    records, counts = [], {}
    for game in GAMES:
        rows = fetch_game(game, start, end, archive)
        if not rows and (end - start).days >= 14:
            raise ValueError(f"No results for {game} in a period of at least two weeks")
        records.extend(rows)
        counts[game] = {"count":len(rows), "first":min((r["date"] for r in rows), default=None),
                        "last":max((r["date"] for r in rows), default=None)}
        print(f"{game}: {len(rows)} verified draws", flush=True)
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as connection:
        create_db(connection)
        changed = save(connection, records, start, end)
        total = export(connection)
    summary = {"checked_at":stamp,"requested_from":str(start),"requested_to":str(end),
               "games":counts,"changed":changed,"database_total":total,"source":BASE}
    (ROOT / "data/status.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
