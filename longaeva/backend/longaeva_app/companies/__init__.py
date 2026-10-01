"""Company model registry (Visa registers in LON-19)."""

from __future__ import annotations

from longaeva_app.companies.base import CompanyModel

_REGISTRY: dict[str, CompanyModel] = {}


def register_company(model: CompanyModel) -> CompanyModel:
    key = model.key
    if key in _REGISTRY:
        raise ValueError(f"Company already registered: {key}")
    errors = model.validate_declarations()
    if errors:
        raise ValueError(f"Invalid company declarations for {key}: {errors}")
    _REGISTRY[key] = model
    return model


def get_company(key: str) -> CompanyModel:
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown company: {key}") from exc


def list_companies() -> list[str]:
    return sorted(_REGISTRY)


def clear_registry() -> None:
    """Test helper: remove all registered companies."""
    _REGISTRY.clear()
