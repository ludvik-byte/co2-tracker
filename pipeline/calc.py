"""Čisté výpočty bez I/O. Všechny definice jsou popsané i v README.

Řady jsou slovníky {rok: hodnota}. Chybějící rok v řadě prostě není, nic se nedopočítává.
"""
from __future__ import annotations

from typing import Mapping

Series = Mapping[int, float]

ON_TRACK = "na_trajektorii"
IMPROVING = "zlepsuje_se"
WORSENING = "zhorsuje_se"
NO_DATA = "bez_dat"


def trajectory_value(base_value: float, base_year: int, cuts: Mapping[int, float], year: int) -> float | None:
    """Požadovaná hodnota v daném roce.

    Lineárně z hodnoty v základním roce na base*(1+cut) v každém milníku (cuts = {2030: -0.48, 2050: -0.99}).
    Před základním rokem None, po posledním milníku zůstává hodnota posledního milníku.
    """
    if year < base_year:
        return None
    points = [(base_year, base_value)] + [(y, base_value * (1 + c)) for y, c in sorted(cuts.items())]
    for (y0, v0), (y1, v1) in zip(points, points[1:]):
        if year <= y1:
            return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    return points[-1][1]


def trajectory_series(base_value: float, base_year: int, cuts: Mapping[int, float], years) -> dict[int, float]:
    return {y: trajectory_value(base_value, base_year, cuts, y) for y in years if y >= base_year}


def cagr(series: Series, end_year: int, years: int = 5) -> float | None:
    """Průměrná roční změna (CAGR) mezi end_year-years a end_year. Chybí-li kterýkoli konec, None."""
    a, b = series.get(end_year - years), series.get(end_year)
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return (b / a) ** (1 / years) - 1


def required_rate(current: float, current_year: int, target: float, target_year: int) -> float | None:
    """Roční tempo (CAGR), které z poslední známé hodnoty dovede na cíl v target_year.

    Záporné číslo = potřebný pokles. Když už je hodnota pod cílem, výsledek je >= 0.
    """
    n = target_year - current_year
    if n <= 0 or current is None or current <= 0 or target is None or target <= 0:
        return None
    return (target / current) ** (1 / n) - 1


def classify(actual_rate: float | None, needed_rate: float | None, on_track_share: float = 0.8) -> str:
    """Semafor hráče.

    na_trajektorii: skutečný roční pokles >= on_track_share * potřebného ročního poklesu
                    (když už je hráč pod cílem, stačí, že emise nerostou)
    zlepsuje_se:    emise klesají, ale pomaleji
    zhorsuje_se:    emise rostou nebo stagnují (tempo >= 0)
    """
    if actual_rate is None or needed_rate is None:
        return NO_DATA
    needed_decline = max(0.0, -needed_rate)
    actual_decline = -actual_rate
    if needed_decline == 0:
        return ON_TRACK if actual_rate <= 0 else WORSENING
    if actual_decline >= on_track_share * needed_decline - 1e-12:  # tolerance zaokrouhlení na hranici
        return ON_TRACK
    if actual_rate < 0:
        return IMPROVING
    return WORSENING


def change_pct(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference == 0:
        return None
    return value / reference - 1


def peak(series: Series) -> tuple[int, float] | None:
    if not series:
        return None
    y = max(series, key=lambda k: series[k])
    return y, series[y]


def rolling_mean(series: Series, window: int) -> dict[int, float]:
    """Klouzavý průměr přes posledních `window` let; jen když jsou všechny roky okna k dispozici."""
    out = {}
    for y in sorted(series):
        vals = [series.get(y - i) for i in range(window)]
        if all(v is not None for v in vals):
            out[y] = sum(vals) / window
    return out


def physics_status(growth: Series, window: int = 5, stabilising_ppm: float = 0.5) -> tuple[str, dict]:
    """Semafor fyziky z ročního růstu koncentrace (ppm/rok).

    Porovnává průměr posledních `window` let s průměrem předchozích `window` let (bez překryvu).
    na_trajektorii: průměrný růst < stabilising_ppm (koncentrace přestává růst)
    zlepsuje_se:    průměrný růst je nižší než v předchozím období
    zhorsuje_se:    průměrný růst je stejný nebo vyšší
    """
    rm = rolling_mean(growth, window)
    if not rm:
        return NO_DATA, {}
    last = max(rm)
    now = rm[last]
    prev = rm.get(last - window)
    info = {"year": last, "mean": now, "prev_year": last - window if prev is not None else None, "prev_mean": prev}
    if now < stabilising_ppm:
        return ON_TRACK, info
    if prev is None:
        return NO_DATA, info
    return (IMPROVING if now < prev else WORSENING), info
