from datetime import datetime
from decimal import Decimal

from conftest import FIX
from radar.extract import (
    amounts_in_line,
    class_prices_from_text,
    extract_links,
    find_effective_from,
    find_window,
    parse_tariff_pdf,
)
from radar.textutil import fold
from radar.timeutil import TZ

REF = datetime(2026, 11, 8, 12, 0, tzinfo=TZ)


def dt(*a):
    return datetime(*a, tzinfo=TZ)


def test_fold_turkish():
    assert fold("BOĞAZİÇİ KÖPRÜSÜ") == fold("bogazici koprusu") == "bogazici koprusu"
    assert fold("IĞDIR") == "igdir"
    assert fold("15\u200b Temmuz") == "15 temmuz"


def test_effective_from_kgm_format():
    assert find_effective_from("(01/01/2026 Saat 00:00'dan itibaren geçerlidir.)", REF) == dt(2026, 1, 1)
    assert find_effective_from("Yeni ücretler 1 Ocak 2027 tarihinden itibaren uygulanacak.", REF) == dt(2027, 1, 1)
    # Duyuru tarihi değil, yürürlük tarihi seçilir
    text = "Duyuru tarihi 20.12.2026 - Yeni ücretler 01.01.2027 tarihinden itibaren geçerlidir"
    assert find_effective_from(text, REF) == dt(2027, 1, 1)


def test_effective_from_missing():
    assert find_effective_from("Köprü ücretlerine zam gelecek mi?", REF) is None


def test_window_bayram():
    text = ("Kurban Bayramı nedeniyle 15 Mayıs 2027 Cumartesi günü saat 12.00'den "
            "19 Mayıs 2027 Çarşamba günü saat 24.00'e kadar köprü ve otoyollar ücretsiz olacak.")
    assert find_window(text, REF) == (dt(2027, 5, 15, 12), dt(2027, 5, 20, 0))


def test_window_without_year_and_until_only():
    start, end = find_window("8 Mart saat 12.00 ile 11 Mart saat 24.00 arasında ücretsiz", REF)
    assert start == dt(2027, 3, 8, 12) and end == dt(2027, 3, 12, 0)
    start, end = find_window("9 Mart 2027 tarihine kadar ücretsiz", REF)
    assert start is None and end == dt(2027, 3, 9, 23, 59, 59)


def test_amounts_skip_measurements():
    line = "1 iki dingilli, dingil araligi 3,20 m'den kucuk araclar 59,00 8,75"
    assert amounts_in_line(line) == [Decimal("59.00"), Decimal("8.75")]
    assert amounts_in_line("2 araclar 1.590,00") == [Decimal("1590.00")]


def test_class_prices_from_wrapped_text():
    text = """BAŞLIK
1 İki dingilli, dingil aralığı 3,20 m'den küçük araçlar 59,00 8,75
2 İki dingilli, dingil aralığı 3,20 m ve daha büyük araçlar
(UKOME kararı ile geçebilen ve geçemeyen) 75,00 11,25
3 Üç dingilli araçlar 168,00 24,50
6 Motosikletler 25,00 3,50
1- Geçiş iznine sahip olmayan araçlar 999,00 cezalı"""
    prices = class_prices_from_text(text)
    assert prices[1] == Decimal("59.00")
    assert prices[2] == Decimal("75.00")  # tutar alt satırda
    assert prices[3] == Decimal("168.00")
    assert prices[6] == Decimal("25.00")


def test_parse_tariff_pdf_table():
    r = parse_tariff_pdf((FIX / "1-15Temmuz-FSM-2026.pdf").read_bytes(), REF)
    assert r.ok and r.method == "tablo"
    assert r.prices[1] == Decimal("59.00") and r.prices[5] == Decimal("440.00") and r.prices[6] == Decimal("25.00")
    assert r.effective_from == dt(2026, 1, 1)
    assert r.warnings == []


def test_parse_highway_pdf_has_date_but_no_classes():
    r = parse_tariff_pdf((FIX / "7-Izmir-Aydin-2026.pdf").read_bytes(), REF)
    assert not r.ok
    assert r.effective_from == dt(2026, 1, 1)


def test_extract_links_merges_icon_and_text():
    html = """<a href="/a.pdf"><img src="i.gif"></a><a href="/a.pdf">1- 15 Temmuz Tarifesi</a>
              <a href="#">x</a><a href="javascript:void(0)">y</a>"""
    links = extract_links(html, "https://www.kgm.gov.tr/Sayfalar/x.aspx")
    assert len(links) == 1
    assert links[0].url == "https://www.kgm.gov.tr/a.pdf"
    assert links[0].text == "1- 15 Temmuz Tarifesi"
