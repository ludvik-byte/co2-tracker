"""Celý běh: stáhne všechny zdroje (každý zvlášť, selhání jednoho nezastaví ostatní) a sestaví site.json.

python -m pipeline.run_all
"""
from pipeline import build, fetch_noaa, fetch_owid

FETCHERS = [fetch_noaa, fetch_owid]


def main() -> None:
    results = {f.SOURCE: f.main() for f in FETCHERS}
    build.main()
    failed = [k for k, ok in results.items() if not ok]
    if failed:
        print("Nedostupné zdroje:", ", ".join(failed))


if __name__ == "__main__":
    main()
