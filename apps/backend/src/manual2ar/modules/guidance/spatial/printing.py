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


def workboard():
    """Same ID/size as V1; explicit flat-board placement makes marker XYZ the teaching work frame."""
    page=Image.new('RGB',(2100,2970),'white');d=ImageDraw.Draw(page)
    d.font=ImageFont.load_default(size=33)
    page.paste(Image.fromarray(marker_image()).resize((800,800),Image.Resampling.NEAREST),(650,1000))
    d.text((140,130),'Manual2AR | A1 mini work-coordinate board v1',fill='black')
    d.text((140,210),'PRINT 100% / ACTUAL SIZE. Black square = 80 x 80 mm.',fill='black')
    d.text((140,285),'Fix FLAT, face up, to a rigid surface beside the printer.',fill='black')
    d.text((140,360),'Align +X with printer X; +Y points towards printer REAR.',fill='black')
    def arrow(a,b,color):
        d.line((*a,*b),fill=color,width=12)
        import math
        angle=math.atan2(b[1]-a[1],b[0]-a[0])
        for delta in (-.5,.5):d.line((*b,b[0]-55*math.cos(angle+delta),b[1]-55*math.sin(angle+delta)),fill=color,width=12)
    arrow((1050,900),(1050,630),(0,135,50));d.text((1110,650),'+Y REAR',fill=(0,120,40))
    arrow((1520,1400),(1880,1400),(200,30,30));d.text((1550,1460),'+X RIGHT',fill=(180,20,20))
    d.text((450,1920),'O = marker centre | +Z = UP, out of paper',fill=(30,65,180))
    d.text((310,2050),'This edge faces printer FRONT. Keep board and printer fixed.',fill='black')
    d.text((260,2180),'Teaching frame only. Not a firmware zero or motion command.',fill='black')
    d.line((550,2450,1550,2450),fill='black',width=4)
    for x in (550,1550):d.line((x,2420,x,2480),fill='black',width=4)
    d.text((620,2520),'Measure this line: exactly 100 mm',fill='black')
    stream=io.BytesIO();page.save(stream,'PDF',resolution=254);return stream.getvalue()
