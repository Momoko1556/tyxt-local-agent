# ============================================================
# 00. 文件说明 / 版本记录（不要删）/脚本版本号：2601172136
# ============================================================

# napcat_bridge.py
# Reverse WebSocket Server for NapCat OneBot11 (Websocket Client mode)
# - Receives OneBot events from NapCat
# - Calls your backend /chat
# - Sends replies back to NapCat
# - NO file logging here (all logs handled by backend)

# ============================================================
# 01. Imports / 第三方依赖
# ============================================================

import os
import re
import json
import time
import random
import asyncio
import tempfile
import urllib.request
import unicodedata
import wave
from typing import Any, Dict, List, Tuple, Optional, Set
from urllib.parse import urlsplit, quote, unquote

import websockets
import requests
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if load_dotenv:
    _DOTENV_PATH = os.path.join(BASE_DIR, ".env")
    load_dotenv(_DOTENV_PATH, override=False)

# ============================================================
# 02. 配置区
#   02.1 基础连接配置（后端 / WS）
#   02.2 全局默认策略（用于其它群兜底）
#   02.3 按群覆盖表（两群策略完全分离）
# ============================================================

# ============================================================
# 02.1 基础连接配置（后端 / WS）
# ============================================================

BACKEND_CHAT = os.getenv("BACKEND_CHAT", "http://127.0.0.1:5000/chat")

def _default_backend_base_from_chat(chat_url: str) -> str:
    try:
        p = urlsplit(str(chat_url or "").strip())
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    return "http://127.0.0.1:5000"

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", _default_backend_base_from_chat(BACKEND_CHAT)).strip().rstrip("/")
BACKEND_TTS_URL = os.getenv("BACKEND_TTS_URL", f"{BACKEND_BASE_URL}/tools/tts").strip()

REVERSE_WS_HOST = os.getenv("REVERSE_WS_HOST", "127.0.0.1")
REVERSE_WS_PORT = int(os.getenv("REVERSE_WS_PORT", "6199"))
REVERSE_WS_PATH = os.getenv("REVERSE_WS_PATH", "/ws")

# 你本人 QQ
OWNER_QQ = os.getenv("OWNER_QQ", "").strip()

# 两个群（与后端保持一致）
PROFILE_A_GROUP_ID = os.getenv("PROFILE_A_GROUP_ID", "1079552241").strip()   # 严格群：只@/点名/引用才回
PROFILE_B_GROUP_ID = os.getenv("PROFILE_B_GROUP_ID", "1077018222").strip()   # 活跃群：唤醒+相关续命+随机插话

# 机器人名字关键词：群聊里出现这些字，也算“点名”
BOT_NAME_KEYWORDS = [x.strip() for x in os.getenv("BOT_NAME_KEYWORDS", "AI,墨渊").split(",") if x.strip()]

# 单条消息最大长度（超过则分段发送）
REPLY_MAX_CHARS = int(os.getenv("REPLY_MAX_CHARS", "9999"))  # 默认不做 200 字限制；如需限制可用环境变量覆盖
# 私聊发送模式（一些移动端在 string 模式下刷新不及时，可切 segment）
PRIVATE_SEND_MODE = str(os.getenv("PRIVATE_SEND_MODE", "string") or "string").strip().lower()
if PRIVATE_SEND_MODE not in ("segment", "string"):
    PRIVATE_SEND_MODE = "string"
PRIVATE_SEND_AUTO_ESCAPE = os.getenv("PRIVATE_SEND_AUTO_ESCAPE", "true").lower() in ("1", "true", "yes")
PRIVATE_LEGACY_SEND_PRIVATE = os.getenv("PRIVATE_LEGACY_SEND_PRIVATE", "true").lower() in ("1", "true", "yes")
# QQ 语音（record）发送：复用后端 /tools/tts
QQ_TTS_ENABLE = os.getenv("QQ_TTS_ENABLE", "true").lower() in ("1", "true", "yes")
QQ_TTS_PRIVATE_ONLY = os.getenv("QQ_TTS_PRIVATE_ONLY", "true").lower() in ("1", "true", "yes")
QQ_TTS_VOICE_ID = str(os.getenv("QQ_TTS_VOICE_ID", "default") or "default").strip() or "default"
QQ_TTS_MAX_CHARS = int(os.getenv("QQ_TTS_MAX_CHARS", "120"))
QQ_TTS_MAX_SEGMENTS = int(os.getenv("QQ_TTS_MAX_SEGMENTS", "6"))
QQ_TTS_MIN_SEGMENT_CHARS = int(os.getenv("QQ_TTS_MIN_SEGMENT_CHARS", "12"))
QQ_TTS_TIMEOUT_S = int(os.getenv("QQ_TTS_TIMEOUT_S", "90"))
QQ_TTS_SEND_DELAY_S = float(os.getenv("QQ_TTS_SEND_DELAY_S", "0.15"))
QQ_TTS_TEXT_AFTER_VOICE_DELAY_S = float(os.getenv("QQ_TTS_TEXT_AFTER_VOICE_DELAY_S", "0.20"))
QQ_TTS_SEND_ORDER = str(os.getenv("QQ_TTS_SEND_ORDER", "text_first") or "text_first").strip().lower()
if QQ_TTS_SEND_ORDER not in ("voice_first", "text_first"):
    QQ_TTS_SEND_ORDER = "text_first"
QQ_TTS_PRIVATE_COMBINE_SEND = os.getenv("QQ_TTS_PRIVATE_COMBINE_SEND", "true").lower() in ("1", "true", "yes")
QQ_TTS_SKIP_ERROR_TEXT = os.getenv("QQ_TTS_SKIP_ERROR_TEXT", "true").lower() in ("1", "true", "yes")
QQ_TTS_MERGE_SEGMENTS = os.getenv("QQ_TTS_MERGE_SEGMENTS", "true").lower() in ("1", "true", "yes")
QQ_TTS_MERGE_PRIVATE_ONLY = os.getenv("QQ_TTS_MERGE_PRIVATE_ONLY", "true").lower() in ("1", "true", "yes")
QQ_TTS_STRIP_LATIN = os.getenv("QQ_TTS_STRIP_LATIN", "true").lower() in ("1", "true", "yes")
QQ_TTS_LOCK_VOICE_PER_TURN = os.getenv("QQ_TTS_LOCK_VOICE_PER_TURN", "true").lower() in ("1", "true", "yes")
QQ_TTS_TEXT_FIRST_ASYNC = os.getenv("QQ_TTS_TEXT_FIRST_ASYNC", "true").lower() in ("1", "true", "yes")
QQ_TTS_TEXT_FIRST_ASYNC_DELAY_S = float(os.getenv("QQ_TTS_TEXT_FIRST_ASYNC_DELAY_S", "0.05"))
QQ_TTS_FORCE_URL = os.getenv("QQ_TTS_FORCE_URL", "false").lower() in ("1", "true", "yes")
QQ_TTS_ROOT = os.path.abspath(os.getenv("QQ_TTS_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "Ollama_agent_shared")))
NAPCAT_TMP_IMAGE_DIR = os.path.abspath(
    os.getenv("NAPCAT_TMP_IMAGE_DIR", os.path.join(QQ_TTS_ROOT, "uploads", "napcat_tmp"))
)
# 群聊触发回复的延迟窗口（避免抢话）
REPLY_DELAY_MIN = float(os.getenv("REPLY_DELAY_MIN", "2.0"))
REPLY_DELAY_MAX = float(os.getenv("REPLY_DELAY_MAX", "3.0"))
if REPLY_DELAY_MAX < REPLY_DELAY_MIN:
    REPLY_DELAY_MAX = REPLY_DELAY_MIN

# 是否在“首次接话”时引用原话
QUOTE_ON_FIRST_REPLY = os.getenv("QUOTE_ON_FIRST_REPLY", "true").lower() in ("1", "true", "yes")

# 是否允许“智能 @”
SMART_AT = os.getenv("SMART_AT", "true").lower() in ("1", "true", "yes")

# 调试
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

# 发送保护：刚离线恢复时先等待一小段时间，避免 QQNT 内核尚未就绪导致 sendMsg timeout
REQUIRE_ONLINE_BEFORE_SEND = os.getenv("REQUIRE_ONLINE_BEFORE_SEND", "true").lower() in ("1", "true", "yes")
OFFLINE_RECOVERY_GRACE_S = float(os.getenv("OFFLINE_RECOVERY_GRACE_S", "8.0"))
OFFLINE_RECOVERY_GRACE_PRIVATE_S = float(os.getenv("OFFLINE_RECOVERY_GRACE_PRIVATE_S", "1.5"))


# ============================================================
# 02.2 全局默认值（用于“其它群”兜底）
# ============================================================

GROUP_RANDOM_REPLY_RATE = float(os.getenv("GROUP_RANDOM_REPLY_RATE", "0.05"))
PEACH_RANDOM_REPLY_RATE = float(os.getenv("PEACH_RANDOM_REPLY_RATE", "0.15"))
WAKE_OFFTOPIC_REPLY_RATE = float(os.getenv("WAKE_OFFTOPIC_REPLY_RATE", "0.08"))
WAKE_SECONDS = int(os.getenv("WAKE_SECONDS", "120"))
WAKE_BROADCAST = os.getenv("WAKE_BROADCAST", "true").lower() in ("1", "true", "yes")

# 如果开启只@才回，则严格只在@或点名时回复（兜底用；严格群不用它，因为我们会硬策略）
GROUP_REPLY_ONLY_WHEN_AT = os.getenv("GROUP_REPLY_ONLY_WHEN_AT", "false").lower() in ("1", "true", "yes")


# ============================================================
# 02.3 按群覆盖表（核心：把两群参数完全分开）
#   - strict 群：强制只触发才回（随机=0），不依赖 wake
#   - random 群：唤醒+相关续命+随机插话（参数独立）
#   - init_topic_at_rate：机器人“主动发起新话题”时，@对方的概率（不是每次都@）
# ============================================================

def _gid(x) -> str:
    return str(x or "").strip()

GROUP_POLICY = {
    _gid(PROFILE_A_GROUP_ID): {
        "mode": "strict",
        "random_rate": 0.0,
        "peach_random_rate": 0.0,
        "wake_offtopic_rate": 0.0,
        "wake_seconds": 0,
        "wake_broadcast": False,
        "init_topic_at_rate": float(os.getenv("GROUP_A_INIT_TOPIC_AT_RATE", "0.00")),  # strict 默认不主动@
    },
    _gid(PROFILE_B_GROUP_ID): {
        "mode": "random",
        "random_rate": float(os.getenv("GROUP_B_RANDOM_RATE", "0.10")),
        "peach_random_rate": float(os.getenv("GROUP_B_PEACH_RATE", "0.18")),
        "wake_offtopic_rate": float(os.getenv("GROUP_B_OFFTOPIC_RATE", "0.10")),
        "wake_seconds": int(os.getenv("GROUP_B_WAKE_SECONDS", "240")),
        "wake_broadcast": os.getenv("GROUP_B_WAKE_BROADCAST", "true").lower() in ("1", "true", "yes"),
        "init_topic_at_rate": float(os.getenv("GROUP_B_INIT_TOPIC_AT_RATE", "0.35")),  # random 默认有点主动
    },
}

def get_group_policy(group_id: str) -> Dict[str, Any]:
    gid = _gid(group_id)
    p = GROUP_POLICY.get(gid)
    if p:
        return p

    # 其它群：用全局默认兜底
    return {
        "mode": "default",
        "random_rate": GROUP_RANDOM_REPLY_RATE,
        "peach_random_rate": PEACH_RANDOM_REPLY_RATE,
        "wake_offtopic_rate": WAKE_OFFTOPIC_REPLY_RATE,
        "wake_seconds": WAKE_SECONDS,
        "wake_broadcast": WAKE_BROADCAST,
        "init_topic_at_rate": float(os.getenv("INIT_TOPIC_AT_RATE", "0.20")),  # 兜底：适中
    }

def get_rates_for_group(group_id: str) -> Tuple[float, float, float, int, bool, str, float, Dict[str, Any]]:
    """
    给 handler 用的统一出口：
    return: random_rate, peach_rate, offtopic_rate, wake_seconds, wake_broadcast, mode, init_topic_at_rate, policy_dict
    """
    p = get_group_policy(group_id)
    return (
        float(p.get("random_rate", GROUP_RANDOM_REPLY_RATE)),
        float(p.get("peach_random_rate", PEACH_RANDOM_REPLY_RATE)),
        float(p.get("wake_offtopic_rate", WAKE_OFFTOPIC_REPLY_RATE)),
        int(p.get("wake_seconds", WAKE_SECONDS)),
        bool(p.get("wake_broadcast", WAKE_BROADCAST)),
        str(p.get("mode", "default") or "default").strip().lower(),
        float(p.get("init_topic_at_rate", 0.0) or 0.0),
        p,
    )

# ============================================================
# 03. 小工具：时间/身份/文本清洗
#   03.1 时间 / 身份
#   03.2 CQ/文本清洗 + 文件名安全化
#   03.3 按群策略读取（给 handler 用）
# ============================================================

# ----------------------------
# 03.1 时间 / 身份
# ----------------------------

def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

def is_owner(user_id: str) -> bool:
    return bool(OWNER_QQ) and (str(user_id) == str(OWNER_QQ))


# ----------------------------
# 03.2 CQ/文本清洗 + 文件名安全化
# ----------------------------

def strip_cq_codes(text: str) -> str:
    """移除形如 [CQ:xxx] 的片段（仅用于策略判定/去噪，不用于真正发送）"""
    if not text:
        return ""
    text = re.sub(r"\[CQ:[^\]]+\]", "", text)
    return text.strip()

def norm_text_simple(text: str) -> str:
    """一个很轻量的 normalize：去 CQ、去多空白、转小写（用于策略判断）"""
    s = strip_cq_codes(text or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


# ----------------------------
# 03.3 按群策略读取（给 handler 用）
#   返回：(random_rate, peach_rate, offtopic_rate, wake_seconds, wake_broadcast, mode, init_topic_at_rate, policy_dict)
# ----------------------------

def get_rates_for_group(group_id: str):
    """
    返回本群策略参数（来自 get_group_policy）：
    - random_rate
    - peach_random_rate
    - wake_offtopic_rate
    - wake_seconds
    - wake_broadcast
    - mode
    - init_topic_at_rate
    """
    p = get_group_policy(group_id) or {}

    def _f(k, default=0.0):
        try:
            return float(p.get(k, default))
        except Exception:
            return float(default)

    def _i(k, default=0):
        try:
            return int(p.get(k, default))
        except Exception:
            return int(default)

    def _b(k, default=False):
        try:
            return bool(p.get(k, default))
        except Exception:
            return bool(default)

    g_mode = str(p.get("mode", "default") or "default").strip().lower()
    g_random_rate = _f("random_rate", GROUP_RANDOM_REPLY_RATE)
    g_peach_rate = _f("peach_random_rate", PEACH_RANDOM_REPLY_RATE)
    g_offtopic_rate = _f("wake_offtopic_rate", WAKE_OFFTOPIC_REPLY_RATE)
    g_wake_seconds = _i("wake_seconds", WAKE_SECONDS)
    g_wake_broadcast = _b("wake_broadcast", WAKE_BROADCAST)
    g_init_topic_at_rate = _f("init_topic_at_rate", 0.20)

    return (
        g_random_rate,
        g_peach_rate,
        g_offtopic_rate,
        g_wake_seconds,
        g_wake_broadcast,
        g_mode,
        g_init_topic_at_rate,
        p,  # 顺手把整份 policy 也返回，方便塞 meta
    )

# ============================================================
# 04. 表情包模块（EMOJI）
# ============================================================
EMOJI_ROOT = os.path.abspath(
    os.getenv("EMOJI_ROOT", os.path.join(BASE_DIR, "tools", "emojis"))
)

def extract_emoji_directive(reply: str):
    """
    从回复末尾提取 [EMOJI:类别/文件名]，返回 (clean_reply, rel_path_or_none)
    只允许末尾一行触发，避免误触。
    """
    if not reply:
        return reply, None

    lines = reply.splitlines()
    if not lines:
        return reply, None

    last = lines[-1].strip()
    if last.startswith("[EMOJI:") and last.endswith("]"):
        inner = last[len("[EMOJI:"):-1].strip()
        # 只接受像 类别/文件名.png 这种相对路径
        if inner and ("/" in inner) and (".." not in inner) and (":" not in inner) and ("\\" not in inner):
            clean = "\n".join(lines[:-1]).rstrip()
            return clean, inner
    return reply, None

def resolve_emoji_path(rel_path: str) -> str:
    """
    rel_path: 例如 '开心/smile_01.png'
    """
    if not rel_path:
        return ""
    ap = os.path.abspath(os.path.join(EMOJI_ROOT, rel_path))
    root = os.path.abspath(EMOJI_ROOT)
    if not ap.startswith(root):
        return ""
    if not os.path.exists(ap):
        return ""
    return ap


# 每个 WS 连接一个发送锁，避免并发 ws.send 导致 RuntimeError
_WS_SEND_LOCKS: Dict[int, asyncio.Lock] = {}
_WS_BG_TASKS: Dict[int, Set[asyncio.Task]] = {}


def _ws_key(ws) -> int:
    return id(ws)


def _get_ws_send_lock(ws) -> asyncio.Lock:
    k = _ws_key(ws)
    lk = _WS_SEND_LOCKS.get(k)
    if lk is None:
        lk = asyncio.Lock()
        _WS_SEND_LOCKS[k] = lk
    return lk


async def ws_send_json(ws, payload: Dict[str, Any]):
    lk = _get_ws_send_lock(ws)
    async with lk:
        await ws.send(json.dumps(payload, ensure_ascii=False))


def _track_bg_task(ws, task: asyncio.Task):
    k = _ws_key(ws)
    st = _WS_BG_TASKS.get(k)
    if st is None:
        st = set()
        _WS_BG_TASKS[k] = st
    st.add(task)

    def _done_cb(t: asyncio.Task):
        try:
            s = _WS_BG_TASKS.get(k)
            if s is not None:
                s.discard(t)
                if not s:
                    _WS_BG_TASKS.pop(k, None)
        except Exception:
            pass

    task.add_done_callback(_done_cb)


def _cancel_bg_tasks_for_ws(ws):
    k = _ws_key(ws)
    tasks = list(_WS_BG_TASKS.pop(k, set()))
    for t in tasks:
        try:
            if not t.done():
                t.cancel()
        except Exception:
            pass
    _WS_SEND_LOCKS.pop(k, None)


async def send_image_private(ws, user_id: str, abs_path: str):
    # OneBot11 通常支持 file=绝对路径（NapCat 多数可用）
    msg = [{"type": "image", "data": {"file": abs_path}}]
    await ws_send_json(ws, {"action": "send_private_msg", "params": {"user_id": str(user_id), "message": msg}})

async def send_image_group(ws, group_id: str, abs_path: str):
    msg = [{"type": "image", "data": {"file": abs_path}}]
    await ws_send_json(ws, {"action": "send_group_msg", "params": {"group_id": str(group_id), "message": msg}})


def _clean_tts_text(text: str, max_chars: int = 120) -> str:
    s = sanitize_for_qq(str(text or ""))
    if not s:
        return ""

    # 和 AstrBot 插件一致：先做 NFKC 归一化 + 去隐形字符
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u200b", "").replace("\ufeff", "")

    # 先清除控制标记/链接
    s = re.sub(r"\[CQ:[^\]]+\]", " ", s, flags=re.I)
    s = re.sub(r"\[EMOJI:[^\]]+\]", " ", s, flags=re.I)
    s = re.sub(r"\[[^\]]+\]\((https?://[^)]+)\)", " ", s, flags=re.I)  # markdown 链接
    s = re.sub(r"https?://\S+", " ", s, flags=re.I)
    # ChatGPT 相关词一律剔除（目标文本 + 可能夹杂的变体）
    s = re.sub(r"(?i)chat\s*[-_ ]*\s*gpt(?:\s*[-_ ]*\d+)?", " ", s)
    s = re.sub(r"(?i)c\s*h\s*a\s*t\s*g\s*p\s*t", " ", s)
    s = re.sub(r"[\uFE0F\u200D]", "", s)  # emoji 常见残留

    # 先移除典型颜文字括号片段（仅限不含中文的短片段）
    def _strip_ascii_emoticon(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        if not inner:
            return " "
        if re.search(r"[\u4e00-\u9fff]", inner):
            return f"（{inner}）"
        alnum = len(re.findall(r"[A-Za-z0-9]", inner))
        symbols = len(re.findall(r"[^A-Za-z0-9\s]", inner))
        # 纯符号/短英文代号/符号占比高：视为颜文字噪声
        if alnum <= 3 or symbols >= alnum:
            return " "
        if re.fullmatch(r"[A-Za-z0-9 _-]{1,12}", inner):
            return " "
        return " "

    s = re.sub(r"[（(]([^()（）]{0,24})[）)]", _strip_ascii_emoticon, s)

    # TTS 可保留标点白名单（偏保守，避免把花样符号念出来）
    allowed_punc = set("，。！？；：、“”‘’（）()【】《》,.!?;:'\"、 ")

    def _is_text_char(ch: str) -> bool:
        if "0" <= ch <= "9" or "A" <= ch <= "Z" or "a" <= ch <= "z":
            return True
        o = ord(ch)
        return 0x4E00 <= o <= 0x9FFF

    # 第一轮：去掉控制类和符号类（Symbol，含绝大部分 emoji）
    out: List[str] = []
    for ch in s:
        if ch in ("\r", "\n", "\t"):
            out.append(" ")
            continue
        cat = unicodedata.category(ch)
        if cat and cat[0] in ("C", "S"):
            continue
        out.append(ch)
    s = "".join(out)

    # 第二轮：仅保留 文本/空白/常用标点
    kept: List[str] = []
    for ch in s:
        if _is_text_char(ch):
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
        elif ch in allowed_punc:
            kept.append(ch)
    s = "".join(kept)

    if QQ_TTS_STRIP_LATIN:
        # 中文场景下可读性优先：移除英文词，避免偶发英文串被读出（含 ChatGPT 类词）
        s = re.sub(r"\b[A-Za-z]{2,}\b", " ", s)

    # 收敛空白与标点
    s = re.sub(r"[（(]\s*[）)]", " ", s)   # 空括号
    s = re.sub(r"[【\[]\s*[】\]]", " ", s)
    s = re.sub(r"[\\/|^*_~=+\-]{2,}", " ", s)
    s = re.sub(r"[，,]{2,}", "，", s)
    s = re.sub(r"[。.!！?？]{2,}", "。", s)
    s = re.sub(r"[；;:：]{2,}", "；", s)
    s = re.sub(r"[。.!！?？][：:;；]+", "。", s)
    s = re.sub(r"[：:;；]+[。.!！?？]", "。", s)
    s = re.sub(r"\s+[：:;；,.!?！？]+\s+", " ", s)  # 独立悬空标点
    s = re.sub(r"([。.!！?？])\s+[，。！？；：、,.!?;:'\"]+", r"\1", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"([，。！？；：、“”‘’（）()【】《》,.!?;:'\"、])\1{1,}", r"\1", s)
    s = re.sub(r"(?i)chat\s*[-_ ]*\s*gpt(?:\s*[-_ ]*\d+)?", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ，,。.!?！？；;：:")
    s = re.sub(r"^[，。！？；：、,.!?;:'\"（）()【】《》\s]+", "", s)

    if max_chars > 0 and len(s) > max_chars:
        s = s[:max_chars].rstrip("，,。.!?！？；;：: ") + "。"
    return s


def _should_skip_tts_for_text(reply_text: str) -> bool:
    """
    Skip TTS for error-like texts to avoid speaking system errors.
    """
    s = str(reply_text or "").strip()
    if not s:
        return True
    s_low = s.lower()

    # High-confidence error keywords: skip if any token matches.
    strong_tokens = [
        "new api request failed",
        "api request failed",
        "request failed",
        "backend error",
        "backend request exception",
        "internal server error",
        "upstream error",
        "do_request_failed",
        "request failed",
        "connection aborted",
        "connectionreseterror",
        "traceback",
        "exception:",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
    ]
    for tok in strong_tokens:
        if tok in s_low:
            return True

    # Common error object shape: {"error":{"message":...}}
    if ('"error"' in s_low) and (('"message"' in s_low) or ('"code"' in s_low)):
        return True

    # URL + error semantics (gateway/upstream error pages)
    if re.search(r"https?://\S+", s_low) and re.search(r"(error|timeout|exception|500|502|503|504)", s_low):
        return True

    # Wrapped bridge fallback error text
    if re.match(r"^[（(]\s*(backend error|backend request exception|model returned empty reply)", s_low):
        return True

    return False


def _split_tts_text(text: str, max_chars: int, min_chars: int = 12) -> List[str]:
    t = str(text or "").strip()
    if not t:
        return []
    if max_chars <= 0 or len(t) <= max_chars:
        return [t]

    mx = max(40, int(max_chars))
    mn = max(4, int(min_chars or 4))
    punct = "。！？!?；;，,、.：:）)】]」』》>…"

    out: List[str] = []
    s = t
    while len(s) > mx:
        window = s[:mx]
        last_pos = -1
        for p in punct:
            pos = window.rfind(p)
            if pos > last_pos:
                last_pos = pos

        cut = (last_pos + 1) if last_pos >= int(mx * 0.45) else mx
        chunk = s[:cut].strip(" ，,。.!?！？；;：:")
        if chunk:
            out.append(chunk)
        s = s[cut:].strip()
    if s:
        out.append(s)

    # 合并过短段，降低 SoVITS 断句出错概率
    merged: List[str] = []
    for seg in out:
        if (not merged) or (len(seg) >= mn):
            merged.append(seg)
            continue
        prev = merged.pop().rstrip("，,。.!?！？；;：:")
        merged.append((prev + "，" + seg).strip(" ，,。.!?！？；;：:"))
    return [x for x in merged if x]


def _request_tts_audio_ref_once(tts_text: str, voice_id: str = "") -> Tuple[str, str]:
    t = _clean_tts_text(tts_text, 0)
    if not t:
        return "", ""

    req_voice = str(voice_id or QQ_TTS_VOICE_ID or "default").strip() or "default"

    payload = {
        "text": t,
        "voice_id": req_voice,
    }
    try:
        r = requests.post(
            BACKEND_TTS_URL,
            json=payload,
            timeout=(8, max(15, QQ_TTS_TIMEOUT_S)),
        )
        r.raise_for_status()
        data = r.json() if r.content else {}
    except Exception as e:
        if DEBUG:
            print(f"[bridge][tts] request failed: {e}")
        return "", req_voice

    if not isinstance(data, dict) or (not bool(data.get("ok"))):
        if DEBUG:
            print(f"[bridge][tts] backend not ok: {data}")
        return "", req_voice

    rel_path = str(data.get("rel_path") or "").strip()
    if not rel_path:
        return "", req_voice
    ref = _tts_audio_ref_from_rel(rel_path)
    used_voice = str(data.get("voice_id") or "").strip()
    if not used_voice:
        m = re.search(r"_([A-Za-z0-9_-]+)\.wav$", rel_path)
        if m:
            used_voice = str(m.group(1) or "").strip()
    used_voice = used_voice or req_voice
    if DEBUG:
        print(f"[bridge][tts] voice={used_voice} rel={rel_path} ref={ref}")
    return ref, used_voice


def request_tts_audio_refs(reply_text: str) -> List[str]:
    if not QQ_TTS_ENABLE:
        return []
    full = _clean_tts_text(reply_text, 0)
    if not full:
        return []

    pieces = _split_tts_text(full, QQ_TTS_MAX_CHARS, QQ_TTS_MIN_SEGMENT_CHARS)
    if QQ_TTS_MAX_SEGMENTS > 0:
        pieces = pieces[:QQ_TTS_MAX_SEGMENTS]
    if not pieces:
        return []

    refs: List[str] = []
    requested_voice = str(QQ_TTS_VOICE_ID or "default").strip() or "default"
    locked_voice = requested_voice
    lock_from_first = bool(QQ_TTS_LOCK_VOICE_PER_TURN and requested_voice.lower() in ("", "default", "auto"))

    for idx, piece in enumerate(pieces, start=1):
        ref, used_voice = _request_tts_audio_ref_once(piece, locked_voice)
        if lock_from_first and idx == 1 and used_voice:
            locked_voice = used_voice
            if DEBUG and (locked_voice != requested_voice):
                print(f"[bridge][tts] lock voice for turn: {requested_voice} -> {locked_voice}")
        if ref:
            refs.append(ref)
        elif DEBUG:
            print(f"[bridge][tts] piece failed idx={idx}/{len(pieces)}")
    if DEBUG:
        print(f"[bridge][tts] pieces={len(pieces)} refs={len(refs)}")
    return refs


def _voice_ref_to_local_path(file_ref: str) -> str:
    ref = str(file_ref or "").strip()
    if not ref:
        return ""

    # 直接就是本地路径
    if os.path.exists(ref):
        return os.path.abspath(ref)

    # URL 形式：尝试映射回 QQ_TTS_ROOT 下的 shared/audio 相对路径
    if ref.startswith("http://") or ref.startswith("https://"):
        marker = "/shared/audio/"
        idx = ref.find(marker)
        if idx >= 0:
            rel = unquote(ref[idx + len(marker):]).strip().replace("/", os.sep)
            ap = os.path.abspath(os.path.join(QQ_TTS_ROOT, rel))
            root = os.path.abspath(QQ_TTS_ROOT)
            if ap.startswith(root) and os.path.exists(ap):
                return ap
    return ""


def _merge_wav_local_files(src_paths: List[str]) -> str:
    files = [str(p).strip() for p in (src_paths or []) if str(p).strip()]
    if len(files) <= 1:
        return files[0] if files else ""

    # 合并语音统一放到 tts 子目录下，避免与原始缓存目录分散
    out_dir = os.path.join(QQ_TTS_ROOT, "tts", "_merged_tts")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir,
        f"tts_merge_{int(time.time() * 1000)}_{random.randint(1000, 9999)}.wav",
    )

    try:
        base_fmt: Optional[Tuple[int, int, int, str, str]] = None
        with wave.open(out_path, "wb") as out_wf:
            for p in files:
                with wave.open(p, "rb") as in_wf:
                    fmt = (
                        in_wf.getnchannels(),
                        in_wf.getsampwidth(),
                        in_wf.getframerate(),
                        in_wf.getcomptype(),
                        in_wf.getcompname(),
                    )
                    if base_fmt is None:
                        base_fmt = fmt
                        out_wf.setnchannels(fmt[0])
                        out_wf.setsampwidth(fmt[1])
                        out_wf.setframerate(fmt[2])
                        if fmt[3] != "NONE":
                            raise ValueError(f"unsupported wav compression: {fmt[3]}")
                    else:
                        if fmt != base_fmt:
                            raise ValueError("wav format mismatch across segments")

                    out_wf.writeframes(in_wf.readframes(in_wf.getnframes()))
        return out_path if os.path.exists(out_path) else ""
    except Exception as e:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except Exception:
            pass
        if DEBUG:
            print(f"[bridge][tts] merge wav failed: {e}")
        return ""


def maybe_merge_tts_refs(refs: List[str], scene: str = "private") -> List[str]:
    out = [str(x).strip() for x in (refs or []) if str(x).strip()]
    if len(out) <= 1:
        return out
    if not QQ_TTS_MERGE_SEGMENTS:
        return out
    if QQ_TTS_MERGE_PRIVATE_ONLY and str(scene).strip().lower() != "private":
        return out

    local_paths: List[str] = []
    for r in out:
        lp = _voice_ref_to_local_path(r)
        if not lp:
            if DEBUG:
                print(f"[bridge][tts] merge skipped (non-local ref): {r}")
            return out
        local_paths.append(lp)

    merged = _merge_wav_local_files(local_paths)
    if not merged:
        return out
    if DEBUG:
        print(f"[bridge][tts] merged segments {len(out)} -> 1 : {merged}")
    return [merged]


def _tts_audio_ref_from_rel(rel_path: str) -> str:
    rel = str(rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return ""

    if not QQ_TTS_FORCE_URL:
        ap = os.path.abspath(os.path.join(QQ_TTS_ROOT, rel))
        if os.path.exists(ap):
            return ap

    base = str(BACKEND_BASE_URL or "").strip().rstrip("/")
    if not base:
        return ""
    enc = quote(rel, safe="/")
    return f"{base}/shared/audio/{enc}"


def request_tts_audio_ref(reply_text: str) -> str:
    refs = request_tts_audio_refs(reply_text)
    return refs[0] if refs else ""


def _record_segment(file_ref: str) -> Dict[str, Any]:
    return {"type": "record", "data": {"file": str(file_ref)}}


def _text_segment(text: str) -> Dict[str, Any]:
    return {"type": "text", "data": {"text": str(text or "")}}


async def send_private_segments(ws, user_id: str, segs: List[Dict[str, Any]]):
    uid = str(user_id).strip()
    payload = {"action": "send_private_msg", "params": {"user_id": uid, "message": segs}}
    await ws_send_json(ws, payload)


async def send_voice_private(ws, user_id: str, file_ref: str):
    await send_private_segments(ws, user_id, [_record_segment(file_ref)])


async def send_voice_group(ws, group_id: str, file_ref: str):
    segs = [_record_segment(file_ref)]
    payload = {"action": "send_group_msg", "params": {"group_id": str(group_id), "message": segs}}
    await ws_send_json(ws, payload)

# ============================================================
# 05. Half-vision mode (image extract + OCR via Gemini API)
#   - Extract plain text from OneBot11 messages
#   - If image segments exist: download/save image and OCR by Gemini API
# ============================================================

import base64
import mimetypes
import urllib.request
import urllib.error

# ---- Gemini OCR config (env) ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_OCR_ENABLED = os.getenv("GEMINI_OCR_ENABLED", "true").lower() in ("1", "true", "yes")
GEMINI_OCR_ENDPOINT = os.getenv("GEMINI_OCR_ENDPOINT", "").strip().rstrip("/")
GEMINI_OCR_MODEL = os.getenv("GEMINI_OCR_MODEL", "[codex逆] gpt-5.2").strip()
GEMINI_OCR_TIMEOUT_SEC = int(os.getenv("GEMINI_OCR_TIMEOUT_SEC", "60"))

# Prompt can be customized if you want
GEMINI_OCR_PROMPT = os.getenv(
    "GEMINI_OCR_PROMPT",
    "请把图片中的文字完整识别出来，仅输出纯文本。若没有可识别文字，输出空字符串。不要加解释。"
).strip()


def safe_filename(name: str, max_len: int = 120) -> str:
    """
    Windows-safe filename for saving images/files
    """
    s = str(name or "").strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)
    s = s.strip().strip(".")
    if not s:
        s = "file"
    return s[:max_len]


def _guess_mime(path_: str, default: str = "image/jpeg") -> str:
    mt, _ = mimetypes.guess_type(path_ or "")
    return mt or default


def _read_bytes(path_: str) -> bytes:
    with open(path_, "rb") as f:
        return f.read()


def gemini_ocr_image_bytes(img_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """
    Gemini OCR: send image bytes to Gemini generateContent and parse returned text.
    Returns OCR text (may be empty).
    """
    if not GEMINI_OCR_ENABLED:
        return ""
    if not GEMINI_API_KEY:
        # No key -> OCR disabled silently
        return ""
    if not img_bytes:
        return ""

    b64 = base64.b64encode(img_bytes).decode("utf-8")
    url = f"{GEMINI_OCR_ENDPOINT}/models/{GEMINI_OCR_MODEL}:generateContent"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": GEMINI_OCR_PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": b64}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 2048,
        },
    }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=GEMINI_OCR_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            j = json.loads(raw or "{}")
    except Exception:
        return ""

    # Parse candidates[0].content.parts[].text
    try:
        cands = j.get("candidates") or []
        if not cands:
            return ""
        content = (cands[0] or {}).get("content") or {}
        parts = content.get("parts") or []
        texts = []
        for p in parts:
            t = (p or {}).get("text")
            if t:
                texts.append(str(t))
        out = "\n".join(texts).strip()
        return out
    except Exception:
        return ""


def ocr_image_file(path_: str) -> str:
    """
    Adapter for extract_text: if present, extract_text will prefer calling ocr_image_file(path).
    """
    try:
        if not path_ or (not os.path.exists(path_)):
            return ""
        mt = _guess_mime(path_)
        bb = _read_bytes(path_)
        return gemini_ocr_image_bytes(bb, mime_type=mt)
    except Exception:
        return ""


def extract_text(event: Dict[str, Any]) -> str:
    """
    Half-vision mode:
    - Read OneBot11 message (str or segment list)
    - Extract plain text (including @ / reply placeholders)
    - If image segments exist: try download and OCR (via ocr_image_file -> your API)
    Return: plain_text + structured "[image]" block
    """
    if not event:
        return ""

    msg = event.get("message", "")

    # 1) plain string message
    if isinstance(msg, str):
        return strip_cq_codes(msg).strip()

    # 2) segment list
    if not isinstance(msg, list):
        return ""

    text_parts: List[str] = []
    image_segments: List[Dict[str, Any]] = []

    for seg in msg:
        if not isinstance(seg, dict):
            continue
        t = str(seg.get("type") or "").lower()
        d = seg.get("data") or {}

        if t == "text":
            text_parts.append(str(d.get("text", "")))

        elif t == "at":
            # ✅ 保留“@”这一事实，避免纯@被当成空消息
            qq = str(d.get("qq", "")).strip()
            text_parts.append(f"@{qq}" if qq else "@")

        elif t in ("reply", "quote"):
            # ✅ 保留“引用/回复”占位，避免纯引用被当成空消息
            text_parts.append("[reply]")

        elif t == "image":
            # OneBot11/NapCat common fields: url / file / path
            image_segments.append(d)

        else:
            # 其他类型：face/json/record/video... 暂不处理
            pass

    plain_text = strip_cq_codes("".join(text_parts)).strip()

    # no image -> return plain text only (now includes @ / [reply] if present)
    if not image_segments:
        return plain_text

    def _download_to(url: str, out_path: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
            if not data:
                return False
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(data)
            return True
        except Exception:
            return False

    def _try_ocr_image(path_: str) -> str:
        # ✅ 统一走你脚本里已经定义的 ocr_image_file（它内部就是你的 API OCR 路线）
        try:
            if "ocr_image_file" in globals():
                return globals()["ocr_image_file"](path_)
        except Exception:
            pass
        return ""

    blocks: List[str] = []
    for idx, d in enumerate(image_segments):
        url = str(d.get("url") or "").strip()
        file_ = str(d.get("file") or "").strip()
        path_ = str(d.get("path") or "").strip()

        # choose a filename
        fn = safe_filename(file_ or f"img_{int(time.time())}_{idx}.jpg")
        local_dir = NAPCAT_TMP_IMAGE_DIR
        local_path = os.path.join(local_dir, fn)

        # obtain local file
        got = False
        if path_ and os.path.exists(path_):
            local_path = path_
            got = True
        elif url:
            got = _download_to(url, local_path)
        elif file_ and file_.startswith("http"):
            got = _download_to(file_, local_path)

        ocr_txt = ""
        if got:
            ocr_txt = (_try_ocr_image(local_path) or "").strip()

        # Build block info
        blocks.append(
            f"[image {idx+1}] file={os.path.basename(local_path)} url={url or file_ or path_}".strip()
        )
        if ocr_txt:
            blocks.append("OCR:\n" + ocr_txt)

    extra = "\n".join([b for b in blocks if b]).strip()
    if extra:
        if plain_text:
            return plain_text + "\n\n" + extra
        return extra

    return plain_text

# ============================================================
# 06. OneBot 事件解析：sender/ids/@/点名/引用
# ============================================================

def pick_sender_name(event: Dict[str, Any]) -> str:
    sender = event.get("sender") or {}
    card = str(sender.get("card", "")).strip()
    nick = str(sender.get("nickname", "")).strip()
    return card or nick or "unknown"


def norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[\s\-\*\#~`!！\?？\.,，。…:：;；\(\)（）\[\]【】\{\}]+", "", s)
    s = s.replace('"', "").replace("'", "").replace("\\", "/")
    return s

FAREWELL_TOKENS = {
    "晚安", "晚安啦", "晚安呀", "好梦", "明天见", "明儿见",
    "再见", "拜拜", "88", "溜了", "我先睡了", "我睡了", "睡了",
    "goodnight", "night", "bye", "seeyou", "cya",
}

def is_farewell(text: str) -> bool:
    t = norm_text(text)
    if not t:
        return False
    # 精确命中
    if t in FAREWELL_TOKENS:
        return True
    # 包含命中（例如“晚安”“先睡啦晚安”）
    for tok in FAREWELL_TOKENS:
        if tok and tok in t:
            return True
    return False
def has_quote_reply(event: dict) -> bool:
    """
    判断本条消息是否包含 OneBot 的 reply/引用段：
    - message 为 list：存在 {"type":"reply", ...}
    - message 为 str：包含 [CQ:reply, ...]
    """
    try:
        msg = (event or {}).get("message")
        if isinstance(msg, list):
            for seg in msg:
                if isinstance(seg, dict) and seg.get("type") == "reply":
                    return True
        if isinstance(msg, str) and "[CQ:reply" in msg:
            return True
    except Exception:
        pass
    return False


def pick_ids(event: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    返回：(message_type, user_id, group_id)
    """
    message_type = str(event.get("message_type") or "").strip()  # private / group
    sender = event.get("sender") or {}

    user_id = str(event.get("user_id") or sender.get("user_id") or sender.get("id") or "").strip()

    group_id = ""
    if message_type == "group":
        group_id = str(event.get("group_id") or sender.get("group_id") or "").strip()

    # 兜底：如果 message_type 为空但存在 group_id
    if not message_type:
        maybe_gid = event.get("group_id") or sender.get("group_id")
        if maybe_gid:
            message_type = "group"
            group_id = str(maybe_gid).strip()
        else:
            message_type = "private"

    return message_type, user_id, group_id

def pick_message_id(event: Dict[str, Any]) -> str:
    """
    OneBot11 message_id，用于 QQ 的真正引用回复（CQ:reply）。

    ⚠️ 严格模式：
    - 只接受 OneBot 标准字段：message_id / messageId
    - 或 message segment 里 type=reply 的 data.id（如果存在）
    - 不再用 event["id"] 兜底（很多实现的 id 不是可引用的 message_id，会导致 sendMsg 被 QQNT 拒绝：result=120）
    - 最终仅返回“纯数字”的 id；否则返回空字符串（将自动跳过 CQ:reply，而不是整条消息发不出去）
    """
    if not isinstance(event, dict):
        return ""

    candidates = []

    if event.get("message_id") is not None:
        candidates.append(event.get("message_id"))
    if event.get("messageId") is not None:
        candidates.append(event.get("messageId"))

    # 有些实现会在 message segment 里给 reply 段
    msg = event.get("message")
    if isinstance(msg, list):
        for seg in msg:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "reply":
                d = seg.get("data") or {}
                rid = d.get("id") or d.get("message_id") or d.get("messageId")
                if rid is not None:
                    candidates.append(rid)
                break

    for mid in candidates:
        try:
            s = str(mid).strip()
        except Exception:
            continue
        if s.isdigit():
            return s

    return ""


def is_valid_numeric_id(v: Any) -> bool:
    """
    OneBot 目标 id（QQ号/群号）合法性检查：
    - 必须是纯数字
    - 必须 > 0
    """
    try:
        s = str(v).strip()
    except Exception:
        return False
    if not s.isdigit():
        return False
    try:
        return int(s) > 0
    except Exception:
        return False

def has_bot_name(text: str) -> bool:
    if not text:
        return False
    for kw in BOT_NAME_KEYWORDS:
        if kw and kw in text:
            return True
    return False

def _at_in_str(raw: str, self_id: str) -> bool:
    if not raw or not self_id:
        return False
    if f"[CQ:at,qq={self_id}]" in raw:
        return True
    if "[CQ:at,qq=all]" in raw:
        return True
    pat = re.compile(r"\[CQ:at,[^\]]*qq=(\d+|all)[^\]]*\]")
    for m in pat.finditer(raw):
        qq = m.group(1)
        if qq == "all" or qq == self_id:
            return True
    return False

def is_at_me(event: Dict[str, Any]) -> bool:
    self_id = str(event.get("self_id", "")).strip()
    msg = event.get("message", "")

    if not self_id:
        return False

    if isinstance(msg, list):
        for seg in msg:
            if not isinstance(seg, dict):
                continue
            if seg.get("type") == "at":
                qq = str((seg.get("data") or {}).get("qq", "")).strip()
                if qq == self_id or qq == "all":
                    return True
        return False

    if isinstance(msg, str):
        return _at_in_str(msg, self_id)

    return False


# ============================================================
# 07. QQ 友好输出：去格式 / 分段 / 颜文字 / 引用策略辅助
# ============================================================

def sanitize_for_qq(text: str) -> str:
    """去掉 QQ 不友好的 Markdown/格式符号，保持纯文本观感；把 *动作* 规范成（动作）。"""
    if not text:
        return ""
    s = str(text)

    # 先去掉常见 Markdown 标记（QQ 看不到这些格式，只会显得乱）
    s = s.replace("**", "").replace("__", "")
    s = s.replace("```", "").replace("`", "")
    s = s.replace("~~", "")

    # ✅ 把 *轻笑* / *立刻放下手头的事* 这种“动作描写”改成中文括号
    # 规则：只处理“成对单星号包裹”的短句，避免误伤乘号/代码
    def _star_action_to_paren(m: re.Match) -> str:
        inner = (m.group(1) or "").strip()
        if not inner:
            return m.group(0)
        # 太长的先不转，避免误伤正常段落
        if len(inner) > 40:
            return m.group(0)
        # 不要把纯数字/纯符号当动作
        if re.fullmatch(r"[0-9\W_]+", inner):
            return m.group(0)
        return f"（{inner}）"

    # 形如：*xxx*，xxx 不跨行、不含星号
    s = re.sub(r"\*(?!\s)([^*\n]{1,60}?)(?<!\s)\*", _star_action_to_paren, s)

    # 列表/引用的“排版符号”也去掉（保留正文）
    s = re.sub(r"(?m)^\s*[-*•]+\s+", "", s)      # - xxx / * xxx
    s = re.sub(r"(?m)^\s*\d+\.\s+", "", s)       # 1. xxx
    s = re.sub(r"(?m)^>\s?", "", s)              # > quote

    # 多余空行收敛
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _split_by_punct(text: str, max_chars: int) -> List[str]:
    """
    兜底切分：优先在标点处分段；找不到合适标点就硬切。
    保证不会死循环，也不会返回空段。
    """
    t = (text or "").strip()
    if not t:
        return []
    if max_chars <= 10:
        max_chars = 10

    punct = "。！？!?；;，,、.：:）)】]」』》>…"
    parts: List[str] = []
    s = t

    while len(s) > max_chars:
        cut = max_chars

        # 先在前 max_chars 范围内找“最后一个标点”作为切点
        window = s[:max_chars]
        last_pos = -1
        for p in punct:
            pos = window.rfind(p)
            if pos > last_pos:
                last_pos = pos

        # 标点切点太靠前就不采用（避免段太碎）
        if last_pos >= int(max_chars * 0.55):
            cut = last_pos + 1

        chunk = s[:cut].strip()
        if chunk:
            parts.append(chunk)

        s = s[cut:].lstrip()

        # 兜底：如果因为奇怪字符导致没推进，就强推进
        if len(s) == len(window):
            s = s[max_chars:].lstrip()

    if s.strip():
        parts.append(s.strip())

    return parts


def split_for_qq(text: str, max_chars: int = 200) -> List[str]:
    """超过 max_chars 就分段发送；优先按换行/段落，其次按标点切。"""
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]

    parts: List[str] = []
    chunks = re.split(r"\n+", t)
    buf = ""
    for ch in chunks:
        ch = ch.strip()
        if not ch:
            continue
        cand = (buf + "\n" + ch).strip() if buf else ch
        if len(cand) <= max_chars:
            buf = cand
            continue

        if buf:
            parts.extend(_split_by_punct(buf, max_chars))
            buf = ""

        parts.extend(_split_by_punct(ch, max_chars))

    if buf:
        parts.extend(_split_by_punct(buf, max_chars))

    return [p.strip() for p in parts if p.strip()]


# ✅ 兼容别名：你 handler 里用的是 split_long_text
def split_long_text(text: str, max_chars: int = 200) -> List[str]:
    """
    按 max_chars 分段。兼容：
    - max_chars <= 0：不分段，整段返回
    - max_chars 很大：基本等于不限制
    """
    text = (text or "").strip()
    if not text:
        return []

    try:
        max_chars = int(max_chars)
    except Exception:
        max_chars = 200

    # <=0 表示“不分段”
    if max_chars <= 0:
        return [text]

    # 给个最低值兜底，避免传进来奇怪的小数字导致疯狂刷屏
    max_chars = max(50, max_chars)

    parts: List[str] = []
    buf: List[str] = []

    for ch in text:
        buf.append(ch)
        if len(buf) >= max_chars:
            parts.append("".join(buf))
            buf = []

    if buf:
        parts.append("".join(buf))

    return parts


# ============================================================
# 08. 话题相关性：轻量判断
# ============================================================

def is_topic_related_light(text: str, topic: str) -> bool:
    if not text or not topic:
        return False
    text = text.lower()
    topic = topic.lower()
    # 超轻量：topic 拆词做 contains
    keywords = [w for w in re.split(r"\s+", topic) if len(w) >= 2]
    if not keywords:
        return False
    return any(k in text for k in keywords)

def is_relevant_to_topic(text: str, topic: str) -> bool:
    """相关性判断入口：目前使用轻量 contains 规则。"""
    return is_topic_related_light(text, topic)


# ============================================================
# 09. 群聊状态机：唤醒/静音/循环检测状态
# ============================================================

WAKE_STATE: Dict[str, Dict[str, Any]] = {}

# ✅ 静音到期时间：按“群/私聊”分桶，避免互相影响
# key 示例：
#   group:1077018222
#   private:<qq_user_id>
MUTE_UNTIL: Dict[str, float] = {}

# ✅ 兼容旧命名：历史版本用过 GROUP_MUTE_UNTIL
GROUP_MUTE_UNTIL = MUTE_UNTIL

# 循环检测状态：记录上一句机器人发言等
LOOP_STATE: Dict[str, Dict[str, Any]] = {}

def mute_key(scene: str, group_id: str, user_id: str) -> str:
    """
    生成静音分桶 key：
      - 群聊：  group:<gid>
      - 私聊：  private:<uid>
    说明：你后面静音判断/写入 MUTE_UNTIL 都依赖这个 key。
    """
    sc = str(scene or "").strip().lower()
    gid = str(group_id or "").strip()
    uid = str(user_id or "").strip()

    # 只要能拿到 gid，就优先按群分桶（避免 scene 字段偶发不一致）
    if gid:
        return f"group:{gid}"
    return f"private:{uid}"

# ✅ 兼容你可能在别处用过的旧函数名
_mute_key = mute_key


def _wake_set(group_id: str, user_id: str, topic_text: str, wake_seconds: int):
    gid = str(group_id or "").strip()
    if not gid:
        return
    try:
        ws = int(wake_seconds)
    except Exception:
        ws = int(WAKE_SECONDS)
    WAKE_STATE[gid] = {
        "expire": time.time() + max(0, ws),
        "last_user_id": str(user_id),
        "topic": (topic_text or "").strip()[:500],
    }

def _wake_active(group_id: str) -> bool:
    gid = str(group_id or "").strip()
    st = WAKE_STATE.get(gid)
    if not st:
        return False
    try:
        return time.time() <= float(st.get("expire", 0) or 0)
    except Exception:
        return False

def _wake_last_user(group_id: str) -> str:
    gid = str(group_id or "").strip()
    st = WAKE_STATE.get(gid) or {}
    return str(st.get("last_user_id", "")).strip()

def _wake_topic(group_id: str) -> str:
    gid = str(group_id or "").strip()
    st = WAKE_STATE.get(gid) or {}
    return str(st.get("topic", "")).strip()

def _wake_refresh(group_id: str,
                  wake_seconds: int,
                  user_id: str = "",
                  topic_text: str = "",
                  update_topic: bool = False):
    gid = str(group_id or "").strip()
    if not gid:
        return

    st = WAKE_STATE.get(gid) or {}
    try:
        ws = int(wake_seconds)
    except Exception:
        ws = int(WAKE_SECONDS)

    st["expire"] = time.time() + max(0, ws)

    if user_id:
        st["last_user_id"] = str(user_id)

    if update_topic and topic_text:
        st["topic"] = (topic_text or "").strip()[:500]

    WAKE_STATE[gid] = st

# ---- 兼容旧 API 命名 ----
def wake_group(group_id: str, user_id: str, topic_text: str):
    _wake_set(group_id, user_id, topic_text, WAKE_SECONDS)

def wake_active(group_id: str) -> bool:
    return _wake_active(group_id)

def wake_last_user(group_id: str) -> str:
    return _wake_last_user(group_id)

def wake_topic(group_id: str) -> str:
    return _wake_topic(group_id)

def wake_refresh(group_id: str, user_id: str = "", topic_text: str = "", update_topic: bool = False):
    _wake_refresh(group_id, WAKE_SECONDS, user_id=user_id, topic_text=topic_text, update_topic=update_topic)


# ============================================================
# 10. OneBot 发送：send_private / send_group
# ============================================================

async def send_private(ws, user_id: str, text: str):
    uid = str(user_id).strip()
    msg = str(text or "")

    # 兼容旧脚本（20260117）：只走 send_private_msg + string
    if PRIVATE_LEGACY_SEND_PRIVATE:
        legacy_action = {
            "action": "send_private_msg",
            "params": {
                "user_id": uid,
                "message": msg,
                "auto_escape": bool(PRIVATE_SEND_AUTO_ESCAPE),
            },
        }
        await ws_send_json(ws, legacy_action)
        return

    # 优先走 send_msg（NapCat 新版兼容更好），失败再回退 send_private_msg
    def _build_send_msg_payload(message_payload: Any) -> Dict[str, Any]:
        return {
            "action": "send_msg",
            "params": {
                "message_type": "private",
                "user_id": uid,
                "message": message_payload,
            },
        }

    if PRIVATE_SEND_MODE == "segment":
        seg_msg = [{"type": "text", "data": {"text": msg}}]
        action = _build_send_msg_payload(seg_msg)
        try:
            await ws_send_json(ws, action)
            return
        except Exception as e:
            if DEBUG:
                print(f"[bridge] private segment send failed, fallback to string: {e}")

    action2 = _build_send_msg_payload(msg)
    action2["params"]["auto_escape"] = bool(PRIVATE_SEND_AUTO_ESCAPE)
    try:
        await ws_send_json(ws, action2)
        return
    except Exception:
        pass

    # 最后兜底旧动作
    action3 = {
        "action": "send_private_msg",
        "params": {
            "user_id": uid,
            "message": msg,
            "auto_escape": bool(PRIVATE_SEND_AUTO_ESCAPE),
        },
    }
    await ws_send_json(ws, action3)

async def send_group(ws, group_id: str, text: str):
    action = {"action": "send_group_msg", "params": {"group_id": str(group_id), "message": text}}
    await ws_send_json(ws, action)

# ============================================================
# 11. 调后端：call_backend
#   关键修复：
#   - 强制 stream=False（桥接永远要 JSON）
#   - requests.post 放到线程里跑（不阻塞 WS 事件循环）
#   - 超时可配置：BACKEND_CONNECT_TIMEOUT_S / BACKEND_TIMEOUT_S
# ============================================================

BACKEND_CONNECT_TIMEOUT_S = int(os.getenv("BACKEND_CONNECT_TIMEOUT_S", "8"))
BACKEND_TIMEOUT_S         = int(os.getenv("BACKEND_TIMEOUT_S", "600"))

def call_backend(user_text: str, meta: Dict[str, Any]) -> str:
    # 桥接永远要非流式 JSON
    payload = {"message": user_text, "meta": meta, "stream": False}

    if DEBUG:
        print("\n[bridge -> backend payload]")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("====================================\n")

    try:
        # (连接超时, 读取超时)
        r = requests.post(
            BACKEND_CHAT,
            json=payload,
            timeout=(BACKEND_CONNECT_TIMEOUT_S, BACKEND_TIMEOUT_S),
        )
        r.raise_for_status()

        # 只接受 JSON
        try:
            data = r.json()
        except Exception:
            text_preview = (r.text or "").strip()
            if len(text_preview) > 300:
                text_preview = text_preview[:300] + "…"
            return f"(Backend returned non-JSON; possible stream/error response: {text_preview})"

        return str(data.get("reply", "")).strip()

    except Exception as e:
        return f"(Backend error: {e})"


async def call_backend_async(user_text: str, meta: Dict[str, Any]) -> str:
    """
    在 async handler 里安全调用：把阻塞的 requests.post 丢到线程池，
    避免卡死 websockets 事件循环导致 NapCat 断开。
    """
    try:
        # Py3.9+ 推荐
        return await asyncio.to_thread(call_backend, user_text, meta)
    except AttributeError:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, call_backend, user_text, meta)

# ============================================================
# 12. Reverse WS 主处理：handler（核心逻辑：收消息→判定→调后端→发回）
#   子段落说明：
#   12.1 收包与基础过滤
#   12.2 解析：场景/身份/文本/at/点名/引用/msg_id
#   12.3 群聊静音：口令静音 + 循环检测静音
#   12.4 组装 meta（给后端）+ 读取按群覆盖参数
#   12.5 回复策略决策总入口
#   12.6 按群分离：STRICT(107955) / RANDOM(107701) / DEFAULT(其他)
#   12.7 调后端生成回复
#   12.8 QQ 友好输出（引用/分段/@/表情包）
#   12.9 状态回写（循环检测 & 唤醒话题续命/更新）
# ============================================================

async def handler(ws, path):
    print(f"[bridge] NapCat connected ✅ path={path}")

    # 这俩群号从环境变量读；没配就用默认
    STRICT_GROUP_ID = str(PROFILE_A_GROUP_ID).strip()  # 107955...：只@/点名/引用才回
    RANDOM_GROUP_ID = str(PROFILE_B_GROUP_ID).strip()  # 107701...：唤醒+相关续命+随机插话

    # 来自 meta_event.heartbeat / lifecycle 的在线状态
    bot_online: Optional[bool] = None
    last_offline_ts = 0.0
    last_online_ts = 0.0

    def _mark_online_state(online: Optional[bool], reason: str = ""):
        nonlocal bot_online, last_offline_ts, last_online_ts
        if online is None:
            return
        now_ts = time.time()
        old = bot_online
        bot_online = bool(online)
        if bot_online:
            last_online_ts = now_ts
        else:
            last_offline_ts = now_ts
        if old is not bot_online:
            print(f"[bridge] bot_online -> {bot_online} ({reason or 'unknown'})")

    def _update_online_state_from_event(evt: Dict[str, Any]):
        """
        读取 NapCat 常见在线状态来源：
        - meta_event + heartbeat: event["status"]["online"]
        - meta_event + lifecycle/connect: 视作上线
        """
        if not isinstance(evt, dict):
            return
        post_type = str(evt.get("post_type") or "").strip().lower()
        if post_type != "meta_event":
            return

        meta_tp = str(evt.get("meta_event_type") or "").strip().lower()
        if meta_tp == "heartbeat":
            st = evt.get("status")
            if isinstance(st, dict) and ("online" in st):
                _mark_online_state(bool(st.get("online")), "heartbeat")
            return

        if meta_tp == "lifecycle":
            sub = str(evt.get("sub_type") or "").strip().lower()
            if sub in ("connect", "enable"):
                _mark_online_state(True, f"lifecycle:{sub}")
            return

    def _send_guard_wait_s(scene_name: str = "") -> float:
        """
        离线恢复保护时间：
        - 明确离线时：进入等待窗口
        - 离线刚恢复：仍保留一个短缓冲窗口，给 QQNT 内核回稳
        """
        sc = str(scene_name or "").strip().lower()
        grace = float(OFFLINE_RECOVERY_GRACE_S)
        if sc == "private":
            grace = max(0.0, float(OFFLINE_RECOVERY_GRACE_PRIVATE_S))

        now_ts = time.time()
        if bot_online is False:
            if last_offline_ts > 0:
                delta = now_ts - last_offline_ts
                return max(0.0, grace - delta)
            return grace

        if (last_offline_ts > 0) and (last_online_ts >= last_offline_ts):
            delta = now_ts - last_online_ts
            return max(0.0, grace - delta)

        return 0.0

    def _has_quote_or_reply(evt: dict) -> bool:
        """
        检测“引用/回复”：
        - OneBot/NapCat 常见：event["message"] 是 list，里面 seg["type"] == "reply"/"quote"
        - 兜底：字符串 CQ 码里含 [CQ:reply
        - 兼容：evt["reply"] / evt["source"]
        """
        try:
            msg = evt.get("message")
            if isinstance(msg, list):
                for seg in msg:
                    if isinstance(seg, dict):
                        tp = str(seg.get("type") or "").lower()
                        if tp in ("reply", "quote"):
                            return True
            if isinstance(msg, str) and ("[CQ:reply" in msg):
                return True
            if evt.get("reply") or evt.get("source"):
                return True
        except Exception:
            pass
        return False

    # —— handler 内部做“按群 wake 秒数”的 wrapper（不改你模块 09）——
    def _wake_set(gid: str, uid: str, topic_text: str, wake_seconds: int):
        if not gid:
            return
        WAKE_STATE[str(gid)] = {
            "expire": time.time() + max(0, int(wake_seconds or 0)),
            "last_user_id": str(uid),
            "topic": (topic_text or "").strip()[:500],
        }

    def _wake_active(gid: str) -> bool:
        st = WAKE_STATE.get(str(gid))
        if not st:
            return False
        return time.time() <= float(st.get("expire", 0) or 0)

    def _wake_last_user(gid: str) -> str:
        st = WAKE_STATE.get(str(gid)) or {}
        return str(st.get("last_user_id", "")).strip()

    def _wake_topic(gid: str) -> str:
        st = WAKE_STATE.get(str(gid)) or {}
        return str(st.get("topic", "")).strip()

    def _wake_refresh(gid: str, wake_seconds: int, user_id: str = "", topic_text: str = "", update_topic: bool = False):
        gid = str(gid)
        if not gid:
            return
        st = WAKE_STATE.get(gid) or {}
        st["expire"] = time.time() + max(0, int(wake_seconds or 0))
        if user_id:
            st["last_user_id"] = str(user_id)
        if update_topic and topic_text:
            st["topic"] = (topic_text or "").strip()[:500]
        WAKE_STATE[gid] = st

    while True:
        # ============================================================
        # 12.1 收包与基础过滤
        # ============================================================
        try:
            raw = await ws.recv()
        except websockets.ConnectionClosed:
            print("[bridge] NapCat disconnected ❌")
            break

        try:
            event = json.loads(raw)
        except Exception:
            continue

        _update_online_state_from_event(event)

        if event.get("post_type") != "message":
            continue

        # 能收到正常 message 事件，视作链路可用
        _mark_online_state(True, "message_event")

        # ============================================================
        # 12.2 解析：场景/身份/文本/at/点名/引用/msg_id
        #   ✅ 修复：
        #   1) 只要事件里拿得到 group_id，就强制按群聊处理
        #      避免 message_type 偶发异常导致“群消息被当私聊”
        #   2) 群B点名（G管家/G）判定必须在 scene 定义之后执行（修复：群B唤醒失效）
        #   3) @ 兜底：self_id 可能缺失/位置不一致，增加多来源 bot_id
        # ============================================================
        message_type, user_id, group_id = pick_ids(event)

        # —— 12.2.1 群聊兜底：不要盲信 message_type，只要有 group_id 就认定是群聊 ——
        try:
            evt_gid = (
                (event or {}).get("group_id")
                or (event or {}).get("groupId")
                or ((event or {}).get("sender") or {}).get("group_id")
                or ((event or {}).get("sender") or {}).get("groupId")
                or ""
            )
            evt_gid = str(evt_gid or "").strip()
        except Exception:
            evt_gid = ""

        if evt_gid:
            group_id = evt_gid
            message_type = "group"
        else:
            message_type = "group" if str(message_type).strip().lower() == "group" else "private"

        # ✅ 先定 scene（后面 at/call_name 都要用）
        scene = "group" if message_type == "group" else "private"

        sender_name = pick_sender_name(event)
        text = extract_text(event)

        # 半视觉：图片消息也会产出文本（图片信息+OCR），所以这里允许继续
        if not text:
            continue

        # --- at / 点名 / 引用 ---
        # ✅ at_me：先用你原函数；再做 OneBot11 segment 兜底（避免@识别失败）
        at_me = is_at_me(event)

        try:
            if not at_me:
                # bot_id 多来源兜底：event/self_id + 环境变量
                bot_ids = set()

                self_id = str(
                    (event or {}).get("self_id")
                    or (event or {}).get("selfId")
                    or ""
                ).strip()
                if self_id:
                    bot_ids.add(self_id)

                for k in ("BOT_QQ", "SELF_QQ", "NAPCAT_SELF_ID"):
                    v = str(os.getenv(k, "") or "").strip()
                    if v:
                        bot_ids.add(v)

                msg0 = (event or {}).get("message")
                if isinstance(msg0, list):
                    for seg in msg0:
                        if not isinstance(seg, dict):
                            continue
                        if str(seg.get("type") or "").lower() == "at":
                            data = seg.get("data") or {}
                            qq = str(data.get("qq") or "").strip()

                            # 常规：@到具体QQ
                            if qq and bot_ids and (qq in bot_ids):
                                at_me = True
                                break

                            # 有些实现 qq 为空仍代表 @bot（保守：只有在 bot_ids 为空时才放宽）
                            if (not qq) and (not bot_ids):
                                at_me = True
                                break
        except Exception:
            pass

        # ✅ call_name：先吃 BOT_NAME_KEYWORDS；群B额外支持 “G管家 / 单独G”
        call_name = has_bot_name(text)
        try:
            gid_tmp = str(group_id or "").strip()
            is_group_b = (scene == "group" and gid_tmp == str(PROFILE_B_GROUP_ID).strip())
            if is_group_b and not call_name:
                t0 = strip_cq_codes(text or "")
                t0 = (t0 or "").replace(" ", "").replace("　", "").strip()
                if "G管家" in t0:
                    call_name = True
                else:
                    # 单独一个 G（避免把“GPT/AGI/英文单词”误判成点名）
                    if re.search(r"(^|[^A-Za-z0-9])G([^A-Za-z0-9]|$)", t0):
                        call_name = True
        except Exception:
            pass

        quoted = _has_quote_or_reply(event)   # ✅ 引用/回复触发（只判定一次）
        owner = is_owner(user_id)

        msg_id = pick_message_id(event)

        gid_str = str(group_id or "").strip()
        is_strict_group = (scene == "group" and gid_str == STRICT_GROUP_ID)
        is_random_group = (scene == "group" and gid_str == RANDOM_GROUP_ID)

        # 可选：解析调试（需要就开环境变量 DEBUG_PARSE=1）
        try:
            if str(os.getenv("DEBUG_PARSE", "0")).strip() == "1":
                print(f"[bridge][12.2] scene={scene} gid={gid_str} uid={user_id} at_me={at_me} call_name={call_name} quoted={quoted} text={strip_cq_codes(text)[:80]!r}")
        except Exception:
            pass


        # ============================================================
        # 12.3 群聊静音：控制指令优先处理（不下发后端，不生成回复）
        #   - 群B：主口令 “请闭嘴 / 请说话”
        #   - 其它：主口令 “快闭嘴 / 快说话”
        #   - 兼容：两套口令都接受
        #   - 静音期间：仅当有人试图唤醒（@我 / 点名 / 引用）才回剩余秒数，其余沉默
        #   ✅ 关键修复：这里必须用 continue，不能 return（return 会直接断开 WS）
        # ============================================================
        now_ts = time.time()

        mk = mute_key(scene, group_id, user_id)

        # --- 口令归一化：去 CQ、去空白（含全角空格）---
        try:
            _cmd_raw = strip_cq_codes(text or "")
        except Exception:
            _cmd_raw = (text or "")
        _cmd_raw = str(_cmd_raw)
        cmd = _cmd_raw.replace(" ", "").replace("　", "").strip()

        is_group_b = (scene == "group" and str(group_id).strip() == str(PROFILE_B_GROUP_ID).strip())

        close_cmds = {"请闭嘴"} if is_group_b else {"快闭嘴"}
        open_cmds  = {"请说话"} if is_group_b else {"快说话"}
        # 兼容：无论在哪个群/私聊，都接受两套口令，避免锁死
        close_cmds |= {"快闭嘴", "请闭嘴"}
        open_cmds  |= {"快说话", "请说话"}

        async def _send_here(msg: str):
            if scene == "private":
                await send_private(ws, user_id, msg)
            else:
                # 静音提示不需要引用卡片，直接发文本即可
                await send_group(ws, group_id, msg)

        def _mute_left_text(left_seconds: int) -> str:
            left_seconds = int(max(0, left_seconds))
            return f"（我在静音中，还剩 {left_seconds} 秒。发送“快说话”或“请说话”解除。）"

        def _call_name_extra_for_group_b(t: str) -> bool:
            """
            群B额外点名：支持 “G”“G管家”
            用于静音倒计时提示的“试图唤醒”判定（避免只喊G不回倒计时）
            """
            if not is_group_b:
                return False
            try:
                tt = strip_cq_codes(t or "").strip()
            except Exception:
                tt = str(t or "").strip()
            if not tt:
                return False
            if "G管家" in tt:
                return True
            # 单独的 G（尽量克制：用边界匹配，避免误伤单词）
            return bool(re.search(r"(^|\\s)G(\\s|$)", tt))

        # 0) 收到静音/解除：直接处理并 continue（不调用后端）
        if cmd in close_cmds:
            MUTE_UNTIL[mk] = now_ts + 600
            await _send_here("好的，我会安静一会儿。（发送“快说话”或“快说话”解除）")
            continue

        if cmd in open_cmds:
            MUTE_UNTIL[mk] = 0
            await _send_here("好的，我回来了。")
            continue

        # 1) 静音期间：不转发后端；仅当“试图唤醒”时提示剩余
        until = float(MUTE_UNTIL.get(mk, 0) or 0)
        if now_ts < until:
            left = int(max(0, until - now_ts))

            if scene == "private":
                await _send_here(_mute_left_text(left))
                continue

            # 群聊：@我 / 点名 / 引用 都算“试图唤醒”
            # 群B：额外支持 “G / G管家” 作为点名
            wake_try = bool(at_me or call_name or quoted or _call_name_extra_for_group_b(text))
            if wake_try:
                await _send_here(_mute_left_text(left))
            continue


        # ============================================================
        # 12.4 组装 meta（给后端）+ 读取按群覆盖参数
        #       - 把 group_policy / init_topic_at_rate 塞进 meta，供 12.8 使用
        #       ✅ 新增：target_user_id/target_name/target_is_peach（强制声明本次回复对象）
        # ============================================================
        target_user_id = user_id
        target_name = sender_name
        target_is_peach = owner

        meta: Dict[str, Any] = {
            "scene": scene,
            "message_type": message_type,
            "user_id": user_id,
            "group_id": group_id,
            "sender_name": sender_name,
            "msg_id": msg_id,
            "is_peach": owner,
            "at_me": at_me,
            "call_name": call_name,
            "quoted": quoted,
            "upstream": "napcat_bridge",

            # ✅ 强制声明“本次要回复的对象是谁”
            "target_user_id": target_user_id,
            "target_name": target_name,
            "target_is_peach": bool(target_is_peach),

            # ✅ 给后端做更硬的对象确认（即便后端有记忆，也不能把群友当用户）
            "force_target_check": True,
        }

        # 本群策略（优先 GROUP_POLICY 覆盖，其次全局默认兜底）
        gp = get_group_policy(gid_str) if gid_str else get_group_policy("")
        meta["group_policy"] = gp

        # ✅ 关键：统一拿到 g_mode（同时写回 meta，避免大小写/空格差异）
        g_mode = str(gp.get("mode", "default") or "default").strip().lower()
        meta["group_mode"] = g_mode

        # 拆出本群参数（供 12.5/12.6 使用）——这里顺手做类型兜底，避免 env/配置写错炸锅
        try:
            g_random_rate = float(gp.get("random_rate", GROUP_RANDOM_REPLY_RATE))
        except Exception:
            g_random_rate = float(GROUP_RANDOM_REPLY_RATE)

        try:
            g_peach_rate = float(gp.get("peach_random_rate", PEACH_RANDOM_REPLY_RATE))
        except Exception:
            g_peach_rate = float(PEACH_RANDOM_REPLY_RATE)

        try:
            g_offtopic_rate = float(gp.get("wake_offtopic_rate", WAKE_OFFTOPIC_REPLY_RATE))
        except Exception:
            g_offtopic_rate = float(WAKE_OFFTOPIC_REPLY_RATE)

        try:
            g_wake_seconds = int(gp.get("wake_seconds", WAKE_SECONDS))
        except Exception:
            g_wake_seconds = int(WAKE_SECONDS)

        try:
            g_wake_broadcast = bool(gp.get("wake_broadcast", WAKE_BROADCAST))
        except Exception:
            g_wake_broadcast = bool(WAKE_BROADCAST)

        # ✅ 新增：发起新话题时@的概率（给 12.8 用）
        try:
            meta["init_topic_at_rate"] = float(gp.get("init_topic_at_rate", 0.0) or 0.0)
        except Exception:
            meta["init_topic_at_rate"] = 0.0

        # ============================================================
        # 12.5 回复策略决策总入口（按群策略分离）
        # ============================================================
        should_reply = False
        was_awake = False
        meta["reply_reason"] = ""   # trigger / wake_related / wake_offtopic / random

        if scene == "private":
            should_reply = True

        else:
            was_awake = _wake_active(gid_str)
            meta["was_awake"] = bool(was_awake)

            # ============================================================
            # 12.6 A) STRICT 群：只在 @ / 点名 / 引用 才回复
            #       - 不随机、不续命、不靠 wake 继续聊
            # ============================================================
            if is_strict_group or (g_mode == "strict"):
                should_reply = bool(at_me or call_name or quoted)
                if should_reply:
                    meta["reply_reason"] = "trigger"
                # strict：明确不维护 wake（避免“越聊越主动”）

            # ============================================================
            # 12.6 B) RANDOM 群：唤醒 + 相关续命 + 随机插话策略
            # ============================================================
            elif is_random_group or (g_mode == "random"):
                # 1) 强触发：@/点名/引用 → 必回，并进入/刷新唤醒期
                if at_me or call_name or quoted:
                    should_reply = True
                    meta["reply_reason"] = "trigger"
                    _wake_set(gid_str, user_id, text, g_wake_seconds)

                else:
                    # 2) 唤醒期：相关就回，并刷新倒计时（续命）
                    if _wake_active(gid_str):
                        topic = _wake_topic(gid_str)
                        last_uid = _wake_last_user(gid_str)
                        same_user = (str(user_id) == str(last_uid))

                        # wake_broadcast=False：只允许同一触发者续聊
                        if (not bool(g_wake_broadcast)) and (not same_user):
                            related = False
                        else:
                            related = bool(same_user or (topic and is_relevant_to_topic(text, topic)))

                        if related:
                            should_reply = True
                            meta["reply_reason"] = "wake_related"
                            new_topic = (str(topic or "") + " " + str(text or "")).strip()[-500:]
                            _wake_refresh(gid_str, g_wake_seconds, user_id=user_id, topic_text=new_topic, update_topic=True)
                        else:
                            # 唤醒期但不相关：允许极低概率插话（不续命）
                            try:
                                if random.random() < float(g_offtopic_rate):
                                    should_reply = True
                                    meta["reply_reason"] = "wake_offtopic"
                            except Exception:
                                pass

                    # 3) 非唤醒期：随机插话（按本群概率）
                    else:
                        try:
                            if owner:
                                if random.random() < float(g_peach_rate):
                                    should_reply = True
                                    meta["reply_reason"] = "random"
                            else:
                                if random.random() < float(g_random_rate):
                                    should_reply = True
                                    meta["reply_reason"] = "random"
                        except Exception:
                            pass

            # ============================================================
            # 12.6 C) DEFAULT（其它群）：沿用“原全局策略”（仍支持 GROUP_REPLY_ONLY_WHEN_AT）
            # ============================================================
            else:
                if at_me or call_name or quoted:
                    should_reply = True
                    meta["reply_reason"] = "trigger"
                    _wake_set(gid_str, user_id, text, g_wake_seconds)

                else:
                    if _wake_active(gid_str):
                        topic = _wake_topic(gid_str)
                        last_uid = _wake_last_user(gid_str)
                        same_user = (str(user_id) == str(last_uid))

                        if (not bool(g_wake_broadcast)) and (not same_user):
                            related = False
                        else:
                            related = bool(same_user or (topic and is_relevant_to_topic(text, topic)))

                        if related:
                            should_reply = True
                            meta["reply_reason"] = "wake_related"
                            new_topic = (str(topic or "") + " " + str(text or "")).strip()[-500:]
                            _wake_refresh(gid_str, g_wake_seconds, user_id=user_id, topic_text=new_topic, update_topic=True)
                        else:
                            if not GROUP_REPLY_ONLY_WHEN_AT:
                                try:
                                    if random.random() < float(g_offtopic_rate):
                                        should_reply = True
                                        meta["reply_reason"] = "wake_offtopic"
                                except Exception:
                                    pass

                    else:
                        if not GROUP_REPLY_ONLY_WHEN_AT:
                            try:
                                if owner:
                                    if random.random() < float(g_peach_rate):
                                        should_reply = True
                                        meta["reply_reason"] = "random"
                                else:
                                    if random.random() < float(g_random_rate):
                                        should_reply = True
                                        meta["reply_reason"] = "random"
                            except Exception:
                                pass

        # 不回复则跳过
        if not should_reply:
            if DEBUG and scene == "group":
                print(f"[bridge] skip: gid={group_id} uid={user_id} name={sender_name} at={at_me} call={call_name} quote={quoted} text={text[:50]}")
            continue

        # ============================================================
        # 12.7 调后端生成回复
        #   ✅ 修复：call_backend_async 不接受 timeout 参数，传了就会 TypeError → WS 断线 → 全部空回
        #   ✅ 约定：call_backend_async 返回 str（reply 文本），这里统一落到 reply_raw/reply_full
        # ============================================================
        backend_t0 = time.time()
        try:
            reply_raw = await call_backend_async(text, meta)   # ✅ 不要再传 timeout=
            reply_full = (reply_raw or "").strip()
        except Exception as e:
            reply_full = f"(Backend request exception: {e})"
        backend_ms = int((time.time() - backend_t0) * 1000)
        if DEBUG or backend_ms >= 1500:
            try:
                print(f"[bridge][timing] backend_ms={backend_ms} scene={scene} uid={user_id} gid={group_id}")
            except Exception:
                pass

        if not reply_full:
            reply_full = "(Model returned empty reply)"

        # ============================================================
        # 12.8 QQ 友好输出（引用/分段/@/表情包）
        # ============================================================

        # —— 0) 先做 QQ 文本净化（去 markdown / 动作星号等）——
        reply_full = sanitize_for_qq(reply_full)

        # —— 1) 默认“短回复”（<=200字），但遇到画图 prompt/长内容请求就放开 —— 
        def _need_long_reply(user_text: str, bot_text: str) -> bool:
            ut = (user_text or "").lower()
            bt = (bot_text or "").lower()

            # 用户明确要长内容：prompt/提示词/参数/完整/全套/negative 等
            long_hints = ["prompt", "提示词", "negative", "正向", "反向", "参数", "完整", "全套", "长一点", "详细", "原文", "列表"]
            if any(k in ut for k in long_hints):
                return True

            # 模型输出像 SD prompt（逗号密集 + 典型词）
            sd_markers = ["masterpiece", "best quality", "ultra-detailed", "cinematic lighting", "negative prompt"]
            if (bt.count(",") >= 12) and any(m in bt for m in sd_markers):
                return True

            return False

        allow_long = _need_long_reply(text, reply_full)
        if not allow_long:
            try:
                soft_limit = int(os.getenv("MODEL_REPLY_SOFT_LIMIT", "0"))
            except Exception:
                soft_limit = 0
            if soft_limit > 0 and len(reply_full) > soft_limit:
                reply_full = reply_full[:soft_limit].rstrip() + "…"

        # —— 2) 表情包指令（末尾一行 [EMOJI:xxx]）——
        reply_full, emoji_rel = extract_emoji_directive(reply_full)
        emoji_abs = resolve_emoji_path(emoji_rel) if emoji_rel else ""

        # ✅ 自动表情包兜底（如果模型没按 [EMOJI:...] 输出）
        def _guess_emoji_category(text_: str) -> str:
            t = strip_cq_codes(text_ or "")
            rules = [
                ("无语", ["无语", "。。。", "……", "离谱", "汗", "？？", "?"]),
                ("开心", ["哈哈", "笑死", "开心", "好耶", "耶", "太好了", "hh", "lol"]),
                ("撒娇", ["求求", "嘛", "嘤", "贴贴", "撒娇"]),
                ("安慰", ["抱抱", "别难过", "没事", "我在", "安慰", "心疼"]),
                ("鼓掌", ["鼓掌", "厉害", "牛", "太强了", "respect"]),
                ("害羞", ["害羞", "脸红", "不好意思", "呜呜"]),
                ("生气", ["生气", "气死", "烦", "恼火", "你完了"]),
                ("震惊", ["震惊", "什么", "啊？", "不会吧", "卧槽", "离大谱"]),
                ("再见", ["再见", "拜拜", "回头见", "晚安"]),
                ("点头", ["好的", "行", "嗯", "明白", "收到", "可以"]),
                ("伤心", ["伤心", "悲伤", "哭泣", "哭唧唧", "嘤嘤嘤", "555", "呜呜"]),
            ]
            for cat, kws in rules:
                for k in kws:
                    if k and k in t:
                        return cat
            return ""

        def _pick_any_emoji_file(root: str) -> str:
            if not root or (not os.path.exists(root)):
                return ""
            exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
            cand = []
            for base, _, files in os.walk(root):
                for fn in files:
                    if fn.lower().endswith(exts):
                        cand.append(os.path.join(base, fn))
            return random.choice(cand) if cand else ""

        def _auto_pick_emoji_abs(text_: str) -> str:
            # 私聊更高一点，群聊更克制一点
            sc = str(scene).strip()
            p = 0.22 if sc == "private" else 0.10
            if random.random() >= p:
                return ""

            root = EMOJI_ROOT if os.path.exists(EMOJI_ROOT) else os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "emojis"
            )
            if not os.path.exists(root):
                return ""

            cat = _guess_emoji_category(text_)
            if cat:
                f = _pick_any_emoji_file(os.path.join(root, cat))
                if f:
                    return f
            return _pick_any_emoji_file(root)

        if not emoji_abs:
            emoji_abs = _auto_pick_emoji_abs(reply_full)

        # —— 3) 分段发送文本（按 REPLY_MAX_CHARS）——
        reply_send = reply_full
        parts = split_long_text(reply_send, REPLY_MAX_CHARS)
        if not parts:
            parts = ["(Model returned empty reply)"]

        # 发送目标合法性：避免 user_id/group_id 异常时把请求送给 QQ 内核导致超时/无回执
        if scene == "private":
            if not is_valid_numeric_id(user_id):
                print(f"[bridge] skip send private: invalid user_id={user_id!r}")
                continue
        else:
            if not is_valid_numeric_id(group_id):
                print(f"[bridge] skip send group: invalid group_id={group_id!r}")
                continue

        # 刚离线恢复保护：给 QQNT 内核一个小缓冲，减少 sendMsg timeout
        guard_wait = _send_guard_wait_s(scene)
        if guard_wait > 0:
            try:
                await asyncio.sleep(guard_wait)
            except Exception:
                pass

        if REQUIRE_ONLINE_BEFORE_SEND and (bot_online is False):
            print(f"[bridge] skip send: bot offline (scene={scene}, uid={user_id}, gid={group_id})")
            continue

        # 群聊：只有“触发回复”（@/点名/引用）才给对方一个 @，避免随机插话乱@人
        triggered = (scene == "group" and (at_me or call_name or quoted))
        at_uid = str(user_id).strip() if triggered else ""

        # 群聊：引用 reply（如果拿到了 msg_id）
        def _build_prefix_segments(include_reply: bool, include_at: bool) -> List[Dict[str, Any]]:
            segs: List[Dict[str, Any]] = []
            if include_reply and msg_id:
                segs.append({"type": "reply", "data": {"id": str(msg_id)}})
            if include_at and at_uid:
                segs.append({"type": "at", "data": {"qq": str(at_uid)}})
            return segs

        # ✅ 群聊接话：先等一下再回（群B更快）
        if triggered:
            try:
                if is_random_group:
                    await asyncio.sleep(float(os.getenv("GROUP_B_REPLY_DELAY", "2.0")))
                else:
                    await asyncio.sleep(random.uniform(REPLY_DELAY_MIN, REPLY_DELAY_MAX))
            except Exception:
                pass

        tts_should_send = bool(QQ_TTS_ENABLE and ((not QQ_TTS_PRIVATE_ONLY) or (scene == "private")))
        if tts_should_send and QQ_TTS_SKIP_ERROR_TEXT and _should_skip_tts_for_text(reply_full):
            tts_should_send = False
            if DEBUG:
                preview = re.sub(r"\s+", " ", str(reply_full or "")).strip()
                if len(preview) > 140:
                    preview = preview[:140] + "…"
                print(f"[bridge][tts] skip error-like text: {preview}")
        voice_refs_cache: Optional[List[str]] = None

        async def _get_voice_refs() -> List[str]:
            nonlocal voice_refs_cache
            if voice_refs_cache is not None:
                return voice_refs_cache
            if not tts_should_send:
                voice_refs_cache = []
                return voice_refs_cache
            try:
                refs = await asyncio.to_thread(request_tts_audio_refs, reply_full)
                if refs:
                    refs = await asyncio.to_thread(maybe_merge_tts_refs, refs, scene)
                voice_refs_cache = refs
            except Exception as e:
                print(f"[bridge][tts] prepare refs failed: {e}")
                voice_refs_cache = []
            return voice_refs_cache

        async def _send_tts_records() -> int:
            if not tts_should_send:
                return 0
            try:
                voice_refs = await _get_voice_refs()
                if not voice_refs:
                    return 0
                for k, voice_ref in enumerate(voice_refs, start=1):
                    if QQ_TTS_SEND_DELAY_S > 0:
                        await asyncio.sleep(QQ_TTS_SEND_DELAY_S)
                    if scene == "private":
                        await send_voice_private(ws, user_id, voice_ref)
                    else:
                        await send_voice_group(ws, group_id, voice_ref)
                    if DEBUG:
                        print(f"[bridge][tts] voice sent {k}/{len(voice_refs)} scene={scene} uid={user_id} gid={group_id}")
                return len(voice_refs)
            except Exception as e:
                print(f"[bridge][tts] send failed: {e}")
                return 0

        async def _send_private_voice_first_combined() -> bool:
            if scene != "private":
                return False
            if not tts_should_send:
                return False
            if not QQ_TTS_PRIVATE_COMBINE_SEND:
                return False
            if QQ_TTS_SEND_ORDER != "voice_first":
                return False

            voice_refs = await _get_voice_refs()
            if not voice_refs:
                return False

            try:
                # 兼容性优先：私聊里“record+text 同链”在部分 QQ/NapCat 组合会吞文字。
                # 这里改为“先语音后文字（文字单独发）”，只用首条 record 触发移动端提示。
                await send_private_segments(ws, user_id, [_record_segment(voice_refs[0])])

                for voice_ref in voice_refs[1:]:
                    if QQ_TTS_SEND_DELAY_S > 0:
                        await asyncio.sleep(QQ_TTS_SEND_DELAY_S)
                    await send_voice_private(ws, user_id, voice_ref)

                for i, part in enumerate(parts):
                    if i > 0:
                        await asyncio.sleep(0.35)
                    await send_private(ws, user_id, part)
                if DEBUG:
                    print(f"[bridge][tts] private combined sent refs={len(voice_refs)} parts={len(parts)}")
                return True
            except Exception as e:
                print(f"[bridge][tts] private combined send failed: {e}")
                return False

        text_send_ok = True
        send_t0 = time.time()
        combined_private_done = False

        # 语音优先：用于提升移动端“新消息弹出”命中率
        if QQ_TTS_SEND_ORDER == "voice_first":
            combined_private_done = await _send_private_voice_first_combined()
            if not combined_private_done:
                sent_voice_count = await _send_tts_records()
                if sent_voice_count > 0:
                    post_delay = max(
                        float(QQ_TTS_TEXT_AFTER_VOICE_DELAY_S),
                        min(12.0, 2.0 * float(sent_voice_count)),
                    )
                    try:
                        await asyncio.sleep(post_delay)
                    except Exception:
                        pass

        # —— 4) 发送文本（首段可带 reply/@，后续段不重复堆）——
        if not combined_private_done:
            for i, part in enumerate(parts):
                if scene == "private":
                    try:
                        await send_private(ws, user_id, part)
                    except Exception as e:
                        print(f"[bridge] send private failed uid={user_id}: {e}")
                        text_send_ok = False
                        break
                else:
                    segs = []
                    if i == 0:
                        segs += _build_prefix_segments(include_reply=True, include_at=True)
                    segs.append({"type": "text", "data": {"text": part}})
                    payload = {
                        "action": "send_group_msg",
                        "params": {"group_id": str(group_id), "message": segs},
                    }
                    try:
                        await ws_send_json(ws, payload)
                    except Exception as e:
                        # 首段降级：去掉 reply/@ 前缀，至少把正文发出去
                        if i == 0:
                            try:
                                fallback_payload = {
                                    "action": "send_group_msg",
                                    "params": {
                                        "group_id": str(group_id),
                                        "message": [{"type": "text", "data": {"text": part}}],
                                    },
                                }
                                await ws_send_json(ws, fallback_payload)
                                print(f"[bridge] group first part fallback sent (drop reply/@), gid={group_id}")
                                continue
                            except Exception as e2:
                                print(f"[bridge] send group failed gid={group_id}: {e2}")
                                text_send_ok = False
                                break
                        else:
                            print(f"[bridge] send group failed gid={group_id}: {e}")
                            text_send_ok = False
                            break

                # 分段之间稍微喘口气，避免刷屏/风控
                if i < len(parts) - 1:
                    try:
                        await asyncio.sleep(0.35)
                    except Exception:
                        pass
        send_ms = int((time.time() - send_t0) * 1000)
        if DEBUG or send_ms >= 1200:
            try:
                print(f"[bridge][timing] send_ms={send_ms} parts={len(parts)} scene={scene} uid={user_id} gid={group_id} ok={text_send_ok}")
            except Exception:
                pass

        # text_first 模式下：文本先发，语音可异步后置（不阻塞本轮 handler）
        if text_send_ok and (QQ_TTS_SEND_ORDER != "voice_first") and (not combined_private_done):
            if QQ_TTS_TEXT_FIRST_ASYNC:
                async def _tts_after_text():
                    try:
                        if QQ_TTS_TEXT_FIRST_ASYNC_DELAY_S > 0:
                            await asyncio.sleep(float(QQ_TTS_TEXT_FIRST_ASYNC_DELAY_S))
                        _ = await _send_tts_records()
                    except asyncio.CancelledError:
                        return
                    except Exception as e:
                        print(f"[bridge][tts] async text_first send failed: {e}")

                t = asyncio.create_task(_tts_after_text())
                _track_bg_task(ws, t)
                if DEBUG:
                    print(f"[bridge][tts] scheduled async after text scene={scene} uid={user_id} gid={group_id}")
            else:
                _ = await _send_tts_records()

        # —— 5) 如有表情包：跟在文本后发送（私聊/群聊都支持）——
        if text_send_ok and emoji_abs and os.path.exists(emoji_abs):
            try:
                if scene == "private":
                    await send_image_private(ws, user_id, emoji_abs)
                else:
                    await send_image_group(ws, group_id, emoji_abs)
            except Exception as e:
                print(f"[bridge] send emoji failed: {e}")

        # ============================================================
        # 12.9 状态回写：循环检测 & 唤醒话题续命/更新
        # ============================================================

        # 12.9.1 循环检测：记录机器人上一句
        if scene == "group" and str(group_id).strip():
            LOOP_STATE[str(group_id)] = {
                "last_bot_reply": (reply_full or "")[:600],
                "ts": time.time(),
            }

        # 12.9.2 唤醒话题更新（STRICT 不维护，避免越聊越主动）
        if scene == "group" and str(group_id).strip() and (not is_strict_group):
            if at_me or call_name or quoted:
                _wake_refresh(
                    group_id,
                    g_wake_seconds,
                    user_id=str(user_id),
                    topic_text=text,
                    update_topic=True,
                )
            elif _wake_active(group_id):
                _wake_refresh(
                    group_id,
                    g_wake_seconds,
                    user_id=_wake_last_user(group_id),
                    topic_text=_wake_topic(group_id),
                    update_topic=False,
                )

    # 连接断开时回收该连接挂起的异步 TTS 任务与发送锁
    _cancel_bg_tasks_for_ws(ws)

# ============================================================
# 13. main() 与服务器启动
# ============================================================

async def main():
    print(f"[bridge] BACKEND_CHAT = {BACKEND_CHAT}")
    print(f"[bridge] Reverse WS Server listening: ws://{REVERSE_WS_HOST}:{REVERSE_WS_PORT}{REVERSE_WS_PATH}")
    print(f"[bridge] OWNER_QQ = {OWNER_QQ if OWNER_QQ else '(empty)'}")
    print(f"[bridge] BOT_NAME_KEYWORDS = {', '.join(BOT_NAME_KEYWORDS) if BOT_NAME_KEYWORDS else '(empty)'}")
    print(f"[bridge] PRIVATE_SEND_MODE = {PRIVATE_SEND_MODE} (legacy={PRIVATE_LEGACY_SEND_PRIVATE}, auto_escape={PRIVATE_SEND_AUTO_ESCAPE})")
    print(f"[bridge] QQ_TTS_ENABLE = {QQ_TTS_ENABLE} private_only={QQ_TTS_PRIVATE_ONLY} voice_id={QQ_TTS_VOICE_ID}")
    print(f"[bridge] QQ_TTS_MAX_CHARS = {QQ_TTS_MAX_CHARS} max_segments={QQ_TTS_MAX_SEGMENTS} min_segment_chars={QQ_TTS_MIN_SEGMENT_CHARS}")
    print(f"[bridge] QQ_TTS_SEND_ORDER = {QQ_TTS_SEND_ORDER} text_after_voice_delay={QQ_TTS_TEXT_AFTER_VOICE_DELAY_S}s")
    print(f"[bridge] QQ_TTS_PRIVATE_COMBINE_SEND = {QQ_TTS_PRIVATE_COMBINE_SEND}")
    print(f"[bridge] QQ_TTS_SKIP_ERROR_TEXT = {QQ_TTS_SKIP_ERROR_TEXT}")
    print(f"[bridge] QQ_TTS_MERGE_SEGMENTS = {QQ_TTS_MERGE_SEGMENTS} private_only={QQ_TTS_MERGE_PRIVATE_ONLY}")
    print(f"[bridge] QQ_TTS_STRIP_LATIN = {QQ_TTS_STRIP_LATIN}")
    print(f"[bridge] QQ_TTS_LOCK_VOICE_PER_TURN = {QQ_TTS_LOCK_VOICE_PER_TURN}")
    print(f"[bridge] QQ_TTS_TEXT_FIRST_ASYNC = {QQ_TTS_TEXT_FIRST_ASYNC} delay={QQ_TTS_TEXT_FIRST_ASYNC_DELAY_S}s")
    print(f"[bridge] MODEL_REPLY_SOFT_LIMIT = {os.getenv('MODEL_REPLY_SOFT_LIMIT', '0')}")
    print(f"[bridge] BACKEND_TTS_URL = {BACKEND_TTS_URL}")
    print(f"[bridge] GROUP_RANDOM_REPLY_RATE = {GROUP_RANDOM_REPLY_RATE}")
    print(f"[bridge] WAKE_SECONDS = {WAKE_SECONDS}")
    print(f"[bridge] WAKE_BROADCAST = {WAKE_BROADCAST}")

    async def _router(ws, path):
        # 兼容 NapCat / WebLogin 常见路径：
        # - /ws
        # - /ws?token=...
        # - /
        raw_path = str(path or "")
        parsed_path = urlsplit(raw_path).path or "/"
        expect_path = str(REVERSE_WS_PATH or "/ws").strip() or "/ws"
        expect_path = expect_path if expect_path.startswith("/") else ("/" + expect_path)
        expect_path_norm = expect_path.rstrip("/") or "/"
        parsed_path_norm = parsed_path.rstrip("/") or "/"

        allowed = {expect_path_norm, "/"}
        if parsed_path_norm not in allowed:
            if DEBUG:
                print(f"[bridge] reject ws path: raw={raw_path!r} parsed={parsed_path!r} expected={expect_path_norm!r}")
            try:
                await ws.close()
            except Exception:
                pass
            return
        await handler(ws, raw_path or parsed_path)

    # 建议加 ping_interval 防止某些网络环境假死
    try:
        server = await websockets.serve(
            _router,
            REVERSE_WS_HOST,
            REVERSE_WS_PORT,
            ping_interval=None,
            ping_timeout=None,
        )
    except OSError as e:
        if getattr(e, "errno", None) == 10048:
            print(f"[bridge] 启动失败：端口 {REVERSE_WS_PORT} 已被占用（通常是已有 napcat_bridge.py 在运行）")
            print("[bridge] 请先结束旧进程，或修改环境变量 REVERSE_WS_PORT 后重启（NapCat 端也要同步改端口）")
            return
        raise

    print("[bridge] 服务已就绪，正在等待 NapCat/WebLogin 连接...")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
