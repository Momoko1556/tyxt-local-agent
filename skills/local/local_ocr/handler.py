import traceback
from typing import Any, Dict

import multimodal_tools


def run(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Local OCR skill entry.

    params:
      - image_path: str, required
    context:
      - TYXT runtime context (not strictly required by this skill)
    """
    del context
    image_path = (params or {}).get("image_path")
    if not image_path:
        return {
            "ok": False,
            "data": None,
            "error": "image_path is required",
        }

    try:
        text = multimodal_tools.ocr_image(str(image_path))
        text_s = str(text or "")
        if text_s.strip().startswith("❌"):
            return {
                "ok": False,
                "data": None,
                "error": text_s.strip(),
            }
        return {
            "ok": True,
            "data": {
                "text": text_s,
                "image_path": str(image_path),
            },
            "error": "",
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "ok": False,
            "data": None,
            "error": f"OCR failed: {e}",
        }
