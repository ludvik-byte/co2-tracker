"""Stáhne owid-co2-data.csv (Our World in Data, postavené na Global Carbon Budget).

Samostatně: python -m pipeline.fetch_owid
"""
from __future__ import annotations

from pathlib import Path

import requests

from pipeline.common import USER_AGENT, download, load_yaml, run_fetch

SOURCE = "owid"


def last_commit_date(api_url: str) -> str | None:
    """Datum posledního commitu souboru na GitHubu = datum aktualizace u zdroje. Nepovinné."""
    try:
        r = requests.get(api_url, timeout=20, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r.json()[0]["commit"]["committer"]["date"][:10]
    except Exception:  # noqa: BLE001 — bez data aktualizace se obejdeme
        return None


def fetch(dest_dir: Path) -> dict:
    cfg = load_yaml("sources.yaml")[SOURCE]
    download(cfg["files"]["co2"], dest_dir / "owid-co2-data.csv", timeout=120)
    return {"source_updated": last_commit_date(cfg["commits_api"])}


def main() -> bool:
    return run_fetch(SOURCE, fetch)


if __name__ == "__main__":
    main()
