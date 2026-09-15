import copy
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scraper import create_db, export, fetch_game, normalize, save, six_months_ago

START, END = dt.date(2026, 8, 15), dt.date(2026, 9, 14)
FIXTURES = Path(__file__).parent / "tests/fixtures"


def sample(game):
    return json.loads((FIXTURES / f"{game}.json").read_text(encoding="utf-8"))


class ScraperTests(unittest.TestCase):
    def test_real_api_fields_including_bonus_and_variable_bingo_length(self):
        for game in ("loto", "loto5", "bingo"):
            value = normalize(game, sample(game), START, END)
            self.assertEqual(value["details"], sample(game))
        loto = normalize("loto", sample("loto"), START, END)
        self.assertEqual(loto["numbers"], [4, 5, 7, 16, 19, 29, 30])
        self.assertEqual(normalize("loto5", sample("loto5"), START, END)["bonus"], 4)
        self.assertEqual(len(normalize("bingo", sample("bingo"), START, END)["numbers"]), 48)

    def test_rejects_bad_or_stale_results(self):
        row = sample("loto")
        row["LotoNumbers"][1] = row["LotoNumbers"][0]
        with self.assertRaises(ValueError):
            normalize("loto", row, START, END)
        with self.assertRaises(ValueError):
            normalize("loto", sample("loto"), dt.date(2026, 3, 1), dt.date(2026, 3, 31))
        row = sample("loto5")
        del row["Broj_Plus"]
        with self.assertRaises(ValueError):
            normalize("loto5", row, START, END)

    def test_pagination_checks_counts_and_duplicates(self):
        rows = []
        for n in range(11):
            row = sample("loto")
            row["Round"] = 50 + n
            rows.append(row)
        def page(game, start, end, number, archive):
            return {"Err":"OK", "TotalCount":11, "TotalPages":2, "data":rows[(number-1)*10:number*10]}
        result = fetch_game("loto", dt.date(2026, 9, 1), END, Path("unused"), fetch=page)
        self.assertEqual(len(result), 11)
        rows[-1] = rows[0]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            fetch_game("loto", dt.date(2026, 9, 1), END, Path("unused"), fetch=page)
        rows.pop()
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            fetch_game("loto", dt.date(2026, 9, 1), END, Path("unused"), fetch=page)

    def test_idempotency_corrections_and_export(self):
        with sqlite3.connect(":memory:") as connection, tempfile.TemporaryDirectory() as directory:
            create_db(connection)
            row = normalize("loto", sample("loto"), START, END)
            self.assertEqual(save(connection, [row], START, END), 1)
            self.assertEqual(save(connection, [row], START, END), 0)
            revised = copy.deepcopy(row)
            revised["details"]["LotoPrizes"][0]["Winners"] = 1
            self.assertEqual(save(connection, [revised], START, END), 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM draws").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM revisions").fetchone()[0], 1)
            target = Path(directory) / "results.json"
            self.assertEqual(export(connection, target), 1)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), [revised])
            revised["date"] = "2026-09-12"
            revised["details"]["Date"] = "2026-09-12T00:00:00"
            self.assertEqual(save(connection, [revised], START, END), 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM draws").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT draw_date FROM draws").fetchone()[0], "2026-09-12")

    def test_six_month_window_clamps_month_end(self):
        self.assertEqual(six_months_ago(dt.date(2026, 8, 31)), dt.date(2026, 2, 28))


if __name__ == "__main__":
    unittest.main()
