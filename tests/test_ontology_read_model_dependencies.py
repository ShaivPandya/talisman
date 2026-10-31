"""The scoped-refresh dependency map must match every read model's definition.

If a migration adds or redefines a materialized read model, these tests fail
until ``READ_MODEL_DEPENDENCIES`` in the scoped-refresh migration (or a later
one) records which source rows change it. A missing entry would leave that read
model stale after writes.
"""

from __future__ import annotations

import re
import runpy
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
SCOPED_REFRESH = MIGRATIONS / "20261031_0001_scoped_read_model_refresh.py"
SCOPED = runpy.run_path(str(SCOPED_REFRESH))
DEPENDENCIES: dict[str, dict[str, tuple[str, ...]]] = SCOPED["READ_MODEL_DEPENDENCIES"]
ANY = SCOPED["ANY_TYPE"]
SOURCE_TABLES = SCOPED["SOURCE_TABLES"]
CREATE_VIEW = re.compile(r"CREATE MATERIALIZED VIEW (\{?\w+\}?) AS(.*?)\"\"\"", re.DOTALL)


def _view_definitions() -> dict[str, tuple[Path, str, dict]]:
    """Latest definition of each materialized view: (migration, SQL, migration globals)."""
    latest: dict[str, tuple[Path, str, dict]] = {}
    for path in sorted(MIGRATIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "CREATE MATERIALIZED VIEW" not in text:
            continue
        module = runpy.run_path(str(path))
        for raw_name, sql in CREATE_VIEW.findall(text):
            name = module[raw_name.strip("{}")] if raw_name.startswith("{") else raw_name
            latest[name] = (path, sql, module)
    return latest


def _literals(pattern: str, sql: str) -> set[str]:
    return set(re.findall(pattern, sql))


def _referenced_types(sql: str, module: dict, column: str) -> set[str]:
    found = _literals(rf"{column} = '(\w+)'", sql)
    for listed in re.findall(rf"{column} IN \(([^)]*)\)", sql):
        found |= set(re.findall(r"'(\w+)'", listed))
    for constant in re.findall(rf"{column} = ANY\(\{{(\w+)\}}\)", sql):
        found |= set(_resolve_array(module, constant))
    return found


def _resolve_array(module: dict, name: str) -> tuple[str, ...]:
    # Array placeholders are built from a tuple constant; the view's own helper names the tuple.
    if name in module and isinstance(module[name], tuple):
        return module[name]
    tuples = {
        "object_type_array": "OPERATIONAL_OBJECT_TYPES",
        "provenance_relation_types": "PROVENANCE_RELATION_TYPES",
    }
    return module[tuples[name]]


def test_every_read_model_has_dependencies():
    assert set(DEPENDENCIES) == set(_view_definitions())


def test_dependencies_match_each_read_model_definition():
    for view, (path, sql, module) in _view_definitions().items():
        expected = DEPENDENCIES[view]
        tables = {table for table in SOURCE_TABLES if re.search(rf"\b{table}\b", sql)}
        assert set(expected) == tables, f"{view} ({path.name}) reads {tables}"

        if "ontology_object_versions" in tables:
            object_types = _referenced_types(sql, module, "object_type")
            filters_every_object = bool(re.search(r"\bWHERE p\.object_type|object_type = ANY", sql))
            if expected["ontology_object_versions"] == (ANY,):
                # Only allowed when some object rows join without a type filter.
                assert not object_types or not filters_every_object, view
            else:
                assert set(expected["ontology_object_versions"]) == object_types, f"{view} ({path.name})"

        if "ontology_relation_versions" in tables:
            relation_types = _referenced_types(sql, module, "relation_type")
            assert set(expected["ontology_relation_versions"]) == relation_types, f"{view} ({path.name})"


def test_no_later_migration_defines_read_models_without_updating_dependencies():
    latest_definition = max(path.name for path, _sql, _module in _view_definitions().values())
    assert latest_definition < SCOPED_REFRESH.name or any(
        "READ_MODEL_DEPENDENCIES" in path.read_text(encoding="utf-8")
        for path in MIGRATIONS.glob("*.py")
        if path.name > SCOPED_REFRESH.name
    )


def test_triggers_cover_every_source_table():
    text = SCOPED_REFRESH.read_text(encoding="utf-8")
    assert "AFTER INSERT OR UPDATE OR DELETE ON {table}" in text
    assert set(SOURCE_TABLES) == {table for tables in DEPENDENCIES.values() for table in tables}
