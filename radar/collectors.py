"""Kaynak toplayıcıları. Her biri kaynağın önceki durumunu (state) alır, yeni durumu yazar
ve bulduğu değişiklikleri aday kayıt (Candidate) olarak döndürür.

İlk çalıştırmada kaynaklar yalnızca "başlangıç" olarak kaydedilir; bildirim üretilmez.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import prices as ledger
from .config import Config, CrossingCfg, Source
from .extract import (
    Link,
    TariffParse,
    domain_of,
    extract_links,
    find_effective_from,
    find_window,
    page_text,
    parse_tariff_pdf,
    same_site,
)
from .fetch import Fetcher
from .guvenlik import redact, safe_url
from .matching import KIND_FREE, KIND_PRICE, Matcher, best_quote
from .models import Candidate
from .textutil import clean_spaces, fold, short_hash, shorten, slugify
from .timeutil import TZ, from_iso, hours_since, to_iso

log = logging.getLogger(__name__)

PDF_RE = re.compile(r"\.pdf(?:$|[?#])", re.IGNORECASE)
_LEADING_NUM = re.compile(r"^\s*\d+\s*[-.)]\s*")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# Haber listelerinde başlığın başında/sonunda duran yayın tarihi (ör. "... olacak 20.04.2027")
_EDGE_DATE = re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]\d{4}[\s\-–|·]*|[\s\-–|·]*\d{1,2}[./]\d{1,2}[./]\d{4}\s*$")


def clean_title(text: str) -> str:
    return clean_spaces(_EDGE_DATE.sub("", text)) or clean_spaces(text)


class CollectError(Exception):
    pass


@dataclass
class Context:
    cfg: Config
    matcher: Matcher
    fetcher: Fetcher
    now: datetime
    crossings_data: dict
    notes: list[str] = field(default_factory=list)


@dataclass
class CollectResult:
    candidates: list[Candidate]
    info: str = ""
    details: dict = field(default_factory=dict)


def collect(src: Source, st: dict, ctx: Context) -> CollectResult:
    handler = {
        "tarife_listesi": collect_tarife_listesi,
        "liste": collect_liste,
        "rss": collect_rss,
        "sayfa": collect_sayfa,
    }[src.type]
    return handler(src, st, ctx)


# ---------------------------------------------------------------------------
# KGM tarife PDF listesi
# ---------------------------------------------------------------------------

def doc_key(link: Link) -> str:
    """Belge kimliği: bağlantı metninden (sıra numarası ve yıl atılarak). Yıl değişse de aynı kalır."""
    text = _YEAR.sub("", _LEADING_NUM.sub("", link.text))
    if len(clean_spaces(text)) >= 6:
        return slugify(text, 70)
    name = link.url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return slugify(_YEAR.sub("", _LEADING_NUM.sub("", name)), 70)


def _parse_targets(mapped: list[CrossingCfg]) -> list[CrossingCfg]:
    return [c for c in mapped if c.parse == "sinif_tablosu"]


def _ensure_baseline(ctx: Context, mapped: list[CrossingCfg], parsed: dict | None, url: str) -> None:
    """Henüz ücret kaydı olmayan geçişler için PDF'teki ücretleri başlangıç olarak yazar (bildirimsiz)."""
    if not parsed or len(parsed.get("prices") or {}) < 3:
        return
    eff = from_iso(parsed.get("effective_from")) or ctx.now
    for c in _parse_targets(mapped):
        if not ledger.entries(ctx.crossings_data, c.id):
            ledger.add_entry(ctx.crossings_data, c.id, c.name, eff, parsed["prices"],
                             source_url=url, note="Başlangıç kaydı (KGM tarifesi)")
            ctx.notes.append(f"Başlangıç ücreti kaydedildi: {c.name}")


def _is_tariff(text: str | None, url: str | None) -> bool:
    """Ücret tarifesi belgesi mi? (KGM sayfasında strateji planı, trafik standartları gibi başka PDF'ler de var.)"""
    t = fold(text)
    return "ucret" in t or "tarife" in t or "ucret" in (url or "").lower()


def collect_tarife_listesi(src: Source, st: dict, ctx: Context) -> CollectResult:
    res = ctx.fetcher.get(src.url)
    links = [l for l in extract_links(res.text, res.final_url) if PDF_RE.search(l.url) and _is_tariff(l.text, l.url)]
    if not links:
        raise CollectError("Sayfada PDF tarife bağlantısı bulunamadı; sayfa yapısı değişmiş olabilir.")

    docs: dict = st.setdefault("docs", {})
    for key in [k for k, d in docs.items() if not _is_tariff(d.get("title"), d.get("url"))]:
        del docs[key]  # önceki sürümün kaydettiği ilgisiz belgeler
    first_run = not docs
    present: set[str] = set()
    changed: list[tuple[Link, str, list[CrossingCfg], TariffParse | None]] = []

    for link in links:
        key = doc_key(link)
        if key in present:
            continue
        present.add(key)
        prev = docs.get(key)
        mapped = ctx.matcher.crossings_for_document(link.text, link.url)
        same_url = bool(prev) and prev.get("url") == link.url
        if same_url and hours_since(prev.get("checked_at"), ctx.now) < ctx.cfg.settings.doc_recheck_hours:
            _ensure_baseline(ctx, mapped, prev.get("parsed"), link.url)
            continue

        entry = dict(prev or {})
        entry.update({
            "title": link.text,
            "url": link.url,
            "checked_at": to_iso(ctx.now),
            "crossings": [c.id for c in mapped],
        })
        entry.pop("removed_at", None)
        try:
            r = ctx.fetcher.get(
                link.url,
                etag=prev.get("etag") if same_url else None,
                last_modified=prev.get("last_modified") if same_url else None,
            )
        except Exception as exc:  # tek bir PDF'in hatası tüm kaynağı durdurmasın
            entry["error"] = redact(exc)[:300]
            docs[key] = entry
            ctx.notes.append(f"Tarife belgesi indirilemedi: {link.text} ({exc})")
            continue
        entry.pop("error", None)
        if r.not_modified:
            docs[key] = entry
            _ensure_baseline(ctx, mapped, entry.get("parsed"), link.url)
            continue
        if not r.is_pdf:
            entry["error"] = "Bağlantı PDF döndürmedi"
            docs[key] = entry
            continue

        entry["etag"] = r.headers.get("etag")
        entry["last_modified"] = r.headers.get("last-modified")
        entry["sha256"] = hashlib.sha256(r.content).hexdigest()[:32]
        try:
            parsed = parse_tariff_pdf(r.content, ctx.now)
        except Exception as exc:
            parsed = None
            entry["parse_error"] = redact(exc)[:300]

        new_text_hash = parsed.text_hash if parsed else entry["sha256"]
        is_change = prev is None or prev.get("text_hash") != new_text_hash
        entry["text_hash"] = new_text_hash
        if parsed:
            entry["parsed"] = parsed.to_json()
            entry["effective_from"] = to_iso(parsed.effective_from)
        if is_change:
            entry["changed_at"] = to_iso(ctx.now)
        docs[key] = entry

        if first_run:
            _ensure_baseline(ctx, mapped, entry.get("parsed"), link.url)
        elif is_change:
            changed.append((link, key, mapped, parsed))

    if not first_run:
        for key, d in docs.items():
            if key not in present and not d.get("removed_at"):
                d["removed_at"] = to_iso(ctx.now)
                ctx.notes.append(f"Tarife belgesi listeden kaldırıldı: {d.get('title')}")

    info = f"{len(present)} tarife belgesi" + (" (başlangıç kaydı)" if first_run else f", {len(changed)} değişiklik")
    candidates = _tariff_candidates(src, ctx, changed)
    return CollectResult(candidates, info, {"docs": sorted(present)})


def _tariff_candidates(src: Source, ctx: Context, changed) -> list[Candidate]:
    """Değişen belgeleri yürürlük tarihine göre gruplayıp her grup için tek aday üretir."""
    groups: dict[str | None, list] = defaultdict(list)
    for item in changed:
        parsed = item[3]
        eff = parsed.effective_from if parsed else None
        groups[to_iso(eff)].append(item)

    out: list[Candidate] = []
    for eff_iso, items in groups.items():
        eff = from_iso(eff_iso)
        prices: dict[str, dict[str, str]] = {}
        crossings: list[str] = []
        flags: list[str] = []
        documents: list[str] = []
        titles: list[str] = []
        quote = ""
        for link, key, mapped, parsed in items:
            targets = _parse_targets(mapped)
            if targets:
                if parsed and parsed.ok:
                    classes = {str(k): str(v) for k, v in parsed.prices.items()}
                    real_change = False
                    for c in targets:
                        at = eff or ctx.now
                        existing = ledger.entry_at(ctx.crossings_data, c.id, at) or ledger.latest_entry(ctx.crossings_data, c.id)
                        if existing and ledger.same_classes(existing["classes"], classes):
                            continue
                        prices[c.id] = classes
                        crossings.append(c.id)
                        real_change = True
                    if not real_change:
                        ctx.notes.append(f"Belge yenilenmiş ama ücretler aynı: {link.text}")
                        continue
                    if [w for w in parsed.warnings if "tarih" not in w]:
                        flags.append("kontrol_et")
                    quote = quote or parsed.excerpt
                else:
                    flags.append("degerler_okunamadi")
                    crossings.extend(c.id for c in targets)
            else:
                crossings.extend(c.id for c in mapped)
            documents.append(key)
            titles.append(link.text)

        if not documents:
            continue
        if eff is None:
            flags.append("tarih_belirsiz")
        title = (
            f"KGM tarifesi değişti: {titles[0]}" if len(titles) == 1
            else f"KGM geçiş ücreti tarifeleri güncellendi ({len(titles)} belge)"
        )
        out.append(Candidate(
            kind=KIND_PRICE,
            title=title,
            source_id=src.id,
            tier=src.tier,
            url=items[0][0].url if len(items) == 1 else src.url,
            publisher=domain_of(src.url),
            crossings=list(dict.fromkeys(crossings)),
            quote=quote or shorten("; ".join(titles), 280),
            prices=prices,
            effective_from=eff,
            flags=list(dict.fromkeys(flags)),
            documents=documents,
        ))
    return out


# ---------------------------------------------------------------------------
# Duyuru ve haber listeleri, RSS
# ---------------------------------------------------------------------------

def _candidate_from_item(
    src: Source,
    ctx: Context,
    *,
    title: str,
    url: str,
    detail: str = "",
    published: datetime | None = None,
    publisher: str | None = None,
) -> Candidate | None:
    title_cls = ctx.matcher.classify(title, src.crossings)
    if title_cls is None:
        return None
    full = title + "\n" + detail
    cls = ctx.matcher.classify(full, src.crossings) or title_cls
    kind = title_cls.kind or cls.kind
    cancel = title_cls.cancel  # iptal yalnızca başlıktan okunur
    if kind is None and not cancel:
        return None

    flags: list[str] = []
    excluded = cls.excluded
    # "... hariç" cümlesinde geçen adlar kapsam sayılmaz
    named = [c for c in (title_cls.crossings or cls.crossings) if c not in excluded]
    crossings = named or list(src.crossings)
    generic = False
    if not crossings and (cls.generic or title_cls.generic):
        crossings = list(ctx.cfg.generic_scope)
        generic = True
        flags.append("kapsam_kontrol")
    crossings = [c for c in crossings if c not in excluded]

    eff_from = eff_to = None
    if kind == KIND_FREE:
        eff_from, eff_to = find_window(full, ctx.now)
    elif kind == KIND_PRICE:
        eff_from = find_effective_from(full, ctx.now)
    stale = ctx.now - timedelta(days=60)
    if eff_from and eff_from < stale:
        eff_from = None
    if eff_to and eff_to < stale:
        eff_to = None
    if kind and not cancel and eff_from is None:
        flags.append("tarih_belirsiz")
    if kind == KIND_PRICE and not cancel:
        flags.append("degerler_okunamadi")

    return Candidate(
        kind=kind or "",
        title=shorten(title, 160),
        source_id=src.id,
        tier=src.tier,
        url=url,
        publisher=publisher or domain_of(url),
        crossings=crossings,
        generic=generic,
        cancel=cancel,
        quote=best_quote(full),
        published=to_iso(published),
        effective_from=eff_from,
        effective_to=eff_to,
        excluded=excluded,
        flags=flags,
    )


def collect_liste(src: Source, st: dict, ctx: Context) -> CollectResult:
    res = ctx.fetcher.get(src.url)
    base = src.url.rstrip("/")
    items = [
        l for l in extract_links(res.text, res.final_url)
        if len(l.text) >= 25 and same_site(l.url, src.url) and l.url.rstrip("/") != base
    ]
    if not items:
        raise CollectError("Sayfada başlık bulunamadı; sayfa yapısı değişmiş olabilir.")

    seen: list[str] = st.setdefault("seen", [])
    seen_set = set(seen)
    first_run = not seen
    candidates: list[Candidate] = []
    new_count = 0
    for item in items:
        h = short_hash(item.url)
        if h in seen_set:
            continue
        seen.append(h)
        seen_set.add(h)
        new_count += 1
        if first_run:
            continue
        if ctx.matcher.classify(item.text, src.crossings) is None:
            continue
        detail = ""
        try:
            r = ctx.fetcher.get(item.url)
            if not r.is_pdf:
                detail = page_text(r.text)[:30000]
        except Exception as exc:
            ctx.notes.append(f"Ayrıntı sayfası okunamadı: {item.url} ({exc})")
        cand = _candidate_from_item(src, ctx, title=clean_title(item.text), url=item.url, detail=detail)
        if cand:
            candidates.append(cand)

    st["seen"] = seen[-2000:]
    st["last_items"] = [{"title": shorten(l.text, 140), "url": l.url} for l in items[:8]]
    info = f"{len(items)} başlık" + (" (başlangıç kaydı)" if first_run else f", {new_count} yeni, {len(candidates)} ilgili")
    return CollectResult(candidates, info)


def collect_rss(src: Source, st: dict, ctx: Context) -> CollectResult:
    import feedparser

    res = ctx.fetcher.get(src.url)
    feed = feedparser.parse(res.content)
    if not feed.entries:
        if getattr(feed, "bozo", False):
            raise CollectError("RSS okunamadı (geçersiz biçim).")
        return CollectResult([], "RSS boş")

    seen: list[str] = st.setdefault("seen", [])
    seen_set = set(seen)
    first_run = not seen
    candidates: list[Candidate] = []
    cutoff = ctx.now - timedelta(days=30)
    for entry in feed.entries:
        uid = entry.get("id") or entry.get("link") or entry.get("title", "")
        h = short_hash(uid)
        if h in seen_set:
            continue
        seen.append(h)
        seen_set.add(h)
        if first_run:
            continue
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone(TZ)
            if published < cutoff:
                continue
        title = clean_spaces(entry.get("title", ""))
        summary = page_text(entry.get("summary", "")) if entry.get("summary") else ""
        source = entry.get("source") or {}
        publisher = source.get("title") if hasattr(source, "get") else None
        if not publisher and " - " in title:
            publisher = title.rsplit(" - ", 1)[1]
        cand = _candidate_from_item(
            src, ctx, title=title, url=safe_url(entry.get("link")) or src.url, detail=summary,
            published=published, publisher=publisher,
        )
        if cand:
            candidates.append(cand)
    st["seen"] = seen[-2000:]
    info = f"{len(feed.entries)} haber" + (" (başlangıç kaydı)" if first_run else f", {len(candidates)} ilgili")
    return CollectResult(candidates, info)


def collect_sayfa(src: Source, st: dict, ctx: Context) -> CollectResult:
    res = ctx.fetcher.get(src.url)
    text = page_text(res.text, src.selector)
    digest = short_hash(fold(text), 16)
    prev = st.get("hash")
    st["hash"] = digest
    if prev is None or prev == digest:
        return CollectResult([], "değişiklik yok" if prev else "başlangıç kaydı")
    cand = Candidate(
        kind=KIND_PRICE,
        title=f"{src.name} değişti",
        source_id=src.id,
        tier=src.tier,
        url=src.url,
        publisher=domain_of(src.url),
        crossings=list(src.crossings),
        quote=shorten(text, 200),
        flags=["kontrol_et", "degerler_okunamadi", "tarih_belirsiz"],
    )
    return CollectResult([cand], "sayfa değişti")
