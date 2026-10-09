"""Cutoff-frozen, source-verified excerpts for the LLM forecast baseline forecast baseline."""

from __future__ import annotations

import gzip
import json
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session, sessionmaker

from longaeva_app.collect.census_sources import resolve_pdf
from longaeva_app.companies.visa.calibration import CalibrationResult, calibrate, load_observation_rows
from longaeva_app.companies.visa.starting_state import StateValue, SupportingLevel
from longaeva_app.evaluation.evidence import freeze_evidence
from longaeva_app.evaluation.leakage import assert_inputs_before_cutoff
from longaeva_app.evaluation.origins import EvaluationOrigin
from longaeva_app.evaluation.targets import build_driver_history
from longaeva_app.extract.census_marts import extract_page_texts
from longaeva_app.extract.census_quarters import quarter_prints
from longaeva_app.extract.html_offsets import DocumentLayout, parse_html
from longaeva_app.hashing import content_hash, sha256_hex, utc_isoformat
from longaeva_app.runs.inputs import parse_aware_utc, resolve_fixture

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
INPUT_DIR = PACKAGE_ROOT / "data/fixtures/llm_baseline"
SELECTION_POLICY = (
    "lon30-excerpts-v1: union of starting-state input spans, calibration-used observation spans, "
    "driver-history spans and frozen reviewed external evidence. HTML tables retain the containing "
    "row, preceding row and first three header/context rows; prose retains nearby text nodes within "
    "500 raw characters. Census retains page 1 containing the dated three-month headline, including "
    "verified quarter-end fitting history. Overlapping rows/nodes are deduplicated. No model predictions, "
    "parameter estimates, mapping results, future actuals or later revisions are supplied."
)


def _raw(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def _verified(path: Path, expected: str) -> bytes:
    data = _raw(path)
    if sha256_hex(data) != expected:
        raise ValueError(f"Source hash mismatch: {path.name}")
    return data


@lru_cache(maxsize=128)
def _layout(raw: bytes) -> DocumentLayout:
    return parse_html(raw.decode("utf-8"))


def html_excerpts(raw: bytes, spans: list[tuple[int, int]]) -> list[dict[str, Any]]:
    """Select contextual rows/nodes by raw original offsets, never by outcomes."""
    layout = _layout(raw)
    chosen: dict[int, set[int]] = defaultdict(set)
    prose: set[int] = set()
    runs = sorted(layout.visible_runs + layout.text_layer_runs, key=lambda run: run.raw_start)
    for start, end in spans:
        if not (0 <= start < end <= len(layout.html)):
            raise ValueError("Input span is outside the original document")
        tables = [(i, t) for i, t in enumerate(layout.tables) if t.start <= start and end <= t.end]
        if tables:
            i, table = min(tables, key=lambda pair: pair[1].end - pair[1].start)
            selected_rows = [
                j
                for j, row in enumerate(table.rows)
                if any(
                    cell.raw_start is not None
                    and cell.raw_end is not None
                    and cell.raw_start < end
                    and start < cell.raw_end
                    for cell in row.cells
                )
            ]
            if selected_rows:
                chosen[i].update(range(min(3, len(table.rows))))
                chosen[i].update(selected_rows)
                chosen[i].update(max(0, j - 1) for j in selected_rows)
                continue
        prose.update(i for i, run in enumerate(runs) if run.raw_start < end + 500 and run.raw_end > max(0, start - 500))
    excerpts = []
    for i, rows in sorted(chosen.items(), key=lambda item: layout.tables[item[0]].start):
        table = layout.tables[i]
        text = table.preceding_text + "\n" + "\n".join(table.row_texts()[j] for j in sorted(rows))
        excerpts.append(
            {
                "kind": "table_rows",
                "char_start": table.start,
                "char_end": table.end,
                "row_indices": sorted(rows),
                "text": text,
                "text_sha256": sha256_hex(text),
            }
        )
    # Group adjacent selected nodes to retain prose without duplicating contexts.
    groups: list[list[int]] = []
    for i in sorted(prose):
        if groups and i == groups[-1][-1] + 1:
            groups[-1].append(i)
        else:
            groups.append([i])
    for group in groups:
        text = " ".join(runs[i].text for i in group)
        excerpts.append(
            {
                "kind": "prose",
                "char_start": runs[group[0]].raw_start,
                "char_end": runs[group[-1]].raw_end,
                "text": text,
                "text_sha256": sha256_hex(text),
            }
        )
    if not excerpts:
        raise ValueError("Required source has no contextual excerpts")
    return sorted(excerpts, key=lambda item: (item["char_start"], item["kind"]))


def source_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for folder in ("visa_releases", "states", "booking", "second_wave"):
        path = PACKAGE_ROOT / f"data/fixtures/{folder}/sources/manifest.json"
        if not path.is_file():
            continue
        for item in json.loads(path.read_text())["sources"]:
            if "accession" not in item or "document" not in item:
                continue
            relative = item["path"]
            original = PACKAGE_ROOT / relative if relative.startswith("data/") else path.parent / relative
            key = item["accession"] + "/" + item["document"]
            entry = {
                "document_key": key,
                "content_sha256": item["content_sha256"],
                "publication_ts": item["acceptance_utc"],
                "url": item["url"],
                "path": str(original.relative_to(PACKAGE_ROOT)),
                "doc_type": item["form"],
            }
            if key in registry and registry[key]["content_sha256"] != entry["content_sha256"]:
                raise ValueError("Conflicting retained source hashes")
            registry[key] = entry
    return registry


def build_pack(
    origin: EvaluationOrigin,
    calibration: CalibrationResult,
    external: list[dict[str, Any]],
) -> dict[str, Any]:
    fixture = resolve_fixture(origin.cutoff_ts)
    rows = load_observation_rows()
    history = build_driver_history(origin, rows=rows)
    assert_inputs_before_cutoff(
        origin.cutoff_ts,
        starting_state_sources=fixture.sources,
        calibration_evidence=calibration.evidence_index,
        driver_history=history.publication_entries,
    )
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    used: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.observation_id) in calibration.evidence_index or any(
            item["source_id"] == row.source_id
            and item["period_label"] == row.period_label
            and item["field"] == row.field
            for item in history.publication_entries
        ):
            if row.publication_ts > origin.cutoff_ts:
                raise ValueError("Selected history row is after cutoff")
            spans[row.source_id].append((row.char_start, row.char_end))
            used[str(row.observation_id)] = {
                "source_id": row.source_id,
                "period": row.period_label,
                "field": row.field,
                "value": row.value,
                "unit": row.unit,
                "basis": row.basis,
                "geography": row.geography,
            }
    state_values: list[StateValue | SupportingLevel] = [*fixture.values.values(), *fixture.supporting_levels.values()]
    for val in state_values:
        if val.source_id and val.span and fixture.sources[val.source_id].role == "input":
            spans[val.source_id].append((val.span.char_start, val.span.char_end))
    registry = source_registry()
    for ref in fixture.sources.values():
        if ref.role == "input":
            if ref.source_id not in registry or registry[ref.source_id]["content_sha256"] != ref.content_sha256:
                raise ValueError("Starting-state source is missing or has a different hash")
            if ref.source_id not in spans:
                raise ValueError("Starting-state input source has no supporting span")
    # Reviewed external spans come from the same retained fixture identities as freeze_evidence.
    by_hash = {item["content_sha256"]: key for key, item in registry.items()}
    fixture_entries: dict[str, tuple[str, dict[str, Any]]] = {}
    for path in sorted((PACKAGE_ROOT / "data/fixtures/observations").glob("*.json")):
        data = json.loads(path.read_text())
        refs = data.get("sources", {})
        if isinstance(refs, list):
            refs = {ref["source_id"]: ref for ref in refs}
        if "source" in data:
            ref = data["source"]
            refs = {ref["source_id"]: ref}
        for obs in data.get("observations", []):
            ref_key = obs.get("source_id") or next(iter(refs), "")
            fixture_entries[obs["observation_id"]] = (ref_key, obs)
    for item in external:
        if item["effective"] is None:
            continue
        if parse_aware_utc(item["publication_ts"]) > origin.cutoff_ts:
            raise ValueError("External observation is after cutoff")
        if item["key"].startswith("census-quarter:"):
            continue
        key = by_hash.get(item["source_hash"])
        fixture_entry = fixture_entries.get(item["key"])
        if key is None or fixture_entry is None or fixture_entry[0] != key:
            raise ValueError("Reviewed external source is missing")
        span = fixture_entry[1]["span"]
        spans[key].append((int(span["char_start"]), int(span["char_end"])))
    documents: list[dict[str, Any]] = []
    for key, selected in sorted(spans.items()):
        entry = registry[key]
        if parse_aware_utc(entry["publication_ts"]) > origin.cutoff_ts:
            raise ValueError("Document publication is after cutoff")
        raw = _verified(PACKAGE_ROOT / entry["path"], entry["content_sha256"])
        documents.append({**entry, "excerpts": html_excerpts(raw, sorted(set(selected)))})
    # The mapping rules fit from these verified quarter-end Census releases.
    manifest = yaml.safe_load((PACKAGE_ROOT / "data/manifest/census.yaml").read_text())
    census = {item["period"]["release_id"]: item for item in manifest["documents"]}
    for census_row in quarter_prints(origin.cutoff_ts):
        entry = census[census_row.release_id]
        if entry["integrity_flag"] != "ok":
            continue
        resolved = resolve_pdf(census_row.release_id)
        if resolved is None:
            raise ValueError(f"Required Census original is missing: {census_row.release_id}")
        raw = _verified(resolved[0], entry["expected_sha256"])
        text = _pdf_headline(raw)
        documents.append(
            {
                "document_key": f"census:{census_row.release_id}",
                "content_sha256": entry["expected_sha256"],
                "publication_ts": census_row.publication_ts,
                "url": entry["url"],
                "doc_type": "MARTS advance release",
                "excerpts": [
                    {
                        "kind": "page",
                        "page": 1,
                        "char_start": 0,
                        "char_end": len(text),
                        "text": text,
                        "text_sha256": sha256_hex(text),
                    }
                ],
            }
        )
    assert_inputs_before_cutoff(origin.cutoff_ts, source_manifest=documents)
    pack = {
        "selection_policy": SELECTION_POLICY,
        "origin_date": origin.origin_date,
        "cutoff_ts": utc_isoformat(origin.cutoff_ts),
        "origin_period": origin.origin.label(),
        "target_period": origin.target.label(),
        "documents": sorted(documents, key=lambda item: item["document_key"]),
        "historical_observations": [used[key] for key in sorted(used)],
        "external_observations": [
            {
                "key": item["key"],
                "publication_ts": item["publication_ts"],
                "source_hash": item["source_hash"],
                "effective": item["effective"],
            }
            for item in external
            if item["effective"] is not None
        ],
    }
    pack["pack_hash"] = content_hash(pack)
    return pack


@lru_cache(maxsize=64)
def _pdf_headline(raw: bytes) -> str:
    texts, _metadata = extract_page_texts(raw)
    if not texts:
        raise ValueError("Required Census PDF has no readable headline page")
    return texts[0]


def validate_pack(pack: dict[str, Any], origin: EvaluationOrigin) -> None:
    if pack.get("pack_hash") != content_hash({k: v for k, v in pack.items() if k != "pack_hash"}):
        raise ValueError("Evidence pack hash mismatch")
    if (pack["origin_date"], pack["cutoff_ts"], pack["target_period"]) != (
        origin.origin_date,
        utc_isoformat(origin.cutoff_ts),
        origin.target.label(),
    ):
        raise ValueError("Evidence pack origin/cutoff/target mismatch")
    assert_inputs_before_cutoff(origin.cutoff_ts, source_manifest=pack["documents"])
    assert_inputs_before_cutoff(origin.cutoff_ts, source_manifest=pack.get("external_observations", []))
    if pack.get("selection_policy") != SELECTION_POLICY:
        raise ValueError("Evidence selection policy changed")
    for document in pack["documents"]:
        if not document["excerpts"]:
            raise ValueError("Missing required excerpts")
        for excerpt in document["excerpts"]:
            if excerpt["text_sha256"] != sha256_hex(excerpt["text"]):
                raise ValueError("Excerpt text hash mismatch")


def verify_originals(pack: dict[str, Any]) -> None:
    """Before a fresh call, recheck every original. Offline scores need only frozen packs."""
    for document in pack["documents"]:
        if document["document_key"].startswith("census:"):
            resolved = resolve_pdf(document["document_key"].split(":", 1)[1])
            if resolved is None:
                raise ValueError("Required Census original is missing")
            path = resolved[0]
        else:
            path = (PACKAGE_ROOT / document["path"]).resolve()
            if not path.is_relative_to(PACKAGE_ROOT.resolve()):
                raise ValueError("Original path escapes the package")
        _verified(path, document["content_sha256"])


def prepare_packs(
    factory: sessionmaker[Session], origins: list[EvaluationOrigin], output_dir: Path = INPUT_DIR
) -> dict[str, dict[str, Any]]:
    snapshot = freeze_evidence(factory, origins)
    output_dir.mkdir(parents=True, exist_ok=True)
    packs = {}
    for origin in origins:
        print(f"Preparing evidence: {origin.origin_date}", flush=True)
        result = calibrate(origin.origin_date, run_sensitivity=False)
        pack = build_pack(origin, result, snapshot.by_origin[origin.origin_date])
        validate_pack(pack, origin)
        (output_dir / f"{origin.origin_date}.json").write_text(json.dumps(pack, indent=2, sort_keys=True) + "\n")
        packs[origin.origin_date] = pack
    return packs
