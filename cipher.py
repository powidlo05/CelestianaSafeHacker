from pathlib import Path

# Фолбэк, если shifr.txt нет рядом (значения из твоего файла)
DEFAULT = {
    **{k: v for k, v in zip("АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
       ["1","11","111","1111","2","22","222","2222","3","33","333","3333",
        "4","44","444","4444","5","55","555","5555","6","66","666","6666",
        "7","77","777","7777","8","88","888","8888"])},
    **{k: v for k, v in zip("abcdefghijklmnopqrstuvwxyz",
       ["11111","111111","1111111","22222","222222","2222222","22222222",
        "33333","333333","3333333","33333333","44444","444444","4444444",
        "44444444","55555","555555","5555555","55555555","66666","666666",
        "6666666","66666666","77777","777777","7777777"])},
}


def load_cipher(filename: str = "shifr.txt") -> dict[str, str]:
    cipher = dict(DEFAULT)
    path = Path(__file__).parent / filename
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                cipher[k.strip()] = v.strip()
    return cipher
