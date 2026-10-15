"""Build na syntetických datech, včetně výpadku zdroje."""
import json
import shutil
from datetime import date
from pathlib import Path

import pytest

from pipeline import build as b
from pipeline import calc

CONFIG = Path(__file__).resolve().parent.parent / "config"
TODAY = date(2026, 9, 25)


def write_config(tmp: Path) -> Path:
    cfg = tmp / "config"
    cfg.mkdir()
    for f in ("settings.yaml", "sources.yaml"):
        shutil.copy(CONFIG / f, cfg / f)
    (cfg / "players.yaml").write_text(
        "players:\n"
        "  - {id: WLD, name: Svět, owid: World, role: world}\n"
        "  - {id: AAA, name: Klesající, owid: Aland, role: player}\n"
        "  - {id: BBB, name: Rostoucí, owid: Bland, role: player}\n"
        "  - {id: CCC, name: Součást, owid: Cland, role: home, part_of: AAA}\n",
        encoding="utf-8")
    return cfg


def write_owid(raw: Path, gap_year: int | None = None):
    d = raw / "owid"
    d.mkdir(parents=True)
    rows = ["country,year,co2,co2_per_capita,coal_co2,oil_co2,gas_co2,cement_co2,flaring_co2,"
            "other_industry_co2,consumption_co2,total_ghg,population"]
    for y in range(1990, 2025):
        vals = {"World": 30000 + 100 * (y - 1990), "Aland": 1000 * 0.9 ** (y - 2019) if y >= 2019 else 1000,
                "Bland": 500 * 1.02 ** (y - 1990), "Cland": 100.0}
        for c, v in vals.items():
            if c == "Aland" and y == gap_year:
                rows.append(f"{c},{y},,,,,,,,,,,")
                continue
            rows.append(f"{c},{y},{v},{v / 100},{v / 3},{v / 3},{v / 3},0,0,0,{v},{v * 1.3},100")
    (d / "owid-co2-data.csv").write_text("\n".join(rows), encoding="utf-8")


def write_noaa(raw: Path):
    d = raw / "noaa"
    d.mkdir(parents=True)
    mm = ["# comment", "year,month,decimal date,average,deseasonalized,ndays,sdev,unc"]
    for y in range(2010, 2027):
        for m in range(1, 13):
            if y == 2026 and m > 8:
                break
            mm.append(f"{y},{m},{y + m / 12:.4f},{390 + 2 * (y - 2010) + m / 12:.2f},{390 + 2 * (y - 2010):.2f},20,0.3,0.1")
    gr = ["# comment", "year,ann inc,unc"] + [f"{y},{3.0 if y < 2021 else 2.0},0.1" for y in range(2010, 2026)]
    (d / "co2_mm_mlo.csv").write_text("\n".join(mm), encoding="utf-8")
    (d / "co2_gr_mlo.csv").write_text("\n".join(gr), encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    cfg = write_config(tmp_path)
    raw = tmp_path / "raw"
    return cfg, raw


def test_full_build(env):
    cfg, raw = env
    write_owid(raw)
    write_noaa(raw)
    out = b.build(raw, cfg, today=TODAY)
    assert out["errors"] == {}
    assert out["physics"]["status"] == calc.IMPROVING
    items = {p["id"]: p for p in out["players"]["items"]}
    assert items["AAA"]["status"] == calc.ON_TRACK        # -10 % ročně > 80 % potřebného
    assert items["BBB"]["status"] == calc.WORSENING
    assert items["AAA"]["vs_base"] == pytest.approx(0.9 ** 5 - 1, abs=1e-4)
    # Součást jiného hráče se nepočítá mezi tahouny výsledku
    s = out["players_summary"]
    assert "CCC" not in s["drivers_up"] + s["drivers_down"]
    assert s["drivers_down"] == ["AAA"]
    # Trajektorie světa: 2030 = 52 % hodnoty 2019
    t = out["world"]["trajectory"]
    assert t["co2_gt"][t["years"].index(2030)] == pytest.approx(32.9 * 0.52, abs=1e-3)
    assert out["sources"]["owid"]["stale"] is False
    json.dumps(out)  # musí jít serializovat


def test_gap_in_data_stays_gap(env):
    cfg, raw = env
    write_owid(raw, gap_year=2020)
    write_noaa(raw)
    out = b.build(raw, cfg, today=TODAY)
    p = next(p for p in out["players"]["items"] if p["id"] == "AAA")
    years = out["players"]["years"]
    assert p["series"]["co2"][years.index(2020)] is None   # žádná interpolace


def test_missing_source_does_not_crash(env):
    cfg, raw = env
    write_noaa(raw)                     # OWID chybí úplně
    out = b.build(raw, cfg, today=TODAY)
    assert out["physics"]["status"] == calc.IMPROVING
    assert out["world"] is None and out["players"] is None
    assert "owid" in out["errors"]
    assert out["sources"]["owid"]["unavailable_since"] is not None


def test_missing_source_uses_previous_run(env):
    cfg, raw = env
    write_owid(raw)
    write_noaa(raw)
    first = json.loads(json.dumps(b.build(raw, cfg, today=TODAY)))
    shutil.rmtree(raw / "noaa")
    second = b.build(raw, cfg, prev=first, today=TODAY)
    assert second["physics"]["from_previous_run"] is True
    assert second["physics"]["latest"] == first["physics"]["latest"]
    assert second["sources"]["noaa"]["data_through"] == "2026-08"
    assert second["sources"]["noaa"]["unavailable_since"] is not None
    assert second["world"]["status"] == first["world"]["status"]


def test_stale_flag(env):
    cfg, raw = env
    write_owid(raw)
    write_noaa(raw)
    out = b.build(raw, cfg, today=date(2027, 6, 1))
    assert out["sources"]["noaa"]["stale"] is True
    assert out["sources"]["owid"]["stale"] is True   # data 2024, po více než 790 dnech
