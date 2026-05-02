"""Conftest racine — options et markers globaux pytest.

Le marker `e2e` et le flag `--no-e2e` sont définis ici pour être disponibles
sur l'ensemble du test suite (pas seulement dans tests/e2e/).
"""

from __future__ import annotations

import pytest


def pytest_configure(config):
    """Enregistre les markers custom."""
    config.addinivalue_line(
        "markers",
        "e2e: Tests end-to-end qui lancent un mock Gateway local "
        "(skip avec --no-e2e pour executions rapides).",
    )


def pytest_addoption(parser):
    parser.addoption(
        "--no-e2e",
        action="store_true",
        default=False,
        help="Skip tests marked as e2e (utile en CI sans reseau ou pour dev rapide).",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--no-e2e"):
        skip_e2e = pytest.mark.skip(reason="--no-e2e flag passe")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)
