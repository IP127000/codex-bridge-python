from __future__ import annotations

import json
from pathlib import Path

from codex_bridge.launch import (
    CODEX_BRIDGE_HOME_NAME,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT,
    LOCAL_BRIDGE_URL,
    MODEL_CATALOG_NAME,
    build_launcher_config,
    build_model_catalog,
    codex_bridge_home_dir,
    codex_launch_workdir,
    context_window_for_model,
    is_simple_launch_args,
    load_saved_api_key,
    load_saved_launcher_config,
    normalize_context_window,
    prepare_temp_codex_home,
    resolve_simple_launch_args,
    write_auth_json,
)


def test_is_simple_launch_args_accepts_up_to_four_positionals() -> None:
    assert is_simple_launch_args(["https://api.deepseek.com/v1", "sk-test", "deepseek-v4-flash"])
    assert is_simple_launch_args([])
    assert is_simple_launch_args(["https://api.deepseek.com/v1"])
    assert is_simple_launch_args(["https://api.deepseek.com/v1", "sk-test", "deepseek-v4-flash", "262144"])
    assert not is_simple_launch_args(["--port", "4444"])
    assert not is_simple_launch_args(["a", "b", "c", "d", "e"])


def test_build_launcher_config_uses_local_bridge_and_openai_api_key(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    config = build_launcher_config(home_dir, "https://api.deepseek.com/v1", "deepseek-v4-flash", tmp_path, 262144)
    assert f'base_url = "{LOCAL_BRIDGE_URL}"' in config
    assert 'env_key = "OPENAI_API_KEY"' in config
    assert 'model_reasoning_effort = "high"' in config
    assert "model_context_window = 262144" in config
    assert "model_auto_compact_token_limit = 131072" in config
    assert "enable_request_compression = true" in config
    assert f'model_catalog_json = "{home_dir / MODEL_CATALOG_NAME}"' in config
    assert '[codex_bridge_launcher]' in config
    assert 'upstream = "https://api.deepseek.com/v1"' in config
    assert "context_window = 262144" in config
    assert f'[projects."{tmp_path.resolve()}"]' in config


def test_build_model_catalog_matches_expected_schema(tmp_path: Path) -> None:
    catalog = build_model_catalog("https://api.deepseek.com/v1", "deepseek-v4-flash", 262144)
    model = catalog["models"][0]
    assert model["slug"] == "deepseek-v4-flash"
    assert model["default_reasoning_level"] == "medium"
    assert model["context_window"] == 262144
    assert model["effective_context_window_percent"] == DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT
    assert model["supported_in_api"] is True
    assert isinstance(model["base_instructions"], str)
    assert isinstance(model["model_messages"], dict)
    assert model["supports_image_detail_original"] is True
    assert model["supports_search_tool"] is True
    assert isinstance(model["supported_reasoning_levels"], list)


def test_prepare_temp_codex_home_reuses_existing_selected_model_metadata(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    home_dir.mkdir(parents=True)
    original_catalog = {
        "models": [
            {
                "slug": "deepseek-v4-flash",
                "display_name": "cached-deepseek",
                "description": "cached",
                "default_reasoning_level": "medium",
                "supported_reasoning_levels": [],
                "shell_type": "shell_command",
                "visibility": "list",
                "supported_in_api": True,
                "priority": 1,
                "base_instructions": "cached",
                "model_messages": {"instructions_template": "", "instructions_variables": {}},
                "default_reasoning_summary": "none",
                "support_verbosity": True,
                "default_verbosity": "low",
                "apply_patch_tool_type": "freeform",
                "web_search_tool_type": "text_and_image",
                "truncation_policy": {"mode": "tokens", "limit": 10000},
                "context_window": 262144,
                "max_context_window": 1048576,
                "effective_context_window_percent": 95,
                "supports_parallel_tool_calls": True,
                "supports_reasoning_summaries": True,
                "supports_image_detail_original": True,
                "experimental_supported_tools": [],
                "input_modalities": ["text"],
                "supports_search_tool": True,
            },
            {
                "slug": "qwen-plus",
                "display_name": "qwen-plus",
                "description": "cached-qwen",
                "default_reasoning_level": "medium",
                "supported_reasoning_levels": [],
                "shell_type": "shell_command",
                "visibility": "list",
                "supported_in_api": True,
                "priority": 1,
                "base_instructions": "cached",
                "model_messages": {"instructions_template": "", "instructions_variables": {}},
                "default_reasoning_summary": "none",
                "support_verbosity": True,
                "default_verbosity": "low",
                "apply_patch_tool_type": "freeform",
                "web_search_tool_type": "text_and_image",
                "truncation_policy": {"mode": "tokens", "limit": 10000},
                "context_window": 131072,
                "max_context_window": 131072,
                "effective_context_window_percent": 95,
                "supports_parallel_tool_calls": True,
                "supports_reasoning_summaries": False,
                "supports_image_detail_original": True,
                "experimental_supported_tools": [],
                "input_modalities": ["text"],
                "supports_search_tool": True,
            },
        ]
    }
    (home_dir / MODEL_CATALOG_NAME).write_text(json.dumps(original_catalog), encoding="utf-8")
    prepare_temp_codex_home(
        home_dir,
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-v4-flash",
        tmp_path,
        262144,
        ["deepseek-v4-flash"],
        reset=False,
    )
    catalog = json.loads((home_dir / MODEL_CATALOG_NAME).read_text(encoding="utf-8"))
    assert len(catalog["models"]) == 1
    assert catalog["models"][0]["slug"] == "deepseek-v4-flash"
    assert catalog["models"][0]["display_name"] == "cached-deepseek"


def test_prepare_temp_codex_home_writes_config(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    home_dir = prepare_temp_codex_home(
        home_dir,
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-v4-flash",
        tmp_path,
        262144,
        ["deepseek-v4-flash"],
        reset=True,
    )
    assert home_dir == tmp_path / CODEX_BRIDGE_HOME_NAME
    config_path = home_dir / "config.toml"
    auth_path = home_dir / "auth.json"
    catalog_path = home_dir / MODEL_CATALOG_NAME
    assert config_path.exists()
    assert auth_path.exists()
    assert catalog_path.exists()
    config = config_path.read_text(encoding="utf-8")
    assert 'model = "deepseek-v4-flash"' in config
    assert "model_context_window = 262144" in config
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert catalog["models"][0]["slug"] == "deepseek-v4-flash"
    auth = json.loads(auth_path.read_text(encoding="utf-8"))
    assert auth["OPENAI_API_KEY"] == "sk-test"


def test_load_saved_launcher_config_reads_saved_values(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    prepare_temp_codex_home(
        home_dir,
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-v4-flash",
        tmp_path,
        262144,
        ["deepseek-v4-flash"],
        reset=True,
    )
    saved = load_saved_launcher_config(home_dir)
    assert saved["upstream"] == "https://api.deepseek.com/v1"
    assert saved["model"] == "deepseek-v4-flash"
    assert saved["context_window"] == 262144


def test_load_saved_api_key_reads_auth_json(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    home_dir.mkdir(parents=True)
    write_auth_json(home_dir, "sk-test")
    assert load_saved_api_key(home_dir) == "sk-test"


def test_resolve_simple_launch_args_fills_missing_values_from_saved_home(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    prepare_temp_codex_home(
        home_dir,
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-v4-flash",
        tmp_path,
        262144,
        ["deepseek-v4-flash"],
        reset=True,
    )
    base_url, api_key, model, context_window, reset_home = resolve_simple_launch_args(
        ["https://api.deepseek.com/v1"],
        home_dir,
    )
    assert base_url == "https://api.deepseek.com/v1"
    assert api_key == "sk-test"
    assert model == "deepseek-v4-flash"
    assert context_window == 262144
    assert not reset_home


def test_resolve_simple_launch_args_does_not_reuse_model_for_different_upstream(tmp_path: Path) -> None:
    home_dir = tmp_path / CODEX_BRIDGE_HOME_NAME
    prepare_temp_codex_home(
        home_dir,
        "https://api.deepseek.com/v1",
        "sk-test",
        "deepseek-v4-flash",
        tmp_path,
        262144,
        ["deepseek-v4-flash"],
        reset=True,
    )
    try:
        resolve_simple_launch_args(
            ["https://dashscope.aliyuncs.com/compatible-mode/v1"],
            home_dir,
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert "model" in message


def test_resolve_simple_launch_args_reports_missing_values(tmp_path: Path) -> None:
    try:
        resolve_simple_launch_args([], tmp_path / CODEX_BRIDGE_HOME_NAME)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert "base_url" in message
    assert "api_key" in message
    assert "model" in message


def test_resolve_simple_launch_args_prefers_explicit_context_window(tmp_path: Path) -> None:
    base_url, api_key, model, context_window, reset_home = resolve_simple_launch_args(
        ["https://api.deepseek.com/v1", "sk-test", "deepseek-v4-flash", "99999"],
        tmp_path / CODEX_BRIDGE_HOME_NAME,
    )
    assert base_url == "https://api.deepseek.com/v1"
    assert api_key == "sk-test"
    assert model == "deepseek-v4-flash"
    assert context_window == 99999
    assert reset_home


def test_normalize_context_window_defaults_to_128k_for_invalid_values() -> None:
    assert normalize_context_window(None) == DEFAULT_CONTEXT_WINDOW
    assert normalize_context_window("abc") == DEFAULT_CONTEXT_WINDOW
    assert normalize_context_window(0) == DEFAULT_CONTEXT_WINDOW


def test_context_window_for_model_falls_back_to_default_for_unknown_model() -> None:
    assert context_window_for_model("unknown-model-slug") == DEFAULT_CONTEXT_WINDOW


def test_codex_launch_workdir_moves_home_launches_into_bridge_home(tmp_path: Path, monkeypatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert codex_bridge_home_dir() == fake_home / CODEX_BRIDGE_HOME_NAME
    assert codex_launch_workdir(fake_home) == fake_home / CODEX_BRIDGE_HOME_NAME
    nested = fake_home / "project"
    nested.mkdir()
    assert codex_launch_workdir(nested) == nested
