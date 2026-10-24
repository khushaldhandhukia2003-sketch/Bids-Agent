from pdf2image import convert_from_path
import cv2
import pytesseract
import numpy as np
from pathlib import Path
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def extract_dimensions(file_path):

    file_path = Path(file_path)
    images = []
    all_text = ""

    if file_path.suffix.lower() == ".pdf":

        pages = convert_from_path(
            str(file_path),
            poppler_path=r"C:\poppler-25.12.0\Library\bin"
        )

        for page in pages:
            img = np.array(page)
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            images.append(img)

    else:
        img = cv2.imread(str(file_path))
        images.append(img)

    for img in images:

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        text = pytesseract.image_to_string(gray)

        all_text += text + "\n"

    numbers = []

    for word in all_text.split():
        if any(c.isdigit() for c in word):
            numbers.append(word)

    return {
        "raw_text": all_text,
        "numbers": numbers
    } 