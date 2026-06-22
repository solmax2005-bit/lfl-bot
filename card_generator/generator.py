import io
import os
from PIL import Image, ImageDraw, ImageFont
from scraper.models import PlayerProfile

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
W, H = 600, 360
HEADER_H = 130
FOOTER_H = 60
STATS_H = H - HEADER_H - FOOTER_H  # 170

COLOR_BLUE = (0x1E, 0x5C, 0x9B)
COLOR_GREEN = (0x2E, 0x7D, 0x32)
COLOR_WHITE = (0xFF, 0xFF, 0xFF)
COLOR_LIGHT = (0xF8, 0xF9, 0xFB)
COLOR_DARK = (0x1A, 0x1A, 0x2E)
COLOR_GREY = (0x90, 0x9A, 0xAA)


def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(ASSETS, filename)
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def draw_card(profile: PlayerProfile) -> bytes:
    img = Image.new("RGB", (W, H), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    # ── Header ──────────────────────────────────────────────────────────────
    header_color = COLOR_GREEN if profile.is_free_agent else COLOR_BLUE
    draw.rectangle([(0, 0), (W, HEADER_H)], fill=header_color)

    # Avatar circle
    av_x, av_y, av_r = 65, 65, 45
    draw.ellipse(
        [(av_x - av_r, av_y - av_r), (av_x + av_r, av_y + av_r)],
        fill=COLOR_WHITE,
    )
    font_av = _load_font("Roboto-Bold.ttf", 28)
    initials = _initials(profile.name)
    bbox = draw.textbbox((0, 0), initials, font=font_av)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((av_x - tw // 2, av_y - th // 2), initials, fill=header_color, font=font_av)

    # Name
    font_name = _load_font("Roboto-Bold.ttf", 22)
    font_sub = _load_font("Roboto-Regular.ttf", 14)
    text_x = av_x + av_r + 16
    draw.text((text_x, 18), profile.name, fill=COLOR_WHITE, font=font_name)
    draw.text((text_x, 46), profile.position, fill=(0xCC, 0xDD, 0xFF), font=font_sub)
    draw.text((text_x, 66), profile.current_club, fill=COLOR_WHITE, font=font_sub)
    draw.text((text_x, 86), f"{profile.birthdate}  ({profile.age} лет)", fill=(0xCC, 0xDD, 0xFF), font=font_sub)

    # ── Stats (white zone) ──────────────────────────────────────────────────
    stats_y = HEADER_H
    draw.rectangle([(0, stats_y), (W, stats_y + STATS_H)], fill=COLOR_WHITE)

    stat_items = [
        ("Голы", profile.goals),
        ("Матчи", profile.matches),
        ("Передачи", profile.assists),
        ("Карточки", f"{profile.yellow_cards}Ж / {profile.red_cards}К"),
    ]
    block_w = W // 4
    font_val = _load_font("Roboto-Bold.ttf", 36)
    font_lbl = _load_font("Roboto-Regular.ttf", 12)

    for i, (label, value) in enumerate(stat_items):
        bx = i * block_w + block_w // 2
        by_val = stats_y + 30
        by_lbl = stats_y + 75

        val_str = str(value)
        bbox = draw.textbbox((0, 0), val_str, font=font_val)
        vw = bbox[2] - bbox[0]
        draw.text((bx - vw // 2, by_val), val_str, fill=COLOR_DARK, font=font_val)

        bbox = draw.textbbox((0, 0), label, font=font_lbl)
        lw = bbox[2] - bbox[0]
        draw.text((bx - lw // 2, by_lbl), label, fill=COLOR_GREY, font=font_lbl)

        if i > 0:
            draw.line([(i * block_w, stats_y + 20), (i * block_w, stats_y + STATS_H - 20)],
                      fill=(0xE0, 0xE4, 0xEA), width=1)

    # ── Footer ──────────────────────────────────────────────────────────────
    footer_y = HEADER_H + STATS_H
    draw.rectangle([(0, footer_y), (W, H)], fill=COLOR_LIGHT)

    status = "🟢 Свободный агент" if profile.is_free_agent else f"🔵 {profile.current_club}"
    clubs_str = " · ".join(profile.career_clubs[:4])
    debut_str = f"В лиге с {profile.debut_year}"

    font_footer = _load_font("Roboto-Regular.ttf", 12)
    draw.text((16, footer_y + 8), status, fill=COLOR_DARK, font=font_footer)
    draw.text((16, footer_y + 24), clubs_str, fill=COLOR_GREY, font=font_footer)
    draw.text((16, footer_y + 40), debut_str, fill=COLOR_GREY, font=font_footer)

    # ── LFL watermark ───────────────────────────────────────────────────────
    font_wm = _load_font("Roboto-Regular.ttf", 11)
    wm = "ug.lfl.ru"
    bbox = draw.textbbox((0, 0), wm, font=font_wm)
    ww = bbox[2] - bbox[0]
    draw.text((W - ww - 12, footer_y + 8), wm, fill=COLOR_GREY, font=font_wm)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
