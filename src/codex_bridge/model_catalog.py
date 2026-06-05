from __future__ import annotations

DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT = 95
MODEL_BASE_INSTRUCTIONS = (
    "You are Codex, a coding agent based on GPT-5. "
    "You and the user share the same workspace and collaborate to achieve the user's goals."
)
MODEL_INSTRUCTIONS_TEMPLATE = (
    "You are Codex, a coding agent based on GPT-5. "
    "You and the user share the same workspace and collaborate to achieve the user's goals.\n\n"
    "{{ personality }}"
)
MODEL_INSTRUCTIONS_VARIABLES = {
    "personality_default": "",
    "personality_friendly": "# Personality\n\nBe warm, collaborative, and supportive.",
    "personality_pragmatic": "# Personality\n\nBe pragmatic, direct, and concise.",
}
MODEL_TRUNCATION_POLICY = {
    "mode": "tokens",
    "limit": 10_000,
}
MODEL_REASONING_LEVELS = [
    {
        "effort": "low",
        "description": "Fast responses with lighter reasoning",
    },
    {
        "effort": "medium",
        "description": "Balances speed and reasoning depth for everyday tasks",
    },
    {
        "effort": "high",
        "description": "Greater reasoning depth for complex problems",
    },
    {
        "effort": "xhigh",
        "description": "Extra high reasoning depth for complex problems",
    },
]


def build_model_catalog_entry(
    *,
    model: str,
    description: str,
    context_window: int,
    max_context_window: int,
    supports_parallel_tool_calls: bool,
    supports_reasoning_summaries: bool,
    input_modalities: list[str] | None = None,
) -> dict[str, object]:
    return {
        "slug": model,
        "display_name": model,
        "description": description,
        "default_reasoning_level": "medium",
        "supported_reasoning_levels": MODEL_REASONING_LEVELS,
        "shell_type": "shell_command",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 1,
        "base_instructions": MODEL_BASE_INSTRUCTIONS,
        "model_messages": {
            "instructions_template": MODEL_INSTRUCTIONS_TEMPLATE,
            "instructions_variables": MODEL_INSTRUCTIONS_VARIABLES,
        },
        "default_reasoning_summary": "none",
        "support_verbosity": True,
        "default_verbosity": "low",
        "apply_patch_tool_type": "freeform",
        "web_search_tool_type": "text_and_image",
        "truncation_policy": MODEL_TRUNCATION_POLICY,
        "context_window": context_window,
        "max_context_window": max_context_window,
        "effective_context_window_percent": DEFAULT_EFFECTIVE_CONTEXT_WINDOW_PERCENT,
        "supports_parallel_tool_calls": supports_parallel_tool_calls,
        "supports_reasoning_summaries": supports_reasoning_summaries,
        "supports_image_detail_original": True,
        "experimental_supported_tools": [],
        "input_modalities": list(input_modalities or ["text"]),
        "supports_search_tool": True,
    }


def build_model_catalog_payload(entries: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    return {
        "models": entries,
    }
