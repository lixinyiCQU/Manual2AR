"""Printable calibration assets, generated in memory; print PDF at actual size."""
import io
import cv2
from PIL import Image, ImageDraw, ImageFont

MARKER_ID = 23
MARKER_LENGTH = .08
SQUARE = .02
PATTERN = (9, 6)


def marker_image():
    return cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), MARKER_ID, 600)


def sheets():
    # 254 DPI = exactly ten pixels per millimetre. A4 210 x 297 mm.
    pages = []
    for kind in ('marker', 'chessboard'):
        page = Image.new('RGB', (2100, 2970), 'white'); draw = ImageDraw.Draw(page)
        draw.font=ImageFont.load_default(size=28)
        if kind == 'marker':
            page.paste(Image.fromarray(marker_image()).resize((800, 800), Image.Resampling.NEAREST), (650, 700))
            title = 'Manual2AR | DICT_4X4_50 ID 23 | black square: 80 x 80 mm'
            draw.text((280, 1550), 'TOP (+Y) is the printed top of the marker. Keep rigidly fixed to printer.', fill='black')
        else:
            title = 'Manual2AR | camera calibration | 9 x 6 inner corners | square 20 mm'
            for y in range(7):
                for x in range(10):
                    if (x + y) % 2 == 0:draw.rectangle((50+x*200,700+y*200,49+(x+1)*200,699+(y+1)*200),fill='black')
        draw.text((120, 180), title, fill='black')
        draw.text((120, 250), 'PRINT ACTUAL SIZE / 100%. Disable fit-to-page. Verify scale with ruler.', fill='black')
        draw.line((550, 2450, 1550, 2450), fill='black', width=4)
        draw.line((550, 2420, 550, 2480), fill='black', width=4);draw.line((1550, 2420, 1550, 2480), fill='black', width=4)
        draw.text((800, 2510), 'This line must measure 100 mm', fill='black');pages.append(page)
    stream=io.BytesIO();pages[0].save(stream,'PDF',resolution=254,save_all=True,append_images=pages[1:])
    return stream.getvalue()
