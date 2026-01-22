import hashlib
import math
import random
from dataclasses import dataclass
from typing import Iterable, Optional

from PIL import Image
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


@dataclass
class PatchAssets:
    display_name: str
    filename: str
    qr_image: Image.Image
    album_image: Optional[Image.Image]
    artist: Optional[str] = None
    title: Optional[str] = None


def _draw_image_fit(
    c, image: Image.Image, x: float, y: float, w: float, h: float
) -> None:
    img_w, img_h = image.size
    if img_w == 0 or img_h == 0:
        return
    scale = min(w / img_w, h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    draw_x = x + (w - draw_w) / 2
    draw_y = y + (h - draw_h) / 2
    c.drawImage(ImageReader(image), draw_x, draw_y, draw_w, draw_h, mask="auto")


def _truncate_text(c, text: str, max_width: float) -> str:
    if not text:
        return ""
    if c.stringWidth(text) <= max_width:
        return text
    ellipsis = "..."
    if c.stringWidth(ellipsis) > max_width:
        return ""
    max_width -= c.stringWidth(ellipsis)
    trimmed = text
    while trimmed and c.stringWidth(trimmed) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed.rstrip() + ellipsis) if trimmed else ellipsis


def _wrap_text_lines(
    c, text: str, max_lines: int, max_widths: list[float]
) -> list[str]:
    words = text.split()
    if not words or max_lines <= 0:
        return []
    lines: list[str] = []
    current = ""
    line_index = 0
    word_index = 0
    truncated = False

    while word_index < len(words) and line_index < max_lines:
        width = max_widths[line_index] if line_index < len(max_widths) else 0.0
        if width <= 0:
            truncated = True
            break
        word = words[word_index]
        candidate = word if not current else f"{current} {word}"
        if c.stringWidth(candidate) <= width:
            current = candidate
            word_index += 1
            continue

        if current:
            lines.append(current)
            line_index += 1
            current = ""
            continue

        lines.append(_truncate_text(c, word, width))
        line_index += 1
        word_index += 1

    if line_index < max_lines and current:
        lines.append(current)
        line_index += 1

    if word_index < len(words):
        truncated = True

    if truncated and lines:
        last_index = min(len(lines), max_lines) - 1
        lines = lines[:max_lines]
        width = max_widths[last_index] if last_index < len(max_widths) else 0.0
        lines[last_index] = _truncate_text(c, f"{lines[last_index]}...", width)

    return lines[:max_lines]


def _line_positions(
    center_y: float, line_height: float, line_count: int
) -> list[float]:
    if line_count <= 0:
        return []
    start = center_y + (line_count - 1) * line_height / 2
    return [start - i * line_height for i in range(line_count)]


def _max_width_at_y(radius: float, y: float, padding: float) -> float:
    if abs(y) >= radius:
        return 0.0
    chord = 2 * math.sqrt(max(radius * radius - y * y, 0.0))
    return max(0.0, chord - 2 * padding)


def _seed_for_patch(patch: PatchAssets) -> int:
    seed_text = f"{patch.artist or ''}|{patch.title or patch.display_name}"
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _max_square_size_in_circle(radius: float, gap: float) -> float:
    if radius <= 0:
        return 0.0
    g = gap / 2
    disc = 5 * radius * radius - g * g
    if disc <= 0:
        return 0.0
    return max(0.0, (-2 * g + math.sqrt(disc)) / 2.5)


def _draw_pattern(
    c, center_x: float, center_y: float, radius: float, seed: int
) -> None:
    if radius <= 0:
        return
    rng = random.Random(seed)
    c.saveState()
    path = c.beginPath()
    path.circle(center_x, center_y, radius)
    c.clipPath(path, stroke=0, fill=0)

    c.setFillColorRGB(1, 1, 1)
    c.rect(
        center_x - radius, center_y - radius, 2 * radius, 2 * radius, fill=1, stroke=0
    )

    shape_count = 36
    for _ in range(shape_count):
        is_black = rng.random() < 0.55
        color = 0 if is_black else 1
        c.setFillColorRGB(color, color, color)
        c.setStrokeColorRGB(color, color, color)

        shape = rng.randint(0, 3)
        if shape == 0:
            w = rng.uniform(radius * 0.2, radius * 0.8)
            h = rng.uniform(radius * 0.2, radius * 0.8)
            x = center_x - radius + rng.random() * (2 * radius - w)
            y = center_y - radius + rng.random() * (2 * radius - h)
            c.rect(x, y, w, h, fill=1, stroke=0)
        elif shape == 1:
            r = rng.uniform(radius * 0.15, radius * 0.45)
            x = center_x - radius + rng.random() * (2 * radius)
            y = center_y - radius + rng.random() * (2 * radius)
            c.circle(x, y, r, fill=1, stroke=0)
        elif shape == 2:
            p = c.beginPath()
            for i in range(3):
                x = center_x - radius + rng.random() * (2 * radius)
                y = center_y - radius + rng.random() * (2 * radius)
                if i == 0:
                    p.moveTo(x, y)
                else:
                    p.lineTo(x, y)
            p.close()
            c.drawPath(p, fill=1, stroke=0)
        else:
            c.setLineWidth(rng.uniform(0.4, 1.2))
            x1 = center_x - radius + rng.random() * (2 * radius)
            y1 = center_y - radius + rng.random() * (2 * radius)
            x2 = center_x - radius + rng.random() * (2 * radius)
            y2 = center_y - radius + rng.random() * (2 * radius)
            c.line(x1, y1, x2, y2)

    c.restoreState()


def _draw_text_box(
    c,
    lines: list[str],
    center_x: float,
    center_y: float,
    line_height: float,
    box_pad: float,
    radius: float,
    circle_center_y: float,
) -> None:
    if not lines:
        return
    block_height = line_height * len(lines)
    box_height = block_height + 2 * box_pad
    if box_height <= 0:
        return
    top_y = center_y + box_height / 2
    bottom_y = center_y - box_height / 2
    max_w_top = _max_width_at_y(radius, top_y - circle_center_y, 0.0)
    max_w_bottom = _max_width_at_y(radius, bottom_y - circle_center_y, 0.0)
    max_allowed = min(max_w_top, max_w_bottom)
    if max_allowed <= 0:
        return
    max_line = max(c.stringWidth(line) for line in lines)
    box_width = min(max_line + 2 * box_pad, max_allowed)
    if box_width <= 0:
        return
    c.saveState()
    c.setFillColorRGB(1, 1, 1)
    c.rect(
        center_x - box_width / 2,
        center_y - box_height / 2,
        box_width,
        box_height,
        fill=1,
        stroke=0,
    )
    c.restoreState()


def render_patches_to_pdf(
    patches: Iterable[PatchAssets],
    output_path: str,
    patch_size_cm: float,
    qr_size_cm: float,
    page_width_mm: float,
    page_height_mm: float,
    layout_mode: str = "halfsize_cover",
) -> None:
    patch_size_mm = patch_size_cm * 10.0

    cols = int(page_width_mm // patch_size_mm)
    rows = int(page_height_mm // patch_size_mm)
    if cols <= 0 or rows <= 0:
        raise ValueError("Patch size too large for the page size")

    margin_x_mm = (page_width_mm - cols * patch_size_mm) / 2.0
    margin_y_mm = (page_height_mm - rows * patch_size_mm) / 2.0

    page_width_pt = page_width_mm * mm
    page_height_pt = page_height_mm * mm
    c = canvas.Canvas(output_path, pagesize=(page_width_pt, page_height_pt))

    patches = list(patches)
    per_page = cols * rows

    for index, patch in enumerate(patches):
        if index > 0 and index % per_page == 0:
            c.showPage()

        page_index = index % per_page
        row = page_index // cols
        col = page_index % cols

        patch_x_mm = margin_x_mm + col * patch_size_mm
        patch_y_mm = page_height_mm - margin_y_mm - (row + 1) * patch_size_mm

        patch_x = patch_x_mm * mm
        patch_y = patch_y_mm * mm
        patch_size = patch_size_mm * mm

        center_x = patch_x + patch_size / 2
        center_y = patch_y + patch_size / 2
        radius = patch_size / 2

        inner_pad = 1.0 * mm
        image_inset = 3.0 * mm
        safe_radius = max(0.0, radius - inner_pad)
        image_radius = max(0.0, safe_radius - image_inset)

        font_name = "Helvetica"
        font_size = 10
        line_height = font_size * 1.2
        max_lines = 2
        text_box_pad = 2.0 * mm
        artist = patch.artist or ""
        title = patch.title or patch.display_name

        # _draw_pattern(c, center_x, center_y, safe_radius, _seed_for_patch(patch))

        if layout_mode == "fullsize_cover":
            cover_size = min(6.5 * cm, 2 * safe_radius)
            cover_size = max(0.0, cover_size)
            cover_x = center_x - cover_size / 2
            cover_y = center_y - cover_size / 2
            if patch.album_image and cover_size > 0:
                c.saveState()
                clip = c.beginPath()
                clip.circle(center_x, center_y, safe_radius)
                c.clipPath(clip, stroke=0, fill=0)
                _draw_image_fit(
                    c, patch.album_image, cover_x, cover_y, cover_size, cover_size
                )
                c.restoreState()

            max_qr_size = image_radius * math.sqrt(2) * 0.9
            qr_size = min(qr_size_cm * 10.0 * mm, max_qr_size)
            qr_size = max(0.0, qr_size)
            if qr_size > 0:
                max_offset = (
                    math.sqrt(
                        max(image_radius * image_radius - (qr_size / 2) ** 2, 0.0)
                    )
                    - qr_size / 2
                )
                qr_center_x = center_x + max(0.0, max_offset)
                qr_x = qr_center_x - qr_size / 2
                qr_y = center_y - qr_size / 2
                _draw_image_fit(c, patch.qr_image, qr_x, qr_y, qr_size, qr_size)

            c.setFont(font_name, font_size)
            if artist:
                text_inset = 2.0 * mm
                text_band = max_lines * line_height
                top_center_y = center_y + image_radius - text_band / 2 - text_inset
                top_positions = _line_positions(top_center_y, line_height, max_lines)
                top_widths = [
                    _max_width_at_y(safe_radius, y - center_y, text_box_pad)
                    for y in top_positions
                ]
                top_lines = _wrap_text_lines(c, artist, max_lines, top_widths)
                if top_lines:
                    _draw_text_box(
                        c,
                        top_lines,
                        center_x,
                        top_center_y,
                        line_height,
                        text_box_pad,
                        safe_radius,
                        center_y,
                    )
                    top_positions = _line_positions(
                        top_center_y, line_height, len(top_lines)
                    )
                    c.setFillColorRGB(0, 0, 0)
                    for line, y in zip(top_lines, top_positions):
                        c.drawCentredString(center_x, y, line)

            if title:
                text_inset = 2.0 * mm
                text_band = max_lines * line_height
                bottom_center_y = center_y - image_radius + text_band / 2 + text_inset
                bottom_positions = _line_positions(
                    bottom_center_y, line_height, max_lines
                )
                bottom_widths = [
                    _max_width_at_y(safe_radius, y - center_y, text_box_pad)
                    for y in bottom_positions
                ]
                bottom_lines = _wrap_text_lines(c, title, max_lines, bottom_widths)
                if bottom_lines:
                    _draw_text_box(
                        c,
                        bottom_lines,
                        center_x,
                        bottom_center_y,
                        line_height,
                        text_box_pad,
                        safe_radius,
                        center_y,
                    )
                    bottom_positions = _line_positions(
                        bottom_center_y, line_height, len(bottom_lines)
                    )
                    c.setFillColorRGB(0, 0, 0)
                    for line, y in zip(bottom_lines, bottom_positions):
                        c.drawCentredString(center_x, y, line)
        else:
            text_band = max_lines * line_height
            gap = 1.5 * mm
            text_inset = 4.0 * mm
            content_height = max(0.0, 2 * image_radius - 2 * text_band - 2 * gap)
            content_height_inner = max(0.0, content_height - 2 * text_inset)

            g = gap / 2
            size_limit = (2 * image_radius - gap) / 2
            corner_limit = _max_square_size_in_circle(image_radius, gap)
            square_size = min(content_height_inner, size_limit, corner_limit)
            square_size = max(0.0, square_size)

            cover_x = center_x - g - square_size
            cover_y = center_y - square_size / 2
            qr_x = center_x + g
            qr_y = center_y - square_size / 2

            if patch.album_image and square_size > 0:
                _draw_image_fit(
                    c,
                    patch.album_image,
                    cover_x,
                    cover_y,
                    square_size,
                    square_size,
                )

            if square_size > 0:
                _draw_image_fit(
                    c,
                    patch.qr_image,
                    qr_x,
                    qr_y,
                    square_size,
                    square_size,
                )

            c.setFont(font_name, font_size)
            if artist:
                top_center_y = (
                    center_y + content_height / 2 + gap + text_band / 2 - text_inset
                )
                top_positions = _line_positions(top_center_y, line_height, max_lines)
                top_widths = [
                    _max_width_at_y(safe_radius, y - center_y, text_box_pad)
                    for y in top_positions
                ]
                top_lines = _wrap_text_lines(c, artist, max_lines, top_widths)
                if top_lines:
                    _draw_text_box(
                        c,
                        top_lines,
                        center_x,
                        top_center_y,
                        line_height,
                        text_box_pad,
                        safe_radius,
                        center_y,
                    )
                    top_positions = _line_positions(
                        top_center_y, line_height, len(top_lines)
                    )
                    c.setFillColorRGB(0, 0, 0)
                    for line, y in zip(top_lines, top_positions):
                        c.drawCentredString(center_x, y, line)

            if title:
                bottom_center_y = (
                    center_y - content_height / 2 - gap - text_band / 2 + text_inset
                )
                bottom_positions = _line_positions(
                    bottom_center_y, line_height, max_lines
                )
                bottom_widths = [
                    _max_width_at_y(safe_radius, y - center_y, text_box_pad)
                    for y in bottom_positions
                ]
                bottom_lines = _wrap_text_lines(c, title, max_lines, bottom_widths)
                if bottom_lines:
                    _draw_text_box(
                        c,
                        bottom_lines,
                        center_x,
                        bottom_center_y,
                        line_height,
                        text_box_pad,
                        safe_radius,
                        center_y,
                    )
                    bottom_positions = _line_positions(
                        bottom_center_y, line_height, len(bottom_lines)
                    )
                    c.setFillColorRGB(0, 0, 0)
                    for line, y in zip(bottom_lines, bottom_positions):
                        c.drawCentredString(center_x, y, line)

        c.saveState()
        c.setLineWidth(0.5)
        c.setDash(2, 2)
        c.setStrokeColorRGB(1, 1, 1)
        c.circle(center_x, center_y, radius, stroke=1, fill=0)
        c.restoreState()

    c.save()
