"""Metinden bilgi ayıklama: Türkçe tarih-saat, TL tutarları, tarife PDF'leri, sayfa bağlantıları."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .guvenlik import safe_url
from .textutil import clean_spaces, fold
from .timeutil import TZ, aware

# ---------------------------------------------------------------------------
# Tarih ve saat
# ---------------------------------------------------------------------------

MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
}

_NUM_DATE = re.compile(r"(?<![\d.])(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)")
_TEXT_DATE = re.compile(
    r"(?<!\d)(\d{1,2})\s+(" + "|".join(MONTHS) + r")[a-z']*(?:\s+(\d{4}))?(?!\d)"
)
_DAY_WORDS = r"(?:pazartesi|sali|carsamba|persembe|cuma|cumartesi|pazar|gunu|tarihinde|tarihi|itibariyle|itibariyla|gece|aksami|sabahi)"
_TIME_AFTER = re.compile(
    r"(?:'[a-z]+)?[\s,]*(?:" + _DAY_WORDS + r"[\s,]+){0,3}(?:saat[\s:]*)?(\d{1,2})[.:](\d{2})(?!\d)"
)

_FROM_WORDS = re.compile(r"itibaren|gecerli|yururluge|uygulanacak|baslayarak")
_UNTIL_WORDS = re.compile(r"\bkadar\b|sona erecek|\bbitis")
_START_SUFFIX = re.compile(r"^'?(?:den|dan|ten|tan)\b|itibaren|baslayarak")


@dataclass
class FoundDate:
    dt: datetime
    has_time: bool
    start: int  # katlanmış metindeki konum
    end: int


def _infer_year(day: int, month: int, ref: datetime) -> int | None:
    """Yıl yazılmamışsa referans tarihe en yakın, geçmişte 60 günden eski olmayan yılı seçer."""
    best = None
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d < ref.date() - timedelta(days=60):
            continue
        if best is None or d < best:
            best = d
    return best.year if best else None


def _build(day: int, month: int, year: int, hour: int | None, minute: int | None) -> datetime | None:
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    if hour is None:
        return datetime.combine(d, time(0, 0), tzinfo=TZ)
    if hour == 24 and minute == 0:
        return datetime.combine(d + timedelta(days=1), time(0, 0), tzinfo=TZ)
    if hour > 23 or (minute or 0) > 59:
        return datetime.combine(d, time(0, 0), tzinfo=TZ)
    return datetime.combine(d, time(hour, minute or 0), tzinfo=TZ)


def find_dates(text: str, ref: datetime) -> tuple[list[FoundDate], str]:
    """Metindeki tarihleri (varsa saatleriyle) bulur. Katlanmış metni de döndürür."""
    t = fold(text)
    ref = aware(ref)
    found: list[FoundDate] = []
    spans: list[tuple[int, int]] = []

    def add(m: re.Match, day: int, month: int, year: int | None) -> None:
        if year is None:
            year = _infer_year(day, month, ref)
            if year is None:
                return
        tm = _TIME_AFTER.match(t, m.end())
        hour = minute = None
        end = m.end()
        if tm:
            hour, minute = int(tm.group(1)), int(tm.group(2))
            end = tm.end()
        dt = _build(day, month, year, hour, minute)
        if dt is None:
            return
        if any(s <= m.start() < e for s, e in spans):
            return
        spans.append((m.start(), end))
        found.append(FoundDate(dt=dt, has_time=hour is not None, start=m.start(), end=end))

    for m in _NUM_DATE.finditer(t):
        add(m, int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for m in _TEXT_DATE.finditer(t):
        add(m, int(m.group(1)), MONTHS[m.group(2)], int(m.group(3)) if m.group(3) else None)

    found.sort(key=lambda f: f.start)
    return found, t


def _tail(dates: list[FoundDate], i: int, t: str, width: int) -> str:
    """Bir tarihten sonraki metin; bir sonraki tarihe kadar (en çok width karakter)."""
    fd = dates[i]
    stop = fd.end + width
    if i + 1 < len(dates):
        stop = min(stop, dates[i + 1].start)
    return t[fd.end: stop]


def find_effective_from(text: str, ref: datetime) -> datetime | None:
    """"... tarihinden itibaren geçerlidir" gibi ifadelerdeki yürürlük anını bulur."""
    dates, t = find_dates(text, ref)
    for i, fd in enumerate(dates):
        if _FROM_WORDS.search(_tail(dates, i, t, 70)):
            return fd.dt
    return None


def find_window(text: str, ref: datetime) -> tuple[datetime | None, datetime | None]:
    """Ücretsiz geçiş gibi süreli kararlarda başlangıç ve bitiş anını bulur."""
    dates, t = find_dates(text, ref)
    if not dates:
        return None, None

    def end_of(fd: FoundDate) -> datetime:
        return fd.dt if fd.has_time else fd.dt + timedelta(hours=23, minutes=59, seconds=59)

    ends = [fd for i, fd in enumerate(dates) if _UNTIL_WORDS.search(_tail(dates, i, t, 40))]
    if ends:
        end_fd = ends[0]
        before = [(i, fd) for i, fd in enumerate(dates) if fd.start < end_fd.start]
        starts = [fd for i, fd in before if _START_SUFFIX.search(_tail(dates, i, t, 25).strip())]
        before = [fd for _, fd in before]
        pick = starts or before
        start = pick[-1].dt if pick else None
        return start, end_of(end_fd)
    if len(dates) >= 2:
        first = min(dates, key=lambda f: f.dt)
        last = max(dates, key=lambda f: f.dt)
        return first.dt, end_of(last)
    return dates[0].dt, None


# ---------------------------------------------------------------------------
# Tutarlar
# ---------------------------------------------------------------------------

_SPACES_RE = re.compile(r"\s+")
_TABLE_AMOUNT = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)[,.](\d{2})(?![\d])")
_UNIT_AFTER = re.compile(r"^\s*(?:m\b|m'|mt\b|metre|cm\b|mm\b|ton\b|kg\b|km\b|%|saat\b)")
_CELL_AMOUNT = re.compile(r"^(?:₺\s*)?(\d{1,3}(?:\.\d{3})+|\d+)[,.](\d{2})\s*(?:tl|₺)?$")


def to_decimal(int_part: str, dec_part: str | None) -> Decimal | None:
    try:
        value = Decimal(int_part.replace(".", "") + "." + (dec_part or "00"))
    except InvalidOperation:
        return None
    return value.quantize(Decimal("0.01"))


def amounts_in_line(line: str) -> list[Decimal]:
    """Satırdaki iki ondalıklı tutarlar (3,20 m gibi ölçüler hariç)."""
    out = []
    for m in _TABLE_AMOUNT.finditer(line):
        if _UNIT_AFTER.match(line[m.end():]):
            continue
        if m.start() > 0 and line[m.start() - 1] == "%":
            continue
        v = to_decimal(m.group(1), m.group(2))
        if v is not None:
            out.append(v)
    return out


def amount_from_cell(cell: str) -> Decimal | None:
    m = _CELL_AMOUNT.match(fold(cell))
    return to_decimal(m.group(1), m.group(2)) if m else None


# ---------------------------------------------------------------------------
# Tarife PDF'leri
# ---------------------------------------------------------------------------

_CLASS_START = re.compile(r"^\s*([1-6])(?:\s*[.\-)]\s*|\s+)(?:sinif\b)?")
_CLASS_CELL = re.compile(r"^([1-6])\s*(?:[.\-)])?\s*(?:sinif|sinifi)?\.?$")


@dataclass
class TariffParse:
    prices: dict[int, Decimal] = field(default_factory=dict)
    effective_from: datetime | None = None
    title: str = ""
    method: str = ""
    warnings: list[str] = field(default_factory=list)
    excerpt: str = ""
    text_hash: str = ""  # PDF metninin özeti: dosya yeniden kaydedilse bile metin aynıysa değişiklik sayılmaz

    @property
    def ok(self) -> bool:
        return len(self.prices) >= 3

    def to_json(self) -> dict:
        return {
            "prices": {str(k): str(v) for k, v in sorted(self.prices.items())},
            "effective_from": self.effective_from.isoformat(timespec="seconds") if self.effective_from else None,
            "title": self.title,
            "method": self.method,
            "warnings": self.warnings,
            "text_hash": self.text_hash,
        }


def class_prices_from_tables(tables: list[list[list[str | None]]]) -> dict[int, Decimal]:
    out: dict[int, Decimal] = {}
    for table in tables:
        for row in table or []:
            cells = [clean_spaces(c) for c in row if c is not None and clean_spaces(c)]
            if len(cells) < 2:
                continue
            m = _CLASS_CELL.match(fold(cells[0]))
            if not m:
                continue
            cls = int(m.group(1))
            if cls in out:
                continue
            for cell in cells[1:]:
                value = amount_from_cell(cell)
                if value is not None:
                    out[cls] = value
                    break
    return out


def class_prices_from_text(text: str) -> dict[int, Decimal]:
    """Tablo okunamazsa: sınıf numarasıyla başlayan satır bloklarındaki ilk tutar."""
    lines = [fold(line) for line in text.splitlines()]
    blocks: list[tuple[int, list[str]]] = []
    for line in lines:
        m = _CLASS_START.match(line)
        if m:
            blocks.append((int(m.group(1)), [line[m.end():]]))
        elif blocks and len(blocks[-1][1]) < 3:
            blocks[-1][1].append(line)
    out: dict[int, Decimal] = {}
    for cls, block_lines in blocks:
        if cls in out:
            continue
        for line in block_lines:
            amounts = amounts_in_line(line)
            if amounts:
                out[cls] = amounts[0]
                break
    return out


def check_class_prices(prices: dict[int, Decimal]) -> list[str]:
    warnings = []
    ordered = [prices[c] for c in range(1, 6) if c in prices]
    if any(b < a for a, b in zip(ordered, ordered[1:])):
        warnings.append("Sınıf ücretleri beklenen sırada değil (1→5 artan olmalı).")
    if 6 in prices and 1 in prices and prices[6] > prices[1]:
        warnings.append("6. sınıf (motosiklet) ücreti 1. sınıftan yüksek görünüyor.")
    if 1 not in prices:
        warnings.append("1. sınıf ücreti okunamadı.")
    return warnings


def parse_tariff_text(text: str, ref: datetime, tables: list | None = None) -> TariffParse:
    import hashlib

    result = TariffParse()
    lines = [clean_spaces(line) for line in text.splitlines() if clean_spaces(line)]
    result.title = lines[0] if lines else ""
    result.excerpt = " · ".join(lines[:3])[:300]
    result.text_hash = hashlib.sha256(fold(text).encode("utf-8")).hexdigest()[:16]
    prices = class_prices_from_tables(tables or [])
    result.method = "tablo"
    if len(prices) < 3:
        prices = class_prices_from_text(text)
        result.method = "metin"
    result.prices = prices
    result.effective_from = find_effective_from(text, ref)
    if not result.ok:
        result.warnings.append("Sınıf ücretleri okunamadı; PDF'i elle kontrol edin.")
    else:
        result.warnings.extend(check_class_prices(prices))
    if result.effective_from is None:
        result.warnings.append("Geçerlilik tarihi okunamadı.")
    return result


def parse_tariff_pdf(data: bytes, ref: datetime, max_pages: int = 5) -> TariffParse:
    import pdfplumber  # yavaş yüklenen bağımlılık, yalnızca gerektiğinde

    texts: list[str] = []
    tables: list = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:max_pages]:
            texts.append(page.extract_text() or "")
            try:
                tables.extend(page.extract_tables() or [])
            except Exception:  # bazı PDF'lerde tablo çıkarımı hata verebilir
                pass
    return parse_tariff_text("\n".join(texts), ref, tables)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

@dataclass
class Link:
    url: str
    text: str


def extract_links(html: str, base_url: str) -> list[Link]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    links: dict[str, Link] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        url = safe_url(urljoin(base_url, href))
        if not url:  # javascript:, data: vb. adresler hiçbir zaman kullanılmaz
            continue
        text = clean_spaces(a.get_text(" ")) or clean_spaces(a.get("title") or "")
        prev = links.get(url)
        if prev is None or len(text) > len(prev.text):
            links[url] = Link(url=url, text=text)
    return list(links.values())


_BLOCKS = ["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "div", "section", "article",
           "blockquote", "pre", "dd", "dt", "table", "ul", "ol", "br"]
_MARK = " "


def page_text(html: str, selector: str | None = None) -> str:
    """Sayfanın okunabilir metni. Her paragraf bir satır; paragraf içindeki satır sonları birleştirilir."""
    from bs4 import Comment

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "form", "aside"]):
        tag.decompose()
    root = None
    if selector:
        root = soup.select_one(selector)
    if root is None:
        root = soup.find("article") or soup.find("main") or soup.body or soup
    if root is None:
        return ""
    for s in list(root.find_all(string=True)):
        if isinstance(s, Comment):
            s.extract()
        else:
            s.replace_with(_SPACES_RE.sub(" ", str(s)))
    for tag in root.find_all(_BLOCKS):
        tag.insert_before(_MARK)
        tag.insert_after(_MARK)
    text = root.get_text(" ")
    lines = [clean_spaces(part) for part in text.split(_MARK)]
    return "\n".join(line for line in lines if line)


def same_site(url: str, base: str) -> bool:
    a, b = urlparse(url).netloc.lower(), urlparse(base).netloc.lower()
    a, b = a.removeprefix("www."), b.removeprefix("www.")
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")
