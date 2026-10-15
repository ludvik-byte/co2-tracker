# Cesta na polovinu: CO₂ tracker

Statický přehled, který každý týden ukazuje, jak svět a jeho největší emitenti plní trajektorii IPCC pro 1,5 °C. Data ze zdrojů, žádné odhady.

Stránka: https://ludvik-byte.github.io/co2-tracker/

## Spuštění

```bash
uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt
.venv/bin/python -m pipeline.run_all      # stáhne zdroje a vytvoří data/site.json
.venv/bin/python -m pytest -q             # testy výpočtů
python3 -m http.server 8765 --directory site
```

Každý zdroj jde stáhnout samostatně: `python -m pipeline.fetch_noaa`, `python -m pipeline.fetch_owid`.

## Přidání hráče

Jeden řádek v `config/players.yaml`, s názvem země přesně podle `owid-co2-data.csv` (sloupec `country`).

## Definice

* **Trajektorie:** přímka z hodnoty 2019 na −48 % v 2030 a −99 % v 2050 (IPCC AR6 WG3, SPM C.1, cesty C1, CO₂). Cíl −43 % / −84 % platí pro skleníkové plyny celkem (CO₂e).
* **Tempo:** průměrná roční změna (CAGR) za posledních 5 let.
* **Potřebné tempo:** roční změna, která z poslední známé hodnoty dovede na cíl 2030.
* **Na trajektorii:** skutečný roční pokles je aspoň 80 % potřebného. **Zlepšuje se:** emise klesají, ale pomaleji. **Zhoršuje se:** emise rostou nebo stagnují.
* **Fyzika:** pětiletý průměr ročního růstu koncentrace proti předchozímu pětiletí; zelená pod 0,5 ppm/rok.
* Chybějící data se nedopočítávají.

## Automatizace

GitHub Actions (`.github/workflows/update.yml`) běží každé pondělí v 06:00 UTC a při každém pushi: testy, stažení zdrojů, build, commit `site.json` a nasazení na GitHub Pages. Když zdroj nejede, stránka ukáže poslední data s upozorněním „data nedostupná od“.
