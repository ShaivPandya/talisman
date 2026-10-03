"""Company model registry (Visa registers via ``register_default_companies``)."""

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


def register_default_companies() -> list[str]:
    """Idempotently register built-in company models (Visa).

    Safe to call multiple times: already-registered keys are skipped.
    No side effects at import time.
    """
    from longaeva_app.companies.visa.model import VisaModel

    registered: list[str] = []
    if "visa" not in _REGISTRY:
        register_company(VisaModel())
        registered.append("visa")
    return registered


__all__ = [
    "CompanyModel",
    "clear_registry",
    "get_company",
    "list_companies",
    "register_company",
    "register_default_companies",
]
