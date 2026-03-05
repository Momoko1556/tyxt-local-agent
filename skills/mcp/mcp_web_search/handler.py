from typing import Any, Dict


def run(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deprecated compatibility shim.

    This local handler is no longer used in normal runtime because
    `skills/mcp/mcp_web_search/skill.json` is now `type = "mcp"` and is dispatched by
    the unified MCP skill handler in `ollama_multi_agent.py`.
    """
    _ = params
    _ = context
    return {
        "ok": False,
        "data": None,
        "error": "deprecated_handler_path: mcp_web_search now uses unified MCP dispatcher",
    }
