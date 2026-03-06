from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _add_repo_root() -> None:
    root = Path(__file__).resolve().parents[1]
    framework_root = root / "0xclaw" / "framework"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if str(framework_root) not in sys.path:
        sys.path.insert(0, str(framework_root))


@pytest.fixture
def contracts_mod():
    return importlib.import_module("0xclaw.orchestration.contracts")


@pytest.fixture
def router_mod():
    return importlib.import_module("0xclaw.orchestration.router")


@pytest.fixture
def state_mod():
    return importlib.import_module("0xclaw.orchestration.state")


@pytest.fixture
def session_mod():
    return importlib.import_module("0xclaw.orchestration.session_control")


@pytest.fixture
def model_mod():
    return importlib.import_module("0xclaw.orchestration.model_profiles")
