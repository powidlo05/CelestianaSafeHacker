from pathlib import Path


def load_cipher(filename: str = "shifr.txt") -> dict[str, str]:
    # Читает соответствие букв->код из shifr.txt
    cipher = {}
    path = Path(__file__).parent / filename
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            cipher[k.strip()] = v.strip()
    return cipher