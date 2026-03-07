import importlib
import sys
from pathlib import Path


def _load_cli_args_module():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "0xclaw"))
    return importlib.import_module("cli_args")


def test_parse_gateway_args_defaults():
    cli_args_mod = _load_cli_args_module()

    port, verbose = cli_args_mod.parse_gateway_args([])

    assert port is None
    assert verbose is False


def test_parse_gateway_args_values():
    cli_args_mod = _load_cli_args_module()

    port, verbose = cli_args_mod.parse_gateway_args(["--port", "19999", "--verbose"])

    assert port == 19999
    assert verbose is True


def test_parse_whatsapp_args_login():
    cli_args_mod = _load_cli_args_module()

    command = cli_args_mod.parse_whatsapp_args(["login"])

    assert command == "login"


def test_repo_config_includes_telegram_channel():
    config = Path("0xclaw/config/config.json").read_text(encoding="utf-8")

    assert '"channels"' in config
    assert '"telegram"' in config
    assert '"whatsapp"' in config


def test_rewrite_bridge_branding(tmp_path):
    content = Path("0xclaw/main.py").read_text(encoding="utf-8")

    assert "def _rewrite_bridge_branding" in content
    assert "0xclaw-whatsapp-bridge" in content
    assert "0xClaw WhatsApp Bridge" in content
    assert ".0xclaw" in content
