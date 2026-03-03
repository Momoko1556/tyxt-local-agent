import os
import re
import time
import io
import wave
import unicodedata
import shutil
try:
    import audioop
except Exception:
    audioop = None
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

try:
    from PIL import Image, ImageEnhance
except Exception:
    Image = None
    ImageEnhance = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    import requests
except Exception:
    requests = None


_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_ALLOWED_DIR = os.path.join(_PROJECT_ROOT, "Ollama_agent_shared")
_DEFAULT_TESSERACT_PATH = ""
_DEFAULT_SOVITS_TTS_URL = "http://127.0.0.1:9880/tts"
_DEFAULT_SOVITS_REF_AUDIO_DIR = os.path.join(_PROJECT_ROOT, "GPT-SoVITS-1007-cu124", "Cove参考音频文件")


def _default_voice_presets(ref_audio_dir: str) -> Dict[str, Dict[str, str]]:
    ref_dir = os.path.abspath(str(ref_audio_dir or _DEFAULT_SOVITS_REF_AUDIO_DIR))
    return {
        "default": {
            "ref_audio_path": os.path.join(ref_dir, "就算是这样，也不至于直接碎掉啊，除非.wav"),
            "prompt_text": "通常、中性、自然的语气。",
            "prompt_lang": "zh",
        },
        "calm": {
            "ref_audio_path": os.path.join(ref_dir, "就算是这样，也不至于直接碎掉啊，除非.wav"),
            "prompt_text": "语速平稳，语气沉静。",
            "prompt_lang": "zh",
        },
        "warm": {
            "ref_audio_path": os.path.join(ref_dir, "宝贝，不要害怕，也不要哭了.wav"),
            "prompt_text": "轻松、温柔、像朋友聊天。",
            "prompt_lang": "zh",
        },
        "bright": {
            "ref_audio_path": os.path.join(ref_dir, "哇，你真的太棒了！我替你感到开心！.wav"),
            "prompt_text": "活泼、有一点明亮的情绪。",
            "prompt_lang": "zh",
        },
        "serious": {
            "ref_audio_path": os.path.join(ref_dir, "就算是这样，也不至于直接碎掉啊，除非.wav"),
            "prompt_text": "偏正式、说明书风格。",
            "prompt_lang": "zh",
        },
        "angry": {
            "ref_audio_path": os.path.join(ref_dir, "你真的有在乎过我的感受吗？我真的受够了！.wav"),
            "prompt_text": "情绪强烈、偏生气语气。",
            "prompt_lang": "zh",
        },
    }


_TTS_CONFIG: Dict[str, Any] = {
    "tts_url": os.getenv("SOVITS_TTS_URL", _DEFAULT_SOVITS_TTS_URL),
    "allowed_dir": os.path.abspath(str(os.getenv("ALLOWED_DIR", _DEFAULT_ALLOWED_DIR))),
    "output_dir": os.path.abspath(str(os.getenv("TTS_OUTPUT_DIR", os.path.join(os.getenv("ALLOWED_DIR", _DEFAULT_ALLOWED_DIR), "tts")))),
    "text_split_method": os.getenv("SOVITS_TEXT_SPLIT_METHOD", "cut0"),
    "voice_presets": _default_voice_presets(os.getenv("SOVITS_REF_AUDIO_DIR", _DEFAULT_SOVITS_REF_AUDIO_DIR)),
}


def configure_tts(
    tts_url: Optional[str] = None,
    allowed_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    text_split_method: Optional[str] = None,
    voice_presets: Optional[Dict[str, Dict[str, str]]] = None,
) -> None:
    """
    由后端主程序在启动时注入 TTS 配置，避免硬编码耦合。
    """
    if tts_url is not None:
        _TTS_CONFIG["tts_url"] = str(tts_url or "").strip()

    if allowed_dir is not None:
        _TTS_CONFIG["allowed_dir"] = os.path.abspath(str(allowed_dir or _DEFAULT_ALLOWED_DIR))

    if output_dir is not None:
        _TTS_CONFIG["output_dir"] = os.path.abspath(str(output_dir or os.path.join(_TTS_CONFIG["allowed_dir"], "tts")))

    if text_split_method is not None:
        _TTS_CONFIG["text_split_method"] = str(text_split_method or "").strip() or "cut0"

    if isinstance(voice_presets, dict) and voice_presets:
        normalized: Dict[str, Dict[str, str]] = {}
        for k, v in voice_presets.items():
            if not isinstance(v, dict):
                continue
            key = str(k or "").strip() or "default"
            normalized[key] = {
                "ref_audio_path": str(v.get("ref_audio_path") or "").strip(),
                "prompt_text": str(v.get("prompt_text") or "").strip(),
                "prompt_lang": str(v.get("prompt_lang") or "zh").strip() or "zh",
            }
        if normalized:
            _TTS_CONFIG["voice_presets"] = normalized

    try:
        os.makedirs(_TTS_CONFIG["output_dir"], exist_ok=True)
    except Exception as e:
        print(f"[multimodal_tools] ensure tts output dir failed: {e}")


def _allowed_dir() -> str:
    p = os.getenv("ALLOWED_DIR", _DEFAULT_ALLOWED_DIR)
    return os.path.abspath(str(p or _DEFAULT_ALLOWED_DIR))


def _resolve_image_path(image_path: str) -> Optional[str]:
    p = str(image_path or "").strip().strip('"').strip("'")
    if not p:
        return None
    if os.path.isabs(p):
        return os.path.abspath(p)
    return os.path.abspath(os.path.join(_allowed_dir(), p))


def _configure_tesseract() -> str:
    if pytesseract is None:
        return ""

    tpath = _detect_tesseract_path()

    if tpath:
        try:
            pytesseract.pytesseract.tesseract_cmd = tpath
        except Exception as e:
            print(f"[multimodal_tools] set tesseract path failed: {e}")
    return tpath


def _detect_tesseract_path() -> str:
    """
    优先级：
    1) .env / 环境变量 TESSERACT_PATH（且路径存在）
    2) 系统 PATH 自动发现（tesseract）
    """
    env_tpath = str(os.getenv("TESSERACT_PATH", _DEFAULT_TESSERACT_PATH) or "").strip()
    if env_tpath:
        if os.path.exists(env_tpath):
            return env_tpath
        print(f"[multimodal_tools] TESSERACT_PATH not found, fallback to PATH: {env_tpath}")

    auto_path = str(shutil.which("tesseract") or "").strip()
    return auto_path


def ocr_status() -> Dict[str, Any]:
    """
    返回 OCR 可用性状态，用于 UI/健康检测展示。
    """
    has_pillow = (Image is not None) and (ImageEnhance is not None)
    has_pyt = pytesseract is not None
    tpath = _detect_tesseract_path()
    tpath_exists = bool(tpath and os.path.exists(tpath))

    if has_pyt and tpath_exists:
        try:
            pytesseract.pytesseract.tesseract_cmd = tpath
        except Exception:
            pass

    available = bool(has_pillow and has_pyt and tpath_exists)
    reason = ""
    if not has_pillow:
        reason = "missing Pillow dependency"
    elif not has_pyt:
        reason = "missing pytesseract dependency"
    elif not tpath_exists:
        reason = "tesseract executable not found"

    return {
        "available": available,
        "has_pillow": bool(has_pillow),
        "has_pytesseract": bool(has_pyt),
        "tesseract_path": str(tpath or ""),
        "reason": reason,
    }


def ocr_image(image_path: str) -> str:
    """
    输入：本地图片的绝对路径或共享目录内的路径字符串。
    输出：从图片中识别出的纯文本（str）。
    要求：兼容当前后端已有的 OCR 行为和异常处理。
    """
    if Image is None or ImageEnhance is None or pytesseract is None:
        msg = "❌ OCR 不可用：缺少依赖（Pillow/pytesseract）"
        print(f"[multimodal_tools] {msg}")
        return msg

    resolved = _resolve_image_path(image_path)
    if not resolved:
        return "❌ OCR 失败：image_path 为空"
    if not os.path.exists(resolved):
        return f"❌ OCR 失败：图片不存在：{image_path}"
    if not os.path.isfile(resolved):
        return f"❌ OCR 失败：不是文件路径：{image_path}"

    tpath = _configure_tesseract()
    if tpath and (not os.path.exists(tpath)):
        msg = f"❌ OCR 不可用：Tesseract 路径不存在：{tpath}"
        print(f"[multimodal_tools] {msg}")
        return msg

    lang = str(os.getenv("OCR_LANG", "chi_sim+eng") or "chi_sim+eng")
    try:
        with Image.open(resolved) as img:
            enhanced = ImageEnhance.Contrast(img).enhance(1.5)
            txt = pytesseract.image_to_string(enhanced, lang=lang)
        return str(txt or "")
    except Exception as e:
        print(f"[multimodal_tools] OCR failed for {resolved}: {e}")
        return f"❌ OCR 识别失败: {e}"


def _choose_voice_preset(voice_id: str) -> Tuple[str, Dict[str, str]]:
    presets = _TTS_CONFIG.get("voice_presets") or {}
    if not isinstance(presets, dict) or not presets:
        presets = _default_voice_presets(os.getenv("SOVITS_REF_AUDIO_DIR", _DEFAULT_SOVITS_REF_AUDIO_DIR))

    requested = str(voice_id or "").strip() or "default"
    if requested in presets:
        return requested, dict(presets.get(requested) or {})
    if "default" in presets:
        return "default", dict(presets.get("default") or {})
    # 兜底：取第一个可用项
    first_key = next(iter(presets.keys()), "default")
    return first_key, dict(presets.get(first_key) or {})


def _first_ref_audio_in_dir(ref_dir: str) -> str:
    try:
        if not ref_dir:
            return ""
        abs_dir = os.path.abspath(str(ref_dir))
        if not os.path.isdir(abs_dir):
            return ""
        names = sorted(os.listdir(abs_dir))
        for n in names:
            ext = os.path.splitext(n)[1].lower()
            if ext in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
                return os.path.join(abs_dir, n)
    except Exception:
        pass
    return ""


def _pick_ref_audio_in_dir(ref_dir: str, voice_id: str = "default", prompt_text: str = "") -> str:
    """
    在预设缺失时，从目录中挑一个“更符合 voice_id 语气”的参考音频：
    - default/calm/warm 优先温和中性，尽量避开“生气/崩溃”措辞
    - bright 优先积极词
    - serious 优先正式词
    """
    try:
        abs_dir = os.path.abspath(str(ref_dir or ""))
        if not os.path.isdir(abs_dir):
            return ""
        files = []
        for n in sorted(os.listdir(abs_dir)):
            ext = os.path.splitext(n)[1].lower()
            if ext in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
                files.append(os.path.join(abs_dir, n))
        if not files:
            return ""
        if len(files) == 1:
            return files[0]

        v = str(voice_id or "default").strip().lower()
        ptxt = str(prompt_text or "")

        preferred_map = {
            "default": ["default", "neutral", "normal", "calm", "warm", "温和", "自然", "平稳", "亲切", "温柔"],
            "calm": ["calm", "quiet", "steady", "沉静", "平稳", "冷静", "舒缓", "慢"],
            "warm": ["warm", "gentle", "soft", "温柔", "亲切", "轻松", "朋友", "安抚"],
            "bright": ["bright", "happy", "joy", "smile", "活泼", "明亮", "开心", "太棒", "高兴"],
            "serious": ["serious", "formal", "manual", "正式", "说明", "专业", "稳重"],
        }
        avoid_common = [
            "angry", "mad", "rage", "furious",
            "生气", "愤怒", "受够", "崩溃", "烦", "吵", "骂", "滚", "讨厌", "恨",
        ]
        avoid_map = {
            "default": avoid_common,
            "calm": avoid_common,
            "warm": avoid_common,
            "bright": ["受够", "生气", "愤怒", "崩溃", "angry", "rage"],
            "serious": ["太棒", "开心", "活泼", "bright", "happy", "joy"],
        }

        preferred = list(preferred_map.get(v, preferred_map["default"]))
        if "温和" in ptxt or "自然" in ptxt or "亲切" in ptxt:
            preferred.extend(["温和", "自然", "亲切", "温柔"])
        if "活泼" in ptxt or "明亮" in ptxt:
            preferred.extend(["活泼", "明亮", "开心", "太棒"])
        avoid = list(avoid_map.get(v, avoid_common))

        best_path = files[0]
        best_score = -10**9

        for fp in files:
            stem = os.path.splitext(os.path.basename(fp))[0]
            name = stem.lower()
            score = 0

            for kw in preferred:
                if kw and kw.lower() in name:
                    score += 3
            for kw in avoid:
                if kw and kw.lower() in name:
                    score -= 5

            # default/calm/warm 更偏向简短中性的参考句，降低强情绪长句命中概率
            if v in {"default", "calm", "warm"}:
                if len(stem) <= 18:
                    score += 1
                elif len(stem) >= 30:
                    score -= 1

            # 二级排序：分数相同优先文件名更短
            if score > best_score or (score == best_score and len(stem) < len(os.path.splitext(os.path.basename(best_path))[0])):
                best_score = score
                best_path = fp

        print(f"[multimodal_tools] fallback ref pick voice={v} score={best_score} -> {best_path}")
        return best_path
    except Exception:
        return _first_ref_audio_in_dir(ref_dir)


def _safe_voice_name(voice_id: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(voice_id or "default")).strip("_")
    return s or "default"


def _infer_prompt_text_from_ref(ref_audio_path: str) -> str:
    """
    若参考音频文件名本身是可读中文句子，则把它当 prompt_text。
    例如：`宝贝，不要害怕，也不要哭了.wav` -> `宝贝，不要害怕，也不要哭了`
    """
    try:
        base = os.path.basename(str(ref_audio_path or ""))
        stem = os.path.splitext(base)[0].strip()
        if not stem:
            return ""
        # 清理常见无关后缀
        stem = re.sub(r"[_\-]+", " ", stem).strip()
        stem = re.sub(r"\s+", " ", stem).strip()
        # 至少包含一个中文且长度合理
        if re.search(r"[\u4e00-\u9fff]", stem) and 2 <= len(stem) <= 120:
            return stem
    except Exception:
        pass
    return ""


def _is_style_placeholder_prompt(prompt_text: str) -> bool:
    s = str(prompt_text or "").strip()
    if not s:
        return True
    # 常见“风格描述”关键词（不是参考音频逐字文本）
    kws = [
        "女声", "语速", "语气", "温和", "活泼", "正式", "风格", "朋友聊天",
        "亲切", "沉静", "说明书", "情绪", "自然"
    ]
    return any(k in s for k in kws)


def _normalize_tts_input_text(text: str) -> str:
    """
    对送入 SoVITS 的文本做最小归一化：
    不做语义改写，不裁剪句首内容。
    """
    t = str(text or "")
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("\u200b", "").replace("\ufeff", "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    # 屏蔽 ChatGPT 相关词（含空格/连字符变体），避免被 TTS 读出来
    t = re.sub(r"(?i)chat\s*[-_ ]*\s*gpt(?:\s*[-_ ]*\d+)?", " ", t)
    t = re.sub(r"(?i)c\s*h\s*a\s*t\s*g\s*p\s*t", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _sanitize_tts_prompt_text(prompt_text: str) -> str:
    """
    清洗参考文本 prompt_text，避免把标签词/无关词（如 ChatGPT）带入 SoVITS 提示。
    """
    s = str(prompt_text or "")
    if not s:
        return "你好。"

    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u200b", "").replace("\ufeff", "")
    s = re.sub(r"\[CQ:[^\]]+\]", " ", s, flags=re.I)
    s = re.sub(r"https?://\S+", " ", s, flags=re.I)
    s = re.sub(r"[【\[][^】\]]{0,24}[】\]]", " ", s)  # 去掉类似【默认】的标签
    s = re.sub(r"(?i)chat\s*[-_ ]*\s*gpt(?:\s*[-_ ]*\d+)?", " ", s)
    s = re.sub(r"(?i)c\s*h\s*a\s*t\s*g\s*p\s*t", " ", s)
    s = re.sub(r"\s+", " ", s).strip()

    # 只保留常见可读字符，避免花样符号污染提示文本
    s = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9，。！？；：、“”‘’（）()【】《》,.!?;:'\"\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ，,。.!?！？；;：:")
    if not s:
        return "你好。"
    if len(s) > 80:
        s = s[:80].rstrip("，,。.!?！？；;：: ") + "。"
    return s


def _count_speak_chars(text: str) -> int:
    if not text:
        return 0
    # 统计“可发音主体字符”，忽略空白和常见标点
    s = re.sub(r"[\s，。！？、；：,.!?;:~\-—_\"'`“”‘’（）()\[\]{}<>《》【】…]+", "", str(text))
    return len(s)


def _infer_voice_id_from_text(text: str) -> str:
    """
    从文本粗略推断 voice_id（仅在请求 voice_id=default/auto 时启用）。
    """
    s = str(text or "").strip().lower()
    if not s:
        return "default"

    # 常见否定，避免“别生气/不生气”被判为 angry
    if any(x in s for x in ["别生气", "不生气", "别急", "冷静", "没生气"]):
        return "calm"

    angry_kws = [
        "生气", "愤怒", "火大", "受够", "烦死", "别惹", "讨厌", "气死", "骂", "怒",
        "angry", "furious", "rage", "mad",
    ]
    bright_kws = [
        "开心", "高兴", "喜悦", "太棒", "哈哈", "笑", "兴奋", "快乐", "惊喜",
        "happy", "great", "awesome", "joy", "glad",
    ]
    warm_kws = [
        "抱抱", "安慰", "别怕", "没事", "温柔", "心疼", "在这", "听着", "宝贝", "亲爱的",
        "comfort", "gentle", "warm", "soft",
    ]
    serious_kws = [
        "正式", "说明", "步骤", "请注意", "结论", "因此", "方案", "汇报", "条款", "规范",
        "serious", "formal", "manual",
    ]

    if any(k in s for k in angry_kws):
        return "angry"
    if any(k in s for k in bright_kws):
        return "bright"
    if any(k in s for k in warm_kws):
        return "warm"
    if any(k in s for k in serious_kws):
        return "serious"
    return "default"


def _merge_short_segments(text: str, min_segment_chars: int = 8) -> str:
    """
    把过短分句与相邻句合并，降低 SoVITS 句级切分后吞句/静音风险。
    只做轻度合并，不改变文本主语义。
    """
    t = str(text or "").strip()
    if not t:
        return ""
    min_chars = max(1, int(min_segment_chars or 1))

    # 按句末符号/换行做粗切分，并保留分隔符
    parts = re.split(r"([。！？!?；;\n]+)", t)
    units = []
    i = 0
    while i < len(parts):
        body = parts[i] if i < len(parts) else ""
        delim = parts[i + 1] if i + 1 < len(parts) else ""
        i += 2
        unit = (body or "") + (delim or "")
        if unit.strip():
            units.append(unit)

    if len(units) <= 1:
        return t

    merged = []
    for unit in units:
        if not merged:
            merged.append(unit)
            continue
        if _count_speak_chars(unit) < min_chars:
            prev = merged.pop()
            prev = re.sub(r"[。！？!?；;\n]+$", "，", prev.rstrip())
            merged.append((prev + unit.lstrip()).strip())
        else:
            merged.append(unit)

    # 首句过短时，和下一句再做一次合并
    if len(merged) >= 2 and _count_speak_chars(merged[0]) < min_chars:
        first = re.sub(r"[。！？!?；;\n]+$", "，", merged[0].rstrip())
        merged = [(first + merged[1].lstrip()).strip()] + merged[2:]

    out = "".join(merged).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out or t


def _wav_duration_seconds(wav_bytes: bytes) -> float:
    """
    返回 wav 时长（秒）；失败返回 -1。
    """
    if not wav_bytes:
        return -1.0
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if not rate:
                return -1.0
            return float(frames) / float(rate)
    except Exception:
        return -1.0


def _wav_levels(wav_bytes: bytes) -> Tuple[float, int]:
    """
    返回 (rms, max_abs)。失败返回 (-1, -1)。
    """
    if (not wav_bytes) or (audioop is None):
        return (-1.0, -1)
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())
        if not frames:
            return (0.0, 0)
        rms = float(audioop.rms(frames, sw))
        mx = int(audioop.max(frames, sw))
        return (rms, mx)
    except Exception:
        return (-1.0, -1)


def _boost_quiet_wav(wav_bytes: bytes, min_rms: float = 120.0, target_peak: int = 12000) -> bytes:
    """
    对过小音量的 16-bit PCM wav 做增益放大，避免“有文件但几乎听不到”。
    """
    if (not wav_bytes) or (audioop is None):
        return wav_bytes
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            params = wf.getparams()
            sw = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if (not frames) or sw != 2:
            return wav_bytes

        rms = float(audioop.rms(frames, sw))
        mx = int(audioop.max(frames, sw))
        if mx <= 0 or rms < 0:
            return wav_bytes
        if rms >= float(min_rms):
            return wav_bytes

        gain = float(target_peak) / float(mx)
        # 防止异常放大
        gain = max(1.0, min(gain, 2000.0))
        boosted = audioop.mul(frames, sw, gain)

        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as wf2:
            wf2.setparams(params)
            wf2.writeframes(boosted)
        print(f"[multimodal_tools] quiet wav boosted: rms={rms:.1f} max={mx} gain={gain:.1f}")
        return out_buf.getvalue()
    except Exception as e:
        print(f"[multimodal_tools] quiet wav boost failed: {e}")
        return wav_bytes


def tts_speak(text: str, voice_id: str = "default") -> Dict[str, Any]:
    """
    调用本机 GPT-SoVITS(api_v2) 把文字合成为语音文件。

    :param text: 要朗读的文本（必填，非空）
    :param voice_id: 使用的声线预设，默认 "default"
    :return:
      {
        "ok": True/False,
        "msg": "错误信息或空",
        "rel_path": "tts/xxx.wav",
        "voice_id": "xxx"
      }
    """
    out: Dict[str, Any] = {"ok": False, "msg": "", "rel_path": "", "voice_id": str(voice_id or "default")}

    if requests is None:
        out["msg"] = "requests not available"
        print("[multimodal_tools] TTS failed: requests not available")
        return out

    raw_text = str(text or "")
    text_clean = _normalize_tts_input_text(raw_text)
    if not text_clean:
        out["msg"] = "text is empty"
        return out
    if raw_text.strip() != text_clean:
        print(f"[multimodal_tools] TTS text normalized: '{raw_text.strip()}' -> '{text_clean}'")

    try:
        min_segment_chars = max(1, int(os.getenv("SOVITS_MIN_SEGMENT_CHARS", "8")))
    except Exception:
        min_segment_chars = 8

    text_for_tts = _merge_short_segments(text_clean, min_segment_chars=min_segment_chars)
    if text_for_tts != text_clean:
        print(f"[multimodal_tools] merge short segments ({min_segment_chars}): '{text_clean}' -> '{text_for_tts}'")

    # 极短文本给一个句尾停顿，降低“有请求但几乎无声”的概率
    if _count_speak_chars(text_for_tts) <= 4 and not re.search(r"[。！？!?]$", text_for_tts):
        text_for_tts = text_for_tts + "。"

    requested_voice = str(voice_id or "default").strip() or "default"
    auto_voice_flag = str(os.getenv("SOVITS_AUTO_VOICE", "1")).strip().lower()
    auto_voice_enabled = auto_voice_flag not in {"0", "false", "off", "no"}
    selected_voice = requested_voice
    if auto_voice_enabled and requested_voice in {"default", "auto"}:
        inferred_voice = _infer_voice_id_from_text(text_for_tts)
        if inferred_voice:
            selected_voice = inferred_voice
            if selected_voice != requested_voice:
                print(
                    f"[multimodal_tools] auto voice infer: req={requested_voice} -> use={selected_voice}"
                )

    used_voice, preset = _choose_voice_preset(selected_voice)
    out["voice_id"] = used_voice

    tts_url = str(_TTS_CONFIG.get("tts_url") or _DEFAULT_SOVITS_TTS_URL).strip()
    allowed_dir = os.path.abspath(str(_TTS_CONFIG.get("allowed_dir") or _DEFAULT_ALLOWED_DIR))
    output_dir = os.path.abspath(str(_TTS_CONFIG.get("output_dir") or os.path.join(allowed_dir, "tts")))
    os.makedirs(output_dir, exist_ok=True)

    ref_audio_path = str(preset.get("ref_audio_path") or "").strip()
    if ref_audio_path and (not os.path.isabs(ref_audio_path)):
        ref_audio_path = os.path.abspath(ref_audio_path)

    prompt_text = str(preset.get("prompt_text") or "").strip()
    prompt_lang = str(preset.get("prompt_lang") or "zh").strip() or "zh"

    if (not ref_audio_path) or (not os.path.exists(ref_audio_path)):
        ref_dir_guess = os.path.dirname(ref_audio_path) if ref_audio_path else os.getenv("SOVITS_REF_AUDIO_DIR", _DEFAULT_SOVITS_REF_AUDIO_DIR)
        fallback_ref = _pick_ref_audio_in_dir(str(ref_dir_guess or ""), voice_id=used_voice, prompt_text=prompt_text)
        if fallback_ref:
            ref_audio_path = fallback_ref
            print(f"[multimodal_tools] voice_id={used_voice} ref audio missing, fallback -> {ref_audio_path}")
        else:
            out["msg"] = f"ref audio not found for voice_id={used_voice}"
            print(f"[multimodal_tools] TTS failed: {out['msg']}")
            return out

    if not prompt_text:
        prompt_text = "你好。"

    inferred_prompt = _infer_prompt_text_from_ref(ref_audio_path)
    # 参考音频有可读文本时，优先使用它作为 prompt_text，避免参考文本与音频不一致导致弱音/异常
    if inferred_prompt:
        prompt_text = inferred_prompt
    prompt_text = _sanitize_tts_prompt_text(prompt_text)

    split_method = str(_TTS_CONFIG.get("text_split_method") or "cut0").strip() or "cut0"

    req = {
        "text": text_for_tts,
        "text_lang": "zh",
        "ref_audio_path": ref_audio_path,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "text_split_method": split_method,
        "speed_factor": 1.0,
        "media_type": "wav",
        "streaming_mode": False,
    }
    print(
        f"[multimodal_tools] tts req voice={requested_voice} use={used_voice} split={split_method} "
        f"ref='{os.path.basename(ref_audio_path)}' prompt='{prompt_text[:40]}'"
    )

    try:
        resp = requests.post(tts_url, json=req, timeout=120)
    except Exception as e:
        out["msg"] = f"TTS request failed: {e}"
        print(f"[multimodal_tools] {out['msg']}")
        return out

    if resp.status_code != 200:
        err_msg = ""
        try:
            j = resp.json()
            if isinstance(j, dict):
                err_msg = str(j.get("message") or j.get("msg") or j.get("error") or "").strip()
            if not err_msg:
                err_msg = str(j)
        except Exception:
            err_msg = str((resp.text or "").strip())
        out["msg"] = f"TTS http {resp.status_code}: {err_msg[:500]}"
        print(f"[multimodal_tools] {out['msg']}")
        return out

    content = resp.content or b""
    if not content:
        out["msg"] = "TTS empty audio content"
        print(f"[multimodal_tools] {out['msg']}")
        return out

    speak_chars = _count_speak_chars(text_for_tts)
    try:
        min_wav_seconds = max(0.1, float(os.getenv("SOVITS_MIN_WAV_SECONDS", "0.45")))
    except Exception:
        min_wav_seconds = 0.45
    short_check_chars = max(3, min_segment_chars // 2)
    wav_seconds = _wav_duration_seconds(content)
    wav_rms, wav_max = _wav_levels(content)
    if wav_seconds >= 0:
        print(
            f"[multimodal_tools] wav_sec={wav_seconds:.3f} chars={speak_chars} "
            f"split={split_method} min_sec={min_wav_seconds} rms={wav_rms:.1f} max={wav_max}"
        )

    try:
        min_wav_rms = max(1.0, float(os.getenv("SOVITS_MIN_WAV_RMS", "120")))
    except Exception:
        min_wav_rms = 120.0

    too_short = (wav_seconds >= 0 and speak_chars >= short_check_chars and wav_seconds < min_wav_seconds)
    too_quiet = (wav_rms >= 0 and speak_chars >= short_check_chars and wav_rms < min_wav_rms)

    # 音频过短/过静自动重试一次：强制 cut0 + 更强短句合并 + 去掉句首噪声标点
    if too_short or too_quiet:
        retry_text = _merge_short_segments(text_for_tts, min_segment_chars=max(min_segment_chars, 10))
        retry_text = re.sub(r"^[，。！？、；：,.!?;:\s]+", "", retry_text).strip() or retry_text
        retry_req = dict(req)
        retry_req["text_split_method"] = "cut0"
        retry_req["text"] = retry_text
        if inferred_prompt:
            retry_req["prompt_text"] = inferred_prompt
        print(
            "[multimodal_tools] weak wav detected; retry once "
            f"(chars={speak_chars}, sec={wav_seconds:.3f}, rms={wav_rms:.1f}, text='{retry_text}')"
        )
        try:
            resp2 = requests.post(tts_url, json=retry_req, timeout=120)
            if resp2.status_code == 200 and (resp2.content or b""):
                dur2 = _wav_duration_seconds(resp2.content)
                rms2, mx2 = _wav_levels(resp2.content)
                pick_retry = False
                if wav_rms >= 0 and rms2 >= 0:
                    pick_retry = rms2 > (wav_rms + 10.0)
                if (not pick_retry) and (dur2 > wav_seconds):
                    pick_retry = True
                if pick_retry:
                    content = resp2.content
                    wav_seconds = dur2
                    wav_rms, wav_max = rms2, mx2
                    print(f"[multimodal_tools] retry accepted, wav_sec={wav_seconds:.3f} rms={wav_rms:.1f} max={wav_max}")
                else:
                    print(
                        "[multimodal_tools] retry not better, keep old "
                        f"(sec={wav_seconds:.3f}, rms={wav_rms:.1f}) new(sec={dur2:.3f}, rms={rms2:.1f})"
                    )
            else:
                print(f"[multimodal_tools] retry failed: http {resp2.status_code}")
        except Exception as e:
            print(f"[multimodal_tools] retry exception: {e}")

    # 最后兜底：若仍然过静，尝试做本地增益放大
    if wav_rms >= 0 and wav_rms < min_wav_rms:
        boosted = _boost_quiet_wav(content, min_rms=min_wav_rms, target_peak=12000)
        if boosted and boosted is not content:
            content = boosted
            wav_rms2, wav_max2 = _wav_levels(content)
            print(f"[multimodal_tools] post-boost levels rms={wav_rms2:.1f} max={wav_max2}")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    ms = int(time.time() * 1000) % 1000
    vname = _safe_voice_name(used_voice)
    filename = f"{ts}-{ms:03d}_{vname}.wav"
    abs_path = os.path.abspath(os.path.join(output_dir, filename))

    try:
        with open(abs_path, "wb") as f:
            f.write(content)
    except Exception as e:
        out["msg"] = f"save wav failed: {e}"
        print(f"[multimodal_tools] {out['msg']}")
        return out

    rel_path = ""
    try:
        rel_path = os.path.relpath(abs_path, allowed_dir).replace("\\", "/")
        if rel_path.startswith(".."):
            rel_path = f"tts/{filename}"
    except Exception:
        rel_path = f"tts/{filename}"

    out.update({"ok": True, "msg": "", "rel_path": rel_path, "voice_id": used_voice})
    return out


def asr_transcribe(audio_path: str) -> str:
    """
    输入：本地音频文件路径。
    输出：识别出的文本（预留）。
    当前阶段：不接真实 ASR，只返回固定提示字符串。
    """
    _ = audio_path
    print("[multimodal_tools] ASR requested but not implemented yet")
    return "ASR not implemented yet"


def img_generate(prompt: str) -> str:
    """
    输入：图像生成提示词。
    输出：生成图像的本地路径（预留）。
    当前阶段：不接文生图引擎，只返回固定提示字符串。
    """
    _ = prompt
    print("[multimodal_tools] image generation requested but not implemented yet")
    return "Image generation not implemented yet"


def img_analyze(image_path: str, task: str = "describe") -> str:
    """
    输入：图像路径 + 任务类型（默认 describe）。
    输出：对图像的文字描述或分析结果（预留）。
    当前阶段：可以直接调用 ocr_image 或返回固定提示。
    """
    print(f"[multimodal_tools] image analyze placeholder task={task}")
    txt = ocr_image(image_path)
    if txt and (not str(txt).startswith("❌")):
        return txt
    return "Image analyze not implemented yet"


__all__ = [
    "ocr_image",
    "ocr_status",
    "configure_tts",
    "tts_speak",
    "asr_transcribe",
    "img_generate",
    "img_analyze",
]
