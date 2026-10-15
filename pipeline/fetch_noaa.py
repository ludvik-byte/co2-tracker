"""Stáhne měsíční koncentrace CO2 a roční růst z NOAA GML (Mauna Loa).

Samostatně: python -m pipeline.fetch_noaa
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pipeline.common import download, load_yaml, run_fetch

SOURCE = "noaa"


def file_creation(path: Path) -> str | None:
    """NOAA uvádí v hlavičce '# File Creation: Sat Sep  5 03:55:47 2026'."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("#"):
                break
            m = re.search(r"File Creation:\s*(.+)$", line)
            if m:
                try:
                    return datetime.strptime(" ".join(m.group(1).split()), "%a %b %d %H:%M:%S %Y").date().isoformat()
                except ValueError:
                    return None
    return None


def fetch(dest_dir: Path) -> dict:
    files = load_yaml("sources.yaml")[SOURCE]["files"]
    download(files["monthly"], dest_dir / "co2_mm_mlo.csv")
    download(files["growth"], dest_dir / "co2_gr_mlo.csv")
    return {"source_updated": file_creation(dest_dir / "co2_mm_mlo.csv")}


def main() -> bool:
    return run_fetch(SOURCE, fetch)


if __name__ == "__main__":
    main()
