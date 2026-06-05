from __future__ import annotations

from pathlib import Path

from codex_bridge.launch import (
    LOCAL_BRIDGE_URL,
    TEMP_CODEX_HOME_NAME,
    build_launcher_config,
    is_simple_launch_args,
    prepare_temp_codex_home,
)


def test_is_simple_launch_args_accepts_three_positionals() -> None:
    assert is_simple_launch_args(["https://api.deepseek.com/v1", "sk-test", "deepseek-v4-flash"])
    assert not is_simple_launch_args(["--port", "4444"])
    assert not is_simple_launch_args(["https://api.deepseek.com/v1", "sk-test"])


def test_build_launcher_config_uses_local_bridge_and_openai_api_key(tmp_path: Path) -> None:
    config = build_launcher_config("deepseek-v4-flash", tmp_path)
    assert f'base_url = "{LOCAL_BRIDGE_URL}"' in config
    assert 'env_key = "OPENAI_API_KEY"' in config
    assert f'[projects."{tmp_path.resolve()}"]' in config


def test_prepare_temp_codex_home_writes_config(tmp_path: Path) -> None:
    home_dir = prepare_temp_codex_home(tmp_path, "deepseek-v4-flash")
    assert home_dir == tmp_path / TEMP_CODEX_HOME_NAME
    config_path = home_dir / "config.toml"
    assert config_path.exists()
    config = config_path.read_text(encoding="utf-8")
    assert 'model = "deepseek-v4-flash"' in config
