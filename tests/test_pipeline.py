"""Uçtan uca senaryo: kurulum → yılbaşı tarife değişikliği → hatırlatmalar → yürürlük →
bayramda ücretsiz geçiş duyurusu → başlangıç ve bitiş. Tümü sahte sitelerle, internete çıkmadan."""

from datetime import datetime

from conftest import FIX
from radar import prices as ledger
from radar.pipeline import run_once
from radar.store import Store
from radar.timeutil import TZ

KGM_LIST = "https://www.kgm.gov.tr/Sayfalar/KGM/SiteTr/Otoyollar/UcretlerYeni.aspx"
PDF_BASE = "https://www.kgm.gov.tr/SiteCollectionDocuments/KGMdocuments/Otoyollar/OtoyolKopruUcret/"
UAB = "https://www.uab.gov.tr/haberler/"


def t(*a):
    return datetime(*a, tzinfo=TZ)


def kgm_page(fsm_year: int, izmir_year: int) -> str:
    return f"""<html><body><h1>Otoyol ve Köprü Geçiş Ücretleri (TL Cinsinden)</h1>
<table><tr><td><a href="{PDF_BASE}{fsm_year}Gecis_Ucret/1-15Temmuz-FSM.pdf"><img src="pdf.gif"></a></td>
<td><a href="{PDF_BASE}{fsm_year}Gecis_Ucret/1-15Temmuz-FSM.pdf">1-\u200b 15 Temmuz Şehitler ve Fatih Sultan Mehmet Köprüleri Geçiş Ücretleri Tarifesi</a></td></tr></table>
<table><tr><td><a href="{PDF_BASE}2026Gecis_Ucret/2-Osmangazi.pdf">2- Osmangazi Köprüsü Geçiş Ücretleri Tarifesi</a></td></tr></table>
<table><tr><td><a href="{PDF_BASE}{izmir_year}Gecis_Ucret/7-Izmir-Aydin.pdf">7- İzmir-Aydın Otoyolu Geçiş Ücretleri Tarifesi</a></td></tr></table>
<a href="/Sayfalar/KGM/SiteTr/Root/Duyurular.aspx">Duyurular</a></body></html>"""


def uab_page(items: list[tuple[str, str]]) -> str:
    links = "".join(f'<li><a href="/haberler/{slug}">{title}</a></li>' for slug, title in items)
    return f"""<html><body><nav><a href="/">Ana Sayfa</a> <a href="/haberler/">Haberler</a></nav>
<ul>{links}</ul><footer><a href="/kvkk">Kişisel Verilerin Korunması Kanunu Aydınlatma Metni</a></footer></body></html>"""


OLD_NEWS = [
    ("bakan-ziyaret", "Bakan liman projesini yerinde inceledi 02.11.2026"),
    ("hizli-tren", "Hızlı tren seferlerine yoğun ilgi sürüyor 05.11.2026"),
]
BAYRAM_NEWS = ("kurban-bayrami-kopru-otoyol", "Kurban Bayramı'nda köprü ve otoyollar ücretsiz olacak 20.04.2027")
BAYRAM_DETAIL = """<html><body><article><h1>Kurban Bayramı'nda köprü ve otoyollar ücretsiz olacak</h1>
<p>Bakanlık açıklamasına göre Kurban Bayramı nedeniyle 15 Mayıs 2027 Cumartesi günü saat 12.00'den
19 Mayıs 2027 Çarşamba günü saat 24.00'e kadar Karayolları Genel Müdürlüğü'nün işlettiği köprü ve otoyollar ücretsiz olacak.</p>
<p>Yap-işlet-devret modeliyle yapılan Yavuz Sultan Selim Köprüsü, Osmangazi Köprüsü, 1915 Çanakkale Köprüsü
ve Avrasya Tüneli'nde ücretsiz geçiş uygulanmayacak.</p></article></body></html>"""


def setup_sources(cfg):
    for s in cfg.sources:
        s.enabled = s.id in ("kgm-tarifeler", "uab-haberler")


def serve_2026(web):
    web.html(KGM_LIST, kgm_page(2026, 2026))
    web.pdf(PDF_BASE + "2026Gecis_Ucret/1-15Temmuz-FSM.pdf", FIX / "1-15Temmuz-FSM-2026.pdf")
    web.pdf(PDF_BASE + "2026Gecis_Ucret/2-Osmangazi.pdf", FIX / "2-Osmangazi-2026.pdf")
    web.pdf(PDF_BASE + "2026Gecis_Ucret/7-Izmir-Aydin.pdf", FIX / "7-Izmir-Aydin-2026.pdf")
    web.html(UAB, uab_page(OLD_NEWS))


def run(cfg, web, telegram, when):
    return run_once(cfg, now=when, transport=web.transport, notify_client=telegram.client)


def test_full_year(cfg, web, telegram):
    setup_sources(cfg)
    store = Store(cfg.data_dir)

    # 1) Kurulum: ücretler başlangıç olarak kaydedilir, yalnızca kurulum mesajı gider
    serve_2026(web)
    rep = run(cfg, web, telegram, t(2026, 11, 8, 12))
    assert rep.first_run
    assert all(s[1] == "tamam" for s in rep.sources), rep.sources
    data = store.read("crossings.json", {})
    assert ledger.entry_at(data, "15-temmuz-sehitler", t(2026, 11, 8))["classes"]["1"] == "59.00"
    assert ledger.entry_at(data, "fatih-sultan-mehmet", t(2026, 11, 8))["classes"]["6"] == "25.00"
    assert ledger.entry_at(data, "osmangazi", t(2026, 11, 8))["classes"]["2"] == "1590.00"
    assert store.load_events() == {}
    msgs = telegram.take()
    assert len(msgs) == 1 and "KURULUM" in msgs[0]
    assert store.path("panel.json").exists()

    # 2) Değişiklik yok: bildirim yok
    rep = run(cfg, web, telegram, t(2026, 11, 20, 9))
    assert not rep.first_run and rep.candidates == 0
    assert telegram.take() == []

    # 3) KGM 2027 tarifelerini yayımlıyor (yılbaşı izleme dönemi içinde)
    web.html(KGM_LIST, kgm_page(2027, 2027))
    web.pdf(PDF_BASE + "2027Gecis_Ucret/1-15Temmuz-FSM.pdf", FIX / "1-15Temmuz-FSM-2027.pdf")
    web.pdf(PDF_BASE + "2027Gecis_Ucret/7-Izmir-Aydin.pdf", FIX / "7-Izmir-Aydin-2027.pdf")
    rep = run(cfg, web, telegram, t(2026, 12, 15, 10))
    events = store.load_events()
    decided = [e for e in events.values() if e["status"] == "karar_cikti"]
    assert len(decided) == 1, [(e["id"], e["status"]) for e in events.values()]
    ev = decided[0]
    assert ev["effective_from"] == "2027-01-01T00:00:00+03:00"
    assert set(ev["crossings"]) == {"15-temmuz-sehitler", "fatih-sultan-mehmet"}
    assert len(ev["documents"]) == 2  # köprü tarifesi + İzmir-Aydın otoyolu tek kayıtta
    assert ev["prices"]["15-temmuz-sehitler"]["old"]["1"] == "59.00"
    assert ev["prices"]["15-temmuz-sehitler"]["new"]["1"] == "72.00"
    data = store.read("crossings.json", {})
    assert ledger.entry_at(data, "15-temmuz-sehitler", t(2026, 12, 31, 23, 59))["classes"]["1"] == "59.00"
    assert ledger.entry_at(data, "15-temmuz-sehitler", t(2027, 1, 1, 0, 1))["classes"]["1"] == "72.00"
    msgs = telegram.take()
    assert len(msgs) == 1, msgs  # izleme mesajı ayrıca gitmez, yalnızca karar
    assert "KARAR ÇIKTI" in msgs[0]
    assert "59,00 TL → <b>72,00 TL</b>" in msgs[0]
    assert "1 Ocak 2027 00:00" in msgs[0]

    # 4) Hatırlatmalar
    run(cfg, web, telegram, t(2026, 12, 25, 9))
    msgs = telegram.take()
    assert len(msgs) == 1 and "7 gün kaldı" in msgs[0]
    run(cfg, web, telegram, t(2026, 12, 31, 9))
    msgs = telegram.take()
    assert len(msgs) == 1 and "yarın yürürlükte" in msgs[0]

    # 5) Yürürlük anı
    run(cfg, web, telegram, t(2027, 1, 1, 0, 20))
    msgs = telegram.take()
    assert len(msgs) == 1 and "BUGÜN YÜRÜRLÜKTE" in msgs[0]
    assert store.load_events()[ev["id"]]["status"] == "yururlukte"

    # 6) Bakanlık bayramda ücretsiz geçişi duyuruyor
    web.html(UAB, uab_page([BAYRAM_NEWS] + OLD_NEWS))
    web.html("https://www.uab.gov.tr/haberler/kurban-bayrami-kopru-otoyol", BAYRAM_DETAIL)
    run(cfg, web, telegram, t(2027, 4, 20, 10))
    free = [e for e in store.load_events().values() if e["kind"] == "ucretsiz_gecis"]
    assert len(free) == 1
    fe = free[0]
    assert fe["status"] == "karar_cikti"
    assert fe["effective_from"] == "2027-05-15T12:00:00+03:00"
    assert fe["effective_to"] == "2027-05-20T00:00:00+03:00"
    assert fe["period_id"] == "kurban-bayrami-2027"
    assert "15-temmuz-sehitler" in fe["crossings"]
    for yid in ("yavuz-sultan-selim", "osmangazi", "1915-canakkale", "avrasya-tuneli"):
        assert yid in fe["excluded"] and yid not in fe["crossings"]
    assert "kapsam_kontrol" in fe["flags"]
    rules = store.load_rules()
    assert len(rules) == 1 and list(rules.values())[0]["fee"] == 0
    msgs = telegram.take()
    assert len(msgs) == 1 and "KARAR ÇIKTI" in msgs[0]
    assert "Kapsam dışı" in msgs[0] and "Avrasya Tüneli" in msgs[0]

    # 7) Kurban izleme dönemi başlıyor ama karar zaten var: ayrı izleme kaydı açılmaz
    run(cfg, web, telegram, t(2027, 5, 3, 9))
    assert "takvim-kurban-bayrami-2027" not in store.load_events()
    assert telegram.take() == []

    # 8) Ücretsiz geçiş başlıyor ve bitiyor
    run(cfg, web, telegram, t(2027, 5, 15, 12, 30))
    msgs = telegram.take()
    assert len(msgs) == 1 and "BUGÜN YÜRÜRLÜKTE" in msgs[0]
    panel = store.read("panel.json", {})
    fsm = next(c for c in panel["crossings"] if c["id"] == "15-temmuz-sehitler")
    assert fsm["free_now"] is not None
    run(cfg, web, telegram, t(2027, 5, 20, 1))
    msgs = telegram.take()
    assert len(msgs) == 1 and "SONA ERDİ" in msgs[0]


def test_source_failure_alert(cfg, web, telegram):
    setup_sources(cfg)
    serve_2026(web)
    run(cfg, web, telegram, t(2026, 11, 8, 12))
    telegram.take()
    web.error(KGM_LIST, 500)
    rep = run(cfg, web, telegram, t(2026, 11, 9, 12))
    assert ("kgm-tarifeler", "HATA") == rep.sources[0][:2]
    assert telegram.take() == []  # 24 saat dolmadan uyarı yok
    run(cfg, web, telegram, t(2026, 11, 10, 13))
    sent = telegram.sent[:]
    assert len(sent) == 1 and sent[0]["chat_id"] == "-200"  # teknik gruba
    assert "KAYNAK HATASI" in sent[0]["text"]
    panel = Store(cfg.data_dir).read("panel.json", {})
    src = next(s for s in panel["sources"] if s["id"] == "kgm-tarifeler")
    assert src["ok"] is False


def test_news_needs_two_publishers(cfg, web, telegram):
    """Haber kaynaklarında tek haber sinyaldir; aynı tarihi veren ikinci yayın karar yapar."""
    rss_url = next(s.url for s in cfg.sources if s.id == "haber-gecis-zam")
    for s in cfg.sources:
        s.enabled = s.id == "haber-gecis-zam"

    def feed(items):
        body = "".join(
            f"<item><title>{title}</title><link>https://news.example/{i}</link><guid>{i}</guid>"
            f"<pubDate>{pub}</pubDate><source url='https://{src}'>{src}</source><description>{desc}</description></item>"
            for i, (title, desc, src, pub) in enumerate(items)
        )
        return f"<?xml version='1.0'?><rss version='2.0'><channel><title>t</title>{body}</channel></rss>"

    old = ("Eski haber", "", "a.com", "Mon, 02 Nov 2026 10:00:00 GMT")
    web.routes[rss_url] = (200, feed([old]).encode(), "application/rss+xml")
    run(cfg, web, telegram, t(2026, 11, 8, 12))
    telegram.take()

    n1 = ("Köprü ve otoyol geçiş ücretlerine zam", "Yeni ücretler 1 Ocak 2027 tarihinden itibaren geçerli olacak.",
          "birinci-gazete.com", "Wed, 25 Nov 2026 08:00:00 GMT")
    web.routes[rss_url] = (200, feed([old, n1]).encode(), "application/rss+xml")
    run(cfg, web, telegram, t(2026, 11, 25, 10))
    ev = next(iter(Store(cfg.data_dir).load_events().values()))
    assert ev["status"] == "sinyal"
    assert telegram.take() == []  # sinyal anında bildirilmez, günlük özete girer

    n2 = ("Köprü ve otoyollarda yeni tarife açıklandı", "Zamlı ücretler 1 Ocak 2027'den itibaren uygulanacak.",
          "ikinci-gazete.com", "Wed, 25 Nov 2026 11:00:00 GMT")
    web.routes[rss_url] = (200, feed([old, n1, n2]).encode(), "application/rss+xml")
    run(cfg, web, telegram, t(2026, 11, 25, 12))
    ev = next(e for e in Store(cfg.data_dir).load_events().values() if not e["id"].startswith("takvim"))
    assert ev["status"] == "karar_cikti"
    assert "degerler_okunamadi" in ev["flags"]
