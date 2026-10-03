"""Download and clean public Bay Area transit and VMT datasets."""

from __future__ import annotations

import argparse
import gzip
import re
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests
from pandas.api.types import is_object_dtype, is_string_dtype

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MTC_BASE = "https://data.bayareametro.gov/resource"
MTC_TABLES = {
    "mtc_transit_ridership_by_operator": "8yy6-v2qd",
    "mtc_transit_ridership_by_mode": "aei4-5fzf",
    "mtc_transit_ridership_region": "t2mj-tpzf",
    "mtc_vmt_by_county": "avsp-dwpp",
    "mtc_vmt_region": "ruva-qh74",
}
SURVEY_URL = (
    "https://data.sf.gov/api/views/b7eg-vqw2/files/"
    "58cbdef4-865c-4cb3-86ad-335e2c808591"
    "?download=true&filename=TDS_2021_data.xlsx"
)
BART_URL = (
    "https://afcweb.bart.gov/ridership/origin-destination/"
    "date-hour-soo-dest-{year}.csv.gz"
)


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names and trim surrounding whitespace in text."""
    normalized = [
        re.sub(r"_+", "_", re.sub(r"[^0-9a-z]+", "_", str(column).lower())).strip("_")
        for column in frame.columns
    ]
    counts: dict[str, int] = {}
    unique: list[str] = []
    for column in normalized:
        count = counts.get(column, 0)
        unique.append(column if count == 0 else f"{column}_{count + 1}")
        counts[column] = count + 1
    result = frame.copy()
    result.columns = unique
    for column in result.columns:
        if is_object_dtype(result[column].dtype) or is_string_dtype(result[column].dtype):
            result[column] = result[column].map(
                lambda value: value.strip() if isinstance(value, str) else value
            ).replace("", pd.NA)
    return result


def prepare_bart_frame(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [
        "service_date", "hour", "origin_station", "destination_station", "trips"
    ]
    frame["service_date"] = pd.to_datetime(frame["service_date"], errors="coerce")
    frame["hour"] = pd.to_numeric(frame["hour"], errors="coerce")
    frame["trips"] = pd.to_numeric(frame["trips"], errors="coerce")
    return frame.dropna(subset=["service_date", "hour", "trips"])


def aggregate_bart_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate BART hourly rows to monthly station-pair trip counts."""
    frame = prepare_bart_frame(frame).dropna(
        subset=["origin_station", "destination_station"]
    )
    frame["year_month"] = frame["service_date"].dt.to_period("M").astype(str)
    for column in ("origin_station", "destination_station"):
        frame[column] = frame[column].astype("string").str.strip()
    return frame.groupby(
        ["year_month", "origin_station", "destination_station"],
        as_index=False,
        observed=True,
    )["trips"].sum()


def aggregate_bart_daily_hour(frame: pd.DataFrame) -> pd.DataFrame:
    """Sum station-pair trips to service-day and hour totals."""
    frame = prepare_bart_frame(frame)
    return frame.groupby(
        ["service_date", "hour"], as_index=False, observed=True
    )["trips"].sum()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    if frame.empty:
        raise ValueError(f"Refusing to write empty dataset: {path}")
    frame.to_parquet(path, index=False)
    print(f"Wrote {len(frame):,} rows x {len(frame.columns):,} columns: {path}")


def fetch_mtc_tables(session: requests.Session, output_dir: Path) -> None:
    numeric = {
        "year", "annual_boardings", "est_weekday_boardings", "percentchg_1991",
        "servicepopulation", "percapita_annual_boardings", "vmt", "vmt_per_capita",
    }
    for name, table_id in MTC_TABLES.items():
        url = f"{MTC_BASE}/{table_id}.json"
        response = session.get(url, params={"$limit": 50000}, timeout=60)
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list) or not records:
            raise ValueError(f"Expected tabular JSON records from {url}")
        frame = normalize_frame(pd.DataFrame.from_records(records))
        frame = frame.drop(columns=[column for column in frame if column.startswith("@")])
        frame = frame.rename(
            columns={
                "system": "operator",
                "system_full_name": "operator_full_name",
                "est_weekday_boardings": "estimated_weekday_boardings",
            }
        )
        for column in numeric.intersection(frame.columns):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        write_parquet(frame, output_dir / f"{name}.parquet")


def fetch_bart_od(
    session: requests.Session, output_dir: Path, years: list[int]
) -> None:
    columns = [
        "service_date", "hour", "origin_station", "destination_station", "trips"
    ]
    outputs: list[pd.DataFrame] = []
    hourly_parts: list[pd.DataFrame] = []
    for year in years:
        url = BART_URL.format(year=year)
        response = session.get(url, stream=True, timeout=(30, 300))
        response.raise_for_status()
        year_parts: list[pd.DataFrame] = []
        try:
            with response, gzip.GzipFile(fileobj=response.raw) as compressed:
                chunks = pd.read_csv(
                    compressed,
                    header=None,
                    names=columns,
                    chunksize=500_000,
                    dtype={"origin_station": "string", "destination_station": "string"},
                )
                for chunk in chunks:
                    part = aggregate_bart_frame(chunk)
                    if not part.empty:
                        year_parts.append(part)
                    hourly_parts.append(aggregate_bart_daily_hour(chunk))
        except pd.errors.EmptyDataError:
            print(f"Skipping empty BART archive for {year}: {url}")
            continue
        if not year_parts:
            print(f"Skipping BART archive with no usable rows for {year}: {url}")
            continue
        yearly = pd.concat(year_parts, ignore_index=True).groupby(
            ["year_month", "origin_station", "destination_station"],
            as_index=False,
            observed=True,
        )["trips"].sum()
        yearly["source_year"] = year
        yearly["source_url"] = url
        outputs.append(yearly)
        print(f"BART {year}: {len(yearly):,} monthly OD rows")
    if not outputs:
        raise ValueError("No usable BART OD archives were downloaded")
    write_parquet(pd.concat(outputs, ignore_index=True), output_dir / "bart_monthly_od.parquet")
    daily_hour = pd.concat(hourly_parts, ignore_index=True).groupby(
        ["service_date", "hour"], as_index=False, observed=True
    )["trips"].sum()
    daily_hour["day_type"] = daily_hour["service_date"].dt.dayofweek.map(
        lambda weekday: "weekend" if weekday >= 5 else "weekday"
    )
    profile = daily_hour.groupby(
        ["day_type", "hour"], as_index=False, observed=True
    ).agg(
        mean_hourly_trips=("trips", "mean"),
        observed_day_hours=("service_date", "size"),
    )
    write_parquet(profile, output_dir / "bart_hourly_profile.parquet")


def fetch_sfmta_survey(session: requests.Session, output_dir: Path) -> None:
    response = session.get(SURVEY_URL, timeout=120)
    response.raise_for_status()
    if not response.content:
        raise ValueError("SFMTA survey attachment download was empty")
    sheets = pd.read_excel(BytesIO(response.content), sheet_name=None)
    survey = max(sheets.values(), key=lambda frame: frame.shape[0] * frame.shape[1])
    survey = normalize_frame(survey).dropna(how="all")
    omit = {"respnum", "respondent_id", "interview_date", "interview_day", "q32a", "q32b"}
    survey = survey.drop(columns=[column for column in survey if column in omit], errors="ignore")
    for column in survey.columns:
        if survey[column].dtype == "object":
            numeric = pd.to_numeric(survey[column], errors="coerce")
            observed = survey[column].notna().sum()
            if observed and numeric.notna().sum() >= observed * 0.9:
                survey[column] = numeric
    write_parquet(survey, output_dir / "sfmta_travel_decision_survey_2021.parquet")


def parse_years(value: str) -> list[int]:
    years: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(year) for year in part.split("-", maxsplit=1))
            if start > end:
                raise argparse.ArgumentTypeError("Year range must be ascending")
            years.extend(range(start, end + 1))
        else:
            years.append(int(part))
    if not years or any(year < 2001 or year > 2100 for year in years):
        raise argparse.ArgumentTypeError("BART years must be between 2001 and 2100")
    return sorted(set(years))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bart-years",
        type=parse_years,
        default=parse_years("2019-2026"),
        help="Comma-separated years or ranges, e.g. 2019-2022,2025",
    )
    parser.add_argument("--skip-bart", action="store_true")
    parser.add_argument("--skip-survey", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with requests.Session() as session:
        session.headers.update({"User-Agent": "bay-area-transit-analysis/0.1"})
        fetch_mtc_tables(session, args.output_dir)
        if not args.skip_survey:
            fetch_sfmta_survey(session, args.output_dir)
        if not args.skip_bart:
            fetch_bart_od(session, args.output_dir, args.bart_years)


if __name__ == "__main__":
    main()