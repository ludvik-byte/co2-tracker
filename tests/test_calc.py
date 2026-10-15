import math

import pytest

from pipeline import calc

CUTS = {2030: -0.48, 2050: -0.99}


def test_trajectory_milestones():
    assert calc.trajectory_value(100, 2019, CUTS, 2019) == 100
    assert calc.trajectory_value(100, 2019, CUTS, 2030) == pytest.approx(52)
    assert calc.trajectory_value(100, 2019, CUTS, 2050) == pytest.approx(1)


def test_trajectory_is_linear_between_milestones():
    # 2019 -> 2030 je 11 let, pokles o 48 bodů, tedy 48/11 za rok
    assert calc.trajectory_value(100, 2019, CUTS, 2024) == pytest.approx(100 - 5 * 48 / 11)
    assert calc.trajectory_value(100, 2019, CUTS, 2040) == pytest.approx((52 + 1) / 2)


def test_trajectory_outside_range():
    assert calc.trajectory_value(100, 2019, CUTS, 2018) is None
    assert calc.trajectory_value(100, 2019, CUTS, 2060) == pytest.approx(1)


def test_cagr_basic():
    s = {2019: 100.0, 2024: 100.0 * 0.95 ** 5}
    assert calc.cagr(s, 2024, 5) == pytest.approx(-0.05)


def test_cagr_missing_year_returns_none():
    # žádné domýšlení: chybí-li počáteční rok, tempo nelze spočítat
    assert calc.cagr({2024: 90.0}, 2024, 5) is None
    assert calc.cagr({2019: 100.0}, 2024, 5) is None


def test_required_rate():
    r = calc.required_rate(100, 2024, 50, 2030)
    assert (1 + r) ** 6 * 100 == pytest.approx(50)
    assert r < 0


def test_required_rate_already_below_target():
    assert calc.required_rate(40, 2024, 50, 2030) > 0


def test_required_rate_invalid():
    assert calc.required_rate(100, 2030, 50, 2030) is None
    assert calc.required_rate(None, 2024, 50, 2030) is None


@pytest.mark.parametrize("actual, needed, expected", [
    (-0.08, -0.10, calc.ON_TRACK),      # 80 % potřebného tempa = hranice
    (-0.079, -0.10, calc.IMPROVING),    # těsně pod hranicí
    (-0.12, -0.10, calc.ON_TRACK),      # rychleji, než je potřeba
    (-0.01, -0.10, calc.IMPROVING),
    (0.0, -0.10, calc.WORSENING),       # stagnace = zhoršuje se
    (0.03, -0.10, calc.WORSENING),
    (-0.01, 0.02, calc.ON_TRACK),       # už pod cílem a neroste
    (0.01, 0.02, calc.WORSENING),       # pod cílem, ale roste
    (None, -0.10, calc.NO_DATA),
    (-0.05, None, calc.NO_DATA),
])
def test_classify(actual, needed, expected):
    assert calc.classify(actual, needed, 0.8) == expected


def test_change_pct_and_peak():
    assert calc.change_pct(90, 100) == pytest.approx(-0.1)
    assert calc.change_pct(90, None) is None
    assert calc.peak({2000: 5, 2010: 9, 2020: 7}) == (2010, 9)
    assert calc.peak({}) is None


def test_rolling_mean_requires_full_window():
    s = {2000: 1, 2001: 2, 2002: 3, 2004: 5}  # chybí 2003
    rm = calc.rolling_mean(s, 3)
    assert rm == {2002: 2}


@pytest.mark.parametrize("recent, expected", [
    (2.0, calc.IMPROVING),
    (3.0, calc.WORSENING),
    (2.5, calc.WORSENING),   # stejné tempo = nezpomaluje
    (0.3, calc.ON_TRACK),
])
def test_physics_status(recent, expected):
    growth = {y: 2.5 for y in range(2011, 2016)}
    growth.update({y: recent for y in range(2016, 2021)})
    status, info = calc.physics_status(growth, 5, 0.5)
    assert status == expected
    assert info["year"] == 2020
    assert math.isclose(info["prev_mean"], 2.5)


def test_physics_status_empty():
    assert calc.physics_status({}, 5, 0.5)[0] == calc.NO_DATA
