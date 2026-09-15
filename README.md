# Lutrija rezultati – javna arhiva

Izvor: https://lutrija.rs/rezultati. Nezavisna arhiva javnih rezultata igara Loto 7/39, Loto 5 i Bingo.

GitHub Actions proverava zvaničan izvor svakog dana u 22:00, Europe/Belgrade, uz automatsko prilagođavanje letnjem/zimskom vremenu. GitHub može odložiti početak kada su serveri opterećeni. Pri neuspehu se pokušava ponovo do tri puta; neuspešan import ne objavljuje nepotpun skup podataka.

`data/results.sqlite3` je trajna online arhiva. `data/feed.json` je atomski objavljen skup rezultata i vremena poslednje uspešne provere koji čita sajt. Sajt proverava feed najkasnije pri sledećem otvaranju stranice, uz kratak keš. Git istorija čuva prethodne verzije, a sirovi odgovori čuvaju se kao Actions artefakti 30 dana.

Početni `data/seed.json` sadrži 131 provereno izvlačenje za period 14.03–14.09.2026. Svako uspešno pokretanje čuva datum provere čak i kada nema novih izvlačenja. Status i dnevnici pokretanja nalaze se u odeljku Actions. Ručno pokretanje: Update lottery results → Run workflow; opcija backfill proverava proteklih šest meseci.

Ovaj repozitorijum ne sadrži pristupne ključeve niti privatni kod sajta.
