import numpy as np
from PIL import Image, ImageOps
import pytesseract

RU = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
EN = "abcdefghijklmnopqrstuvwxyz"
BASE_W, BASE_H = 770, 915
BASE_BOX = (170, 450, 610, 567)


def crop_code(img: Image.Image) -> Image.Image:
    """Обрезает зону кода; если размер отличается от 770x915 — масштабирует координаты."""
    w, h = img.size
    if (w, h) == (BASE_W, BASE_H):
        return img.crop(BASE_BOX)
    kx, ky = w / BASE_W, h / BASE_H
    x1, y1, x2, y2 = BASE_BOX
    return img.crop((int(x1 * kx), int(y1 * ky), int(x2 * kx), int(y2 * ky)))


def extract_code(img: Image.Image) -> str:
    arr = np.array(img.convert("RGB"), dtype=int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    white = (r > 250) & (g > 250) & (b > 250)          # русские заглавные
    yellow = (r > 240) & (g > 240) & (b < 26)          # английские строчные
    combined = white | yellow
    if not combined.any():
        return ""

    # Сегментация по столбцам: каждый символ — отдельный блок (порядок любой)
    col = combined.any(axis=0)
    boxes, start = [], None
    for x in range(len(col)):
        if col[x] and start is None:
            start = x
        elif not col[x] and start is not None:
            boxes.append((start, x))
            start = None
    if start is not None:
        boxes.append((start, len(col)))
    boxes = [bx for bx in boxes if bx[1] - bx[0] >= 4][:5]  # максимум 5 символов

    out = ""
    for x1, x2 in boxes:
        is_ru = white[:, x1:x2].sum() >= yellow[:, x1:x2].sum()
        mask = white[:, x1:x2] if is_ru else yellow[:, x1:x2]
        rows = np.where(mask.any(axis=1))[0]
        if rows.size < 10:
            continue
        y1, y2 = rows[0], rows[-1] + 1
        char_img = Image.fromarray(np.where(mask[y1:y2], 0, 255).astype(np.uint8))
        out += _recognize(char_img, is_ru)
    return out


def _recognize(img: Image.Image, is_ru: bool) -> str:
    lang = "rus" if is_ru else "eng"
    allowed = RU if is_ru else EN
    img = img.resize((img.width * 4, img.height * 4), Image.NEAREST)
    img = ImageOps.expand(img, border=24, fill=255)
    for psm in ("10", "8", "6"):
        cfg = f"--psm {psm} -c tessedit_char_whitelist={allowed}"
        try:
            raw = pytesseract.image_to_string(img, lang=lang, config=cfg)
        except Exception:
            continue
        txt = raw.strip().replace("\n", "").replace(" ", "")
        txt = txt.upper() if is_ru else txt.lower()
        if len(txt) == 1 and txt in allowed:
            return txt
    return "?"
