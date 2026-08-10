"""Every module actually imports.

**Syntax checking does not catch this.** A dropped import still referenced in a class
body, a constant renamed in every place but one, a helper moved between modules — none of
it shows up until the file is really loaded. On this app that means it shows up on the
Homey Pro at install time, in a runtime with no debugger attached.

The gap is concrete: before this file, the suite never imported `navien_lib/*/driver.py`,
`selfcheck.py`, `i18n.py`, `tls.py` or the root `app.py`. The drivers are not empty shims —
they register the Flow cards — so a stale name in one would have shipped.

Borrowed from navien_smart_ha v0.18.0, which added the same test upstream and describes it
as the cheapest test in the suite and the one that catches something most often.

`homey` resolves to the fake in `conftest.py` unless a real SDK is present, so this runs
in the same checkout as everything else.
"""

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _modules() -> list:
    names = ["app"]                       # homey_export lives here, outside the package
    for path in sorted((ROOT / "navien_lib").rglob("*.py")):
        parts = list(path.relative_to(ROOT).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.append(".".join(parts))
    return names


@pytest.mark.parametrize("name", _modules())
def test_module_imports(name):
    importlib.import_module(name)
