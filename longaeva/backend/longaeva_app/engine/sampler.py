"""Seeded path-major correlated factor sampler."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.floating]


def factor_root(correlation: FloatArray, *, rtol: float = 1e-10) -> FloatArray:
    """Return a matrix ``L`` such that ``L @ L.T ≈ correlation``.

    Uses Cholesky when the matrix is positive-definite. Falls back to a symmetric
    eigendecomposition root when the matrix is singular but positive-semidefinite.
    Rejects non-PSD matrices.
    """
    corr = np.asarray(correlation, dtype=np.float64)
    if corr.ndim != 2 or corr.shape[0] != corr.shape[1]:
        raise ValueError(f"correlation must be square, got shape {corr.shape}")
    if not np.allclose(corr, corr.T, rtol=rtol, atol=1e-12):
        raise ValueError("correlation matrix must be symmetric")
    if not np.allclose(np.diag(corr), 1.0, rtol=rtol, atol=1e-12):
        raise ValueError("correlation diagonal must be 1")

    eigvals = np.linalg.eigvalsh(corr)
    if float(np.min(eigvals)) < -rtol:
        raise ValueError(f"correlation is not positive-semidefinite (min eigenvalue {float(np.min(eigvals)):.3e})")

    try:
        return np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        # Singular PSD: symmetric square root via eigendecomposition.
        vals, vecs = np.linalg.eigh(corr)
        vals = np.clip(vals, 0.0, None)
        return vecs * np.sqrt(vals)


def draw_factors(
    *,
    n_paths: int,
    n_quarters: int,
    n_factors: int,
    seed: int,
) -> FloatArray:
    """Draw iid standard normals in path-major order: shape ``(n_paths, n_quarters, n_factors)``.

    Path ``i`` is identical for any ``n_paths > i`` under the same seed (prefix property).
    Raw draws never depend on parameter values, so paired runs share them exactly.
    """
    if n_paths < 1:
        raise ValueError("n_paths must be >= 1")
    if n_quarters < 1:
        raise ValueError("n_quarters must be >= 1")
    if n_factors < 1:
        raise ValueError("n_factors must be >= 1")
    if seed < 0:
        raise ValueError("seed must be >= 0")

    rng = np.random.Generator(np.random.PCG64(seed))
    # Path-major: fill path 0 completely, then path 1, …
    return rng.standard_normal((n_paths, n_quarters, n_factors)).astype(np.float64, copy=False)


def correlate_draws(raw: FloatArray, root: FloatArray) -> FloatArray:
    """Apply ``root`` so each (path, quarter) row becomes correlated: ``z @ root.T``."""
    z = np.asarray(raw, dtype=np.float64)
    factor_l = np.asarray(root, dtype=np.float64)
    if z.ndim != 3:
        raise ValueError(f"raw draws must be 3-D, got shape {z.shape}")
    if factor_l.ndim != 2 or factor_l.shape[0] != factor_l.shape[1]:
        raise ValueError(f"root must be square, got shape {factor_l.shape}")
    if z.shape[2] != factor_l.shape[0]:
        raise ValueError(f"factor dimension mismatch: draws {z.shape[2]} vs root {factor_l.shape[0]}")
    # (n_paths, n_quarters, n_factors) @ (n_factors, n_factors).T
    return z @ factor_l.T


__all__ = [
    "correlate_draws",
    "draw_factors",
    "factor_root",
]
