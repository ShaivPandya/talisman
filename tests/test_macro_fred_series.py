from __future__ import annotations

import threading

import pandas as pd
import pytest

from macro.housing import housing
from macro.labor_market import labor_market


@pytest.mark.parametrize("module", [housing, labor_market], ids=["housing", "labor_market"])
def test_fred_series_download_concurrently_and_fail_independently(monkeypatch, module):
    monkeypatch.setenv("FRED_API_KEY", "x" * 32)
    monkeypatch.setenv("ALTERNATIVE_DATA_CASE_SHILLER_PERMISSION_CONFIRMED", "true")
    keys = list(module.SERIES_CONFIG)
    failing_id = module.SERIES_CONFIG[keys[0]][0]
    in_flight = threading.Barrier(len(keys), timeout=5)

    def fetch(_fred, fred_id, *, observation_start):
        in_flight.wait()  # passes only once every series is being fetched at the same time
        if fred_id == failing_id:
            raise RuntimeError("FRED down")
        index = pd.date_range("2024-01-01", periods=14, freq="MS")
        return pd.Series(range(1000, 1014), index=index, dtype=float)

    monkeypatch.setattr(module, "fred_get_series", fetch)
    data = module.get_data()

    assert list(data["series"]) == keys
    assert data["series"][keys[0]]["error"] == "FRED down"
    assert set(data["latest"]) == set(keys[1:])
