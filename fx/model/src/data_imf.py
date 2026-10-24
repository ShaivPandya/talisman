import json
import re
from pathlib import Path

import pandas as pd

from utils.retry import requests_get

IMF_BASE = "https://www.imf.org/external/datamapper/api/v1"


class ImfError(RuntimeError):
    pass


def fetch_imf_datamapper_json(path: str) -> dict:
    """Bounded metadata/batch reads using the existing DataMapper transport."""
    if not re.fullmatch(r"[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)?", path):
        raise ImfError("Invalid IMF DataMapper path")
    with requests_get(f"{IMF_BASE}/{path}", timeout=(10, 30), stream=True) as response:
        if response.status_code != 200:
            raise ImfError(f"IMF DataMapper request failed ({response.status_code})")
        chunks = []
        size = 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 12_000_000:
                raise ImfError("IMF DataMapper response exceeds the bounded download limit")
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks))
        except (ValueError, UnicodeError):
            raise ImfError("IMF DataMapper returned no valid JSON") from None
    if not isinstance(payload, dict):
        raise ImfError("IMF DataMapper schema changed")
    return payload


def fetch_imf_datamapper_indicator(
    indicator: str, iso3: str, cache_dir: Path | None, refresh: bool = False, *, payload: dict | None = None
) -> pd.Series:
    # Snapshot-backed production reads pass None; other callers retain the CSV cache.
    cache_path = cache_dir / f"imf_{indicator}_{iso3}.csv" if cache_dir is not None else None
    if cache_path is not None and cache_path.exists() and not refresh and payload is None:
        df = pd.read_csv(cache_path, parse_dates=["date"])
        s = pd.to_numeric(df["value"], errors="coerce")
        return pd.Series(s.values, index=df["date"], name=f"{indicator}_{iso3}").sort_index()

    if payload is None:
        url = f"{IMF_BASE}/{indicator}/{iso3}"
        r = requests_get(url, timeout=60)
        if r.status_code != 200:
            raise ImfError(f"IMF DataMapper request failed ({r.status_code})")
        j = r.json()
    else:
        j = payload
    values = j.get("values", {}).get(indicator, {}).get(iso3, {})

    if not values:
        raise ImfError(f"No values returned for {indicator}/{iso3}")

    s = pd.Series(values, dtype="float64")
    idx = pd.to_datetime(s.index.astype(str) + "-12-31")  # annual -> year-end date index

    if cache_path is not None:
        out = pd.DataFrame({"date": idx, "value": s.values})
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(cache_path, index=False)

    return pd.Series(s.values, index=idx, name=f"{indicator}_{iso3}").sort_index()
