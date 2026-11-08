"""Komut satırı.

    python -m radar calistir        Bir radar turu çalıştırır (GitHub Actions bunu 30 dakikada bir çağırır)
    python -m radar kaynak-testi    Kaynakların okunup okunmadığını ve PDF'lerden okunan ücretleri gösterir
    python -m radar test-bildirim   Telegram ve e-posta ayarlarını deneme mesajıyla sınar
    python -m radar panel           Paneli yerelde açar (--ornek: örnek veriyle)
    python -m radar harita-guncelle Otoyol gişelerinin konumlarını OpenStreetMap'ten yeniler
    python -m radar durum           Kayıtların ve ücretlerin özetini yazdırır
    python -m radar yayinla         Projeyi güvenlik taramasından geçirip GitHub'da yayınlar
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from . import __version__
from .config import ConfigError, load_config
from .timeutil import TZ, fmt_datetime, from_iso, now as tz_now


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


# ---------------------------------------------------------------------------

def cmd_calistir(args, cfg) -> int:
    from .pipeline import run_once

    report = run_once(cfg, now=_parse_time(args.zaman), send=not args.bildirim_yok, dry_run=args.deneme)
    print(f"Tarife Radarı {__version__} · {fmt_datetime(_parse_time(args.zaman) or tz_now())}")
    if report.first_run:
        print("İlk çalıştırma: kaynaklar başlangıç olarak kaydedildi, değişiklik bildirimi gönderilmedi.")
    for sid, status, info in report.sources:
        print(f"  [{status}] {sid}: {info}")
    if report.status_changes:
        print("Durum değişiklikleri:")
        for line in report.status_changes:
            print(f"  - {line}")
    for note in report.notes:
        print(f"  · {note}")
    for line in report.messages:
        print(f"  ✉ {line}")
    if args.deneme:
        print("Deneme modu: hiçbir dosya yazılmadı.")
    elif report.written:
        print("Yazılan: " + ", ".join(report.written))
    failed = [s for s in report.sources if s[1] != "tamam"]
    return 0 if not failed or len(failed) < len(report.sources) else 1


def cmd_kaynak_testi(args, cfg) -> int:
    from .extract import extract_links, page_text, parse_tariff_pdf, same_site
    from .fetch import Fetcher
    from .matching import Matcher
    from .collectors import PDF_RE, _is_tariff

    matcher = Matcher(cfg.crossings, cfg.generic_phrases)
    now = tz_now()
    sources = [s for s in cfg.sources if (args.hepsi or s.enabled) and (not args.kaynak or s.id == args.kaynak)]
    if not sources:
        print("Kaynak bulunamadı. Kimliği config/sources.yaml'dan kontrol edin.")
        return 1
    bad = 0
    with Fetcher(cfg.settings.user_agent, min_delay=cfg.settings.request_delay) as f:
        for src in sources:
            print(f"\n== {src.name} ({src.id}) {'[kapalı]' if not src.enabled else ''}")
            print(f"   {src.url}")
            try:
                r = f.get(src.url)
            except Exception as exc:
                bad += 1
                print(f"   HATA: {exc}")
                continue
            print(f"   HTTP {r.status} · {r.content_type or '?'} · {len(r.content):,} bayt")
            if src.type == "tarife_listesi":
                links = [l for l in extract_links(r.text, r.final_url) if PDF_RE.search(l.url) and _is_tariff(l.text, l.url)]
                print(f"   PDF tarife bağlantısı: {len(links)}")
                for l in links:
                    mapped = matcher.crossings_for_document(l.text, l.url)
                    tag = ", ".join(c.name for c in mapped) if mapped else "—"
                    print(f"   - {l.text[:80]}  →  {tag}")
                    if any(c.parse == "sinif_tablosu" for c in mapped) and not args.hizli:
                        try:
                            pr = f.get(l.url)
                            parsed = parse_tariff_pdf(pr.content, now)
                            prices = ", ".join(f"{k}. sınıf {v}" for k, v in sorted(parsed.prices.items())) or "okunamadı"
                            print(f"       geçerlilik: {fmt_datetime(parsed.effective_from)} · {prices}")
                            for w in parsed.warnings:
                                print(f"       uyarı: {w}")
                        except Exception as exc:
                            print(f"       PDF okunamadı: {exc}")
            elif src.type == "liste":
                items = [l for l in extract_links(r.text, r.final_url) if len(l.text) >= 25 and same_site(l.url, src.url)]
                print(f"   Başlık sayısı: {len(items)}")
                for l in items[:8]:
                    cls = matcher.classify(l.text, src.crossings)
                    mark = f"  ← ilgili ({cls.kind or 'iptal'})" if cls else ""
                    print(f"   - {l.text[:100]}{mark}")
            elif src.type == "rss":
                import feedparser

                feed = feedparser.parse(r.content)
                print(f"   Haber sayısı: {len(feed.entries)}")
                for e in feed.entries[:8]:
                    cls = matcher.classify(e.get("title", ""), src.crossings)
                    mark = f"  ← ilgili ({cls.kind or 'iptal'})" if cls else ""
                    print(f"   - {e.get('title', '')[:100]}{mark}")
            else:
                text = page_text(r.text, src.selector)
                print(f"   Metin uzunluğu: {len(text)} karakter")
    print("\nBitti." + (f" {bad} kaynak okunamadı." if bad else " Tüm kaynaklar okundu."))
    return 1 if bad else 0


def cmd_test_bildirim(args, cfg) -> int:
    from .guvenlik import redact
    from .notify import send_email, send_telegram

    s = cfg.settings
    text = "<b>[TEST] Tarife Radarı</b>\nBu bir deneme mesajıdır. Bildirim ayarları çalışıyor."
    ok = True
    if s.telegram_ready:
        try:
            send_telegram(cfg, s.telegram_chat_id, text)
            print("Telegram: gönderildi.")
            if s.telegram_tech_chat_id:
                send_telegram(cfg, s.telegram_tech_chat_id, text.replace("[TEST]", "[TEST · teknik grup]"))
                print("Telegram teknik grup: gönderildi.")
        except Exception as exc:
            ok = False
            print(f"Telegram: HATA {redact(exc, s)}")
    else:
        print("Telegram: TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID tanımlı değil (.env).")
    if s.email_ready:
        try:
            send_email(cfg, "[Tarife Radarı] Test", "Bu bir deneme mesajıdır. E-posta ayarları çalışıyor.")
            print(f"E-posta: gönderildi ({', '.join(s.email_to)}).")
        except Exception as exc:
            ok = False
            print(f"E-posta: HATA {redact(exc, s)}")
    else:
        print("E-posta: SMTP_HOST, EMAIL_TO ve SMTP_FROM/SMTP_USER tanımlı değil (.env).")
    return 0 if ok else 1


def cmd_panel(args, cfg) -> int:
    from .demo import sample_map, sample_panel
    from .panel import serve, write_json

    if args.ornek:
        write_json(cfg.root / "panel" / "ornek-panel.json", sample_panel(cfg, tz_now()))
        write_json(cfg.root / "panel" / "ornek-harita.json", sample_map(tz_now()))
    elif not (cfg.data_dir / "panel.json").exists():
        print("Henüz panel verisi yok. Önce 'python -m radar calistir' çalıştırın ya da '--ornek' ile örnek veriye bakın.")
        return 1
    serve(cfg.root, port=args.port, sample=args.ornek, open_browser=not args.tarayici_yok)
    return 0


def cmd_harita(args, cfg) -> int:
    from collections import Counter

    from . import bolgeler, harita
    from .store import Store

    store = Store(cfg.data_dir)
    state = store.read("state.json", {})
    print("Gişe konumları OpenStreetMap'ten alınıyor (birkaç dakika sürebilir)…")
    note = harita.refresh(cfg, store, state, tz_now(), force=True)
    if store.exists:  # radar hiç çalışmadıysa state.json yazılmaz; ilk tur yine "ilk çalıştırma" olur
        store.write("state.json", state)
    print(note)
    data = store.read("harita.json", None)
    if not data:
        return 1
    points = data["noktalar"]
    print(f"\nToplam {len(points)} nokta · {sum(1 for p in points if p['adsiz'])} adsız · "
          f"{sum(1 for p in points if p['tur'] == 'serbest')} serbest geçiş noktası")
    per_region = Counter(p["bolge"] for p in points)
    for bid, ad, _, _ in bolgeler.BOLGELER:
        print(f"  {ad}: {per_region.get(bid, 0)}")
    if per_region.get(None):
        print(f"  İli bulunamayan: {per_region[None]}")
    roads = Counter(p["yol"] for p in points if p["yol"])
    if roads:
        print("En çok gişesi olan yollar: " + ", ".join(f"{r} ({n})" for r, n in roads.most_common(8)))
    return 1 if note and note.startswith("Harita verisi alınamadı") else 0


def cmd_yayinla(args, cfg) -> int:
    from .yayin import main as yayin_main

    return yayin_main(args)


def cmd_durum(args, cfg) -> int:
    from . import prices as ledger
    from .models import STATUS_LABELS
    from .store import Store

    store = Store(cfg.data_dir)
    if not store.exists:
        print("Henüz kayıt yok. Önce 'python -m radar calistir' çalıştırın.")
        return 1
    now = tz_now()
    data = store.read("crossings.json", {})
    print("Güncel ücretler (1. sınıf):")
    for c in cfg.crossings:
        if not c.panel:
            continue
        cur = ledger.entry_at(data, c.id, now)
        up = ledger.upcoming_entry(data, c.id, now)
        line = f"  {c.name}: {cur['classes'].get('1') + ' TL' if cur else '—'}"
        if up:
            line += f"  →  {up['classes'].get('1')} TL ({fmt_datetime(from_iso(up['valid_from']))})"
        print(line)
    events = store.load_events()
    open_events = [e for e in events.values() if e["status"] in ("sinyal", "gundemde", "karar_cikti")]
    print(f"\nAçık kayıtlar: {len(open_events)}")
    for e in sorted(open_events, key=lambda e: e["updated_at"], reverse=True):
        print(f"  [{STATUS_LABELS[e['status']]}] {e['title']} · yürürlük {fmt_datetime(from_iso(e.get('effective_from')))}")
    health = store.read("health.json", {})
    print("\nKaynaklar:")
    for s in cfg.sources:
        if not s.enabled:
            continue
        h = health.get(s.id, {})
        state = "çalışıyor" if h.get("ok") else f"HATA: {h.get('error', 'bilinmiyor')}"
        print(f"  {s.name}: {state}")
    harita_data = store.read("harita.json", None)
    if harita_data:
        print(f"\nHarita: {len(harita_data['noktalar'])} gişe noktası · "
              f"güncelleme {fmt_datetime(from_iso(harita_data['olusturma']))}")
    else:
        print("\nHarita: gişe verisi henüz yok ('python -m radar harita-guncelle').")
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m radar", description="Tarife Radarı: geçiş ücreti değişikliklerini izler.")
    p.add_argument("--ayrinti", action="store_true", help="Ayrıntılı günlük")
    sub = p.add_subparsers(dest="komut", required=True)

    c = sub.add_parser("calistir", aliases=["run"], help="Bir radar turu çalıştırır")
    c.add_argument("--bildirim-yok", action="store_true", help="Bildirim göndermeden çalıştır")
    c.add_argument("--deneme", action="store_true", help="Hiçbir dosya yazmadan ve göndermeden ne olacağını göster")
    c.add_argument("--zaman", help="Şimdiki zamanı taklit et (ör. 2026-12-31T23:00)")
    c.set_defaults(func=cmd_calistir)

    k = sub.add_parser("kaynak-testi", help="Kaynakları dener, PDF'lerden okunan ücretleri gösterir")
    k.add_argument("--kaynak", help="Yalnızca bu kaynak kimliği")
    k.add_argument("--hepsi", action="store_true", help="Kapalı kaynakları da dene")
    k.add_argument("--hizli", action="store_true", help="PDF'leri indirme")
    k.set_defaults(func=cmd_kaynak_testi)

    t = sub.add_parser("test-bildirim", help="Telegram ve e-postaya deneme mesajı gönderir")
    t.set_defaults(func=cmd_test_bildirim)

    pn = sub.add_parser("panel", help="Paneli yerelde açar")
    pn.add_argument("--ornek", action="store_true", help="Örnek veriyle aç")
    pn.add_argument("--port", type=int, default=8000)
    pn.add_argument("--tarayici-yok", action="store_true", help="Tarayıcıyı otomatik açma")
    pn.set_defaults(func=cmd_panel)

    h = sub.add_parser("harita-guncelle", help="Otoyol gişelerinin konumlarını OpenStreetMap'ten yeniler")
    h.set_defaults(func=cmd_harita)

    d = sub.add_parser("durum", help="Kayıtların özetini yazdırır")
    d.set_defaults(func=cmd_durum)

    y = sub.add_parser("yayinla", help="Güvenlik taramasından geçirip GitHub'da yayınlar")
    y.add_argument("--depo", default="otoyol-ucretleri", help="Depo adı (varsayılan: otoyol-ucretleri)")
    y.add_argument("--gizli", action="store_true", help="Gizli (private) depo oluştur")
    y.add_argument("--deneme", action="store_true", help="Yalnızca kontrol ve tarama yap, hiçbir şey gönderme")
    y.add_argument("--yalnizca-ayarlar", action="store_true",
                   help="Kodu göndermeden anahtarları ve güvenlik ayarlarını yeniden uygula")
    y.set_defaults(func=cmd_yayinla)
    return p


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.ayrinti else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"Yapılandırma hatası: {exc}")
        return 2
    return args.func(args, cfg)
