"""Verify scoped public-data exceptions still detect synthetic credential fields."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    config = Path(__file__).resolve().parents[1] / ".gitleaks.toml"
    fingerprint = hashlib.sha256(b"public fixture request; not a credential").hexdigest()
    marker = "llm.reasoning_effort.frontier_defaults_v2"
    series = "naics_452_dept"
    samples = {
        "api/llm_settings.py": f'MIGRATION_KEY = "{marker}"\napi_key = "{fingerprint}"\n',
        "api/unrelated.py": f'MIGRATION_KEY = "{marker}"\n',
        "longaeva/data/fixtures/llm_baseline/cached.json": "\n".join(
            json.dumps(row)
            for row in (
                {"request_key": fingerprint},
                {"request_key": "synthetic_" + fingerprint},
                {"api_key": fingerprint},
                {"key": series},
            )
        ),
        "other/cache.json": json.dumps({"request_key": fingerprint, "key": series}),
        "longaeva/backend/tests/test_llm_baseline.py": (
            'settings(openai_api_key="test-key", anthropic_api_key="test-key", gemini_api_key="test-key")\n'
            f'anthropic_api_key = "{fingerprint}"\n'
        ),
    }
    samples["scripts/check_gitleaks_allowlists.py"] = samples["longaeva/backend/tests/test_llm_baseline.py"]
    with tempfile.TemporaryDirectory(prefix="talisman-gitleaks-") as directory:
        root = Path(directory)
        for name, source in samples.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        report = root / "findings.json"
        result = subprocess.run(
            [
                "gitleaks",
                "dir",
                ".",
                "--config",
                str(config),
                "--no-banner",
                "--redact",
                "--report-format",
                "json",
                "--report-path",
                str(report),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 1 or not report.exists():
            raise RuntimeError("Synthetic credential scan did not return findings")
        findings = json.loads(report.read_text())
        actual = {(row["File"], row["StartLine"]) for row in findings}
        expected = {
            ("api/llm_settings.py", 2),
            ("api/unrelated.py", 1),
            ("longaeva/data/fixtures/llm_baseline/cached.json", 1),
            ("longaeva/data/fixtures/llm_baseline/cached.json", 2),
            ("longaeva/data/fixtures/llm_baseline/cached.json", 3),
            ("longaeva/data/fixtures/llm_baseline/cached.json", 4),
            ("other/cache.json", 1),
            ("longaeva/backend/tests/test_llm_baseline.py", 2),
            ("scripts/check_gitleaks_allowlists.py", 2),
        }
        # Unreviewed hashes and identifiers at unreviewed paths still trigger.
        # Two independently detected fields share the line in other/cache.json.
        if actual != expected or len(findings) != 10:
            raise RuntimeError(f"Public-data exceptions changed credential detection: {actual}")
    print("Gitleaks exact exceptions passed; all ten expected findings detected")


if __name__ == "__main__":
    main()
