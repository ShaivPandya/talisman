"""Every mounted SPA route must be reachable directly on Firebase Hosting."""

import json
import re
from pathlib import Path


def test_mounted_routes_have_spa_rewrites_and_uncached_html():
    hosting = json.loads(Path("firebase.json").read_text())["hosting"]
    routes = re.findall(r'\{ path: "([^"]+)", page:', Path("frontend/src/lib/pageRoutes.ts").read_text())
    assert routes, "No mounted routes found; update this contract if route registration changes."
    rewrites = [re.compile(rule["regex"]) for rule in hosting["rewrites"] if rule.get("destination") == "/index.html"]
    uncached = [
        re.compile(rule["regex"])
        for rule in hosting["headers"]
        if "regex" in rule and any(h["key"] == "Cache-Control" and "no-store" in h["value"] for h in rule["headers"])
    ]
    for route in [*routes, "/login"]:
        path = re.sub(r":[^/]+", "SAMPLE", route)
        assert any(pattern.fullmatch(path) for pattern in rewrites), f"Direct navigation to {route} would return 404."
        assert any(pattern.fullmatch(path) for pattern in uncached), f"HTML for {route} must not retain stale bundles."
    assert not any(pattern.fullmatch("/assets/missing.js") for pattern in rewrites)
