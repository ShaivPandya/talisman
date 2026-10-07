"""Frozen, portable prospective registration and offline replay (LON-32)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlparse

import numpy as np
from pydantic import AwareDatetime, BaseModel, Field, model_validator

from longaeva_app.api.schemas import ParameterSetCreate
from longaeva_app.companies.base import FiscalPeriod
from longaeva_app.companies.visa.definitions import VISA_FISCAL_CALENDAR
from longaeva_app.companies.visa.model import VisaModel
from longaeva_app.engine.outputs import (
    RELATIVE_TOLERANCE,
    canonical_outputs_hash,
    load_npz_arrays,
    max_summary_relative_difference,
    summary_payload,
)
from longaeva_app.engine.provenance import code_version, lib_versions
from longaeva_app.engine.replay import compare_simulation
from longaeva_app.engine.runner import SimulationResult, simulate
from longaeva_app.evaluation.leakage import assert_inputs_before_cutoff
from longaeva_app.hashing import content_hash, sha256_hex
from longaeva_app.runs.forecasts import ARCHIVE_METRICS
from longaeva_app.runs.inputs import manifest_hash, parse_aware_utc

ORIGIN_DATE = "2026-07-28"
CUTOFF = datetime(2026, 7, 28, 20, 5, 26, tzinfo=UTC)
TARGET = "FY2026Q4"
REGISTRATION_NAME = "prospective-fy2026q4"
REGISTRATION_FILE = "prospective_fy2026q4.json"
PUBLICATION_URL: Final = "https://investor.visa.com/financial-information/quarterly-earnings/default.aspx"


class PublicationCheck(BaseModel):
    """An operator's fresh capture of the rendered official earnings table.

    Visa's table is populated by JavaScript. An empty HTTP response or 403 is
    never evidence of non-publication; retain the complete earnings-release row.
    """

    source_url: Literal["https://investor.visa.com/financial-information/quarterly-earnings/default.aspx"]
    checked_at: AwareDatetime
    method: Literal["rendered_official_quarterly_table"]
    release_links: list[str] = Field(min_length=3)

    def assert_unpublished(self, now: datetime) -> None:
        age = now - self.checked_at
        if age < timedelta(0) or age > timedelta(hours=1):
            raise ValueError("Publication check must be from the past hour")
        quarters: set[int] = set()
        for link in self.release_links:
            parsed = urlparse(link)
            if parsed.scheme != "https" or parsed.hostname != "s1.q4cdn.com":
                raise ValueError("Publication check contains a non-Visa release link")
            for quarter in range(1, 5):
                if f"/050606653/files/doc_financials/2026/q{quarter}/" in parsed.path.lower():
                    quarters.add(quarter)
        if 4 in quarters:
            raise ValueError("Q4 FY2026 results are already published")
        if quarters != {1, 2, 3}:
            raise ValueError("Cannot establish publication status: expected Q1, Q2 and Q3 release links")


class RegistrationBundle(BaseModel):
    version: Literal["lon32-v1"]
    kind: Literal["prospective"]
    target: Literal["FY2026Q4"]
    registered_at: AwareDatetime
    cutoff_ts: AwareDatetime
    publication_check: PublicationCheck
    run: dict[str, Any]
    parameters: ParameterSetCreate
    evidence: dict[str, Any]
    forecasts: list[dict[str, Any]] = Field(min_length=20, max_length=20)
    metric_definitions: dict[str, dict[str, str]]
    paths_file: str
    paths_sha256: str
    replay: dict[str, Any]
    content_hash: str

    @model_validator(mode="after")
    def validate_registration(self) -> RegistrationBundle:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if content_hash(payload) != self.content_hash:
            raise ValueError("Registration content hash does not match")
        if self.cutoff_ts != CUTOFF or self.parameters.cutoff_ts != CUTOFF:
            raise ValueError("Registration cutoff does not match the July 28 origin")
        if self.registered_at <= CUTOFF:
            raise ValueError("Registration time must be the actual later creation time")
        self.publication_check.assert_unpublished(self.registered_at)
        if self.parameters.computed_content_hash() != self.run["parameter_set_hash"]:
            raise ValueError("Parameter-set hash does not match")
        if manifest_hash(self.run["source_manifest"]) != self.run["source_manifest_hash"]:
            raise ValueError("Source-manifest hash does not match")
        assert_inputs_before_cutoff(
            CUTOFF,
            source_manifest=self.run["source_manifest"],
            calibration_evidence=self.evidence["calibration_evidence"],
            driver_history=self.evidence["driver_history"]["publication_entries"],
        )
        for observation in self.evidence["reviewed_snapshot"]:
            if parse_aware_utc(observation["publication_ts"]) > CUTOFF:
                raise ValueError("Reviewed evidence was published after the cutoff")
        state = {k: float(v) for k, v in self.run["starting_state"].items()}
        if content_hash(state) != self.run["starting_state_hash"]:
            raise ValueError("Starting-state hash does not match")
        if self.run["interventions"] or self.run["switches"] != {"service_lag": True, "pool_mix": False}:
            raise ValueError("Registration must use the full baseline without interventions")
        if self.run["n_quarters"] != 4 or int(self.run["n_paths"]) < 1:
            raise ValueError("Registration requires a four-quarter simulation")
        expected = {
            (metric, period)
            for metric in ARCHIVE_METRICS
            for period in ("FY2026Q4", "FY2027Q1", "FY2027Q2", "FY2027Q3")
        }
        keys = {(row["metric"], row["period_label"]) for row in self.forecasts}
        if keys != expected or set(self.metric_definitions) != set(ARCHIVE_METRICS):
            raise ValueError("Incomplete forecast archive")
        summary = {(row["metric"], row["period_label"]): row for row in self.run["summary"]}
        if min(parse_aware_utc(row["created_at"]) for row in self.forecasts) != self.registered_at:
            raise ValueError("Registration timestamp differs from archive creation time")
        for row in self.forecasts:
            if row["kind"] != "prospective" or row["run_id"] != self.run["id"]:
                raise ValueError("Forecast belongs to a different registration")
            if row["quantiles"] != summary[(row["metric"], row["period_label"])]["quantiles"]:
                raise ValueError("Archived quantiles differ from the saved run")
            period = FiscalPeriod(int(row["period_label"][2:6]), int(row["period_label"][-1]))
            if (
                row["target_period_start"] != VISA_FISCAL_CALENDAR.period_start(period).isoformat()
                or row["target_period_end"] != VISA_FISCAL_CALENDAR.period_end(period).isoformat()
            ):
                raise ValueError("Forecast dates differ from the target fiscal period")
        if self.replay["status"] != "exact_match" or self.replay["llm_provider"]:
            raise ValueError("Registration requires exact replay with LLM disabled")
        if (
            self.replay["recorded_outputs_hash"] != self.run["outputs_hash"]
            or self.replay["recomputed_outputs_hash"] != self.run["outputs_hash"]
        ):
            raise ValueError("Replay hashes do not match the registered outputs")
        if Path(self.paths_file).name != self.paths_file or not self.paths_file.endswith(".npz"):
            raise ValueError("Paths file must be a sibling NPZ artifact")
        return self


def load_registration(path: Path) -> RegistrationBundle:
    bundle = RegistrationBundle.model_validate_json(path.read_text(encoding="utf-8"))
    data = (path.parent / bundle.paths_file).read_bytes()
    if sha256_hex(data) != bundle.paths_sha256:
        raise ValueError("Packaged path-file hash does not match")
    metrics, states, labels = load_npz_arrays(data)
    periods = tuple(FiscalPeriod(int(label[2:6]), int(label[-1])) for label in labels)
    recorded = SimulationResult(
        metrics=metrics,
        states=states,
        periods=periods,
        draws=np.empty((0, 0, 0)),
        seed=int(bundle.run["seed"]),
        n_paths=int(bundle.run["n_paths"]),
        switches=bundle.run["switches"],
        params=bundle.parameters.values,
    )
    if canonical_outputs_hash(recorded) != bundle.run["outputs_hash"]:
        raise ValueError("Packaged output hash does not match the registered run")
    if max_summary_relative_difference(summary_payload(recorded), bundle.run["summary"]) > RELATIVE_TOLERANCE:
        raise ValueError("Packaged summaries do not match the registered run")
    return bundle


def replay_registration(path: Path) -> dict[str, Any]:
    """Replay frozen inputs without database, calibration, evidence loading or LLM."""
    bundle = load_registration(path)
    run = bundle.run
    metrics, states, _labels = load_npz_arrays((path.parent / bundle.paths_file).read_bytes())
    result = simulate(
        VisaModel(),
        run["starting_state"],
        bundle.parameters.values,
        origin=FiscalPeriod(2026, 3),
        seed=int(run["seed"]),
        n_paths=int(run["n_paths"]),
        n_quarters=4,
        switches=run["switches"],
    )
    comparison = compare_simulation(
        result,
        recorded_hash=run["outputs_hash"],
        recorded_metrics=metrics,
        recorded_states=states,
        recorded_summary=run["summary"],
        recomputed_summary=summary_payload(result),
        recorded_code_version=run["code_version"],
        recomputed_code_version=code_version(),
        recorded_lib_versions=run["lib_versions"],
        recomputed_lib_versions=lib_versions(),
    )
    return {
        "run_id": run["id"],
        "status": comparison.status,
        "recorded_outputs_hash": comparison.recorded_hash,
        "recomputed_outputs_hash": comparison.recomputed_hash,
        "max_relative_difference": comparison.max_relative_difference,
        "differences": comparison.differences,
        "llm_provider": "",
    }


def write_json_once(path: Path, payload: dict[str, Any]) -> None:
    """Never replace an already frozen registration or checkpoint."""
    data = (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode()
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to replace frozen artifact {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data)
