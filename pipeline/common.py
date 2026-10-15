"""Sdílené pomůcky: cesty, config, stahování s cache a stavový soubor zdroje.

Každý zdroj má složku data/raw/<zdroj>/ se staženými soubory a meta.json:
    last_attempt       kdy jsme naposledy zkoušeli stáhnout (UTC ISO)
    last_success       kdy se stažení naposledy povedlo
    unavailable_since  od kdy zdroj selhává (None, když poslední pokus prošel)
    error              text poslední chyby
    source_updated     datum aktualizace uvedené zdrojem, pokud ho zdroj uvádí
Při chybě se starý soubor nemaže, build ho použije a stránka ukáže varování.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
RAW = Path(os.environ.get("CO2_RAW_DIR", ROOT / "data" / "raw"))

USER_AGENT = "co2-tracker (github.com/ludvik-byte/co2-tracker)"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_yaml(name: str, config_dir: Path = CONFIG) -> dict:
    with open(config_dir / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_meta(source: str, raw_dir: Path = RAW) -> dict:
    p = raw_dir / source / "meta.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def write_meta(source: str, meta: dict, raw_dir: Path = RAW) -> None:
    d = raw_dir / source
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def download(url: str, dest: Path, retries: int = 3, timeout: int = 60) -> None:
    """Stáhne soubor atomicky (přes .part), aby nedokončené stažení nepřepsalo cache."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            if tmp.stat().st_size == 0:
                raise ValueError(f"prázdný soubor z {url}")
            tmp.replace(dest)
            return
        except Exception as e:  # noqa: BLE001 — zkusíme znovu, pak chybu předáme dál
            last_err = e
            time.sleep(2 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    raise RuntimeError(f"{url}: {last_err}")


def run_fetch(source: str, fetch_fn, raw_dir: Path = RAW) -> bool:
    """Spustí stahovací funkci zdroje a zapíše výsledek do meta.json. Nikdy nevyhodí výjimku."""
    meta = read_meta(source, raw_dir)
    meta["last_attempt"] = now_iso()
    try:
        extra = fetch_fn(raw_dir / source) or {}
        meta.update(extra)
        meta["last_success"] = meta["last_attempt"]
        meta["unavailable_since"] = None
        meta["error"] = None
        ok = True
    except Exception as e:  # noqa: BLE001
        meta["error"] = str(e)[:500]
        meta["unavailable_since"] = meta.get("unavailable_since") or meta["last_attempt"]
        ok = False
    write_meta(source, meta, raw_dir)
    print(f"[{source}] {'OK' if ok else 'CHYBA: ' + meta['error']}")
    return ok
