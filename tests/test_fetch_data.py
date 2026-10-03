import unittest

import pandas as pd

from scripts.fetch_data import (
    aggregate_bart_daily_hour,
    aggregate_bart_frame,
    normalize_frame,
    parse_years,
)


class FetchDataTests(unittest.TestCase):
    def test_normalize_frame_normalizes_names_and_trims_text(self) -> None:
        frame = pd.DataFrame([["  BART ", 2024]], columns=["System", "YEAR"])
        cleaned = normalize_frame(frame)
        self.assertEqual(list(cleaned.columns), ["system", "year"])
        self.assertEqual(cleaned.loc[0, "system"], "BART")

    def test_aggregate_bart_frame_sums_station_pairs_by_month(self) -> None:
        frame = pd.DataFrame(
            [
                ["2025-01-02", 8, "12TH", "16TH", 2],
                ["2025-01-20", 9, "12TH", "16TH", 3],
                ["2025-02-01", 9, "12TH", "16TH", 4],
            ]
        )
        result = aggregate_bart_frame(frame)
        self.assertEqual(result["year_month"].tolist(), ["2025-01", "2025-02"])
        self.assertEqual(result["trips"].tolist(), [5, 4])

    def test_aggregate_bart_daily_hour_sums_all_od_pairs(self) -> None:
        frame = pd.DataFrame(
            [
                ["2025-01-04", 8, "12TH", "16TH", 2],
                ["2025-01-04", 8, "12TH", "CIVC", 3],
            ]
        )
        result = aggregate_bart_daily_hour(frame)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc[0, "trips"], 5)

    def test_parse_years_expands_ranges_and_deduplicates(self) -> None:
        self.assertEqual(parse_years("2019-2021,2021,2025"), [2019, 2020, 2021, 2025])


if __name__ == "__main__":
    unittest.main()