# -*- coding: utf-8 -*-
"""
超薄 CC 桥接层（单轮调用）。

职责：
- 组装本地 ClaudeCode_CN 命令
- 执行一次非交互调用
- 返回结构化结果（文本/错误/耗时）
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from typing import Any, Dict, List, Optional

from cc_tool_compat import mark_openai_tool_mode, resolve_openai_tool_mode


DEFAULT_CC_ROOT = os.path.abspath(
    str(os.getenv("TYXT_CC_ROOT") or r"E:\ClaudeCode_CN")
)
DEFAULT_TIMEOUT_SEC = 180
DEFAULT_CMD_BASE = [
    "bun",
    "cli.js",
    "--print",
    "--output-format",
    "text",
]
DEFAULT_PERMISSION_MODE = "bypassPermissions"
DEFAULT_RETRY_ON_EMPTY_OUTPUT = True
DEFAULT_OPENAI_SAFE_TOOLS = "Bash,Edit,Read,Write,Grep,Glob,LS"


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return int(default)
        return int(float(str(value).strip()))
    except Exception:
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "on", "enabled"}:
        return True
    if s in {"0", "false", "no", "off", "disabled"}:
        return False
    return bool(default)


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _write_tyxt_cc_log(
    path: str,
    *,
    prompt: str,
    command: List[str],
    ok: bool,
    error: str,
    stdout_text: str,
    stderr_text: str,
    duration_ms: int,
    exit_code: int,
) -> str:
    target = str(path or "").strip()
    if not target:
        return ""
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
    except Exception:
        return ""
    now_text = time.strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = []
    lines.append(f"# TYXT -> CC Task Run Log ({now_text})")
    lines.append("")
    lines.append(f"- ok: {'true' if ok else 'false'}")
    lines.append(f"- exit_code: {int(exit_code)}")
    lines.append(f"- duration_ms: {int(duration_ms)}")
    lines.append(f"- command: {' '.join([str(x) for x in (command or [])])}")
    if error:
        lines.append(f"- error: {str(error)}")
    lines.append("")
    lines.append("## Prompt")
    lines.append("```text")
    lines.append(str(prompt or ""))
    lines.append("```")
    lines.append("")
    lines.append("## Stdout")
    lines.append("```text")
    lines.append(str(stdout_text or ""))
    lines.append("```")
    lines.append("")
    lines.append("## Stderr")
    lines.append("```text")
    lines.append(str(stderr_text or ""))
    lines.append("```")
    lines.append("")
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return target
    except Exception:
        return ""


def _parse_cmd_base(raw: str) -> List[str]:
    try:
        parts = shlex.split(str(raw or "").strip(), posix=False)
        return [str(x) for x in parts if str(x).strip()]
    except Exception:
        return []


def _resolve_command_base() -> List[str]:
    raw = str(os.getenv("TYXT_CC_BRIDGE_CMD") or "").strip()
    base = _parse_cmd_base(raw) if raw else []
    default_max_turns = str(max(1, _safe_int(os.getenv("TYXT_CC_MAX_TURNS"), 8)))
    if not base:
        base = list(DEFAULT_CMD_BASE)
    if ("-p" not in base) and ("--print" not in base):
        base.append("--print")
    if "--output-format" not in base:
        base.extend(["--output-format", "text"])
    if "--max-turns" not in base:
        base.extend(["--max-turns", default_max_turns])
    return base


def _command_has_flag(parts: List[str], flag: str) -> bool:
    target = str(flag or "").strip().lower()
    if not target:
        return False
    for item in parts:
        token = str(item or "").strip().lower()
        if token == target:
            return True
        if target == "--model" and token.startswith("--model="):
            return True
        if target == "--permission-mode" and token.startswith("--permission-mode="):
            return True
        if target == "--add-dir" and token.startswith("--add-dir="):
            return True
        if target == "--tools" and token.startswith("--tools="):
            return True
    return False


def _looks_like_openai_schema_error(text: str) -> bool:
    low = str(text or "").strip().lower()
    if not low:
        return False
    return (
        ("validationexception" in low and "improperly formed request" in low)
        or ("invalid_request_error" in low and "improperly formed request" in low)
    )


def _resolve_existing_dir(path_text: Any) -> str:
    raw = str(path_text or "").strip()
    if not raw:
        return ""
    try:
        abs_path = os.path.abspath(raw)
    except Exception:
        return ""
    if not os.path.isdir(abs_path):
        return ""
    return abs_path


def _normalize_login_mode(value: Any) -> str:
    s = str(value or "").strip().lower()
    if s in {"claude_subscription", "claudeai", "claude", "claude_subscription_account"}:
        return "claude_subscription"
    if s in {"anthropic_console", "console", "anthropic"}:
        return "anthropic_console"
    if s in {"openai", "openai_api", "openai-api"}:
        return "openai_api"
    if s == "ollama":
        return "ollama"
    if s in {"codex_login", "codex", "chatgpt", "codex_chatgpt"}:
        return "codex_login"
    return "claude_subscription"


def _normalize_bridge_config(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    return {
        "cc_root": str(data.get("cc_root") or data.get("ccRoot") or "").strip(),
        "cc_allowed_workspace_dir": str(
            data.get("cc_allowed_workspace_dir")
            or data.get("ccAllowedWorkspaceDir")
            or data.get("cc_allowed_project_dir")
            or data.get("ccAllowedProjectDir")
            or ""
        ).strip(),
        "login_mode": _normalize_login_mode(data.get("login_mode") or data.get("loginMode")),
        "openai_base_url": str(data.get("openai_base_url") or data.get("openaiBaseUrl") or "").strip(),
        "openai_api_key": str(data.get("openai_api_key") or data.get("openaiApiKey") or "").strip(),
        "openai_model": str(
            data.get("openai_model")
            or data.get("openaiModel")
            or data.get("model_name")
            or data.get("modelName")
            or ""
        ).strip(),
        "ollama_base_url": str(data.get("ollama_base_url") or data.get("ollamaBaseUrl") or "").strip(),
        "ollama_model": str(data.get("ollama_model") or data.get("ollamaModel") or "").strip(),
    }


def call_local_cc_once(
    prompt: str,
    workspace_path: str = "",
    timeout_sec: Optional[int] = None,
    extra_env: Optional[Dict[str, str]] = None,
    bridge_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.time()
    text = _clean_text(prompt)
    if not text:
        return {
            "ok": False,
            "error": "empty_prompt",
            "text": "",
            "duration_ms": 0,
        }

    normalized_cfg = _normalize_bridge_config(bridge_config)
    cc_root_cfg = str(normalized_cfg.get("cc_root") or "").strip()
    cc_root = os.path.abspath(cc_root_cfg or str(os.getenv("TYXT_CC_ROOT") or DEFAULT_CC_ROOT))
    if not os.path.isdir(cc_root):
        return {
            "ok": False,
            "error": f"cc_root_not_found: {cc_root}",
            "text": "",
            "duration_ms": 0,
        }

    cmd = _resolve_command_base()

    env = os.environ.copy()
    login_mode = _normalize_login_mode(normalized_cfg.get("login_mode") or os.getenv("TYXT_CC_LOGIN_MODE"))
    env["TYXT_CC_LOGIN_MODE"] = login_mode
    model_name = ""
    openai_base_url = ""
    openai_api_key = ""
    openai_model = ""
    if login_mode == "openai_api":
        openai_base_url = str(normalized_cfg.get("openai_base_url") or "").strip()
        openai_api_key = str(normalized_cfg.get("openai_api_key") or "").strip()
        openai_model = str(normalized_cfg.get("openai_model") or "").strip()
        env["CLAUDE_CODE_USE_OPENAI"] = "1"
        env.pop("CLAUDE_CODE_USE_OLLAMA", None)
        if openai_base_url:
            env["OPENAI_BASE_URL"] = openai_base_url
            env["OPENAI_API_BASE"] = openai_base_url
        if openai_api_key:
            env["OPENAI_API_KEY"] = openai_api_key
        if openai_model:
            env["OPENAI_MODEL"] = openai_model
            env["TYXT_OPENAI_MODEL"] = openai_model
            model_name = openai_model
    elif login_mode == "ollama":
        ollama_base = str(normalized_cfg.get("ollama_base_url") or "").strip()
        ollama_model = str(normalized_cfg.get("ollama_model") or "").strip()
        env["CLAUDE_CODE_USE_OLLAMA"] = "1"
        env.pop("CLAUDE_CODE_USE_OPENAI", None)
        if ollama_base:
            env["OLLAMA_BASE_URL"] = ollama_base
            env["OLLAMA_HOST"] = ollama_base
        if ollama_model:
            env["OLLAMA_MODEL"] = ollama_model
            env["TYXT_OLLAMA_MODEL"] = ollama_model
            model_name = ollama_model
    else:
        # Claude subscription / Anthropic Console / Codex(ChatGPT) should use CC built-in auth flow.
        env.pop("CLAUDE_CODE_USE_OPENAI", None)
        env.pop("CLAUDE_CODE_USE_OLLAMA", None)

    # Keep model linkage via env by default.
    # Some CC builds interpret `--model` under non-ollama providers, causing routing errors.
    append_model_flag = _safe_bool(os.getenv("TYXT_CC_APPEND_MODEL_FLAG"), False)
    if append_model_flag and model_name and not _command_has_flag(cmd, "--model"):
        cmd.extend(["--model", model_name])

    # OpenAI-compatible gateways vary by channel/model.
    # Auto mode probes compatibility and caches full/safe selection.
    if login_mode == "openai_api" and (not _command_has_flag(cmd, "--tools")):
        tools_mode = str(os.getenv("TYXT_CC_OPENAI_TOOLS_MODE") or "auto").strip().lower()
        if tools_mode not in {"auto", "safe", "full"}:
            tools_mode = "auto"
        effective_mode = tools_mode
        if tools_mode == "auto":
            effective_mode = resolve_openai_tool_mode(
                openai_base_url,
                openai_api_key,
                openai_model or model_name,
                preferred="auto",
            )
        if effective_mode == "safe":
            safe_tools = str(os.getenv("TYXT_CC_OPENAI_SAFE_TOOLS") or DEFAULT_OPENAI_SAFE_TOOLS).strip()
            if safe_tools:
                cmd.extend(["--tools", safe_tools])

    enable_perm_bypass = _safe_bool(
        os.getenv("TYXT_CC_ENABLE_PERMISSION_BYPASS"),
        True,
    )
    if enable_perm_bypass:
        perm_mode = str(os.getenv("TYXT_CC_PERMISSION_MODE") or DEFAULT_PERMISSION_MODE).strip()
        if perm_mode and not _command_has_flag(cmd, "--permission-mode"):
            cmd.extend(["--permission-mode", perm_mode])
        if (not _command_has_flag(cmd, "--dangerously-skip-permissions")) and (
            not _command_has_flag(cmd, "--allow-dangerously-skip-permissions")
        ):
            cmd.append("--dangerously-skip-permissions")

    ws = str(workspace_path or "").strip()
    ws_dir = _resolve_existing_dir(ws)
    allowed_ws_dir = _resolve_existing_dir(normalized_cfg.get("cc_allowed_workspace_dir"))
    add_dir_candidates: List[str] = []
    if ws_dir:
        add_dir_candidates.append(ws_dir)
    if allowed_ws_dir and allowed_ws_dir not in add_dir_candidates:
        add_dir_candidates.append(allowed_ws_dir)
    if add_dir_candidates and (not _command_has_flag(cmd, "--add-dir")):
        for folder in add_dir_candidates:
            cmd.extend(["--add-dir", folder])
    if ws:
        env["TYXT_WORKSPACE_PATH"] = ws

    if isinstance(extra_env, dict):
        for k, v in extra_env.items():
            key = str(k or "").strip()
            if not key:
                continue
            env[key] = str(v or "")
    cc_log_path = str(env.get("TYXT_CC_LOG_PATH") or "").strip()

    timeout = _safe_int(
        timeout_sec if timeout_sec is not None else os.getenv("TYXT_CC_TIMEOUT_SEC"),
        DEFAULT_TIMEOUT_SEC,
    )
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_SEC

    # `--add-dir` may consume following positional tokens in some CLI parsers.
    # Insert `--` so the prompt is always treated as a positional argument.
    if "--" not in cmd:
        cmd.append("--")
    cmd.append(text)
    # Always run from CC root so relative "cli.js" is resolvable.
    # Workspace scope is passed via --add-dir and TYXT_WORKSPACE_PATH.
    run_cwd = cc_root

    try:
        proc = subprocess.run(
            cmd,
            cwd=run_cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError as e:
        return {
            "ok": False,
            "error": f"cc_command_not_found: {e}",
            "text": "",
            "duration_ms": int((time.time() - started) * 1000),
            "command": cmd,
            "cwd": run_cwd,
            "login_mode": login_mode,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"cc_timeout: {timeout}s",
            "text": "",
            "duration_ms": int((time.time() - started) * 1000),
            "command": cmd,
            "cwd": run_cwd,
            "login_mode": login_mode,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"cc_exec_failed: {e}",
            "text": "",
            "duration_ms": int((time.time() - started) * 1000),
            "command": cmd,
            "cwd": run_cwd,
            "login_mode": login_mode,
        }

    stdout_text = _clean_text(proc.stdout)
    stderr_text = _clean_text(proc.stderr)
    retry_openai_safe_tools = _safe_bool(
        os.getenv("TYXT_CC_RETRY_OPENAI_SAFE_TOOLS"),
        True,
    )
    if (
        login_mode == "openai_api"
        and retry_openai_safe_tools
        and int(proc.returncode) != 0
        and (not _command_has_flag(cmd, "--tools"))
        and _looks_like_openai_schema_error(f"{stderr_text}\n{stdout_text}")
    ):
        mark_openai_tool_mode(
            openai_base_url,
            openai_model or model_name,
            "safe",
            reason="runtime_schema_error",
        )
        safe_tools = str(os.getenv("TYXT_CC_OPENAI_SAFE_TOOLS") or DEFAULT_OPENAI_SAFE_TOOLS).strip()
        if safe_tools:
            retry_cmd = list(cmd)
            if "--" in retry_cmd:
                split_idx = retry_cmd.index("--")
                retry_cmd[split_idx:split_idx] = ["--tools", safe_tools]
            else:
                retry_cmd.extend(["--tools", safe_tools])
            try:
                proc_retry = subprocess.run(
                    retry_cmd,
                    cwd=run_cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    env=env,
                )
                proc = proc_retry
                cmd = retry_cmd
                stdout_text = _clean_text(proc_retry.stdout)
                stderr_text = _clean_text(proc_retry.stderr)
            except Exception:
                pass

    retry_on_empty_output = _safe_bool(
        os.getenv("TYXT_CC_RETRY_ON_EMPTY_OUTPUT"),
        DEFAULT_RETRY_ON_EMPTY_OUTPUT,
    )
    if proc.returncode == 0 and (not stdout_text) and (not stderr_text) and retry_on_empty_output:
        try:
            proc_retry = subprocess.run(
                cmd,
                cwd=run_cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
            retry_stdout = _clean_text(proc_retry.stdout)
            retry_stderr = _clean_text(proc_retry.stderr)
            if retry_stdout or retry_stderr:
                proc = proc_retry
                stdout_text = retry_stdout
                stderr_text = retry_stderr
            else:
                # Keep retry result for richer diagnostics (e.g. non-zero on second run).
                proc = proc_retry
                stdout_text = retry_stdout
                stderr_text = retry_stderr
        except Exception:
            pass

    duration_ms = int((time.time() - started) * 1000)
    combined_text = stdout_text or stderr_text

    if proc.returncode == 0 and combined_text:
        if login_mode == "openai_api" and (not _command_has_flag(cmd, "--tools")):
            mark_openai_tool_mode(
                openai_base_url,
                openai_model or model_name,
                "full",
                reason="runtime_success_no_tools",
            )
        cc_log_written = _write_tyxt_cc_log(
            cc_log_path,
            prompt=text,
            command=cmd,
            ok=True,
            error="",
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            duration_ms=duration_ms,
            exit_code=int(proc.returncode),
        )
        return {
            "ok": True,
            "text": combined_text,
            "error": "",
            "exit_code": int(proc.returncode),
            "stdout": stdout_text,
            "stderr": stderr_text,
            "duration_ms": duration_ms,
            "command": cmd,
            "cwd": run_cwd,
            "login_mode": login_mode,
            "cc_log_path": cc_log_written,
        }

    cc_log_written = _write_tyxt_cc_log(
        cc_log_path,
        prompt=text,
        command=cmd,
        ok=False,
        error=(
            stderr_text
            or stdout_text
            or ("cc_empty_output_exit0" if int(proc.returncode) == 0 else f"cc_exit_{proc.returncode}")
        ),
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        duration_ms=duration_ms,
        exit_code=int(proc.returncode),
    )
    return {
        "ok": False,
        "text": "",
        "error": (
            stderr_text
            or stdout_text
            or ("cc_empty_output_exit0" if int(proc.returncode) == 0 else f"cc_exit_{proc.returncode}")
        ),
        "exit_code": int(proc.returncode),
        "stdout": stdout_text,
        "stderr": stderr_text,
        "duration_ms": duration_ms,
        "command": cmd,
        "cwd": run_cwd,
        "login_mode": login_mode,
        "cc_log_path": cc_log_written,
    }


__all__ = ["call_local_cc_once"]
