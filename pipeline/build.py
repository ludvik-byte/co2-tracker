"""Normalizace, výpočty a export data/site.json (a kopie do site/site.json).

Samostatně: python -m pipeline.build
Build nikdy nespadne kvůli jednomu zdroji: když zdroj chybí nebo je poškozený, použije
předchozí verzi dané sekce ze site.json a označí ji jako nedostupnou od data prvního selhání.
"""
from __future__ import annotations

import json
import math
import shutil
import traceback
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from pipeline import calc
from pipeline.common import CONFIG, RAW, ROOT, load_yaml, now_iso, read_meta

OUT = ROOT / "data" / "site.json"
SITE_COPY = ROOT / "site" / "site.json"
SCHEMA = 1


# ---------------------------------------------------------------- formátování vět

def fmt(x: float | None, dec: int = 1, sign: bool = False) -> str:
    if x is None:
        return "n/a"
    s = f"{x:+.{dec}f}" if sign else f"{x:.{dec}f}"
    return s.replace(".", ",").replace("-", "−")


def pct(x: float | None, dec: int = 1, sign: bool = True) -> str:
    return "n/a" if x is None else fmt(x * 100, dec, sign) + " %"


def clean(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except TypeError:
        pass
    return float(v) if not isinstance(v, (int, str)) else v


def rnd(v, n=3):
    v = clean(v)
    return None if v is None else round(float(v), n)


# ---------------------------------------------------------------- zdroje: načtení

def load_noaa(raw_dir: Path) -> dict:
    mm = pd.read_csv(raw_dir / "noaa" / "co2_mm_mlo.csv", comment="#")
    gr = pd.read_csv(raw_dir / "noaa" / "co2_gr_mlo.csv", comment="#")
    mm = mm[mm["average"] > 0]  # NOAA značí chybějící měsíc -99.99
    gr.columns = ["year", "inc", "unc"]  # year, ann inc, unc
    gr = gr[gr["inc"] > -90]
    return {
        "monthly": [(int(r.year), int(r.month), float(r.average), float(r.deseasonalized)) for r in mm.itertuples()],
        "growth": {int(r.year): float(r.inc) for r in gr.itertuples()},
        "growth_unc": {int(r.year): float(r.unc) for r in gr.itertuples()},
    }


OWID_COLS = ["country", "year", "co2", "co2_per_capita", "coal_co2", "oil_co2", "gas_co2", "cement_co2",
             "flaring_co2", "other_industry_co2", "consumption_co2", "total_ghg", "population"]


def load_owid(raw_dir: Path, owid_names: list[str]) -> dict[str, pd.DataFrame]:
    df = pd.read_csv(raw_dir / "owid" / "owid-co2-data.csv", usecols=OWID_COLS)
    df = df[df["country"].isin(owid_names)]
    out = {}
    for name in owid_names:
        d = df[df["country"] == name].set_index("year").sort_index()
        if d.empty:
            raise ValueError(f"OWID neobsahuje '{name}' (zkontroluj config/players.yaml)")
        out[name] = d
    return out


def col(d: pd.DataFrame, c: str, start: int | None = None) -> dict[int, float]:
    s = d[c].dropna()
    if start is not None:
        s = s[s.index >= start]
    return {int(k): float(v) for k, v in s.items()}


def aligned(series: dict[int, float], years: list[int], scale: float = 1.0, n: int = 3):
    return [None if series.get(y) is None else round(series[y] * scale, n) for y in years]


# ---------------------------------------------------------------- sekce

def source_info(key: str, sources_cfg: dict, raw_dir: Path, data_through: date | None,
                label: str | None, max_age: int, today: date) -> dict:
    cfg, meta = sources_cfg[key], read_meta(key, raw_dir)
    stale = data_through is not None and (today - data_through).days > max_age
    return {
        "name": cfg["name"], "page": cfg["page"], "license": cfg.get("license"),
        "files": cfg.get("files", {}),
        "data_through": label, "data_through_date": data_through.isoformat() if data_through else None,
        "fetched": meta.get("last_success"), "source_updated": meta.get("source_updated"),
        "last_attempt": meta.get("last_attempt"), "unavailable_since": meta.get("unavailable_since"),
        "error": meta.get("error"), "max_age_days": max_age, "stale": bool(stale),
    }


def month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)


def build_physics(noaa: dict, settings: dict) -> dict:
    p = settings["physics"]
    growth = noaa["growth"]
    g5 = calc.rolling_mean(growth, p["window"])
    status, info = calc.physics_status(growth, p["window"], p["stabilising_ppm"])
    y, m, avg, _ = noaa["monthly"][-1]
    prev_year = [r for r in noaa["monthly"] if r[0] == y - 1 and r[1] == m]
    yoy = avg - prev_year[0][2] if prev_year else None
    if status == calc.ON_TRACK:
        s = f"Koncentrace přestává růst: průměrný růst za {p['window']} let je {fmt(info['mean'], 2)} ppm/rok."
    elif status == calc.NO_DATA:
        s = "Pro porovnání pětiletých období chybí data."
    else:
        verb = "zpomaluje" if status == calc.IMPROVING else "nezpomaluje"
        s = (f"Růst koncentrace {verb}. Průměr let {info['year'] - p['window'] + 1} až {info['year']} je "
             f"{fmt(info['mean'], 2)} ppm/rok, v předchozím pětiletí {fmt(info['prev_mean'], 2)} ppm/rok.")
    return {
        "status": status, "sentence": s,
        "latest": {"year": y, "month": m, "ppm": avg, "yoy_ppm": rnd(yoy, 2),
                   "growth_year": max(growth), "growth_ppm": growth[max(growth)],
                   "growth5_year": info.get("year"), "growth5_ppm": rnd(info.get("mean"), 3),
                   "growth5_prev_ppm": rnd(info.get("prev_mean"), 3)},
        "monthly": [[f"{r[0]}-{r[1]:02d}", r[2], r[3]] for r in noaa["monthly"]],
        "growth": [[yy, growth[yy], rnd(g5.get(yy), 3), noaa["growth_unc"].get(yy)] for yy in sorted(growth)],
    }


def player_metrics(p: dict, d: pd.DataFrame, settings: dict, years: list[int]) -> dict:
    t, st = settings["trajectory"], settings["status"]
    by = t["base_year"]
    co2 = col(d, "co2")
    latest = max(co2)
    v = co2[latest]
    base = co2.get(by)
    traj_latest = calc.trajectory_value(base, by, t["co2"], latest) if base else None
    target = base * (1 + t["co2"][t["target_year"]]) if base else None
    rate = calc.cagr(co2, latest, st["cagr_years"])
    need = calc.required_rate(v, latest, target, t["target_year"]) if target else None
    pk = calc.peak(co2)
    v5 = co2.get(latest - st["cagr_years"])
    ghg = col(d, "total_ghg")
    cons = col(d, "consumption_co2")
    pc = col(d, "co2_per_capita")
    return {
        "id": p["id"], "name": p["name"], "role": p.get("role", "player"), "part_of": p.get("part_of"),
        "owid": p["owid"],
        "year": latest, "co2_mt": rnd(v, 1), "per_capita_t": rnd(pc.get(latest), 2),
        "base_mt": rnd(base, 1), "vs_base": rnd(calc.change_pct(v, base), 4),
        "peak_year": pk[0], "peak_mt": rnd(pk[1], 1), "vs_peak": rnd(calc.change_pct(v, pk[1]), 4),
        "traj_mt": rnd(traj_latest, 1), "target_2030_mt": rnd(target, 1),
        "gap_mt": rnd(v - traj_latest, 1) if traj_latest else None,
        "gap_pct": rnd(calc.change_pct(v, traj_latest), 4),
        "cagr5": rnd(rate, 5), "required": rnd(need, 5),
        "change5_mt": rnd(v - v5, 1) if v5 is not None else None,
        "status": calc.classify(rate, need, st["on_track_share"]),
        "consumption_year": max(cons) if cons else None, "consumption_mt": rnd(cons[max(cons)], 1) if cons else None,
        "ghg_year": max(ghg) if ghg else None, "ghg_mt_co2e": rnd(ghg[max(ghg)], 1) if ghg else None,
        "ghg_vs_base": rnd(calc.change_pct(ghg.get(max(ghg)) if ghg else None, ghg.get(by)), 4),
        "series": {
            "co2": aligned(co2, years, 1, 2),
            "per_capita": aligned(pc, years, 1, 3),
            "consumption": aligned(cons, years, 1, 2),
        },
    }


def world_section(w: dict, d: pd.DataFrame, settings: dict, years: list[int]) -> dict:
    t = settings["trajectory"]
    by = t["base_year"]
    co2 = col(d, "co2")
    ghg = col(d, "total_ghg")
    ty = list(range(by, 2051))
    traj = calc.trajectory_series(co2[by], by, t["co2"], ty)
    traj_ghg = calc.trajectory_series(ghg[by], by, t["ghg"], ty) if by in ghg else {}
    status = w["status"]
    wording = {calc.ON_TRACK: "jsou na trajektorii", calc.IMPROVING: "klesají, ale pomaleji, než je potřeba",
               calc.WORSENING: "rostou", calc.NO_DATA: "nelze vyhodnotit"}[status]
    s = (f"Globální fosilní emise CO₂ {wording}. V roce {w['year']} byly {fmt(w['co2_mt'] / 1000, 1)} Gt, "
         f"tedy {pct(w['vs_base'])} proti roku {by}; trajektorie pro rok {w['year']} je {fmt(w['traj_mt'] / 1000, 1)} Gt.")
    fuels = {k: aligned(col(d, f"{k}_co2"), years, 1 / 1000, 3) for k in
             ["coal", "oil", "gas", "cement", "flaring", "other_industry"]}
    return {
        "status": status, "sentence": s, "latest": {k: v for k, v in w.items() if k != "series"},
        "years": years,
        "co2_gt": aligned(co2, years, 1 / 1000, 3),
        "fuels_gt": fuels,
        "ghg_gt_co2e": aligned(ghg, years, 1 / 1000, 3),
        "trajectory": {"years": ty, "co2_gt": [round(traj[y] / 1000, 3) for y in ty],
                       "ghg_gt_co2e": [round(traj_ghg[y] / 1000, 3) for y in ty] if traj_ghg else None},
    }


def players_summary(players: list[dict]) -> dict:
    ranked = [p for p in players if p["role"] != "world"]
    counts = {k: sum(p["status"] == k for p in ranked) for k in
              (calc.ON_TRACK, calc.IMPROVING, calc.WORSENING, calc.NO_DATA)}
    # "Kdo táhne výsledek": absolutní změna za 5 let, bez hráčů, kteří jsou součástí jiného (Německo v EU27).
    drivers = [p for p in ranked if not p.get("part_of") and p["change5_mt"] is not None]
    up = sorted(drivers, key=lambda p: -p["change5_mt"])[:3]
    down = sorted(drivers, key=lambda p: p["change5_mt"])[:3]
    n = len(ranked)
    if counts[calc.ON_TRACK] * 2 >= n:
        status = calc.ON_TRACK
    elif counts[calc.ON_TRACK] + counts[calc.IMPROVING] > counts[calc.WORSENING]:
        status = calc.IMPROVING
    else:
        status = calc.WORSENING
    yr = max((p["year"] for p in ranked), default=None)

    def names(lst, positive):
        return ", ".join(f"{p['name']} ({fmt(p['change5_mt'], 0, True)} Mt)" for p in lst
                         if (p["change5_mt"] > 0) == positive) or "nikdo"
    s = (f"Na trajektorii je {counts[calc.ON_TRACK]} z {n}, zlepšuje se {counts[calc.IMPROVING]}, "
         f"zhoršuje se {counts[calc.WORSENING]}. Největší nárůst za 5 let: {names(up, True)}. "
         f"Největší pokles: {names(down, False)}.")
    return {"status": status, "sentence": s, "counts": counts, "n": n, "year": yr,
            "drivers_up": [p["id"] for p in up if p["change5_mt"] > 0],
            "drivers_down": [p["id"] for p in down if p["change5_mt"] < 0]}


# ---------------------------------------------------------------- hlavní běh

def build(raw_dir: Path = RAW, config_dir: Path = CONFIG, prev: dict | None = None,
          today: date | None = None) -> dict:
    today = today or date.today()
    prev = prev or {}
    settings = load_yaml("settings.yaml", config_dir)
    sources_cfg = load_yaml("sources.yaml", config_dir)
    players_cfg = load_yaml("players.yaml", config_dir)["players"]
    fr = settings["freshness_days"]
    out = {"schema": SCHEMA, "generated": now_iso(), "today": today.isoformat(),
           "settings": {"trajectory": settings["trajectory"], "status": settings["status"],
                        "physics": settings["physics"]},
           "sources": {}, "errors": {}}

    def fallback(section_keys, key, err):
        out["errors"][key] = err
        for k in section_keys:
            if prev.get(k) is not None:
                out[k] = prev[k]
                out[k]["from_previous_run"] = True
            else:
                out[k] = None
        old = (prev.get("sources") or {}).get(key)
        info = source_info(key, sources_cfg, raw_dir, None, None, 0, today)
        if old:
            info.update({k: old.get(k) for k in ("data_through", "data_through_date", "fetched", "source_updated")})
        info["unavailable_since"] = info["unavailable_since"] or info["last_attempt"] or out["generated"]
        out["sources"][key] = info

    # NOAA
    try:
        noaa = load_noaa(raw_dir)
        y, m = noaa["monthly"][-1][:2]
        out["physics"] = build_physics(noaa, settings)
        out["sources"]["noaa"] = source_info("noaa", sources_cfg, raw_dir, month_end(y, m), f"{y}-{m:02d}",
                                             fr["noaa_monthly"], today)
    except Exception:  # noqa: BLE001
        fallback(["physics"], "noaa", traceback.format_exc(limit=2))

    # OWID
    try:
        owid = load_owid(raw_dir, [p["owid"] for p in players_cfg])
        latest = max(int(d["co2"].dropna().index.max()) for d in owid.values())
        years = list(range(settings["series_start"], latest + 1))
        players = [player_metrics(p, owid[p["owid"]], settings, years) for p in players_cfg]
        world = next(p for p in players if p["role"] == "world")
        out["world"] = world_section(world, owid[world["owid"]], settings, years)
        out["players"] = {"years": years, "items": players}
        out["players_summary"] = players_summary(players)
        out["sources"]["owid"] = source_info("owid", sources_cfg, raw_dir, date(latest, 12, 31), str(latest),
                                             fr["owid"], today)
    except Exception:  # noqa: BLE001
        fallback(["world", "players", "players_summary"], "owid", traceback.format_exc(limit=2))

    return out


def main() -> dict:
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else None
    data = build(prev=prev)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    SITE_COPY.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT, SITE_COPY)
    for k, v in data["sources"].items():
        flag = "NEDOSTUPNÉ" if v.get("unavailable_since") else ("ZASTARALÉ" if v.get("stale") else "ok")
        print(f"[{k}] data do {v.get('data_through')}  {flag}")
    for k in ("physics", "world", "players_summary"):
        if data.get(k):
            print(f"  {k}: {data[k]['status']}  {data[k]['sentence']}")
    return data


if __name__ == "__main__":
    main()
