# Bay Area Transit and VMT Analysis

Reproducible public-data starter project for exploring transit ridership and vehicle miles traveled (VMT) in the San Francisco Bay Area.

## Setup

This repository uses `uv`; the environment is created in `.venv`.

```bash
uv sync
```

## Download and clean data

```bash
uv run python scripts/fetch_data.py
```

The default BART pull requests hourly station-to-station data for 2019 through 2026 and aggregates it in chunks to monthly origin-destination counts. To choose a smaller set of years:

```bash
uv run python scripts/fetch_data.py --bart-years 2019-2022,2025 --skip-survey
```

The script writes cleaned Parquet files to `data/`:

- `bart_monthly_od.parquet`: monthly BART station-pair trip counts derived from hourly CSV archives.
- `bart_hourly_profile.parquet`: average total trips by hour for weekdays and weekends, derived from service-day/hour totals.
- `mtc_transit_ridership_by_operator.parquet`: operator annual boardings and related measures from MTC's Vital Signs/National Transit Database series.
- `mtc_transit_ridership_by_mode.parquet`: annual regional boardings by transit mode.
- `mtc_transit_ridership_region.parquet`: annual Bay Area transit ridership series.
- `mtc_vmt_by_county.parquet`: annual VMT and VMT per capita for the nine Bay Area counties.
- `mtc_vmt_region.parquet`: annual regional VMT and VMT per capita.
- `sfmta_travel_decision_survey_2021.parquet`: cleaned, weighted 2021 survey responses. Respondent number, interview date, and origin/destination ZIP fields are omitted.

MTC tables are downloaded from public Socrata JSON APIs. BART OD archives are published at [BART Ridership Reports](https://www.bart.gov/about/reports/ridership). The survey workbook comes from the [SFMTA Travel Decision Survey 2021](https://data.sf.gov/Transportation/Travel-Decision-Survey-2021/b7eg-vqw2) attachment.

## Analysis notes

MTC's published ridership series ends in 2022, while its HPMS-derived VMT series runs through 2024. Ridership series report boardings, not unique riders. BART OD counts are monthly station-pair records; county and regional VMT is annual and cannot be assigned to station pairs without a separate, defensible spatial model. Compare overlapping annual or regional periods first and treat relationships as associations, not causal effects. The SFMTA survey is a weighted respondent sample from 2021, not a continuous ridership counter.

Run the exploratory notebook after downloading data:

```bash
uv run jupyter lab
```