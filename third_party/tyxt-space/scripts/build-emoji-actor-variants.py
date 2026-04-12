#!/usr/bin/env python3

import json
import math
import shutil
from pathlib import Path

from PIL import Image, ImageSequence


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "dist/assets/generated/actors"
TARGET_ROOT = ROOT / "public/assets/generated/actors"
FRAME_CANVAS = (128, 128)

VARIANTS = [
    {
        "id": "capy-claw-emoji",
        "label": "Capy-Claw",
        "source_dir": "capy-claw",
        "target_dir": "capy-claw-emoji-v2",
        "actions": {
            "work": "emoji_01_work.gif",
            "read": "emoji_02_read.gif",
            "idea": "emoji_03_idea.gif",
            "repair": "emoji_03_repair.gif",
            "error": "emoji_04_error.gif",
            "sleep": "emoji_05_sleep.gif",
            "coffee": "emoji_06_coffee.gif",
            "rest": "emoji_08_rest.gif",
            "walk": "emoji_11_walk.gif",
            "stand_front": "emoji_12_stand_front.gif",
            "stand_back": "emoji_13_stand_back.gif",
            "lie_flat": "emoji_14_lie_flat.gif",
        },
    },
    {
        "id": "cat-claw-emoji",
        "label": "Cat-Claw",
        "source_dir": "cat-claw",
        "target_dir": "cat-claw-emoji-v1",
        "actions": {
            "work": "emoji_01_work.gif",
            "front": "emoji_02_front.gif",
            "repair": "emoji_03_repair.gif",
            "idea": "emoji_04_idea.gif",
            "error": "emoji_05_error.gif",
            "sleep": "emoji_06_sleep.gif",
            "coffee": "emoji_07_coffee.gif",
            "game": "emoji_08_game.gif",
            "walk": "emoji_09_walk.gif",
            "stand_front": "emoji_10_stand_front.gif",
            "stand_back": "emoji_11_stand_back.gif",
            "lie_side": "emoji_12_lie_side.gif",
        },
    },
]


def remove_green_screen(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            if g >= 180 and r <= 90 and b <= 90:
                pixels[x, y] = (0, 0, 0, 0)
    return rgba


def normalize_frame(frame: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    normalized = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    offset_x = max(0, (canvas_size[0] - frame.width) // 2)
    offset_y = max(0, canvas_size[1] - frame.height)
    normalized.alpha_composite(frame, (offset_x, offset_y))
    return normalized


def load_frames(path: Path) -> tuple[list[Image.Image], int]:
    source = Image.open(path)
    frames = [normalize_frame(remove_green_screen(frame.copy()), FRAME_CANVAS) for frame in ImageSequence.Iterator(source)]
    durations = []
    for frame in ImageSequence.Iterator(source):
        durations.append(int(frame.info.get("duration", source.info.get("duration", 160))))
    avg_duration = max(1, round(sum(durations) / max(1, len(durations))))
    fps = max(1, round(1000 / avg_duration))
    return frames, fps


def build_sheet(frames: list[Image.Image], output_path: Path) -> dict[str, int]:
    frame_width, frame_height = frames[0].size
    cols = min(8, max(1, math.ceil(math.sqrt(len(frames)))))
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new("RGBA", (frame_width * cols, frame_height * rows), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        col = index % cols
        row = index // cols
        sheet.alpha_composite(frame, (col * frame_width, row * frame_height))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return {
        "frameWidth": frame_width,
        "frameHeight": frame_height,
        "frameCount": len(frames),
        "columns": cols,
        "rows": rows,
    }


def build_variant(variant: dict[str, object]) -> None:
    source_dir = SOURCE_ROOT / str(variant["source_dir"])
    target_dir = TARGET_ROOT / str(variant["target_dir"])
    source_target = target_dir / "source"
    sheet_target = target_dir / "sheets"

    if not source_dir.exists():
        raise FileNotFoundError(f"Missing actor gif source directory: {source_dir}")

    if target_dir.exists():
        shutil.rmtree(target_dir)

    source_target.mkdir(parents=True, exist_ok=True)
    sheet_target.mkdir(parents=True, exist_ok=True)

    manifests = []
    for action_id, file_name in dict(variant["actions"]).items():
        source_path = source_dir / file_name
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source gif: {source_path}")

        copied_gif = source_target / file_name
        shutil.copy2(source_path, copied_gif)

        frames, fps = load_frames(source_path)
        sheet_path = sheet_target / f"{action_id}-spritesheet.png"
        poster_path = sheet_target / f"{action_id}-poster.png"
        sheet_meta = build_sheet(frames, sheet_path)
        frames[0].save(poster_path)

        manifests.append({
            "id": action_id,
            "sourceGif": str(copied_gif.relative_to(ROOT)),
            "spritesheet": str(sheet_path.relative_to(ROOT)),
            "poster": str(poster_path.relative_to(ROOT)),
            "fps": fps,
            "sheet": sheet_meta,
        })

    (target_dir / "manifest.json").write_text(
        json.dumps(
            {
                "variant": variant["id"],
                "label": variant["label"],
                "frameCanvas": {"width": FRAME_CANVAS[0], "height": FRAME_CANVAS[1]},
                "actions": manifests,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    if not SOURCE_ROOT.exists():
        raise FileNotFoundError(f"Missing actor source root: {SOURCE_ROOT}")

    for variant in VARIANTS:
        build_variant(variant)


if __name__ == "__main__":
    main()
