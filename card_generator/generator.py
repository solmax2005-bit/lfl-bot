import io
import os
from PIL import Image, ImageDraw, ImageFont
from scraper.models import PlayerProfile

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
W, H        = 600, 390
HEADER_H    = 155
STATS_H     = 140
FOOTER_H    = H - HEADER_H - STATS_H   # 95

C_BG         = (0x0F, 0x19, 0x23)
C_HEADER_TOP = (0x1A, 0x32, 0x52)
C_STATS_BG   = (0x13, 0x1F, 0x2D)
C_FOOTER_BG  = (0x09, 0x12, 0x1C)
C_WHITE      = (0xFF, 0xFF, 0xFF)
C_MUTED      = (0xA8, 0xBE, 0xD4)   # lighter — readable on dark bg
C_SOFT       = (0xCC, 0xDD, 0xEE)   # near-white for secondary info
C_DIV        = (0x26, 0x3A, 0x50)
C_BLUE_ACC   = (0x29, 0x9D, 0xFF)
C_GOLD_ACC   = (0xFF, 0xC1, 0x07)
C_GREEN_ACC  = (0x4C, 0xAF, 0x50)
C_AV_BG      = (0x1A, 0x2E, 0x44)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = os.path.join(ASSETS, name)
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    for fb in [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(fb):
            return ImageFont.truetype(fb, size)
    return ImageFont.load_default()


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p and p[0].isalpha()]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def _gradient(draw: ImageDraw.Draw, x0, y0, x1, y1, c1, c2) -> None:
    steps = y1 - y0
    for i in range(steps):
        t = i / max(steps - 1, 1)
        color = tuple(int(c1[j] + (c2[j] - c1[j]) * t) for j in range(3))
        draw.line([(x0, y0 + i), (x1, y0 + i)], fill=color)


def _cx_text(draw: ImageDraw.Draw, cx: int, cy: int, text: str,
             font: ImageFont.FreeTypeFont, fill: tuple) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w // 2, cy - h // 2), text, font=font, fill=fill)


def _clip_text(draw: ImageDraw.Draw, text: str,
               font: ImageFont.FreeTypeFont, max_w: int) -> str:
    bbox = draw.textbbox((0, 0), text, font=font)
    if bbox[2] - bbox[0] <= max_w:
        return text
    while len(text) > 1:
        text = text[:-1]
        bbox = draw.textbbox((0, 0), text + "…", font=font)
        if bbox[2] - bbox[0] <= max_w:
            return text + "…"
    return text


def _draw_person_silhouette(draw: ImageDraw.Draw, cx: int, cy: int, color: tuple) -> None:
    """Draw a simple person icon (head + shoulders) centered at (cx, cy)."""
    # Head
    hr = 12
    draw.ellipse([(cx - hr, cy - 26), (cx + hr, cy - 2)], fill=color)
    # Shoulders — upper half of a wide ellipse
    sw, sh = 22, 14
    draw.pieslice([(cx - sw, cy + 4), (cx + sw, cy + 4 + sh * 2)], 180, 360, fill=color)


def _draw_player_header(draw: ImageDraw.Draw, profile: PlayerProfile,
                        accent: tuple) -> None:
    _gradient(draw, 0, 0, W, HEADER_H, C_HEADER_TOP, C_BG)

    # Corner accent triangle
    tri = [(W - 160, 0), (W, 0), (W, 100)]
    shade = tuple(min(255, int(accent[j] * 0.12 + C_HEADER_TOP[j] * 0.88)) for j in range(3))
    draw.polygon(tri, fill=shade)

    # Avatar
    ax, ay, ar = 76, 77, 50
    draw.ellipse([(ax - ar - 4, ay - ar - 4), (ax + ar + 4, ay + ar + 4)], fill=accent)
    draw.ellipse([(ax - ar - 1, ay - ar - 1), (ax + ar + 1, ay + ar + 1)], fill=C_STATS_BG)
    draw.ellipse([(ax - ar, ay - ar), (ax + ar, ay + ar)], fill=C_AV_BG)
    _draw_person_silhouette(draw, ax, ay, accent)

    # Text
    tx = ax + ar + 18
    avail = W - tx - 20
    fn  = _font("Roboto-Bold.ttf",    24)
    fb  = _font("Roboto-Bold.ttf",    14)
    fs  = _font("Roboto-Regular.ttf", 15)
    fsm = _font("Roboto-Regular.ttf", 13)

    name = _clip_text(draw, profile.name, fn, avail)
    draw.text((tx, 16), name, fill=C_WHITE, font=fn)

    # Position badge
    pos = profile.position or "—"
    bbox = draw.textbbox((0, 0), pos, font=fb)
    pw, ph = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 7
    draw.rounded_rectangle(
        [(tx - pad, 52 - pad // 2), (tx + pw + pad, 52 + ph + pad)],
        radius=4, fill=accent,
    )
    draw.text((tx, 52), pos, fill=C_BG, font=fb)

    draw.text((tx, 80), profile.current_club or "—", fill=C_SOFT, font=fs)
    bd = profile.birthdate or "—"
    age = f"  ({profile.age} лет)" if profile.age else ""
    draw.text((tx, 102), bd + age, fill=C_MUTED, font=fsm)

    # Bottom accent line
    draw.rectangle([(0, HEADER_H - 2), (W, HEADER_H)], fill=accent)


def _draw_stats(draw: ImageDraw.Draw, profile: PlayerProfile, sy: int) -> None:
    draw.rectangle([(0, sy), (W, sy + STATS_H)], fill=C_STATS_BG)
    font_val = _font("Roboto-Bold.ttf", 44)
    font_val_sm = _font("Roboto-Bold.ttf", 28)
    font_lbl = _font("Roboto-Bold.ttf", 12)
    col_w = W // 4

    cards_str = f"{profile.yellow_cards}Ж/{profile.red_cards}К"
    items = [
        ("ГОЛЫ",     str(profile.goals),   font_val),
        ("МАТЧИ",    str(profile.matches),  font_val),
        ("ПЕРЕДАЧИ", str(profile.assists),  font_val),
        ("КАРТОЧКИ", cards_str,             font_val_sm),
    ]
    for i, (label, value, vfont) in enumerate(items):
        cx = i * col_w + col_w // 2
        _cx_text(draw, cx, sy + 56, value, vfont, C_WHITE)
        _cx_text(draw, cx, sy + 112, label, font_lbl, C_MUTED)
        if i > 0:
            draw.line([(i * col_w, sy + 22), (i * col_w, sy + STATS_H - 22)],
                      fill=C_DIV, width=1)


def _draw_manual_stats(draw: ImageDraw.Draw, profile: PlayerProfile, sy: int) -> None:
    draw.rectangle([(0, sy), (W, sy + STATS_H)], fill=C_STATS_BG)
    font_val = _font("Roboto-Bold.ttf", 18)
    font_lbl = _font("Roboto-Regular.ttf", 12)
    exp = profile.experience or "Нет данных об опыте"
    _cx_text(draw, W // 2, sy + STATS_H // 2 - 10, exp, font_val, C_WHITE)
    _cx_text(draw, W // 2, sy + STATS_H // 2 + 18, "ОПЫТ", font_lbl, C_MUTED)


def _draw_footer(draw: ImageDraw.Draw, profile: PlayerProfile,
                 fy: int, accent: tuple) -> None:
    draw.rectangle([(0, fy), (W, H)], fill=C_FOOTER_BG)
    fb = _font("Roboto-Bold.ttf", 13)
    fr = _font("Roboto-Regular.ttf", 12)

    badge_color = C_GREEN_ACC if profile.is_free_agent else accent
    badge_txt = "● СВОБОДНЫЙ АГЕНТ" if profile.is_free_agent else f"● {profile.current_club.upper()}"
    if getattr(profile, "looking", False):
        badge_txt += "   🔍 ИЩЕТ КОМАНДУ"
    draw.text((16, fy + 12), badge_txt, fill=badge_color, font=fb)

    clubs = " · ".join(profile.career_clubs[:6])
    if clubs:
        draw.text((16, fy + 34), clubs, fill=C_SOFT, font=fr)

    if profile.debut_year:
        debut = f"В лиге с {profile.debut_year}"
        bbox = draw.textbbox((0, 0), debut, font=fr)
        draw.text((W - (bbox[2] - bbox[0]) - 16, fy + 12), debut, fill=C_SOFT, font=fr)

    if profile.lfl_url:
        src_txt = "lfl.ru"
        bbox = draw.textbbox((0, 0), src_txt, font=fr)
        draw.text((W - (bbox[2] - bbox[0]) - 16, fy + 34), src_txt, fill=C_MUTED, font=fr)


def draw_card(profile: PlayerProfile) -> bytes:
    img = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)
    accent = C_GOLD_ACC if profile.is_free_agent else C_BLUE_ACC

    _draw_player_header(draw, profile, accent)

    sy = HEADER_H
    if profile.lfl_url:
        _draw_stats(draw, profile, sy)
    else:
        _draw_manual_stats(draw, profile, sy)

    _draw_footer(draw, profile, HEADER_H + STATS_H, accent)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def draw_team_card(team: dict) -> bytes:
    img = Image.new("RGB", (W, H), C_BG)
    draw = ImageDraw.Draw(img)
    accent = C_BLUE_ACC

    _gradient(draw, 0, 0, W, HEADER_H, C_HEADER_TOP, C_BG)
    draw.rectangle([(0, HEADER_H - 2), (W, HEADER_H)], fill=accent)

    # Team avatar
    ax, ay, ar = 76, 77, 50
    draw.ellipse([(ax-ar-4, ay-ar-4), (ax+ar+4, ay+ar+4)], fill=accent)
    draw.ellipse([(ax-ar-1, ay-ar-1), (ax+ar+1, ay+ar+1)], fill=C_STATS_BG)
    draw.ellipse([(ax-ar, ay-ar), (ax+ar, ay+ar)], fill=C_AV_BG)
    _draw_person_silhouette(draw, ax, ay, accent)

    tx = ax + ar + 18
    fn = _font("Roboto-Bold.ttf", 24)
    fs = _font("Roboto-Regular.ttf", 13)
    fb_sm = _font("Roboto-Bold.ttf", 13)
    nm = team.get("name", "—")

    name = _clip_text(draw, nm, fn, W - tx - 20)
    draw.text((tx, 18), name, fill=C_WHITE, font=fn)

    league = team.get("league", "")
    if league:
        bbox = draw.textbbox((0, 0), league, font=fb_sm)
        pw, ph = bbox[2]-bbox[0], bbox[3]-bbox[1]
        pad = 7
        draw.rounded_rectangle([(tx-pad, 54-pad//2), (tx+pw+pad, 54+ph+pad)], radius=4, fill=accent)
        draw.text((tx, 54), league, fill=C_BG, font=fb_sm)

    div = team.get("division", "")
    if div:
        draw.text((tx, 80), div, fill=C_WHITE, font=fs)

    # Stats area
    sy = HEADER_H
    draw.rectangle([(0, sy), (W, sy + STATS_H)], fill=C_STATS_BG)
    font_lbl = _font("Roboto-Regular.ttf", 12)
    font_body = _font("Roboto-Regular.ttf", 14)

    districts = ", ".join(team.get("districts", [])) or "—"
    positions = ", ".join(team.get("positions", [])) or "—"

    draw.text((20, sy + 18), "ОКРУГ", fill=C_MUTED, font=font_lbl)
    draw.text((20, sy + 36), districts, fill=C_WHITE, font=font_body)
    draw.text((20, sy + 72), "ИЩЕМ ПОЗИЦИИ", fill=C_MUTED, font=font_lbl)
    draw.text((20, sy + 90), positions, fill=C_WHITE, font=font_body)

    # Footer
    fy = HEADER_H + STATS_H
    draw.rectangle([(0, fy), (W, H)], fill=C_FOOTER_BG)
    fr = _font("Roboto-Regular.ttf", 11)
    fb2 = _font("Roboto-Bold.ttf", 12)
    comment = team.get("comment", "")
    contact = team.get("contact", "")
    draw.text((16, fy + 12), comment or "—", fill=C_WHITE, font=fb2)
    if contact:
        draw.text((16, fy + 34), contact, fill=C_MUTED, font=fr)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
