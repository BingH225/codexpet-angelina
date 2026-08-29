from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parents[1]
GIF_DIR = ROOT / "安洁" / "GIF"
UI_DIR = ROOT / "安洁" / "UI素材"
OUTPUT_DIR = ROOT / "codex-pet" / "anjie"

CELL_WIDTH = 192
CELL_HEIGHT = 208
COLUMNS = 8
ROWS = 9
SHEET_WIDTH = CELL_WIDTH * COLUMNS
SHEET_HEIGHT = CELL_HEIGHT * ROWS
MAX_CONTENT_WIDTH = 182
MAX_CONTENT_HEIGHT = 198


@dataclass(frozen=True)
class RowSpec:
    state: str
    source: str
    frame_count: int
    flip: bool = False
    effect: str | None = None


ROW_SPECS = [
    RowSpec("idle", "坐坐.gif", 6),
    RowSpec("running-right", "送货.gif", 8, flip=True),
    RowSpec("running-left", "送货.gif", 8),
    RowSpec("waving", "海边.gif", 4),
    RowSpec("jumping", "纸飞机.gif", 5),
    RowSpec("failed", "坐坐.gif", 8, effect="failed"),
    RowSpec("waiting", "探险.gif", 6),
    RowSpec("running", "潜水.gif", 6),
    RowSpec("review", "看书.gif", 6),
]


def load_gif_frames(path: Path) -> list[Image.Image]:
    image = Image.open(path)
    frames: list[Image.Image] = []
    for index in range(getattr(image, "n_frames", 1)):
        image.seek(index)
        frames.append(image.convert("RGBA").copy())
    return frames


def sample_frames(frames: list[Image.Image], count: int) -> list[Image.Image]:
    if len(frames) == count:
        return [frame.copy() for frame in frames]
    if len(frames) > count:
        indexes = [round(index * (len(frames) - 1) / max(1, count - 1)) for index in range(count)]
        return [frames[index].copy() for index in indexes]

    ping_pong = list(range(len(frames)))
    if len(frames) > 2:
        ping_pong.extend(range(len(frames) - 2, 0, -1))
    return [frames[ping_pong[index % len(ping_pong)]].copy() for index in range(count)]


def union_alpha_box(frames: list[Image.Image]) -> tuple[int, int, int, int]:
    union = Image.new("L", frames[0].size, 0)
    for frame in frames:
        union = ImageChops.lighter(union, frame.getchannel("A"))
    box = union.getbbox()
    if box is None:
        raise ValueError("Animation contains no visible pixels")
    return box


def fit_row(frames: list[Image.Image], flip: bool) -> list[Image.Image]:
    if flip:
        frames = [ImageOps.mirror(frame) for frame in frames]
    box = union_alpha_box(frames)
    cropped = [frame.crop(box) for frame in frames]
    width, height = cropped[0].size
    scale = min(MAX_CONTENT_WIDTH / width, MAX_CONTENT_HEIGHT / height)
    output_size = (max(1, round(width * scale)), max(1, round(height * scale)))

    fitted: list[Image.Image] = []
    for frame in cropped:
        resized = frame.resize(output_size, Image.Resampling.LANCZOS)
        cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
        x = (CELL_WIDTH - resized.width) // 2
        y = CELL_HEIGHT - resized.height - 4
        cell.alpha_composite(resized, (x, y))
        fitted.append(cell)
    return fitted


def tint_failed(frame: Image.Image, frame_index: int, star: Image.Image) -> Image.Image:
    alpha = frame.getchannel("A")
    rgb = frame.convert("RGB")
    muted = ImageEnhance.Color(rgb).enhance(0.45)
    cool = Image.blend(muted, Image.new("RGB", muted.size, (127, 151, 190)), 0.14)
    processed = cool.convert("RGBA")
    processed.putalpha(alpha)

    shaken = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    x_offset = (-3, 2, -2, 3, -2, 2, -1, 1)[frame_index]
    shaken.alpha_composite(processed, (x_offset, 2))

    effect = star.resize((62, 62), Image.Resampling.LANCZOS)
    effect.putalpha(effect.getchannel("A").point(lambda value: round(value * 0.82)))
    effect_x = 12 + (frame_index % 3) * 3
    effect_y = 7 + (frame_index % 2) * 3
    shaken.alpha_composite(effect, (effect_x, effect_y))
    return shaken


def build_sheet() -> Image.Image:
    sheet = Image.new("RGBA", (SHEET_WIDTH, SHEET_HEIGHT), (0, 0, 0, 0))
    failure_star = Image.open(UI_DIR / "22.png").convert("RGBA")

    for row, spec in enumerate(ROW_SPECS):
        source_frames = load_gif_frames(GIF_DIR / spec.source)
        selected = sample_frames(source_frames, spec.frame_count)
        fitted = fit_row(selected, spec.flip)
        if spec.effect == "failed":
            fitted = [tint_failed(frame, index, failure_star) for index, frame in enumerate(fitted)]
        for column, frame in enumerate(fitted):
            sheet.alpha_composite(frame, (column * CELL_WIDTH, row * CELL_HEIGHT))
    return sheet


def create_preview(sheet: Image.Image) -> Image.Image:
    checker = Image.new("RGBA", sheet.size, (236, 234, 230, 255))
    tile = 24
    for y in range(0, sheet.height, tile):
        for x in range(0, sheet.width, tile):
            if (x // tile + y // tile) % 2:
                patch = Image.new("RGBA", (tile, tile), (210, 207, 204, 255))
                checker.alpha_composite(patch, (x, y))
    checker.alpha_composite(sheet)
    return checker.resize((768, 936), Image.Resampling.LANCZOS).convert("RGB")


def validate(sheet: Image.Image, output: Path) -> None:
    if sheet.size != (1536, 1872):
        raise ValueError(f"Unexpected spritesheet size: {sheet.size}")
    for row, spec in enumerate(ROW_SPECS):
        for column in range(spec.frame_count):
            frame = sheet.crop((
                column * CELL_WIDTH,
                row * CELL_HEIGHT,
                (column + 1) * CELL_WIDTH,
                (row + 1) * CELL_HEIGHT,
            ))
            if frame.getchannel("A").getbbox() is None:
                raise ValueError(f"Empty required frame at row={row} column={column}")
    if output.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Spritesheet exceeds the 20 MiB Codex limit")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet = build_sheet()
    output = OUTPUT_DIR / "spritesheet.webp"
    sheet.save(output, "WEBP", lossless=True, method=6)
    validate(sheet, output)
    create_preview(sheet).save(OUTPUT_DIR / "preview.png", optimize=True)
    print(f"Built {output} ({output.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
