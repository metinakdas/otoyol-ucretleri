"""Test için örnek tarife PDF'leri üretir (reportlab gerekir; yalnızca geliştirici aracı).

Değerler TEST AMAÇLIDIR. 15 Temmuz/FSM 2026 dosyası KGM'nin 2026 tarifesindeki biçimi ve
ücretleri taklit eder; 2027 dosyası ile Osmangazi ve otoyol dosyalarındaki değerler uydurmadır.

    pip install reportlab
    python tests/make_fixtures.py
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).parent / "fixtures"

FONT = "Helvetica"
for candidate in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
    if Path(candidate).exists():
        pdfmetrics.registerFont(TTFont("TR", candidate))
        FONT = "TR"
        break

ROWS = [
    ("1", "İki dingilli, dingil aralığı 3,20 m'den küçük araçlar"),
    ("2", "İki dingilli, dingil aralığı 3,20 m ve daha büyük araçlar"),
    ("3", "Üç dingilli araçlar"),
    ("4", "Dört ve beş dingilli araçlar"),
    ("5", "Altı ve daha fazla dingilli araçlar"),
    ("6", "Motosikletler"),
]


def tariff(path: Path, title: str, validity: str, fees: list[str], extra: list[str]) -> None:
    styles = getSampleStyleSheet()
    for s in styles.byName.values():
        s.fontName = FONT
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4))
    data = [["ARAÇ SINIFI", "ARAÇ TİPİ", "KÖPRÜ GEÇİŞ ÜCRETİ", "Mevcut Tarife"]]
    data += [[c, d, f, e] for (c, d), f, e in zip(ROWS, fees, extra)]
    table = Table(data, colWidths=[90, 380, 140, 110])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    doc.build([
        Paragraph(title, styles["Title"]),
        Paragraph(validity, styles["Normal"]),
        Spacer(1, 12),
        table,
        Spacer(1, 12),
        Paragraph("1- Geçiş iznine sahip olmayan araçlar geçiş ücretinin yanında cezalı geçiş ücretlerini de ödeyecektir.", styles["Normal"]),
        Paragraph("2- Ücretlere KDV dahildir.", styles["Normal"]),
    ])


def highway(path: Path, title: str, validity: str) -> None:
    styles = getSampleStyleSheet()
    for s in styles.byName.values():
        s.fontName = FONT
    doc = SimpleDocTemplate(str(path), pagesize=A4)
    doc.build([Paragraph(title, styles["Title"]), Paragraph(validity, styles["Normal"]),
               Paragraph("Giriş-çıkış gişeleri arası ücret matrisi (test).", styles["Normal"])])


if __name__ == "__main__":
    HERE.mkdir(parents=True, exist_ok=True)
    t = "15 TEMMUZ ŞEHİTLER KÖPRÜSÜ VE FATİH SULTAN MEHMET KÖPRÜSÜ GEÇİŞ ÜCRETLERİ TARİFESİ"
    tariff(HERE / "1-15Temmuz-FSM-2026.pdf", t, "(01/01/2026 Saat 00:00'dan itibaren geçerlidir.)",
           ["59,00", "75,00", "168,00", "333,00", "440,00", "25,00"],
           ["8,75", "11,25", "24,50", "49,00", "65,25", "3,50"])
    tariff(HERE / "1-15Temmuz-FSM-2027.pdf", t, "(01/01/2027 Saat 00:00'dan itibaren geçerlidir.)",
           ["72,00", "92,00", "205,00", "406,00", "537,00", "30,00"],
           ["13,00", "17,00", "37,00", "73,00", "97,00", "5,00"])
    tariff(HERE / "2-Osmangazi-2026.pdf", "OSMANGAZİ KÖPRÜSÜ GEÇİŞ ÜCRETLERİ TARİFESİ",
           "(01/01/2026 Saat 00:00'dan itibaren geçerlidir.)",
           ["995,00", "1.590,00", "1.890,00", "2.510,00", "3.170,00", "695,00"],
           ["0,00", "0,00", "0,00", "0,00", "0,00", "0,00"])
    highway(HERE / "7-Izmir-Aydin-2026.pdf", "İZMİR-AYDIN OTOYOLU GEÇİŞ ÜCRETLERİ",
            "(01/01/2026 Saat 00:00'dan itibaren geçerlidir.)")
    highway(HERE / "7-Izmir-Aydin-2027.pdf", "İZMİR-AYDIN OTOYOLU GEÇİŞ ÜCRETLERİ",
            "(01/01/2027 Saat 00:00'dan itibaren geçerlidir.)")
    print("Örnek PDF'ler üretildi:", HERE)
