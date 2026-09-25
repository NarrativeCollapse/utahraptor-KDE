#!/usr/bin/env python3
"""The OS identity, read from config/identity.json.

config/identity.json is the single source for the user-visible identity: the
OS name and id that os-release and image-info carry, the registry namespace the
images publish under, and the project URLs. Renaming the OS is an edit to that
file; tests/test_identity.py names every place that still carries a literal
copy and fails until they agree.

Internal names are deliberately not part of it. The utah-* helpers under
/usr/local/libexec, /usr/share/utah, the utah-packages repository and the
UTAH_* environment variables are this image's Utah lineage and stay put.

    identity.py get KEY              one field, e.g. `get name`
    identity.py image [FLAVOR]       absolution / absolution-nvidia
    identity.py ref [FLAVOR] [TAG]   ghcr.io/narrativecollapse/absolution:testing
    identity.py json                 the whole file, for scripts that want it all
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "config" / "identity.json"
REQUIRED = ("name", "id", "codename", "vendor", "repository", "home_url",
            "documentation_url", "support_url", "bug_report_url")


def load(path: Path = CONFIG) -> dict[str, str]:
    data = json.loads(path.read_text())
    missing = [key for key in REQUIRED if not data.get(key)]
    if missing:
        raise SystemExit(f"{path.name} is missing: {', '.join(missing)}")
    if data["id"] != data["id"].lower() or not data["id"].replace("-", "").isalnum():
        raise SystemExit(f"{path.name}: id must be lowercase letters, digits and dashes")
    if data["vendor"] != data["vendor"].lower():
        raise SystemExit(f"{path.name}: vendor is a registry namespace and must be lowercase")
    return data


def image(identity: dict[str, str], flavor: str = "main") -> str:
    """The published image name for a flavor: the id, suffixed unless main."""
    return identity["id"] if flavor == "main" else f"{identity['id']}-{flavor}"


def ref(identity: dict[str, str], flavor: str = "main", tag: str = "testing") -> str:
    return f"ghcr.io/{identity['vendor']}/{image(identity, flavor)}:{tag}"


def main(argv: list[str]) -> int:
    identity = load()
    what = argv[1] if len(argv) > 1 else "json"
    if what == "get":
        if len(argv) < 3 or argv[2] not in identity:
            raise SystemExit(f"usage: identity.py get {{{','.join(identity)}}}")
        print(identity[argv[2]])
    elif what == "image":
        print(image(identity, argv[2] if len(argv) > 2 else "main"))
    elif what == "ref":
        print(ref(identity, argv[2] if len(argv) > 2 else "main",
                  argv[3] if len(argv) > 3 else "testing"))
    elif what == "json":
        print(json.dumps(identity, indent=2))
    else:
        raise SystemExit(f"unknown query: {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
