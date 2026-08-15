import numpy as np
from PIL import Image, ImageOps
import pytesseract

RU = "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
EN = "abcdefghijklmnopqrstuvwxyz"
BASE_W, BASE_H = 770, 915
BASE_BOX = (170, 450, 610, 567)


def crop_code(img: Image.Image) -> Image.Image:
    w, h = img.size
    if (w, h) == (BASE_W, BASE_H):
        return img.crop(BASE_BOX)
    kx, ky = w / BASE_W, h / BASE_H
    x1, y1, x2, y2 = BASE_BOX
    return img.crop((int(x1 * kx), int(y1 * ky), int(x2 * kx), int(y2 * ky)))


def extract_code(img: Image.Image) -> str:
    arr = np.array(img.convert("RGB"), dtype=int)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # пороги чуть мягче 250/240, чтобы захватить сглаженные края букв
    white = (r > 200) & (g > 200) & (b > 200)  # русские заглавные
    yellow = (r > 200) & (g > 200) & (b < 100)  # английские строчные
    combined = white | yellow
    if not combined.any():
        return ""

    # сегментация по столбцам: каждый символ — отдельный блок
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
    boxes = [bx for bx in boxes if bx[1] - bx[0] >= 4][:5]

    chars = []
    for x1, x2 in boxes:
        is_ru = white[:, x1:x2].sum() >= yellow[:, x1:x2].sum()
        mask = (white if is_ru else yellow)[:, x1:x2]
        rows = np.where(mask.any(axis=1))[0]
        if rows.size < 10:
            continue
        y1, y2 = rows[0], rows[-1] + 1
        chars.append((mask[y1:y2], is_ru))

    out = ""
    for mask, is_ru in chars:
        ch = _recognize(mask, is_ru)
        ch = _fix_letter(ch, mask)  # геометрическая коррекция путаницы a/d, n/h, o/b
        out += ch
    return out


def _mask_to_image(mask: np.ndarray) -> Image.Image:
    img = Image.fromarray(np.where(mask, 0, 255).astype(np.uint8))
    factor = max(2, min(6, 140 // max(1, img.height) + 1))
    img = img.resize((img.width * factor, img.height * factor), Image.Resampling.LANCZOS)
    img = img.point(lambda p: 0 if p < 128 else 255)  # повторная бинаризация
    return ImageOps.expand(img, border=20, fill=255)


def _recognize(mask: np.ndarray, is_ru: bool) -> str:
    lang = "rus" if is_ru else "eng"
    allowed = RU if is_ru else EN
    img = _mask_to_image(mask)
    votes = []
    for psm in ("10", "8", "6"):
        cfg = f"--psm {psm} -c tessedit_char_whitelist={allowed}"
        try:
            raw = pytesseract.image_to_string(img, lang=lang, config=cfg)
        except Exception:
            continue
        txt = raw.strip().replace("\n", "").replace(" ", "")
        txt = txt.upper() if is_ru else txt.lower()
        if len(txt) == 1 and txt in allowed:
            votes.append(txt)
    if not votes:
        return "?"
    return max(set(votes), key=votes.count)


def _top_features(mask: np.ndarray):
    # Ширина и сторона заполнения верхней пятой части символа
    h, w = mask.shape
    band = mask[: max(2, h // 5), :]
    cols = np.where(band.any(axis=0))[0]
    width_ratio = cols.size / w
    side = None
    if cols.size:
        side = "left" if (cols[0] + cols[-1]) / 2 < w / 2 else "right"
    return width_ratio, side


def _fix_letter(ch: str, mask: np.ndarray) -> str:
    top_w, side = _top_features(mask)
    narrow_top = top_w < 0.5  # наверху только узкий стебель => есть выносная палка
    if narrow_top:
        # tesseract сказал строчную без палки, но палка явно есть
        if ch == "a":
            return "d"
        if ch == "n":
            return "h"
        if ch == "o":
            return "d" if side == "right" else "b"
    else:
        # tesseract сказал букву с палкой, но верх широкий => палки нет
        if ch == "d":
            return "a"
        if ch == "h":
            return "n"
        if ch == "b":
            return "o"
    return ch
