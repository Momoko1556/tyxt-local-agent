import traceback
from typing import Any, Dict

import multimodal_tools


def run(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Local GPT-SoVITS TTS skill entry.

    params:
      - text: str, required
      - voice_id: str, optional, defaults to "default"
    context:
      - TYXT runtime context (not strictly required by this skill)
    """
    del context
    text = (params or {}).get("text", "")
    voice_id = (params or {}).get("voice_id") or "default"

    if (not isinstance(text, str)) or (not text.strip()):
        return {
            "ok": False,
            "data": None,
            "error": "text is empty",
        }

    try:
        res = multimodal_tools.tts_speak(text.strip(), voice_id=str(voice_id))
        if not isinstance(res, dict):
            return {
                "ok": False,
                "data": None,
                "error": f"invalid tts_speak response type: {type(res)}",
            }

        ok = bool(res.get("ok", True))
        msg = str(res.get("msg", "") or "")
        return {
            "ok": ok,
            "data": res,
            "error": "" if ok else (msg or "tts_speak failed"),
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "ok": False,
            "data": None,
            "error": f"TTS failed: {e}",
        }

