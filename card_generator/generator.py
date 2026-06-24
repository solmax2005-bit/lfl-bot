import io
import os
from PIL import Image, ImageDraw, ImageFont
from scraper.models import PlayerProfile

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
W, H = 600, 360
HEADER_H = 130
FOOTER_H = 60
STATS_H = H - HEADER_H - FOOTER_H  # 170

COLOR_BLUE  = (0x1E, 0x5C, 0x9B)
COLOR_GREEN = (0x2E, 0x7D, 0x32)
COLOR_WHITE = (0xFF, 0xFF, 0xFF)
COLOR_LIGHT = (0xF8, 0xF9, 0xFB)
COLOR_DARK  = (0x1A, 0x1A, 0x2E)
COLOR_GREY  = (0x90, 0x9A, 0xAA)


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


def _draw_header(draw: ImageDraw.Draw, img: Image.Image, color, name: str, sub1: str, sub2: str, sub3: str = "") -> None:
    draw.rectangle([(0, 0), (W, HEADER_H)], fill=color)
    av_x, av_y, av_r = 65, 65, 45
    draw.ellipse([(av_x - av_r, av_y - av_r), (av_x + av_r, av_y + av_r)], fill=COLOR_WHITE)
    font_av = _load_font("Roboto-Bold.ttf", 28)
    initials = _initials(name)
    bbox = draw.textbbox((0, 0), initials, font=font_av)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((av_x - tw // 2, av_y - th // 2), initials, fill=color, font=font_av)

    font_name = _load_font("Roboto-Bold.ttf", 22)
    font_sub  = _load_font("Roboto-Regular.ttf", 14)
    tx = av_x + av_r + 16
    draw.text((tx, 18), name, fill=COLOR_WHITE, font=font_name)
    draw.text((tx, 46), sub1, fill=(0xCC, 0xDD, 0xFF), font=font_sub)
    draw.text((tx, 66), sub2, fill=COLOR_WHITE, font=font_sub)
    if sub3:
        draw.text((tx, 86), sub3, fill=(0xCC, 0xDD, 0xFF), font=font_sub)


def draw_card(profile: PlayerProfile) -> bytes:
    img = Image.new("RGB", (W, H), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    header_color = COLOR_GREEN if profile.is_free_agent else COLOR_BLUE
    age_str = f"{profile.age} лет" if profile.age else ""
    _draw_header(
        draw, img, header_color,
        profile.name, profile.position, profile.current_club,
        f"{profile.birthdate}  ({age_str})" if age_str else profile.birthdate,
    )

    stats_y = HEADER_H
    draw.rectangle([(0, stats_y), (W, stats_y + STATS_H)], fill=COLOR_WHITE)

    is_manual = not profile.lfl_url

    if is_manual:
        # Show experience text or dashes
        font_exp  = _load_font("Roboto-Regular.ttf", 14)
        font_lbl  = _load_font("Roboto-Regular.ttf", 12)
        exp_text  = profile.experience if profile.experience else "—  —  —  —"
        label     = "Прошлые команды" if profile.experience else "Нет опыта"
        bbox = draw.textbbox((0, 0), exp_text, font=font_exp)
        ew = bbox[2] - bbox[0]
        draw.text(((W - ew) // 2, stats_y + 50), exp_text, fill=COLOR_DARK, font=font_exp)
        bbox = draw.textbbox((0, 0), label, font=font_lbl)
        lw = bbox[2] - bbox[0]
        draw.text(((W - lw) // 2, stats_y + 80), label, fill=COLOR_GREY, font=font_lbl)
    else:
        stat_items = [
            ("Голы",     profile.goals),
            ("Матчи",    profile.matches),
            ("Передачи", profile.assists),
            ("Карточки", f"{profile.yellow_cards}Ж / {profile.red_cards}К"),
        ]
        block_w  = W // 4
        font_val = _load_font("Roboto-Bold.ttf", 36)
        font_lbl = _load_font("Roboto-Regular.ttf", 12)
        for i, (label, value) in enumerate(stat_items):
            bx = i * block_w + block_w // 2
            val_str = str(value)
            bbox = draw.textbbox((0, 0), val_str, font=font_val)
            vw = bbox[2] - bbox[0]
            draw.text((bx - vw // 2, stats_y + 30), val_str, fill=COLOR_DARK, font=font_val)
            bbox = draw.textbbox((0, 0), label, font=font_lbl)
            lw = bbox[2] - bbox[0]
            draw.text((bx - lw // 2, stats_y + 75), label, fill=COLOR_GREY, font=font_lbl)
            if i > 0:
                draw.line(
                    [(i * block_w, stats_y + 20), (i * block_w, stats_y + STATS_H - 20)],
                    fill=(0xE0, 0xE4, 0xEA), width=1,
                )

    footer_y = HEADER_H + STATS_H
    draw.rectangle([(0, footer_y), (W, H)], fill=COLOR_LIGHT)
    status = "🟢 Свободный агент" if profile.is_free_agent else f"🔵 {profile.current_club}"
    clubs_str = " · ".join(profile.career_clubs[:4])
    font_footer = _load_font("Roboto-Regular.ttf", 12)
    draw.text((16, footer_y + 8),  status,     fill=COLOR_DARK, font=font_footer)
    draw.text((16, footer_y + 24), clubs_str,  fill=COLOR_GREY, font=font_footer)
    if profile.debut_year:
        draw.text((16, footer_y + 40), f"В лиге с {profile.debut_year}", fill=COLOR_GREY, font=font_footer)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def draw_team_card(team: dict) -> bytes:
    img = Image.new("RGB", (W, H), COLOR_WHITE)
    draw = ImageDraw.Draw(img)

    # Header
    _draw_header(
        draw, img, COLOR_BLUE,
        team["name"], team["league"],
        team.get("division", "") or "",
    )

    # Middle (white zone)
    mid_y = HEADER_H
    draw.rectangle([(0, mid_y), (W, mid_y + STATS_H)], fill=COLOR_WHITE)

    font_body = _load_font("Roboto-Regular.ttf", 14)
    font_lbl  = _load_font("Roboto-Regular.ttf", 12)

    districts = team.get("districts", [])
    positions = team.get("positions", [])

    dist_str = ", ".join(districts) if districts else "—"
    pos_str  = ", ".join(positions) if positions else "—"

    draw.text((20, mid_y + 20), "Округ:", fill=COLOR_GREY, font=font_lbl)
    draw.text((20, mid_y + 38), dist_str, fill=COLOR_DARK, font=font_body)
    draw.text((20, mid_y + 68), "Ищем:", fill=COLOR_GREY, font=font_lbl)
    draw.text((20, mid_y + 86), pos_str, fill=COLOR_DARK, font=font_body)

    # Footer
    footer_y = HEADER_H + STATS_H
    draw.rectangle([(0, footer_y), (W, H)], fill=COLOR_LIGHT)
    font_footer = _load_font("Roboto-Regular.ttf", 12)
    comment = team.get("comment", "")
    contact = team.get("contact", "")
    draw.text((16, footer_y + 8),  comment or "—", fill=COLOR_DARK, font=font_footer)
    draw.text((16, footer_y + 28), contact,        fill=COLOR_GREY, font=font_footer)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
