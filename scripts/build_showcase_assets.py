"""Build public README media from local private videos and processed frames."""

from __future__ import annotations

import argparse
from pathlib import Path

import imageio.v2 as imageio
from PIL import Image, ImageDraw, ImageFont


VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".dav"}
DOG_NAME_MAP = {
    "多比": "DuoBi",
    "大乖": "DaGuai",
    "皮特": "PiTe",
    "豆豆": "DouDou",
}


def resize_to_width(image: Image.Image, width: int) -> Image.Image:
    ratio = width / image.width
    height = max(1, int(image.height * ratio))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def load_font(size: int = 22) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont) -> None:
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=font)
    draw.rectangle((bbox[0] - 6, bbox[1] - 4, bbox[2] + 6, bbox[3] + 4), fill=(255, 255, 255))
    draw.text((x, y), text, fill=(20, 28, 38), font=font)


def read_video_frame(video_path: Path, second: float | None = None) -> Image.Image:
    reader = imageio.get_reader(str(video_path))
    try:
        meta = reader.get_meta_data()
        fps = float(meta.get("fps", 25.0))
        duration = float(meta.get("duration", 0) or 0)
        target_second = second if second is not None else max(duration * 0.35, 1.0)
        index = int(max(0, target_second) * fps)
        frame = reader.get_data(index)
        return Image.fromarray(frame).convert("RGB")
    finally:
        reader.close()


def score_dog_visibility(image: Image.Image) -> float:
    small = image.resize((160, 90), Image.Resampling.BILINEAR).convert("RGB")
    pixels = list(small.getdata())
    dark = 0
    contrast = 0
    for red, green, blue in pixels:
        luminance = 0.299 * red + 0.587 * green + 0.114 * blue
        if luminance < 85:
            dark += 1
        contrast += abs(red - green) + abs(green - blue) + abs(blue - red)
    return dark + contrast / 255.0


def best_public_frame(video_path: Path) -> Image.Image:
    reader = imageio.get_reader(str(video_path))
    try:
        meta = reader.get_meta_data()
        fps = float(meta.get("fps", 25.0))
        duration = float(meta.get("duration", 20) or 20)
        seconds = [max(0.5, duration * ratio) for ratio in (0.15, 0.3, 0.45, 0.6, 0.75)]
        best_score = -1.0
        best_image: Image.Image | None = None
        for second in seconds:
            try:
                frame = Image.fromarray(reader.get_data(int(second * fps))).convert("RGB")
            except Exception:
                continue
            score = score_dog_visibility(frame)
            if score > best_score:
                best_score = score
                best_image = frame
        if best_image is None:
            raise RuntimeError(f"No readable frames in {video_path}")
        return best_image
    finally:
        reader.close()


def make_gif(
    video_path: Path,
    output_path: Path,
    *,
    width: int,
    fps: float,
    start_second: float = 0,
    duration: float | None = None,
) -> None:
    reader = imageio.get_reader(str(video_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []

    try:
        meta = reader.get_meta_data()
        source_fps = float(meta.get("fps", 25.0))
        source_duration = float(meta.get("duration", 0) or 0)
        if duration is None:
            duration = max(0, source_duration - start_second)

        step = 1.0 / fps
        count = int(duration * fps)
        for item in range(count):
            second = start_second + item * step
            index = int(second * source_fps)
            frame = Image.fromarray(reader.get_data(index)).convert("RGB")
            frame = resize_to_width(frame, width)
            frames.append(frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=128))
    finally:
        reader.close()

    if not frames:
        raise RuntimeError(f"No frames were extracted from {video_path}")

    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        optimize=True,
        duration=int(1000 / fps),
        loop=0,
    )


def make_demo_contact_sheet(video_path: Path, output_path: Path) -> None:
    times = [0, 45, 90, 135, 180, 225, 270, 315, 360, 405, 450, 500]
    thumbs = []
    for second in times:
        image = read_video_frame(video_path, second).resize((320, 180), Image.Resampling.LANCZOS)
        thumbs.append((second, image))

    font = load_font(18)
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * 320, rows * 216), "white")
    draw = ImageDraw.Draw(canvas)
    for idx, (second, image) in enumerate(thumbs):
        x = (idx % cols) * 320
        y = (idx // cols) * 216
        canvas.paste(image, (x, y + 28))
        draw_label(draw, (x + 8, y + 5), f"{int(second // 60):02d}:{int(second % 60):02d}", font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=88)


def best_video_frame_per_class(root: Path) -> list[tuple[str, Image.Image]]:
    selected: list[tuple[str, Image.Image]] = []
    for class_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        files = sorted(path for path in class_dir.rglob("*") if path.suffix.lower() in VIDEO_EXTENSIONS)
        mp4_files = [path for path in files if path.suffix.lower() == ".mp4"]
        candidates = (mp4_files or files)[:10]
        best_score = -1.0
        best_image = None
        for candidate in candidates:
            try:
                image = best_public_frame(candidate)
            except Exception:
                continue
            score = score_dog_visibility(image)
            if score > best_score:
                best_score = score
                best_image = image
        if best_image is not None:
            selected.append((class_dir.name, best_image))
    return selected


def make_original_gallery(video_root: Path, output_path: Path) -> None:
    items = best_video_frame_per_class(video_root)
    if not items:
        raise RuntimeError(f"No source videos found in {video_root}")

    font = load_font(22)
    tile_w, tile_h = 360, 230
    canvas = Image.new("RGB", (tile_w * len(items), tile_h), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(items):
        image = image.resize((tile_w, 203), Image.Resampling.LANCZOS)
        x = index * tile_w
        canvas.paste(image, (x, 27))
        draw_label(draw, (x + 10, 5), f"Raw class {label}", font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=90)


def best_frame_for_dog(dog_dir: Path) -> Path:
    files = sorted(dog_dir.rglob("*.png"), key=lambda path: path.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError(f"No processed frames found in {dog_dir}")
    return files[0]


def make_processed_gallery(processed_root: Path, output_path: Path) -> None:
    dog_dirs = sorted(path for path in processed_root.iterdir() if path.is_dir())
    if not dog_dirs:
        raise RuntimeError(f"No processed dog folders found in {processed_root}")

    font = load_font(22)
    tile_w, tile_h = 360, 250
    canvas = Image.new("RGB", (tile_w * len(dog_dirs), tile_h), "white")
    draw = ImageDraw.Draw(canvas)
    for index, dog_dir in enumerate(dog_dirs):
        frame_path = best_frame_for_dog(dog_dir)
        image = Image.open(frame_path).convert("RGB").resize((tile_w, 223), Image.Resampling.LANCZOS)
        x = index * tile_w
        canvas.paste(image, (x, 27))
        draw_label(draw, (x + 10, 5), DOG_NAME_MAP.get(dog_dir.name, dog_dir.name), font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=90)


def make_keypoint_sheet(video_path: Path, output_path: Path) -> None:
    keypoints = [
        ("Upload", 405),
        ("Select video", 435),
        ("Processing", 450),
        ("Result view", 500),
    ]
    font = load_font(24)
    tile_w, tile_h = 420, 270
    canvas = Image.new("RGB", (tile_w * 2, tile_h * 2), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (label, second) in enumerate(keypoints):
        image = read_video_frame(video_path, second).resize((tile_w, 235), Image.Resampling.LANCZOS)
        x = (index % 2) * tile_w
        y = (index // 2) * tile_h
        canvas.paste(image, (x, y + 35))
        draw_label(draw, (x + 10, y + 8), label, font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=90)


def make_architecture_png(output_path: Path) -> None:
    labels = [
        "Upload / RTSP",
        "Frame sampling",
        "YOLOv8 detection",
        "SAM mask",
        "Illumination module",
        "OSNet-AIN ReID",
        "Weighted voting",
        "Identity result",
    ]
    font = load_font(22)
    small = load_font(18)
    width, height = 1500, 360
    canvas = Image.new("RGB", (width, height), (247, 249, 252))
    draw = ImageDraw.Draw(canvas)
    box_w, box_h = 150, 78
    y = 145
    gap = 32
    x = 30
    colors = [(224, 239, 255), (232, 244, 234), (255, 242, 224), (246, 232, 255)]
    for index, label in enumerate(labels):
        fill = colors[index % len(colors)]
        draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=14, fill=fill, outline=(70, 91, 120), width=2)
        bbox = draw.textbbox((0, 0), label, font=small)
        draw.text((x + (box_w - (bbox[2] - bbox[0])) / 2, y + 27), label, fill=(20, 28, 38), font=small)
        if index < len(labels) - 1:
            ax = x + box_w + 6
            ay = y + box_h // 2
            draw.line((ax, ay, ax + gap - 12, ay), fill=(70, 91, 120), width=3)
            draw.polygon([(ax + gap - 12, ay - 6), (ax + gap - 12, ay + 6), (ax + gap, ay)], fill=(70, 91, 120))
        x += box_w + gap

    title = "Dog ReID Pipeline: Detection, Segmentation, Illumination Robustness, and Voting"
    draw.text((30, 45), title, fill=(20, 28, 38), font=font)
    draw.text((30, 85), "Large model weights, video data, and feature galleries stay local.", fill=(92, 107, 125), font=small)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build public media assets for README.")
    parser.add_argument("--demo-video", type=Path, required=True)
    parser.add_argument("--dog-video-root", type=Path, required=True)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/figures"))
    args = parser.parse_args()

    make_gif(args.demo_video, args.out / "demo_preview.gif", width=640, fps=3, start_second=405, duration=95)
    make_gif(args.demo_video, args.out / "demo_full.gif", width=480, fps=1, start_second=0, duration=None)
    make_demo_contact_sheet(args.demo_video, args.out / "demo_full_timeline.png")
    make_original_gallery(args.dog_video_root, args.out / "source_dog_gallery.png")
    make_processed_gallery(args.processed_root, args.out / "processed_key_frames.png")
    make_keypoint_sheet(args.demo_video, args.out / "recognition_keypoints.png")
    make_architecture_png(args.out / "system_architecture.png")


if __name__ == "__main__":
    main()
