# -*- coding: utf-8 -*-
# ============================================================
# 00. 文件说明 / 版本记录（不要删）/脚本版本号：2603031127
# ============================================================
# Ollama Multi-Agent Backend (full, merged, type-safe)
# 保留原有全部功能：健康检查、/chat 流式/非流式、向量记忆、共享区 I/O、上网搜索等
# 修复：元数据数值比较统一强转，避免 'str' vs 'int' 比较异常
# 不输出 prompts.txt 内容到后台日志
# ============================================================
# 01. Imports / 第三方依赖
# ============================================================

import os
import re
import json
import time
import shlex
import base64
import mimetypes
import io
import threading
import subprocess
import importlib.util
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from typing import Deque, List, Dict, Any, Optional, Tuple
from collections import deque
from urllib.parse import urlparse, parse_qs, unquote

import datetime  # ✅ 用模块方式，后续可用 datetime.datetime / datetime.timedelta，避免 AttributeError

import requests
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

if load_dotenv:
    _DOTENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_DOTENV_PATH, override=False)

from flask import Flask, request, jsonify, make_response, Response, stream_with_context, send_from_directory, send_file, url_for, session
from flask_cors import CORS
from werkzeug.utils import secure_filename

from chromadb.api.types import Documents, Embeddings
from chromadb.utils.embedding_functions import EmbeddingFunction

# 共享区读取依赖（与原脚本一致）
import pandas as pd
import docx
from PIL import Image

# ========= Runtime switches =========
# “闭嘴”功能用：如果当前时间 < 这个时间戳，则直接不回复
MUTE_UNTIL_TS = 0.0   # 全局禁言截止时间戳（秒）


# PDF 文本
import fitz

# 多模态工具统一入口（OCR/TTS/ASR/文生图）
import multimodal_tools
import skills_registry
import mcp_bridge
import mcp_manager
from profiles_store import (
    apply_profile_note as profiles_apply_profile_note,
    append_memory_strip as profiles_append_memory_strip,
    load_memory_strips as profiles_load_memory_strips,
    load_user_profile as profiles_load_user_profile,
    maybe_update_user_profile_from_turn as profiles_maybe_update_user_profile_from_turn,
    normalize_profile_user_id,
    save_memory_strips as profiles_save_memory_strips,
    update_user_location as profiles_update_user_location,
)
from memory_store import CHROMA_COLLECTION_NAME, CHROMA_PERSIST_DIR, make_collection_name, parse_collection_name
from memory_retriever_v2 import (
    CHAT_MEM_STORE,
    IMPORTANCE_HIT_BOOST,
    MEM_STORE,
    bump_chat_memory_importance,
    effective_importance,
    resolve_channel_owner,
    retrieve_chat_memory_records,
    retrieve_chat_memories,
    retrieve_memories,
)
from import_chatgpt_export import import_chatgpt_export_records
from import_kb_files import import_kb_records

# ============================================================
# 02. 工具函数（安全类型转换）
# ============================================================

def safe_int(v, default=0) -> int:
    try:
        if v is None:
            return int(default)
        s = str(v).strip()
        if s == "":
            return int(default)
        return int(float(s))
    except Exception:
        return int(default)

def safe_float(v, default=0.0) -> float:
    try:
        if v is None:
            return float(default)
        s = str(v).strip()
        if s == "":
            return float(default)
        return float(s)
    except Exception:
        return float(default)

# ✅ 兼容旧命名：脚本其它地方仍可能在用 _safe_int / _safe_float
_safe_int = safe_int
_safe_float = safe_float

def safe_bool(v, default=False) -> bool:
    try:
        if isinstance(v, bool):
            return v
        if v is None:
            return bool(default)
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if not s:
            return bool(default)
        if s in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
            return True
        if s in {"0", "false", "no", "n", "off", "disable", "disabled"}:
            return False
        return bool(default)
    except Exception:
        return bool(default)


_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _current_system_time_info() -> Dict[str, str]:
    """
    每次调用都实时读取本机系统时间（含时区），用于“时间感知”注入。
    """
    try:
        now = datetime.datetime.now().astimezone()
    except Exception:
        now = datetime.datetime.now()

    try:
        weekday = _WEEKDAY_ZH[now.weekday()]
    except Exception:
        weekday = ""

    tz_name = ""
    try:
        tz_name = str(now.tzname() or "").strip()
    except Exception:
        tz_name = ""

    offset_raw = ""
    try:
        offset_raw = now.strftime("%z")  # 例如 +0800
    except Exception:
        offset_raw = ""
    if len(offset_raw) == 5 and (offset_raw.startswith("+") or offset_raw.startswith("-")):
        offset = f"{offset_raw[:3]}:{offset_raw[3:]}"  # +08:00
    else:
        offset = offset_raw

    return {
        "local_dt": now.strftime("%Y-%m-%d %H:%M:%S"),
        "iso": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "weekday": weekday,
        "tz_name": tz_name,
        "utc_offset": offset,
        "unix_ts": str(int(now.timestamp())),
    }


def _build_system_time_block() -> str:
    """
    给模型的“当前系统时间”上下文块。
    """
    t = _current_system_time_info()
    tz_display = t.get("tz_name", "")
    if t.get("utc_offset"):
        tz_display = f"{tz_display} (UTC{t['utc_offset']})".strip()

    return (
        "【当前系统时间】\n"
        f"- 本地时间: {t.get('local_dt', '')}\n"
        f"- 星期: {t.get('weekday', '')}\n"
        f"- 时区: {tz_display}\n"
        f"- ISO时间: {t.get('iso', '')}\n"
        f"- Unix时间戳: {t.get('unix_ts', '')}\n"
        "【时间使用规则】涉及“今天/明天/昨天/现在”等相对时间时，以上述系统时间为准。"
    )

# ============================================================
# 03. 基础配置：服务地址 / 模型 / 目录 / 文件路径
# ============================================================
# 本模块只做「配置定义」，不包含任何业务逻辑
# ------------------------------------------------------------

# ========== Ollama（本地） ==========
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
MODEL_NAME      = os.getenv("MODEL_NAME", "deepseek-r1:8b")
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# ========== LLM Provider 选择 ==========
# newapi : 使用云 API（OpenAI / Claude 转发等）
# ollama: 使用本地 Ollama
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

# ========== NEW API（云 API） ==========
NEWAPI_BASE_URL = os.getenv("NEWAPI_BASE_URL", "").strip()
NEWAPI_API_KEY  = os.getenv("NEWAPI_API_KEY", "").strip()
NEWAPI_MODEL    = os.getenv("NEWAPI_MODEL", "").strip()

# ========== 文件 / 目录 ==========
# 允许访问的共享目录（图片 / 表情包 / OCR 输入等）
ALLOWED_DIR = os.getenv(
    "ALLOWED_DIR",
    os.path.join(PROJECT_ROOT, "Ollama_agent_shared"),
)
ALLOWED_DIR = os.path.abspath(str(ALLOWED_DIR))
IMPORT_DROP_DIR = os.path.join(ALLOWED_DIR, "import")
os.makedirs(IMPORT_DROP_DIR, exist_ok=True)

WAREHOUSE_BASE_DIR = os.getenv(
    "TYXT_WAREHOUSE_DIR",
    os.path.join(PROJECT_ROOT, "memory_warehouse"),
)
WAREHOUSE_BASE_DIR = os.path.abspath(str(WAREHOUSE_BASE_DIR))
ONLINE_MEMORY_DIR = os.path.join(WAREHOUSE_BASE_DIR, "online")
os.makedirs(ONLINE_MEMORY_DIR, exist_ok=True)

TYXT_PROFILE_DIR = os.getenv(
    "TYXT_PROFILE_DIR",
    os.path.join(PROJECT_ROOT, "profiles"),
)
TYXT_PROFILE_DIR = os.path.abspath(str(TYXT_PROFILE_DIR))
os.environ["TYXT_PROFILE_DIR"] = TYXT_PROFILE_DIR
os.makedirs(TYXT_PROFILE_DIR, exist_ok=True)

# TYXT 前端 HTML 文件路径（默认当前脚本所在目录下的 TYXT_UI.html）
TYXT_UI_HTML = os.getenv(
    "TYXT_UI_HTML",
    os.path.join(PROJECT_ROOT, "frontend", "TYXT_UI.html"),
)
TYXT_UI_HTML = os.path.abspath(str(TYXT_UI_HTML))
TYXT_FRONTEND_DIR = os.getenv(
    "TYXT_FRONTEND_DIR",
    os.path.join(PROJECT_ROOT, "frontend"),
)
TYXT_FRONTEND_DIR = os.path.abspath(str(TYXT_FRONTEND_DIR))
TYXT_CERT_DIR = os.path.join(PROJECT_ROOT, "certs", "lan")
TYXT_LAN_ROOT_CA = os.path.join(TYXT_CERT_DIR, "rootCA.cer")
TYXT_LAN_BOOTSTRAP_JSON = os.path.join(TYXT_CERT_DIR, "lan_bootstrap.json")
TYXT_TOOLS_DIR = os.path.join(PROJECT_ROOT, "tools")
TYXT_LAN_CLIENT_JOIN_PS1 = os.path.join(TYXT_TOOLS_DIR, "join_lan_ui.ps1")
TYXT_LAN_INSTALL_ROOTCA_PS1 = os.path.join(TYXT_TOOLS_DIR, "install_lan_root_ca.ps1")

# ========= TYXT Skills (local plugin system v0.1) =========
TYXT_SKILLS_DIR = os.path.abspath(
    str(os.getenv("TYXT_SKILLS_DIR", os.path.join(PROJECT_ROOT, "skills")))
)
TYXT_SKILLS_QUARANTINE_DIR = os.path.abspath(
    str(os.getenv("TYXT_SKILLS_QUARANTINE_DIR", os.path.join(PROJECT_ROOT, "skills_quarantine")))
)
TYXT_SKILLS_BLACKLIST_PATH = os.path.abspath(
    str(os.getenv("TYXT_SKILLS_BLACKLIST_PATH", os.path.join(PROJECT_ROOT, "skills_blacklist.json")))
)
TYXT_SKILLS_STATE_PATH = os.path.abspath(
    str(os.getenv("TYXT_SKILLS_STATE_PATH", os.path.join(PROJECT_ROOT, "skills_state.json")))
)

# Global capability switches for skill runtime permission gates.
TYXT_SKILLS_ALLOW_NETWORK = safe_bool(os.getenv("TYXT_SKILLS_ALLOW_NETWORK", "1"), True)
TYXT_SKILLS_ALLOW_FILESYSTEM = safe_bool(os.getenv("TYXT_SKILLS_ALLOW_FILESYSTEM", "1"), True)
TYXT_SKILLS_ALLOW_LLM = safe_bool(os.getenv("TYXT_SKILLS_ALLOW_LLM", "0"), False)

# ========= TYXT MCP Bridge (Phase X PoC) =========
TYXT_MCP_ENABLED = safe_bool(os.getenv("TYXT_MCP_ENABLED", "0"), False)
TYXT_MCP_CONFIG_PATH = os.path.abspath(
    str(os.getenv("TYXT_MCP_CONFIG_PATH", os.path.join(PROJECT_ROOT, "configs", "mcp_servers.json")))
)

skills_registry.configure(
    skills_dir=TYXT_SKILLS_DIR,
    quarantine_dir=TYXT_SKILLS_QUARANTINE_DIR,
    blacklist_path=TYXT_SKILLS_BLACKLIST_PATH,
    state_path=TYXT_SKILLS_STATE_PATH,
)

ENABLE_PROFILE_UPDATE = safe_bool(os.getenv("TYXT_ENABLE_PROFILE_UPDATE", "1"), True)
ENABLE_MEMORY_STRIP_AUTO = safe_bool(os.getenv("TYXT_ENABLE_MEMORY_STRIP_AUTO", "1"), True)
OPEN_METEO_FORECAST_URL = os.getenv(
    "OPEN_METEO_FORECAST_URL",
    "https://api.open-meteo.com/v1/forecast",
)

# ========== GPT-SoVITS（本地 TTS） ==========
SOVITS_TTS_URL = os.getenv(
    "SOVITS_TTS_URL",
    "http://127.0.0.1:9880/tts"
)

SOVITS_REF_AUDIO_DIR = os.getenv(
    "SOVITS_REF_AUDIO_DIR",
    os.path.join(PROJECT_ROOT, "GPT-SoVITS-1007-cu124", "Cove参考音频文件"),
)
SOVITS_REF_AUDIO_DIR = os.path.abspath(str(SOVITS_REF_AUDIO_DIR))

SOVITS_TEXT_SPLIT_METHOD = os.getenv("SOVITS_TEXT_SPLIT_METHOD", "cut0")

SOVITS_VOICE_PRESETS = {
    "default": {
        "ref_audio_path": os.path.join(SOVITS_REF_AUDIO_DIR, "就算是这样，也不至于直接碎掉啊，除非.wav"),
        "prompt_text": "通常、中性、自然的语气。",
        "prompt_lang": "zh"
    },
    "calm": {
        "ref_audio_path": os.path.join(SOVITS_REF_AUDIO_DIR, "就算是这样，也不至于直接碎掉啊，除非.wav"),
        "prompt_text": "语速平稳，语气沉静。",
        "prompt_lang": "zh"
    },
    "warm": {
        "ref_audio_path": os.path.join(SOVITS_REF_AUDIO_DIR, "宝贝，不要害怕，也不要哭了.wav"),
        "prompt_text": "轻松、温柔、像朋友聊天。",
        "prompt_lang": "zh"
    },
    "bright": {
        "ref_audio_path": os.path.join(SOVITS_REF_AUDIO_DIR, "哇，你真的太棒了！我替你感到开心！.wav"),
        "prompt_text": "活泼、有一点明亮的情绪。",
        "prompt_lang": "zh"
    },
    "serious": {
        "ref_audio_path": os.path.join(SOVITS_REF_AUDIO_DIR, "就算是这样，也不至于直接碎掉啊，除非.wav"),
        "prompt_text": "偏正式、说明书风格。",
        "prompt_lang": "zh"
    },
    "angry": {
        "ref_audio_path": os.path.join(SOVITS_REF_AUDIO_DIR, "你真的有在乎过我的感受吗？我真的受够了！.wav"),
        "prompt_text": "情绪强烈、偏生气语气。",
        "prompt_lang": "zh"
    },
}

TTS_OUTPUT_DIR = os.path.join(ALLOWED_DIR, "tts")
os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)

# ========== 本地账号配置（Phase 2.0） ==========
BASE_DIR = PROJECT_ROOT
CONFIG_DIR = os.path.join(BASE_DIR, "configs")
USER_PROFILES_PATH = os.path.join(CONFIG_DIR, "user_profiles.json")
PERSONA_CONFIG_PATH = os.path.join(CONFIG_DIR, "persona_config.json")
os.makedirs(CONFIG_DIR, exist_ok=True)

try:
    multimodal_tools.configure_tts(
        tts_url=SOVITS_TTS_URL,
        allowed_dir=ALLOWED_DIR,
        output_dir=TTS_OUTPUT_DIR,
        text_split_method=SOVITS_TEXT_SPLIT_METHOD,
        voice_presets=SOVITS_VOICE_PRESETS,
    )
except Exception as _e:
    print(f"[WARN] configure_tts failed: {_e}")


def _load_user_profiles() -> Dict[str, Any]:
    if not os.path.exists(USER_PROFILES_PATH):
        return {}
    try:
        with open(USER_PROFILES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] load user profiles failed: {e}")
        return {}


def _save_user_profiles(data: Dict[str, Any]) -> None:
    tmp_path = USER_PROFILES_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, USER_PROFILES_PATH)


def _load_persona_config() -> Dict[str, Any]:
    if not os.path.exists(PERSONA_CONFIG_PATH):
        return {"content": "", "agent_title": "", "agent_name": "", "updated_at": None}
    try:
        with open(PERSONA_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"content": "", "agent_title": "", "agent_name": "", "updated_at": None}
        return {
            "content": str(data.get("content") or ""),
            "agent_title": str(data.get("agent_title") or ""),
            "agent_name": str(data.get("agent_name") or ""),
            "updated_at": data.get("updated_at"),
        }
    except Exception as e:
        print(f"[WARN] load persona config failed: {e}")
        return {"content": "", "agent_title": "", "agent_name": "", "updated_at": None}


def _save_persona_config(data: Dict[str, Any]) -> None:
    tmp_path = PERSONA_CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, PERSONA_CONFIG_PATH)


def _normalize_public_profile(user_id: str, profile: Dict[str, Any], nickname_fallback: str = "", role_fallback: str = "user") -> Dict[str, Any]:
    p = profile if isinstance(profile, dict) else {}
    role = "admin" if str(p.get("role", role_fallback) or "").strip().lower() == "admin" else "user"
    gender = str(p.get("gender") or "unknown").strip().lower() or "unknown"
    if gender not in {"female", "male", "other", "unknown"}:
        gender = "unknown"

    age = p.get("age")
    try:
        if age in (None, ""):
            age = None
        else:
            age = int(age)
    except Exception:
        age = None

    return {
        "user_id": str(user_id or p.get("user_id") or "").strip(),
        "nickname": str(p.get("nickname") or nickname_fallback or user_id).strip() or str(user_id or "").strip(),
        "role": role,
        "gender": gender,
        "age": age,
    }


def _request_user_id_fallback() -> str:
    """
    兼容 file:// 本地页面等 session 可能缺失的场景：
    - 先从 query 参数读 user_id
    - 再从 JSON body 里读 user_id/meta.user_id
    """
    try:
        uid = str(request.args.get("user_id") or request.args.get("userId") or "").strip()
        if uid:
            return uid
    except Exception:
        pass

    try:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            uid = str(payload.get("user_id") or payload.get("userId") or "").strip()
            if (not uid) and isinstance(payload.get("meta"), dict):
                uid = str(payload.get("meta", {}).get("user_id") or payload.get("meta", {}).get("userId") or "").strip()
            if uid:
                return uid
    except Exception:
        pass

    return ""


def _load_profile_role_nickname(user_id: str) -> Tuple[str, str]:
    uid = str(user_id or "").strip()
    if not uid:
        return "user", ""
    role = "user"
    nickname = uid
    try:
        profiles = _load_user_profiles()
        p = profiles.get(uid) if isinstance(profiles, dict) else None
        if isinstance(p, dict):
            role = "admin" if str(p.get("role") or "").strip().lower() == "admin" else "user"
            nickname = str(p.get("nickname") or uid).strip() or uid
    except Exception:
        pass
    return role, nickname


def _profile_user_id_for_ctx(user_id: Any, scene: str = "", group_id: str = "") -> str:
    sc = str(scene or "").strip().lower()
    gid = str(group_id or "").strip()
    uid = str(user_id or "").strip()
    if sc == "group" and gid:
        return normalize_profile_user_id(f"group_{gid}")
    if (not uid) or uid.lower() in {"anonymous", "none", "null", "system"}:
        return "local_admin"
    return normalize_profile_user_id(uid)


def append_memory_strip_for_user(
    user_id: str,
    text: str,
    importance: float = 5.0,
    created_by: str = "agent",
) -> bool:
    txt = str(text or "").strip()
    if not txt:
        return False
    try:
        pid = _profile_user_id_for_ctx(user_id)
        profiles_append_memory_strip(
            user_id=pid,
            text=txt,
            importance=float(safe_float(importance, 5.0)),
            created_by=str(created_by or "agent").strip().lower() or "agent",
            profile_base_dir=TYXT_PROFILE_DIR,
        )
        return True
    except Exception as e:
        print(f"[memory_strip append error] {e}")
        return False


def _summarize_memory_strips_for_prompt(strips_data: Dict[str, Any], max_items: int = 8, max_text_len: int = 120) -> str:
    items = strips_data.get("strips") if isinstance(strips_data, dict) else []
    if not isinstance(items, list):
        return ""

    def _k(x: Dict[str, Any]) -> Tuple[float, int]:
        imp = safe_float((x or {}).get("importance"), 5.0)
        ts = safe_int((x or {}).get("updated_at"), 0)
        return (imp, ts)

    normalized: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        imp = max(0.0, min(10.0, safe_float(it.get("importance"), 5.0)))
        normalized.append(
            {
                "text": text,
                "importance": imp,
                "updated_at": safe_int(it.get("updated_at"), 0),
            }
        )

    if not normalized:
        return ""

    normalized.sort(key=_k, reverse=True)
    lines = ["【用户显式记忆条（用户亲自指定，优先遵循）】"]
    idx = 1
    for row in normalized[:max_items]:
        t = re.sub(r"\s+", " ", row.get("text", "")).strip()
        if len(t) > max_text_len:
            t = t[:max_text_len].rstrip() + "…"
        lines.append(f"{idx}. {t}（重要度 {row.get('importance', 5.0):.1f}）")
        idx += 1
    return "\n".join(lines).strip()


def _summarize_user_profile_for_prompt(profile_data: Dict[str, Any], max_facts: int = 3, max_text_len: int = 110) -> str:
    p = profile_data if isinstance(profile_data, dict) else {}
    traits = p.get("traits") if isinstance(p.get("traits"), dict) else {}
    prefs = p.get("preferences") if isinstance(p.get("preferences"), dict) else {}
    facts = p.get("facts") if isinstance(p.get("facts"), list) else []

    parts: List[str] = []
    temperament = str(traits.get("temperament") or "").strip()
    comm_style = str(traits.get("communication_style") or "").strip()
    if temperament:
        parts.append(f"性格倾向：{temperament}")
    if comm_style:
        parts.append(f"沟通偏好：{comm_style}")

    likes = [str(x).strip() for x in (prefs.get("likes") if isinstance(prefs.get("likes"), list) else []) if str(x).strip()]
    dislikes = [str(x).strip() for x in (prefs.get("dislikes") if isinstance(prefs.get("dislikes"), list) else []) if str(x).strip()]
    if likes:
        parts.append("偏好：" + "、".join(likes[:6]))
    if dislikes:
        parts.append("不喜欢：" + "、".join(dislikes[:6]))

    norm_facts: List[Dict[str, Any]] = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        txt = str(f.get("text") or "").strip()
        if not txt:
            continue
        norm_facts.append(
            {
                "text": txt,
                "confidence": max(0.0, min(1.0, safe_float(f.get("confidence"), 0.7))),
                "last_seen_at": safe_int(f.get("last_seen_at"), 0),
            }
        )
    if norm_facts:
        norm_facts.sort(key=lambda x: (x["confidence"], x["last_seen_at"]), reverse=True)
        fact_lines: List[str] = []
        for f in norm_facts[:max_facts]:
            t = re.sub(r"\s+", " ", f.get("text", "")).strip()
            if len(t) > max_text_len:
                t = t[:max_text_len].rstrip() + "…"
            fact_lines.append(f"- {t}")
        if fact_lines:
            parts.append("长期观察到的事实：\n" + "\n".join(fact_lines))

    if not parts:
        return ""
    return "【用户画像摘要（系统推断，仅作辅助）】\n" + "\n".join(parts)


def build_user_context_segments(user_id: str) -> Dict[str, Any]:
    pid = _profile_user_id_for_ctx(user_id)
    try:
        strips_data = profiles_load_memory_strips(pid, profile_base_dir=TYXT_PROFILE_DIR)
    except Exception:
        strips_data = {"strips": []}
    try:
        profile_data = profiles_load_user_profile(pid, profile_base_dir=TYXT_PROFILE_DIR)
    except Exception:
        profile_data = {"facts": [], "traits": {}, "preferences": {}}

    strips_summary = _summarize_memory_strips_for_prompt(strips_data)
    profile_summary = _summarize_user_profile_for_prompt(profile_data)
    return {
        "profile_user_id": pid,
        "strips_summary": strips_summary,
        "profile_summary": profile_summary,
        "strips_count": len(strips_data.get("strips") or []) if isinstance(strips_data, dict) else 0,
        "facts_count": len(profile_data.get("facts") or []) if isinstance(profile_data, dict) else 0,
    }


def _text_contains_user_alias(text: str, alias: str) -> bool:
    t = str(text or "")
    a = str(alias or "").strip()
    if len(a) < 2:
        return False
    # 含中文时做直接包含，避免英文边界规则误伤中文昵称。
    if re.search(r"[\u4e00-\u9fff]", a):
        return a in t
    pat = r"(?<![A-Za-z0-9_])" + re.escape(a) + r"(?![A-Za-z0-9_])"
    return re.search(pat, t, flags=re.IGNORECASE) is not None


def _build_related_user_context_blocks(
    meta: Dict[str, Any],
    user_text: str,
    primary_user_id: str,
    max_users: int = 4,
) -> List[str]:
    """
    组装“相关对象”的画像/记忆条注入块：
    - 主对象（primary_user_id）
    - 群聊中的 target_user_id 与当前发言者 user_id
    - 文本中提及到的已知用户（按 user_profiles 的 nickname/user_id 命中）
    """
    m = meta or {}
    scene = str(m.get("scene") or "").strip().lower()
    txt = str(user_text or "")
    profiles = _load_user_profiles()

    ordered_uids: List[str] = []
    seen = set()

    def _add_uid(uid_val: Any) -> None:
        uid = str(uid_val or "").strip()
        if not uid:
            return
        norm_uid = normalize_profile_user_id(uid)
        if not norm_uid or norm_uid in seen:
            return
        seen.add(norm_uid)
        ordered_uids.append(norm_uid)

    # 1) 主对象优先
    _add_uid(primary_user_id)

    # 2) 群聊补充：目标对象 + 当前发言者
    if scene == "group":
        _add_uid(m.get("target_user_id"))
        _add_uid(m.get("user_id"))

    # 3) 文本提及对象（昵称或 user_id）
    if isinstance(profiles, dict) and txt.strip():
        for uid_key, prof in profiles.items():
            uid = str(uid_key or "").strip()
            if not uid:
                continue
            p = prof if isinstance(prof, dict) else {}
            aliases = [str(p.get("nickname") or "").strip(), uid]
            matched = False
            for al in aliases:
                if _text_contains_user_alias(txt, al):
                    matched = True
                    break
            if matched:
                _add_uid(uid)

    if max_users > 0:
        ordered_uids = ordered_uids[:max_users]

    blocks: List[str] = []
    for uid in ordered_uids:
        seg = build_user_context_segments(uid)
        strips_summary = str(seg.get("strips_summary") or "").strip()
        profile_summary = str(seg.get("profile_summary") or "").strip()
        if (not strips_summary) and (not profile_summary):
            continue

        nick = uid
        try:
            if isinstance(profiles, dict):
                p = profiles.get(uid) if isinstance(profiles.get(uid), dict) else None
                if isinstance(p, dict):
                    nick = str(p.get("nickname") or uid).strip() or uid
        except Exception:
            nick = uid

        lines = [f"【相关对象画像与记忆】{nick}（user_id={uid}）"]
        if strips_summary:
            lines.append(strips_summary)
        if profile_summary:
            lines.append(profile_summary)
        blocks.append("\n".join(lines).strip())

    return blocks


@dataclass
class MemoryDecision:
    should_write_strip: bool = False
    strip_text: Optional[str] = None
    strip_importance: float = 5.0
    should_update_profile: bool = False
    profile_note: Optional[str] = None
    profile_confidence: float = 0.8


_EXPLICIT_MEMORY_PAT = re.compile(
    r"("
    r"请记住|帮我记住|请你记住|你要记得|以后记得|以后不要忘|别忘了|记一下|记住这点|请帮我记下|请帮我记住|记住这个|记住这件事"
    r"|please\s+remember"
    r"|help\s+me\s+remember"
    r"|remember\s+(this|that|it)"
    r"|don't\s+forget|do\s+not\s+forget"
    r"|keep\s+(this|that|it)?\s*in\s+mind"
    r"|make\s+a\s+note(?:\s+of\s+this)?"
    r")",
    re.IGNORECASE,
)


def _truncate_text_for_judge(text: str, max_len: int = 700) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) > max_len:
        return s[:max_len].rstrip() + "…"
    return s


def _extract_explicit_memory_strip_text(user_text: str) -> Optional[str]:
    src = str(user_text or "").strip()
    if not src:
        return None
    if not _EXPLICIT_MEMORY_PAT.search(src):
        return None

    s = src
    s = re.sub(r"^(请|麻烦)?\s*(你)?\s*(帮我)?\s*记(住|一下|下)\s*[：:，,\s]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^(以后)?\s*(你)?\s*(要)?\s*记得\s*[：:，,\s]*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^(请)?\s*(你)?\s*(以后)?\s*(别|不要)?\s*忘(了)?\s*[：:，,\s]*", "", s, flags=re.IGNORECASE)
    s = re.sub(
        r"^(please\s+)?(can\s+you\s+)?(help\s+me\s+)?remember\s+(this|that|it)\s*[:;,\.\-\s]*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"^(please\s+)?(can\s+you\s+)?(help\s+me\s+)?remember\s*[:;,\.\-\s]*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"^(please\s+)?(do\s+not|don't)\s+forget\s*[:;,\.\-\s]*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"^(please\s+)?keep\s+(this|that|it)?\s*in\s+mind\s*[:;,\.\-\s]*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"^(please\s+)?make\s+a\s+note(?:\s+of\s+this)?\s*[:;,\.\-\s]*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip(" \t\r\n，,。.;；:：!?！？\"'")

    # 如果提炼后太短，就保留原句（去掉明显前缀后兜底）
    if len(s) < 2:
        s = src
    s = _truncate_text_for_judge(s, max_len=180)
    if len(s) < 2:
        return None
    return s


def run_memory_judge(
    user_id: str,
    last_user_message: str,
    assistant_reply: str,
    recent_context_hint: str = "",
) -> MemoryDecision:
    """
    轻量“记忆判定器” / Lightweight memory judge:
    - 先走显式规则：用户明确要求“请记住/帮我记住”或英文 remember/forget 表达时，一律写记忆条。
    - 再调用一次轻量 LLM，输出严格 JSON 决策。
    """
    decision = MemoryDecision()
    uid = str(user_id or "").strip() or "local_admin"
    user_msg = str(last_user_message or "").strip()
    ai_msg = str(assistant_reply or "").strip()
    hint = str(recent_context_hint or "").strip()

    if not user_msg:
        return decision

    explicit_strip = _extract_explicit_memory_strip_text(user_msg)
    if explicit_strip:
        decision.should_write_strip = True
        decision.strip_text = explicit_strip
        decision.strip_importance = 7.0
        decision.should_update_profile = False
        decision.profile_note = None
        decision.profile_confidence = 0.0
        return decision

    sys_prompt = (
        "You are TYXT memory judge. Decide whether current turn should be stored.\n"
        "Output JSON only, no markdown, no extra text.\n"
        "Rules:\n"
        "1) If user explicitly asks to remember (请记住/帮我记住/记得/please remember/help me remember/don't forget), write strip only.\n"
        "2) Memory strip stores explicit long-term preference/boundary/background.\n"
        "3) User profile stores inferred stable traits/communication style/long-term interests.\n"
        "4) Do NOT store one-time short tasks (e.g., 今晚吃什么/临时问路/what to eat tonight/temporary directions) into profile.\n"
        "5) Be conservative; false is better than noisy memory.\n"
        "JSON schema:\n"
        "{"
        "\"should_write_strip\":bool,"
        "\"strip_text\":string|null,"
        "\"strip_importance\":number,"
        "\"should_update_profile\":bool,"
        "\"profile_note\":string|null,"
        "\"profile_confidence\":number"
        "}"
    )
    user_prompt = (
        f"user_id: {uid}\n"
        f"last_user_message: {_truncate_text_for_judge(user_msg, 600)}\n"
        f"assistant_reply: {_truncate_text_for_judge(ai_msg, 600)}\n"
        f"recent_context_hint: {_truncate_text_for_judge(hint, 400)}"
    )

    try:
        judge_text = call_model(
            [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            max_tokens=220,
            temperature=0.1,
            top_p=0.9,
            top_k=20,
        )
    except Exception as e:
        print(f"[memory_judge call error] {e}")
        return decision

    obj = _extract_first_json_obj(judge_text or "")
    if not isinstance(obj, dict):
        return decision

    decision.should_write_strip = safe_bool(obj.get("should_write_strip"), False)
    strip_text = str(obj.get("strip_text") or "").strip()
    if strip_text:
        decision.strip_text = _truncate_text_for_judge(strip_text, 220)
    decision.strip_importance = max(0.0, min(10.0, safe_float(obj.get("strip_importance"), 5.0)))

    decision.should_update_profile = safe_bool(obj.get("should_update_profile"), False)
    profile_note = str(obj.get("profile_note") or "").strip()
    if profile_note:
        decision.profile_note = _truncate_text_for_judge(profile_note, 220)
    decision.profile_confidence = max(0.0, min(1.0, safe_float(obj.get("profile_confidence"), 0.8)))

    # 兜底：没有可写文本则关闭对应开关
    if not decision.strip_text:
        decision.should_write_strip = False
    if not decision.profile_note:
        decision.should_update_profile = False

    # 规则优先：显式记忆语义不写画像
    if _EXPLICIT_MEMORY_PAT.search(user_msg) and decision.should_write_strip:
        decision.should_update_profile = False
        decision.profile_note = None
        decision.profile_confidence = 0.0

    return decision


def _post_reply_housekeeping(
    user_input: str,
    reply: str,
    meta: Optional[Dict[str, Any]],
    user_ctx_segments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    回复后的“慢任务”：
    - 记忆判定与写入
    - 会话落盘
    - 用户画像更新
    返回 memory_meta（给调用方可选展示）。
    """
    m = dict(meta or {})
    seg = dict(user_ctx_segments or {})
    memory_meta = {
        "strip_added": False,
        "profile_updated": False,
    }

    try:
        profile_uid = str(m.get("profile_user_id") or m.get("user_id") or "").strip() or "local_admin"
        recent_hint = (
            str(seg.get("strips_summary") or "").strip()
            + "\n"
            + str(seg.get("profile_summary") or "").strip()
        ).strip()
        decision = run_memory_judge(
            user_id=profile_uid,
            last_user_message=user_input,
            assistant_reply=reply,
            recent_context_hint=recent_hint,
        )

        if decision.should_write_strip and str(decision.strip_text or "").strip():
            if ENABLE_MEMORY_STRIP_AUTO:
                ok = append_memory_strip_for_user(
                    profile_uid,
                    text=str(decision.strip_text or "").strip(),
                    importance=float(decision.strip_importance),
                    created_by="agent",
                )
                memory_meta["strip_added"] = bool(ok)
            else:
                print(
                    f"[memory_judge] strip candidate skipped by switch: user={profile_uid} "
                    f"text={decision.strip_text!r} imp={decision.strip_importance:.2f}"
                )

        if decision.should_update_profile and str(decision.profile_note or "").strip():
            if ENABLE_PROFILE_UPDATE:
                p = profiles_apply_profile_note(
                    user_id=profile_uid,
                    note=str(decision.profile_note or "").strip(),
                    confidence=float(decision.profile_confidence),
                    source="memory_judge",
                    profile_base_dir=TYXT_PROFILE_DIR,
                )
                memory_meta["profile_updated"] = bool(p)
            else:
                print(
                    f"[memory_judge] profile candidate skipped by switch: user={profile_uid} "
                    f"note={decision.profile_note!r} conf={decision.profile_confidence:.2f}"
                )
    except Exception as e:
        print(f"[memory_judge warn] {e}")

    try:
        save_chat(user_input, reply, meta=m)
    except Exception as e:
        print(f"[save_chat error] {e}")

    if ENABLE_PROFILE_UPDATE:
        try:
            turn_summary = f"用户：{user_input}\n助手：{reply}"
            profiles_maybe_update_user_profile_from_turn(
                user_id=str(m.get("profile_user_id") or m.get("user_id") or ""),
                turn_summary=turn_summary,
                profile_base_dir=TYXT_PROFILE_DIR,
            )
        except Exception as e:
            print(f"[profile update hook warn] {e}")

    return memory_meta


def _post_reply_housekeeping_bg(
    user_input: str,
    reply: str,
    meta: Optional[Dict[str, Any]],
    user_ctx_segments: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        _post_reply_housekeeping(
            user_input=user_input,
            reply=reply,
            meta=meta,
            user_ctx_segments=user_ctx_segments,
        )
    except Exception as e:
        print(f"[post_reply_housekeeping bg warn] {e}")


def hash_password(password: str) -> str:
    """生成带 salt 的 sha256 hash，返回形式 salt$hash。"""
    if not password:
        raise ValueError("password is empty")
    salt = secrets.token_hex(16)
    h = hashlib.sha256()
    h.update((salt + password).encode("utf-8"))
    return f"{salt}${h.hexdigest()}"


def verify_password(password: str, stored: str) -> bool:
    """验证用户输入密码是否与存储 hash 匹配。"""
    try:
        salt, hex_digest = str(stored or "").split("$", 1)
    except ValueError:
        return False
    h = hashlib.sha256()
    h.update((salt + str(password or "")).encode("utf-8"))
    return h.hexdigest() == hex_digest

# Chroma 向量数据库（Profile A 默认）
CHROMA_PATH = CHROMA_PERSIST_DIR
CHROMA_COLLECTION = CHROMA_COLLECTION_NAME

# 关键词 / 触发规则
KEYWORDS_FILE = os.getenv(
    "KEYWORDS_FILE",
    os.path.join(PROJECT_ROOT, "trigger_keywords.json"),
)
KEYWORDS_FILE = os.path.abspath(str(KEYWORDS_FILE))

# ⚠️ 注意：
# chat_history.txt 已不再作为主要上下文来源
# 实际使用的是：
#   - chat_private.txt
#   - groups/group_<gid>.txt
CHAT_LOG = os.path.join(ALLOWED_DIR, "chat_history.txt")

# ========== 外部工具脚本 ==========
SEARCH_ENGINE_PATH = os.getenv(
    "SEARCH_ENGINE_PATH",
    os.path.join(PROJECT_ROOT, "search_engine.py"),
)
SEARCH_ENGINE_PATH = os.path.abspath(str(SEARCH_ENGINE_PATH))

# ============================================================
# 04. Profile / Group 专用配置（集中管理：群策略 / 人格 / 上下文 / 记忆库）
# ============================================================
# Profile A: 私聊 + 主群 共用人格/上下文/记忆（保持一致）
# Profile B: 映射群 独立人格/上下文/向量库 + 后台定时增量 ingest

# ========= 04-1. 群 ID =========
PROFILE_A_GROUP_ID = str(os.getenv("PROFILE_A_GROUP_ID", "1079552241")).strip()
PROFILE_B_GROUP_ID = str(os.getenv("PROFILE_B_GROUP_ID", "1077018222")).strip()

# ========= 04-2. Profile B 专用向量库（物理隔离目录） =========
# ⚠️ 这里必须是“目录”，chroma.sqlite3 会自动生成在目录内
CHROMA_PATH_PROFILE_B = os.getenv(
    "CHROMA_PATH_PROFILE_B",
    os.path.join(CHROMA_PERSIST_DIR, f"group_{PROFILE_B_GROUP_ID}"),
)
CHROMA_PATH_PROFILE_B = os.path.abspath(str(CHROMA_PATH_PROFILE_B))

# ========= 04-4. Profile B 自动增量 ingest（实现：轮询 + 命中整点才执行） =========
PROFILE_B_INGEST_ENABLE = (str(os.getenv("PROFILE_B_INGEST_ENABLE", "1")).strip() != "0")

# 轮询频率（秒）：用于“检查是否到整点、是否需要 ingest”
# ✅ 主变量统一用 PROFILE_B_INGEST_POLL_SEC
PROFILE_B_INGEST_POLL_SEC = safe_int(os.getenv("PROFILE_B_INGEST_POLL_SEC"), 60)

# ✅ 兼容旧代码：如果别处还引用 PROFILE_B_INGEST_INTERVAL_SEC，不让它炸
PROFILE_B_INGEST_INTERVAL_SEC = PROFILE_B_INGEST_POLL_SEC

# ========= 04-5. 临时会话/文件记忆区 =========
SESSION_FILE_MEMORY = None  # None: 不写入临时会话文件

# ============================================================
# 05. 生成/模型/记忆相关的默认配置（容错读取环境变量）
# ============================================================
GEN_MAX_TOKENS      = _safe_int(os.getenv("GEN_MAX_TOKENS"), 2048)
GEN_TEMP            = _safe_float(os.getenv("GEN_TEMP"), 1.0)
GEN_TOP_P           = _safe_float(os.getenv("GEN_TOP_P"), 0.95)
GEN_TOP_K           = _safe_int(os.getenv("GEN_TOP_K"), 60)
NUM_CTX             = _safe_int(os.getenv("NUM_CTX"), 4096)
MAX_REQUEST_SECONDS = _safe_int(os.getenv("MAX_REQUEST_SECONDS"), 600)
NEWAPI_RETRY_TIMES  = max(1, _safe_int(os.getenv("NEWAPI_RETRY_TIMES"), 2))
NEWAPI_RETRY_BACKOFF_S = max(0.0, _safe_float(os.getenv("NEWAPI_RETRY_BACKOFF_S"), 0.8))
NEWAPI_STREAM_READ_TIMEOUT_S = max(10, _safe_int(os.getenv("NEWAPI_STREAM_READ_TIMEOUT_S"), 30))
DEFER_POST_REPLY_TASKS_FOR_NAPCAT = safe_bool(os.getenv("DEFER_POST_REPLY_TASKS_FOR_NAPCAT", "1"), True)
CONTEXT_TURN_LIMIT_DEFAULT = max(1, _safe_int(os.getenv("TYXT_CONTEXT_TURN_LIMIT"), 20))
WINDOW_DISPLAY_TURN_LIMIT_DEFAULT = max(1, _safe_int(os.getenv("TYXT_WINDOW_DISPLAY_TURN_LIMIT"), 60))
CHAT_STREAM_ENABLED_DEFAULT = safe_bool(os.getenv("TYXT_CHAT_STREAM_ENABLED", "1"), True)

EMBED_MODEL     = os.getenv("MEM_EMBED_MODEL", "bge-m3")
MEM_LIGHT_TOPK  = _safe_int(os.getenv("MEM_LIGHT_TOPK"), 10)
MEM_TOPK        = _safe_int(os.getenv("MEM_TOPK"), 20)
MEM_LOOKBACK_DAYS = _safe_int(os.getenv("MEM_LOOKBACK_DAYS"), 365)

# 前端图片展示最大尺寸（超出则按比例缩小）
IMAGE_PREVIEW_MAX_W = _safe_int(os.getenv("IMAGE_PREVIEW_MAX_W"), 520)
IMAGE_PREVIEW_MAX_H = _safe_int(os.getenv("IMAGE_PREVIEW_MAX_H"), 360)

# ============================================================
# 06. OCR / Tesseract 路径
# ============================================================
# OCR 逻辑已迁移到 multimodal_tools.ocr_image()

# ============================================================
# 07. Session / 参数配置文件（CONFIG_FILE / MODEL_CONFIG）
# ============================================================
# 用于保存与加载模型运行参数（启动时读取）
# 修改 config.json 后需重启服务才会生效

CONFIG_FILE = os.path.abspath(str(os.getenv("CONFIG_FILE", os.path.join(PROJECT_ROOT, "config.json"))))

def _normalize_web_search_provider(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s == "tavily":
        return "tavily"
    return "builtin"

def _normalize_web_search_mode(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in {"off", "disabled", "disable", "0", "false", "no"}:
        return "off"
    if s in {"force", "always", "strict", "2"}:
        return "force"
    if s in {"default", "auto", "on", "enabled", "enable", "1", "true", "yes"}:
        return "default"
    return "off"

def _load_config_file() -> Dict[str, Any]:
    cfg = {
        "max_tokens": GEN_MAX_TOKENS,
        "temperature": GEN_TEMP,
        "top_p": GEN_TOP_P,
        "top_k": GEN_TOP_K,
        # ctx_size 默认与 NUM_CTX 保持一致
        "ctx_size": NUM_CTX,
        # prompt 注入的回合上限（私聊/群聊临时上下文）
        "context_turn_limit": CONTEXT_TURN_LIMIT_DEFAULT,
        # UI 展示回合上限（仅前端显示裁剪，不影响 runtime txt）
        "window_display_turn_limit": WINDOW_DISPLAY_TURN_LIMIT_DEFAULT,
        # UI 发送模式：True=流式（/v1/chat/completions），False=一次性（/chat）
        "chat_stream_enabled": CHAT_STREAM_ENABLED_DEFAULT,
        # 本地 Ollama 模型名
        "ollama_model": MODEL_NAME,
        # 上网搜索配置（provider + key）
        "web_search_enabled": False,
        "web_search_mode": "off",
        "web_search_provider": "builtin",
        "web_search_api_key": "",
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                # 宽松合并：允许用户覆盖已有字段
                cfg.update(user_cfg)
    except Exception as e:
        print("[WARN] load config failed:", e)
    raw_mode = str(cfg.get("web_search_mode", "") or "").strip()
    if raw_mode:
        cfg["web_search_mode"] = _normalize_web_search_mode(raw_mode)
    else:
        cfg["web_search_mode"] = "default" if safe_bool(cfg.get("web_search_enabled"), False) else "off"
    cfg["web_search_enabled"] = bool(cfg.get("web_search_mode") != "off")
    cfg["web_search_provider"] = _normalize_web_search_provider(cfg.get("web_search_provider", "builtin"))
    cfg["web_search_api_key"] = str(cfg.get("web_search_api_key", "") or "").strip()
    return cfg


def _save_config_file(cfg: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("[WARN] save config failed:", e)


# 启动时加载一次，供后续 /chat / completions 使用
MODEL_CONFIG = _load_config_file()
try:
    # 启动时一次性环境变量覆盖（不在每次配置请求时反复覆盖）
    _env_web_provider = os.getenv("TYXT_WEB_SEARCH_PROVIDER")
    if _env_web_provider is not None and str(_env_web_provider).strip():
        MODEL_CONFIG["web_search_provider"] = _normalize_web_search_provider(_env_web_provider)
    _env_web_mode = os.getenv("TYXT_WEB_SEARCH_MODE")
    if _env_web_mode is not None and str(_env_web_mode).strip():
        MODEL_CONFIG["web_search_mode"] = _normalize_web_search_mode(_env_web_mode)
        MODEL_CONFIG["web_search_enabled"] = bool(MODEL_CONFIG["web_search_mode"] != "off")
    _env_web_key = os.getenv("TYXT_WEB_SEARCH_API_KEY")
    if _env_web_key is not None:
        MODEL_CONFIG["web_search_api_key"] = str(_env_web_key or "").strip()
except Exception as e:
    print("[WARN] apply startup web search env override failed:", e)


def _get_context_turn_limit() -> int:
    """
    模型 prompt 注入的“临时上下文回合上限”。
    """
    try:
        raw = MODEL_CONFIG.get("context_turn_limit", CONTEXT_TURN_LIMIT_DEFAULT)
        v = safe_int(raw, CONTEXT_TURN_LIMIT_DEFAULT)
    except Exception:
        v = CONTEXT_TURN_LIMIT_DEFAULT
    return max(1, min(500, int(v)))

# ============================================================
# 08. Flask App 初始化 / CORS / 全局锁
# ============================================================
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-me-please")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")


# ============================================================
# CORS：允许 file:// 或任意前端域访问本地后端（UI 直开 HTML 也能用）
# ============================================================
@app.after_request
def _add_cors_headers(resp):
    origin = request.headers.get("Origin", "").strip()
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    else:
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

# ✅ 关键：让 JSON 不把中文转成 \uXXXX
app.config["JSON_AS_ASCII"] = False
app.config["JSON_SORT_KEYS"] = False
try:
    # Flask 2.2+ 写法
    app.json.ensure_ascii = False
except Exception:
    pass

CORS(app, resources={r"/*": {"origins": "*"}})

# 模型调用互斥锁（防并发把本地模型/上游压爆）
_model_lock = threading.Semaphore(1)
_last_call_meta = threading.local()
MCP_BRIDGE: Optional[mcp_bridge.MCPBridge] = None
MCP_SERVER_CONFIGS: Dict[str, mcp_bridge.MCPServerConfig] = {}
MCP_BRIDGE_ENABLED = bool(TYXT_MCP_ENABLED)
MCP_TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}
MCP_SERVER_RUNTIME_STATUS: Dict[str, Dict[str, Any]] = {}
MCP_SKILL_DEBUG_ENABLED = safe_bool(os.getenv("TYXT_MCP_SKILL_DEBUG", "1"), True)
MCP_SKILL_DEBUG_MAX = max(20, min(2000, safe_int(os.getenv("TYXT_MCP_SKILL_DEBUG_MAX"), 200)))
_MCP_SKILL_DEBUG_LOCK = threading.RLock()
_MCP_SKILL_DEBUG_LOGS: Deque[Dict[str, Any]] = deque(maxlen=MCP_SKILL_DEBUG_MAX)


def _append_mcp_skill_debug(event: str, **fields: Any) -> None:
    if not MCP_SKILL_DEBUG_ENABLED:
        return
    row: Dict[str, Any] = {
        "ts": round(float(time.time()), 3),
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": str(event or "").strip() or "event",
    }
    for k, v in (fields or {}).items():
        key = str(k or "").strip()
        if not key or (v is None):
            continue
        if isinstance(v, (str, int, float, bool, list, dict)):
            row[key] = v
        else:
            row[key] = str(v)
    with _MCP_SKILL_DEBUG_LOCK:
        _MCP_SKILL_DEBUG_LOGS.append(row)


def _get_mcp_skill_debug_logs(limit: int = 80) -> List[Dict[str, Any]]:
    n = max(1, min(500, safe_int(limit, 80)))
    with _MCP_SKILL_DEBUG_LOCK:
        rows = list(_MCP_SKILL_DEBUG_LOGS)
    return rows[-n:]


def _set_last_call_meta(meta: Dict[str, Any]):
    try:
        _last_call_meta.value = dict(meta or {})
    except Exception:
        pass


def _get_last_call_meta() -> Dict[str, Any]:
    try:
        v = getattr(_last_call_meta, "value", None)
        if isinstance(v, dict):
            return dict(v)
    except Exception:
        pass
    return {}

# ============================================================
# 09. System Prompt 人格加载（已切换为仅 UI 人格）
# ============================================================
def get_profile(meta: dict) -> str:
    # 当前策略：统一人格，不再按群区分 Profile。
    return "A"


def get_system_prompt_base(meta: dict) -> str:
    # prompts.txt / group prompts 注入逻辑已废弃。
    # 当前人格来源统一为 configs/persona_config.json（前端“Agent 人格设置”）。
    return ""


def build_system_prompt_lines(meta: dict) -> List[str]:
    
    #生成 system prompt 的基础行列表（只负责人格文本，不做上下文注入）
    # 在 /chat 或 /v1/chat/completions 里调用，把返回的 lines 作为 sys_lines 起点。
    
    lines: List[str] = []
    base = get_system_prompt_base(meta)
    if base.strip():
        lines.append(base.strip())
    return lines

# ============================================================
# 10. 记忆触发：关键词与触发判定（trigger_memory_check）
# ============================================================

# 缓存：避免每次触发都读文件
_KEYWORDS_CACHE: Optional[List[str]] = None
_KEYWORDS_MTIME: float = 0.0

# 预编译正则：避免每次 search 都编译
_MEMORY_TRIGGER_PATTERNS = [
    re.compile(r"(你)?还记得", re.IGNORECASE),
    re.compile(r"记得(吗|不|没)", re.IGNORECASE),
    re.compile(r"(回忆|回想)(一下)?", re.IGNORECASE),
    re.compile(r"(上次|那次|那天).*?(说|聊|做|见|谈)", re.IGNORECASE),
    re.compile(r"(之前|过去|曾经).*(说|聊|做|见|谈)", re.IGNORECASE),
    re.compile(r"\b(do\s+you\s+)?remember\b", re.IGNORECASE),
    re.compile(r"\brecall\b", re.IGNORECASE),
    re.compile(r"\b(last\s+time|that\s+time|the\s+other\s+day)\b.*\b(said|talked|did|met|discussed)\b", re.IGNORECASE),
    re.compile(r"\b(before|previously|in\s+the\s+past)\b.*\b(said|talked|did|met|discussed)\b", re.IGNORECASE),
]

_DEFAULT_KEYWORDS = [
    "你还记得", "还记得", "记得", "回忆", "回想",
    "之前", "上次", "那次", "那天", "过去", "曾经", "我们聊过",
    "do you remember", "remember", "recall", "last time", "that time",
    "in the past", "previously", "we talked about"
]


def load_keywords(force_reload: bool = False) -> List[str]:
    
    #加载记忆触发关键词，支持外部 JSON 文件扩展
    #- 默认会做缓存：文件无变化就不重复读取
    #- force_reload=True 可强制重载
    
    global _KEYWORDS_CACHE, _KEYWORDS_MTIME

    # 没有外部文件：直接返回默认
    if not KEYWORDS_FILE or (not os.path.exists(KEYWORDS_FILE)):
        _KEYWORDS_CACHE = list(_DEFAULT_KEYWORDS)
        return _KEYWORDS_CACHE

    try:
        mtime = os.path.getmtime(KEYWORDS_FILE)
        if (not force_reload) and _KEYWORDS_CACHE is not None and mtime == _KEYWORDS_MTIME:
            return _KEYWORDS_CACHE

        with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
            w = json.load(f)

        if isinstance(w, list) and w:
            kws = []
            for x in w:
                if x is None:
                    continue
                s = str(x).strip()
                if not s or s.lower() == "none":
                    continue
                kws.append(s)

            # 空列表就回退默认
            _KEYWORDS_CACHE = kws if kws else list(_DEFAULT_KEYWORDS)
        else:
            _KEYWORDS_CACHE = list(_DEFAULT_KEYWORDS)

        _KEYWORDS_MTIME = mtime
        return _KEYWORDS_CACHE

    except Exception as e:
        print(f"[Keywords Load Error] {e}")
        _KEYWORDS_CACHE = list(_DEFAULT_KEYWORDS)
        return _KEYWORDS_CACHE


def trigger_memory_check(text: str) -> bool:
    
    #检查输入是否触发向量记忆查询
    
    text_raw = (text or "").strip()
    if not text_raw:
        return False
    text_lower = text_raw.lower()

    # 关键词直接匹配
    kws = load_keywords()
    for k in kws:
        ks = str(k or "").strip()
        if not ks:
            continue
        if ks.lower() in text_lower:
            return True

    # 正则模糊匹配
    return any(p.search(text_raw) for p in _MEMORY_TRIGGER_PATTERNS)

# ============================================================
# 11. 向量库 Chroma：client / collection / where_recent / add_memories / vector_search
# ============================================================
# —— 动态超时估算（日志提示用）——
_retrieval_times: Deque[float] = deque(maxlen=20)


def _calc_timeout():
    if not _retrieval_times:
        return 12
    avg = sum(_retrieval_times) / len(_retrieval_times)
    return max(6, min(300, int(avg * 2 + 0.5)))


def _scene_for_memory(meta: Optional[dict]) -> str:
    m = meta or {}
    scene = str(m.get("scene") or "").strip().lower()
    gid = str(m.get("group_id") or "").strip()
    if scene == "group" and gid:
        return f"qq_group:{gid}"
    if scene in {"private", "local_ui", "ui", "chat", ""}:
        return "local_ui"
    return scene


def _memory_filters_from_meta(meta: Optional[dict], lookback_days: Optional[int] = None) -> Dict[str, Any]:
    m = meta or {}
    filters: Dict[str, Any] = {}
    try:
        channel_type, owner_id = resolve_channel_owner(m)
        filters["channel_type"] = str(channel_type or "").strip() or "local"
        filters["owner_id"] = str(owner_id or "").strip() or "local_admin"
    except Exception:
        channel_type, owner_id = ("local", "local_admin")
    uid = str(m.get("user_id") or "").strip()
    if uid and (str(channel_type) != "group"):
        filters["user_id"] = uid
    # 兼容历史/导入数据：同一 private tenant 里可能同时存在 scene=local_ui 与 scene=qq_private:<uid>。
    # 这里不再做“单一 scene 强过滤”，避免误杀本该命中的历史记录。
    if str(channel_type) == "private":
        owner = str(owner_id or "").strip()
        scenes = []
        for s in [
            str(m.get("scene") or "").strip(),
            _scene_for_memory(m),
            f"qq_private:{owner}" if owner else "",
            "local_ui",
        ]:
            if s and s not in scenes:
                scenes.append(s)
        if scenes:
            filters["scene"] = {"$in": scenes}
    elif str(channel_type) == "group":
        owner = str(owner_id or "").strip()
        scenes = []
        for s in [
            str(m.get("scene") or "").strip(),
            _scene_for_memory(m),
            f"qq_group:{owner}" if owner else "",
            "group",
        ]:
            if s and s not in scenes:
                scenes.append(s)
        if scenes:
            filters["scene"] = {"$in": scenes}
    filters["deleted"] = {"$ne": True}
    days = safe_int(lookback_days, 0)
    if days > 0:
        filters["lookback_days"] = days
    return filters


_MEMORY_QUERY_CLEAN_PATTERNS = [
    re.compile(r"^(你|你能|你还|你是否|请你|帮我)?(还)?(记得|记不记得|回忆一下|想一下|想想|再想想)\s*", re.IGNORECASE),
    re.compile(r"^(关于|有关|针对)\s*", re.IGNORECASE),
    re.compile(r"^(can\s+you\s+)?(do\s+you\s+)?(still\s+)?remember\s*", re.IGNORECASE),
    re.compile(r"^(please\s+)?(help\s+me\s+)?remember\s*", re.IGNORECASE),
    re.compile(r"^(can\s+you\s+)?recall\s*", re.IGNORECASE),
    re.compile(r"^(about|regarding|related\s+to)\s*", re.IGNORECASE),
]
_MEMORY_QUERY_TAIL_PATTERN = re.compile(
    r"(这件事|这件事情|这个事|这个事情|的事|事情|内容|细节|吗|嘛|么|呢|呀|啊|呗|吧|"
    r"this\s+(thing|topic)|that\s+(thing|topic)|the\s+(thing|topic)|"
    r"details?|content|context|"
    r"right|okay|ok|please|？|\?|！|!)\s*$",
    re.IGNORECASE,
)
_MEMORY_KEYWORD_STOPWORDS = {
    "你", "我", "他", "她", "它", "我们", "你们", "他们", "她们", "它们",
    "记得", "还记得", "回忆", "回想", "想想", "一下", "关于", "有关", "针对",
    "事情", "内容", "细节", "那次", "上次", "之前", "过去", "现在", "以后",
    "这个", "那个", "这里", "那里", "什么", "怎么", "为何", "为什么",
    "吗", "呢", "呀", "啊", "嘛", "么", "吧", "呗",
    "i", "me", "my", "you", "your", "he", "she", "it", "we", "they", "them", "our", "their",
    "remember", "recall", "memory", "about", "regarding", "related", "related to",
    "thing", "things", "topic", "details", "detail", "content", "context",
    "last", "time", "before", "previously", "past", "now", "later",
    "what", "how", "why", "when", "where",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "please",
    "ok", "okay", "right",
}


def _memory_query_candidates(user_input: str) -> List[str]:
    """
    回忆类问句提取检索候选词，避免整句问法导致向量命中偏弱。
    例如：“你还记得关于小龙虾的事情吗？” -> ["你还记得关于小龙虾的事情吗", "小龙虾"]
    """
    raw = str(user_input or "").strip()
    if not raw:
        return []

    out: List[str] = []
    seen = set()

    def _add(q: str) -> None:
        qq = re.sub(r"\s+", " ", str(q or "")).strip()
        if len(qq) < 2:
            return
        if qq in seen:
            return
        seen.add(qq)
        out.append(qq)

    def _strip_tail_terms(s: str) -> str:
        prev = ""
        cur = str(s or "").strip()
        while cur and cur != prev:
            prev = cur
            cur = _MEMORY_QUERY_TAIL_PATTERN.sub("", cur).strip()
        cur = re.sub(r"(的?(事情|事|内容|细节))$", "", cur).strip()
        cur = re.sub(
            r"(this\s+(thing|topic)|that\s+(thing|topic)|the\s+(thing|topic)|details?|content|context)$",
            "",
            cur,
            flags=re.IGNORECASE,
        ).strip()
        cur = re.sub(r"的$", "", cur).strip()
        return cur

    cleaned = raw
    for pat in _MEMORY_QUERY_CLEAN_PATTERNS:
        cleaned = pat.sub("", cleaned).strip()
    cleaned = _strip_tail_terms(cleaned)
    cleaned = re.sub(r"^(关于|有关|针对)\s*", "", cleaned).strip()
    cleaned = re.sub(r"^(about|regarding|related\s+to)\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"^和\s*", "", cleaned).strip()
    cleaned = re.sub(r"^and\s+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    # 优先提取“关于 XXX 的事情吗”里的 XXX 作为关键词
    m_about = re.search(
        r"关于\s*(.+?)(?:的?(?:事情|事|内容|细节))?(?:吗|嘛|么|呢|呀|啊|？|\?)?\s*$",
        raw,
        re.IGNORECASE,
    )
    if m_about:
        focus = str(m_about.group(1) or "").strip()
        focus = _strip_tail_terms(focus)
        focus = re.sub(r"^(关于|有关|针对)\s*", "", focus).strip()
        _add(focus)
    else:
        m_about_en = re.search(
            r"(?:about|regarding|related\s+to)\s+(.+?)(?:\s+(?:details?|content|context|thing|topic))?(?:\s*(?:\?|please|right|ok|okay))?\s*$",
            raw,
            re.IGNORECASE,
        )
        if m_about_en:
            focus = str(m_about_en.group(1) or "").strip()
            focus = _strip_tail_terms(focus)
            focus = re.sub(r"^(about|regarding|related\s+to)\s*", "", focus, flags=re.IGNORECASE).strip()
            _add(focus)

    # 其次保留清洗后的核心短语
    _add(cleaned)

    # 再拆分出更短关键词（过滤常见虚词）
    stop_words = set(_MEMORY_KEYWORD_STOPWORDS)
    tokens = re.split(r"[，。！？!?；;：:\s、/\\|（）()【】\[\]\"'“”‘’·…\-]+", cleaned)
    tokens = [t for t in tokens if t and t not in stop_words and t.lower() not in stop_words and len(t) >= 2]
    tokens = sorted(tokens, key=lambda x: len(x), reverse=True)
    for t in tokens[:5]:
        _add(t)

    # 兜底：关键词提取失败时再回退整句
    if not out:
        _add(raw)

    return out[:5]


def _memory_focus_keywords(user_input: str) -> List[str]:
    """
    从用户问句提取“重点关键词”，过滤无意义词，优先返回信息量更高的词。
    """
    cands = _memory_query_candidates(user_input)
    scored: List[Tuple[float, str]] = []
    seen = set()

    def _push(tok: str) -> None:
        t = str(tok or "").strip()
        if len(t) < 2:
            return
        tl = t.lower()
        if tl in seen:
            return
        if t in _MEMORY_KEYWORD_STOPWORDS or tl in _MEMORY_KEYWORD_STOPWORDS:
            return
        # 排除“几乎全是虚词/回忆词”的短词
        if re.fullmatch(r"(记得|回忆|事情|内容|细节|关于|remember|recall|details?|content|about)+", tl, re.IGNORECASE):
            return
        seen.add(tl)
        # 简单打分：长度越长信息量越高；含数字/英文或中文实体词再加分
        score = float(min(len(t), 14))
        if re.search(r"[A-Za-z0-9]", t):
            score += 1.5
        if re.search(r"[\u4e00-\u9fff]{2,}", t):
            score += 0.8
        scored.append((score, t))

    for c in cands:
        _push(c)
        if "的" in c:
            for seg in c.split("的"):
                _push(seg)
        parts = re.split(r"[，。！？!?；;：:\s、/\\|（）()【】\[\]\"'“”‘’·…\-]+", c)
        for p in parts:
            p = str(p or "").strip()
            if not p:
                continue
            _push(p)

    scored.sort(key=lambda x: (-x[0], -len(x[1])))
    return [t for _s, t in scored[:3]]


def _payload_filter_by_keywords(res: Any, keywords: List[str]) -> Any:
    """
    对向量返回结果做关键词硬过滤，减少无关凑数内容注入到 prompt。
    """
    if not isinstance(res, dict):
        return res
    keys = [str(k or "").strip().lower() for k in (keywords or []) if len(str(k or "").strip()) >= 2]
    if not keys:
        return res

    ids = list(((res.get("ids") or [[]])[0] or []))
    docs = list(((res.get("documents") or [[]])[0] or []))
    metas = list(((res.get("metadatas") or [[]])[0] or []))
    dists_outer = (res.get("distances") or res.get("scores") or [[]])
    dists = list((dists_outer[0] if isinstance(dists_outer, list) and dists_outer else []) or [])

    keep_idx: List[int] = []
    for i, d in enumerate(docs):
        txt = str(d or "").lower()
        if any(k in txt for k in keys):
            keep_idx.append(i)

    if not keep_idx:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]], "scores": [[]]}

    out_ids = [ids[i] for i in keep_idx if i < len(ids)]
    out_docs = [docs[i] for i in keep_idx if i < len(docs)]
    out_metas = [metas[i] for i in keep_idx if i < len(metas)]
    out_dists = [dists[i] for i in keep_idx if i < len(dists)]
    return {
        "ids": [out_ids],
        "documents": [out_docs],
        "metadatas": [out_metas],
        "distances": [out_dists],
        "scores": [out_dists],
    }


def _records_to_query_payload(records: List[Any]) -> Dict[str, Any]:
    ids = [str(getattr(r, "id", "")) for r in records]
    docs = [str(getattr(r, "text", "")) for r in records]
    metas = [dict(getattr(r, "metadata", {}) or {}) for r in records]
    scores = [getattr(r, "score", None) for r in records]
    return {
        "ids": [ids],
        "documents": [docs],
        "metadatas": [metas],
        "distances": [scores],
        "scores": [scores],
    }


_ONLINE_POSITIVE_PAT = re.compile(
    r"(开心|高兴|太好了|不错|喜欢|满意|感动|幸福|"
    r"happy|glad|great|awesome|love|like|satisfied|moved|excited|delighted)",
    re.IGNORECASE,
)
_ONLINE_NEGATIVE_PAT = re.compile(
    r"(难过|不开心|烦|生气|郁闷|伤心|痛苦|焦虑|沮丧|"
    r"sad|upset|angry|annoyed|depressed|frustrated|painful|anxious|worried)",
    re.IGNORECASE,
)
_ONLINE_PLAN_PAT = re.compile(
    r"(打算|计划|希望|准备|明年|下周|我要|想要|将要|"
    r"\b(plan|planning|prepare|preparing|hope|going to|will|"
    r"next\s+(week|month|year)|tomorrow|later|i\s+want|i'd\s+like)\b)",
    re.IGNORECASE,
)
_ONLINE_TOPIC_WORDS = [
    "NapCat", "memory", "记忆", "RAG", "vector", "向量库", "prompt", "提示词",
    "group chat", "群聊", "private chat", "私聊", "login", "登录",
    "persona", "人格", "TTS", "OCR",
]


def _normalize_for_fingerprint(text: str) -> str:
    t = str(text or "")
    t = t.replace("\r", "\n")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _online_initial_importance(text: str) -> float:
    t = str(text or "").strip()
    if _ONLINE_PLAN_PAT.search(t):
        return 7.0
    if len(t) > 80:
        return 5.0
    return 3.0


def _online_detect_emotion(text: str) -> str:
    t = str(text or "")
    if _ONLINE_POSITIVE_PAT.search(t):
        return "positive"
    if _ONLINE_NEGATIVE_PAT.search(t):
        return "negative"
    return "neutral"


def _online_extract_topic_tags(text: str, max_tags: int = 5) -> List[str]:
    t = str(text or "")
    t_low = t.lower()
    out: List[str] = []
    seen = set()
    for kw in _ONLINE_TOPIC_WORDS:
        kw_s = str(kw)
        if kw_s.lower() in t_low and kw_s not in seen:
            seen.add(kw_s)
            out.append(kw_s)
            if len(out) >= max_tags:
                break
    return out


def _online_memory_log_path(channel_type: str, owner_id: str) -> str:
    ch = _safe_id_token(channel_type, "local")
    owner = _safe_id_token(owner_id, "local_admin")
    d = os.path.join(ONLINE_MEMORY_DIR, ch)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{owner}.jsonl")


def _append_jsonl_line(path: str, row: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _persist_online_memory(user_text: str, assistant_text: str, meta: Optional[dict]) -> None:
    mm = dict(meta or {})
    try:
        channel_type, owner_id = resolve_channel_owner(mm)
    except Exception:
        channel_type, owner_id = ("local", "local_admin")
    now_ts = int(time.time())
    scene = _scene_for_memory(mm)
    uid = str(mm.get("user_id") or "").strip() or None

    user_part = str(user_text or "").strip()
    ai_part = str(assistant_text or "").strip()
    merged_text = f"用户说：{user_part}\nAI 回复：{ai_part}".strip()
    if len(merged_text) < 2:
        return

    norm_text = _normalize_for_fingerprint(merged_text)
    fp_src = f"{owner_id}|{norm_text}"
    fingerprint = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:16]
    emotion = _online_detect_emotion(merged_text)
    tags = _online_extract_topic_tags(merged_text, max_tags=5)
    importance = float(_online_initial_importance(merged_text))
    rec_id = f"conv_{time.strftime('%Y%m%d_%H%M%S', time.localtime(now_ts))}_{uuid.uuid4().hex[:8]}"

    metadata = {
        "importance": importance,
        "emotion": emotion,
        "topic_tags": ",".join(tags),
        "fingerprint": fingerprint,
        "source": "online_conv",
        "layer": "conv",
        "user_id": uid,
        "scene": scene,
        "channel_type": channel_type,
        "owner_id": owner_id,
        "timestamp": now_ts,
        "deleted": False,
    }

    row = {
        "id": rec_id,
        "owner_id": owner_id,
        "channel_type": channel_type,
        "scene": scene,
        "timestamp": now_ts,
        "text": merged_text,
        "metadata": {
            **metadata,
            "topic_tags": tags,
        },
    }
    try:
        _append_jsonl_line(_online_memory_log_path(channel_type, owner_id), row)
    except Exception as e:
        print(f"[online_mem] append jsonl failed: {e}")

    try:
        duplicated = CHAT_MEM_STORE.has_fingerprint(channel_type, owner_id, fingerprint)
    except Exception:
        duplicated = False

    if not duplicated:
        payload_meta = dict(metadata)
        payload_meta["id"] = rec_id
        try:
            CHAT_MEM_STORE.add([merged_text], [payload_meta])
        except Exception as e:
            print(f"[online_mem] add vector failed: {e}")

    used_ids = [str(x).strip() for x in (mm.get("_used_memory_ids") or []) if str(x).strip()]
    if used_ids:
        try:
            bumped = bump_chat_memory_importance(used_ids, meta=mm, delta=IMPORTANCE_HIT_BOOST)
            if bumped:
                print(f"[online_mem] bump_importance ok: {bumped}")
        except Exception as e:
            print(f"[online_mem] bump_importance failed: {e}")


def add_memories(
    texts: list[str],
    source: str = "",
    importance: Optional[float] = None,
    meta: Optional[dict] = None,
):
    """
    批量存储多条记忆到统一 MemoryStore。
    """
    if not texts:
        return "⚠️ 没有需要存储的内容"

    now_ts = int(time.time())
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []
    base_meta = dict(meta or {})
    for t in texts:
        text = str(t or "").strip()
        if not text:
            continue
        mm = dict(base_meta)
        mm["timestamp"] = now_ts
        mm["source"] = str(source or mm.get("source") or "")
        # 重要度规则：
        # 1) 记录本身带了 importance -> 用记录值
        # 2) 调用方显式传了 importance -> 用调用值
        # 3) 两者都没有 -> 默认 5.0
        if "importance" in mm:
            mm["importance"] = safe_float(mm.get("importance"), 5.0)
        elif importance is not None:
            mm["importance"] = safe_float(importance, 5.0)
        else:
            mm["importance"] = 5.0
        mm["scene"] = _scene_for_memory(mm)
        mm["layer"] = str(mm.get("layer") or "default")
        mm["user_id"] = str(mm.get("user_id") or "anonymous")
        mm["deleted"] = bool(mm.get("deleted", False))
        try:
            ch, owner = resolve_channel_owner(mm)
            mm["channel_type"] = ch
            mm["owner_id"] = owner
        except Exception:
            pass
        gid = str(mm.get("group_id") or "").strip()
        if gid:
            mm["group_id"] = gid
        docs.append(text)
        metas.append(mm)

    if not docs:
        return "⚠️ 没有有效文本可写入"

    try:
        ids = MEM_STORE.add(texts=docs, metadatas=metas)
        return f"✅ 已存储 {len(ids)} 条记忆"
    except Exception as e:
        return f"❌ Storage failed: {e}"


def vector_search(query: str, top_k=MEM_TOPK, timeout_s: Optional[int] = None, meta: Optional[dict] = None):
    """
    统一检索入口（向量召回 + 二次筛选）。
    """
    if timeout_s is None:
        timeout_s = _calc_timeout()

    try:
        safe_top_k = max(1, safe_int(top_k, MEM_TOPK))
        t0 = time.time()
        # 聊天主链路统一走 memory_retriever_v2（二次排序 + 关键词增强 + deleted 过滤）
        records = retrieve_chat_memory_records(
            query=str(query or ""),
            meta=meta or {},
            top_k=safe_top_k,
            lookback_days=MEM_LOOKBACK_DAYS,
            max_chars=1200,
        )
        # 时间窗兜底：若最近窗口无命中，则自动回退到“全历史”再检索一次。
        if (not records) and safe_int(MEM_LOOKBACK_DAYS, 0) > 0:
            records = retrieve_chat_memory_records(
                query=str(query or ""),
                meta=meta or {},
                top_k=safe_top_k,
                lookback_days=None,
                max_chars=1200,
            )
            if records:
                print(f"[VectorSearch] fallback_no_lookback hits={len(records)}")
        if isinstance(meta, dict):
            meta["_used_memory_ids"] = [str(getattr(r, "id", "")).strip() for r in records if str(getattr(r, "id", "")).strip()]
            try:
                _ch, _owner = resolve_channel_owner(meta)
            except Exception:
                _ch, _owner = ("", "")
            meta["_memory_channel_type"] = str(_ch or "")
            meta["_memory_owner_id"] = str(_owner or "")
        elapsed = time.time() - t0
        _retrieval_times.append(elapsed)
        owner_dbg = ""
        if isinstance(meta, dict):
            owner_dbg = f" tenant={meta.get('_memory_channel_type','')}/{meta.get('_memory_owner_id','')}"
        print(f"[VectorSearch] query={str(query or '').strip()[:60]!r} top_k={safe_top_k} hits={len(records)} time={elapsed:.2f}s{owner_dbg}")
        return _records_to_query_payload(records)
    except Exception as e:
        print(f"[VectorSearch Error] {e}")
        return {"error": f"Memory store unavailable or timeout ({timeout_s}s): {e}"}


def retrieve_memory(query: str, meta: Optional[dict] = None, top_k: Optional[int] = None) -> str:
    """兼容旧调用：返回格式化后的记忆文本。"""
    safe_top_k = max(1, safe_int(top_k, MEM_TOPK))
    mm = meta or {}
    result = retrieve_chat_memories(
        query=str(query or ""),
        meta=mm,
        top_k=safe_top_k,
        lookback_days=MEM_LOOKBACK_DAYS,
        max_chars=1200,
    )
    texts = list(result.get("texts") or [])
    if isinstance(mm, dict):
        mm["_used_memory_ids"] = [str(x).strip() for x in (result.get("ids") or []) if str(x).strip()]
        mm["_memory_channel_type"] = str(result.get("channel_type") or "")
        mm["_memory_owner_id"] = str(result.get("owner_id") or "")
    lines: List[str] = []
    for idx, txt in enumerate(texts, 1):
        txt = str(txt or "").strip()
        if not txt:
            continue
        lines.append(f"{idx}. {txt}")
    return "\n".join(lines).strip()



# ============================================================
# 12. Embedding 提供方
#   - EMBED_PROVIDER=local_bge / ollama
#   - LocalBGEM3EmbeddingFunction / OllamaEmbeddingFunction
# ============================================================

EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local_bge")  # local_bge / ollama

# 关键：本地 embedding 模型只初始化一次（避免每次检索都重新加载，导致极慢）
_BGE_MODEL = None
_BGE_LOCK = threading.Lock()

# 默认维度：建议与 bge-m3 的 dense_vecs 对齐（常见 1024）
EMBED_DIM_DEFAULT = _safe_int(os.getenv("EMBED_DIM_DEFAULT"), 1024)


def _normalize_ollama_base(base: str) -> str:
    
    #把 OLLAMA_BASE_URL 规范化为 http://host:port（去掉 /v1、去掉尾斜杠）
    #允许输入：http://127.0.0.1:11434 或 http://127.0.0.1:11434/v1
    
    b = str(base or "").strip().rstrip("/")
    if b.endswith("/v1"):
        b = b[:-3]
    # 也兼容 .../v1/xxx 这种误填：只要包含 /v1 就截断到 /v1 之前
    if "/v1" in b:
        b = b.split("/v1")[0]
    return b.rstrip("/")


class OllamaEmbeddingFunction(EmbeddingFunction):
    def __init__(self, base=None, model=EMBED_MODEL, timeout=30):
        self.base = _normalize_ollama_base(base or OLLAMA_BASE_URL)
        self.url = f"{self.base}/api/embeddings"
        self.model = model
        self.timeout = timeout
        self.dim = None  # 首次成功后记录维度

    def _post(self, payload):
        r = requests.post(self.url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def __call__(self, input: Documents):
        if not input:
            return []

        # 1) 批量 input
        try:
            data = self._post({"model": self.model, "input": list(input)})
            if isinstance(data, dict):
                # 有些实现返回 {"embedding":[...]}（单条）或 {"data":[{"embedding":...},...]}
                if "data" in data and isinstance(data["data"], list):
                    embs = [item.get("embedding", []) for item in data["data"]]
                    if embs and isinstance(embs[0], list):
                        self.dim = len(embs[0])
                    return embs

                if "embedding" in data and isinstance(data["embedding"], list):
                    v = data["embedding"]
                    self.dim = self.dim or len(v)
                    return [v]

        except Exception as e:
            print(f"[Embeddings] batch failed, fallback single: {e}")

        # 2) 单条逐个请求 fallback（仍然用 input 字段，避免 prompt 混用）
        out = []
        for text in input:
            try:
                jd = self._post({"model": self.model, "input": str(text)})
                if isinstance(jd, dict) and "embedding" in jd and isinstance(jd["embedding"], list):
                    v = jd["embedding"]
                    self.dim = self.dim or len(v)
                    out.append(v)
                else:
                    dim = self.dim or EMBED_DIM_DEFAULT
                    out.append([0.0] * dim)
            except Exception as e:
                print(f"[Embeddings] single failed: {e}")
                dim = self.dim or EMBED_DIM_DEFAULT
                out.append([0.0] * dim)
        return out


# ====== 强制 HuggingFace 使用官方源（禁用镜像干扰） ======
os.environ["HF_ENDPOINT"] = "https://huggingface.co"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
for k in ["HUGGINGFACE_HUB_BASE_URL", "HF_MIRROR", "HF_MIRROR_ENDPOINT"]:
    os.environ.pop(k, None)

# （可选）固定缓存目录，避免到处找
# os.environ["HF_HOME"] = os.path.join(os.getcwd(), ".hf_cache")
# os.environ["HUGGINGFACE_HUB_CACHE"] = os.path.join(os.environ["HF_HOME"], "hub")


def _get_local_bge_model():
    
    #获取（并缓存）本地 BGEM3FlagModel。
    #若镜像/缓存异常导致 403 等，自动切回 huggingface.co 再试一次。
    
    global _BGE_MODEL
    if _BGE_MODEL is not None:
        return _BGE_MODEL

    with _BGE_LOCK:
        if _BGE_MODEL is not None:
            return _BGE_MODEL

        try:
            _BGE_MODEL = get_embedding_model()
            return _BGE_MODEL
        except Exception as e1:
            msg = str(e1)
            print(f"[Embeddings] LocalBGEM3 first load failed: {e1}")

            if ("hf-mirror" in msg) or ("resolve-cache" in msg) or (".DS_Store" in msg) or ("403" in msg):
                try:
                    os.environ["HF_ENDPOINT"] = "https://huggingface.co"
                    os.environ.pop("HUGGINGFACE_HUB_BASE_URL", None)
                    _BGE_MODEL = get_embedding_model()
                    print("[Embeddings] Switched HF_ENDPOINT to https://huggingface.co and loaded OK.")
                    return _BGE_MODEL
                except Exception as e2:
                    print(f"[Embeddings] LocalBGEM3 second load failed: {e2}")
                    raise e2

            raise e1


class LocalBGEM3EmbeddingFunction(EmbeddingFunction):
    
    #用本地 BGEM3FlagModel 生成向量：
    #- 模型仅首次加载一次（性能关键）
    #- 失败会返回零向量兜底（保证系统不断）
    
    def __init__(self):
        self.dim = None

    def __call__(self, input: Documents) -> Embeddings:
        if not input:
            return []

        try:
            model = _get_local_bge_model()

            bs = int(os.getenv("BGE_BATCH_SIZE", "24"))
            mx = int(os.getenv("BGE_MAX_LENGTH", "512"))

            result = model.encode(list(input), batch_size=bs, max_length=mx)
            vecs = result.get("dense_vecs")
            if vecs is None:
                dim = self.dim or EMBED_DIM_DEFAULT
                return [[0.0] * dim for _ in input]

            if self.dim is None:
                try:
                    self.dim = int(vecs.shape[1])
                except Exception:
                    pass

            return vecs.tolist()

        except Exception as e:
            print(f"[Embeddings] LocalBGEM3 failed: {e}")
            dim = self.dim or EMBED_DIM_DEFAULT
            return [[0.0] * dim for _ in input]

# ============================================================
# 13. 记忆结果格式化：format_memories / _format_memories
# ============================================================

def _format_memories(res, max_chars_per: int = 800) -> Tuple[str, bool]:
    
    #兼容 Chroma query 返回结构：
    # res["documents"][0] -> List[str]
    # res["metadatas"][0] -> List[dict]
    #输出去重、截断后的可读文本
    #返回：(text, empty_flag)
    
    try:
        if not isinstance(res, dict) or res.get("error"):
            return "", True

        docs_all = (res.get("documents") or [[]])[0] or []
        metas_all = (res.get("metadatas") or [[]])[0] or []

        uniq: List[str] = []
        seen = set()

        for i, d in enumerate(docs_all):
            if not d:
                continue

            snip = str(d).strip()
            if not snip:
                continue

            # 用前 160 字去重（简单有效）
            k = snip[:160]
            if k in seen:
                continue
            seen.add(k)

            # 可选：来源名
            name = ""
            if i < len(metas_all) and isinstance(metas_all[i], dict):
                name = str(metas_all[i].get("source") or metas_all[i].get("title") or "").strip()

            # 单行化 + 截断
            sn = snip.replace("\n", " ")
            if len(sn) > max_chars_per:
                sn = sn[:max_chars_per] + "…"

            if name:
                uniq.append(f"• {name}：{sn}")
            else:
                uniq.append(f"• {sn}")

        txt = "\n".join(uniq).strip()
        return txt, (len(uniq) == 0)

    except Exception as e:
        print(f"[FormatMemories Error] {e}")
        return "", True


# 兼容入口：外部若调用 format_memories，就走这层
def format_memories(res, max_chars_per: int = 800) -> Tuple[str, bool]:
    return _format_memories(res, max_chars_per=max_chars_per)


def get_current_user_ctx(req_json: Optional[dict] = None) -> Tuple[Optional[str], str, Optional[str]]:
    """
    返回 (user_id, role, nickname)
    优先从 session 里取；若不存在，再看 req_json 里是否显式提供 user_id（用于第三方桥接场景）。
    role 为空时默认为 "user"。
    """
    user_id = session.get("user_id")
    role = session.get("role") or "user"
    nickname = session.get("nickname")

    if not user_id and isinstance(req_json, dict):
        meta = req_json.get("meta") if isinstance(req_json.get("meta"), dict) else {}
        user_id = (
            req_json.get("user_id")
            or meta.get("user_id")
            or req_json.get("userId")
            or meta.get("userId")
            or req_json.get("qq")
            or meta.get("qq")
        )
        if not nickname:
            nickname = req_json.get("nickname") or meta.get("nickname") or meta.get("sender_name")

    user_id = str(user_id or "").strip() or None
    nickname = str(nickname or "").strip() or None
    role = "admin" if str(role).strip().lower() == "admin" else "user"
    return user_id, role, nickname


# ====== 账号认证（QQ号 + 密码）======
@app.route("/auth/register", methods=["POST", "OPTIONS"])
def auth_register():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id") or "").strip()
        nickname = str(data.get("nickname") or "").strip()
        password = str(data.get("password") or "")
        password_confirm = str(data.get("password_confirm") or "")
        gender = str(data.get("gender") or "unknown").strip() or "unknown"
        age_raw = data.get("age")

        if not user_id:
            return jsonify({"ok": False, "msg": "QQ number is required"}), 200
        if not re.fullmatch(r"\d{5,20}", user_id):
            return jsonify({"ok": False, "msg": "Invalid QQ number format"}), 200
        if not password:
            return jsonify({"ok": False, "msg": "Password is required"}), 200
        if password != password_confirm:
            return jsonify({"ok": False, "msg": "Passwords do not match"}), 200

        profiles = _load_user_profiles()
        if user_id in profiles:
            return jsonify({"ok": False, "msg": "User already exists"}), 200

        # 首位有效注册用户 = admin；其后都为 user
        existing_users = 0
        try:
            for _uid, p in (profiles or {}).items():
                if not isinstance(p, dict):
                    continue
                puid = str(p.get("user_id") or _uid or "").strip()
                if puid:
                    existing_users += 1
        except Exception:
            existing_users = len(profiles or {})
        role = "admin" if existing_users == 0 else "user"
        ph = hash_password(password)
        now = datetime.datetime.utcnow().isoformat()
        age = None
        try:
            if age_raw not in (None, ""):
                age = int(age_raw)
        except Exception:
            age = None

        profiles[user_id] = {
            "user_id": user_id,
            "nickname": nickname or user_id,
            "password_hash": ph,
            "role": role,
            "gender": gender,
            "age": age,
            "created_at": now,
            "updated_at": now,
        }
        _save_user_profiles(profiles)

        session["user_id"] = user_id
        session["role"] = role
        session["nickname"] = nickname or user_id

        return jsonify({
            "ok": True,
            "user_id": user_id,
            "nickname": nickname or user_id,
            "role": role
        }), 200
    except Exception as e:
        print(f"[auth/register error] {e}")
        return jsonify({"ok": False, "msg": "Register failed"}), 200


@app.route("/auth/login", methods=["POST", "OPTIONS"])
def auth_login():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(silent=True) or {}
        user_id = str(data.get("user_id") or "").strip()
        password = str(data.get("password") or "")

        profiles = _load_user_profiles()
        profile = profiles.get(user_id) if user_id else None
        if not isinstance(profile, dict):
            return jsonify({"ok": False, "msg": "Invalid account or password"}), 200

        stored = str(profile.get("password_hash") or "")
        if (not stored) or (not verify_password(password, stored)):
            return jsonify({"ok": False, "msg": "Invalid account or password"}), 200

        role = "admin" if str(profile.get("role") or "").strip().lower() == "admin" else "user"
        nickname = str(profile.get("nickname") or user_id).strip() or user_id

        session["user_id"] = user_id
        session["role"] = role
        session["nickname"] = nickname

        return jsonify({
            "ok": True,
            "user_id": user_id,
            "nickname": nickname,
            "role": role
        }), 200
    except Exception as e:
        print(f"[auth/login error] {e}")
        return jsonify({"ok": False, "msg": "Login failed"}), 200


@app.route("/auth/logout", methods=["POST", "OPTIONS"])
def auth_logout():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        session.clear()
    except Exception:
        pass
    return jsonify({"ok": True}), 200


@app.route("/auth/me", methods=["GET", "OPTIONS"])
def auth_me():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        user_id = str(session.get("user_id") or "").strip()
        if not user_id:
            return jsonify({"ok": True, "logged_in": False}), 200
        role = "admin" if str(session.get("role") or "").strip().lower() == "admin" else "user"
        nickname = str(session.get("nickname") or user_id).strip() or user_id
        return jsonify({
            "ok": True,
            "logged_in": True,
            "user_id": user_id,
            "nickname": nickname,
            "role": role
        }), 200
    except Exception as e:
        print(f"[auth/me error] {e}")
        return jsonify({"ok": True, "logged_in": False}), 200


@app.route("/user/profile", methods=["GET", "OPTIONS"])
def user_profile_get():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = request.get_json(silent=True) or {}
        user_id, role, nickname = get_current_user_ctx(payload if isinstance(payload, dict) else {})
        session_user_id = str(session.get("user_id") or "").strip()
        if not session_user_id:
            return jsonify({"ok": False, "msg": "Not logged in", "logged_in": False}), 200

        user_id = str(user_id or session_user_id).strip()
        profiles = _load_user_profiles()
        profile = profiles.get(user_id) if isinstance(profiles, dict) else None
        if not isinstance(profile, dict):
            profile = {
                "user_id": user_id,
                "nickname": nickname or user_id,
                "role": "user",
                "gender": "unknown",
                "age": None,
            }
        pub = _normalize_public_profile(user_id, profile, nickname_fallback=nickname or user_id, role_fallback=role or "user")
        return jsonify({"ok": True, "logged_in": True, "profile": pub}), 200
    except Exception as e:
        print(f"[user/profile get error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load user profile"}), 200


@app.route("/user/profile/update", methods=["POST", "OPTIONS"])
def user_profile_update():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = request.get_json(silent=True) or {}
        user_id, role, nickname = get_current_user_ctx(payload if isinstance(payload, dict) else {})
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = str(payload.get("user_id") or payload.get("userId") or "").strip()

        # 兼容 file:// 本地页面：session 丢失时允许前端显式带 user_id 兜底
        if not session_user_id and not (user_id or payload_user_id):
            return jsonify({"ok": False, "msg": "Not logged in"}), 200

        user_id = str(session_user_id or user_id or payload_user_id).strip()
        profiles = _load_user_profiles()
        if not isinstance(profiles, dict):
            profiles = {}

        profile = profiles.get(user_id)
        if not isinstance(profile, dict):
            now = datetime.datetime.utcnow().isoformat()
            profile = {
                "user_id": user_id,
                "nickname": nickname or user_id,
                "password_hash": "",
                "role": "user",
                "gender": "unknown",
                "age": None,
                "created_at": now,
                "updated_at": now,
            }

        if "nickname" in payload:
            new_nickname = str(payload.get("nickname") or "").strip()
            if new_nickname:
                profile["nickname"] = new_nickname

        if "gender" in payload:
            g = str(payload.get("gender") or "").strip().lower() or str(profile.get("gender") or "unknown").strip().lower() or "unknown"
            if g not in {"female", "male", "other", "unknown"}:
                g = "unknown"
            profile["gender"] = g

        if "age" in payload:
            v = payload.get("age")
            if v in (None, ""):
                profile["age"] = None
            else:
                try:
                    iv = int(v)
                    if iv < 0:
                        iv = 0
                    if iv > 120:
                        iv = 120
                    profile["age"] = iv
                except Exception:
                    profile["age"] = None

        profile["updated_at"] = datetime.datetime.utcnow().isoformat()
        profiles[user_id] = profile
        _save_user_profiles(profiles)

        new_nick = str(profile.get("nickname") or user_id).strip() or user_id
        session["user_id"] = user_id
        session["role"] = "admin" if str(profile.get("role") or "").strip().lower() == "admin" else "user"
        session["nickname"] = new_nick

        pub = _normalize_public_profile(user_id, profile, nickname_fallback=new_nick, role_fallback=role or "user")
        return jsonify({"ok": True, "profile": pub}), 200
    except Exception as e:
        print(f"[user/profile update error] {e}")
        return jsonify({"ok": False, "msg": "Failed to save user profile"}), 200


@app.route("/persona/get", methods=["GET", "OPTIONS"])
def persona_get():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        cfg = _load_persona_config()
        return jsonify({
            "ok": True,
            "content": str(cfg.get("content") or ""),
            "agent_title": str(cfg.get("agent_title") or ""),
            "agent_name": str(cfg.get("agent_name") or ""),
            "updated_at": cfg.get("updated_at"),
        }), 200
    except Exception as e:
        print(f"[persona/get error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load persona"}), 200


@app.route("/persona/update", methods=["POST", "OPTIONS"])
def persona_update():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = request.get_json(silent=True) or {}
        user_id, role, _nickname = get_current_user_ctx(payload if isinstance(payload, dict) else {})
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = str(payload.get("user_id") or payload.get("userId") or "").strip()

        # 优先 session；session 丢失时回退 payload user_id + profiles role 校验（兼容 file:// 页面）
        effective_user_id = str(session_user_id or user_id or payload_user_id).strip()
        effective_role = "admin" if str(role).strip().lower() == "admin" else "user"
        effective_nick = str(session.get("nickname") or "").strip()

        if (not session_user_id) and effective_user_id:
            profiles = _load_user_profiles()
            prof = profiles.get(effective_user_id) if isinstance(profiles, dict) else None
            if isinstance(prof, dict):
                effective_role = "admin" if str(prof.get("role") or "").strip().lower() == "admin" else "user"
                effective_nick = str(prof.get("nickname") or effective_user_id).strip() or effective_user_id

        if (not effective_user_id) or effective_role != "admin":
            return jsonify({"ok": False, "msg": "Admin only: persona update"}), 200

        content = str(payload.get("content") or "").strip()
        agent_title = re.sub(r"\s+", " ", str(payload.get("agent_title") or "")).strip()
        agent_name = re.sub(r"\s+", " ", str(payload.get("agent_name") or "")).strip()
        if len(agent_title) > 24:
            agent_title = agent_title[:24].strip()
        if len(agent_name) > 24:
            agent_name = agent_name[:24].strip()
        now = datetime.datetime.utcnow().isoformat()
        data = {
            "content": content,
            "agent_title": agent_title,
            "agent_name": agent_name,
            "updated_at": now,
        }
        _save_persona_config(data)
        session["user_id"] = effective_user_id
        session["role"] = effective_role
        session["nickname"] = effective_nick or effective_user_id
        return jsonify({
            "ok": True,
            "content": content,
            "agent_title": agent_title,
            "agent_name": agent_name,
            "updated_at": now
        }), 200
    except Exception as e:
        print(f"[persona/update error] {e}")
        return jsonify({"ok": False, "msg": "Failed to save persona"}), 200


@app.route("/profile/memory_strips", methods=["GET", "OPTIONS"])
def profile_memory_strips_get():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = _request_user_id_fallback()
        effective_user_id = str(session_user_id or payload_user_id).strip()
        if not effective_user_id:
            return jsonify({"ok": False, "msg": "Not logged in"}), 401

        # 兼容 file:// 页面：session 缺失时，允许显式 user_id 兜底并回写 session
        if (not session_user_id) and effective_user_id:
            eff_role, eff_nick = _load_profile_role_nickname(effective_user_id)
            session["user_id"] = effective_user_id
            session["role"] = eff_role
            session["nickname"] = eff_nick or effective_user_id

        profile_user_id = _profile_user_id_for_ctx(effective_user_id)
        data = profiles_load_memory_strips(profile_user_id, profile_base_dir=TYXT_PROFILE_DIR)
        strips_raw = data.get("strips") if isinstance(data, dict) else []
        strips: List[Dict[str, Any]] = []
        for it in (strips_raw if isinstance(strips_raw, list) else []):
            if not isinstance(it, dict):
                continue
            txt = str(it.get("text") or "").strip()
            if not txt:
                continue
            strips.append(
                {
                    "id": str(it.get("id") or "").strip(),
                    "text": txt,
                    "importance": round(max(0.0, min(10.0, safe_float(it.get("importance"), 5.0))), 3),
                    "tags": it.get("tags") if isinstance(it.get("tags"), list) else [],
                }
            )
        return jsonify({"ok": True, "user_id": profile_user_id, "strips": strips}), 200
    except Exception as e:
        print(f"[profile/memory_strips get error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load memory strips"}), 200


@app.route("/profile/memory_strips/save", methods=["POST", "OPTIONS"])
def profile_memory_strips_save():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = _request_user_id_fallback()
        effective_user_id = str(session_user_id or payload_user_id).strip()
        if not effective_user_id:
            return jsonify({"ok": False, "msg": "Not logged in"}), 401

        payload = request.get_json(silent=True) or {}
        strips = payload.get("strips")
        if not isinstance(strips, list):
            strips = []

        if (not session_user_id) and effective_user_id:
            eff_role, eff_nick = _load_profile_role_nickname(effective_user_id)
            session["user_id"] = effective_user_id
            session["role"] = eff_role
            session["nickname"] = eff_nick or effective_user_id

        role = "admin" if str(session.get("role") or "").strip().lower() == "admin" else "user"
        created_by = "admin" if role == "admin" else "user"
        profile_user_id = _profile_user_id_for_ctx(effective_user_id)

        saved = profiles_save_memory_strips(
            user_id=profile_user_id,
            data={"strips": strips},
            profile_base_dir=TYXT_PROFILE_DIR,
            default_created_by=created_by,
        )
        count = len(saved.get("strips") or []) if isinstance(saved, dict) else 0
        return jsonify({"ok": True, "user_id": profile_user_id, "count": count}), 200
    except Exception as e:
        print(f"[profile/memory_strips save error] {e}")
        return jsonify({"ok": False, "msg": "Failed to save memory strips"}), 200


@app.route("/profile/location", methods=["GET", "OPTIONS"])
def profile_location_get():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = _request_user_id_fallback()
        effective_user_id = str(session_user_id or payload_user_id).strip()
        if not effective_user_id:
            return jsonify({"ok": False, "msg": "Not logged in"}), 401

        if (not session_user_id) and effective_user_id:
            eff_role, eff_nick = _load_profile_role_nickname(effective_user_id)
            session["user_id"] = effective_user_id
            session["role"] = eff_role
            session["nickname"] = eff_nick or effective_user_id

        profile_user_id = _profile_user_id_for_ctx(effective_user_id)
        profile = profiles_load_user_profile(profile_user_id, profile_base_dir=TYXT_PROFILE_DIR)
        location = profile.get("location") if isinstance(profile, dict) else {}
        if not isinstance(location, dict):
            location = {}

        city = str(location.get("city") or "").strip()
        lat_raw = location.get("lat")
        lon_raw = location.get("lon")
        lat = None
        lon = None
        try:
            if lat_raw not in (None, ""):
                lat = float(lat_raw)
        except Exception:
            lat = None
        try:
            if lon_raw not in (None, ""):
                lon = float(lon_raw)
        except Exception:
            lon = None

        out_location = {
            "city": city,
            "lat": lat,
            "lon": lon,
            "source": str(location.get("source") or "").strip(),
            "updated_at": safe_int(location.get("updated_at"), 0),
        }
        return jsonify({"ok": True, "location": out_location}), 200
    except Exception as e:
        print(f"[profile/location get error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load location"}), 200


@app.route("/profile/location/save", methods=["POST", "OPTIONS"])
def profile_location_save():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = _request_user_id_fallback()
        effective_user_id = str(session_user_id or payload_user_id).strip()
        if not effective_user_id:
            return jsonify({"ok": False, "msg": "Not logged in"}), 401

        payload = request.get_json(silent=True) or {}
        city = str(payload.get("city") or "").strip()
        lat_raw = payload.get("lat")
        lon_raw = payload.get("lon")

        if not city:
            return jsonify({"ok": False, "msg": "city is required"}), 400

        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except Exception:
            return jsonify({"ok": False, "msg": "lat/lon must be numeric"}), 400

        if (lat < -90.0) or (lat > 90.0) or (lon < -180.0) or (lon > 180.0):
            return jsonify({"ok": False, "msg": "lat/lon out of range"}), 400

        if (not session_user_id) and effective_user_id:
            eff_role, eff_nick = _load_profile_role_nickname(effective_user_id)
            session["user_id"] = effective_user_id
            session["role"] = eff_role
            session["nickname"] = eff_nick or effective_user_id

        profile_user_id = _profile_user_id_for_ctx(effective_user_id)
        location = profiles_update_user_location(
            user_id=profile_user_id,
            city=city,
            lat=lat,
            lon=lon,
            source="user",
            profile_base_dir=TYXT_PROFILE_DIR,
        )
        app.logger.info(
            "User %s updated location city=%s lat=%s lon=%s",
            profile_user_id,
            location.get("city"),
            location.get("lat"),
            location.get("lon"),
        )
        return jsonify({"ok": True, "location": location}), 200
    except Exception as e:
        print(f"[profile/location save error] {e}")
        return jsonify({"ok": False, "msg": "Failed to save location"}), 200


@app.route("/tools/weather", methods=["GET", "OPTIONS"])
def tools_weather():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        session_user_id = str(session.get("user_id") or "").strip()
        payload_user_id = _request_user_id_fallback()
        effective_user_id = str(session_user_id or payload_user_id).strip()
        if not effective_user_id:
            return jsonify({"ok": False, "msg": "Not logged in"}), 401

        if (not session_user_id) and effective_user_id:
            eff_role, eff_nick = _load_profile_role_nickname(effective_user_id)
            session["user_id"] = effective_user_id
            session["role"] = eff_role
            session["nickname"] = eff_nick or effective_user_id

        profile_user_id = _profile_user_id_for_ctx(effective_user_id)
        profile = profiles_load_user_profile(profile_user_id, profile_base_dir=TYXT_PROFILE_DIR)
        location = profile.get("location") if isinstance(profile, dict) else {}
        if not isinstance(location, dict):
            location = {}

        city = str(location.get("city") or "").strip()
        lat_raw = location.get("lat")
        lon_raw = location.get("lon")
        lat = None
        lon = None
        try:
            if lat_raw not in (None, ""):
                lat = float(lat_raw)
        except Exception:
            lat = None
        try:
            if lon_raw not in (None, ""):
                lon = float(lon_raw)
        except Exception:
            lon = None

        if lat is None or lon is None:
            return jsonify({
                "ok": False,
                "error": "no_location",
                "message": "Location is not configured",
            }), 400

        params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "timezone": "auto",
            "forecast_days": 2,
            "hourly": "weathercode",
            "daily": "weathercode,temperature_2m_min,temperature_2m_max",
        }
        resp = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=12)
        if resp.status_code != 200:
            app.logger.error(
                "Open-Meteo request failed: status=%s body=%s",
                resp.status_code,
                (resp.text or "")[:300],
            )
            return jsonify({"ok": False, "error": "weather_fetch_failed", "message": "Weather service request failed"}), 502

        data = resp.json() if resp.content else {}
        cw = data.get("current_weather") if isinstance(data, dict) else {}
        if not isinstance(cw, dict):
            cw = {}
        cwu = data.get("current_weather_units") if isinstance(data, dict) else {}
        if not isinstance(cwu, dict):
            cwu = {}
        hourly = data.get("hourly") if isinstance(data, dict) else {}
        if not isinstance(hourly, dict):
            hourly = {}
        daily = data.get("daily") if isinstance(data, dict) else {}
        if not isinstance(daily, dict):
            daily = {}

        temp = cw.get("temperature")
        weather_code = cw.get("weathercode")
        windspeed = cw.get("windspeed")
        observation_time = str(cw.get("time") or "").strip()
        timezone_name = str(data.get("timezone") or "").strip() if isinstance(data, dict) else ""
        windspeed_unit = str(cwu.get("windspeed") or "").strip()
        temp_unit = str(cwu.get("temperature") or "").strip()
        try:
            temp = float(temp) if temp is not None else None
        except Exception:
            temp = None
        try:
            weather_code = int(weather_code) if weather_code is not None else None
        except Exception:
            weather_code = None
        try:
            windspeed = float(windspeed) if windspeed is not None else None
        except Exception:
            windspeed = None

        # 解析小时天气码，提取“下一阶段天气”
        next_weather_code = None
        try:
            h_times = list(hourly.get("time") or [])
            h_codes = list(hourly.get("weathercode") or [])
            if h_times and h_codes and (len(h_times) == len(h_codes)):
                start_idx = -1
                if observation_time:
                    try:
                        start_idx = h_times.index(observation_time)
                    except ValueError:
                        start_idx = -1
                if start_idx < 0:
                    for i, t in enumerate(h_times):
                        if str(t) >= observation_time:
                            start_idx = i
                            break
                if start_idx < 0:
                    start_idx = 0
                cur_code = None
                try:
                    cur_code = int(h_codes[start_idx])
                except Exception:
                    cur_code = None
                if start_idx + 1 < len(h_codes):
                    for j in range(start_idx + 1, min(len(h_codes), start_idx + 9)):
                        try:
                            cand = int(h_codes[j])
                        except Exception:
                            continue
                        if cur_code is None or cand != cur_code:
                            next_weather_code = cand
                            break
                    if next_weather_code is None:
                        try:
                            next_weather_code = int(h_codes[start_idx + 1])
                        except Exception:
                            next_weather_code = None
        except Exception:
            next_weather_code = None

        # 今日日期、最高/最低温
        date_str = ""
        temp_min = None
        temp_max = None
        try:
            d_times = list(daily.get("time") or [])
            d_mins = list(daily.get("temperature_2m_min") or [])
            d_maxs = list(daily.get("temperature_2m_max") or [])
            if d_times:
                date_str = str(d_times[0] or "").strip()
            if d_mins:
                try:
                    temp_min = float(d_mins[0]) if d_mins[0] is not None else None
                except Exception:
                    temp_min = None
            if d_maxs:
                try:
                    temp_max = float(d_maxs[0]) if d_maxs[0] is not None else None
                except Exception:
                    temp_max = None
        except Exception:
            date_str = ""
            temp_min = None
            temp_max = None
        if not date_str and observation_time:
            date_str = str(observation_time).split("T", 1)[0]

        fetched_at = int(time.time())
        app.logger.info(
            "Weather fetched for user %s city=%s lat=%s lon=%s temp=%s",
            profile_user_id, city, lat, lon, temp
        )
        return jsonify({
            "ok": True,
            "city": city,
            "lat": lat,
            "lon": lon,
            "temperature": temp,
            "weather_code": weather_code,
            "next_weather_code": next_weather_code,
            "date": date_str,
            "temp_min": temp_min,
            "temp_max": temp_max,
            "windspeed": windspeed,
            "temperature_unit": temp_unit or "°C",
            "windspeed_unit": windspeed_unit or "km/h",
            "observation_time": observation_time,
            "timezone": timezone_name,
            "provider": "open-meteo",
            "fetched_at": fetched_at,
        }), 200
    except requests.RequestException as e:
        app.logger.error("Open-Meteo request exception: %s", e)
        return jsonify({"ok": False, "error": "weather_fetch_failed", "message": "Weather service request failed"}), 502
    except Exception as e:
        print(f"[tools/weather error] {e}")
        return jsonify({"ok": False, "msg": "Weather query failed"}), 200


def _require_admin_session() -> Tuple[Optional[str], Optional[Any]]:
    """
    管理后台鉴权：
    - Not logged in：401
    - 非 admin：403
    返回 (admin_user_id, error_response_or_none)
    """
    session_uid = str(session.get("user_id") or "").strip()
    payload_uid = _request_user_id_fallback()
    uid = str(session_uid or payload_uid).strip()
    if not uid:
        return None, (jsonify({"ok": False, "msg": "Not logged in"}), 401)

    role = "admin" if str(session.get("role") or "").strip().lower() == "admin" else "user"
    # session 丢失或 role 不可靠时，回退到 user_profiles 校验
    if role != "admin" or (not session_uid):
        prof_role, prof_nick = _load_profile_role_nickname(uid)
        role = prof_role
        if not session_uid:
            session["user_id"] = uid
            session["role"] = role
            session["nickname"] = prof_nick or uid

    if role != "admin":
        return None, (jsonify({"ok": False, "msg": "Permission denied"}), 403)
    return uid, None


def _resolve_request_user_ctx(payload: Optional[Dict[str, Any]] = None) -> Tuple[str, str, str]:
    """
    Resolve request user context with graceful fallback:
    1) session / explicit payload via get_current_user_ctx
    2) user_id fallback from query/body and profile role lookup
    Returns (user_id, role, nickname)
    """
    data = payload if isinstance(payload, dict) else {}
    user_id, role, nickname = get_current_user_ctx(data)
    uid = str(user_id or "").strip()
    r = "admin" if str(role or "").strip().lower() == "admin" else "user"
    nick = str(nickname or uid).strip() or uid
    if uid:
        return uid, r, nick

    fallback_uid = _request_user_id_fallback()
    if not fallback_uid:
        return "", "user", ""
    prof_role, prof_nick = _load_profile_role_nickname(fallback_uid)
    return str(fallback_uid), ("admin" if prof_role == "admin" else "user"), (prof_nick or fallback_uid)


def _tenant_display_name(channel_type: str, owner_id: str) -> str:
    ch = str(channel_type or "").strip().lower()
    owner = str(owner_id or "").strip()
    if ch == "group":
        return f"群聊 / {owner}"
    if ch == "local":
        return "本地 / 管理员"
    return f"私聊 / {owner}"


def _preview_text(text: str, max_len: int = 120) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) > max_len:
        return s[:max_len] + "…"
    return s


def _preview_text_with_query(text: str, query: str, max_len: int = 320) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    q = str(query or "").strip()
    if not s:
        return ""
    if not q:
        return _preview_text(s, max_len=max_len)
    sl = s.lower()
    ql = q.lower()
    hit = sl.find(ql)
    if hit < 0:
        return _preview_text(s, max_len=max_len)
    left = max(0, hit - max_len // 3)
    right = min(len(s), hit + len(q) + (max_len * 2 // 3))
    out = s[left:right]
    if left > 0:
        out = "…" + out
    if right < len(s):
        out = out + "…"
    return out


def _trim_text(text: str, max_len: int = 6000) -> str:
    s = str(text or "")
    if len(s) <= max_len:
        return s
    return s[:max_len] + "\n...\n[内容过长，已截断]"


def _query_terms(query: str) -> List[str]:
    q = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    if not q:
        return []
    pieces = re.split(r"[\s,，。！？!?:：;；/\\|()\[\]{}\"'`~@#$%^&*+=<>《》“”‘’·…-]+", q)
    terms = [p for p in pieces if p]
    if q and q not in terms:
        terms.insert(0, q)
    # 去重并保序
    out: List[str] = []
    seen: set = set()
    for t in terms:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _lexical_match_score(query: str, text: str) -> Tuple[float, bool]:
    q = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not q or not t:
        return 0.0, False
    terms = _query_terms(q)
    if not terms:
        return 0.0, False

    exact_hit = q in t
    hit_count = 0
    for term in terms:
        if term and term in t:
            hit_count += 1
    ratio = hit_count / max(1, len(terms))

    # 关键词命中加权：完整短语命中 > 分词命中
    score = 0.0
    if exact_hit:
        score += 0.9
    score += 0.35 * ratio
    return score, (exact_hit or hit_count > 0)


_IMPORT_ALLOWED_MODES = {"chatgpt_export", "kb_files"}
_IMPORT_ALLOWED_OWNER_TYPES = {"local", "private", "group"}
_IMPORT_JOB_TERMINAL = {"done", "error", "stopped"}
_IMPORT_JOBS: Dict[str, Dict[str, Any]] = {}
_IMPORT_JOB_LOCK = threading.RLock()
_IMPORT_JOB_KEEP_MAX = max(10, safe_int(os.getenv("TYXT_IMPORT_JOB_KEEP_MAX", "30"), 30))


def _parse_import_owner_target(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    owner_type = str((data or {}).get("owner_type") or "").strip().lower()
    owner_id = str((data or {}).get("owner_id") or "").strip()
    if not owner_type:
        return None, None, "Missing owner_type"
    if owner_type not in _IMPORT_ALLOWED_OWNER_TYPES:
        return None, None, "Invalid owner_type (local/private/group only)"
    if not owner_id:
        return None, None, "Missing owner_id"
    return owner_type, owner_id, None


def _scan_import_files(mode: str, root_dir: str) -> List[Dict[str, Any]]:
    m = str(mode or "").strip().lower()
    root = os.path.abspath(str(root_dir or "").strip())
    if m == "chatgpt_export":
        allowed = {".zip", ".json"}
    else:
        allowed = {".doc", ".docx", ".txt", ".md", ".pdf"}

    details: List[Dict[str, Any]] = []
    if os.path.isfile(root):
        ext = os.path.splitext(root)[1].lower()
        if ext in allowed:
            try:
                sz = int(os.path.getsize(root))
            except Exception:
                sz = 0
            details.append(
                {
                    "name": os.path.basename(root),
                    "path": os.path.basename(root),
                    "size": sz,
                    "ext": ext,
                }
            )
        return details

    for base, _dirs, files in os.walk(root):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in allowed:
                continue
            abs_path = os.path.join(base, fn)
            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
            try:
                sz = int(os.path.getsize(abs_path))
            except Exception:
                sz = 0
            details.append(
                {
                    "name": fn,
                    "path": rel_path,
                    "size": sz,
                    "ext": ext,
                }
            )
    details.sort(key=lambda x: str(x.get("path") or ""))
    return details


@app.route("/admin/user/exists", methods=["GET", "OPTIONS"])
def admin_user_exists():
    if request.method == "OPTIONS":
        return ("", 204)
    _admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        # user_id: 管理员身份兜底（供 _require_admin_session fallback 使用）
        # target_user_id: 真正要校验是否存在的账号
        user_id = str(request.args.get("target_user_id") or request.args.get("user_id") or "").strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "Missing user_id"}), 200
        profiles = _load_user_profiles()
        exists = bool(isinstance(profiles, dict) and user_id in profiles)
        return jsonify({"ok": True, "user_id": user_id, "exists": exists}), 200
    except Exception as e:
        print(f"[admin/user/exists error] {e}")
        return jsonify({"ok": False, "msg": "User verification failed"}), 200


def _normalize_import_path(path_value: Any) -> str:
    return str(path_value or "").replace("\\", "/").replace("./", "").strip()


def _make_empty_file_log(path: str, ext: str = "", size: int = 0) -> Dict[str, Any]:
    return {
        "path": _normalize_import_path(path),
        "ext": str(ext or "").strip().lower(),
        "size": int(size or 0),
        "status": "pending",
        "normalized_records": 0,
        "chunks_total": 0,
        "scanned_records": 0,
        "imported_records": 0,
        "skipped_duplicates": 0,
        "skipped_empty": 0,
        "errors": 0,
        "message": "",
        "progress_pct": 0.0,
    }


def _calc_import_job_progress(job: Dict[str, Any]) -> float:
    file_logs = list((job.get("file_logs") or {}).values())
    if not file_logs:
        return 0.0
    total = 0.0
    for row in file_logs:
        pct = safe_float((row or {}).get("progress_pct"), 0.0)
        pct = max(0.0, min(100.0, pct))
        total += pct
    return round(total / max(1, len(file_logs)), 2)


def _refresh_import_job_summary(job: Dict[str, Any]) -> None:
    file_logs = list((job.get("file_logs") or {}).values())
    summary = {
        "scanned_records": 0,
        "imported_records": 0,
        "skipped_duplicates": 0,
        "skipped_empty": 0,
        "errors": 0,
        "warnings": 0,
        "files_total": len(file_logs),
        "files_done": 0,
        "files_error": 0,
        "files_running": 0,
    }
    for row in file_logs:
        status = str((row or {}).get("status") or "").strip().lower()
        summary["scanned_records"] += safe_int((row or {}).get("scanned_records"), 0)
        summary["imported_records"] += safe_int((row or {}).get("imported_records"), 0)
        summary["skipped_duplicates"] += safe_int((row or {}).get("skipped_duplicates"), 0)
        summary["skipped_empty"] += safe_int((row or {}).get("skipped_empty"), 0)
        summary["errors"] += safe_int((row or {}).get("errors"), 0)
        if status in {"done", "partial", "empty", "stopped"}:
            summary["files_done"] += 1
        elif status == "error":
            summary["files_error"] += 1
            summary["files_done"] += 1
        elif status in {"running"}:
            summary["files_running"] += 1
    summary["progress_pct"] = _calc_import_job_progress(job)
    job["summary"] = summary


def _prune_import_jobs() -> None:
    with _IMPORT_JOB_LOCK:
        if len(_IMPORT_JOBS) <= _IMPORT_JOB_KEEP_MAX:
            return
        rows = sorted(
            _IMPORT_JOBS.values(),
            key=lambda x: safe_int((x or {}).get("created_at"), 0),
            reverse=True,
        )
        keep_ids = {str((r or {}).get("job_id") or "") for r in rows[:_IMPORT_JOB_KEEP_MAX]}
        for jid in list(_IMPORT_JOBS.keys()):
            if jid not in keep_ids:
                _IMPORT_JOBS.pop(jid, None)


def _build_import_job_snapshot(job: Dict[str, Any]) -> Dict[str, Any]:
    logs_map = dict(job.get("file_logs") or {})
    order = list(job.get("file_order") or [])
    out_logs: List[Dict[str, Any]] = []
    emitted = set()
    for p in order:
        k = _normalize_import_path(p)
        if k in logs_map:
            out_logs.append(dict(logs_map[k] or {}))
            emitted.add(k)
    for k, v in logs_map.items():
        if k in emitted:
            continue
        out_logs.append(dict(v or {}))
    return {
        "job_id": str(job.get("job_id") or ""),
        "mode": str(job.get("mode") or ""),
        "root_dir": str(job.get("root_dir") or ""),
        "owner_type": str(job.get("owner_type") or ""),
        "owner_id": str(job.get("owner_id") or ""),
        "created_by": str(job.get("created_by") or ""),
        "status": str(job.get("status") or "pending"),
        "message": str(job.get("message") or ""),
        "created_at": safe_int(job.get("created_at"), 0),
        "started_at": safe_int(job.get("started_at"), 0),
        "updated_at": safe_int(job.get("updated_at"), 0),
        "finished_at": safe_int(job.get("finished_at"), 0),
        "pause_requested": bool(job.get("pause_requested")),
        "stop_requested": bool(job.get("stop_requested")),
        "summary": dict(job.get("summary") or {}),
        "file_logs": out_logs,
        "result": dict(job.get("result") or {}),
    }


def _merge_import_job_file_log(job: Dict[str, Any], evt: Dict[str, Any]) -> None:
    if not isinstance(evt, dict):
        return
    key = _normalize_import_path(evt.get("path") or evt.get("name") or "")
    if not key:
        return
    file_logs = job.setdefault("file_logs", {})
    order = job.setdefault("file_order", [])
    base = file_logs.get(key) or _make_empty_file_log(
        path=key,
        ext=str(evt.get("ext") or evt.get("kind") or "").strip().lower(),
        size=safe_int(evt.get("size"), 0),
    )
    for fld in (
        "status",
        "normalized_records",
        "chunks_total",
        "scanned_records",
        "imported_records",
        "skipped_duplicates",
        "skipped_empty",
        "errors",
        "message",
        "progress_pct",
    ):
        if fld in evt and evt.get(fld) is not None:
            base[fld] = evt.get(fld)
    if "ext" in evt and str(evt.get("ext") or "").strip():
        base["ext"] = str(evt.get("ext") or "").strip().lower()
    if "size" in evt:
        base["size"] = safe_int(evt.get("size"), safe_int(base.get("size"), 0))
    base["path"] = key
    file_logs[key] = base
    if key not in order:
        order.append(key)


def _create_import_job(
    mode: str,
    root_dir: str,
    owner_type: str,
    owner_id: str,
    created_by: str,
    scan_details: List[Dict[str, Any]],
) -> str:
    now_ts = int(time.time())
    job_id = f"import_{now_ts}_{uuid.uuid4().hex[:8]}"
    file_logs: Dict[str, Dict[str, Any]] = {}
    file_order: List[str] = []
    for item in scan_details or []:
        p = _normalize_import_path((item or {}).get("path") or (item or {}).get("name") or "")
        if not p:
            continue
        file_order.append(p)
        file_logs[p] = _make_empty_file_log(
            path=p,
            ext=str((item or {}).get("ext") or "").strip().lower(),
            size=safe_int((item or {}).get("size"), 0),
        )
    job = {
        "job_id": job_id,
        "mode": mode,
        "root_dir": root_dir,
        "owner_type": owner_type,
        "owner_id": owner_id,
        "created_by": created_by,
        "created_at": now_ts,
        "started_at": 0,
        "updated_at": now_ts,
        "finished_at": 0,
        "status": "pending",
        "message": "",
        "pause_requested": False,
        "stop_requested": False,
        "file_logs": file_logs,
        "file_order": file_order,
        "summary": {},
        "result": {},
    }
    _refresh_import_job_summary(job)
    with _IMPORT_JOB_LOCK:
        _IMPORT_JOBS[job_id] = job
        _prune_import_jobs()
    return job_id


def _get_import_job(job_id: str) -> Optional[Dict[str, Any]]:
    jid = str(job_id or "").strip()
    if not jid:
        return None
    with _IMPORT_JOB_LOCK:
        return _IMPORT_JOBS.get(jid)


def _run_import_job_worker(job_id: str) -> None:
    with _IMPORT_JOB_LOCK:
        job = _IMPORT_JOBS.get(job_id)
        if not job:
            return
        job["status"] = "running"
        job["started_at"] = int(time.time())
        job["updated_at"] = int(time.time())

    def _should_pause() -> bool:
        with _IMPORT_JOB_LOCK:
            j = _IMPORT_JOBS.get(job_id) or {}
            return bool(j.get("pause_requested")) and (not bool(j.get("stop_requested")))

    def _should_stop() -> bool:
        with _IMPORT_JOB_LOCK:
            j = _IMPORT_JOBS.get(job_id) or {}
            return bool(j.get("stop_requested"))

    def _progress(evt: Dict[str, Any]) -> None:
        with _IMPORT_JOB_LOCK:
            j = _IMPORT_JOBS.get(job_id)
            if not j:
                return
            _merge_import_job_file_log(j, evt or {})
            j["updated_at"] = int(time.time())
            if j.get("status") not in _IMPORT_JOB_TERMINAL:
                if j.get("pause_requested"):
                    j["status"] = "paused"
                elif j.get("stop_requested"):
                    j["status"] = "stopping"
                else:
                    j["status"] = "running"
            _refresh_import_job_summary(j)

    try:
        with _IMPORT_JOB_LOCK:
            j = _IMPORT_JOBS.get(job_id)
            if not j:
                return
            mode = str(j.get("mode") or "").strip().lower()
            root_dir = str(j.get("root_dir") or "").strip()
            owner_type = str(j.get("owner_type") or "").strip().lower()
            owner_id = str(j.get("owner_id") or "").strip()

        if mode == "chatgpt_export":
            result = import_chatgpt_export_records(
                input_path=root_dir,
                owner_type=owner_type,
                owner_id=owner_id,
                max_records=0,
                progress_callback=_progress,
                should_pause=_should_pause,
                should_stop=_should_stop,
            )
        else:
            result = import_kb_records(
                root_dir=root_dir,
                owner_type=owner_type,
                owner_id=owner_id,
                max_records=0,
                progress_callback=_progress,
                should_pause=_should_pause,
                should_stop=_should_stop,
            )

        with _IMPORT_JOB_LOCK:
            j = _IMPORT_JOBS.get(job_id)
            if not j:
                return
            j["result"] = dict(result or {})
            for row in list((result or {}).get("file_logs") or []):
                _merge_import_job_file_log(j, dict(row or {}))
            now_ts = int(time.time())
            j["updated_at"] = now_ts
            j["finished_at"] = now_ts
            if not isinstance(result, dict) or (not result.get("ok")):
                j["status"] = "error"
                j["message"] = str((result or {}).get("error") or "Import failed")
            elif bool((result or {}).get("stopped_by_control")):
                j["status"] = "stopped"
                j["message"] = "导入已停止"
            else:
                j["status"] = "done"
                j["message"] = "导入完成"
            _refresh_import_job_summary(j)
    except Exception as e:
        with _IMPORT_JOB_LOCK:
            j = _IMPORT_JOBS.get(job_id)
            if j:
                now_ts = int(time.time())
                j["status"] = "error"
                j["message"] = f"Import exception: {e}"
                j["updated_at"] = now_ts
                j["finished_at"] = now_ts
                _refresh_import_job_summary(j)
        print(f"[admin/memory/import worker error] {e}")


def _parse_iso_to_unix(value: Any) -> Optional[int]:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return int(dt.timestamp())
        return int(dt.astimezone().timestamp())
    except Exception:
        return None


def _admin_sim_from_score(raw_score: Any) -> float:
    try:
        d = abs(float(raw_score))
    except Exception:
        d = 999999.0
    return 1.0 / (1.0 + d)


_SINGLE_USER_REBIND_DONE = False


def _single_registered_user_id() -> str:
    try:
        profiles = _load_user_profiles()
        if not isinstance(profiles, dict):
            return ""
        ids: List[str] = []
        for k, p in profiles.items():
            if isinstance(p, dict):
                uid = str(p.get("user_id") or k or "").strip()
            else:
                uid = str(k or "").strip()
            if uid:
                ids.append(uid)
        uniq = sorted(set(ids))
        if len(uniq) == 1:
            return uniq[0]
    except Exception:
        pass
    return ""


def _known_user_ids() -> set:
    out = set()
    try:
        profiles = _load_user_profiles()
        if isinstance(profiles, dict):
            for k, p in profiles.items():
                if isinstance(p, dict):
                    uid = str(p.get("user_id") or k or "").strip()
                else:
                    uid = str(k or "").strip()
                if uid:
                    out.add(uid)
    except Exception:
        pass
    return out


def _canonicalize_chat_user_id(user_id: Any, scene: Any = "", group_id: Any = "") -> str:
    uid = str(user_id or "").strip()
    sc = str(scene or "").strip().lower()
    gid = str(group_id or "").strip()
    if not uid:
        return ""
    if sc == "group" or gid:
        return uid
    low = uid.lower()
    if low in {"anonymous", "none", "null", "system"}:
        return uid
    known = _known_user_ids()
    if uid in known:
        return uid
    single = _single_registered_user_id()
    if single:
        try:
            print(f"[user_id canonicalize] {uid} -> {single}")
        except Exception:
            pass
        return single
    return uid


def _maybe_rebind_single_user_private_tenants() -> None:
    """
    兼容历史测试数据：
    - 当系统仅有一个已注册用户时
    - 把误写到其它 private owner_id（且主要为 local_ui 场景）的记录
      迁移到该唯一用户 owner_id 下
    """
    global _SINGLE_USER_REBIND_DONE
    if _SINGLE_USER_REBIND_DONE:
        return

    target_uid = str(_single_registered_user_id() or "").strip()
    if not target_uid:
        _SINGLE_USER_REBIND_DONE = True
        return

    known_ids = _known_user_ids()
    moved_total = 0
    try:
        tenants = CHAT_MEM_STORE.list_tenants()
    except Exception:
        tenants = []

    for t in tenants:
        try:
            ch = str((t or {}).get("channel_type") or "").strip().lower()
            old_owner = str((t or {}).get("owner_id") or "").strip()
            if ch != "private" or (not old_owner):
                continue
            if old_owner == target_uid:
                continue
            if old_owner in known_ids:
                continue

            # 只迁移“明显是本地 UI 的历史误写”租户，避免影响真实多用户数据
            sample = CHAT_MEM_STORE.list_records(
                channel_type="private",
                owner_id=old_owner,
                page=1,
                page_size=20,
                include_deleted=True,
            )
            sample_rows = sample.get("records") or []
            if not sample_rows:
                continue
            if any(str((getattr(r, "metadata", {}) or {}).get("scene") or "").strip().lower() not in {"", "local_ui", "private", f"qq_private:{old_owner}".lower()} for r in sample_rows):
                continue

            while True:
                got = CHAT_MEM_STORE.list_records(
                    channel_type="private",
                    owner_id=old_owner,
                    page=1,
                    page_size=100,
                    include_deleted=True,
                )
                rows = got.get("records") or []
                if not rows:
                    break

                add_docs: List[str] = []
                add_metas: List[Dict[str, Any]] = []
                del_ids: List[str] = []
                for rec in rows:
                    rid = str(getattr(rec, "id", "") or "").strip()
                    if not rid:
                        continue
                    meta = dict(getattr(rec, "metadata", {}) or {})
                    fp = str(meta.get("fingerprint") or "").strip()

                    if fp and CHAT_MEM_STORE.has_fingerprint("private", target_uid, fp):
                        del_ids.append(rid)
                        continue

                    meta["channel_type"] = "private"
                    meta["owner_id"] = target_uid
                    meta["user_id"] = target_uid
                    scene_v = str(meta.get("scene") or "").strip().lower()
                    if scene_v in {"", "private", "local_ui", f"qq_private:{old_owner}".lower()}:
                        meta["scene"] = f"qq_private:{target_uid}"

                    add_docs.append(str(getattr(rec, "text", "") or ""))
                    add_metas.append(meta)
                    del_ids.append(rid)

                if add_docs:
                    CHAT_MEM_STORE.add(add_docs, add_metas)
                    moved_total += len(add_docs)
                if del_ids:
                    CHAT_MEM_STORE.delete(del_ids, channel_type="private", owner_id=old_owner)
        except Exception:
            continue

    if moved_total > 0:
        try:
            print(f"[tenant_rebind] moved {moved_total} records -> private/{target_uid}")
        except Exception:
            pass
    _SINGLE_USER_REBIND_DONE = True


@app.route("/admin/memory/tenants", methods=["GET", "OPTIONS"])
def admin_memory_tenants():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        _maybe_rebind_single_user_private_tenants()
        tenants = CHAT_MEM_STORE.list_tenants()
        out: List[Dict[str, Any]] = []
        for t in tenants:
            ch = str(t.get("channel_type") or "").strip()
            owner = str(t.get("owner_id") or "").strip()
            out.append(
                {
                    "channel_type": ch,
                    "owner_id": owner,
                    "collection": str(t.get("collection") or make_collection_name(ch, owner)),
                    "display_name": _tenant_display_name(ch, owner),
                    "doc_count": int(t.get("doc_count") or 0),
                    "last_ts": t.get("last_ts"),
                    "deleted_count": int(t.get("deleted_count") or 0),
                }
            )
        out.sort(key=lambda x: int(x.get("last_ts") or 0), reverse=True)
        return jsonify({"ok": True, "tenants": out}), 200
    except Exception as e:
        print(f"[admin/memory/tenants error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load tenant list"}), 200


@app.route("/memory/deleted/private", methods=["GET", "OPTIONS"])
def memory_deleted_private():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = {"user_id": request.args.get("user_id")}
        user_id, _role, _nick = get_current_user_ctx(payload)
        uid = str(user_id or "").strip()
        if not uid:
            return jsonify({"ok": False, "msg": "Not logged in", "logged_in": False}), 200

        page = max(1, safe_int(request.args.get("page"), 1))
        page_size = max(1, min(200, safe_int(request.args.get("page_size"), 100)))

        result = CHAT_MEM_STORE.list_records(
            channel_type="private",
            owner_id=uid,
            page=page,
            page_size=page_size,
            include_deleted=True,
        )
        recs = result.get("records") or []
        out_rows: List[Dict[str, Any]] = []
        now_ts = int(time.time())
        for rec in recs:
            meta = dict(getattr(rec, "metadata", {}) or {})
            if not bool(meta.get("deleted", False)):
                continue
            ts = safe_int(meta.get("timestamp"), 0)
            imp = safe_float(meta.get("importance"), 5.0)
            eff = safe_float(effective_importance(meta, now_ts=now_ts), imp)
            full_text = str(getattr(rec, "text", "") or "")
            out_rows.append(
                {
                    "id": str(getattr(rec, "id", "") or ""),
                    "timestamp": ts,
                    "importance": round(imp, 3),
                    "effective_importance": round(eff, 3),
                    "deleted": True,
                    "emotion": str(meta.get("emotion") or ""),
                    "source": str(meta.get("source") or ""),
                    "text_preview": _preview_text(full_text),
                    "text_full": full_text,
                }
            )

        return jsonify(
            {
                "ok": True,
                "logged_in": True,
                "page": int(result.get("page") or page),
                "page_size": int(result.get("page_size") or page_size),
                "total": len(out_rows),
                "records": out_rows,
            }
        ), 200
    except Exception as e:
        print(f"[memory/deleted/private error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load deleted memories"}), 200


@app.route("/admin/memory/list", methods=["GET", "OPTIONS"])
def admin_memory_list():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        channel_type = str(request.args.get("channel_type") or "").strip().lower()
        owner_id = str(request.args.get("owner_id") or "").strip()
        page = max(1, safe_int(request.args.get("page"), 1))
        page_size = max(1, min(100, safe_int(request.args.get("page_size"), 20)))
        include_deleted = safe_bool(request.args.get("include_deleted"), False)

        if channel_type not in {"private", "group", "local"} or (not owner_id):
            return jsonify({"ok": False, "msg": "Invalid channel_type or owner_id"}), 200

        result = CHAT_MEM_STORE.list_records(
            channel_type=channel_type,
            owner_id=owner_id,
            page=page,
            page_size=page_size,
            include_deleted=include_deleted,
        )
        recs = result.get("records") or []
        out_rows: List[Dict[str, Any]] = []
        now_ts = int(time.time())
        for rec in recs:
            meta = dict(getattr(rec, "metadata", {}) or {})
            ts = safe_int(meta.get("timestamp"), 0)
            imp = safe_float(meta.get("importance"), 5.0)
            eff = safe_float(effective_importance(meta, now_ts=now_ts), imp)
            full_text = str(getattr(rec, "text", "") or "")
            out_rows.append(
                {
                    "id": str(getattr(rec, "id", "") or ""),
                    "timestamp": ts,
                    "importance": round(imp, 3),
                    "effective_importance": round(eff, 3),
                    "deleted": bool(meta.get("deleted", False)),
                    "emotion": str(meta.get("emotion") or ""),
                    "source": str(meta.get("source") or ""),
                    "text_preview": _preview_text(full_text),
                    "text_full": full_text,
                }
            )

        return jsonify(
            {
                "ok": True,
                "page": int(result.get("page") or page),
                "page_size": int(result.get("page_size") or page_size),
                "total": int(result.get("total") or 0),
                "records": out_rows,
            }
        ), 200
    except Exception as e:
        print(f"[admin/memory/list error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load memory list"}), 200


@app.route("/admin/memory/soft_delete", methods=["POST", "OPTIONS"])
def admin_memory_soft_delete():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        data = request.get_json(silent=True) or {}
        channel_type = str(data.get("channel_type") or "").strip().lower()
        owner_id = str(data.get("owner_id") or "").strip()
        mem_id = str(data.get("id") or "").strip()
        deleted = safe_bool(data.get("deleted"), True)
        if channel_type not in {"private", "group", "local"} or (not owner_id) or (not mem_id):
            return jsonify({"ok": False, "msg": "Invalid parameters"}), 200

        ok = CHAT_MEM_STORE.soft_delete(
            channel_type=channel_type,
            owner_id=owner_id,
            mem_id=mem_id,
            deleted=deleted,
            deleted_by=admin_uid,
        )
        if not ok:
            return jsonify({"ok": False, "msg": "not found"}), 200
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"[admin/memory/soft_delete error] {e}")
        return jsonify({"ok": False, "msg": "Soft delete failed"}), 200


@app.route("/admin/memory/set_importance", methods=["POST", "OPTIONS"])
def admin_memory_set_importance():
    if request.method == "OPTIONS":
        return ("", 204)
    _admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        data = request.get_json(silent=True) or {}
        channel_type = str(data.get("channel_type") or "").strip().lower()
        owner_id = str(data.get("owner_id") or "").strip()
        mem_id = str(data.get("id") or "").strip()
        mode = str(data.get("mode") or "delta").strip().lower()
        value = safe_float(data.get("value"), 0.0)
        if channel_type not in {"private", "group", "local"} or (not owner_id) or (not mem_id):
            return jsonify({"ok": False, "msg": "Invalid parameters"}), 200
        if mode not in {"delta", "set"}:
            mode = "delta"

        new_imp = CHAT_MEM_STORE.set_importance(
            channel_type=channel_type,
            owner_id=owner_id,
            mem_id=mem_id,
            mode=mode,
            value=value,
        )
        if new_imp is None:
            return jsonify({"ok": False, "msg": "not found"}), 200
        return jsonify({"ok": True, "importance": round(float(new_imp), 3)}), 200
    except Exception as e:
        print(f"[admin/memory/set_importance error] {e}")
        return jsonify({"ok": False, "msg": "Importance update failed"}), 200


@app.route("/admin/memory/import/scan", methods=["POST", "OPTIONS"])
def admin_memory_import_scan():
    if request.method == "OPTIONS":
        return ("", 204)
    _admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        data = request.get_json(silent=True) or {}
        mode = str(data.get("mode") or "").strip().lower()
        owner_type, owner_id, owner_err = _parse_import_owner_target(data)
        if owner_err:
            return jsonify({"ok": False, "msg": owner_err}), 200
        if mode not in _IMPORT_ALLOWED_MODES:
            return jsonify({"ok": False, "msg": "Invalid mode (chatgpt_export/kb_files only)"}), 200
        # 导入目录固定为共享目录下 import，前端仅提供“打开文件夹”按钮
        root_abs = os.path.abspath(IMPORT_DROP_DIR)
        os.makedirs(root_abs, exist_ok=True)

        details = _scan_import_files(mode, root_abs)
        return jsonify(
            {
                "ok": True,
                "mode": mode,
                "root_dir": root_abs,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "file_count": len(details),
                "details": details[:5000],
            }
        ), 200
    except Exception as e:
        print(f"[admin/memory/import/scan error] {e}")
        return jsonify({"ok": False, "msg": "Failed to scan import source"}), 200


@app.route("/admin/memory/import/run", methods=["POST", "OPTIONS"])
def admin_memory_import_run():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        data = request.get_json(silent=True) or {}
        mode = str(data.get("mode") or "").strip().lower()
        owner_type, owner_id, owner_err = _parse_import_owner_target(data)
        if owner_err:
            return jsonify({"ok": False, "msg": owner_err}), 200
        if mode not in _IMPORT_ALLOWED_MODES:
            return jsonify({"ok": False, "msg": "Invalid mode (chatgpt_export/kb_files only)"}), 200
        # 导入目录固定为共享目录下 import，导入条数不设上限（max_records=0）
        root_abs = os.path.abspath(IMPORT_DROP_DIR)
        os.makedirs(root_abs, exist_ok=True)
        scan_details = _scan_import_files(mode, root_abs)
        if not scan_details:
            return jsonify({"ok": False, "msg": "No importable files in import directory"}), 200

        job_id = _create_import_job(
            mode=mode,
            root_dir=root_abs,
            owner_type=owner_type,
            owner_id=owner_id,
            created_by=admin_uid,
            scan_details=scan_details,
        )
        th = threading.Thread(target=_run_import_job_worker, args=(job_id,), daemon=True)
        th.start()

        app.logger.info(
            "memory import started by=%s mode=%s owner_type=%s owner_id=%s job_id=%s files=%s",
            admin_uid,
            mode,
            owner_type,
            owner_id,
            job_id,
            len(scan_details),
        )
        job = _get_import_job(job_id) or {}
        return jsonify(
            {
                "ok": True,
                "job_id": job_id,
                "status": str(job.get("status") or "running"),
                "mode": mode,
                "root_dir": root_abs,
                "owner_type": owner_type,
                "owner_id": owner_id,
                "file_count": len(scan_details),
                "file_logs": list((_build_import_job_snapshot(job).get("file_logs") or []))[:5000],
            }
        ), 200
    except Exception as e:
        print(f"[admin/memory/import/run error] {e}")
        return jsonify({"ok": False, "msg": "Import run failed"}), 200


@app.route("/admin/memory/import/status", methods=["GET", "OPTIONS"])
def admin_memory_import_status():
    if request.method == "OPTIONS":
        return ("", 204)
    _admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        job_id = str(request.args.get("job_id") or "").strip()
        if not job_id:
            with _IMPORT_JOB_LOCK:
                jobs = sorted(
                    list(_IMPORT_JOBS.values()),
                    key=lambda x: safe_int((x or {}).get("created_at"), 0),
                    reverse=True,
                )
                if not jobs:
                    return jsonify({"ok": False, "msg": "No import jobs"}), 200
                job = jobs[0]
        else:
            job = _get_import_job(job_id)
            if not job:
                return jsonify({"ok": False, "msg": "Import job not found"}), 200

        snap = _build_import_job_snapshot(job)
        return jsonify({"ok": True, "job": snap}), 200
    except Exception as e:
        print(f"[admin/memory/import/status error] {e}")
        return jsonify({"ok": False, "msg": "Failed to load import job status"}), 200


@app.route("/admin/memory/import/control", methods=["POST", "OPTIONS"])
def admin_memory_import_control():
    if request.method == "OPTIONS":
        return ("", 204)
    _admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        data = request.get_json(silent=True) or {}
        job_id = str(data.get("job_id") or "").strip()
        action = str(data.get("action") or "").strip().lower()
        if not job_id:
            return jsonify({"ok": False, "msg": "Missing job_id"}), 200
        if action not in {"pause", "resume", "stop"}:
            return jsonify({"ok": False, "msg": "Invalid action (pause/resume/stop only)"}), 200

        with _IMPORT_JOB_LOCK:
            job = _IMPORT_JOBS.get(job_id)
            if not job:
                return jsonify({"ok": False, "msg": "Import job not found"}), 200
            status = str(job.get("status") or "").strip().lower()
            if status in _IMPORT_JOB_TERMINAL:
                snap = _build_import_job_snapshot(job)
                return jsonify({"ok": True, "job": snap}), 200

            if action == "pause":
                job["pause_requested"] = True
                if status in {"running", "pending"}:
                    job["status"] = "paused"
                job["message"] = "Import paused"
            elif action == "resume":
                job["pause_requested"] = False
                if status in {"paused", "pending", "running"}:
                    job["status"] = "running"
                job["message"] = "Import resumed"
            else:
                job["stop_requested"] = True
                job["pause_requested"] = False
                if status not in _IMPORT_JOB_TERMINAL:
                    job["status"] = "stopping"
                job["message"] = "Stopping import"
            job["updated_at"] = int(time.time())
            _refresh_import_job_summary(job)
            snap = _build_import_job_snapshot(job)

        return jsonify({"ok": True, "job": snap}), 200
    except Exception as e:
        print(f"[admin/memory/import/control error] {e}")
        return jsonify({"ok": False, "msg": "Import control failed"}), 200


@app.route("/admin/memory/search", methods=["POST", "OPTIONS"])
def admin_memory_search():
    if request.method == "OPTIONS":
        return ("", 204)
    _admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    try:
        data = request.get_json(silent=True) or {}
        owner_type, owner_id, owner_err = _parse_import_owner_target(data)
        if owner_err:
            return jsonify({"ok": False, "msg": owner_err}), 200

        query = str(data.get("query") or "").strip()

        limit = max(1, min(20, safe_int(data.get("limit"), 20)))
        t_from = _parse_iso_to_unix(data.get("time_from"))
        t_to = _parse_iso_to_unix(data.get("time_to"))
        if str(data.get("time_from") or "").strip() and t_from is None:
            return jsonify({"ok": False, "msg": "Invalid time_from format"}), 200
        if str(data.get("time_to") or "").strip() and t_to is None:
            return jsonify({"ok": False, "msg": "Invalid time_to format"}), 200

        imp_min = safe_float(data.get("importance_min"), 0.0)
        imp_max = safe_float(data.get("importance_max"), 10.0)
        deleted_only = safe_bool(data.get("deleted_only"), False)
        imp_min = max(0.0, min(10.0, imp_min))
        imp_max = max(0.0, min(10.0, imp_max))
        if imp_min > imp_max:
            imp_min, imp_max = imp_max, imp_min

        # 新增：当 query 为空但定义了日期范围时，按日期窗口直接列出聊天记录（不做语义检索）。
        if (not query) and (t_from is not None or t_to is not None):
            out_rows: List[Dict[str, Any]] = []
            page = 1
            page_size = 100
            saw_older_than_from = False
            while len(out_rows) < limit:
                page_res = CHAT_MEM_STORE.list_records(
                    channel_type=owner_type,
                    owner_id=owner_id,
                    page=page,
                    page_size=page_size,
                    include_deleted=bool(deleted_only),
                )
                recs = list((page_res or {}).get("records") or [])
                if not recs:
                    break

                for rec in recs:
                    meta = dict(getattr(rec, "metadata", {}) or {})
                    full_text = str(getattr(rec, "text", "") or "")
                    if not full_text.strip():
                        continue
                    is_deleted = bool(meta.get("deleted", False))
                    if deleted_only and (not is_deleted):
                        continue
                    if (not deleted_only) and is_deleted:
                        continue
                    ts = safe_int(meta.get("timestamp"), 0)
                    if t_to is not None and ts > t_to:
                        # 结果按时间倒序，当前页可能还会出现更早记录，继续扫描
                        continue
                    if t_from is not None and ts < t_from:
                        saw_older_than_from = True
                        # 已落到起始时间前，后续页只会更旧，可提前结束
                        continue
                    imp = safe_float(meta.get("importance"), 5.0)
                    if imp < imp_min or imp > imp_max:
                        continue

                    if ts > 0:
                        try:
                            ts_iso = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
                        except Exception:
                            ts_iso = ""
                    else:
                        ts_iso = ""

                    out_rows.append(
                        {
                            "id": str(getattr(rec, "id", "") or ""),
                            "text": _preview_text(full_text),
                            "text_preview": _preview_text(full_text),
                            "text_full": _trim_text(full_text, max_len=6000),
                            "timestamp": ts_iso,
                            "importance": round(safe_float(meta.get("importance"), 0.0), 3),
                            "source": str(meta.get("source") or ""),
                            "layer": str(meta.get("layer") or ""),
                            "deleted": is_deleted,
                            "owner_type": owner_type,
                            "owner_id": owner_id,
                        }
                    )
                    if len(out_rows) >= limit:
                        break

                if len(out_rows) >= limit:
                    break
                if len(recs) < page_size:
                    break
                if saw_older_than_from and t_from is not None:
                    break
                page += 1

            return jsonify(
                {
                    "ok": True,
                    "records": out_rows[:limit],
                    "note": "Query empty: returned records by date range",
                }
            ), 200

        if not query:
            return jsonify({"ok": False, "msg": "Please provide a query or date range"}), 200

        # 管理检索：多取一些候选，再做“语义 + 关键词命中”二次排序
        query_clean = str(query or "").strip()
        keyword_like = (2 <= len(query_clean) <= 24) and (re.search(r"\s", query_clean) is None)
        raw_top_k = max(limit * 20, 240)
        records = CHAT_MEM_STORE.search_raw(
            query=query,
            top_k=raw_top_k,
            filters=(
                {
                    "channel_type": owner_type,
                    "owner_id": owner_id,
                    "deleted": True,
                }
                if deleted_only
                else {
                    "channel_type": owner_type,
                    "owner_id": owner_id,
                    "deleted": {"$ne": True},
                }
            ),
        )

        now_ts = int(time.time())
        scored: List[Tuple[float, float, bool, int, Any]] = []
        lexical_hit_count = 0
        for rec in records:
            meta = dict(getattr(rec, "metadata", {}) or {})
            full_text = str(getattr(rec, "text", "") or "")
            if not full_text.strip():
                continue
            ts = safe_int(meta.get("timestamp"), 0)
            if t_from is not None and ts < t_from:
                continue
            if t_to is not None and ts > t_to:
                continue
            imp = safe_float(meta.get("importance"), 5.0)
            if imp < imp_min or imp > imp_max:
                continue
            eff = safe_float(effective_importance(meta, now_ts=now_ts), imp)
            sim = _admin_sim_from_score(getattr(rec, "score", None))
            semantic = sim * (1.0 + max(0.0, min(10.0, eff)) / 10.0)
            lex_score, lex_hit = _lexical_match_score(query, full_text)
            if lex_hit:
                lexical_hit_count += 1
            is_structured_blob = (
                len(full_text) >= 2500
                and (
                    ("content_type" in full_text and "asset_pointer" in full_text)
                    or (full_text.count("{") >= 20 and full_text.count("}") >= 20)
                )
            )
            if is_structured_blob and (not lex_hit):
                # 跳过明显非自然语言的大块结构化噪音（如导出中的图片资产对象）
                continue
            # 对完全无关键词命中的候选做轻微降权，避免明显不相关排在前面
            if (not lex_hit) and len(str(query or "").strip()) >= 2:
                semantic *= 0.55
            final = semantic + lex_score
            scored.append((final, lex_score, bool(lex_hit), ts, rec))

        scored.sort(key=lambda x: (-x[0], -x[1], -x[3]))
        if keyword_like and lexical_hit_count <= 0:
            return jsonify({"ok": True, "records": [], "note": "No records contain this keyword (possibly not imported yet)"}), 200
        # 关键修正：若已经存在关键词命中，则仅返回关键词命中的记录，
        # 不再使用“无关键词命中”的语义候选来凑满 limit。
        if lexical_hit_count > 0:
            scored = [row for row in scored if bool(row[2])]
        out_rows: List[Dict[str, Any]] = []
        for _score, _lex, _lex_hit, _ts, rec in scored[:limit]:
            meta = dict(getattr(rec, "metadata", {}) or {})
            full_text = str(getattr(rec, "text", "") or "")
            ts = safe_int(meta.get("timestamp"), 0)
            if ts > 0:
                try:
                    ts_iso = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
                except Exception:
                    ts_iso = ""
            else:
                ts_iso = ""
            out_rows.append(
                {
                    "id": str(getattr(rec, "id", "") or ""),
                    "text": _preview_text_with_query(full_text, query, max_len=320),
                    "text_preview": _preview_text_with_query(full_text, query, max_len=320),
                    "text_full": _trim_text(full_text, max_len=6000),
                    "timestamp": ts_iso,
                    "importance": round(safe_float(meta.get("importance"), 0.0), 3),
                    "source": str(meta.get("source") or ""),
                    "layer": str(meta.get("layer") or ""),
                    "deleted": bool(meta.get("deleted", False)),
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                }
            )
        return jsonify({"ok": True, "records": out_rows}), 200
    except Exception as e:
        print(f"[admin/memory/search error] {e}")
        return jsonify({"ok": False, "msg": "Search failed"}), 200


# ====== 健康检查 ======
@app.route("/", methods=["GET"])
def index():
    """
    主页：直接返回 TYXT_UI.html
    方便局域网其它设备通过 http://IP:5000/ 访问 UI
    """
    try:
        if os.path.exists(TYXT_UI_HTML):
            return send_file(TYXT_UI_HTML, mimetype="text/html; charset=utf-8")

        # 兼容当前项目结构：前端文件位于 frontend/TYXT_UI.html
        fallback_html = os.path.join(TYXT_FRONTEND_DIR, "TYXT_UI.html")
        if os.path.exists(fallback_html):
            return send_file(fallback_html, mimetype="text/html; charset=utf-8")

        raise FileNotFoundError(TYXT_UI_HTML)
    except Exception as e:
        return f"TYXT_UI.html not found. Check TYXT_UI_HTML path. Error: {e}", 500


@app.route("/frontend/<path:filename>", methods=["GET"])
def frontend_static(filename):
    """
    前端静态资源入口（logo / 图片等）
    """
    safe_name = str(filename or "").replace("\\", "/").lstrip("/")
    if not safe_name:
        return ("", 404)
    try:
        return send_from_directory(TYXT_FRONTEND_DIR, safe_name, as_attachment=False)
    except Exception:
        return ("", 404)


@app.route("/chatgpt_logo_transparent.png", methods=["GET"])
def frontend_chatgpt_logo():
    try:
        return send_from_directory(
            TYXT_FRONTEND_DIR,
            "chatgpt_logo_transparent.png",
            as_attachment=False
        )
    except Exception:
        return ("", 404)


@app.route("/favicon.ico", methods=["GET"])
def frontend_favicon():
    try:
        ico_path = os.path.join(TYXT_FRONTEND_DIR, "favicon.ico")
        if os.path.exists(ico_path):
            return send_from_directory(TYXT_FRONTEND_DIR, "favicon.ico", as_attachment=False)

        logo_path = os.path.join(TYXT_FRONTEND_DIR, "chatgpt_logo_transparent.png")
        if os.path.exists(logo_path):
            return send_from_directory(
                TYXT_FRONTEND_DIR,
                "chatgpt_logo_transparent.png",
                as_attachment=False
            )
    except Exception:
        pass
    return ("", 204)


@app.route("/tools/lan/rootca", methods=["GET"])
def api_lan_rootca():
    try:
        if os.path.exists(TYXT_LAN_ROOT_CA):
            return send_file(TYXT_LAN_ROOT_CA, mimetype="application/pkix-cert")
        return jsonify({"ok": False, "msg": "LAN root CA not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Failed to read LAN root CA: {e}"}), 500


@app.route("/tools/lan/bootstrap", methods=["GET"])
def api_lan_bootstrap():
    try:
        if os.path.exists(TYXT_LAN_BOOTSTRAP_JSON):
            return send_file(TYXT_LAN_BOOTSTRAP_JSON, mimetype="application/json; charset=utf-8")
        return jsonify({"ok": False, "msg": "LAN bootstrap file not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Failed to read LAN bootstrap file: {e}"}), 500


@app.route("/tools/lan/client_join_ps1", methods=["GET"])
def api_lan_client_join_ps1():
    try:
        if os.path.exists(TYXT_LAN_CLIENT_JOIN_PS1):
            return send_file(TYXT_LAN_CLIENT_JOIN_PS1, mimetype="text/plain; charset=utf-8")
        return jsonify({"ok": False, "msg": "LAN client join script not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Failed to read LAN client join script: {e}"}), 500


@app.route("/tools/lan/install_lan_root_ca_ps1", methods=["GET"])
def api_lan_install_root_ca_ps1():
    try:
        if os.path.exists(TYXT_LAN_INSTALL_ROOTCA_PS1):
            return send_file(TYXT_LAN_INSTALL_ROOTCA_PS1, mimetype="text/plain; charset=utf-8")
        return jsonify({"ok": False, "msg": "LAN root CA installer script not found"}), 404
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Failed to read LAN root CA installer script: {e}"}), 500


@app.route("/health", methods=["GET","OPTIONS"])
def api_health():
    if request.method == "OPTIONS": return ("",204)
    return jsonify({"ok": True, "msg": "backend alive"}), 200

@app.route("/chat", methods=["OPTIONS"])
def chat_options():
    resp=make_response("",204)
    origin = request.headers.get("Origin", "").strip()
    resp.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Methods"]="POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"]="Content-Type, Authorization"
    return resp

# ============================================================
# 14 路由：/health 与 /chat（第三方桥接入口）
# ============================================================

# ✅ 静音到期时间：按“群/私聊”分桶，避免互相影响
# key 示例：
#   group:<group_id>
#   private:<qq_user_id>
MUTE_UNTIL: Dict[str, float] = {}
# 低误触发英文口令（避免日常聊天误触发）；可用环境变量覆盖
MUTE_CMD_ON_TOKEN = str(os.getenv("TYXT_MUTE_CMD_ON", "TYXT::SILENCE::ON") or "").strip() or "TYXT::SILENCE::ON"
MUTE_CMD_OFF_TOKEN = str(os.getenv("TYXT_MUTE_CMD_OFF", "TYXT::SILENCE::OFF") or "").strip() or "TYXT::SILENCE::OFF"

def _mute_key(meta: dict) -> str:
    scene = str(meta.get("scene") or "").strip() or "private"
    gid = str(meta.get("group_id") or "").strip()
    uid = str(meta.get("user_id") or "").strip()
    if scene == "group" and gid:
        return f"group:{gid}"
    return f"private:{uid or 'unknown'}"


def _ctx_group_id_for_prompt(meta: Dict[str, Any]) -> str:
    """
    群聊临时上下文来源（统一版）：
    - 私聊：不拼群临时（返回空）
    - 群聊：默认拼“本群”临时上下文（返回当前 group_id）
    - 可选覆盖：支持环境变量/配置项 TYXT_CTX_GROUP_PROMPT_MAP 做映射
      - 支持 JSON 对象：{"<源群ID>":"<目标群ID>", "*":"self"}
      - 支持简写字符串：<源群ID>:<目标群ID>,*:self
      - value 可为：
        - "self"：使用当前群
        - "" / "none" / "off"：不注入群临时
        - 其他群号：注入指定群临时
    """
    scene = str((meta or {}).get("scene") or "").strip().lower()
    if scene != "group":
        return ""

    gid = str((meta or {}).get("group_id") or "").strip()
    if not gid:
        return ""

    raw_map = os.getenv("TYXT_CTX_GROUP_PROMPT_MAP", "").strip()
    if not raw_map:
        try:
            raw_map = MODEL_CONFIG.get("ctx_group_prompt_map", "")
        except Exception:
            raw_map = ""

    mapping: Dict[str, str] = {}
    try:
        if isinstance(raw_map, dict):
            for k, v in raw_map.items():
                ks = str(k or "").strip()
                if ks:
                    mapping[ks] = str(v or "").strip()
        elif isinstance(raw_map, str) and raw_map.strip():
            s = raw_map.strip()
            if s.startswith("{"):
                obj = json.loads(s)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        ks = str(k or "").strip()
                        if ks:
                            mapping[ks] = str(v or "").strip()
            else:
                # 逗号分隔：src:dst,src2:dst2,*:self
                parts = [x.strip() for x in s.split(",") if str(x or "").strip()]
                for p in parts:
                    if ":" not in p:
                        continue
                    src, dst = p.split(":", 1)
                    src = str(src or "").strip()
                    dst = str(dst or "").strip()
                    if src:
                        mapping[src] = dst
    except Exception:
        mapping = {}

    target = mapping.get(gid)
    if target is None:
        target = mapping.get("*")

    if target is None:
        # 默认：群聊用本群上下文
        return gid

    tv = str(target or "").strip().lower()
    if tv in {"", "none", "null", "off", "disable", "disabled"}:
        return ""
    if tv in {"self", "same", "current"}:
        return gid
    return str(target or "").strip()


def _safe_id_token(v: Any, default: str = "unknown") -> str:
    s = str(v or "").strip()
    if not s:
        return default
    s = re.sub(r"[^0-9A-Za-z_.-]", "_", s)
    return s or default


def _safe_fs_name(v: Any, default: str = "default") -> str:
    s = str(v or "").strip()
    if not s:
        return default
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", "_", s).strip(" ._")
    if not s:
        return default
    if len(s) > 80:
        s = s[:80].rstrip(" ._")
    return s or default


def _chat_title_from_meta(meta: Optional[Dict[str, Any]]) -> str:
    m = meta or {}
    for k in ("chat_title", "session_title", "window_title", "chat_name", "title"):
        v = str(m.get(k) or "").strip()
        if v:
            return v
    return "default"


def _runtime_logs_dir() -> str:
    p = os.path.join(ALLOWED_DIR, "runtime_logs")
    os.makedirs(p, exist_ok=True)
    return p


def _runtime_groups_root() -> str:
    p = os.path.join(_runtime_logs_dir(), "groups")
    os.makedirs(p, exist_ok=True)
    return p


def _runtime_private_root() -> str:
    p = os.path.join(_runtime_logs_dir(), "private")
    os.makedirs(p, exist_ok=True)
    return p


def _runtime_private_dir(user_id: Any) -> str:
    uid = _safe_id_token(user_id, "anonymous")
    p = os.path.join(_runtime_private_root(), uid)
    os.makedirs(p, exist_ok=True)
    return p


def _runtime_private_deleted_dir(user_id: Any) -> str:
    """
    私聊上下文“回收站”目录：
      runtime_logs/private/<user_id>/deleted
    """
    uid = _safe_id_token(user_id, "anonymous")
    p = os.path.join(_runtime_private_dir(uid), "deleted")
    os.makedirs(p, exist_ok=True)
    return p


def _runtime_private_chat_path(user_id: Any, chat_title: Any = "default") -> str:
    uid = _safe_id_token(user_id, "anonymous")
    title = _safe_fs_name(chat_title, "default")
    return os.path.join(_runtime_private_dir(uid), f"{uid}_{title}.txt")


def _runtime_title_match_key(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return "default"
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = re.sub(r"\s+", "_", s).strip(" ._")
    if not s:
        s = "default"
    return s.lower()


def _resolve_private_chat_context_file(user_id: Any, chat_title: Any) -> Tuple[Optional[str], str]:
    """
    根据 chat_title 解析运行时上下文文件路径，兼容：
    1) 新命名：<uid>_<title>.txt
    2) 旧命名：<title>.txt
    3) 标题轻微差异（空格/下划线/尾部下划线）
    """
    uid = _safe_id_token(user_id, "anonymous")
    title = _safe_fs_name(chat_title, "default")
    user_dir = _runtime_private_dir(uid)

    exact_new = os.path.abspath(_runtime_private_chat_path(uid, title))
    if os.path.exists(exact_new):
        return exact_new, title

    exact_old = os.path.abspath(os.path.join(user_dir, f"{title}.txt"))
    if os.path.exists(exact_old):
        return exact_old, title

    want_key = _runtime_title_match_key(title)
    prefix = f"{uid}_"
    candidates: List[Tuple[float, str]] = []
    try:
        for name in os.listdir(user_dir):
            p = os.path.abspath(os.path.join(user_dir, name))
            if not os.path.isfile(p):
                continue
            if not str(name or "").lower().endswith(".txt"):
                continue

            n = str(name)
            raw_title = ""
            if n.startswith(prefix):
                raw_title = n[len(prefix):-4]
            else:
                raw_title = n[:-4]
            if not raw_title:
                continue

            if _runtime_title_match_key(raw_title) != want_key:
                continue

            try:
                mt = float(os.path.getmtime(p))
            except Exception:
                mt = 0.0
            candidates.append((mt, p))
    except Exception:
        candidates = []

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1], title
    return None, title


def _list_private_chat_context_titles(user_id: Any) -> List[str]:
    """
    列出某个用户在 runtime_logs/private/<user_id>/ 下已有的聊天上下文标题（文件名中的 title 部分）。
    返回值为已做文件名安全化后的 title 列表。
    """
    uid = _safe_id_token(user_id, "anonymous")
    base_dir = _runtime_private_dir(uid)
    if not os.path.isdir(base_dir):
        return []
    out: List[str] = []
    prefix = f"{uid}_"
    try:
        for name in os.listdir(base_dir):
            if not str(name or "").lower().endswith(".txt"):
                continue
            if not str(name).startswith(prefix):
                continue
            title = str(name)[len(prefix):-4].strip()
            if title:
                out.append(title)
    except Exception:
        return []
    # 去重并保持可预测排序
    return sorted(set(out))


def _extract_ts_from_runtime_header(header_line: str) -> str:
    try:
        m = re.match(r"^\[([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})\]", str(header_line or "").strip())
        if m:
            return str(m.group(1) or "").strip()
    except Exception:
        pass
    return ""


def _parse_runtime_turn_segments(block_text: str) -> List[Dict[str, str]]:
    """
    解析单个 runtime 聊天块中的“说话人分段”。
    兼容多行正文：
      说话人A: 第一行
      续行...
      说话人B: 第一行
      续行...
    """
    lines = [ln.rstrip("\r") for ln in str(block_text or "").splitlines()]
    if not lines:
        return []

    segments: List[Dict[str, str]] = []
    cur_speaker = ""
    cur_buf: List[str] = []

    def _flush():
        nonlocal cur_speaker, cur_buf, segments
        txt = "\n".join([x for x in cur_buf if str(x).strip()]).strip()
        if cur_speaker and txt:
            segments.append({"speaker": cur_speaker, "text": txt})
        cur_speaker = ""
        cur_buf = []

    for ln in lines:
        st = str(ln or "").strip()
        if not st:
            if cur_speaker:
                cur_buf.append("")
            continue

        m = re.match(r"^([A-Za-z0-9_\u4e00-\u9fff]{1,20})\s*[：:]\s*(.*)$", st)
        if m:
            _flush()
            cur_speaker = str(m.group(1) or "").strip()
            cur_buf = [str(m.group(2) or "").strip()]
        else:
            if cur_speaker:
                cur_buf.append(st)

    _flush()
    return segments


def _load_private_chat_context_messages(user_id: Any, chat_title: Any, max_turns: int = 200) -> List[Dict[str, str]]:
    """
    读取 runtime 私聊上下文并解析为消息数组（user/ai 交替）。
    返回格式：
      [{"role":"user","content":"...","time":"YYYY-mm-dd HH:MM:SS"}, ...]
    """
    uid = _safe_id_token(user_id, "anonymous")
    p, _resolved_title = _resolve_private_chat_context_file(uid, chat_title)
    if (not p) or (not os.path.exists(p)):
        return []

    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read() or ""
    except Exception:
        return []

    if not raw.strip():
        return []

    blocks = [x.strip() for x in re.split(r"\n-{20,}\n", raw) if str(x or "").strip()]
    if not blocks:
        return []

    max_turns_i = max(1, min(safe_int(max_turns, 200), 500))
    if len(blocks) > max_turns_i:
        blocks = blocks[-max_turns_i:]

    out: List[Dict[str, str]] = []
    bot_default_name = str(os.getenv("ASSISTANT_NAME", "管家")).strip().lower()
    ai_aliases = {"ai", "assistant", "bot", bot_default_name}
    ai_aliases = {x for x in ai_aliases if x}

    for blk in blocks:
        lines = [ln.rstrip("\r") for ln in str(blk or "").splitlines() if str(ln or "").strip()]
        if len(lines) < 2:
            continue

        header = str(lines[0] or "").strip()
        body = "\n".join(lines[1:])
        ts = _extract_ts_from_runtime_header(header)

        segments = _parse_runtime_turn_segments(body)
        if not segments:
            continue

        user_seg = None
        ai_seg = None
        for seg in segments:
            sp = str(seg.get("speaker") or "").strip().lower()
            if sp in ai_aliases:
                ai_seg = seg
            elif user_seg is None:
                user_seg = seg

        # 兜底：文件是固定“用户在前，AI在后”
        if user_seg is None and segments:
            user_seg = segments[0]
        if ai_seg is None:
            if len(segments) >= 2:
                ai_seg = segments[-1]
            elif segments:
                ai_seg = segments[0]

        user_text = str((user_seg or {}).get("text") or "").strip()
        ai_text = str((ai_seg or {}).get("text") or "").strip()

        if user_text:
            out.append({"role": "user", "content": user_text, "time": ts})
        if ai_text:
            out.append({"role": "ai", "content": ai_text, "time": ts})

    return out


def _build_turn_pairs_from_messages(messages: List[Dict[str, str]], max_turns: int = 2000) -> List[Tuple[str, str]]:
    """
    把 role 序列整理成 (user_text, ai_text) 回合对。
    """
    out: List[Tuple[str, str]] = []
    last_user = ""
    rows = list(messages or [])
    if max_turns > 0 and len(rows) > max_turns * 2:
        rows = rows[-(max_turns * 2):]
    for m in rows:
        role = str((m or {}).get("role") or "").strip().lower()
        content = str((m or {}).get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            last_user = content
            continue
        if role == "ai":
            if last_user:
                out.append((last_user, content))
                last_user = ""
            continue
    return out


def _extract_turn_pair_from_memory_text(full_text: str) -> Tuple[str, str]:
    """
    从长期记忆文本中提取“用户说/AI 回复”对。
    """
    txt = str(full_text or "").replace("\r", "").strip()
    if not txt:
        return ("", "")

    m = re.match(r"^\s*用户说[：:]\s*(.*?)\s*AI\s*回复[：:]\s*([\s\S]*)\s*$", txt, flags=re.I)
    if m:
        return (str(m.group(1) or "").strip(), str(m.group(2) or "").strip())

    m2 = re.match(r"^\s*用户[：:]\s*(.*?)\s*助手[：:]\s*([\s\S]*)\s*$", txt, flags=re.I)
    if m2:
        return (str(m2.group(1) or "").strip(), str(m2.group(2) or "").strip())

    return ("", "")


def _runtime_group_dir(group_id: Any) -> str:
    gid = _safe_id_token(group_id, "unknown_group")
    p = os.path.join(_runtime_groups_root(), gid)
    os.makedirs(p, exist_ok=True)
    return p


def _runtime_group_chat_path(group_id: Any) -> str:
    gid = _safe_id_token(group_id, "unknown_group")
    return os.path.join(_runtime_group_dir(gid), f"group_{gid}.txt")


def _runtime_group_summary_path(group_id: Any) -> str:
    return os.path.join(_runtime_group_dir(group_id), "group_summary.txt")


def _rename_private_chat_context_file(user_id: Any, old_title: Any, new_title: Any) -> Dict[str, Any]:
    uid = _safe_id_token(user_id, "anonymous")
    old_t = _safe_fs_name(old_title, "default")
    new_t = _safe_fs_name(new_title, "default")

    src = _runtime_private_chat_path(uid, old_t)
    dst = _runtime_private_chat_path(uid, new_t)

    out = {
        "ok": True,
        "user_id": uid,
        "old_title": old_t,
        "new_title": new_t,
        "src": src.replace("\\", "/"),
        "dst": dst.replace("\\", "/"),
        "msg": ""
    }

    if os.path.abspath(src) == os.path.abspath(dst):
        out["msg"] = "same_name_skip"
        return out

    os.makedirs(os.path.dirname(dst), exist_ok=True)

    # 旧文件不存在：可能还没产生聊天记录，直接返回成功（让前端体验连续）
    if not os.path.exists(src):
        out["msg"] = "source_not_found_skip"
        return out

    # 目标已存在：做一次合并，避免覆盖丢失
    if os.path.exists(dst):
        try:
            with open(src, "r", encoding="utf-8", errors="ignore") as f:
                src_txt = f.read() or ""
            if src_txt.strip():
                need_sep = False
                try:
                    if os.path.getsize(dst) > 0:
                        need_sep = True
                except Exception:
                    need_sep = True
                with open(dst, "a", encoding="utf-8") as f:
                    if need_sep:
                        f.write("\n")
                    f.write(src_txt)
            os.remove(src)
            out["msg"] = "merged_into_existing"
            return out
        except Exception as e:
            out["ok"] = False
            out["msg"] = f"merge_failed: {e}"
            return out

    try:
        os.replace(src, dst)
        out["msg"] = "renamed"
        return out
    except Exception as e:
        out["ok"] = False
        out["msg"] = f"rename_failed: {e}"
        return out


def _delete_private_chat_context_file(user_id: Any, chat_title: Any) -> Dict[str, Any]:
    uid = _safe_id_token(user_id, "anonymous")
    source_resolved, title = _resolve_private_chat_context_file(uid, chat_title)
    target = _runtime_private_chat_path(uid, title)
    private_root = os.path.abspath(_runtime_private_root())
    user_dir = os.path.abspath(_runtime_private_dir(uid))
    deleted_dir = os.path.abspath(_runtime_private_deleted_dir(uid))
    target_abs = os.path.abspath(target)

    out = {
        "ok": True,
        "user_id": uid,
        "title": title,
        "path": target.replace("\\", "/"),
        "deleted_path": "",
        "msg": ""
    }

    # 防止路径越界
    if not user_dir.startswith(private_root):
        out["ok"] = False
        out["msg"] = "path_outside_private_root"
        return out

    # 兼容兜底：若按新命名规则未命中，尝试旧命名（<title>.txt）
    source_abs = os.path.abspath(source_resolved) if source_resolved else target_abs

    # 目标不存在：视为成功，保证前端连续体验
    if not os.path.exists(source_abs):
        out["msg"] = "source_not_found_skip"
        return out

    if (not source_abs.startswith(user_dir)) or source_abs.startswith(deleted_dir):
        out["ok"] = False
        out["msg"] = "source_outside_user_dir"
        return out

    try:
        base_name = os.path.basename(source_abs)
        dst_abs = os.path.abspath(os.path.join(deleted_dir, base_name))
        if os.path.exists(dst_abs):
            stem, ext = os.path.splitext(base_name)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dst_abs = os.path.abspath(os.path.join(deleted_dir, f"{stem}__deleted_{ts}{ext}"))
        os.replace(source_abs, dst_abs)
        out["deleted_path"] = dst_abs.replace("\\", "/")
        out["msg"] = "moved_to_deleted"
        return out
    except Exception as e:
        out["ok"] = False
        out["msg"] = f"move_to_deleted_failed: {e}"
        return out


# ========= 群聊块解析（适配你的日志块格式）=========
def _tail_nonempty_lines(text: str, n: int) -> list:
    """
    兼容旧调用：返回末尾 n 行非空行（不做块解析）。
    说明：你现在主要用“块解析”的函数；这个函数保留是为了兼容历史/兜底。
    """
    try:
        lines = [ln.rstrip("\n") for ln in (text or "").splitlines() if str(ln).strip()]
        return lines[-n:] if n > 0 else []
    except Exception:
        return []


def _split_blocks(group_ctx_text: str) -> list:
    """
    按 60 个 '-' 分隔成块。每块典型结构：
    ------------------------------------------------------------
    [2026-01-16 23:04:05] [群聊] [group_id=...] [user_id=...] [昵称]
    昵称: 发言...
    （可能有续行）
    AI: 机器人回复...（也可能有续行）
    ------------------------------------------------------------
    """
    try:
        sep = "-" * 60
        raw = (group_ctx_text or "").strip()
        if not raw:
            return []
        parts = [p.strip() for p in raw.split(sep)]
        return [p for p in parts if p]
    except Exception:
        return []


def _parse_block_header(block: str) -> dict:
    """
    从块头的 [] 中解析 group_id / user_id / nickname（尽量稳）。
    返回：{group_id,user_id,nickname,header_line}
    """
    try:
        lines = [ln.strip() for ln in (block or "").splitlines() if ln.strip()]
        if not lines:
            return {"group_id": "", "user_id": "", "nickname": "", "header_line": ""}

        header = lines[0]
        gid = ""
        uid = ""
        nick = ""

        # group_id=xxx / user_id=xxx
        m1 = re.search(r"group_id\s*=\s*([0-9]+)", header)
        if m1:
            gid = m1.group(1).strip()
        m2 = re.search(r"user_id\s*=\s*([0-9]+)", header)
        if m2:
            uid = m2.group(1).strip()

        # 最后一段 [昵称]
        all_brackets = re.findall(r"\[([^\]]+)\]", header)
        if all_brackets:
            last = all_brackets[-1].strip()
            # 排除明显不是昵称的块
            if last and ("group_id" not in last) and ("user_id" not in last) and (":" not in last):
                nick = last

        return {"group_id": gid, "user_id": uid, "nickname": nick, "header_line": header}
    except Exception:
        return {"group_id": "", "user_id": "", "nickname": "", "header_line": ""}


def _extract_speaker_text_from_block(block: str, speaker_nickname: str) -> str:
    """
    从一个块里抽取“某个说话者”的内容（仅该说话者的连续发言行），不会把“AI:”混进去。
    规则：
      - 找到 “{speaker}: ...” 开始
      - 收集该行冒号后的文本
      - 继续收集后续“非 xxx:”开头的续行
      - 碰到别的 “某某:” 开头则停止
    """
    try:
        lines = (block or "").splitlines()
        speaker = (speaker_nickname or "").strip()
        if not speaker:
            return ""

        start_idx = -1
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith(f"{speaker}:"):
                start_idx = i
                break
        if start_idx < 0:
            return ""

        out = []
        first = lines[start_idx].strip()
        out.append(first[len(speaker) + 1 :].lstrip(" ：:").strip())

        for j in range(start_idx + 1, len(lines)):
            s = lines[j].rstrip()
            st = s.strip()
            if not st:
                continue
            # 新说话者开始（形如 “xxx:”）
            if re.match(r"^[^\s：:]{1,20}\s*[：:]", st):
                break
            out.append(st)

        return "\n".join([x for x in out if str(x).strip()]).strip()
    except Exception:
        return ""


def _extract_target_blocks(group_ctx_text: str, target_name: str, target_user_id: str, n_blocks: int = 5) -> list:
    """
    返回目标对象最近 n_blocks 个“块”（按块头 user_id 匹配为主，昵称为辅）。
    """
    try:
        blocks = _split_blocks(group_ctx_text)
        if not blocks:
            return []

        tuid = str(target_user_id or "").strip()
        tname = str(target_name or "").strip()

        matched = []
        for blk in blocks:
            h = _parse_block_header(blk)
            uid = str(h.get("user_id") or "").strip()
            nick = str(h.get("nickname") or "").strip()

            hit = False
            if tuid and uid and tuid == uid:
                hit = True
            elif (not tuid) and tname and nick and tname == nick:
                hit = True

            if hit:
                matched.append(blk)

        if not matched:
            return []

        return matched[-max(1, int(n_blocks or 5)) :]
    except Exception:
        return []


def _extract_target_lines(group_ctx_text: str, target_name: str, target_user_id: str, n: int = 5) -> list:
    """
    参考1：按 target_user_id 精准抓该对象的最近 3~5 个“块”，并只提取“对方”的内容，不混入Agent。
    输出为多条字符串（每条对应一个块内该对象发言内容）。
    """
    try:
        n_blocks = max(1, int(n or 5))
    except Exception:
        n_blocks = 5

    try:
        blocks = _extract_target_blocks(group_ctx_text, target_name, target_user_id, n_blocks=n_blocks)
        if not blocks:
            return []

        out = []
        for blk in blocks:
            h = _parse_block_header(blk)
            nick = str(h.get("nickname") or "").strip() or str(target_name or "").strip()
            if not nick:
                continue
            txt = _extract_speaker_text_from_block(blk, nick)
            if txt:
                out.append(f"{nick}: {txt}".strip())
        return out
    except Exception:
        return []


def _tail_group_blocks_as_lines(group_ctx_text: str, n_blocks: int = 10) -> list:
    """
    参考2：取最近 n_blocks 个块，做“块摘要行”：
      - header + 对方第一行（尽量短）
    """
    try:
        blocks = _split_blocks(group_ctx_text)
        if not blocks:
            return []
        tail = blocks[-max(1, int(n_blocks or 10)) :]

        out = []
        for blk in tail:
            h = _parse_block_header(blk)
            header = str(h.get("header_line") or "").strip()
            nick = str(h.get("nickname") or "").strip()

            # 找到 “昵称:” 那行的内容作为摘要
            first_line = ""
            if nick:
                for ln in blk.splitlines():
                    st = ln.strip()
                    if st.startswith(f"{nick}:"):
                        first_line = st
                        break
            # 摘要 fallback：取第2行
            if not first_line:
                ls = [x.strip() for x in blk.splitlines() if x.strip()]
                if len(ls) >= 2:
                    first_line = ls[1]

            # 再做个长度兜底
            s = " | ".join([x for x in [header, first_line] if x])
            s = (s or "").strip()
            if len(s) > 220:
                s = s[:220].rstrip() + "…"
            if s:
                out.append(s)

        return out[-max(1, int(n_blocks or 10)) :]
    except Exception:
        return []


def _normalize_attachments(v: Any, max_items: int = 6) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    if not isinstance(v, list):
        return out
    for item in v[:max_items]:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("file") or "").strip()
            name = str(item.get("name") or "").strip()
            url = str(item.get("url") or "").strip()
        else:
            path = str(item or "").strip()
            name = ""
            url = ""
        if (not path) and (not url):
            continue
        if not name:
            if path:
                name = os.path.basename(path)
            elif url:
                try:
                    name = os.path.basename((urlparse(url).path or "").strip())
                except Exception:
                    name = ""
            name = name or "attachment"
        out.append({"name": name, "path": path, "url": url})
    return out


def _clean_search_text(value: Any, max_len: int = 260) -> str:
    s = re.sub(r"\s+", " ", str(value or "").strip())
    if max_len > 0 and len(s) > max_len:
        s = s[: max(1, max_len - 1)].rstrip() + "…"
    return s


def _normalize_search_link(raw_link: Any) -> str:
    link = str(raw_link or "").strip()
    if not link:
        return ""
    # trim trailing punctuations copied from sentence context
    while link and re.search(r"[),.;!?，。；！？】〕）》」]$", link):
        link = link[:-1].rstrip()
    if not link:
        return ""
    if link.startswith("//"):
        link = "https:" + link
    elif (not re.match(r"^https?://", link, flags=re.IGNORECASE)) and re.match(r"^www\.", link, flags=re.IGNORECASE):
        link = "https://" + link
    elif not re.match(r"^https?://", link, flags=re.IGNORECASE):
        link = "http://" + link
    try:
        p = urlparse(link)
        host = str(p.netloc or "").lower()
        # DuckDuckGo redirect links usually carry the target in uddg.
        if "duckduckgo.com" in host:
            qs = parse_qs(str(p.query or ""))
            uddg_vals = qs.get("uddg") or []
            if uddg_vals:
                target = unquote(str(uddg_vals[0] or "").strip())
                if target:
                    link = target
    except Exception:
        pass
    return str(link or "").strip()


def _source_label_from_link(link: Any) -> str:
    u = _normalize_search_link(link)
    if not u:
        return "来源"
    host = ""
    try:
        host = str(urlparse(u).netloc or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        return "来源"
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    source_map = {
        "news.google.com": "Google 新闻",
        "google.com": "Google",
        "bing.com": "Bing News",
        "cn.bing.com": "Bing News",
        "toutiao.com": "今日头条",
        "baidu.com": "百度",
        "sina.com.cn": "新浪新闻",
        "163.com": "网易新闻",
        "qq.com": "腾讯新闻",
        "thepaper.cn": "澎湃新闻",
        "bbc.com": "BBC",
        "bbc.co.uk": "BBC",
        "reuters.com": "Reuters",
    }
    if host in source_map:
        return source_map[host]
    for k, v in source_map.items():
        if host.endswith("." + k):
            return v
    return host


def _looks_like_web_lookup_query(text: Any) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return False
    pats = [
        r"上网搜|联网搜|搜索|查一下|查查|新闻|资讯|头条|热点",
        r"web\s*search|search\s+the\s+web|news|latest|headline|headlines|breaking",
    ]
    for p in pats:
        try:
            if re.search(p, s, flags=re.IGNORECASE):
                return True
        except Exception:
            continue
    return False


_GENERIC_NEWS_TITLE_PATTERNS = [
    re.compile(r"^(google|bing|百度|今日头条|新浪|网易).{0,6}(新闻|news)", re.IGNORECASE),
    re.compile(r"搜索.{0,8}(news|新闻)", re.IGNORECASE),
    re.compile(r"百度一下", re.IGNORECASE),
    re.compile(r"首页", re.IGNORECASE),
]


def _is_generic_news_title(title: str) -> bool:
    t = _clean_search_text(title, max_len=120)
    if not t:
        return True
    for p in _GENERIC_NEWS_TITLE_PATTERNS:
        try:
            if p.search(t):
                return True
        except Exception:
            continue
    return False


def _normalize_search_item_row(item: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(item, dict):
        return None
    title = _clean_search_text(item.get("title") or item.get("name") or "", max_len=160)
    link = _normalize_search_link(item.get("url") or item.get("link") or item.get("href") or "")
    snippet = _clean_search_text(
        item.get("snippet")
        or item.get("content")
        or item.get("summary")
        or item.get("description")
        or item.get("text")
        or "",
        max_len=320,
    )
    if (not title) and snippet:
        title = _clean_search_text(snippet, max_len=80)
    if not (title or link or snippet):
        return None
    return {
        "title": title or "Search Result",
        "snippet": snippet,
        "link": link,
    }


def _search_engine_items(query: str, top_k: int = 6) -> List[Dict[str, str]]:
    q = (query or "").strip()
    if not q:
        return []
    k = max(1, min(safe_int(top_k, 6), 10))

    mod_name = f"search_engine_live_{int(time.time() * 1000) % 1000000}"
    m = _load_module_from_path(SEARCH_ENGINE_PATH, mod_name)

    # 优先结构化结果
    if hasattr(m, "_ddg_html_page"):
        items = m._ddg_html_page(q, 0) or []
        out_rows: List[Dict[str, str]] = []
        for row in items[:k]:
            if not isinstance(row, dict):
                continue
            nr = _normalize_search_item_row(row)
            if nr:
                out_rows.append(nr)
        return out_rows[:k]

    text = m.search(q, mode="web", top_k=k)
    lines = [s for s in (text or "").splitlines() if s and not s.strip().startswith("🔎")]
    out: List[Dict[str, str]] = []

    for ln in lines:
        if re.match(r"^\d+\.\s", ln):
            out.append({
                "title": _clean_search_text(re.sub(r"^\d+\.\s", "", ln).strip(), max_len=160),
                "snippet": "",
                "link": "",
            })
        elif ln.strip().startswith("http"):
            if out:
                out[-1]["link"] = _normalize_search_link(ln.strip())
        else:
            if out:
                prev = out[-1].get("snippet", "")
                out[-1]["snippet"] = _clean_search_text((prev + (" " if prev else "") + ln.strip()).strip(), max_len=320)
    rows: List[Dict[str, str]] = []
    for row in out[:k]:
        nr = _normalize_search_item_row(row)
        if nr:
            rows.append(nr)
    return rows[:k]


_WEB_SEARCH_MCP_SKILL_IDS = (
    "mcp_web_search",
    "mcp-web-search",
    "web_search_mcp",
)


def _find_enabled_mcp_web_search_skill_id() -> str:
    """
    Return an enabled MCP web-search skill id if available, otherwise empty string.
    """
    try:
        skills = skills_registry.load_all_skills(force=False)
    except Exception:
        return ""
    # 1) Prefer explicit known ids.
    for sid in _WEB_SEARCH_MCP_SKILL_IDS:
        d = skills.get(sid)
        if d is None:
            continue
        if str(getattr(d, "status", "")).strip().lower() != skills_registry.SKILL_STATUS_NORMAL:
            continue
        if not bool(getattr(d, "enabled", False)):
            continue
        if str(getattr(d, "skill_type", "")).strip().lower() != skills_registry.SKILL_TYPE_MCP:
            continue
        return sid
    # 2) Fallback: locate by target server/tool in any MCP skill.
    for sid, d in skills.items():
        if not sid or d is None:
            continue
        if str(getattr(d, "status", "")).strip().lower() != skills_registry.SKILL_STATUS_NORMAL:
            continue
        if not bool(getattr(d, "enabled", False)):
            continue
        if str(getattr(d, "skill_type", "")).strip().lower() != skills_registry.SKILL_TYPE_MCP:
            continue
        server_name = str(getattr(d, "server_name", "") or "").strip().lower()
        tool_name = str(getattr(d, "tool_name", "") or "").strip().lower()
        if server_name == "mcp_web_search" and tool_name in {"web_search", "search"}:
            return str(sid).strip()
    return ""


def _normalize_web_items_from_mcp(data: Any, max_items: int = 8) -> List[Dict[str, str]]:
    """
    Normalize MCP tool result into TYXT search item rows:
    [{title, snippet, link}]
    """
    rows: List[Dict[str, str]] = []
    answer = ""
    src_list: List[Any] = []
    if isinstance(data, list):
        src_list = list(data)
    elif isinstance(data, dict):
        answer = str(data.get("answer") or "").strip()
        for key in ("results", "items", "result"):
            vv = data.get(key)
            if isinstance(vv, list):
                src_list = vv
                break
        if (not src_list) and isinstance(data.get("data"), dict):
            nested = data.get("data") or {}
            answer = answer or str(nested.get("answer") or "").strip()
            for key in ("results", "items", "result"):
                vv = nested.get(key)
                if isinstance(vv, list):
                    src_list = vv
                    break
    for item in src_list[: max(1, int(max_items or 8))]:
        if not isinstance(item, dict):
            continue
        nr = _normalize_search_item_row(item)
        if nr:
            rows.append(nr)
    if (not rows) and answer:
        rows.append({"title": "Answer", "snippet": _clean_search_text(answer, max_len=320), "link": ""})
    return rows


def _search_engine_items_with_fallback(
    query: str,
    top_k: int = 6,
    meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """
    Web search execution strategy:
    1) If MCP web-search skill is enabled, call MCP first.
    2) If MCP fails or returns empty rows, fallback to built-in search_engine.py logic.
    """
    q = (query or "").strip()
    if not q:
        return []
    k = max(1, min(safe_int(top_k, 6), 10))
    m = meta if isinstance(meta, dict) else {}
    provider = _normalize_web_search_provider(
        m.get("web_search_provider", MODEL_CONFIG.get("web_search_provider", "builtin"))
    )
    mcp_skill_id = _find_enabled_mcp_web_search_skill_id()
    if mcp_skill_id:
        try:
            args = {
                "query": q,
                "max_results": k,
            }
            if provider == "tavily":
                # Prefer richer Tavily search when provider is Tavily.
                args["search_depth"] = "advanced"
                args["include_answer"] = True
            ctx = {
                "user_id": str(m.get("user_id") or "").strip(),
                "channel_type": str(m.get("scene") or m.get("channel_type") or "local").strip(),
                "owner_id": str(m.get("owner_id") or m.get("group_id") or m.get("user_id") or "").strip(),
                "role": str(m.get("role") or "").strip(),
                "meta": {"source": "chat_web_search", "provider": provider},
                "__caps": _build_skill_caps(),
            }
            out = skills_registry.run_skill(mcp_skill_id, args, ctx)
            if isinstance(out, dict) and safe_bool(out.get("ok"), False):
                rows = _normalize_web_items_from_mcp(out.get("data"), max_items=k)
                if rows:
                    print(f"[WEB_SEARCH] via_mcp skill={mcp_skill_id} provider={provider} items={len(rows)}")
                    return rows[:k]
                print(f"[WEB_SEARCH warn] mcp_empty_result skill={mcp_skill_id} provider={provider}, fallback=builtin")
            else:
                err = ""
                if isinstance(out, dict):
                    err = str(out.get("error") or "").strip()
                print(f"[WEB_SEARCH warn] mcp_failed skill={mcp_skill_id} provider={provider} err={err or 'unknown'}, fallback=builtin")
        except Exception as e:
            print(f"[WEB_SEARCH warn] mcp_exception fallback=builtin err={e}")
    else:
        if provider == "tavily":
            print("[WEB_SEARCH warn] provider=tavily but mcp_web_search skill is not enabled; fallback=builtin")
    return _search_engine_items(q, top_k=k)


def _format_search_items_for_prompt(items: List[Dict[str, str]]) -> str:
    if not items:
        return ""
    rows = []
    for i, it in enumerate(items, start=1):
        title = str(it.get("title") or "").strip()
        link = _normalize_search_link(it.get("link"))
        snippet = str(it.get("snippet") or "").strip()
        line = f"{i}. {title or '（无标题）'}"
        if snippet:
            line += f"\n   梗概: {snippet}"
        if link:
            src_site = ""
            try:
                src_site = str(urlparse(link).netloc or "").strip()
            except Exception:
                src_site = ""
            if src_site:
                line += f"\n   来源站点: {src_site}"
        rows.append(line)
    return "\n".join(rows)


def _collect_search_sources(items: List[Dict[str, str]], max_links: int = 6) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    k = max(1, min(safe_int(max_links, 6), 12))
    for it in (items or []):
        if len(out) >= k:
            break
        if not isinstance(it, dict):
            continue
        link = _normalize_search_link(it.get("link"))
        if not link:
            continue
        if (not link) or (link in seen):
            continue
        seen.add(link)
        title = _clean_search_text(it.get("title") or "", max_len=72)
        if not title:
            try:
                title = str(urlparse(link).netloc or "").strip() or "来源"
            except Exception:
                title = "来源"
        out.append({"title": title, "link": link})
    return out


def _collect_search_links(items: List[Dict[str, str]], max_links: int = 6) -> List[str]:
    out: List[str] = []
    for row in _collect_search_sources(items, max_links=max_links):
        link = str(row.get("link") or "").strip()
        if link:
            out.append(link)
    return out


def _format_search_links_for_reply(items: List[Dict[str, str]], max_links: int = 6) -> str:
    sources = _collect_search_sources(items, max_links=max_links)
    if not sources:
        return ""
    rows = ["来源："]
    for i, row in enumerate(sources, start=1):
        title = _clean_search_text(row.get("title") or "来源", max_len=72)
        lk = str(row.get("link") or "").strip()
        if not lk:
            continue
        rows.append(f"{i}. （来源）[{title}]({lk})")
    return "\n".join(rows).strip()


_WEB_ACCESS_DENY_PATTERNS = [
    re.compile(r"无法.{0,8}(获取|访问|连接).{0,8}(实时|网络|新闻|资讯)"),
    re.compile(r"知识库.{0,12}(截止|只到|仅到)"),
    re.compile(r"没有.{0,6}(真正的)?网络搜索能力"),
    re.compile(r"(cannot|can't|unable to).{0,20}(access|fetch|get).{0,12}(real[- ]?time|news|web|internet)", re.IGNORECASE),
    re.compile(r"knowledge.{0,12}(cutoff|up to)", re.IGNORECASE),
]


def _reply_denies_web_access(text: Any) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    for pat in _WEB_ACCESS_DENY_PATTERNS:
        try:
            if pat.search(s):
                return True
        except Exception:
            continue
    return False


def _build_web_digest_for_reply(items: List[Dict[str, str]], max_items: int = 5) -> str:
    rows = _normalize_web_items_from_mcp(items, max_items=max_items)
    if not rows:
        rows = [x for x in (items or []) if isinstance(x, dict)]
    if not rows:
        return ""
    out: List[str] = []
    k = max(1, min(safe_int(max_items, 5), 8))
    for i, it in enumerate(rows[:k], start=1):
        link = _normalize_search_link(it.get("link"))
        source = _source_label_from_link(link)
        title = _clean_search_text(it.get("title") or "", max_len=96)
        snippet = _clean_search_text(it.get("snippet") or "", max_len=120)
        text = title
        # If title is generic portal/navigation text, fallback to snippet.
        if (not text) or _is_generic_news_title(text):
            if snippet:
                text = snippet
        if not text:
            text = "未提取到可展示标题"
        if link:
            out.append(f"{i}. {text}（来源：[{source}]({link})）")
        else:
            out.append(f"{i}. {text}（来源：{source}）")
    return "\n".join(out).strip()


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}

_IMAGE_QUERY_PATTERNS = [
    re.compile(r"(看|分析|描述|识别).{0,10}(图|图片|照片|截图)"),
    re.compile(r"(图里|图中|画面里|画面中)"),
    re.compile(r"(这张图|这个图|这幅图|这图片|这照片)"),
    re.compile(r"(see|analy[sz]e|describe|identify).{0,16}(image|photo|picture|screenshot)", re.IGNORECASE),
    re.compile(r"(in|from)\s+the\s+(image|photo|picture|screenshot)", re.IGNORECASE),
    re.compile(r"(this|the)\s+(image|photo|picture|screenshot)", re.IGNORECASE),
]

_IMAGE_CLAIM_PATTERNS = [
    re.compile(r"我(看到了|看到|看见了|看见).{0,10}(图|图片|照片|画面)"),
    re.compile(r"(图中|图片中|画面中|这张图里|这张图中).{0,80}(是|有|显示|展示)"),
    re.compile(r"(这是一张|这是一个).{0,50}(图|图片|照片)"),
    re.compile(r"(可以看到|能看到).{0,60}(图|图片|画面)"),
    re.compile(r"\bi\s+(can\s+)?(see|saw|have\s+seen).{0,20}(image|photo|picture|screenshot|scene)", re.IGNORECASE),
    re.compile(r"(in|from)\s+the\s+(image|photo|picture|screenshot).{0,120}(is|are|shows?|display|contains?)", re.IGNORECASE),
    re.compile(r"(this|the)\s+is\s+(an?\s+)?(image|photo|picture|screenshot)", re.IGNORECASE),
    re.compile(r"(you|we)\s+can\s+see.{0,80}(image|photo|picture|scene)", re.IGNORECASE),
]

_IMAGE_DISCLAIMER_PATTERNS = [
    re.compile(r"(看不到|无法看到|不能看到).{0,10}(图|图片|照片|画面)"),
    re.compile(r"(无法确认|不能确认|无法判断).{0,20}(图|图片|照片|画面|图中|图里)"),
    re.compile(r"(不能|无法).{0,8}(直接看图|读取图片|识别图片内容)"),
    re.compile(r"(未识别到|没有提取到).{0,20}(图片|图像).{0,10}(内容|文本|信息)"),
    re.compile(r"(can't|cannot|unable to)\s+(see|view).{0,20}(image|photo|picture|screenshot)", re.IGNORECASE),
    re.compile(r"(cannot|can't|unable to)\s+(confirm|determine|verify|judge).{0,30}(image|photo|picture|content|details)", re.IGNORECASE),
    re.compile(r"(cannot|can't|unable to).{0,16}(directly\s+)?(read|parse|recognize|identify).{0,24}(image|photo|picture|content|text)", re.IGNORECASE),
    re.compile(r"(no|not).{0,12}(image|photo|picture).{0,20}(content|text|info|information).{0,12}(detected|extracted|recognized)", re.IGNORECASE),
]

_IMAGE_MEMORY_BLEED_PATTERNS = [
    re.compile(r"core_memory", re.I),
    re.compile(r"\bRAG\b", re.I),
    re.compile(r"向量(召回|记忆|数据库|检索)"),
    re.compile(r"群聊(上下文|总结|记录)"),
    re.compile(r"我(记得|记忆里)"),
    re.compile(r"编号\s*\d+"),
    re.compile(r"vector\s*(recall|memory|database|search|retrieval)", re.I),
    re.compile(r"group\s*(context|summary|record|history|log)", re.I),
    re.compile(r"\bi\s*(remember|recall)\b", re.I),
    re.compile(r"\brecord\s*#?\s*\d+\b", re.I),
]


def _is_image_ref(s: str) -> bool:
    v = str(s or "").strip()
    if not v:
        return False
    v = v.split("?", 1)[0].split("#", 1)[0]
    return os.path.splitext(v)[1].lower() in _IMAGE_EXTS


def _resolve_shared_abs_path(rel_or_name: str) -> Optional[str]:
    try:
        ap = os.path.abspath(os.path.join(ALLOWED_DIR, str(rel_or_name or "").strip()))
        if not ap.startswith(os.path.abspath(ALLOWED_DIR)):
            return None
        return ap
    except Exception:
        return None


def _is_local_or_private_url(url: str) -> bool:
    try:
        u = str(url or "").strip()
        if not u:
            return True
        p = urlparse(u)
        host = str(p.hostname or "").strip().lower()
        if not host:
            return True
        if host in {"localhost", "127.0.0.1", "::1"}:
            return True
        if host.startswith("10.") or host.startswith("192.168.") or host.startswith("169.254."):
            return True
        if host.startswith("172."):
            seg = host.split(".")
            if len(seg) >= 2:
                try:
                    second = int(seg[1])
                    if 16 <= second <= 31:
                        return True
                except Exception:
                    pass
        return False
    except Exception:
        return True


def _image_abs_to_data_url(abs_path: str) -> str:
    try:
        ap = str(abs_path or "").strip()
        if (not ap) or (not os.path.exists(ap)) or (not os.path.isfile(ap)):
            return ""
        max_bytes = safe_int(os.getenv("VISION_IMAGE_MAX_BYTES"), 2 * 1024 * 1024)
        max_edge = max(256, safe_int(os.getenv("VISION_IMAGE_MAX_EDGE"), 1024))
        jpeg_quality = max(45, min(95, safe_int(os.getenv("VISION_IMAGE_JPEG_QUALITY"), 82)))

        with Image.open(ap) as im:
            im.load()
            w, h = im.size
            longest = max(int(w or 0), int(h or 0))
            if longest > max_edge:
                ratio = float(max_edge) / float(longest)
                nw = max(1, int(round(w * ratio)))
                nh = max(1, int(round(h * ratio)))
                im = im.resize((nw, nh), Image.LANCZOS)

            has_alpha = im.mode in {"RGBA", "LA"} or ("transparency" in im.info)
            if has_alpha:
                save_format = "PNG"
                mime = "image/png"
                save_kwargs = {"optimize": True}
            else:
                if im.mode not in {"RGB", "L"}:
                    im = im.convert("RGB")
                save_format = "JPEG"
                mime = "image/jpeg"
                save_kwargs = {"quality": jpeg_quality, "optimize": True, "progressive": True}

            buf = io.BytesIO()
            im.save(buf, format=save_format, **save_kwargs)
            raw = buf.getvalue()

        if max_bytes > 0 and len(raw) > max_bytes:
            return ""
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


def _collect_attachment_image_urls(attachments: List[Dict[str, str]], host_base: str = "", max_items: int = 3) -> List[str]:
    out: List[str] = []
    if not attachments:
        return out

    host = str(host_base or "").strip().rstrip("/")
    payload_mode = str(os.getenv("VISION_PAYLOAD_MODE", "auto") or "auto").strip().lower()
    prefer_url = payload_mode in {"url", "link"}
    prefer_data = payload_mode in {"data", "base64"}

    for a in attachments:
        if len(out) >= max(1, int(max_items or 3)):
            break

        path = str(a.get("path") or "").strip()
        name = str(a.get("name") or "").strip()
        url = str(a.get("url") or "").strip()

        # 仅处理图片附件
        if not (_is_image_ref(url) or _is_image_ref(path) or _is_image_ref(name)):
            continue

        abs_path = _resolve_shared_abs_path(path) if path else None

        # 对外部云 API，localhost/private URL 往往不可访问：默认优先转 data URL 直传
        final_url = ""
        if prefer_url:
            if url:
                final_url = url
        elif prefer_data:
            if abs_path:
                final_url = _image_abs_to_data_url(abs_path)
        else:
            if abs_path and (_is_local_or_private_url(url) or (not url)):
                final_url = _image_abs_to_data_url(abs_path)
            # data URL 不可用时再尝试原 URL（公网可达 URL）
            if (not final_url) and url:
                final_url = url

        # 强制模式失败时，兜底到另一种，避免直接丢图
        if (not final_url) and prefer_url and abs_path:
            final_url = _image_abs_to_data_url(abs_path)
        if (not final_url) and prefer_data and url:
            final_url = url

        # 最后兜底：按已上传文件名拼一个本机 URL（主要给本地调用链）
        if not final_url:
            base = os.path.basename(path) or os.path.basename(name)
            base = secure_filename(base)
            if base and _is_image_ref(base) and host:
                try:
                    final_url = host + url_for("api_uploaded_file", filename=base)
                except Exception:
                    final_url = ""

        if final_url and final_url not in out:
            out.append(final_url)
    return out


def _looks_like_image_query(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    t_lower = t.lower()
    for p in _IMAGE_QUERY_PATTERNS:
        if p.search(t):
            return True
    for kw in [
        "看图", "图片", "照片", "截图", "图里", "图中", "看看这张图", "分析这张图", "描述这张图",
        "image", "photo", "picture", "screenshot", "in the image", "from the image",
        "look at this image", "analyze this image", "describe this image", "identify this image",
    ]:
        kws = str(kw or "")
        if (kws in t) or (kws.lower() in t_lower):
            return True
    return False


def _prefer_english_by_user_text(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    has_en = re.search(r"[A-Za-z]", t) is not None
    has_zh = re.search(r"[\u4e00-\u9fff]", t) is not None
    if has_en and (not has_zh):
        return True
    return re.search(
        r"\b(image|photo|picture|screenshot|describe|analy[sz]e|identify|what|show)\b",
        t,
        flags=re.IGNORECASE,
    ) is not None


def _reply_has_image_disclaimer(reply_text: str) -> bool:
    r = str(reply_text or "").strip()
    if not r:
        return False
    return any(p.search(r) for p in _IMAGE_DISCLAIMER_PATTERNS)


def _reply_claims_image_seen(reply_text: str) -> bool:
    r = str(reply_text or "").strip()
    if not r:
        return False
    if _reply_has_image_disclaimer(r):
        return False
    return any(p.search(r) for p in _IMAGE_CLAIM_PATTERNS)


def _reply_likely_memory_bleed_on_image(reply_text: str) -> bool:
    r = str(reply_text or "").strip()
    if not r:
        return False
    return any(p.search(r) for p in _IMAGE_MEMORY_BLEED_PATTERNS)


def _enforce_image_honesty_guard(
    user_text: str,
    reply_text: str,
    has_image_attachment: bool,
    has_reliable_image_evidence: bool,
) -> str:
    reply = str(reply_text or "").strip()
    if not has_image_attachment:
        return reply
    if has_reliable_image_evidence:
        return reply
    if not _looks_like_image_query(user_text):
        return reply
    if (not reply) or reply.startswith("❌"):
        return reply
    if _reply_has_image_disclaimer(reply):
        return reply
    if _reply_claims_image_seen(reply) or len(reply) >= 6:
        if _prefer_english_by_user_text(user_text):
            return (
                "I can't directly confirm the exact content of this image right now. "
                "This attachment did not provide sufficiently reliable visual evidence, "
                "so I should not guess and risk misleading you. "
                "Please upload a clearer image or tell me which details to focus on."
            )
        return (
            "我目前无法直接确认这张图片的具体内容。"
            "这次附件没有提供足够可靠的图像信息，"
            "为避免误导我不能瞎猜。你可以上传更清晰图片，"
            "或补充你想让我重点识别的细节。"
        )
    return reply


def _build_attachment_context_detail(
    attachments: List[Dict[str, str]],
    max_files: int = 3,
    include_image_ocr: bool = True,
    include_image_hint: bool = False,
) -> Dict[str, Any]:
    info = {
        "context": "",
        "has_image": False,
        "has_reliable_image_evidence": False,
    }
    if not attachments:
        return info

    blocks: List[str] = []
    for i, a in enumerate(attachments[:max_files], start=1):
        path = str(a.get("path") or "").strip()
        url = str(a.get("url") or "").strip()
        name = str(a.get("name") or os.path.basename(path) or os.path.basename((urlparse(url).path or "").strip()) or f"attachment_{i}").strip()

        is_image = _is_image_ref(path) or _is_image_ref(name) or _is_image_ref(url)
        if is_image:
            info["has_image"] = True
            if not include_image_ocr:
                if include_image_hint:
                    blocks.append(f"[附件{i}] {name}（图片）\n（已通过多模态视觉输入提供给模型，已跳过 OCR 文本提取）")
                continue

            if not path:
                blocks.append(f"[附件{i}] {name}（图片OCR）\n⚠ 无本地路径，无法执行 OCR。")
                continue
            ap = _resolve_shared_abs_path(path)
            if (not ap) or (not os.path.exists(ap)):
                blocks.append(f"[Attachment {i}] {name} (Image OCR)\n❌ Image file does not exist or is outside the shared directory.")
                continue

            try:
                raw = str(_read_ocr(ap, max_chars=5000) or "").strip()
            except Exception as e:
                raw = f"❌ OCR read failed: {e}"

            compact = re.sub(r"\s+", "", raw)
            if raw and (not raw.startswith("❌")) and len(compact) >= 8:
                info["has_reliable_image_evidence"] = True
                if len(raw) > 2200:
                    raw = raw[:2200].rstrip() + "..."
                blocks.append(f"[附件{i}] {name}（图片OCR）\n{raw}")
            else:
                if raw.startswith("❌"):
                    blocks.append(f"[附件{i}] {name}（图片OCR）\n{raw}")
                else:
                    blocks.append(f"[附件{i}] {name}（图片OCR）\n（未识别到可靠文字证据，不能据此确认画面细节）")
            continue

        if not path:
            continue

        try:
            txt = read_file_auto(path)
            txt = (txt or "").strip()
            if not txt:
                continue
            if len(txt) > 2200:
                txt = txt[:2200].rstrip() + "..."
            blocks.append(f"[附件{i}] {name}\n{txt}")
        except Exception:
            continue

    info["context"] = "\n\n".join(blocks).strip()
    return info


def _build_attachment_context(attachments: List[Dict[str, str]], max_files: int = 3) -> str:
    return str(_build_attachment_context_detail(attachments, max_files=max_files).get("context") or "")


# ========= 简易聊天接口（/chat）默认非流式，兼容第三方桥接客户端 =========
@app.route("/chat", methods=["POST"])
def chat_post():
    try:
        data = request.get_json(force=True, silent=True) or {}
        ctx_user_id, ctx_role, ctx_nickname = get_current_user_ctx(data)

        # 兼容桥接端: { "message": "...", "meta": {...} }
        upstream_meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        # 兼容其他上游：把常见字段也合并进 meta
        group_id = data.get("group_id") or data.get("groupId") or upstream_meta.get("group_id") or upstream_meta.get("groupId") or ""
        payload_user_id = data.get("user_id") or data.get("userId") or data.get("qq") or upstream_meta.get("user_id") or upstream_meta.get("userId") or ""
        payload_nickname = data.get("nickname") or data.get("name") or upstream_meta.get("sender_name") or upstream_meta.get("nickname") or ""
        user_id = str(ctx_user_id or payload_user_id or "").strip()
        nickname = _clean_display_name(ctx_nickname or payload_nickname or "")

        # 你 bridge 里用的是 sender_name（你截图里就是这个字段）
        sender_name = (
            data.get("sender_name") or data.get("nickname") or data.get("name")
            or upstream_meta.get("sender_name") or upstream_meta.get("nickname") or upstream_meta.get("name")
            or ""
        )

        # 如果上游传了 sender 对象，也吃掉
        sender = upstream_meta.get("sender") or data.get("sender") or {}
        if isinstance(sender, dict):
            sender_name = sender_name or sender.get("card") or sender.get("nickname") or sender.get("name") or ""
        sender_name = _clean_display_name(sender_name)
        if not nickname:
            nickname = sender_name
        if not sender_name:
            sender_name = nickname
        if not nickname:
            nickname = str(user_id or "").strip()
        if not sender_name:
            sender_name = str(user_id or "").strip()

        # 前端工具开关/附件透传
        _raw_mode = upstream_meta.get("web_search_mode", data.get("web_search_mode"))
        if _raw_mode is None or str(_raw_mode).strip() == "":
            web_search_enabled_legacy = safe_bool(
                upstream_meta.get("web_search_enabled", data.get("web_search_enabled", MODEL_CONFIG.get("web_search_enabled", False))),
                default=False
            )
            web_search_mode = "default" if web_search_enabled_legacy else "off"
        else:
            web_search_mode = _normalize_web_search_mode(_raw_mode)
        web_search_enabled = bool(web_search_mode != "off")
        web_search_provider = _normalize_web_search_provider(
            upstream_meta.get(
                "web_search_provider",
                data.get("web_search_provider", MODEL_CONFIG.get("web_search_provider", "builtin")),
            )
        )
        file_tools_enabled = safe_bool(
            upstream_meta.get("file_tools_enabled", data.get("file_tools_enabled", True)),
            default=True
        )
        attachments = _normalize_attachments(
            upstream_meta.get("attachments") if isinstance(upstream_meta.get("attachments"), list) else data.get("attachments")
        )
        web_top_k = safe_int(upstream_meta.get("web_top_k", data.get("web_top_k")), 6)

        # scene：优先用上游 meta 的明确值
        scene = upstream_meta.get("scene") or ("group" if str(group_id).strip() else "private")
        user_id = _canonicalize_chat_user_id(user_id, scene=scene, group_id=group_id)

        meta = {
            **(upstream_meta if isinstance(upstream_meta, dict) else {}),
            "scene": str(scene).strip(),
            "group_id": str(group_id).strip(),
            "user_id": str(user_id or "anonymous").strip(),
            "role": "admin" if str(ctx_role).strip().lower() == "admin" else "user",
            "sender_name": str(sender_name).strip() or str(user_id or "anonymous"),
            "nickname": str(nickname).strip() or str(sender_name).strip() or str(user_id or "anonymous"),
            "web_search_enabled": web_search_enabled,
            "web_search_mode": web_search_mode,
            "web_search_provider": web_search_provider,
            "file_tools_enabled": file_tools_enabled,
            "attachments": attachments,
            "web_top_k": max(1, min(web_top_k, 10)),
        }
        try:
            _ch, _owner = resolve_channel_owner(meta)
            meta["channel_type"] = _ch
            meta["owner_id"] = _owner
        except Exception:
            pass
        meta["profile_user_id"] = _profile_user_id_for_ctx(
            meta.get("user_id"),
            scene=meta.get("scene"),
            group_id=meta.get("group_id"),
        )

        # 当前系统时间（请求级，实时）
        try:
            _now_info = _current_system_time_info()
            meta["system_time"] = _now_info.get("local_dt", "")
            meta["system_timezone"] = (
                f"{_now_info.get('tz_name', '')} (UTC{_now_info.get('utc_offset', '')})"
                if _now_info.get("utc_offset")
                else _now_info.get("tz_name", "")
            )
        except Exception:
            pass

        try:
            print(
                f"[chat] user_id={meta.get('user_id', 'anonymous')} "
                f"role={meta.get('role', 'user')} scene={meta.get('scene', '')} "
                f"group_id={meta.get('group_id', '')}"
            )
        except Exception:
            pass

        # 兼容多种入参：message / prompt / input / content
        user_input = (data.get("message") or data.get("prompt") or data.get("input") or data.get("content") or "").strip()
        # 某些桥接端在编码异常时会把文本变成一串 ?，这里尽量从备用字段回捞一次。
        if _looks_placeholder_text(user_input):
            backup_candidates = [
                data.get("text"),
                data.get("query"),
                upstream_meta.get("message"),
                upstream_meta.get("content"),
                upstream_meta.get("text"),
            ]
            msgs = data.get("messages")
            if isinstance(msgs, list):
                for m in reversed(msgs):
                    if not isinstance(m, dict):
                        continue
                    if str(m.get("role") or "").strip().lower() != "user":
                        continue
                    c = m.get("content") or m.get("text") or ""
                    if isinstance(c, str):
                        backup_candidates.append(c)
                    elif isinstance(c, list):
                        parts = []
                        for it in c:
                            if isinstance(it, dict):
                                parts.append(str(it.get("text") or "").strip())
                            else:
                                parts.append(str(it).strip())
                        backup_candidates.append(" ".join([x for x in parts if x]))
                    else:
                        backup_candidates.append(str(c))
                    break
            for cand in backup_candidates:
                cand_s = str(cand or "").strip()
                if cand_s and (not _looks_placeholder_text(cand_s)):
                    user_input = cand_s
                    break
        if not user_input:
            return jsonify({"reply": "❌ Empty input"}), 400

        # ====== 静音控制（按群指令差异）======
        now_ts = time.time()
        mk = _mute_key(meta)

        cmd = user_input.strip()
        cmd_norm = str(cmd or "").strip().casefold()
        gid = str(meta.get("group_id") or "").strip()
        scene_str = str(meta.get("scene") or "").strip()

        group_b = str(globals().get("PROFILE_B_GROUP_ID") or PROFILE_B_GROUP_ID).strip()
        is_group_b = (scene_str == "group" and gid == group_b)

        # 指定群：闭嘴/说话
        if is_group_b:
            mute_on  = {"请闭嘴", MUTE_CMD_ON_TOKEN}
            mute_off = {"请说话", MUTE_CMD_OFF_TOKEN}
            off_hint = "请说话"
        else:
            mute_on  = {"快闭嘴", MUTE_CMD_ON_TOKEN}
            mute_off = {"快说话", MUTE_CMD_OFF_TOKEN}
            off_hint = "快说话"

        mute_on_norm = {str(x or "").strip().casefold() for x in mute_on if str(x or "").strip()}
        mute_off_norm = {str(x or "").strip().casefold() for x in mute_off if str(x or "").strip()}
        off_hint_show = f"{off_hint} / {MUTE_CMD_OFF_TOKEN}"

        if cmd_norm in mute_on_norm:
            MUTE_UNTIL[mk] = now_ts + 600  # 10分钟
            try:
                save_chat(user_input, "好的，我会安静十分钟。", meta=meta)
            except Exception:
                pass
            return jsonify({"reply": f"好的，我会安静十分钟。（发送“{off_hint_show}”解除）"}), 200

        if cmd_norm in mute_off_norm:
            MUTE_UNTIL[mk] = 0
            try:
                save_chat(user_input, "好的，我回来了。", meta=meta)
            except Exception:
                pass
            return jsonify({"reply": "好的，我回来了。"}), 200

        until = float(MUTE_UNTIL.get(mk, 0) or 0)
        if now_ts < until:
            # 静音期间：群聊保持沉默；私聊给提示
            if str(meta.get("scene") or "").strip() == "private":
                left = int(max(0, until - now_ts))
                return jsonify({"reply": f"（我在静音中，还剩 {left} 秒。发送“快说话 / {MUTE_CMD_OFF_TOKEN}”解除。）"}), 200
            return jsonify({"reply": ""}), 200

        # ====== 共享目录自然语言读写（命中即短路，不再走模型）======
        if bool(meta.get("file_tools_enabled", True)):
            handled, io_reply = try_handle_shared_io(user_input, allow_write=True)
            if handled:
                try:
                    save_chat(user_input, io_reply, meta=meta)
                except Exception:
                    pass
                return jsonify({"reply": io_reply}), 200

        # ====== 临时上下文注入：私聊ctx + 群临时ctx（按你指定来源）=====
        context_turn_limit = _get_context_turn_limit()

        # 私聊临时聊天数据：当前策略关闭（避免把私聊临时上下文注入模型）
        private_ctx = ""

        # 群临时聊天数据：按统一规则选择来源群（默认本群）
        group_ctx = ""
        try:
            src_gid = _ctx_group_id_for_prompt(meta)
            if src_gid:
                group_ctx = tail_blocks(_runtime_group_chat_path(src_gid), n=context_turn_limit)
        except Exception:
            group_ctx = ""

        # ====== 向量检索（RAG）======
        # 当前策略：仅群聊触发 RAG；私聊不调取 RAG（避免私聊上下文干扰）
        mem_txt = ""
        triggered = False
        try:
            is_group_scene = (str(scene).strip().lower() == "group")
            triggered = trigger_memory_check(user_input) if is_group_scene else False
            topk = (MEM_TOPK if triggered else MEM_LIGHT_TOPK) if is_group_scene else 0
            if topk > 0:
                focus_keywords = _memory_focus_keywords(user_input) if triggered else []
                memory_queries = focus_keywords if focus_keywords else (
                    _memory_query_candidates(user_input) if triggered else [str(user_input or "").strip()]
                )
                if not memory_queries:
                    memory_queries = [str(user_input or "").strip()]

                empty = True
                last_error = ""
                try:
                    if triggered:
                        print(f"[RAG] focus_keywords={focus_keywords} queries={memory_queries}")
                except Exception:
                    pass
                for mq in memory_queries:
                    res = vector_search(mq, top_k=topk, meta=meta)
                    if isinstance(res, dict) and res.get("error"):
                        last_error = str(res.get("error") or "")
                        continue
                    if focus_keywords:
                        res = _payload_filter_by_keywords(res, focus_keywords)
                    mem_try, empty_try = format_memories(res)
                    if not empty_try and str(mem_try).strip():
                        mem_txt = mem_try
                        empty = False
                        break
                    empty = bool(empty_try)

                if triggered and empty:
                    # 仅在显式触发回忆时暴露检索异常提示；平时保持静默，避免干扰对话。
                    if last_error:
                        mem_txt = f"【记忆检索提示】{last_error}"
                    else:
                        mem_txt = "（无匹配记忆）"
        except Exception:
            mem_txt = ""
        try:
            print(f"[RAG] triggered={str(triggered).lower()} mem_len={len(str(mem_txt or ''))}")
        except Exception:
            pass

        # ====== 网页搜索（由前端开关 + 查询意图共同控制）======
        web_items: List[Dict[str, str]] = []
        web_mode = _normalize_web_search_mode(meta.get("web_search_mode", "off"))
        web_feature_enabled = bool(web_mode != "off")
        wants_web_lookup = _looks_like_web_lookup_query(user_input)
        if wants_web_lookup and (not web_feature_enabled):
            disabled_reply = "目前上网搜索功能没有开启。请先在设置里打开“上网搜索”后再试。"
            try:
                save_chat(user_input, disabled_reply, meta=meta)
            except Exception:
                pass
            return jsonify({"reply": disabled_reply}), 200
        should_web_lookup = bool(web_mode == "force" or (web_mode == "default" and wants_web_lookup))
        if should_web_lookup:
            try:
                web_items = _search_engine_items_with_fallback(
                    user_input,
                    top_k=safe_int(meta.get("web_top_k"), 6),
                    meta=meta,
                )
            except Exception as e:
                print("[WEB_SEARCH warn]", e)
                web_items = []

        # ====== 前端附件（共享目录内图片/文档）======
        attachments_ctx = ""
        has_image_attachment = False
        has_reliable_image_evidence = False
        ocr_reliable = False
        ocr_enabled_for_images = True
        image_urls_for_vision: List[str] = []

        provider_now = str(LLM_PROVIDER or "").strip().lower()
        try:
            image_urls_for_vision = _collect_attachment_image_urls(
                meta.get("attachments") or [],
                host_base=request.host_url
            )
            use_newapi_vision = bool(image_urls_for_vision) and provider_now == "newapi"
            skip_ocr_when_multimodal = safe_bool(os.getenv("VISION_SKIP_OCR_WHEN_MULTIMODAL", "1"), True)
            ocr_enabled_for_images = not (use_newapi_vision and skip_ocr_when_multimodal)

            att_detail = _build_attachment_context_detail(
                meta.get("attachments") or [],
                include_image_ocr=ocr_enabled_for_images,
                include_image_hint=use_newapi_vision,
            )
            attachments_ctx = str(att_detail.get("context") or "")
            has_image_attachment = bool(att_detail.get("has_image"))
            ocr_reliable = bool(att_detail.get("has_reliable_image_evidence"))
            has_reliable_image_evidence = bool(ocr_reliable)
        except Exception:
            attachments_ctx = ""
            has_image_attachment = False
            has_reliable_image_evidence = False
            ocr_reliable = False
            ocr_enabled_for_images = True
            image_urls_for_vision = []
            use_newapi_vision = False

        if use_newapi_vision:
            # 真实图片作为视觉输入时，视为有可靠图像证据（不依赖 OCR）
            has_reliable_image_evidence = True
        if has_image_attachment:
            try:
                img_payload_kind = []
                for u in image_urls_for_vision[:3]:
                    su = str(u or "")
                    if su.startswith("data:image/"):
                        img_payload_kind.append("data")
                    elif su.startswith("http://") or su.startswith("https://"):
                        img_payload_kind.append("url")
                    else:
                        img_payload_kind.append("other")
                print(
                    f"[Vision] provider={provider_now} has_image={has_image_attachment} "
                    f"payload_count={len(image_urls_for_vision)} payload_kind={img_payload_kind} "
                    f"multimodal={use_newapi_vision} ocr_enabled={ocr_enabled_for_images} "
                    f"ocr_reliable={ocr_reliable} evidence_reliable={has_reliable_image_evidence}"
                )
            except Exception:
                pass

        image_focus_mode = bool(has_image_attachment and _looks_like_image_query(user_input))
        isolate_image_context = bool(
            image_focus_mode and safe_bool(os.getenv("VISION_ISOLATE_CONTEXT", "0"), False)
        )
        if isolate_image_context:
            # 可选隔离模式（默认关闭）：仅在明确开启时屏蔽上下文注入
            mem_txt = ""
            web_items = []
            meta["_used_memory_ids"] = []

        # ====== 人格来源（仅 UI 人格设置）======
        ui_persona_cfg = _load_persona_config()
        ui_persona_txt = str(ui_persona_cfg.get("content") or "").strip()
        # ====== 聊天对象（群聊优先 target_user_id）======
        target_user_id = str(meta.get("target_user_id") or "").strip()
        target_name = str(meta.get("target_name") or "").strip()
        target_is_peach = bool(meta.get("target_is_peach", False))
        profile_target_uid = ""
        if str(scene).strip().lower() == "group":
            profile_target_uid = str(
                target_user_id
                or meta.get("profile_user_id")
                or meta.get("user_id")
                or ""
            ).strip()
        else:
            profile_target_uid = str(
                meta.get("profile_user_id")
                or meta.get("user_id")
                or ""
            ).strip()
        user_ctx_segments = build_user_context_segments(profile_target_uid)
        user_ctx_blocks_for_prompt = _build_related_user_context_blocks(
            meta=meta,
            user_text=user_input,
            primary_user_id=profile_target_uid,
            max_users=4,
        )

        # ====== 群聊参考区拆分（参考1/2/3）======

        ref1_n = max(1, int(context_turn_limit))
        ref2_n = max(1, int(context_turn_limit))
        ref1_lines = _extract_target_lines(group_ctx, target_name, target_user_id, n=ref1_n) if (str(scene).strip() == "group" and (not isolate_image_context)) else []
        ref2_lines = _tail_group_blocks_as_lines(group_ctx, ref2_n) if (str(scene).strip() == "group" and (not isolate_image_context)) else []

        ref_block_1 = f"【参考1：本次需要回复的对象近期发言（最多{ref1_n}块/条）】\n" + ("\n\n".join(ref1_lines) if ref1_lines else "（未匹配到该对象的近期发言：可能 target_user_id/日志格式不一致）")
        ref_block_2 = f"【参考2：群聊近期上下文（最多{ref2_n}块摘要）】\n" + ("\n\n".join(ref2_lines) if ref2_lines else "（无）")
        ref_block_3 = "【参考3：RAG 向量召回（仅供参考，避免张冠李戴）】\n" + ((mem_txt or "").strip() if (mem_txt or "").strip() else "（无）")

        # ====== 构建 system prompt（UI 人格 + 对象确认 + 参考区）======
        sys_lines = []

        if ui_persona_txt:
            sys_lines.append("【UI人格设定】\n" + ui_persona_txt)
        for b in user_ctx_blocks_for_prompt:
            if str(b or "").strip():
                sys_lines.append(str(b).strip())

        # 实时系统时间感知
        sys_lines.append(_build_system_time_block())

        # 对象确认硬规则（防止把群友误认为用户）
        sys_lines.append(
            "\n".join([
                "【对象确认（强制）】群聊回复前必须确认“要回复的对象是谁”。只对 target_user_id 对应的人讲话。",
                f"【对象】{target_name or target_user_id or '未知'}（user_id={target_user_id or ''}，group_id={gid or ''}）",
                f"【对象】target_is_peach={str(bool(target_is_peach)).lower()}",
                "【对象确认（强制）】严禁把其他群成员误认为用户；若 target_is_peach=false，不要用用户专属称呼/关系口吻。",
            ])
        )

        # 输出简洁约束（软约束，硬控在桥接侧）
        try:
            hard_limit = int(os.getenv("MODEL_REPLY_HARD_LIMIT", "200"))
        except Exception:
            hard_limit = 200
        sys_lines.append(
            "\n".join([
                f"【输出约束】默认回复控制在 {max(80, min(600, hard_limit))} 字以内；除非对方明确要求长文/详细步骤/展开分析。",
                "【输出约束】表达尽量简洁，不复读参考区原文，不要长篇大论。",
            ])
        )

        if has_image_attachment:
            sys_lines.append(
                "【图片真实性规则（强制）】"
                "只有在确实看到了图片输入或可验证证据时，才能描述图像内容。"
                "看不清/不确定时必须明确说“无法确认”，禁止脑补和编造细节。"
            )
            if (not has_reliable_image_evidence) and (not use_newapi_vision):
                sys_lines.append(
                    "【本次图片证据状态】检测到图片附件，但当前没有可靠图像证据。"
                    "若用户要求看图，请直接说明“无法确认图片内容”，不要猜。"
                )

        if str(meta.get("group_id") or "").strip():
            sys_lines.append(f"【场景】群聊 group_id={str(meta.get('group_id')).strip()}")
        else:
            sys_lines.append("【场景】私聊")

        if sender_name:
            sys_lines.append(f"【对方昵称】{sender_name}")

        if private_ctx and (not isolate_image_context):
            sys_lines.append("【私聊临时聊天数据】\n" + private_ctx)

        if isolate_image_context:
            sys_lines.append(
                "【图像优先（强制）】本轮是看图任务。"
                "请优先依据图片本身回答，不要引用 RAG、群聊上下文、长期记忆或网页搜索内容。"
            )

        if attachments_ctx:
            sys_lines.append("【附件内容（共享目录）】\n" + attachments_ctx)

        if web_items and (not isolate_image_context):
            web_txt = _format_search_items_for_prompt(web_items)
            if web_txt:
                sys_lines.append(
                    "【联网结果使用要求】\n"
                    "已提供本轮网页搜索结果。请基于这些结果回答，不要再说“无法联网/知识截止无法获取实时信息”。\n"
                    "输出以“标题或简短梗概”为主；每条后可附格式：`（来源）[标题](链接)`。\n"
                    "不要在正文末尾再单独输出“来源：”链接列表。"
                )
                sys_lines.append("【网页搜索结果（供参考）】\n" + web_txt)

        if str(scene).strip() == "group":
            if not isolate_image_context:
                sys_lines.append(ref_block_1)
                sys_lines.append(ref_block_2)
                sys_lines.append(ref_block_3)
        else:
            if mem_txt and (not isolate_image_context):
                sys_lines.append("【RAG向量数据】\n" + mem_txt)

        system_prompt = "\n\n".join([x for x in sys_lines if str(x).strip()])

        user_message_content: Any = user_input
        if use_newapi_vision:
            parts: List[Dict[str, Any]] = [{"type": "text", "text": user_input}]
            for u in image_urls_for_vision[:3]:
                if str(u or "").strip():
                    parts.append({"type": "image_url", "image_url": {"url": str(u).strip()}})
            if len(parts) > 1:
                user_message_content = parts

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content},
        ]

        # ====== 调用模型 ======
        # ✅ 群聊统一延迟 2~3 秒：给上游/上下文一个稳定缓冲（私聊不延迟）
        if str(meta.get("scene") or "").strip() == "group":
            try:
                import random as _random
                time.sleep(2.0 + _random.random() * 1.0)
            except Exception:
                pass

        reply = call_model(messages)
        reply = (reply or "").strip()
        if not reply:
            # 避免桥接因空 reply 直接不发：私聊给提示，群聊给最短兜底
            if str(meta.get("scene") or "").strip() == "private":
                reply = "（我这次生成了空回复。你可以再发一次，或发“请说话”确认没有静音。）"
            else:
                reply = "（模型返回空回复）"

        call_meta = _get_last_call_meta()
        reliable_image_for_guard = bool(has_reliable_image_evidence)
        try:
            if has_image_attachment and call_meta.get("fallback_used") and str(call_meta.get("final_provider") or "").strip().lower() == "ollama":
                reliable_image_for_guard = False
        except Exception:
            pass

        # 图片场景下：若无可靠图像证据，强制防止“看图瞎编”
        reply = _enforce_image_honesty_guard(
            user_text=user_input,
            reply_text=reply,
            has_image_attachment=has_image_attachment,
            has_reliable_image_evidence=reliable_image_for_guard,
        )

        if isolate_image_context and _reply_likely_memory_bleed_on_image(reply):
            reply = (
                "我这次没有稳定对齐到图片内容，回答被历史记忆上下文干扰了。"
                "请再发一次“只描述这张图”，我会仅基于图片回答，不引用历史记录。"
            )

        if web_items and _reply_denies_web_access(reply):
            digest = _build_web_digest_for_reply(
                web_items,
                max_items=safe_int(meta.get("web_top_k"), 6),
            )
            if digest:
                reply = digest

        # 标注：本次是否由 Ollama 回退完成
        reply_source = ""
        reply_note = ""
        try:
            cm = call_meta if isinstance(call_meta, dict) else _get_last_call_meta()
            if cm.get("fallback_used") and str(cm.get("final_provider") or "").strip().lower() == "ollama":
                reply_source = "ollama_fallback"
                if bool(cm.get("has_image_payload")):
                    reply_note = "本次回复由 Ollama 本地模型完成（NEW API 限流回退；未直接读取图片像素）"
                else:
                    reply_note = "本次回复由 Ollama 本地模型完成（NEW API 限流回退）"
        except Exception:
            pass

        # ====== 回复后慢任务（记忆判定/落盘/画像更新）======
        # NapCat 场景优先“先回消息”，慢任务后台执行，减少 QQ 端体感延迟。
        memory_meta = {
            "strip_added": False,
            "profile_updated": False,
        }
        defer_housekeeping = bool(
            DEFER_POST_REPLY_TASKS_FOR_NAPCAT
            and str(meta.get("upstream") or "").strip().lower() == "napcat_bridge"
        )
        if defer_housekeeping:
            try:
                threading.Thread(
                    target=_post_reply_housekeeping_bg,
                    kwargs={
                        "user_input": user_input,
                        "reply": reply,
                        "meta": dict(meta or {}),
                        "user_ctx_segments": dict(user_ctx_segments or {}),
                    },
                    daemon=True,
                ).start()
            except Exception as e:
                print(f"[post_reply_housekeeping defer warn] {e}")
                memory_meta = _post_reply_housekeeping(
                    user_input=user_input,
                    reply=reply,
                    meta=meta,
                    user_ctx_segments=user_ctx_segments,
                )
        else:
            memory_meta = _post_reply_housekeeping(
                user_input=user_input,
                reply=reply,
                meta=meta,
                user_ctx_segments=user_ctx_segments,
            )
        return jsonify({
            "reply": reply,
            "reply_source": reply_source,
            "reply_note": reply_note,
            "meta": {
                "memory": memory_meta,
            },
        }), 200

    except Exception as e:
        try:
            print(f"❌ /chat error: {e}")
        except Exception:
            pass
        return jsonify({"reply": "❌ Internal server error"}), 500

# ============================================================
# 15. 运行时上下文拼接：build_runtime_context_blocks
#   - 统一策略（不再区分 Profile A/B）
#   - 私聊：private_ctx +（可选）all_group_summaries
#   - 群聊：group_ctx(默认本群，可由 TYXT_CTX_GROUP_PROMPT_MAP 覆盖) + group_sum
#   - 群聊 summary 文件格式：group_summary_<gid>.txt（按 60 个'-'分块）
# ============================================================
def tail_blocks(path: str, n: int = 20, max_chars: int = 180000) -> str:
    try:
        if not path or (not os.path.exists(path)):
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read() or ""
        if not raw.strip():
            return ""
        blocks = [x.strip() for x in re.split(r"\n-{20,}\n", raw) if str(x or "").strip()]
        if not blocks:
            return ""
        if n > 0:
            blocks = blocks[-int(n):]
        out = ("\n" + "-" * 60 + "\n").join(blocks).strip()
        if len(out) > max_chars:
            out = out[-max_chars:]
        return out
    except Exception:
        return ""


def build_runtime_context_blocks(meta: dict) -> dict:
    """
    返回要注入的上下文块（字符串字典），统一注入策略：
    - 私聊：chat_private（按 user_id + 聊天窗口隔离）+ all_group_summaries
    - 群聊：group_ctx（默认本群）+ group_sum（本群总结）
    """
    meta = meta or {}
    scene = str(meta.get("scene") or "").strip().lower()
    gid = str(meta.get("group_id") or "").strip()

    groups_dir  = _runtime_groups_root()

    # 控制条数（由参数设置里的 context_turn_limit 驱动）
    PRIVATE_N = _get_context_turn_limit()
    GROUP_N   = _get_context_turn_limit()
    SUM_N     = 20

    uid = str(meta.get("user_id") or "").strip() or "anonymous"
    chat_title = _chat_title_from_meta(meta)

    # 私聊上下文（按 user_id + 聊天窗口名隔离）
    private_ctx = ""
    if scene != "group":
        private_ctx = tail_blocks(_runtime_private_chat_path(uid, chat_title), PRIVATE_N)

    # 群聊上下文：统一由来源群规则函数决定（默认本群）
    group_ctx = ""
    src_gid = _ctx_group_id_for_prompt(meta)
    if src_gid:
        group_ctx = tail_blocks(_runtime_group_chat_path(src_gid), GROUP_N)
        if not group_ctx:
            group_ctx = tail_blocks(os.path.join(groups_dir, f"group_{src_gid}.txt"), GROUP_N)

    # 本群 summary（如果有，优先新结构）
    group_sum = ""
    if gid:
        group_sum = tail_blocks(_runtime_group_summary_path(gid), SUM_N)
        if not group_sum:
            group_sum = tail_blocks(os.path.join(groups_dir, f"group_summary_{gid}.txt"), SUM_N)

    # 私聊时“所有群 summary”（如果未来你要）
    all_group_summaries = ""
    if scene != "group":
        try:
            import glob
            summary_paths = []
            summary_paths.extend(glob.glob(os.path.join(groups_dir, "*", "group_summary.txt")))
            summary_paths.extend(glob.glob(os.path.join(groups_dir, "group_summary_*.txt")))
            summary_paths = sorted(
                list(dict.fromkeys(summary_paths)),
                key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
                reverse=True
            )

            chunks = []
            for pth in summary_paths:
                base = os.path.basename(pth).strip().lower()
                if base == "group_summary.txt":
                    gid2 = os.path.basename(os.path.dirname(pth))
                else:
                    gid2 = os.path.basename(pth).replace("group_summary_", "").replace(".txt", "").strip()
                s = tail_blocks(pth, SUM_N)
                if s:
                    chunks.append(f"【群聊总结（最近{SUM_N}条 group_id={gid2}）】\n{s}")

            if chunks:
                all_group_summaries = "\n".join(chunks).strip()
        except Exception:
            all_group_summaries = ""

    # 私聊：拼 private + 所有群 summary
    if scene != "group":
        return {
            "private_ctx": private_ctx or "",
            "group_ctx": "",
            "group_sum": "",
            "all_group_summaries": all_group_summaries or ""
        }

    # 群聊：统一只拼群聊上下文和群总结（不拼 private）
    return {
        "private_ctx": "",
        "group_ctx": group_ctx or "",
        "group_sum": group_sum or "",
        "all_group_summaries": ""
    }

# ============================================================
# 16. 模型调用统一入口：call_model（newapi / ollama，流式/非流式）
# ============================================================
def call_model(messages, stream=False, max_tokens=None, temperature=None, top_p=None, top_k=None, provider_override=None):
    
    #统一模型调用入口：
    # LLM_PROVIDER=newapi: 调用 NEW API（OpenAI 兼容 /v1/chat/completions）
    # LLM_PROVIDER=ollama: 保留你原有 Ollama /api/chat 逻辑（完整兜底）
    # 注意：NEWAPI_BASE_URL 建议以 .../v1 结尾；否则这里会少一层 /v1  

    provider = (provider_override or LLM_PROVIDER or "newapi").strip().lower()

    # ==== 参数解析（优先使用传入的，其次用 MODEL_CONFIG，最后用默认值）====
    num_predict = int(max_tokens if max_tokens is not None else MODEL_CONFIG.get("max_tokens", GEN_MAX_TOKENS))
    temp_val    = float(temperature if temperature is not None else MODEL_CONFIG.get("temperature", GEN_TEMP))
    top_p_val   = float(top_p if top_p is not None else MODEL_CONFIG.get("top_p", GEN_TOP_P))
    top_k_val   = int(top_k if top_k is not None else MODEL_CONFIG.get("top_k", GEN_TOP_K))
    _set_last_call_meta({
        "primary_provider": provider,
        "final_provider": provider,
        "fallback_used": False,
        "fallback_reason": "",
        "has_image_payload": False,
    })

    def _flatten_msg_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for it in content:
                if isinstance(it, dict):
                    tp = str(it.get("type") or "").strip().lower()
                    if tp == "text":
                        txt = str(it.get("text") or "").strip()
                        if txt:
                            parts.append(txt)
                    elif tp == "image_url":
                        iu = it.get("image_url")
                        if isinstance(iu, dict):
                            u = str(iu.get("url") or "").strip()
                        else:
                            u = str(iu or "").strip()
                        if u:
                            parts.append(f"[图片附件] {u}")
                    else:
                        txt = str(it.get("text") or it.get("content") or "").strip()
                        if txt:
                            parts.append(txt)
                else:
                    txt = str(it or "").strip()
                    if txt:
                        parts.append(txt)
            return "\n".join(parts).strip()
        return str(content or "").strip()

    def _messages_have_image_payload(msgs: Any) -> bool:
        if not isinstance(msgs, list):
            return False
        for m in msgs:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            if not isinstance(c, list):
                continue
            for part in c:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type") or "").strip().lower() == "image_url":
                    return True
        return False

    def _normalize_messages_for_text_model(msgs: Any) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        if not isinstance(msgs, list):
            return out
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "user").strip() or "user"
            out.append({
                "role": role,
                "content": _flatten_msg_content(m.get("content"))
            })
        return out

    def _messages_to_responses_input(msgs: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not isinstance(msgs, list):
            return out
        for m in msgs:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "user").strip() or "user"
            content = m.get("content")
            parts: List[Dict[str, Any]] = []
            if isinstance(content, str):
                txt = content.strip()
                if txt:
                    parts.append({"type": "input_text", "text": txt})
            elif isinstance(content, list):
                for it in content:
                    if not isinstance(it, dict):
                        txt = str(it or "").strip()
                        if txt:
                            parts.append({"type": "input_text", "text": txt})
                        continue
                    tp = str(it.get("type") or "").strip().lower()
                    if tp == "text":
                        txt = str(it.get("text") or "").strip()
                        if txt:
                            parts.append({"type": "input_text", "text": txt})
                    elif tp == "image_url":
                        iu = it.get("image_url")
                        if isinstance(iu, dict):
                            u = str(iu.get("url") or "").strip()
                        else:
                            u = str(iu or "").strip()
                        if u:
                            parts.append({"type": "input_image", "image_url": u})
                    else:
                        txt = str(it.get("text") or it.get("content") or "").strip()
                        if txt:
                            parts.append({"type": "input_text", "text": txt})
            else:
                txt = str(content or "").strip()
                if txt:
                    parts.append({"type": "input_text", "text": txt})

            if parts:
                out.append({"role": role, "content": parts})
        return out

    def _responses_output_text(data: Dict[str, Any]) -> str:
        try:
            t = str((data or {}).get("output_text") or "").strip()
            if t:
                return t
        except Exception:
            pass

        chunks: List[str] = []
        try:
            outputs = (data or {}).get("output") or []
            if isinstance(outputs, list):
                for o in outputs:
                    if not isinstance(o, dict):
                        continue
                    c_list = o.get("content") or []
                    if not isinstance(c_list, list):
                        continue
                    for c in c_list:
                        if not isinstance(c, dict):
                            continue
                        tp = str(c.get("type") or "").strip().lower()
                        if tp in {"output_text", "text"}:
                            txt = str(c.get("text") or "").strip()
                            if txt:
                                chunks.append(txt)
        except Exception:
            pass
        return "".join(chunks).strip()

    def _http_status_from_exc(e) -> int:
        try:
            return int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
        except Exception:
            return 0

    def _exc_response_text(e) -> str:
        try:
            return str(getattr(getattr(e, "response", None), "text", "") or "")
        except Exception:
            return ""

    def _compact_newapi_error(e, max_len: int = 220) -> str:
        code = _http_status_from_exc(e)
        base_msg = str(e or "").strip()
        body = _exc_response_text(e).strip()
        picked = ""

        if body:
            low = body.lower()
            if "<html" in low:
                if code == 524 or "error code 524" in low:
                    picked = "Upstream gateway timeout (Cloudflare 524)"
                elif code:
                    picked = f"Upstream returned an HTML error page (HTTP {code})"
                else:
                    picked = "Upstream returned an HTML error page"
            else:
                try:
                    jd = json.loads(body)
                    if isinstance(jd, dict):
                        err = jd.get("error")
                        if isinstance(err, dict):
                            picked = str(err.get("message") or err.get("code") or "").strip()
                        else:
                            picked = str(err or jd.get("message") or "").strip()
                except Exception:
                    picked = ""
                if not picked:
                    picked = body

        msg = picked or base_msg or "Unknown error"
        msg = re.sub(r"\s+", " ", str(msg)).strip()
        if len(msg) > max_len:
            msg = msg[:max_len].rstrip() + "..."
        if code and f"{code}" not in msg:
            return f"HTTP {code}: {msg}"
        return msg

    def _is_newapi_rate_limited(e) -> bool:
        code = _http_status_from_exc(e)
        if code == 429:
            return True
        txt = _exc_response_text(e).lower()
        if not txt:
            return False
        return ("429" in txt and "rate" in txt) or ("rate limit" in txt) or ("rate_limit" in txt)

    def _is_newapi_vision_unsupported(e) -> bool:
        txt = _exc_response_text(e).lower()
        if not txt:
            return False
        return (
            ("image" in txt and ("unsupported" in txt or "not support" in txt or "not supported" in txt))
            or ("vision" in txt and ("unsupported" in txt or "not support" in txt or "not supported" in txt))
            or ("multimodal" in txt and ("unsupported" in txt or "not support" in txt))
        )

    def _is_newapi_transient_network_error(e) -> bool:
        if isinstance(e, requests.exceptions.Timeout):
            return True
        code = _http_status_from_exc(e)
        if code in {408, 500, 502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 530}:
            return True
        transient_types = (
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            requests.exceptions.ProxyError,
            requests.exceptions.SSLError,
        )
        if isinstance(e, transient_types):
            return True
        msg = str(e or "").strip().lower()
        if not msg:
            return False
        keys = [
            "connection aborted",
            "connection reset",
            "reset by peer",
            "winerror 10054",
            "远程主机强迫关闭了一个现有的连接",
            "remote end closed connection",
            "eof occurred",
        ]
        return any(k in msg for k in keys)

    def _newapi_post_with_retry(
        req_url: str,
        headers: Dict[str, str],
        payload_obj: Dict[str, Any],
        timeout_val: Any,
        stream_mode: bool = False,
    ):
        tries = max(1, int(NEWAPI_RETRY_TIMES))
        last_err = None
        for i in range(tries):
            try:
                return requests.post(
                    req_url,
                    headers=headers,
                    json=payload_obj,
                    timeout=timeout_val,
                    stream=bool(stream_mode),
                )
            except Exception as e:
                last_err = e
                if (not _is_newapi_transient_network_error(e)) or (i + 1 >= tries):
                    raise
                wait_s = float(NEWAPI_RETRY_BACKOFF_S) * float(i + 1)
                try:
                    print(f"[NEWAPI retry] {i + 1}/{tries} transient network error: {e}")
                except Exception:
                    pass
                if wait_s > 0:
                    time.sleep(wait_s)
        if last_err is not None:
            raise last_err
        raise RuntimeError("newapi post failed without exception")

    has_image_payload = _messages_have_image_payload(messages)
    text_only_messages = _normalize_messages_for_text_model(messages)
    responses_input_messages = _messages_to_responses_input(messages)
    _set_last_call_meta({
        "primary_provider": provider,
        "final_provider": provider,
        "fallback_used": False,
        "fallback_reason": "",
        "has_image_payload": bool(has_image_payload),
    })

    def _build_ollama_fallback_messages(src_messages: Any, image_payload: bool) -> List[Dict[str, str]]:
        msgs = _normalize_messages_for_text_model(src_messages)
        if not image_payload:
            return msgs
        guard = (
            "【图片可见性限制（强制）】本次请求原本包含图片，但你当前运行在纯文本回退通道，"
            "无法直接读取图片像素。禁止编造图中细节；若用户让你看图，必须明确说明你现在无法直接看图。"
        )
        merged = False
        for m in msgs:
            if str(m.get("role") or "").strip() == "system":
                m["content"] = ((m.get("content") or "").strip() + "\n\n" + guard).strip()
                merged = True
                break
        if not merged:
            msgs.insert(0, {"role": "system", "content": guard})
        return msgs

    # ===================== 分支 1：NEW API（OpenAI 兼容） =====================
    if provider == "newapi":
        if not NEWAPI_API_KEY:
            return "❌ NEW API key is empty: please set NEWAPI_API_KEY"

        url = NEWAPI_BASE_URL.rstrip("/") + "/chat/completions"
        responses_url = NEWAPI_BASE_URL.rstrip("/") + "/responses"
        headers = {
            "Authorization": f"Bearer {NEWAPI_API_KEY}",
            "Content-Type": "application/json",
        }

        def _try_newapi_responses_nonstream() -> Tuple[bool, str]:
            # 某些第三方网关在 chat/completions 下会忽略 image_url，多模态需走 /responses
            try:
                use_responses = safe_bool(os.getenv("NEWAPI_VISION_USE_RESPONSES", "1"), True)
            except Exception:
                use_responses = True
            if not (use_responses and has_image_payload):
                return False, ""
            if not responses_input_messages:
                return False, ""

            rp = {
                "model": NEWAPI_MODEL,
                "input": responses_input_messages,
                "temperature": temp_val,
                "top_p": top_p_val,
                "max_output_tokens": num_predict,
            }
            try:
                rr = _newapi_post_with_retry(
                    responses_url,
                    headers=headers,
                    payload_obj=rp,
                    timeout_val=MAX_REQUEST_SECONDS,
                    stream_mode=False,
                )
                rr.raise_for_status()
                jd = rr.json() or {}
                txt = _responses_output_text(jd)
                _set_last_call_meta({
                    "primary_provider": "newapi",
                    "final_provider": "newapi",
                    "fallback_used": False,
                    "fallback_reason": "",
                    "has_image_payload": bool(has_image_payload),
                    "vision_api": "responses",
                })
                try:
                    print("[Vision API] using /responses for multimodal request")
                except Exception:
                    pass
                return True, txt
            except Exception as e:
                try:
                    print(f"[Vision API warn] /responses failed, fallback /chat/completions: {e}")
                except Exception:
                    pass
                return False, ""

        payload = {
            "model": NEWAPI_MODEL,
            "messages": messages,
            "temperature": temp_val,
            "top_p": top_p_val,
            "max_tokens": num_predict,
        }

        # ---- 流式：按 SSE 解析 data: {...} ----
        if stream:
            def _gen():
                got_any = False
                try:
                    with _newapi_post_with_retry(
                        url,
                        headers=headers,
                        payload_obj={**payload, "stream": True},
                        timeout_val=(8, min(int(MAX_REQUEST_SECONDS), int(NEWAPI_STREAM_READ_TIMEOUT_S))),
                        stream_mode=True,
                    ) as r:
                        r.raise_for_status()
                        for raw in r.iter_lines(chunk_size=8192, decode_unicode=False):
                            if not raw:
                                continue
                            line = raw.decode("utf-8", "ignore").strip()
                            if not line:
                                continue
                            if line.startswith("data:"):
                                line = line[5:].strip()
                            if line == "[DONE]":
                                break
                            try:
                                obj = json.loads(line)
                            except Exception:
                                continue

                            # OpenAI-like: choices[0].delta.content
                            choices = obj.get("choices") or []
                            if choices:
                                delta = (choices[0].get("delta") or {}).get("content")
                                if delta:
                                    got_any = True
                                    yield str(delta)

                except Exception as e:
                    if _is_newapi_rate_limited(e):
                        if has_image_payload:
                            yield "❌ NEW API rate-limited for an image request. Auto fallback to text-only model was blocked to avoid hallucinations. Please try again later."
                            return
                        # NEWAPI 限流：自动切到本地 Ollama
                        try:
                            fb = call_model(
                                messages,
                                stream=True,
                                max_tokens=num_predict,
                                temperature=temp_val,
                                top_p=top_p_val,
                                top_k=top_k_val,
                                provider_override="ollama",
                            )
                            if isinstance(fb, str):
                                if fb:
                                    got_any = True
                                    yield fb
                            else:
                                for chunk in fb:
                                    s = str(chunk or "")
                                    if s:
                                        got_any = True
                                        yield s
                            return
                        except Exception as e2:
                            yield f"❌ NEW API rate-limited, and Ollama fallback failed: {e2}"
                    elif _is_newapi_transient_network_error(e):
                        # NEWAPI 网络抖动（如 WinError 10054）：自动切本地 Ollama 兜底
                        try:
                            fb_messages = _build_ollama_fallback_messages(messages, has_image_payload)
                            fb = call_model(
                                fb_messages,
                                stream=True,
                                max_tokens=num_predict,
                                temperature=temp_val,
                                top_p=top_p_val,
                                top_k=top_k_val,
                                provider_override="ollama",
                            )
                            if isinstance(fb, str):
                                if fb:
                                    got_any = True
                                    yield fb
                            else:
                                for chunk in fb:
                                    s = str(chunk or "")
                                    if s:
                                        got_any = True
                                        yield s
                            return
                        except Exception as e2:
                            yield f"❌ NEW API network error, and Ollama fallback failed: {e2}"
                    else:
                        if has_image_payload and _is_newapi_vision_unsupported(e):
                            yield "❌ The current NEW API/model does not support image input. Please switch to a vision-capable model."
                            return
                        yield f"❌ NEW API streaming call failed: {_compact_newapi_error(e)}"

                # 如果流式没拿到任何内容，自动兜底到非流式
                if not got_any:
                    try:
                        used_resp, txt_resp = _try_newapi_responses_nonstream()
                        if used_resp:
                            yield txt_resp if txt_resp else "(Sorry, I could not respond properly just now. Please provide more detail.)"
                            return
                        r = _newapi_post_with_retry(
                            url,
                            headers=headers,
                            payload_obj={**payload, "stream": False},
                            timeout_val=MAX_REQUEST_SECONDS,
                            stream_mode=False,
                        )
                        r.raise_for_status()
                        data = r.json()
                        raw_txt = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
                        txt = _flatten_msg_content(raw_txt).strip()
                        yield txt if txt else "(Sorry, I could not respond properly just now. Please provide more detail.)"
                    except Exception as e:
                        if _is_newapi_rate_limited(e):
                            if has_image_payload:
                                yield "❌ NEW API rate-limited for an image request. Auto fallback to text-only model was blocked to avoid hallucinations. Please try again later."
                                return
                            try:
                                fb2 = call_model(
                                    messages,
                                    stream=False,
                                    max_tokens=num_predict,
                                    temperature=temp_val,
                                    top_p=top_p_val,
                                    top_k=top_k_val,
                                    provider_override="ollama",
                                )
                                yield str(fb2 or "(NEW API rate-limited, and Ollama returned no content)")
                            except Exception as e2:
                                yield f"❌ NEW API rate-limited, and Ollama fallback failed: {e2}"
                        elif _is_newapi_transient_network_error(e):
                            try:
                                fb_messages = _build_ollama_fallback_messages(messages, has_image_payload)
                                fb2 = call_model(
                                    fb_messages,
                                    stream=False,
                                    max_tokens=num_predict,
                                    temperature=temp_val,
                                    top_p=top_p_val,
                                    top_k=top_k_val,
                                    provider_override="ollama",
                                )
                                yield str(fb2 or "(NEW API network error, and Ollama returned no content)")
                            except Exception as e2:
                                yield f"❌ NEW API network error, and Ollama fallback failed: {e2}"
                        else:
                            if has_image_payload and _is_newapi_vision_unsupported(e):
                                yield "❌ The current NEW API/model does not support image input. Please switch to a vision-capable model."
                                return
                            yield f"❌ NEW API fallback failed: {e}"

            return _gen()

        # ---- 非流式 ----
        try:
            used_resp, txt_resp = _try_newapi_responses_nonstream()
            if used_resp:
                return txt_resp if txt_resp else "(Sorry, I could not respond properly just now. Please provide more detail.)"
            r = _newapi_post_with_retry(
                url,
                headers=headers,
                payload_obj=payload,
                timeout_val=MAX_REQUEST_SECONDS,
                stream_mode=False,
            )
            r.raise_for_status()
            data = r.json()
            raw_reply = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
            reply = _flatten_msg_content(raw_reply).strip()
            return reply if reply else "(Sorry, I could not respond properly just now. Please provide more detail.)"
        except Exception as e:
            if _is_newapi_rate_limited(e):
                try:
                    fb_messages = _build_ollama_fallback_messages(messages, has_image_payload)
                    fb = call_model(
                        fb_messages,
                        stream=False,
                        max_tokens=num_predict,
                        temperature=temp_val,
                        top_p=top_p_val,
                        top_k=top_k_val,
                        provider_override="ollama",
                    )
                    _set_last_call_meta({
                        "primary_provider": "newapi",
                        "final_provider": "ollama",
                        "fallback_used": True,
                        "fallback_reason": "newapi_rate_limited",
                        "has_image_payload": bool(has_image_payload),
                    })
                    try:
                        print(f"[LLM Fallback] newapi -> ollama reason=rate_limited has_image={bool(has_image_payload)}")
                    except Exception:
                        pass
                    return str(fb or "(NEW API rate-limited, and Ollama returned no content)")
                except Exception as e2:
                    return f"❌ NEW API rate-limited, and Ollama fallback failed: {e2}"
            if _is_newapi_transient_network_error(e):
                try:
                    fb_messages = _build_ollama_fallback_messages(messages, has_image_payload)
                    fb = call_model(
                        fb_messages,
                        stream=False,
                        max_tokens=num_predict,
                        temperature=temp_val,
                        top_p=top_p_val,
                        top_k=top_k_val,
                        provider_override="ollama",
                    )
                    _set_last_call_meta({
                        "primary_provider": "newapi",
                        "final_provider": "ollama",
                        "fallback_used": True,
                        "fallback_reason": "newapi_network_error",
                        "has_image_payload": bool(has_image_payload),
                    })
                    try:
                        print(f"[LLM Fallback] newapi -> ollama reason=network_error has_image={bool(has_image_payload)}")
                    except Exception:
                        pass
                    return str(fb or "(NEW API network error, and Ollama returned no content)")
                except Exception as e2:
                    return f"❌ NEW API network error, and Ollama fallback failed: {e2}"
            if has_image_payload and _is_newapi_vision_unsupported(e):
                return "❌ The current NEW API/model does not support image input. Please switch to a vision-capable model."
            return f"❌ NEW API call failed: {_compact_newapi_error(e)}"

    # ===================== 分支 2：Ollama（原逻辑完整保留） =====================
    base = OLLAMA_BASE_URL.rstrip("/").replace("/v1", "")
    chat_url = f"{base}/api/chat"
    gen_url  = f"{base}/api/generate"

    def _gen_fallback_with_generate(msgs):
        sys_txt = "\n".join([_flatten_msg_content(m.get("content")) for m in msgs if m.get("role")=="system"]).strip()
        usr_txt = "\n".join([_flatten_msg_content(m.get("content")) for m in msgs if m.get("role")=="user"]).strip()
        prompt  = (sys_txt+"\n\n" if sys_txt else "") + usr_txt
        try:
            r = requests.post(gen_url, json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "keep_alive": "10m",
                "options": {
                    "temperature": temp_val,
                    "top_p": top_p_val,
                    "top_k": top_k_val,
                    "num_predict": num_predict
                }
            }, timeout=MAX_REQUEST_SECONDS)
            r.raise_for_status()
            data = r.json()
            text = (data.get("response") or "").strip()
            return text if text else "(Sorry, I could not respond properly just now. Please provide more detail.)"
        except Exception as e:
            return f"❌ Fallback failed: {e}"

    payload = {
        "model": MODEL_NAME,
        "messages": text_only_messages,
        "stream": bool(stream),
        "keep_alive": "10m",
        "options": {
            "temperature": temp_val,
            "top_p": top_p_val,
            "top_k": top_k_val,
            "num_predict": num_predict
        }
    }

    if stream:
        def _gen():
            got = False
            try:
                with requests.post(chat_url, json=payload, stream=True, timeout=(8, MAX_REQUEST_SECONDS)) as r:
                    r.raise_for_status()
                    for raw in r.iter_lines(chunk_size=8192, decode_unicode=False):
                        if not raw:
                            continue
                        if raw.startswith(b"data:"):
                            raw = raw[5:].lstrip()
                            if not raw:
                                continue
                        try:
                            line = raw.decode("utf-8", "ignore").strip()
                            if not line:
                                continue
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if obj.get("done"):
                            break
                        chunk = obj.get("delta") or ((obj.get("message") or {}).get("content")) or obj.get("response") or ""
                        if chunk:
                            got = True
                            yield chunk
            except Exception as e:
                yield f"❌ Streaming call failed: {e}"

            if not got:
                try:
                    r = requests.post(chat_url, json={**payload, "stream": False}, timeout=MAX_REQUEST_SECONDS)
                    r.raise_for_status()
                    data = r.json()
                    txt = ((data.get("message") or {}).get("content") or data.get("response") or "").strip()
                    if not txt:
                        txt = _gen_fallback_with_generate(text_only_messages)
                    yield txt
                except Exception:
                    yield _gen_fallback_with_generate(text_only_messages)
        return _gen()

    try:
        r = requests.post(chat_url, json=payload, timeout=MAX_REQUEST_SECONDS)
        r.raise_for_status()
        data = r.json()
        reply = (data.get("message") or {}).get("content", "") or data.get("response", "") or ""
        reply = reply.strip()
        if reply:
            return reply
        return _gen_fallback_with_generate(text_only_messages)
    except requests.exceptions.Timeout:
        return "❌ Model call timed out"
    except requests.exceptions.ConnectionError:
        return "❌ Cannot connect to Ollama service (please run: ollama serve)"
    except Exception as e:
        return f"❌ Model call failed: {e}"

# ============================================================
# 17. 共享区工具：read_file_auto / OCR / 表格 / PDF
#    - 仅用于共享目录 I/O
#    - 不参与 prompt 拼接
#    - 不写入向量库
# ============================================================
def _read_text(p, max_chars=200000):
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        s = f.read()
    return s[:max_chars]

def _read_docx(p, max_chars=200000):
    txt = "\n".join(x.text for x in docx.Document(p).paragraphs if x.text.strip())
    return txt[:max_chars]

def _read_pdf(p, max_chars=200000):
    out = []
    with fitz.open(p) as pdf:
        for page in pdf:
            out.append(page.get_text())
            # 防止超大 PDF 一口气读爆
            if sum(len(x) for x in out) > max_chars:
                break
    txt = "\n".join(out)
    return txt[:max_chars]

def _read_table(p, max_chars=200000):
    p_low = p.lower()
    try:
        if p_low.endswith((".xls", ".xlsx")):
            df = pd.read_excel(p)
        else:
            # 尽量稳：不同 pandas 版本参数略有差异，用 try 兜底
            try:
                df = pd.read_csv(p, encoding="utf-8", encoding_errors="ignore", engine="python")
            except Exception:
                df = pd.read_csv(p, encoding="utf-8", errors="ignore", engine="python")
        txt = df.to_string(index=False)
        return txt[:max_chars]
    except Exception as e:
        # 兜底：直接当文本读
        try:
            return _read_text(p, max_chars=max_chars)
        except Exception:
            raise e

def _read_ocr(p, max_chars=200000):
    # OCR 统一走 multimodal_tools，保留原有返回风格（文本/错误字符串）
    try:
        txt = multimodal_tools.ocr_image(str(p or ""))
    except Exception as e:
        print(f"[OCR wrapper error] {e}")
        txt = f"❌ OCR failed: {e}"
    txt = str(txt or "")
    return txt[:max_chars]

def read_file_auto(rel_or_name: str) -> str:
    # 统一安全Path: 只能读 ALLOWED_DIR 里的内容
    abs_path = os.path.abspath(os.path.join(ALLOWED_DIR, rel_or_name))
    if not abs_path.startswith(os.path.abspath(ALLOWED_DIR)):
        return "❌ Access denied."
    if not os.path.exists(abs_path):
        return f"❌ File not found: {rel_or_name}"

    ext = os.path.splitext(abs_path)[1].lower()
    try:
        if ext in [".txt", ".md", ".json", ".log", ".py"]:
            content = _read_text(abs_path)
        elif ext == ".docx":
            content = _read_docx(abs_path)
        elif ext == ".pdf":
            content = _read_pdf(abs_path)
        elif ext in [".csv", ".xls", ".xlsx"]:
            content = _read_table(abs_path)
        elif ext in [".png", ".jpg", ".jpeg", ".bmp", ".tiff"]:
            content = _read_ocr(abs_path)
        else:
            return f"⚠ Unsupported file: {ext}"
    except Exception as e:
        return f"❌ Read failed: {e}"

    preview = content[:2000] + ("..." if len(content) > 2000 else "")
    return f"📄 已读取 {os.path.basename(abs_path)}，共 {len(content)} 字符（已限长）。\n\n{preview}"


# ============================================================
# 18. 聊天落盘（私聊/群聊分流 + 每群一个文件）
#   - 私聊：runtime_logs/private/<user_id>/<user_id>_<chat_title>.txt
#   - 群聊：runtime_logs/groups/<group_id>/group_<group_id>.txt
# ============================================================
def _now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def _scene_label(meta: dict) -> str:
    scene = (meta or {}).get("scene") or (meta or {}).get("message_type") or ""
    scene = str(scene).strip().lower()
    if scene == "group":
        return "群聊"
    if scene == "private":
        return "私聊"
    return "未知场景"

def _is_placeholder_name(name: Any) -> bool:
    t = str(name or "").strip()
    if not t:
        return True
    if re.fullmatch(r"[?？]+", t):
        return True
    if t.lower() in {"unknown", "none", "null", "n/a", "na"}:
        return True
    if t in {"未知", "匿名"}:
        return True
    return False

def _clean_display_name(name: Any) -> str:
    t = str(name or "").strip()
    if _is_placeholder_name(t):
        return ""
    return t

def _looks_placeholder_text(text: Any) -> bool:
    t = str(text or "").strip()
    if not t:
        return True
    return bool(re.fullmatch(r"[?？\s]+", t))

def _pick_display_name(meta: dict) -> str:
    meta = meta or {}
    # 优先：显式 nickname / sender_name / card
    name = _clean_display_name(meta.get("nickname") or meta.get("sender_name") or meta.get("card") or "")
    if name:
        return name
    # 其次：sender dict
    sender = meta.get("sender") or {}
    if isinstance(sender, dict):
        name = _clean_display_name(sender.get("card") or sender.get("nickname") or sender.get("name") or "")
        if name:
            return name
    uid = str(meta.get("user_id") or "").strip()
    if uid:
        return uid
    return "unknown"

def _pick_assistant_name(meta: dict) -> str:
    """
    不写死模型名字：允许不同群不同马甲
    优先级：meta.assistant_name / meta.bot_name / meta.self_name
    兜底：环境变量 ASSISTANT_NAME（没有就用“管家”）
    """
    meta = meta or {}
    name = (meta.get("assistant_name") or meta.get("bot_name") or meta.get("self_name") or "").strip()
    if name:
        return name
    return str(os.getenv("ASSISTANT_NAME", "管家")).strip() or "管家"

def save_chat(user_text: str, assistant_text: str, meta=None):
    """
    统一写入：
    - runtime_logs/private/<user_id>/<user_id>_<chat_title>.txt（私聊）
    - runtime_logs/groups/<group_id>/group_<group_id>.txt（群聊：用于 prompt 注入）
    """
    try:
        meta = meta or {}
        os.makedirs(ALLOWED_DIR, exist_ok=True)

        _runtime_logs_dir()

        ts = _now_str()
        scene = _scene_label(meta)
        group_id = str(meta.get("group_id") or "").strip()
        user_id  = str(meta.get("user_id")  or "").strip() or "anonymous"
        chat_title = _chat_title_from_meta(meta)
        who = _pick_display_name(meta)
        bot = _pick_assistant_name(meta)

        head_parts = [f"[{ts}]", f"[{scene}]"]
        if group_id:
            head_parts.append(f"[group_id={group_id}]")
        if user_id:
            head_parts.append(f"[user_id={user_id}]")
        head_parts.append(f"[{who}]")
        header = " ".join(head_parts)

        block = (
            f"{header}\n"
            f"{who}: {str(user_text).strip()}\n"
            f"{bot}: {str(assistant_text).strip()}\n"
            f"{'-'*60}\n"
        )
        # 私聊临时上下文固定用 "AI" 标签，避免受人格/马甲名变化影响
        private_block = (
            f"{header}\n"
            f"{who}: {str(user_text).strip()}\n"
            f"AI: {str(assistant_text).strip()}\n"
            f"{'-'*60}\n"
        )

        # 1) 私聊：按 user_id 分目录
        if str(meta.get("scene") or "").strip().lower() == "private":
            p = _runtime_private_chat_path(user_id, chat_title)
            with open(p, "a", encoding="utf-8") as f:
                f.write(private_block)

        # 2) 群聊：按 group_id 分目录
        if str(meta.get("scene") or "").strip().lower() == "group" and group_id:
            g = _runtime_group_chat_path(group_id)
            with open(g, "a", encoding="utf-8") as f:
                f.write(block)

        # 3) 在线长期记忆：JSONL + 多租户向量库（查重 + 命中强化）
        try:
            _persist_online_memory(user_text, assistant_text, meta)
        except Exception as e:
            try:
                print(f"[online_mem] persist failed: {e}")
            except Exception:
                pass

    except Exception:
        pass


# ============================================================
# 19. 共享区写文件工具（append/overwrite + 文件索引/模糊查找）
#   说明：这里只负责“共享目录文件操作”，不包含聊天落盘工具，避免重复定义覆盖
# ============================================================

def _safe_abs(rel: str):
    #把相对路径转为安全的绝对路径（限制在 ALLOWED_DIR 内）
    ap = os.path.abspath(os.path.join(ALLOWED_DIR, rel))
    if not ap.startswith(os.path.abspath(ALLOWED_DIR)):
        return None
    return ap

def append_file(rel: str, content: str) -> str:
   #向共享目录里的文件追加内容（如果文件不存在会新建）
    ap = _safe_abs(rel)
    if not ap:
        return "❌ Access denied."
    try:
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        with open(ap, "a", encoding="utf-8") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        _ensure_index(force=True)
        return f"✅ 已追加到 {rel}。"
    except Exception as e:
        return f"❌ Write failed: {e}"

def overwrite_file(rel: str, content: str) -> str:
   #覆盖写入共享目录里的文件（如果文件不存在会新建）
    ap = _safe_abs(rel)
    if not ap:
        return "❌ Access denied."
    try:
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        with open(ap, "w", encoding="utf-8") as f:
            f.write(content)
        _ensure_index(force=True)
        return f"✅ 已覆盖写入 {rel}。"
    except Exception as e:
        return f"❌ Write failed: {e}"

# ========= 共享区模糊检索（支持刷新+宽松匹配） =========
_FILE_INDEX = []
_FILE_INDEX_BUILT = False

def _ensure_index(force: bool = False):
    #建立或刷新共享目录文件索引
    global _FILE_INDEX, _FILE_INDEX_BUILT
    if _FILE_INDEX_BUILT and not force:
        return
    _FILE_INDEX = []
    for root, _, files in os.walk(ALLOWED_DIR):
        for fn in files:
            rel = os.path.relpath(os.path.join(root, fn), ALLOWED_DIR)
            _FILE_INDEX.append((fn.lower(), rel.replace("\\", "/")))
    _FILE_INDEX_BUILT = True

def fuzzy_find_file(q: str, limit: int = 5, cutoff: int = 20):
    #在共享目录里模糊查找文件，返回 (score, rel, name) 列表
    _ensure_index()
    ql = (q or "").lower().strip()
    if not ql:
        return []

    scored = []
    for name, rel in _FILE_INDEX:
        score = 0
        if name in ql or rel in ql:
            score = 100
        else:
            for token in ql.replace("：", " ").replace(":", " ").split():
                if token and token in name:
                    score += 30
        scored.append((score, rel, name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(s, r, n) for s, r, n in scored[:limit] if s >= cutoff]

def list_shared_folder(max_items: int = 200) -> str:
    #列出共享目录里的全部文件（相对路径），返回文本清单
    _ensure_index(force=True)
    if not _FILE_INDEX:
        return f"(Shared directory is empty)\nPath: {ALLOWED_DIR}"

    out = []
    for _, rel in _FILE_INDEX[:max_items]:
        out.append("• " + rel)
    if len(_FILE_INDEX) > max_items:
        out.append(f"...（仅显示前 {max_items} 项，共 {len(_FILE_INDEX)} 个文件）")
    return "\n".join(out)


_FILE_PAT_SHARED = re.compile(
    r"([^\s\"'“”]+?\.(?:txt|md|json|log|py|yaml|yml|csv|xlsx|xls|pdf|docx|png|jpg|jpeg|webp|gif|bmp))",
    re.I
)
_FILE_PAT_ASCII = re.compile(
    r"([A-Za-z0-9_./\\-]+\.(?:txt|md|json|log|py|yaml|yml|csv|xlsx|xls|pdf|docx|png|jpg|jpeg|webp|gif|bmp))",
    re.I
)

_SHARED_WORDS = ["共享", "共享区", "共享目录", "共享文件夹", "共享盘", "shared folder"]
_LIST_WORDS = ["列出", "有哪些", "有什么", "列表", "清单", "目录", "浏览", "全部文件", "文件列表", "文件清单"]
_READ_WORDS = ["读取", "读一下", "读一读", "读下", "查看", "打开", "看看", "显示", "看一下", "帮我看", "内容是什么", "写了什么"]
_WRITE_WORDS = ["写入", "写到", "保存到", "存到", "记入", "记到", "追加", "补充到", "更新", "写上", "写下", "改成", "改为", "替换成"]
_APPEND_WORDS = ["追加", "补充", "接着写", "后面加", "附加", "append"]
_OVERWRITE_WORDS = ["覆盖", "替换", "重写", "清空", "覆写", "改成", "改为", "rewrite", "overwrite"]


def _contains_any(text: str, words: List[str]) -> bool:
    return any(w in text for w in words)


def _strip_path_token(s: str) -> str:
    return str(s or "").strip().strip(" \t\r\n\"'“”`，。；;：:（）()[]{}")


def _cleanup_rel_candidate(rel: str) -> str:
    c = _strip_path_token(rel)
    if not c:
        return ""
    c = c.replace("\\", "/")

    # 先尝试从候选串里再抓一次“纯文件片段”（避免把自然语言前缀吞进去）
    all_ascii = list(_FILE_PAT_ASCII.finditer(c))
    if all_ascii:
        c = _strip_path_token(all_ascii[-1].group(1))

    # 去掉常见前缀口语
    prefix_words = [
        "你再试一次", "你再试试", "再试一次", "再试试", "试试", "帮我", "请", "麻烦",
        "打开", "读取", "查看", "读一下", "读一读", "读下", "显示",
        "在共享文件夹里的", "在共享目录里的", "共享文件夹里的", "共享目录里的", "共享区里的",
        "在共享文件夹", "在共享目录", "共享文件夹", "共享目录", "共享区",
        "在", "把", "将"
    ]
    changed = True
    while changed:
        changed = False
        for w in prefix_words:
            if c.startswith(w):
                c = c[len(w):].lstrip(" /")
                changed = True

    # 去掉常见后缀语气词
    c = re.sub(r"(?:里|里面|内|中的?)$", "", c).strip()
    return _strip_path_token(c)


def _extract_rel_candidate(text: str) -> str:
    t = str(text or "")

    # 优先识别引号里的“文件名/路径”
    quoted = re.findall(r"[“\"']([^\"'“”]{1,260})[”\"']", t)
    for seg in quoted:
        q = _strip_path_token(seg)
        ms_ascii = list(_FILE_PAT_ASCII.finditer(q))
        if ms_ascii:
            return _cleanup_rel_candidate(ms_ascii[-1].group(1))
        ms = list(_FILE_PAT_SHARED.finditer(q))
        if ms:
            return _cleanup_rel_candidate(ms[-1].group(1))

    # 再从整句识别（优先 ascii 片段，如 test.txt）
    ms_ascii = list(_FILE_PAT_ASCII.finditer(t))
    if ms_ascii:
        return _cleanup_rel_candidate(ms_ascii[-1].group(1))
    ms = list(_FILE_PAT_SHARED.finditer(t))
    if ms:
        return _cleanup_rel_candidate(ms[-1].group(1))

    return ""


def _guess_rel_by_fuzzy(text: str, cutoff: int = 20) -> str:
    t = str(text or "")
    if not t:
        return ""
    tail = t
    for w in (_SHARED_WORDS + _LIST_WORDS + _READ_WORDS + _WRITE_WORDS):
        tail = tail.replace(w, " ")
    tail = re.sub(r"(把|将|请|帮我|一下|下|里|内|中|到|进|在)", " ", tail)
    tail = re.sub(r"\s+", " ", tail).strip()
    if not tail:
        tail = t
    guess = fuzzy_find_file(tail, limit=1, cutoff=cutoff)
    if guess:
        return guess[0][1]
    return ""


def _extract_write_content(text: str, rel: str) -> str:
    t = str(text or "").strip()
    rel = str(rel or "").strip()

    # 场景1：把“内容”放在引号里
    quoted = [x.strip() for x in re.findall(r"[“\"']([^\"'“”]{1,4000})[”\"']", t)]
    for q in quoted:
        if not q:
            continue
        # 过滤“路径型引号”
        if _FILE_PAT_SHARED.search(q):
            continue
        if rel and (q == rel or rel in q):
            continue
        return q

    if rel:
        rel_esc = re.escape(rel)
        # 场景2：把xxx写到/追加到 文件
        for pat in [
            rf"(?:把|将)\s*(.+?)\s*(?:写入|写到|保存到|存到|记入|追加到|追加进|覆盖到|替换到)\s*{rel_esc}",
            rf"(?:在|往)\s*{rel_esc}\s*(?:里|内|中)?\s*(?:写入|写到|追加|覆盖|替换|写上|写下)\s*(.+)$",
            rf"(?:写入|写到|保存到|存到|记入|追加|覆盖|替换)\s*(?:到|进|在)?\s*{rel_esc}\s*(?:里|内|中)?\s*(.+)$",
        ]:
            mm = re.search(pat, t)
            if mm:
                c = str(mm.group(1) or "").strip(" ：:，。；;")
                if c:
                    return c

    # 场景3：冒号后的内容
    if "：" in t or ":" in t:
        parts = re.split(r"[：:]", t, maxsplit=1)
        if len(parts) == 2:
            c = (parts[1] or "").strip()
            # 避免把“路径”当作内容
            if c and not _FILE_PAT_SHARED.fullmatch(c):
                return c

    return ""


def _default_write_content(text: str) -> str:
    t = str(text or "")
    ts = _current_system_time_info().get("local_dt", "")
    if any(k in t for k in ["一句话", "一行", "一句"]):
        return f"这是自动写入的一句话。({ts})"
    if any(k in t for k in ["一段话", "一段", "写点内容", "随便写", "写一点", "写点"]):
        return f"这是自动写入的测试内容，时间：{ts}。"
    if any(k in t for k in ["测试", "试试", "验证"]):
        return f"测试写入成功。({ts})"
    return ""


def _looks_like_write_intent(text: str) -> bool:
    t = str(text or "")
    if not t:
        return False

    # 明确写入词
    if _contains_any(t, _WRITE_WORDS) or _contains_any(t, _APPEND_WORDS) or _contains_any(t, _OVERWRITE_WORDS):
        return True

    # 口语化表达：写一句/写一行/写一段/写点...
    if re.search(r"写(?:一|1)?(?:句|行|段)|写一句|写一行|写一段|写点|写一些|写个", t):
        return True

    # 有引号内容 + 有“写”字，通常是写入
    if ("写" in t) and bool(re.search(r"[“\"']([^\"'“”]{1,4000})[”\"']", t)):
        if not re.search(r"(写了什么|怎么写|写的是啥)", t):
            return True

    return False


def _likely_shared_io_request(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if _extract_rel_candidate(t):
        return True
    hits = 0
    for w in (_SHARED_WORDS + _LIST_WORDS + _READ_WORDS + _WRITE_WORDS):
        if w in t:
            hits += 1
    return hits >= 2


def _extract_first_json_obj(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None

    # fenced json
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
    if m:
        raw = (m.group(1) or "").strip()

    # direct parse
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # extract first {...}
    m2 = re.search(r"\{[\s\S]*\}", raw)
    if m2:
        s = m2.group(0)
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _normalize_compiled_action(v: Any) -> str:
    s = str(v or "").strip().lower()
    mp = {
        "read": "read",
        "open": "read",
        "view": "read",
        "读取": "read",
        "打开": "read",
        "查看": "read",

        "append": "append",
        "write": "append",
        "write_append": "append",
        "追加": "append",
        "写入": "append",
        "保存": "append",

        "overwrite": "overwrite",
        "replace": "overwrite",
        "rewrite": "overwrite",
        "覆盖": "overwrite",
        "替换": "overwrite",
        "重写": "overwrite",

        "list": "list",
        "ls": "list",
        "dir": "list",
        "目录": "list",

        "none": "none",
        "unknown": "none",
        "skip": "none",
    }
    return mp.get(s, "none")


def _compile_shared_command_by_model(user_text: str, allow_write: bool = True) -> Optional[Dict[str, Any]]:
    """
    用模型把自然语言编译为共享目录指令 JSON（中英双语输入）。
    """
    if not _likely_shared_io_request(user_text):
        return None

    write_hint = "allow" if allow_write else "deny"
    compiler_system = (
        "You are TYXT shared-folder command compiler / 共享目录指令编译器.\n"
        "Translate user request (Chinese or English) into ONE JSON object only. No extra text.\n"
        "支持中英输入，只输出 JSON。\n"
        "Schema / 字段：\n"
        "{\n"
        "  \"action\": \"list|read|append|overwrite|none\",\n"
        "  \"path\": \"relative file path or filename, optional / 相对路径或文件名，可空\",\n"
        "  \"content\": \"text to write, optional / 写入内容，可空\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"reason\": \"one short sentence / 一句话\"\n"
        "}\n"
        "Action mapping / 动作映射：\n"
        "- list: list files/folders, ls, dir, 列目录, 文件清单\n"
        "- read: read/open/view/show, 读取, 打开, 查看, 看看\n"
        "- append: append/write/add/save note, 写入, 追加, 补充, 记入\n"
        "- overwrite: overwrite/replace/rewrite, 覆盖, 替换, 重写, 改为\n"
        "- none: unclear/unsafe\n"
        "Rules / 规则：\n"
        "- path must be file path only; remove natural-language wrappers.\n"
        "- path 只保留文件路径，不要带自然语言前后缀。\n"
        "- if write intent exists but content missing, set content=\"__AUTO__\".\n"
        "- 若有写入意图但内容缺失，content 设为 \"__AUTO__\"。\n"
        f"- current write policy / 当前写入策略: {write_hint}.\n"
        "- if write policy is deny and user asks to write, prefer action=none.\n"
        "- 不确定就 action=none。\n"
    )
    compiler_user = f"User text / 用户原话: {str(user_text or '').strip()}"

    try:
        compile_messages = [
            {"role": "system", "content": compiler_system},
            {"role": "user", "content": compiler_user},
        ]
        out = call_model(
            compile_messages,
            stream=False,
            max_tokens=220,
            temperature=0.0,
            top_p=0.1,
            top_k=20,
        )
        obj = _extract_first_json_obj(str(out or ""))
        if not isinstance(obj, dict):
            return None

        action = _normalize_compiled_action(obj.get("action"))
        if action == "none":
            return None

        confidence = safe_float(obj.get("confidence"), 0.0)
        if confidence > 0 and confidence < 0.30:
            return None

        path = _cleanup_rel_candidate(obj.get("path") or obj.get("file") or "")
        content = str(obj.get("content") or "").strip()
        return {
            "action": action,
            "path": path,
            "content": content,
            "confidence": confidence,
            "reason": str(obj.get("reason") or "").strip(),
        }
    except Exception as e:
        try:
            print("[shared compiler warn]", e)
        except Exception:
            pass
        return None


def _execute_compiled_shared_command(cmd: Dict[str, Any], raw_text: str, allow_write: bool = True) -> Tuple[bool, str]:
    action = _normalize_compiled_action(cmd.get("action"))
    path = _cleanup_rel_candidate(cmd.get("path") or "")
    content = str(cmd.get("content") or "").strip()

    if action == "list":
        return True, list_shared_folder()

    if action == "read":
        if not path:
            path = _guess_rel_by_fuzzy(raw_text, cutoff=20)
        if not path:
            return True, "❌ Target file to read was not found (include filename or extension)."
        return True, read_file_auto(path)

    if action in {"append", "overwrite"}:
        if not allow_write:
            return True, "❌ Writing to shared directory is disabled for the current session."
        if not path:
            path = _guess_rel_by_fuzzy(raw_text, cutoff=30)
        if not path:
            return True, "❌ Target file to write was not found (include filename, e.g. test.txt)."

        if (not content) or (content.upper() == "__AUTO__"):
            content = _extract_write_content(raw_text, path) or _default_write_content(raw_text)

        if not content:
            return True, "❌ Write intent detected, but content is empty. Wrap content in quotes."

        if action == "overwrite":
            msg = overwrite_file(path, content)
        else:
            msg = append_file(path, content)
        preview = read_file_auto(path)
        return True, f"{msg}\n\n{preview}"

    return False, ""


def try_handle_shared_io(user_text: str, allow_write: bool = True) -> Tuple[bool, str]:
    """
    共享目录自然语言读写入口。
    返回: (handled, reply_text)
    """
    t = (user_text or "").strip()
    if not t:
        return False, ""

    has_shared_word = _contains_any(t, _SHARED_WORDS)
    rel = _extract_rel_candidate(t)
    possible_shared = has_shared_word or bool(rel) or _likely_shared_io_request(t)

    # 1) 列出共享目录
    want_list = has_shared_word and _contains_any(t, _LIST_WORDS)
    if want_list and not rel:
        return True, list_shared_folder()

    # 2) 写入/追加/覆盖共享文件（优先于读，避免“打开+写”被误判成只读）
    want_write = _looks_like_write_intent(t) or bool(re.search(r"(?:在|往).*(?:里|内|中).*(?:写|追加|覆盖|替换)", t))
    if allow_write and want_write and possible_shared:

        if not rel:
            rel = _guess_rel_by_fuzzy(t, cutoff=30)

        if rel:
            content = _extract_write_content(t, rel)
            if not content:
                content = _default_write_content(t)

            if content:
                is_overwrite = _contains_any(t, _OVERWRITE_WORDS)
                is_append = _contains_any(t, _APPEND_WORDS)
                if is_overwrite:
                    msg = overwrite_file(rel, content)
                elif is_append:
                    msg = append_file(rel, content)
                else:
                    # 默认“写入/保存到”走追加，避免误覆盖历史内容
                    msg = append_file(rel, content)
                preview = read_file_auto(rel)
                return True, f"{msg}\n\n{preview}"

    # 3) 读取共享文件
    want_read = _contains_any(t, _READ_WORDS)
    if want_read and possible_shared:
        if not rel:
            rel = _guess_rel_by_fuzzy(t, cutoff=20)
        if rel:
            return True, read_file_auto(rel)

    # 4) 模型编译指令（自然语言 -> JSON 指令 -> 执行）
    compiled = _compile_shared_command_by_model(t, allow_write=allow_write)
    if isinstance(compiled, dict):
        ok, out = _execute_compiled_shared_command(compiled, t, allow_write=allow_write)
        if ok:
            return True, out

    # 5) 兜底错误提示：仅在明显是共享目录意图时返回
    if want_write and possible_shared:
        return True, "❌ Write intent to shared file detected, but executable info is missing (filename or content). Example: write \"content\" to test.txt"
    if want_read and possible_shared:
        return True, "❌ Read intent to shared file detected, but filename is missing. Example: open test.txt"

    return False, ""

# ============================================================
# 20. 场景识别与清洗：extract_scene_from_request / clean_reply_text
#   说明：
#   - 这里只负责“把上游请求规范化成 meta” + “清洗回复文本”
#   - 不在这里做落盘（落盘统一走 save_chat）
# ============================================================

def extract_scene_from_request(data: dict) -> dict:
    
    #尽量从第三方桥接端/客户端请求里推断场景信息，并输出统一 meta。
    #兼容字段：group_id / user_id / sender / chat_type / message_type / session_id / meta 等。

    #返回字段（统一格式）：
    #- scene: "private" / "group"
    #- group_id: str
    #- user_id: str
    #- nickname: str         # 发言者昵称（用于日志显示）
    #- sender_name: str      # 兼容旧字段（等同 nickname）
    #- is_peach: bool        # 如果上游明确传了 is_peach/is_owner 就沿用
    
    data = data or {}
    ctx_user_id, ctx_role, ctx_nickname = get_current_user_ctx(data if isinstance(data, dict) else {})

    # ✅ 一些桥接端会把关键字段塞在 meta 里：先合并
    if isinstance(data.get("meta"), dict):
        merged = {}
        merged.update(data.get("meta") or {})
        merged.update(data)  # 顶层优先级更高
        data = merged

    group_id = data.get("group_id") or data.get("groupId") or ""
    user_id  = ctx_user_id or data.get("user_id") or data.get("userId") or data.get("qq") or ""

    # sender / nickname
    nickname = ctx_nickname or data.get("nickname") or data.get("name") or ""
    sender = data.get("sender") or {}
    if isinstance(sender, dict):
        nickname = nickname or sender.get("card") or sender.get("nickname") or sender.get("name") or ""
    nickname = _clean_display_name(nickname)

    # message_type / chat_type / scene
    chat_type = (data.get("message_type") or data.get("chat_type") or data.get("scene") or "").strip().lower()

    # session_id 里也可能藏 group/private
    session_id = str(data.get("session_id") or data.get("sessionId") or "")

    # 推断场景
    if str(group_id).strip():
        scene = "group"
    elif chat_type in ("group", "private"):
        scene = chat_type
    elif "group" in session_id.lower():
        scene = "group"
    else:
        scene = "private"

    # 如果还拿不到 user_id，尝试从 OpenAI 格式的 user 字段取
    if not str(user_id).strip():
        user_id = data.get("user") or ""
    user_id = _canonicalize_chat_user_id(user_id, scene=scene, group_id=group_id)

    # 用户识别：仅当上游显式传入（你后续也可以自己定制规则）
    is_peach = bool(data.get("is_peach") or data.get("is_owner"))

    meta = {
        "scene": scene,
        "message_type": scene,  # 给旧逻辑兼容
        "group_id": str(group_id).strip(),
        "user_id": str(user_id).strip() or "anonymous",
        "role": "admin" if str(ctx_role).strip().lower() == "admin" else "user",
        "nickname": str(nickname).strip() or str(user_id).strip() or "anonymous",
        "sender_name": str(nickname).strip() or str(user_id).strip() or "anonymous",  # 兼容旧字段
        "is_peach": is_peach,
    }
    try:
        ch, owner = resolve_channel_owner(meta)
        meta["channel_type"] = ch
        meta["owner_id"] = owner
    except Exception:
        pass
    return meta

def clean_reply_text(s: str) -> str:
    
    #轻清洗：
    #- 把字面量 \\n 转回真正换行
    #- 清除常见二次转义残留
    #- 压缩多余空行
    
    if s is None:
        return ""

    s = str(s)

    # 1) 反转义：把“字面量 \n”变成真正换行（只处理最常见的）
    s = s.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")

    # 2) 去掉一些常见的“二次转义残留”
    s = s.replace('\\"', '"').replace("\\'", "'")

    # 3) 连续空行最多保留 2 行
    s = re.sub(r"\n{4,}", "\n\n", s)

    # 4) 去掉行尾空格
    s = "\n".join([line.rstrip() for line in s.splitlines()])

    return s.strip()


# ============================================================
# 21. OpenAI 兼容接口：/v1/chat/completions（供第三方客户端接入）
#   关键原则：
#   - 先从请求里解析 meta（允许 data.meta 传入；不传也能兜底 private）
#   - system_prompt 必须真的喂进模型（messages_for_model = [system] + norm_msgs）
#   - 落盘统一走 save_chat(user, assistant, meta=meta)
# ============================================================

@app.route("/v1/chat/completions", methods=["POST", "OPTIONS"])
def api_chat_completions():
    if request.method == "OPTIONS":
        return ("", 204)

    try:
        data = request.get_json(silent=True) or {}

        # ---- 1) 解析 meta：允许上游传 meta；不传则从 data 推断（默认 private）----
        # 你前面 #20 已经把 extract_scene_from_request 做成“规范化 meta”的入口了
        meta = extract_scene_from_request(data)

        # 如果上游显式传了 meta（例如 bridge/astrbot），合并进去（顶层优先）
        if isinstance(data.get("meta"), dict):
            m2 = dict(data.get("meta") or {})
            m2.update(meta)   # meta 是规范化产物，优先保证最小字段齐全
            meta = m2

        # ---- 2) 取 messages：兼容 messages / prompt / input / content ----
        messages = data.get("messages") or []
        if not messages:
            if data.get("prompt"):
                messages = [{"role": "user", "content": data["prompt"]}]
            elif data.get("input"):
                messages = [{"role": "user", "content": data["input"]}]
            elif data.get("content"):
                messages = [{"role": "user", "content": data["content"]}]

        # 标准化 messages
        norm_msgs = []
        for m in messages:
            if isinstance(m, dict):
                role = str(m.get("role") or "user")
                content = m.get("content") or m.get("text") or ""
            else:
                role, content = "user", str(m)
            norm_msgs.append({"role": role, "content": str(content)})

        if not norm_msgs:
            return Response(
                json.dumps({"error": "no input messages"}, ensure_ascii=False),
                status=400,
                mimetype="application/json; charset=utf-8"
            )

        # ---- 3) 找最后一个 user 输入（用于记忆检索 & 落盘 user_text）----
        user_input = ""
        for m in reversed(norm_msgs):
            if m.get("role") == "user" and (m.get("content") or "").strip():
                user_input = (m.get("content") or "").strip()
                break
        if not user_input:
            user_input = (norm_msgs[-1].get("content") or "").strip()
        stream_requested = bool(data.get("stream")) or (request.args.get("stream") == "1")

        # ---- 4) 记忆召回（按 Profile 选择向量库/collection 的话，你后面在 vector_search 内部处理）----
        triggered = trigger_memory_check(user_input)
        topk = MEM_TOPK if triggered else MEM_LIGHT_TOPK

        mem_txt = ""
        if topk > 0:
            focus_keywords = _memory_focus_keywords(user_input) if triggered else []
            memory_queries = focus_keywords if focus_keywords else (
                _memory_query_candidates(user_input) if triggered else [str(user_input or "").strip()]
            )
            if not memory_queries:
                memory_queries = [str(user_input or "").strip()]

            empty = True
            for mq in memory_queries:
                res = vector_search(mq, top_k=topk, meta=meta)
                if isinstance(res, dict) and "error" in res:
                    continue
                if focus_keywords:
                    res = _payload_filter_by_keywords(res, focus_keywords)
                mem_try, empty_try = format_memories(res)
                if not empty_try and str(mem_try).strip():
                    mem_txt = mem_try
                    empty = False
                    break
                empty = bool(empty_try)
            if triggered and empty:
                mem_txt = "（无匹配记忆）"

        # ---- 4.1) 网页搜索（支持 MCP 优先，失败回退内置）----
        _raw_mode = meta.get("web_search_mode", data.get("web_search_mode", MODEL_CONFIG.get("web_search_mode", "")))
        if _raw_mode is None or str(_raw_mode).strip() == "":
            web_search_enabled = safe_bool(
                meta.get("web_search_enabled", data.get("web_search_enabled", MODEL_CONFIG.get("web_search_enabled", False))),
                False,
            )
            web_search_mode = "default" if web_search_enabled else "off"
        else:
            web_search_mode = _normalize_web_search_mode(_raw_mode)
            web_search_enabled = bool(web_search_mode != "off")
        web_search_provider = _normalize_web_search_provider(
            meta.get("web_search_provider", data.get("web_search_provider", MODEL_CONFIG.get("web_search_provider", "builtin")))
        )
        web_top_k = max(1, min(safe_int(meta.get("web_top_k", data.get("web_top_k")), 6), 10))
        wants_web_lookup = _looks_like_web_lookup_query(user_input)
        if wants_web_lookup and (not web_search_enabled):
            disabled_text = "目前上网搜索功能没有开启。请先在设置里打开“上网搜索”后再试。"
            try:
                save_chat(user_input or "[no_user]", disabled_text, meta=meta)
            except Exception:
                pass
            if stream_requested:
                def _disabled_stream():
                    payload = {
                        "id": f"chatcmpl-{int(time.time())}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": MODEL_NAME,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": disabled_text},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                return Response(
                    stream_with_context(_disabled_stream()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
                )
            resp = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": MODEL_NAME,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": disabled_text},
                    "finish_reason": "stop"
                }]
            }
            return Response(json.dumps(resp, ensure_ascii=False), status=200, mimetype="application/json; charset=utf-8")
        web_items: List[Dict[str, str]] = []
        should_web_lookup = bool(web_search_mode == "force" or (web_search_mode == "default" and wants_web_lookup))
        if should_web_lookup:
            try:
                web_items = _search_engine_items_with_fallback(user_input, top_k=web_top_k, meta=meta)
            except Exception as e:
                print("[WEB_SEARCH warn]", e)
                web_items = []
        meta["web_search_enabled"] = bool(web_search_enabled)
        meta["web_search_mode"] = web_search_mode
        meta["web_search_provider"] = web_search_provider
        meta["web_top_k"] = int(web_top_k)

        # ---- 5) 拼 system prompt：人格 + 时间感知 + 协议 + 临时上下文 ----
        sys_lines = []

        # 5.1 人格底座：仅使用 UI 人格设置
        try:
            ui_persona_cfg = _load_persona_config()
            ui_persona_txt = str(ui_persona_cfg.get("content") or "").strip()
            if ui_persona_txt:
                sys_lines.append("【UI人格设定】\n" + ui_persona_txt)
        except Exception:
            pass

        # 5.1.1 实时系统时间（每次请求动态注入）
        sys_lines.append(_build_system_time_block())

        # 5.2 元信息（让模型知道现在是谁/在哪）
        try:
            scene = str(meta.get("scene") or "private")
            gid   = str(meta.get("group_id") or "").strip()
            uid   = str(meta.get("user_id") or "").strip()
            nick  = str(meta.get("nickname") or meta.get("sender_name") or "").strip()
            sys_lines.append(
                "【当前会话元信息】\n"
                f"- scene: {scene}\n"
                f"- group_id: {gid}\n"
                f"- user_id: {uid}\n"
                f"- nickname: {nick}\n"
            )
        except Exception:
            pass

        # 5.3 你的“QQ 文本规则/风格规则/表情包协议”等，可以继续放在这里
        # （你后面如果要我帮你把“表情包协议”统一写成一段，我也能给你模块化）
        sys_lines.append(
            "【QQ 输出规则】\n"
            "1) 不要用 Markdown（**、-、` 等），用纯文本。\n"
            "2) 尽量短句，优先 1-4 句说清楚。\n"
            "3) 需要分段就分段，但不要刷屏。\n"
        )

        # 5.4 临时上下文注入（关键：统一只走 build_runtime_context_blocks，不再混用旧变量）
        ctx = build_runtime_context_blocks(meta)
        if ctx.get("private_ctx"):
            sys_lines.append("【私聊临时上下文】\n" + (ctx["private_ctx"] or ""))
        if ctx.get("group_ctx"):
            sys_lines.append("【群聊临时上下文】\n" + (ctx["group_ctx"] or ""))
        if ctx.get("group_sum"):
            sys_lines.append("【群聊总结】\n" + (ctx["group_sum"] or ""))
        if ctx.get("all_group_summaries"):
            sys_lines.append("【所有群聊总结】\n" + (ctx["all_group_summaries"] or ""))

        # 5.5 RAG 记忆片段
        if mem_txt:
            sys_lines.append("【相关长期记忆片段】\n" + mem_txt)

        # 5.5.1 网页搜索结果（用于联网信息补充）
        if web_items:
            web_txt = _format_search_items_for_prompt(web_items)
            if web_txt:
                sys_lines.append(
                    "【联网结果使用要求】\n"
                    "已提供本轮网页搜索结果。请基于这些结果回答，不要再说“无法联网/知识截止无法获取实时信息”。\n"
                    "输出以“标题或简短梗概”为主；每条后可附格式：`（来源）[标题](链接)`。\n"
                    "不要在正文末尾再单独输出“来源：”链接列表。"
                )
                sys_lines.append("【网页搜索结果（供参考）】\n" + web_txt)

        # 5.6 把 meta 明文塞给模型（你之前就要求它“看得到人名/ID/场景”）
        try:
            meta_dump = json.dumps(meta, ensure_ascii=False)
        except Exception:
            meta_dump = str(meta)
        sys_lines.append(f"【meta】{meta_dump}")

        system_prompt = "\n\n".join([x for x in sys_lines if (x or "").strip()])

        # ✅ 真正喂给模型的 messages：system + 原 messages（不要把 system 丢了）
        messages_for_model = []
        if system_prompt:
            messages_for_model.append({"role": "system", "content": system_prompt})
        messages_for_model.extend(norm_msgs)

        # ---- 6) 参数 ----
        max_tokens  = int(data.get("max_tokens") or MODEL_CONFIG.get("max_tokens", GEN_MAX_TOKENS))
        temperature = float(data.get("temperature") or MODEL_CONFIG.get("temperature", GEN_TEMP))
        top_p       = float(data.get("top_p") or MODEL_CONFIG.get("top_p", GEN_TOP_P))
        top_k       = int(data.get("top_k") or MODEL_CONFIG.get("top_k", GEN_TOP_K))

        stream = bool(stream_requested)

        # ---- 7) 流式 ----
        if stream:
            def generate():
                buf = []
                with _model_lock:
                    for delta in call_model(
                        messages_for_model,
                        stream=True,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        top_p=top_p,
                        top_k=top_k
                    ):
                        piece = clean_reply_text(str(delta))
                        if piece:
                            buf.append(piece)

                        payload = {
                            "id": f"chatcmpl-{int(time.time())}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": MODEL_NAME,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": piece},
                                "finish_reason": None
                            }]
                        }
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                full = clean_reply_text("".join(buf)).strip()
                if web_items:
                    if web_items and _reply_denies_web_access(full):
                        corrected = _build_web_digest_for_reply(
                            web_items,
                            max_items=safe_int(meta.get("web_top_k"), 6),
                        )
                        if corrected:
                            addon_fix = "\n\n（已根据联网结果自动更正）\n" + corrected
                            full = (full.rstrip() + addon_fix).strip()
                            payload = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": MODEL_NAME,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": addon_fix},
                                    "finish_reason": None
                                }]
                            }
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if full:
                    try:
                        save_chat(user_input or "[no_user]", full, meta=meta)
                    except Exception as e:
                        print("[save_chat error]", e)

                yield "data: [DONE]\n\n"

            return Response(
                stream_with_context(generate()),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )

        # ---- 8) 非流式 ----
        with _model_lock:
            reply = call_model(
                messages_for_model,
                stream=False,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k
            )

        reply_text = clean_reply_text(str(reply))
        if web_items:
            if web_items and _reply_denies_web_access(reply_text):
                corrected = _build_web_digest_for_reply(
                    web_items,
                    max_items=safe_int(meta.get("web_top_k"), 6),
                )
                if corrected:
                    reply_text = corrected
        try:
            save_chat(user_input or "[no_user]", reply_text, meta=meta)
        except Exception as e:
            print("[save_chat error]", e)

        resp = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": MODEL_NAME,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": reply_text},
                "finish_reason": "stop"
            }]
        }
        return Response(json.dumps(resp, ensure_ascii=False), status=200, mimetype="application/json; charset=utf-8")

    except Exception as e:
        print("[api_chat_completions error]", e)
        return Response(json.dumps({"error": str(e)}, ensure_ascii=False), status=500, mimetype="application/json; charset=utf-8")

# ============================================================
# 22. 工具接口：/tools/open_shared_folder /tools/search_engine
#               /tools/save_params /tools/load_params /tools/update_config /tools/mem_debug
# ============================================================

# ====== 工具：打开共享文件夹 ======
@app.post("/tools/open_shared_folder")
def api_open_shared_folder():
    try:
        target_dir = os.path.abspath(os.path.normpath(ALLOWED_DIR))
        os.makedirs(target_dir, exist_ok=True)

        # 尽量把 Explorer 窗口前置（仅 Windows）
        try:
            import time
            import ctypes
            import win32gui
            import win32con
            import urllib.parse as _urlparse

            user32 = ctypes.windll.user32

            def _norm_path(p: str) -> str:
                try:
                    return os.path.normcase(os.path.normpath(os.path.abspath(str(p or "").strip())))
                except Exception:
                    return ""

            target_abs = _norm_path(target_dir)
            target_name = os.path.basename(target_abs).lower()

            def _focus_hwnd(hwnd) -> bool:
                if not hwnd:
                    return False
                try:
                    user32.AllowSetForegroundWindow(-1)
                except Exception:
                    pass
                try:
                    # 解除可能存在的前台锁
                    lock_fn = getattr(user32, "LockSetForegroundWindow", None)
                    if lock_fn:
                        lock_fn(2)  # LSFW_UNLOCK
                except Exception:
                    pass
                try:
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                except Exception:
                    pass
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                except Exception:
                    pass
                try:
                    win32gui.BringWindowToTop(hwnd)
                except Exception:
                    pass
                try:
                    win32gui.SetForegroundWindow(hwnd)
                except Exception:
                    # 常见前台锁限制：用 ALT 键技巧兜底
                    try:
                        user32.keybd_event(0x12, 0, 0, 0)       # ALT down
                        user32.SetForegroundWindow(int(hwnd))
                        user32.keybd_event(0x12, 0, 0x0002, 0)  # ALT up
                    except Exception:
                        pass
                # SwitchToThisWindow 在部分系统上比 SetForegroundWindow 更容易成功
                try:
                    switch_fn = getattr(user32, "SwitchToThisWindow", None)
                    if switch_fn:
                        switch_fn(int(hwnd), True)
                except Exception:
                    pass
                # AttachThreadInput 强制前置激活
                try:
                    fg_hwnd = user32.GetForegroundWindow()
                    fg_tid = user32.GetWindowThreadProcessId(int(fg_hwnd), None)
                    target_tid = user32.GetWindowThreadProcessId(int(hwnd), None)
                    cur_tid = user32.GetCurrentThreadId()
                    if fg_tid and target_tid:
                        user32.AttachThreadInput(int(fg_tid), int(target_tid), True)
                    if cur_tid and target_tid and cur_tid != target_tid:
                        user32.AttachThreadInput(int(cur_tid), int(target_tid), True)
                    try:
                        user32.SetForegroundWindow(int(hwnd))
                    except Exception:
                        pass
                    try:
                        user32.SetActiveWindow(int(hwnd))
                    except Exception:
                        pass
                    try:
                        user32.SetFocus(int(hwnd))
                    except Exception:
                        pass
                    if cur_tid and target_tid and cur_tid != target_tid:
                        user32.AttachThreadInput(int(cur_tid), int(target_tid), False)
                    if fg_tid and target_tid:
                        user32.AttachThreadInput(int(fg_tid), int(target_tid), False)
                except Exception:
                    pass
                try:
                    # TopMost 闪切，确保窗口在最前
                    win32gui.SetWindowPos(
                        hwnd,
                        win32con.HWND_TOPMOST,
                        0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                    )
                    win32gui.SetWindowPos(
                        hwnd,
                        win32con.HWND_NOTOPMOST,
                        0, 0, 0, 0,
                        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                    )
                except Exception:
                    pass
                # COM AppActivate 兜底（标题激活）
                try:
                    import win32com.client as _win32client
                    title = str(win32gui.GetWindowText(hwnd) or "").strip()
                    if title:
                        wsh = _win32client.Dispatch("WScript.Shell")
                        try:
                            wsh.SendKeys("%")
                        except Exception:
                            pass
                        try:
                            wsh.AppActivate(title)
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    fg_hwnd = user32.GetForegroundWindow()
                    return int(fg_hwnd) == int(hwnd)
                except Exception:
                    return False

            def _pick_hwnd_by_shell_windows():
                try:
                    import win32com.client as _win32client
                    shell = _win32client.Dispatch("Shell.Application")
                    wins = shell.Windows()
                    for w in wins:
                        try:
                            hwnd = int(getattr(w, "HWND", 0) or 0)
                            if not hwnd:
                                continue
                            path = ""
                            try:
                                path = str(w.Document.Folder.Self.Path or "")
                            except Exception:
                                loc = str(getattr(w, "LocationURL", "") or "")
                                if loc.lower().startswith("file:///"):
                                    path = _urlparse.unquote(loc[8:]).replace("/", "\\")
                            pabs = _norm_path(path)
                            if not pabs:
                                continue
                            # 允许定位到目标目录，或目标目录在当前窗口路径之下（有时会打开到子目录）
                            if pabs == target_abs or pabs.startswith(target_abs + os.sep):
                                return hwnd
                        except Exception:
                            continue
                except Exception:
                    return None
                return None

            # 1) 先尝试把“确实已打开到目标目录”的窗口前置
            # 注意：不要用标题模糊匹配，否则会把任意 Explorer 窗口前置，导致看起来“没打开共享目录”
            existing = _pick_hwnd_by_shell_windows()
            if existing and _focus_hwnd(existing):
                return jsonify({"ok": True, "msg": f"✅ Shared folder opened: {ALLOWED_DIR}", "path": target_dir}), 200

            # 2) 强制按目标路径打开，再按目标路径匹配到的窗口前置
            try:
                subprocess.Popen(["explorer.exe", target_dir])
            except Exception:
                os.startfile(target_dir)  # type: ignore[attr-defined]

            end_ts = time.time() + 4.5
            while time.time() < end_ts:
                hwnd = _pick_hwnd_by_shell_windows()
                if hwnd:
                    _focus_hwnd(hwnd)
                    break
                time.sleep(0.15)
        except Exception:
            # 非 Windows 或前置失败时，至少保证能打开
            try:
                os.startfile(target_dir)  # type: ignore[attr-defined]
            except Exception:
                subprocess.Popen(["explorer.exe", target_dir])

        return jsonify({"ok": True, "msg": f"✅ Shared folder opened: {ALLOWED_DIR}", "path": target_dir}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/tools/open_import_folder")
def api_open_import_folder():
    try:
        target_dir = os.path.abspath(IMPORT_DROP_DIR)
        os.makedirs(target_dir, exist_ok=True)
        subprocess.Popen(["explorer.exe", target_dir])
        return jsonify({"ok": True, "path": target_dir, "msg": "√ Import folder opened"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ====== 工具：上传图片（前端附件） ======
def _uploads_dir() -> str:
    d = os.path.join(ALLOWED_DIR, "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _fit_image_size(width: int, height: int, max_w: int, max_h: int) -> Tuple[int, int]:
    try:
        w = max(1, int(width))
        h = max(1, int(height))
        mw = max(1, int(max_w))
        mh = max(1, int(max_h))
        ratio = min(mw / w, mh / h, 1.0)
        return max(1, int(round(w * ratio))), max(1, int(round(h * ratio)))
    except Exception:
        return 0, 0


@app.get("/uploads/<path:filename>")
def api_uploaded_file(filename: str):
    try:
        # 仅允许单文件名，避免路径穿越
        base = os.path.basename(str(filename or "").strip())
        if (not base) or (base != filename):
            return jsonify({"ok": False, "error": "invalid filename"}), 400
        return send_from_directory(_uploads_dir(), base, as_attachment=False)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 404


@app.get("/shared/audio/<path:rel_path>")
def serve_tts_audio(rel_path: str):
    """
    从共享目录下读取 tts 子目录音频并返回。
    只允许访问 ALLOWED_DIR/tts 目录下的文件。
    """
    try:
        rel_clean = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
        if not rel_clean:
            return jsonify({"ok": False, "msg": "invalid path"}), 400

        abs_path = os.path.abspath(os.path.join(ALLOWED_DIR, rel_clean))
        tts_root = os.path.abspath(TTS_OUTPUT_DIR)
        if not (abs_path == tts_root or abs_path.startswith(tts_root + os.sep)):
            return jsonify({"ok": False, "msg": "forbidden"}), 403

        if (not os.path.exists(abs_path)) or (not os.path.isfile(abs_path)):
            return jsonify({"ok": False, "msg": "file not found"}), 404

        return send_file(abs_path, mimetype="audio/wav", as_attachment=False)
    except Exception as e:
        print(f"[shared/audio error] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 500


@app.post("/tools/upload_image")
def api_upload_image():
    try:
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "Missing file field"}), 200

        f = request.files["file"]
        if (not f) or (not f.filename):
            return jsonify({"ok": False, "error": "Empty file"}), 200

        filename = secure_filename(f.filename)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"]:
            return jsonify({"ok": False, "error": f"Unsupported image format: {ext}"}), 200

        save_dir = _uploads_dir()

        ts = time.strftime("%Y%m%d_%H%M%S")
        save_name = f"{ts}_{int(time.time() * 1000) % 1000000:06d}{ext}"
        save_path = os.path.join(save_dir, save_name)
        f.save(save_path)
        _ensure_index(force=True)

        # 读取图片尺寸，并给出前端建议展示尺寸（超限自动缩小）
        width = 0
        height = 0
        disp_w = 0
        disp_h = 0
        try:
            with Image.open(save_path) as im:
                width, height = im.size
            disp_w, disp_h = _fit_image_size(width, height, IMAGE_PREVIEW_MAX_W, IMAGE_PREVIEW_MAX_H)
        except Exception:
            pass

        file_url = request.host_url.rstrip("/") + url_for("api_uploaded_file", filename=save_name)

        return jsonify({
            "ok": True,
            "path": save_path,
            "saved_as": save_name,
            "url": file_url,
            "image": {
                "width": int(width or 0),
                "height": int(height or 0),
                "display_width": int(disp_w or 0),
                "display_height": int(disp_h or 0),
                "max_width": int(IMAGE_PREVIEW_MAX_W),
                "max_height": int(IMAGE_PREVIEW_MAX_H)
            }
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


# ========= 工具：OCR（多模态工具层）=========
@app.get("/tools/ocr_status")
def api_tool_ocr_status():
    try:
        status = multimodal_tools.ocr_status()
        return jsonify({"ok": True, **(status or {})}), 200
    except Exception as e:
        print(f"[tools/ocr_status error] {e}")
        return jsonify({"ok": False, "available": False, "reason": str(e)}), 200


@app.post("/tools/ocr_image")
def api_tool_ocr_image():
    try:
        data = request.get_json(silent=True) or {}
        image_path = str(data.get("image_path") or "").strip()
        if not image_path:
            return jsonify({"ok": False, "msg": "Missing image_path"}), 200

        text = multimodal_tools.ocr_image(image_path)
        text = str(text or "")
        if text.startswith("❌"):
            print(f"[tools/ocr_image] failed: {text}")
            return jsonify({"ok": False, "msg": text, "text": ""}), 200

        return jsonify({"ok": True, "text": text}), 200
    except Exception as e:
        print(f"[tools/ocr_image error] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 200


# ========= 工具：TTS（GPT-SoVITS）=========
@app.post("/tools/tts")
def api_tool_tts():
    try:
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()
        voice_id = str(data.get("voice_id") or "default").strip() or "default"
        if not text:
            return jsonify({"ok": False, "msg": "text is empty", "rel_path": "", "voice_id": voice_id}), 200

        res = multimodal_tools.tts_speak(text, voice_id=voice_id)
        if not isinstance(res, dict):
            print(f"[tools/tts] invalid response type: {type(res)}")
            return jsonify({"ok": False, "msg": "invalid tts response", "rel_path": "", "voice_id": voice_id}), 200

        return jsonify(res), 200
    except Exception as e:
        print(f"[tools/tts error] {e}")
        return jsonify({"ok": False, "msg": str(e), "rel_path": ""}), 200


# ========= 工具：ASR（占位）=========
@app.post("/tools/asr")
def api_tool_asr():
    try:
        data = request.get_json(silent=True) or {}
        audio_path = str(data.get("audio_path") or "")
        msg = str(multimodal_tools.asr_transcribe(audio_path) or "ASR not implemented yet")
        print("[tools/asr] requested but not implemented yet")
        return jsonify({"ok": False, "msg": msg}), 200
    except Exception as e:
        print(f"[tools/asr error] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 200


# ========= 工具：文生图（占位）=========
@app.post("/tools/img_generate")
def api_tool_img_generate():
    try:
        data = request.get_json(silent=True) or {}
        prompt = str(data.get("prompt") or "")
        msg = str(multimodal_tools.img_generate(prompt) or "Image generation not implemented yet")
        print("[tools/img_generate] requested but not implemented yet")
        return jsonify({"ok": False, "msg": msg}), 200
    except Exception as e:
        print(f"[tools/img_generate error] {e}")
        return jsonify({"ok": False, "msg": str(e)}), 200


# ========= 工具：上网搜索 =========
def _load_module_from_path(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"无法加载模块：{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

@app.post("/tools/search_engine")
def api_search_engine():
    try:
        data  = request.get_json(silent=True) or {}
        query = (data.get("query") or "").strip()
        top_k = int(data.get("top_k") or 8)
        if not query:
            return jsonify({"result": [], "error": "Empty query"}), 200
        provider = _normalize_web_search_provider(
            data.get("web_search_provider", MODEL_CONFIG.get("web_search_provider", "builtin"))
        )
        meta = {
            "web_search_provider": provider,
            "user_id": str(data.get("user_id") or "").strip(),
            "scene": str(data.get("scene") or "local").strip(),
            "owner_id": str(data.get("owner_id") or "").strip(),
            "role": str(data.get("role") or "").strip(),
        }
        items = _search_engine_items_with_fallback(query, top_k=top_k, meta=meta)
        return jsonify({"result": items[: max(1, min(int(top_k), 10))]}), 200

    except Exception as e:
        return jsonify({"result": [], "error": f"Search failed: {e}"}), 200


# ========= 工具：网页搜索别名（便于前端统一）=========
@app.post("/tools/web_search")
def api_web_search_alias():
    return api_search_engine()


# ========= 共享目录文件管理 API（供前端/插件调用）=========
@app.post("/files/list")
def api_files_list():
    try:
        data = request.get_json(silent=True) or {}
        rel = str(data.get("path") or "").strip()
        ap = _safe_abs(rel or ".")
        if not ap:
            return jsonify({"ok": False, "error": "Access denied."}), 200
        if not os.path.exists(ap):
            return jsonify({"ok": False, "error": "path not found"}), 200
        if os.path.isfile(ap):
            return jsonify({"ok": False, "error": "path is a file"}), 200

        items = []
        for name in sorted(os.listdir(ap)):
            fp = os.path.join(ap, name)
            items.append({
                "name": name,
                "type": "dir" if os.path.isdir(fp) else "file",
                "size": (os.path.getsize(fp) if os.path.isfile(fp) else None),
            })
        return jsonify({"ok": True, "path": rel or ".", "items": items}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.post("/files/read")
def api_files_read():
    try:
        data = request.get_json(silent=True) or {}
        rel = str(data.get("path") or "").strip()
        mode = str(data.get("mode") or "auto").strip().lower()
        max_chars = safe_int(data.get("max_chars"), 20000 if mode == "text" else 200000)
        max_chars = max(500, min(max_chars, 500000))

        ap = _safe_abs(rel)
        if not ap:
            return jsonify({"ok": False, "error": "Access denied."}), 200
        if not os.path.exists(ap):
            return jsonify({"ok": False, "error": "file not found"}), 200
        if os.path.isdir(ap):
            return jsonify({"ok": False, "error": "path is a directory"}), 200

        if mode == "text":
            with open(ap, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read(max_chars + 1)
            truncated = len(txt) > max_chars
            if truncated:
                txt = txt[:max_chars]
            return jsonify({"ok": True, "path": rel, "text": txt, "truncated": truncated}), 200

        txt = read_file_auto(rel)
        if len(txt) > max_chars:
            txt = txt[:max_chars] + "..."
        return jsonify({"ok": True, "path": rel, "text": txt, "truncated": False}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.post("/files/write")
def api_files_write():
    try:
        data = request.get_json(silent=True) or {}
        rel = str(data.get("path") or "").strip()
        content = str(data.get("content") or "")
        append = safe_bool(data.get("append"), False)
        if not rel:
            return jsonify({"ok": False, "error": "path required"}), 200
        out = append_file(rel, content) if append else overwrite_file(rel, content)
        return jsonify({"ok": out.startswith("✅"), "text": out}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.post("/files/delete")
def api_files_delete():
    try:
        data = request.get_json(silent=True) or {}
        rel = str(data.get("path") or "").strip()
        hard = safe_bool(data.get("hard"), False)
        ap = _safe_abs(rel)
        if not ap:
            return jsonify({"ok": False, "error": "Access denied."}), 200
        if not os.path.exists(ap):
            return jsonify({"ok": False, "error": "path not found"}), 200

        if hard:
            if os.path.isdir(ap):
                import shutil
                shutil.rmtree(ap)
            else:
                os.remove(ap)
            _ensure_index(force=True)
            return jsonify({"ok": True, "deleted": True, "hard": True}), 200

        trash_root = os.path.join(ALLOWED_DIR, ".trash")
        os.makedirs(trash_root, exist_ok=True)
        rel_norm = rel.replace("\\", "/").lstrip("/")
        ts = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(trash_root, f"{rel_norm}__{ts}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        import shutil
        shutil.move(ap, dst)
        _ensure_index(force=True)
        return jsonify({
            "ok": True,
            "deleted": True,
            "hard": False,
            "trash": os.path.relpath(dst, ALLOWED_DIR).replace("\\", "/")
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.post("/files/mkdir")
def api_files_mkdir():
    try:
        data = request.get_json(silent=True) or {}
        rel = str(data.get("path") or "").strip()
        ap = _safe_abs(rel)
        if not ap:
            return jsonify({"ok": False, "error": "Access denied."}), 200
        os.makedirs(ap, exist_ok=True)
        return jsonify({"ok": True, "path": rel}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@app.post("/files/rename")
def api_files_rename():
    try:
        data = request.get_json(silent=True) or {}
        src = str(data.get("src") or "").strip()
        dst = str(data.get("dst") or "").strip()
        if not src or not dst:
            return jsonify({"ok": False, "error": "src/dst required"}), 200
        src_ap = _safe_abs(src)
        dst_ap = _safe_abs(dst)
        if not src_ap or not dst_ap:
            return jsonify({"ok": False, "error": "Access denied."}), 200
        if not os.path.exists(src_ap):
            return jsonify({"ok": False, "error": "src not found"}), 200
        os.makedirs(os.path.dirname(dst_ap), exist_ok=True)
        os.replace(src_ap, dst_ap)
        _ensure_index(force=True)
        return jsonify({"ok": True, "src": src, "dst": dst}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200

# ============================================================
# 23. 参数接口 + Embedding API + Profile B 整点增量 ingest
#   - /tools/save_params
#   - /tools/load_params
#   - /tools/update_config
#   - /api/embed
#   - Profile B：整点增量 ingest（offset + ingest_log）
# ============================================================


# ============================================================
# 24. API 配置（NEWAPI / Provider）——可在前端实时保存/加载
#   保存到：<项目根>/tools/api_config.json
#   同时写入：CONFIG_FILE（config.json）里的 api_config 字段（兼容你现有习惯）
# ============================================================

def _project_root_dir() -> str:
    # 以 CONFIG_FILE 所在目录作为项目根
    try:
        return os.path.dirname(CONFIG_FILE)
    except Exception:
        return os.getcwd()

def _tools_dir() -> str:
    d = os.path.join(_project_root_dir(), "tools")
    os.makedirs(d, exist_ok=True)
    return d

def _api_config_path() -> str:
    return os.path.join(_tools_dir(), "api_config.json")

def _read_api_config_file() -> Dict[str, Any]:
    # 默认来自环境变量（作为兜底）
    cfg: Dict[str, Any] = {
        "llm_provider": LLM_PROVIDER,
        "newapi_base_url": NEWAPI_BASE_URL,
        "newapi_api_key": NEWAPI_API_KEY,
        "newapi_model": NEWAPI_MODEL,
        "ollama_base_url": OLLAMA_BASE_URL,
        "ollama_model": MODEL_NAME,
    }
    try:
        p = _api_config_path()
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f) or {}
            if isinstance(obj, dict):
                cfg.update(obj)
    except Exception as e:
        print("[WARN] read api_config failed:", e)
    return cfg

def _apply_api_config_runtime(cfg: Dict[str, Any]):
    """把 api_config 写入运行时全局变量（不重启也生效）"""
    global LLM_PROVIDER, NEWAPI_BASE_URL, NEWAPI_API_KEY, NEWAPI_MODEL, OLLAMA_BASE_URL, MODEL_NAME
    try:
        if cfg.get("llm_provider"):
            LLM_PROVIDER = str(cfg["llm_provider"]).strip().lower()
        if cfg.get("newapi_base_url"):
            NEWAPI_BASE_URL = str(cfg["newapi_base_url"]).strip().rstrip("/")
        if cfg.get("newapi_api_key") is not None:
            NEWAPI_API_KEY = str(cfg.get("newapi_api_key", "")).strip()
        if cfg.get("newapi_model"):
            NEWAPI_MODEL = str(cfg["newapi_model"]).strip()

        if cfg.get("ollama_base_url"):
            OLLAMA_BASE_URL = str(cfg["ollama_base_url"]).strip()
        if cfg.get("ollama_model"):
            MODEL_NAME = str(cfg["ollama_model"]).strip()
    except Exception as e:
        print("[WARN] apply api_config runtime failed:", e)

def _write_api_config_file(cfg: Dict[str, Any]) -> None:
    p = _api_config_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def _write_api_config_into_main_config(cfg: Dict[str, Any]) -> None:
    """兼容：把 api_config 也写进 CONFIG_FILE（config.json）"""
    try:
        main = _load_config_file()
        if not isinstance(main, dict):
            main = {}
        main["api_config"] = {
            "llm_provider": cfg.get("llm_provider"),
            "newapi_base_url": cfg.get("newapi_base_url"),
            "newapi_api_key": cfg.get("newapi_api_key"),
            "newapi_model": cfg.get("newapi_model"),
            "ollama_base_url": cfg.get("ollama_base_url"),
            "ollama_model": cfg.get("ollama_model"),
        }
        _save_config_file(main)
    except Exception as e:
        print("[WARN] write api_config into config.json failed:", e)


# 启动时加载一次（如果文件存在）
try:
    _apply_api_config_runtime(_read_api_config_file())
except Exception:
    pass


@app.route("/tools/api_config", methods=["GET", "POST", "OPTIONS"])
def tools_api_config():
    if request.method == "OPTIONS":
        return ("", 204)

    if request.method == "GET":
        try:
            cfg = _read_api_config_file()
            return jsonify({"ok": True, "config": cfg}), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 200

    # POST 保存
    try:
        data = request.get_json(silent=True) or {}
        cfg = _read_api_config_file()

        # 只更新允许字段
        for k in ["llm_provider", "newapi_base_url", "newapi_api_key", "newapi_model", "ollama_base_url", "ollama_model"]:
            if k in data:
                cfg[k] = data[k]

        # 规范化
        if cfg.get("newapi_base_url"):
            cfg["newapi_base_url"] = str(cfg["newapi_base_url"]).strip().rstrip("/")
        if cfg.get("llm_provider"):
            cfg["llm_provider"] = str(cfg["llm_provider"]).strip().lower()

        _write_api_config_file(cfg)
        _write_api_config_into_main_config(cfg)
        _apply_api_config_runtime(cfg)

        return jsonify({"ok": True, "config": cfg}), 200
    except Exception as e:
        print("[ERROR] tools_api_config:", e)
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/tools/runtime_info", methods=["GET", "OPTIONS"])
def tools_runtime_info():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        # 返回 UI 顶部展示用的“当前模型名”
        if LLM_PROVIDER == "ollama":
            display_model = MODEL_NAME
        else:
            display_model = NEWAPI_MODEL
        return jsonify({
            "ok": True,
            "provider": LLM_PROVIDER,
            "display_model": display_model,
            "ollama_model": MODEL_NAME,
            "newapi_model": NEWAPI_MODEL,
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


def _build_mcp_skill_id(server_name: str, tool_name: str) -> str:
    return f"mcp::{str(server_name or '').strip()}::{str(tool_name or '').strip()}"


def _parse_mcp_skill_id(skill_id: str) -> Tuple[str, str]:
    sid = str(skill_id or "").strip()
    if not sid.startswith("mcp::"):
        return "", ""
    parts = sid.split("::", 2)
    if len(parts) != 3:
        return "", ""
    return str(parts[1] or "").strip(), str(parts[2] or "").strip()


def _refresh_runtime_mcp_skills() -> Dict[str, Any]:
    """
    Build runtime MCP skills from MCP bridge tools and merge into TYXT skills registry.
    """
    global MCP_TOOL_REGISTRY, MCP_SERVER_RUNTIME_STATUS
    summary: Dict[str, Any] = {
        "mcp_enabled": bool(MCP_BRIDGE_ENABLED),
        "servers": 0,
        "tools": 0,
        "errors": [],
    }
    MCP_TOOL_REGISTRY = {}
    MCP_SERVER_RUNTIME_STATUS = {}
    try:
        # Keep this source isolated so we do not affect future runtime skill providers.
        skills_registry.clear_runtime_skills(source="mcp")
    except Exception:
        pass

    if not MCP_BRIDGE_ENABLED:
        app.logger.info("[MCP] disabled. runtime MCP skills cleared.")
        return summary
    if MCP_BRIDGE is None:
        app.logger.warning("[MCP] bridge is not initialized.")
        return summary

    runtime_skills: List[skills_registry.SkillDescriptor] = []
    servers = MCP_BRIDGE.list_servers()
    summary["servers"] = len(servers)
    for server_name in servers:
        MCP_SERVER_RUNTIME_STATUS[str(server_name)] = {
            "server": str(server_name),
            "status": "ok",
            "error": "",
            "tool_count": 0,
        }
        try:
            tools = MCP_BRIDGE.list_tools(server_name)
        except Exception as e:
            msg = f"list_tools failed server={server_name}: {e}"
            summary["errors"].append(msg)
            app.logger.error("[MCP] %s", msg)
            MCP_SERVER_RUNTIME_STATUS[str(server_name)] = {
                "server": str(server_name),
                "status": "error",
                "error": str(e),
                "tool_count": 0,
            }
            continue
        for td in tools:
            tool_name = str(td.tool_name or "").strip()
            if not tool_name:
                continue
            skill_id = _build_mcp_skill_id(server_name, tool_name)
            schema = td.schema if isinstance(td.schema, dict) else {"type": "object"}
            if str(schema.get("type") or "").strip().lower() != "object":
                schema = {"type": "object", "properties": {"_input": {"type": "string"}}}
            runtime_skills.append(
                skills_registry.SkillDescriptor(
                    id=skill_id,
                    name=str(td.title or tool_name).strip() or tool_name,
                    version="0.1.0",
                    author=f"mcp:{server_name}",
                    description=str(td.description or "").strip(),
                    tags=["mcp", str(server_name)],
                    unsafe=False,
                    # MCP tools may perform network/file operations internally.
                    # Set conservative capability to "network=True" by default so
                    # global gate TYXT_SKILLS_ALLOW_NETWORK can still disable all MCP calls.
                    permissions={"network": True, "filesystem": False, "llm": False},
                    entry={"type": "mcp", "module": "", "function": "run"},
                    inputs=dict(schema),
                    outputs={"type": "object"},
                    dir_path="",
                    source="mcp",
                    status=skills_registry.SKILL_STATUS_NORMAL,
                    safe_status=skills_registry.SAFE_STATUS_SAFE,
                    enabled=False,
                    scan_reasons=[],
                    has_update=False,
                    update_url="",
                    skill_type=skills_registry.SKILL_TYPE_MCP,
                    server_name=str(server_name),
                    tool_name=str(tool_name),
                )
            )
            MCP_TOOL_REGISTRY[skill_id] = {
                "id": skill_id,
                "server": str(server_name),
                "server_name": str(server_name),
                "name": str(tool_name),
                "tool_name": str(tool_name),
                "title": str(td.title or tool_name).strip() or tool_name,
                "description": str(td.description or "").strip(),
                "tags": ["mcp", str(server_name)],
                "status": "normal",
                "enabled": False,
            }
        MCP_SERVER_RUNTIME_STATUS[str(server_name)]["tool_count"] = len(tools)
    summary["tools"] = len(runtime_skills)
    if runtime_skills:
        skills_registry.set_runtime_skills(runtime_skills, replace=False)
        try:
            loaded = skills_registry.load_all_skills(force=False)
            for sid, row in list(MCP_TOOL_REGISTRY.items()):
                d = loaded.get(sid)
                if d is not None:
                    row["enabled"] = bool(getattr(d, "enabled", False))
                    row["status"] = str(getattr(d, "status", "normal") or "normal")
        except Exception:
            pass
    app.logger.info("[MCP] runtime MCP skills refreshed: servers=%s tools=%s", summary["servers"], summary["tools"])
    return summary


def _init_mcp_bridge(force_enable: bool = False) -> Dict[str, Any]:
    """
    Initialize global MCP bridge from config, then refresh runtime MCP skills.
    """
    global MCP_BRIDGE, MCP_SERVER_CONFIGS, MCP_BRIDGE_ENABLED, MCP_TOOL_REGISTRY, MCP_SERVER_RUNTIME_STATUS
    cfg_obj: Dict[str, Any]
    try:
        cfg_obj = mcp_manager.load_mcp_config(TYXT_MCP_CONFIG_PATH, create_if_missing=True, logger=app.logger)
    except Exception as e:
        app.logger.error("[MCP] failed to load config from %s: %s", TYXT_MCP_CONFIG_PATH, e)
        cfg_obj = {"mcpServers": {}}
    cfg_map = mcp_manager.build_bridge_config_map(cfg_obj)

    # Inject Tavily key from global config for MCP servers when config uses
    # placeholder/empty key, so admin only needs to set key once in "API 设置".
    def _is_placeholder_tavily_key(v: Any) -> bool:
        s = str(v or "").strip()
        if not s:
            return True
        low = s.lower()
        if ("你的key" in s) or ("your key" in low) or ("your_key" in low) or ("replace_me" in low):
            return True
        return False

    try:
        ws_key = str(MODEL_CONFIG.get("web_search_api_key", "") or "").strip()
    except Exception:
        ws_key = ""
    if ws_key:
        injected = 0
        for _srv_name, _cfg in list(cfg_map.items()):
            try:
                env = dict(getattr(_cfg, "env", {}) or {})
                raw_key = str(env.get("TAVILY_API_KEY") or "").strip()
                if _is_placeholder_tavily_key(raw_key):
                    env["TAVILY_API_KEY"] = ws_key
                    _cfg.env = env
                    injected += 1
            except Exception:
                continue
        if injected:
            app.logger.info("[MCP] injected TAVILY_API_KEY from global web_search_api_key into %s server(s).", injected)

    # Auto-enable when config contains at least one valid MCP server, so
    # administrators can manage MCP from UI without requiring env toggles.
    mcp_on = bool(TYXT_MCP_ENABLED or force_enable or bool(cfg_map))
    MCP_BRIDGE_ENABLED = bool(mcp_on)
    if not mcp_on:
        MCP_SERVER_CONFIGS = {}
        MCP_BRIDGE = None
        MCP_TOOL_REGISTRY = {}
        MCP_SERVER_RUNTIME_STATUS = {}
        app.logger.info("[MCP] disabled (env=%s force=%s config_servers=%s).", TYXT_MCP_ENABLED, force_enable, len(cfg_map))
        try:
            skills_registry.clear_runtime_skills(source="mcp")
        except Exception:
            pass
        return {"ok": True, "enabled": False, "servers": 0}
    MCP_SERVER_CONFIGS = dict(cfg_map or {})
    MCP_BRIDGE = mcp_bridge.MCPBridge(MCP_SERVER_CONFIGS, logger=app.logger)
    app.logger.info("[MCP] bridge initialized. config=%s servers=%s", TYXT_MCP_CONFIG_PATH, len(MCP_SERVER_CONFIGS))
    mcp_summary = _refresh_runtime_mcp_skills()
    return {
        "ok": True,
        "enabled": True,
        "servers": len(MCP_SERVER_CONFIGS),
        "summary": mcp_summary,
    }


def _list_mcp_tools_registry_rows() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    loaded = skills_registry.load_all_skills(force=False)
    for sid in sorted(MCP_TOOL_REGISTRY.keys()):
        row = dict(MCP_TOOL_REGISTRY.get(sid) or {})
        d = loaded.get(sid)
        if d is not None:
            row["enabled"] = bool(getattr(d, "enabled", False))
            row["status"] = str(getattr(d, "status", "normal") or "normal")
            row["safe_status"] = str(getattr(d, "safe_status", "unknown") or "unknown")
        out.append(row)
    return out


def load_skill_config(skill_id: str) -> Dict[str, Any]:
    """
    Load normalized skill config from the current skills registry cache.
    """
    sid = str(skill_id or "").strip()
    if not sid:
        return {}
    skills = skills_registry.load_all_skills(force=False)
    d = skills.get(sid)
    if d is None:
        return {}
    return {
        "id": str(d.id or "").strip(),
        "name": str(d.name or "").strip(),
        "type": str(d.skill_type or skills_registry.SKILL_TYPE_PYTHON).strip().lower() or skills_registry.SKILL_TYPE_PYTHON,
        "skill_type": str(d.skill_type or skills_registry.SKILL_TYPE_PYTHON).strip().lower() or skills_registry.SKILL_TYPE_PYTHON,
        "mcp_server": str(d.server_name or "").strip(),
        "mcp_tool": str(d.tool_name or "").strip(),
        "server_name": str(d.server_name or "").strip(),
        "tool_name": str(d.tool_name or "").strip(),
        "input_schema": dict(d.inputs or {"type": "object"}),
        "inputs": dict(d.inputs or {"type": "object"}),
    }


def _validate_mcp_input_schema(schema: Dict[str, Any], user_args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    if not isinstance(schema, dict):
        return True, dict(user_args or {}), ""
    if str(schema.get("type") or "object").strip().lower() != "object":
        return True, dict(user_args or {}), ""
    payload = dict(user_args or {}) if isinstance(user_args, dict) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = list(schema.get("required") or [])

    for k, spec in props.items():
        if not isinstance(spec, dict):
            continue
        if k not in payload and ("default" in spec):
            payload[k] = spec.get("default")

    for key in required:
        if key not in payload:
            return False, {}, f"missing required param: {key}"

    for k, spec in props.items():
        if k not in payload:
            continue
        if not isinstance(spec, dict):
            continue
        expected = str(spec.get("type") or "").strip().lower()
        value = payload.get(k)
        if expected == "string" and (not isinstance(value, str)):
            return False, {}, f"invalid type for {k}: expected string"
        if expected == "integer":
            if isinstance(value, bool) or (not isinstance(value, int)):
                return False, {}, f"invalid type for {k}: expected integer"
        if expected == "number":
            if isinstance(value, bool) or (not isinstance(value, (int, float))):
                return False, {}, f"invalid type for {k}: expected number"
        if expected == "boolean" and (not isinstance(value, bool)):
            return False, {}, f"invalid type for {k}: expected boolean"
        if expected == "object" and (not isinstance(value, dict)):
            return False, {}, f"invalid type for {k}: expected object"
        if expected == "array" and (not isinstance(value, list)):
            return False, {}, f"invalid type for {k}: expected array"
    return True, payload, ""


def call_mcp_tool(server_name: str, tool_name: str, args: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
    """
    Unified MCP bridge call wrapper.
    """
    if (not MCP_BRIDGE_ENABLED) or MCP_BRIDGE is None:
        _append_mcp_skill_debug(
            "mcp_call_blocked",
            server_name=str(server_name or "").strip(),
            tool_name=str(tool_name or "").strip(),
            error="mcp_not_enabled",
        )
        return {"ok": False, "result": None, "error": "mcp_not_enabled"}
    s = str(server_name or "").strip()
    t = str(tool_name or "").strip()
    if (not s) or (not t):
        _append_mcp_skill_debug(
            "mcp_call_blocked",
            server_name=s,
            tool_name=t,
            error="mcp_skill_missing_target",
        )
        return {"ok": False, "result": None, "error": "mcp_skill_missing_target"}
    payload = dict(args or {}) if isinstance(args, dict) else {}
    wait = max(0.5, min(300.0, float(safe_float(timeout, 30.0))))
    try:
        out = MCP_BRIDGE.call_tool(server_name=s, tool_name=t, args=payload, timeout=wait)
        if not isinstance(out, dict):
            _append_mcp_skill_debug(
                "mcp_call_error",
                server_name=s,
                tool_name=t,
                error="mcp_invalid_result",
            )
            return {"ok": False, "result": None, "error": "mcp_invalid_result"}
        _append_mcp_skill_debug(
            "mcp_call_done",
            server_name=s,
            tool_name=t,
            ok=bool(out.get("ok")),
            error=str(out.get("error") or ""),
        )
        return out
    except Exception as e:
        app.logger.error("[MCP] call_mcp_tool failed server=%s tool=%s err=%s", s, t, e)
        _append_mcp_skill_debug(
            "mcp_call_error",
            server_name=s,
            tool_name=t,
            error=str(e),
        )
        return {"ok": False, "result": None, "error": str(e)}


def handle_mcp_skill(skill_id: str, user_args: Dict[str, Any], skill_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Generic MCP skill handler (config-driven).
    """
    sid = str(skill_id or "").strip()
    cfg = dict(skill_cfg or {}) if isinstance(skill_cfg, dict) else load_skill_config(sid)
    _append_mcp_skill_debug(
        "mcp_dispatch_start",
        skill_id=sid,
        arg_keys=sorted(list((user_args or {}).keys())) if isinstance(user_args, dict) else [],
    )
    if not cfg:
        _append_mcp_skill_debug("mcp_dispatch_error", skill_id=sid, error="skill_not_found")
        return {"ok": False, "data": None, "error": "skill_not_found"}
    st = str(cfg.get("type") or cfg.get("skill_type") or "").strip().lower()
    if st != skills_registry.SKILL_TYPE_MCP:
        _append_mcp_skill_debug("mcp_dispatch_error", skill_id=sid, error="not_mcp_skill")
        return {"ok": False, "data": None, "error": "not_mcp_skill"}

    server_name = str(cfg.get("mcp_server") or cfg.get("server_name") or "").strip()
    tool_name = str(cfg.get("mcp_tool") or cfg.get("tool_name") or "").strip()
    if (not server_name) or (not tool_name):
        sid_server, sid_tool = _parse_mcp_skill_id(sid)
        server_name = server_name or sid_server
        tool_name = tool_name or sid_tool
    if (not server_name) or (not tool_name):
        _append_mcp_skill_debug("mcp_dispatch_error", skill_id=sid, error="mcp_skill_missing_target")
        return {"ok": False, "data": None, "error": "mcp_skill_missing_target"}

    payload = dict(user_args or {}) if isinstance(user_args, dict) else {}
    timeout = safe_float(payload.pop("__timeout", 30.0), 30.0)
    timeout = max(0.5, min(300.0, float(timeout)))
    input_schema = cfg.get("input_schema") if isinstance(cfg.get("input_schema"), dict) else cfg.get("inputs")
    ok_inputs, clean_args, input_err = _validate_mcp_input_schema(input_schema if isinstance(input_schema, dict) else {"type": "object"}, payload)
    if not ok_inputs:
        _append_mcp_skill_debug(
            "mcp_dispatch_error",
            skill_id=sid,
            server_name=server_name,
            tool_name=tool_name,
            error=input_err or "invalid_params",
        )
        return {"ok": False, "data": None, "error": input_err or "invalid_params"}

    app.logger.info("[MCP] unified handler skill=%s server=%s tool=%s", sid, server_name, tool_name)
    _append_mcp_skill_debug(
        "mcp_dispatch_call",
        skill_id=sid,
        server_name=server_name,
        tool_name=tool_name,
    )
    result = call_mcp_tool(server_name=server_name, tool_name=tool_name, args=clean_args, timeout=timeout)
    if not isinstance(result, dict):
        _append_mcp_skill_debug(
            "mcp_dispatch_error",
            skill_id=sid,
            server_name=server_name,
            tool_name=tool_name,
            error="mcp_invalid_result",
        )
        return {"ok": False, "data": None, "error": "mcp_invalid_result"}
    if not safe_bool(result.get("ok"), False):
        err = str(result.get("error") or "mcp_call_failed")
        app.logger.warning("[MCP] tool failed server=%s tool=%s err=%s", server_name, tool_name, err)
        _append_mcp_skill_debug(
            "mcp_dispatch_error",
            skill_id=sid,
            server_name=server_name,
            tool_name=tool_name,
            error=err,
        )
        return {"ok": False, "data": result.get("result"), "error": err}
    _append_mcp_skill_debug(
        "mcp_dispatch_ok",
        skill_id=sid,
        server_name=server_name,
        tool_name=tool_name,
    )
    return {"ok": True, "data": result.get("result"), "error": ""}


def _run_mcp_skill(
    skill_desc: skills_registry.SkillDescriptor,
    params: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Skills registry runner for MCP skill type.
    """
    del context
    cfg = {
        "id": str(skill_desc.id or "").strip(),
        "type": skills_registry.SKILL_TYPE_MCP,
        "skill_type": skills_registry.SKILL_TYPE_MCP,
        "mcp_server": str(skill_desc.server_name or "").strip(),
        "mcp_tool": str(skill_desc.tool_name or "").strip(),
        "server_name": str(skill_desc.server_name or "").strip(),
        "tool_name": str(skill_desc.tool_name or "").strip(),
        "input_schema": dict(skill_desc.inputs or {"type": "object"}),
        "inputs": dict(skill_desc.inputs or {"type": "object"}),
    }
    return handle_mcp_skill(str(skill_desc.id or "").strip(), params if isinstance(params, dict) else {}, skill_cfg=cfg)


skills_registry.register_skill_runner(skills_registry.SKILL_TYPE_MCP, _run_mcp_skill)
try:
    _init_mcp_bridge()
except Exception as _mcp_init_e:
    app.logger.error("[MCP] init failed: %s", _mcp_init_e)


def _build_skill_caps() -> Dict[str, bool]:
    return {
        "network": bool(TYXT_SKILLS_ALLOW_NETWORK),
        "filesystem": bool(TYXT_SKILLS_ALLOW_FILESYSTEM),
        "llm": bool(TYXT_SKILLS_ALLOW_LLM),
    }


def _build_skill_exec_context(payload: Dict[str, Any], user_id: str, role: str) -> Dict[str, Any]:
    p = payload if isinstance(payload, dict) else {}
    meta = p.get("meta") if isinstance(p.get("meta"), dict) else {}
    scene = str(
        p.get("scene")
        or p.get("channel_type")
        or (meta.get("scene") if isinstance(meta, dict) else "")
        or "local"
    ).strip().lower() or "local"
    owner_id = str(
        p.get("owner_id")
        or p.get("group_id")
        or (meta.get("owner_id") if isinstance(meta, dict) else "")
        or (meta.get("group_id") if isinstance(meta, dict) else "")
        or user_id
    ).strip() or user_id
    return {
        "user_id": str(user_id or "").strip(),
        "role": "admin" if str(role or "").strip().lower() == "admin" else "user",
        "scene": scene,
        "channel_type": scene,
        "owner_id": owner_id,
        "meta": dict(meta) if isinstance(meta, dict) else {},
        "shared_root": str(ALLOWED_DIR or ""),
        "import_dir": str(IMPORT_DROP_DIR or ""),
        "__caps": _build_skill_caps(),
    }


@app.route("/tools/skills/list", methods=["GET", "OPTIONS"])
def tools_skills_list():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        req_payload = request.args.to_dict(flat=True) if request.args else {}
        uid, role, _nick = _resolve_request_user_ctx(req_payload)
        if not uid:
            return jsonify({"ok": False, "msg": "Not logged in", "skills": []}), 401
        admin_view = str(role or "").strip().lower() == "admin"
        rows = skills_registry.list_skills(admin_view=admin_view)
        out: Dict[str, Any] = {"ok": True, "skills": rows, "admin_view": bool(admin_view)}
        if admin_view:
            out["summary"] = skills_registry.get_scan_summary()
        return jsonify(out), 200
    except Exception as e:
        print(f"[tools/skills/list error] {e}")
        return jsonify({"ok": False, "msg": f"Failed to load skills: {e}", "skills": []}), 200


@app.route("/admin/mcp/config", methods=["GET", "OPTIONS"])
def admin_mcp_config_get():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        cfg = mcp_manager.load_mcp_config(TYXT_MCP_CONFIG_PATH, create_if_missing=True, logger=app.logger)
        text = mcp_manager.dump_mcp_config_text(cfg)
        return jsonify(
            {
                "ok": True,
                "config_path": TYXT_MCP_CONFIG_PATH,
                "config_text": text,
            }
        ), 200
    except Exception as e:
        app.logger.error("[MCP] /admin/mcp/config error: %s", e)
        return jsonify({"ok": False, "error": f"Load config failed: {e}", "detail": str(e)}), 200


@app.route("/admin/mcp/config/save", methods=["POST", "OPTIONS"])
def admin_mcp_config_save():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        data = request.get_json(silent=True) or {}
        raw_text = str(data.get("config_text") or "").strip()
        if not raw_text:
            return jsonify({"ok": False, "error": "config_text is empty", "detail": ""}), 200

        parsed = mcp_manager.save_mcp_config(raw_text, TYXT_MCP_CONFIG_PATH, logger=app.logger)
        init_result = _init_mcp_bridge()
        skills_registry.reload_skills()
        tool_rows = _list_mcp_tools_registry_rows()
        return jsonify(
            {
                "ok": True,
                "message": "保存并重载成功",
                "server_count": int(len(MCP_SERVER_CONFIGS)),
                "tool_count": int(len(tool_rows)),
                "config_text": mcp_manager.dump_mcp_config_text(parsed),
                "result": init_result,
            }
        ), 200
    except json.JSONDecodeError as e:
        return jsonify({"ok": False, "error": f"JSON 解析失败: {e}", "detail": str(e)}), 200
    except Exception as e:
        app.logger.error("[MCP] /admin/mcp/config/save error: %s", e)
        return jsonify({"ok": False, "error": f"保存失败: {e}", "detail": str(e)}), 200


@app.route("/admin/mcp/tools", methods=["GET", "OPTIONS"])
def admin_mcp_tools():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        tools = _list_mcp_tools_registry_rows()
        servers = [dict(v or {}) for _, v in sorted(MCP_SERVER_RUNTIME_STATUS.items(), key=lambda x: str(x[0]))]
        return jsonify(
            {
                "ok": True,
                "enabled": bool(MCP_BRIDGE_ENABLED),
                "tools": tools,
                "server_status": servers,
            }
        ), 200
    except Exception as e:
        app.logger.error("[MCP] /admin/mcp/tools error: %s", e)
        return jsonify({"ok": False, "error": f"Load MCP tools failed: {e}", "tools": []}), 200


@app.route("/tools/mcp/status", methods=["GET", "OPTIONS"])
def tools_mcp_status():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        servers = sorted(list(MCP_SERVER_CONFIGS.keys()))
        return jsonify(
            {
                "ok": True,
                "enabled": bool(MCP_BRIDGE_ENABLED),
                "env_enabled": bool(TYXT_MCP_ENABLED),
                "config_path": TYXT_MCP_CONFIG_PATH,
                "servers": servers,
                "server_count": len(servers),
            }
        ), 200
    except Exception as e:
        app.logger.error("[MCP] /tools/mcp/status error: %s", e)
        return jsonify({"ok": False, "msg": f"MCP status failed: {e}"}), 200


@app.route("/tools/mcp/reload", methods=["POST", "OPTIONS"])
def tools_mcp_reload():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        init_result = _init_mcp_bridge()
        skills_registry.reload_skills()
        return jsonify({"ok": True, "result": init_result}), 200
    except Exception as e:
        app.logger.error("[MCP] /tools/mcp/reload error: %s", e)
        return jsonify({"ok": False, "msg": f"MCP reload failed: {e}"}), 200


@app.route("/tools/mcp/tools", methods=["GET", "OPTIONS"])
def tools_mcp_tools():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        if not MCP_BRIDGE_ENABLED:
            return jsonify({"ok": False, "msg": "MCP not enabled", "tools": []}), 200
        if MCP_BRIDGE is None:
            return jsonify({"ok": False, "msg": "MCP bridge not initialized", "tools": []}), 200
        q = request.args.to_dict(flat=True) if request.args else {}
        server_name = str((q or {}).get("server_name") or "").strip()
        if not server_name:
            return jsonify({"ok": False, "msg": "Missing server_name", "tools": []}), 200
        rows = MCP_BRIDGE.list_tools(server_name)
        tools = [
            {
                "server_name": str(x.server_name),
                "tool_name": str(x.tool_name),
                "title": str(x.title),
                "description": str(x.description),
                "schema": dict(x.schema or {"type": "object"}),
            }
            for x in rows
        ]
        return jsonify({"ok": True, "server_name": server_name, "tools": tools}), 200
    except Exception as e:
        app.logger.error("[MCP] /tools/mcp/tools error: %s", e)
        return jsonify({"ok": False, "msg": f"List MCP tools failed: {e}", "tools": []}), 200


@app.route("/tools/mcp/call", methods=["POST", "OPTIONS"])
def tools_mcp_call():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        if not MCP_BRIDGE_ENABLED:
            return jsonify({"ok": False, "msg": "MCP not enabled", "result": {"ok": False, "result": None, "error": "mcp_not_enabled"}}), 200
        if MCP_BRIDGE is None:
            return jsonify({"ok": False, "msg": "MCP bridge not initialized", "result": {"ok": False, "result": None, "error": "mcp_not_initialized"}}), 200
        data = request.get_json(silent=True) or {}
        server_name = str(data.get("server_name") or "").strip()
        tool_name = str(data.get("tool_name") or "").strip()
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        timeout = safe_float(data.get("timeout"), 30.0)
        timeout = max(0.5, min(300.0, float(timeout)))
        if not server_name or not tool_name:
            return jsonify({"ok": False, "msg": "Missing server_name or tool_name", "result": {"ok": False, "result": None, "error": "missing_target"}}), 200
        result = MCP_BRIDGE.call_tool(server_name=server_name, tool_name=tool_name, args=args, timeout=timeout)
        return jsonify({"ok": True, "server_name": server_name, "tool_name": tool_name, "result": result}), 200
    except Exception as e:
        app.logger.error("[MCP] /tools/mcp/call error: %s", e)
        return jsonify({"ok": False, "msg": f"Call MCP tool failed: {e}", "result": {"ok": False, "result": None, "error": str(e)}}), 200


@app.route("/tools/mcp/skill_debug_logs", methods=["GET", "OPTIONS"])
def tools_mcp_skill_debug_logs():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        q = request.args.to_dict(flat=True) if request.args else {}
        limit = max(1, min(500, safe_int((q or {}).get("limit"), 80)))
        logs = _get_mcp_skill_debug_logs(limit)
        return jsonify(
            {
                "ok": True,
                "enabled": bool(MCP_SKILL_DEBUG_ENABLED),
                "limit": limit,
                "count": len(logs),
                "logs": logs,
            }
        ), 200
    except Exception as e:
        app.logger.error("[MCP] /tools/mcp/skill_debug_logs error: %s", e)
        return jsonify({"ok": False, "msg": f"Load MCP debug logs failed: {e}", "logs": []}), 200


@app.route("/tools/skills/toggle", methods=["POST", "OPTIONS"])
def tools_skills_toggle():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        data = request.get_json(silent=True) or {}
        skill_id = str(data.get("skill_id") or "").strip()
        enabled = safe_bool(data.get("enabled"), False)
        if not skill_id:
            return jsonify({"ok": False, "msg": "Missing skill_id"}), 200
        ok, reason, skill_row = skills_registry.set_skill_enabled(skill_id, enabled)
        if not ok:
            return jsonify({"ok": False, "msg": reason or "toggle_failed", "skill": skill_row}), 200
        warning = ""
        if enabled and isinstance(skill_row, dict):
            if str(skill_row.get("safe_status") or "").strip().lower() == "warning":
                warning = "This skill has warning-level risk signals."
        return jsonify({"ok": True, "skill": skill_row, "warning": warning}), 200
    except Exception as e:
        print(f"[tools/skills/toggle error] {e}")
        return jsonify({"ok": False, "msg": f"Toggle failed: {e}"}), 200


@app.route("/tools/skills/uninstall", methods=["POST", "OPTIONS"])
def tools_skills_uninstall():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        data = request.get_json(silent=True) or {}
        skill_id = str(data.get("skill_id") or "").strip()
        if not skill_id:
            return jsonify({"ok": False, "msg": "Missing skill_id"}), 200
        ok, reason = skills_registry.uninstall_skill(skill_id)
        if not ok:
            return jsonify({"ok": False, "msg": reason or "uninstall_failed"}), 200
        return jsonify({"ok": True, "skill_id": skill_id}), 200
    except Exception as e:
        print(f"[tools/skills/uninstall error] {e}")
        return jsonify({"ok": False, "msg": f"Uninstall failed: {e}"}), 200


@app.route("/tools/skills/run", methods=["POST", "OPTIONS"])
def tools_skills_run():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(silent=True) or {}
        skill_id = str(data.get("skill_id") or "").strip()
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        uid, role, _nick = _resolve_request_user_ctx(data)
        if not uid:
            return jsonify({"ok": False, "msg": "Not logged in", "result": {"ok": False, "data": None, "error": "not_logged_in"}}), 401
        if not skill_id:
            return jsonify({"ok": False, "msg": "Missing skill_id", "result": {"ok": False, "data": None, "error": "missing_skill_id"}}), 200

        skill_ctx = _build_skill_exec_context(data, uid, role)
        result = skills_registry.run_skill(skill_id=skill_id, params=params, context=skill_ctx)
        return jsonify({"ok": True, "skill_id": skill_id, "result": result}), 200
    except Exception as e:
        print(f"[tools/skills/run error] {e}")
        return jsonify({"ok": False, "msg": f"Skill run failed: {e}", "result": {"ok": False, "data": None, "error": str(e)}}), 200


@app.route("/tools/skills/rescan", methods=["POST", "OPTIONS"])
def tools_skills_rescan():
    if request.method == "OPTIONS":
        return ("", 204)
    admin_uid, err = _require_admin_session()
    if err is not None:
        return err
    del admin_uid
    try:
        mcp_summary = _refresh_runtime_mcp_skills() if MCP_BRIDGE_ENABLED else {"mcp_enabled": False, "servers": 0, "tools": 0, "errors": []}
        skills_registry.reload_skills()
        rows = skills_registry.list_skills(admin_view=True)
        summary = skills_registry.get_scan_summary()
        return jsonify({"ok": True, "skills": rows, "summary": summary, "mcp_summary": mcp_summary}), 200
    except Exception as e:
        print(f"[tools/skills/rescan error] {e}")
        return jsonify({"ok": False, "msg": f"Rescan failed: {e}"}), 200


@app.route("/tools/list_chat_contexts", methods=["GET", "OPTIONS"])
def tools_list_chat_contexts():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        req_payload = request.args.to_dict(flat=True) if request.args else {}
        ctx_user_id, _ctx_role, _ctx_nick = get_current_user_ctx(req_payload)
        body_uid = str((req_payload or {}).get("user_id") or "").strip()
        user_id = str(ctx_user_id or body_uid).strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id is empty", "titles": []}), 200

        titles = _list_private_chat_context_titles(user_id)
        return jsonify({
            "ok": True,
            "scene": "private",
            "user_id": user_id,
            "titles": titles,
        }), 200
    except Exception as e:
        print("[ERROR] tools_list_chat_contexts:", e)
        return jsonify({"ok": False, "msg": str(e), "titles": []}), 200


@app.route("/tools/get_chat_context", methods=["GET", "OPTIONS"])
def tools_get_chat_context():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        req_payload = request.args.to_dict(flat=True) if request.args else {}
        ctx_user_id, _ctx_role, _ctx_nick = get_current_user_ctx(req_payload)
        body_uid = str((req_payload or {}).get("user_id") or "").strip()
        user_id = str(ctx_user_id or body_uid).strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id is empty", "messages": []}), 200

        chat_title_raw = str((req_payload or {}).get("chat_title") or "").strip()
        if not chat_title_raw:
            return jsonify({"ok": False, "msg": "chat_title is empty", "messages": []}), 200

        max_turns = safe_int((req_payload or {}).get("max_turns"), 200)
        if max_turns <= 0:
            max_turns = 200

        safe_title = _safe_fs_name(chat_title_raw, "default")
        msgs = _load_private_chat_context_messages(user_id, safe_title, max_turns=max_turns)
        return jsonify({
            "ok": True,
            "scene": "private",
            "user_id": str(user_id),
            "chat_title": safe_title,
            "messages": msgs,
        }), 200
    except Exception as e:
        print("[ERROR] tools_get_chat_context:", e)
        return jsonify({"ok": False, "msg": str(e), "messages": []}), 200


@app.route("/tools/export_chat_context", methods=["GET", "OPTIONS"])
def tools_export_chat_context():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        req_payload = request.args.to_dict(flat=True) if request.args else {}
        ctx_user_id, _ctx_role, _ctx_nick = get_current_user_ctx(req_payload)
        body_uid = str((req_payload or {}).get("user_id") or "").strip()
        user_id = str(ctx_user_id or body_uid).strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id is empty", "text": ""}), 200

        chat_title_raw = str((req_payload or {}).get("chat_title") or "").strip()
        if not chat_title_raw:
            return jsonify({"ok": False, "msg": "chat_title is empty", "text": ""}), 200

        p, safe_title = _resolve_private_chat_context_file(user_id, chat_title_raw)
        if (not p) or (not os.path.exists(p)):
            return jsonify({"ok": False, "msg": "chat context file not found", "text": ""}), 200

        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read() or ""

        filename = f"{_safe_id_token(user_id, 'user')}_{safe_title}_full_context.txt"
        return jsonify({
            "ok": True,
            "scene": "private",
            "user_id": str(user_id),
            "chat_title": safe_title,
            "filename": filename,
            "text": raw,
        }), 200
    except Exception as e:
        print("[ERROR] tools_export_chat_context:", e)
        return jsonify({"ok": False, "msg": str(e), "text": ""}), 200


@app.route("/tools/soft_delete_chat_context_memory", methods=["POST", "OPTIONS"])
def tools_soft_delete_chat_context_memory():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(silent=True) or {}
        ctx_user_id, _ctx_role, _ctx_nick = get_current_user_ctx(data)
        body_uid = str((data or {}).get("user_id") or "").strip()
        user_id = str(ctx_user_id or body_uid).strip()
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id is empty"}), 200

        scene = str((data or {}).get("scene") or "private").strip().lower()
        if scene != "private":
            return jsonify({"ok": True, "msg": "scene_not_private_skip", "deleted_count": 0}), 200

        chat_title_raw = str((data or {}).get("chat_title") or (data or {}).get("title") or "").strip()
        if not chat_title_raw:
            return jsonify({"ok": False, "msg": "chat_title is empty"}), 200

        safe_title = _safe_fs_name(chat_title_raw, "default")
        msgs = _load_private_chat_context_messages(user_id, safe_title, max_turns=5000)
        turn_pairs = _build_turn_pairs_from_messages(msgs, max_turns=5000)
        if not turn_pairs:
            return jsonify(
                {
                    "ok": True,
                    "user_id": user_id,
                    "chat_title": safe_title,
                    "deleted_count": 0,
                    "matched_count": 0,
                    "turn_count": 0,
                    "msg": "no_turn_pairs",
                }
            ), 200

        owner_id = str(user_id)
        target_norm_texts = set()
        target_fingerprints = set()
        for u_text, a_text in turn_pairs:
            merged_text = f"用户说：{str(u_text or '').strip()}\nAI 回复：{str(a_text or '').strip()}".strip()
            norm_text = _normalize_for_fingerprint(merged_text)
            if not norm_text:
                continue
            target_norm_texts.add(norm_text)
            fp_src = f"{owner_id}|{norm_text}"
            fp = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:16]
            target_fingerprints.add(fp)

        if not target_norm_texts:
            return jsonify(
                {
                    "ok": True,
                    "user_id": user_id,
                    "chat_title": safe_title,
                    "deleted_count": 0,
                    "matched_count": 0,
                    "turn_count": len(turn_pairs),
                    "msg": "no_valid_turn_pairs",
                }
            ), 200

        page = 1
        page_size = 100
        scanned = 0
        max_scan = max(1000, min(20000, safe_int((data or {}).get("max_scan"), 8000)))
        matched_ids: List[str] = []

        while scanned < max_scan:
            got = CHAT_MEM_STORE.list_records(
                channel_type="private",
                owner_id=owner_id,
                page=page,
                page_size=page_size,
                include_deleted=True,
            )
            recs = list(got.get("records") or [])
            if not recs:
                break

            for rec in recs:
                scanned += 1
                if scanned > max_scan:
                    break
                rid = str(getattr(rec, "id", "") or "").strip()
                if not rid:
                    continue
                meta = dict(getattr(rec, "metadata", {}) or {})
                if bool(meta.get("deleted", False)):
                    continue

                fp = str(meta.get("fingerprint") or "").strip()
                if fp and fp in target_fingerprints:
                    matched_ids.append(rid)
                    continue

                text_full = str(getattr(rec, "text", "") or "")
                if text_full:
                    norm_full = _normalize_for_fingerprint(text_full)
                    if norm_full in target_norm_texts:
                        matched_ids.append(rid)
                        continue

                uu, aa = _extract_turn_pair_from_memory_text(text_full)
                if uu and aa:
                    merged = f"用户说：{uu}\nAI 回复：{aa}".strip()
                    if _normalize_for_fingerprint(merged) in target_norm_texts:
                        matched_ids.append(rid)
                        continue

            page += 1
            if len(recs) < page_size:
                break

        uniq_ids = sorted(set([x for x in matched_ids if x]))
        deleted_ok = 0
        for mid in uniq_ids:
            try:
                ok = CHAT_MEM_STORE.soft_delete(
                    channel_type="private",
                    owner_id=owner_id,
                    mem_id=mid,
                    deleted=True,
                    deleted_by=user_id,
                )
                if ok:
                    deleted_ok += 1
            except Exception:
                continue

        return jsonify(
            {
                "ok": True,
                "user_id": user_id,
                "chat_title": safe_title,
                "turn_count": len(turn_pairs),
                "matched_count": len(uniq_ids),
                "deleted_count": int(deleted_ok),
                "scanned_count": int(scanned),
            }
        ), 200
    except Exception as e:
        print("[ERROR] tools_soft_delete_chat_context_memory:", e)
        return jsonify({"ok": False, "msg": str(e)}), 200


@app.route("/tools/save_params", methods=["POST", "OPTIONS"])
def api_save_params():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        global MODEL_NAME
        data = request.get_json(silent=True) or {}
        prev_web_search_api_key = str(MODEL_CONFIG.get("web_search_api_key", "") or "").strip()

        def _as_int(k, default):
            try:
                return int(data.get(k, default))
            except Exception:
                return int(default)

        def _as_float(k, default):
            try:
                return float(data.get(k, default))
            except Exception:
                return float(default)

        def _as_str(k, default):
            try:
                v = data.get(k, default)
                return str(v).strip()
            except Exception:
                return str(default or "").strip()

        def _as_bool(k, default):
            try:
                return safe_bool(data.get(k, default), bool(default))
            except Exception:
                return bool(default)

        next_ollama_model = _as_str("ollama_model", MODEL_CONFIG.get("ollama_model", MODEL_NAME))
        if not next_ollama_model:
            next_ollama_model = str(MODEL_NAME or "").strip()
        raw_mode_in = data.get("web_search_mode", None)
        if raw_mode_in is None or str(raw_mode_in).strip() == "":
            next_web_search_mode = "default" if _as_bool("web_search_enabled", MODEL_CONFIG.get("web_search_enabled", False)) else "off"
        else:
            next_web_search_mode = _normalize_web_search_mode(
                _as_str("web_search_mode", MODEL_CONFIG.get("web_search_mode", "off"))
            )

        MODEL_CONFIG.update({
            "top_k": _as_int("top_k", MODEL_CONFIG.get("top_k", GEN_TOP_K)),
            "max_tokens": _as_int("max_tokens", MODEL_CONFIG.get("max_tokens", GEN_MAX_TOKENS)),
            "temperature": _as_float("temperature", MODEL_CONFIG.get("temperature", GEN_TEMP)),
            "top_p": _as_float("top_p", MODEL_CONFIG.get("top_p", GEN_TOP_P)),
            "ctx_size": _as_int("ctx_size", MODEL_CONFIG.get("ctx_size", 8192)),
            "context_turn_limit": _as_int("context_turn_limit", MODEL_CONFIG.get("context_turn_limit", CONTEXT_TURN_LIMIT_DEFAULT)),
            "window_display_turn_limit": _as_int("window_display_turn_limit", MODEL_CONFIG.get("window_display_turn_limit", WINDOW_DISPLAY_TURN_LIMIT_DEFAULT)),
            "chat_stream_enabled": _as_bool("chat_stream_enabled", MODEL_CONFIG.get("chat_stream_enabled", CHAT_STREAM_ENABLED_DEFAULT)),
            "web_search_enabled": bool(next_web_search_mode != "off"),
            "web_search_mode": next_web_search_mode,
            "web_search_provider": _normalize_web_search_provider(_as_str("web_search_provider", MODEL_CONFIG.get("web_search_provider", "builtin"))),
            "web_search_api_key": _as_str("web_search_api_key", MODEL_CONFIG.get("web_search_api_key", "")),
            "ollama_model": next_ollama_model,
        })
        MODEL_NAME = next_ollama_model

        _save_config_file(MODEL_CONFIG)
        if prev_web_search_api_key != str(MODEL_CONFIG.get("web_search_api_key", "") or "").strip():
            try:
                _init_mcp_bridge()
                skills_registry.reload_skills()
            except Exception as e:
                print("[WARN] mcp reload after web_search_api_key change failed:", e)
        # 同步到 api_config，避免重启后回退到旧模型
        try:
            api_cfg = _read_api_config_file()
            api_cfg["ollama_model"] = MODEL_NAME
            _write_api_config_file(api_cfg)
            _write_api_config_into_main_config(api_cfg)
        except Exception:
            pass
        return jsonify({"ok": True, "config": MODEL_CONFIG}), 200

    except Exception as e:
        print("[ERROR] api_save_params:", e)
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/tools/load_params", methods=["GET", "OPTIONS"])
def api_load_params():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        cfg = dict(MODEL_CONFIG or {})
        if not cfg:
            cfg = _load_config_file()
        return jsonify({"ok": True, "config": cfg}), 200
    except Exception as e:
        print("[ERROR] api_load_params:", e)
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/tools/update_config", methods=["POST", "OPTIONS"])
def api_update_config():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        global MODEL_NAME
        data = request.get_json(silent=True) or {}
        prev_web_search_api_key = str(MODEL_CONFIG.get("web_search_api_key", "") or "").strip()

        def _get_int(k, default):
            try:
                return int(data.get(k, default))
            except Exception:
                return int(default)

        def _get_float(k, default):
            try:
                return float(data.get(k, default))
            except Exception:
                return float(default)

        def _get_str(k, default):
            try:
                v = data.get(k, default)
                return str(v).strip()
            except Exception:
                return str(default or "").strip()

        def _get_bool(k, default):
            try:
                return safe_bool(data.get(k, default), bool(default))
            except Exception:
                return bool(default)

        next_ollama_model = _get_str("ollama_model", MODEL_CONFIG.get("ollama_model", MODEL_NAME))
        if not next_ollama_model:
            next_ollama_model = str(MODEL_NAME or "").strip()
        raw_mode_in = data.get("web_search_mode", None)
        if raw_mode_in is None or str(raw_mode_in).strip() == "":
            next_web_search_mode = "default" if _get_bool("web_search_enabled", MODEL_CONFIG.get("web_search_enabled", False)) else "off"
        else:
            next_web_search_mode = _normalize_web_search_mode(
                _get_str("web_search_mode", MODEL_CONFIG.get("web_search_mode", "off"))
            )

        MODEL_CONFIG.update({
            "top_k": _get_int("top_k", MODEL_CONFIG.get("top_k", GEN_TOP_K)),
            "max_tokens": _get_int("max_tokens", MODEL_CONFIG.get("max_tokens", GEN_MAX_TOKENS)),
            "temperature": _get_float("temperature", MODEL_CONFIG.get("temperature", GEN_TEMP)),
            "top_p": _get_float("top_p", MODEL_CONFIG.get("top_p", GEN_TOP_P)),
            "ctx_size": _get_int("ctx_size", MODEL_CONFIG.get("ctx_size", 8192)),
            "context_turn_limit": _get_int("context_turn_limit", MODEL_CONFIG.get("context_turn_limit", CONTEXT_TURN_LIMIT_DEFAULT)),
            "window_display_turn_limit": _get_int("window_display_turn_limit", MODEL_CONFIG.get("window_display_turn_limit", WINDOW_DISPLAY_TURN_LIMIT_DEFAULT)),
            "chat_stream_enabled": _get_bool("chat_stream_enabled", MODEL_CONFIG.get("chat_stream_enabled", CHAT_STREAM_ENABLED_DEFAULT)),
            "web_search_enabled": bool(next_web_search_mode != "off"),
            "web_search_mode": next_web_search_mode,
            "web_search_provider": _normalize_web_search_provider(_get_str("web_search_provider", MODEL_CONFIG.get("web_search_provider", "builtin"))),
            "web_search_api_key": _get_str("web_search_api_key", MODEL_CONFIG.get("web_search_api_key", "")),
            "ollama_model": next_ollama_model,
        })
        MODEL_NAME = next_ollama_model

        _save_config_file(MODEL_CONFIG)
        if prev_web_search_api_key != str(MODEL_CONFIG.get("web_search_api_key", "") or "").strip():
            try:
                _init_mcp_bridge()
                skills_registry.reload_skills()
            except Exception as e:
                print("[WARN] mcp reload after web_search_api_key change failed:", e)
        try:
            api_cfg = _read_api_config_file()
            api_cfg["ollama_model"] = MODEL_NAME
            _write_api_config_file(api_cfg)
            _write_api_config_into_main_config(api_cfg)
        except Exception:
            pass
        return jsonify({"ok": True, "config": MODEL_CONFIG}), 200

    except Exception as e:
        print("[ERROR] api_update_config:", e)
        return jsonify({"ok": False, "error": str(e)}), 200


@app.route("/tools/rename_chat_context", methods=["POST", "OPTIONS"])
def tools_rename_chat_context():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(silent=True) or {}
        ctx_user_id, _ctx_role, _ctx_nick = get_current_user_ctx(data)

        scene = str(data.get("scene") or "private").strip().lower()
        old_title = str(data.get("old_title") or "").strip()
        new_title = str(data.get("new_title") or "").strip()
        body_uid = str(data.get("user_id") or "").strip()
        user_id = str(ctx_user_id or body_uid).strip()

        if scene != "private":
            return jsonify({"ok": True, "msg": "scene_not_private_skip"}), 200
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id is empty"}), 200
        if not new_title:
            return jsonify({"ok": False, "msg": "new_title is empty"}), 200

        result = _rename_private_chat_context_file(user_id, old_title or "default", new_title)
        return jsonify(result), 200
    except Exception as e:
        print("[ERROR] tools_rename_chat_context:", e)
        return jsonify({"ok": False, "msg": str(e)}), 200


@app.route("/tools/delete_chat_context", methods=["POST", "OPTIONS"])
def tools_delete_chat_context():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(silent=True) or {}
        ctx_user_id, _ctx_role, _ctx_nick = get_current_user_ctx(data)

        scene = str(data.get("scene") or "private").strip().lower()
        chat_title = str(data.get("chat_title") or data.get("title") or "").strip()
        body_uid = str(data.get("user_id") or "").strip()
        user_id = str(ctx_user_id or body_uid).strip()

        if scene != "private":
            return jsonify({"ok": True, "msg": "scene_not_private_skip"}), 200
        if not user_id:
            return jsonify({"ok": False, "msg": "user_id is empty"}), 200
        if not chat_title:
            return jsonify({"ok": False, "msg": "chat_title is empty"}), 200

        result = _delete_private_chat_context_file(user_id, chat_title)
        return jsonify(result), 200
    except Exception as e:
        print("[ERROR] tools_delete_chat_context:", e)
        return jsonify({"ok": False, "msg": str(e)}), 200


# ========= 嵌入接口（兼容第三方客户端 / 自建调用） =========
@app.route("/api/embed", methods=["POST"])
def embed_text():
    data = request.get_json(force=True) or {}
    texts = data.get("texts") or data.get("input") or []
    if isinstance(texts, str):
        texts = [texts]
    if not texts:
        return jsonify({"error": "No texts provided"}), 400

    model = get_embedding_model()
    result = model.encode(list(texts), batch_size=int(os.getenv("EMBED_BATCH_SIZE", "32")), max_length=int(os.getenv("EMBED_MAX_LENGTH", "512")))
    embeddings = result.get("dense_vecs")
    if embeddings is None:
        return jsonify({"error": "embedding failed"}), 500

    return jsonify({"embeddings": embeddings.tolist()}), 200


# ===================== Profile B：整点后台增量 ingest =====================

def _profile_b_offset_paths():
    group_dir = _runtime_group_dir(PROFILE_B_GROUP_ID)
    offset_path = os.path.join(group_dir, "ingest_offset.json")
    ingest_log  = os.path.join(group_dir, "ingest_log.txt")
    group_file  = _runtime_group_chat_path(PROFILE_B_GROUP_ID)  # ✅ 与 save_chat 对齐
    return group_file, offset_path, ingest_log

def _load_ingest_offset(path: str) -> int:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            return int(obj.get("byte", 0))
    except Exception:
        pass
    return 0

def _save_ingest_offset(path: str, byte_pos: int):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"byte": int(byte_pos), "ts": int(time.time())}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _append_ingest_log(path: str, line: str):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line.rstrip() + "\n")
    except Exception:
        pass

def _extract_text_blocks_for_ingest(raw: str) -> list[str]:
    """
    Profile B：全量导入（群友+你+bot）
    但不导入图片/视频/表情包等（常见是 CQ 码）
    """
    if not raw:
        return []

    sep = "\n" + "-" * 60 + "\n"
    chunks = [c.strip() for c in raw.split(sep) if c.strip()]
    out = []

    for c in chunks:
        # 粗过滤 CQ（图片/视频/表情等）
        if "[CQ:" in c:
            lines = []
            for ln in c.splitlines():
                if "[CQ:" in ln:
                    continue
                lines.append(ln)
            c = "\n".join(lines).strip()

        if len(c) < 8:
            continue
        out.append(c)

    return out

def profile_b_ingest_once():
    group_file, offset_path, ingest_log = _profile_b_offset_paths()
    if not os.path.exists(group_file):
        return

    start = _load_ingest_offset(offset_path)
    try:
        with open(group_file, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(start)
            new_data = f.read()
            end_pos = f.tell()
    except Exception:
        return

    blocks = _extract_text_blocks_for_ingest(new_data)
    _save_ingest_offset(offset_path, end_pos)

    if not blocks:
        return

    meta = {"scene": "group", "group_id": PROFILE_B_GROUP_ID}
    # ✅ 关键：写入时按 meta 分流到 Profile B 物理库
    add_memories(blocks, source=f"group_{PROFILE_B_GROUP_ID}", importance=0, meta=meta)

    # 北京时间日志
    try:
        import datetime as _dt
        bj = _dt.datetime.utcnow() + _dt.timedelta(hours=8)
        _append_ingest_log(ingest_log, f"[{bj.strftime('%Y-%m-%d %H:%M:%S')}] ingest {len(blocks)} blocks, byte {start}->{end_pos}")
    except Exception:
        pass

def start_profile_b_ingest_thread():
    if not PROFILE_B_INGEST_ENABLE:
        return

    # ✅ 统一用 POLL_SEC（并兼容旧变量名）
    poll = safe_int(globals().get("PROFILE_B_INGEST_POLL_SEC", None), 60)
    if poll <= 0:
        poll = 60

    def _loop():
        last_hour = None
        while True:
            try:
                import datetime as _dt
                now = _dt.datetime.utcnow() + _dt.timedelta(hours=8)  # 北京时间
                if now.minute == 0:
                    key = now.strftime("%Y-%m-%d %H")
                    if key != last_hour:
                        profile_b_ingest_once()
                        last_hour = key
                time.sleep(poll)
            except Exception:
                time.sleep(5)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()

# 启动 Profile B ingest
start_profile_b_ingest_thread()

# ============================================================
# 25. 入口：if __name__ == "__main__"
# ============================================================
if __name__ == "__main__":
    # Flask 模式运行：监听 0.0.0.0，方便局域网其它设备访问
    host = "0.0.0.0"
    port = 5000
    debug = False

    ssl_cert = str(os.getenv("TYXT_SSL_CERT_FILE") or "").strip()
    ssl_key = str(os.getenv("TYXT_SSL_KEY_FILE") or "").strip()
    ssl_context = None
    if ssl_cert or ssl_key:
        cert_abs = os.path.abspath(ssl_cert) if ssl_cert else ""
        key_abs = os.path.abspath(ssl_key) if ssl_key else ""
        if cert_abs and key_abs and os.path.exists(cert_abs) and os.path.exists(key_abs):
            ssl_context = (cert_abs, key_abs)
            print(f"[HTTPS] enabled cert={cert_abs} key={key_abs}")
        else:
            print(
                "[HTTPS] disabled (missing cert/key). "
                f"cert={cert_abs or '<empty>'} key={key_abs or '<empty>'}"
            )

    app.run(host=host, port=port, debug=debug, ssl_context=ssl_context)
