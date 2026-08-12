import sys
from PIL import Image
from ocr import crop_code, extract_code
from cipher import load_cipher

img = Image.open(sys.argv[1])
letters = extract_code(crop_code(img))
cipher = load_cipher()
print("Буквы:", letters)
print("Код:  ", "".join(cipher.get(ch, "?") for ch in letters))
