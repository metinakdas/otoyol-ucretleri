"use strict";

(function () {
  const TZ = "Europe/Istanbul";
  const fmtMoney = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDate = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", timeZone: TZ });
  const fmtShort = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", timeZone: TZ });
  const fmtShorter = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "short", timeZone: TZ });
  const fmtMonthYear = new Intl.DateTimeFormat("tr-TR", { month: "long", year: "numeric", timeZone: TZ });
  const fmtDateTime = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: TZ });
  const fmtYmd = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: TZ });
  const MONTHS = ["OCA", "ŞUB", "MAR", "NİS", "MAY", "HAZ", "TEM", "AĞU", "EYL", "EKİ", "KAS", "ARA"];
  const CLASSES = ["1", "2", "3", "4", "5", "6"];

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => (v == null ? "—" : fmtMoney.format(Number(v)) + " ₺");
  const date = (iso) => (iso ? fmtDate.format(new Date(iso)) : "belirsiz");
  const dateTime = (iso) => (iso ? fmtDateTime.format(new Date(iso)) : "belirsiz");
  const safeUrl = (url) => (typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url.trim()) ? url.trim() : null);
  const link = (url, label) => (safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : esc(label));
  const hesapApi = () => window.RadarHesap;
  const clsName = (k) => (hesapApi() ? hesapApi().className(k) : "");
  const className = (k) => `${k}. sınıf` + (clsName(k) ? " · " + clsName(k) : "");
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  const ICON = {
    kopru: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 16h18M5 16V9M19 16V9M5 9c3 4 11 4 14 0"/></svg>',
    tunel: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V12a8 8 0 0 1 16 0v7M4 19h16"/></svg>',
    cal: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>',
    bell: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/></svg>',
    x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  };
  // Köprü listesinde ad yanındaki kısa not (ücretin nasıl alındığı)
  const NOTE = {
    "15-temmuz-sehitler": "yalnız Avrupa → Asya", "fatih-sultan-mehmet": "yalnız Avrupa → Asya",
    "yavuz-sultan-selim": "KMO tarifesinde", "osmangazi": "Gebze–Bursa tarifesinde", "1915-canakkale": "Malkara–Çanakkale",
  };

  let data_ = null, now_ = new Date(), cls_ = "1";

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* tarayıcı depolaması kapalı olabilir */ }
    return null;
  }
  function dayDiff(iso, now) { return Math.round((Date.parse(fmtYmd.format(new Date(iso))) - Date.parse(fmtYmd.format(now))) / 86400000); }
  function ago(iso, now) {
    if (!iso) return "—";
    const m = (now - new Date(iso)) / 60000;
    if (m < 1) return "az önce";
    if (m < 60) return Math.round(m) + " dk önce";
    if (m < 1440) return Math.round(m / 60) + " sa önce";
    return Math.round(m / 1440) + " gün önce";
  }
  function inDays(iso, now) {
    const n = dayDiff(iso, now);
    return n > 1 ? n + " gün" : n === 1 ? "Yarın" : n === 0 ? "Bugün" : -n + " gün önce";
  }
  function names(data, ids) {
    const map = data.names || {};
    return (ids || []).map((x) => (typeof x === "string" ? map[x] || x : x.name)).join(", ");
  }
  async function fetchFirst(urls) {
    for (const url of urls) {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (res.ok) return await res.json();
      } catch (e) { /* sıradakini dene */ }
    }
    return null;
  }
  const sample = () => new URLSearchParams(location.search).has("ornek");
  const load = () => fetchFirst(sample() ? ["ornek-panel.json"] : ["data/panel.json", "../data/panel.json"]);
  const loadTable = () => fetchFirst(sample() ? ["ornek-ucret-tablosu.json"] : ["data/ucret-tablosu.json", "../data/ucret-tablosu.json"]);

  // ---------------------------------------------------------------- sekmeler (masaüstü sekme, telefon alt çubuk)

  function selectTab(name, focus) {
    document.querySelectorAll('.tabs [role="tab"]').forEach((t) => {
      const on = t.getAttribute("aria-controls") === "tab-" + name;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      if (on && focus) t.focus();
    });
    document.querySelectorAll("#tabbar [data-tab]").forEach((b) => {
      if (b.dataset.tab === name) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    const panel = $("#panel");
    if (panel) panel.querySelectorAll(".tab-panel").forEach((p) => { if (!p.hidden) p.scrollTop = 0; });
  }
  function bindTabs() {
    const tabs = [...document.querySelectorAll('.tabs [role="tab"]')];
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => selectTab(t.getAttribute("aria-controls").slice(4)));
      t.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
        selectTab(next.getAttribute("aria-controls").slice(4), true);
      });
    });
    $("#tabbar").addEventListener("click", (e) => {
      const b = e.target.closest("[data-tab]");
      if (!b) return;
      selectTab(b.dataset.tab);
      $("#panel").classList.remove("is-expanded");
    });
    $("#sheet-handle").addEventListener("click", () => {
      const p = $("#panel");
      p.classList.toggle("is-expanded");
      setTimeout(() => window.RadarMap && window.RadarMap.invalidate(), 240);
    });
  }

  // Sınıf seçimi hesap, köprü listesi ve harita arasında ortaktır.
  function setClassEverywhere(cls, from) {
    cls_ = cls;
    store("radar.sinif", cls);
    renderCrossings(data_, now_);
    if (from !== "hesap" && hesapApi()) hesapApi().setClass(cls);
    if (window.RadarMap) window.RadarMap.setClass(cls);
  }

  // ---------------------------------------------------------------- üst bilgi

  function renderStatus(data, now) {
    const enabled = data.sources.filter((s) => s.enabled);
    const failing = enabled.filter((s) => s.ok === false);
    const stale = data.last_run && now - new Date(data.last_run) > 6 * 3600 * 1000;
    const cls = failing.length ? "bad" : stale ? "warn" : "good";
    const text = failing.length ? `${failing.length} kaynak okunamıyor` : `Güncel · ${ago(data.last_run, now)}`;
    const title = `Son kontrol ${ago(data.last_run, now)} · ${failing.length ? failing.length + " kaynak okunamıyor; ücretler son doğrulanan tarifeden" : "tüm kaynaklar çalışıyor"}`;
    const el = $("#status");
    el.title = title;
    el.innerHTML = `<span class="dot ${cls}" aria-hidden="true"></span>${esc(text)}`;
    const m = $("#m-status");
    m.className = "m-status m-only " + (cls === "good" ? "" : cls);
    m.setAttribute("aria-label", text);
    m.title = title;
    $("#m-status-2").innerHTML = `<span class="dot ${cls}" aria-hidden="true"></span>${esc(text)}`;
  }

  // Yeni tarife dönemi geri sayımı (yılbaşı) ve varsa resmî olarak yayımlanmış yeni tarife
  function nextTariff(data, now) {
    const up = (data.upcoming || []).filter((u) => u.effective_from && dayDiff(u.effective_from, now) >= 0)
      .sort((a, b) => new Date(a.effective_from) - new Date(b.effective_from))[0];
    const cal = (data.calendar || []).find((p) => p.kind === "yilbasi" && dayDiff(p.end || p.start, now) >= 0);
    return { up, cal };
  }
  function renderCountdown(data, now) {
    const { up, cal } = nextTariff(data, now);
    const when = up ? up.effective_from : cal ? cal.start : null;
    const pill = $("#countdown"), chip = $("#m-countdown");
    if (!when) { pill.hidden = true; chip.hidden = true; return; }
    const n = dayDiff(when, now);
    const d = fmtShort.format(new Date(when));
    pill.hidden = false;
    pill.innerHTML = `${ICON.cal}${up ? "Yeni tarife" : "Yeni tarife dönemi"} ${esc(d)} · <b>${esc(n > 0 ? n + " gün" : "bugün")}</b>`;
    pill.setAttribute("aria-label", `${up ? "Yeni tarife" : "Yeni tarife dönemi"} ${d}, ${n} gün kaldı. Duyuruları aç`);
    chip.hidden = false;
    chip.innerHTML = `${esc(d)} · <b>${esc(n > 0 ? n + " gün" : "bugün")}</b>`;
    chip.setAttribute("aria-label", pill.getAttribute("aria-label"));
    pill.onclick = chip.onclick = () => selectTab("duyuru");
  }
  function upcomingText() {
    if (!data_) return "";
    const { up, cal } = nextTariff(data_, now_);
    if (up) return `Yeni tarife ${fmtShort.format(new Date(up.effective_from))} itibarıyla geçerli olacak.`;
    if (cal) return `Yeni tarife dönemi ${fmtShort.format(new Date(cal.start))}; tarife yayımlanınca yeni tutar burada görünür.`;
    return "";
  }

  // ---------------------------------------------------------------- duyurular

  function renderAnnouncements(data, now) {
    const items = [];
    (data.active_rules || []).forEach((r) => items.push({ cls: "free-rule", k: "Ücretsiz geçiş sürüyor", t: r.title,
      m: `${names(data, r.crossings)} · bitiş ${dateTime(r.valid_to)}`, cd: inDays(r.valid_to, now), tag: "ok", src: null }));
    (data.upcoming || []).forEach((u) => {
      const src = u.sources && u.sources[u.sources.length - 1];
      items.push({ cls: "change", k: "Yaklaşan değişiklik", t: u.title,
        m: `Yürürlük ${dateTime(u.effective_from)}${u.crossings.length ? " · " + names(data, u.crossings) : ""}`,
        cd: inDays(u.effective_from, now), tag: "warn", src });
    });
    $("#announcements").innerHTML = items.map((x) => `<div class="ann ${x.cls}">
      <div class="k"><span>${esc(x.k)}</span><span class="tag ${x.tag}">${esc(x.cd)}</span></div><div class="t">${esc(x.t)}</div>
      <div class="m">${esc(x.m)}${x.src ? " · " + link(x.src.url, x.src.publisher || "kaynak") : ""}</div></div>`).join("");
    ["#duyuru-badge", "#duyuru-badge-m"].forEach((id) => { const b = $(id); b.hidden = !items.length; b.textContent = items.length; });
    const n = $("#notice");
    if (!items.length) { n.hidden = true; return; }
    const top = items[0];
    n.hidden = false;
    n.innerHTML = `<span class="tag ${top.tag}">${esc(top.cd)}</span><span>${esc(top.t)}</span>`;
    n.onclick = () => selectTab("duyuru");
  }

  function renderPlate(data, now) {
    const { up, cal } = nextTariff(data, now);
    const when = up ? up.effective_from : cal ? cal.start : null;
    if (!when) { $("#cd-plate").innerHTML = ""; return; }
    const n = dayDiff(when, now);
    $("#cd-plate").innerHTML = `<div class="plate cd-plate"><div class="plate-in">
      <div class="cd-top"><div class="cd-l"><span class="cd-k">${up ? "Yeni tarife" : esc(cal.name.replace(/^\d{4}\s*/, "").replace(/^./, (c) => c.toLocaleUpperCase("tr")))}</span>
        <span class="cd-d">${esc(fmtDate.format(new Date(when)))}</span></div>
        <div class="cd-n"><b>${esc(Math.max(0, n))}</b><span>gün</span></div></div>
      <div class="cd-t">${up ? `${esc(up.title)}. Rotalarının yeni tutarı Rota sekmesinde görünür.` : "Yeni tarife henüz yayımlanmadı. Yayımlanınca rotalarının yeni tutarı burada görünür."}</div></div></div>`;
  }

  // Takvim: bayramlar (yılbaşı yukarıdaki plakada). Karar çıktıysa yeşil.
  function renderCalendar(data, now) {
    const { cal } = nextTariff(data, now);
    const rules = (data.next_rules || []).concat(data.active_rules || []);
    const list = (data.calendar || []).filter((p) => p !== cal && dayDiff(p.end || p.start, now) >= 0).slice(0, 4);
    $("#calendar-sec").hidden = !list.length;
    $("#calendar").innerHTML = list.map((p) => {
      const d = new Date(p.start);
      const [y, m, dd] = fmtYmd.format(d).split("-").map(Number);
      const decided = p.kind === "bayram" && rules.some((r) => r.valid_from && dayDiff(r.valid_from, new Date(p.start)) <= 3 && dayDiff(r.valid_from, new Date(p.start)) >= -3);
      const sub = p.kind === "bayram" ? (decided ? "Ücretsiz geçiş kararı çıktı" : "Ücretsiz geçiş kararı açıklanmadı") : "Ücret güncellemesi dönemi";
      return `<li><span class="cal-tile" aria-hidden="true"><b>${dd}</b><span>${MONTHS[m - 1]}</span></span>
        <span class="cal-t"><b>${esc(p.name.replace(/\s*\d{4}$/, ""))}</b><span class="${decided ? "ok" : ""}">${esc(sub)}</span></span>
        <span class="cal-n">${esc(inDays(p.start, now))}</span><span class="visually-hidden">${esc(fmtDate.format(d))} ${y}</span></li>`;
    }).join("");
  }

  function renderFree(data) {
    const parts = [];
    (data.active_rules || []).forEach((r) => parts.push(`<div class="ann free-rule"><div class="k"><span>Ücretsiz geçiş sürüyor</span><span class="tag ok">Bitiş ${esc(fmtShorter.format(new Date(r.valid_to)))}</span></div>
      <div class="t">${esc(r.title)}</div><div class="m">${esc(names(data, r.crossings))} · bitiş ${esc(dateTime(r.valid_to))}</div></div>`));
    (data.next_rules || []).forEach((r) => parts.push(`<div class="ann free-rule"><div class="k"><span>Karar çıktı</span><span class="tag ok">${esc(fmtShorter.format(new Date(r.valid_from)))}</span></div>
      <div class="t">${esc(r.title)}</div><div class="m">${esc(dateTime(r.valid_from))} – ${esc(dateTime(r.valid_to))} · ${esc(names(data, r.crossings))}</div></div>`));
    if (!parts.length) {
      parts.push(`<div class="empty-box">${ICON.bell}<div><b>Şu an yeni duyuru yok</b><span>KGM ve Bakanlık ${esc(data.run_interval_minutes || 30)} dakikada bir kontrol ediliyor</span></div></div>`);
    }
    $("#free").innerHTML = parts.join("");
  }

  function renderEvents(data, now) {
    const list = data.events || [];
    $("#events-fold").hidden = !list.length;
    $("#events-count").textContent = list.length ? String(Math.min(list.length, 8)) : "";
    $("#events").innerHTML = list.slice(0, 8).map((e) => {
      const src = e.sources && e.sources[e.sources.length - 1];
      const when = e.effective_from ? ` · yürürlük ${esc(date(e.effective_from))}` : "";
      const flags = (e.flags || []).filter((f) => f.id !== "takvim").map((f) => `<span class="chip ${f.id === "kacirildi" ? "bad" : ""}">${esc(f.label)}</span>`).join("");
      return `<li><div class="top"><span class="pill ${esc(e.status)}">${esc(e.status_label)}</span><span class="when">${esc(ago(e.updated_at, now))}</span></div>
        <div class="title">${src ? link(src.url, e.title) : esc(e.title)}</div>
        <div class="sub">${esc(e.kind_label)}${e.crossings.length ? " · " + esc(names(data, e.crossings)) : ""}${when}</div>${flags}</li>`;
    }).join("");
  }

  function renderTz(data, now) {
    const t = data.saat_dilimi;
    $("#tz-fold").hidden = !t;
    if (!t) return;
    const list = t.degisiklikler || [];
    $("#tz-v").textContent = list.length ? `${list.length} değişiklik` : "Değişiklik yok";
    $("#tz-list").innerHTML = (list.length ? list.map((c) => `<li><div class="top"><span class="title">IANA tzdata ${esc(c.iana)}</span><span class="when">${esc(ago(c.at, now))}</span></div>
        ${c.lines.map((l) => `<div class="sub">${esc(l)}</div>`).join("")}</li>`).join("")
      : `<li class="empty">Son sürümde gelecekteki saat farklarında değişiklik yok.</li>`)
      + `<li class="empty">IANA tzdata ${esc(t.iana || "?")} izleniyor · ${link(t.kaynak, "IANA duyuruları")}</li>`
      + `<li><button type="button" class="tz-all" data-tz-open>Tüm ülkeleri gör</button></li>`;
    document.querySelectorAll(".tz-btn").forEach((b) => { b.hidden = false; });
    const recent = list.some((c) => (now - new Date(c.at)) / 864e5 < 30);
    $("#tz-dot").hidden = !recent;
  }

  // ---------------------------------------------------------------- saat dilimleri penceresi (tüm ülkeler, arama)

  const TZW = { data: null, rows: [], filter: "all", timer: 0 };
  const AY = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
  const regionTr = (() => { try { return new Intl.DisplayNames(["tr"], { type: "region" }); } catch (e) { return null; } })();
  const tzFold = (s) => String(s || "").toLocaleLowerCase("tr").replace(/ı/g, "i").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const two = (n) => String(n).padStart(2, "0");
  const utcLabel = (sec) => `UTC${sec < 0 ? "−" : "+"}${two(Math.floor(Math.abs(sec) / 3600))}:${two(Math.floor((Math.abs(sec) % 3600) / 60))}`;
  const shifted = (ms, off) => new Date(ms + off * 1000);
  const clock = (ms, off) => { const d = shifted(ms, off); return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`; };
  const day = (ms, off) => { const d = shifted(ms, off); return `${d.getUTCDate()} ${AY[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  function tzAt(t, ms) {
    let v = t[0];
    for (const x of t) { if (Date.parse(x[0]) <= ms) v = x; else break; }
    return v;
  }
  function offsetKeys(o) {
    const sign = o < 0 ? "-" : "+", h = Math.abs(o) / 3600;
    return [utcLabel(o).replace("−", "-"), `utc${sign}${h}`, `gmt${sign}${h}`, `${sign}${h}`];
  }
  function tzBuild() {
    const names = TZW.data.ulkeler || {};
    const chg = (data_ && data_.saat_dilimi && data_.saat_dilimi.farklar) || {};
    TZW.rows = Object.entries(TZW.data.zones || {}).map(([zone, z]) => {
      const tr = regionTr ? regionTr.of(z.cc) : "";
      const en = names[z.cc] || z.cc;
      const name = tr && tr !== z.cc ? tr : en;
      const city = zone.split("/").pop().replace(/_/g, " ");
      const offs = [...new Set(z.t.map((x) => x[1]))];
      const c = chg[zone] || null;
      const keys = [name, en, zone.replace(/[_/]/g, " "), z.cc, ...offs.flatMap(offsetKeys), ...(c && c.eski != null ? offsetKeys(c.eski) : [])];
      return { zone, cc: z.cc, name, city, t: z.t, dst: z.t.some((x) => x[2]), chg: c, key: tzFold(keys.join(" ")) };
    }).sort((a, b) => (!!b.chg - !!a.chg) || a.name.localeCompare(b.name, "tr") || a.city.localeCompare(b.city, "tr"));
    const n = TZW.rows.filter((r) => r.chg).length;
    $("#tz-nchg").textContent = `(${n})`;
    $("#tz-sub").textContent = `IANA tzdata ${TZW.data.iana || "?"} · ${TZW.rows.length} bölge, ${new Set(TZW.rows.map((r) => r.cc)).size} ülke · saatler şu an`;
  }
  function tzRow(r, ms) {
    const cur = tzAt(r.t, ms), off = cur[1];
    const next = r.t.find((x) => Date.parse(x[0]) > ms);
    const sub = next ? `${day(Date.parse(next[0]), next[1])} → ${utcLabel(next[1])}${next[2] ? " (yaz saati)" : ""}` : "Yaz saati yok, sabit";
    const c = r.chg;
    const chg = c ? `<div class="tz-chg"><span class="tz-pill">Değişti · tzdata ${esc(c.iana)}</span>
        <span>${c.eski == null ? "Yeni bölge" : `Eski ${esc(utcLabel(c.eski))} → yeni <b>${esc(utcLabel(c.yeni))}</b>`}${c.tarih ? ` · ${esc(c.tarih)} itibarıyla` : ""}</span></div>` : "";
    return `<li class="tz-row${c ? " is-chg" : ""}">
      <div class="tz-main"><span class="tz-name">${esc(r.name)}</span><span class="tz-city">${esc(r.city)} · ${esc(r.zone)}</span></div>
      <div class="tz-off"><span class="tz-utc">${esc(utcLabel(off))}</span><span class="tz-time">${clock(ms, off)}${cur[2] ? " · yaz saati" : ""}</span></div>
      <div class="tz-next">${next ? "Sonraki geçiş: " : ""}${esc(sub)}</div>${chg}</li>`;
  }
  function tzRender() {
    const list = $("#tz-rows");
    if (!TZW.data) return;
    const ms = Date.now();
    const toks = tzFold($("#tz-q").value).split(/\s+/).filter(Boolean);
    const rows = TZW.rows.filter((r) => (TZW.filter !== "changed" || r.chg) && (TZW.filter !== "dst" || r.dst)
      && toks.every((t) => r.key.includes(t)));
    $("#tz-count").textContent = rows.length === TZW.rows.length ? `${rows.length} bölge` : `${TZW.rows.length} bölgeden ${rows.length} gösteriliyor`;
    list.innerHTML = rows.length ? rows.map((r) => tzRow(r, ms)).join("")
      : `<li class="tz-empty">${TZW.filter === "changed" && !toks.length ? "Son IANA sürümlerinde saat farkı değişen ülke yok." : "Eşleşen ülke ya da şehir yok."}</li>`;
  }
  async function tzOpen() {
    const dlg = $("#tz-dialog");
    if (!dlg.open) dlg.showModal();
    $("#tz-q").focus();
    if (!TZW.data) {
      $("#tz-rows").innerHTML = `<li class="tz-empty">Yükleniyor…</li>`;
      TZW.data = await fetchFirst(sample() ? [] : ["data/saat-dilimleri.json", "../data/saat-dilimleri.json"]);
      if (!TZW.data) { $("#tz-rows").innerHTML = `<li class="tz-empty">Saat dilimi verisi henüz yok; radarın ilk turundan sonra görünür.</li>`; return; }
      tzBuild();
    }
    tzRender();
    clearInterval(TZW.timer);
    TZW.timer = setInterval(tzRender, 30000);
  }
  function bindTz() {
    const dlg = $("#tz-dialog");
    document.addEventListener("click", (e) => { if (e.target.closest("[data-tz-open]")) tzOpen(); });
    dlg.addEventListener("click", (e) => { if (e.target === dlg || e.target.closest("[data-tz-close]")) dlg.close(); });
    dlg.addEventListener("close", () => clearInterval(TZW.timer));
    $("#tz-q").addEventListener("input", tzRender);
    dlg.querySelectorAll("[data-tzf]").forEach((b) => b.addEventListener("click", () => {
      TZW.filter = b.dataset.tzf;
      dlg.querySelectorAll("[data-tzf]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      tzRender();
    }));
  }

  function renderSources(data, now) {
    const enabled = data.sources.filter((s) => s.enabled);
    const failing = enabled.filter((s) => s.ok === false).length;
    const sum = $("#source-summary");
    sum.textContent = failing ? `${failing} sorunlu` : "Tümü okunuyor";
    sum.className = "fold-v " + (failing ? "bad" : "good");
    $("#sources").innerHTML = enabled.map((s) => `<li><span class="dot ${s.ok === true ? "good" : s.ok === false ? "bad" : ""}" aria-hidden="true"></span>
      <span>${link(s.url, s.name)}</span><span class="when">${esc(ago(s.last_success, now))}</span>
      ${s.ok === false ? `<span class="err">${esc((s.error || "").slice(0, 120))}</span>` : ""}</li>`).join("");
  }

  function renderDocuments(data) {
    const docs = data.documents || [];
    $("#doc-count").textContent = docs.length ? String(docs.filter((d) => !d.removed).length) : "";
    $("#documents").innerHTML = docs.length ? docs.map((d) => `<li class="${d.removed ? "removed" : ""}">
      <span>${link(d.url, d.title || d.key)}</span>
      <span class="sub">Geçerlilik ${esc(date(d.effective_from))}${d.error ? ` · <span class="chip bad">${esc(d.error)}</span>` : ""}</span></li>`).join("")
      : `<li class="empty">Henüz belge okunmadı.</li>`;
  }

  // ---------------------------------------------------------------- köprüler

  const shortName = (n) => String(n).replace(/\s+Köprüsü$/, "");
  function crossingDetail(c) {
    const cur = c.current && c.current.classes ? c.current.classes : {};
    const gece = c.current && c.current.gece && c.current.gece.classes ? c.current.gece : null;
    const up = c.upcoming && c.upcoming.classes ? c.upcoming : null;
    const partial = CLASSES.some((k) => cur[k] == null) && CLASSES.some((k) => cur[k] != null);
    const head = `<tr><th scope="col">Sınıf</th><th scope="col" class="now">${gece ? `Gündüz · şu an` : "Şu an"}</th>${gece ? `<th scope="col">Gece ${esc((gece.saat || "").replace("-", "–"))}</th>` : ""}${up ? `<th scope="col">${esc(fmtShorter.format(new Date(up.valid_from)))}</th>` : ""}</tr>`;
    const rows = [];
    for (let i = 0; i < CLASSES.length; i++) {
      const k = CLASSES[i];
      if (partial && cur[k] == null) {
        let j = i;
        while (j + 1 < CLASSES.length && cur[CLASSES[j + 1]] == null) j++;
        const label = j > i ? `${k}–${CLASSES[j]} · ${k === "3" && CLASSES[j] === "5" ? "Kamyon, otobüs" : CLASSES.slice(i, j + 1).map(clsName).join(", ")}` : `${k} · ${clsName(k)}`;
        rows.push(`<tr><th scope="row">${esc(label)}</th><td class="no" colspan="${1 + (gece ? 1 : 0) + (up ? 1 : 0)}"><span class="no-tag">Geçemez</span></td></tr>`);
        i = j;
        continue;
      }
      rows.push(`<tr><th scope="row">${esc(k)} · ${esc(clsName(k))}</th><td class="now">${cur[k] != null ? esc(fmtMoney.format(Number(cur[k]))) : "—"}</td>
        ${gece ? `<td>${gece.classes[k] != null ? esc(fmtMoney.format(Number(gece.classes[k]))) : "—"}</td>` : ""}${up ? `<td>${up.classes[k] != null ? esc(fmtMoney.format(Number(up.classes[k]))) : "—"}</td>` : ""}</tr>`);
    }
    const H = hesapApi();
    const canAdd = H && H.canAddExtra(c.id);
    const acts = [];
    if (canAdd) acts.push(H.hasExtra(c.id) ? `<button type="button" class="btn primary" data-goto-rota="1">Rotada ✓</button>` : `<button type="button" class="btn primary" data-add-extra="${esc(c.id)}">Rotaya ekle</button>`);
    if (c.konum) acts.push(`<button type="button" class="btn" data-map-focus="${esc(c.id)}">Haritada göster</button>`);
    if (c.current && safeUrl(c.current.source_url)) acts.push(`<a class="btn" href="${esc(safeUrl(c.current.source_url))}" target="_blank" rel="noopener noreferrer">Tarife ↗</a>`);
    const included = !canAdd && NOTE[c.id] && !/Avrupa/.test(NOTE[c.id]) ? `<p class="cr-note">Ücret otoyol gişe tarifesine dahildir; rotada otomatik hesaplanır.</p>` : "";
    return `<div class="cr-detail">
      <table class="cr-table"><thead>${head}</thead><tbody>${rows.join("")}</tbody></table>${included}
      <div class="cr-acts n${acts.length || 1}">${acts.join("")}</div></div>`;
  }

  function renderKClasses() {
    const H = hesapApi();
    if (!H) return;
    $("#k-veh-chip").innerHTML = H.clsChipHtml(cls_);
    $("#k-veh-chip").setAttribute("aria-label", `Araç: ${className(cls_)}. Değiştir`);
    $("#k-classes").innerHTML = H.clsGridHtml(cls_, "data-kcls");
  }

  function renderCrossings(data, now) {
    if (!data) return;
    renderKClasses();
    const list = data.crossings || [];
    if (!list.length) { $("#crossings").innerHTML = `<li><p class="empty pad">Henüz ücret kaydı yok.</p></li>`; return; }
    const open = $("#crossings").dataset.open || "";
    const vals = list.map((c) => (c.current && c.current.classes[cls_] != null ? Number(c.current.classes[cls_]) : null));
    const max = Math.max(1, ...vals.filter((v) => v != null));
    $("#crossings").innerHTML = list.map((c, i) => {
      const v = vals[i];
      let tag = "";
      if (c.free_now) tag = `<span class="tag ok">Ücretsiz</span>`;
      else if (c.upcoming) tag = `<span class="tag warn">Zam ${esc(fmtShorter.format(new Date(c.upcoming.valid_from)))}</span>`;
      const note = NOTE[c.id] || c.operator || "";
      const isOpen = open === c.id;
      return `<li class="${isOpen ? "is-open" : ""}"><button type="button" class="cr-row" data-id="${esc(c.id)}" aria-expanded="${isOpen}">
          <span class="nm">${esc(shortName(c.name))}${note ? ` <span class="nt">· ${esc(note)}</span>` : ""}</span>
          <span class="pr">${tag}${v != null ? esc(money(v)) : c.current ? `<span class="tag no">Geçemez</span>` : "—"}</span>
          <span class="bar" aria-hidden="true"><i data-w="${v != null ? Math.max(2, (v / max) * 100).toFixed(1) : 0}"></i></span>
        </button>${isOpen ? crossingDetail(c) : ""}</li>`;
    }).join("");
    // Çubuk genişlikleri (CSP satır içi stile izin vermez; CSSOM ile atanır)
    document.querySelectorAll("#crossings [data-w]").forEach((i) => { i.style.width = i.dataset.w + "%"; });
    const latest = list.map((c) => c.current && c.current.valid_from).filter(Boolean).sort().pop();
    $("#k-foot").textContent = `Çubuklar en pahalı geçişe göre ölçeklenir${latest ? " · " + fmtMonthYear.format(new Date(latest)) + " tarifesi" : ""}`;
  }

  function bindCrossings() {
    $("#crossings").addEventListener("click", (e) => {
      const f = e.target.closest("[data-map-focus]");
      if (f) {
        e.preventDefault();
        if (window.RadarMap) window.RadarMap.focusCrossing(f.dataset.mapFocus);
        $("#panel").classList.remove("is-expanded");
        return;
      }
      const a = e.target.closest("[data-add-extra]");
      if (a) { addExtra(a.dataset.addExtra); return; }
      if (e.target.closest("[data-goto-rota]")) { selectTab("rota"); return; }
      const row = e.target.closest(".cr-row");
      if (!row) return;
      const box = $("#crossings");
      box.dataset.open = box.dataset.open === row.dataset.id ? "" : row.dataset.id;
      renderCrossings(data_, now_);
      const again = document.querySelector(`.cr-row[data-id="${CSS.escape(row.dataset.id)}"]`);
      if (again) again.focus();
    });
    const chip = $("#k-veh-chip"), grid = $("#k-classes");
    chip.addEventListener("click", () => { grid.hidden = !grid.hidden; chip.setAttribute("aria-expanded", String(!grid.hidden)); });
    const pickK = (k, keep) => { setClassEverywhere(k); if (!keep) { grid.hidden = true; chip.setAttribute("aria-expanded", "false"); } };
    grid.addEventListener("click", (e) => { const b = e.target.closest("[data-kcls]"); if (b) pickK(b.dataset.kcls); });
    if (hesapApi()) hesapApi().radioKeys(grid, (k) => pickK(k, true), "data-kcls");
  }

  function openCrossing(id) {
    selectTab("kopru");
    $("#crossings").dataset.open = id;
    renderCrossings(data_, now_);
    const row = document.querySelector(`.cr-row[data-id="${CSS.escape(id)}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  function addExtra(id) {
    const H = hesapApi();
    if (!H) return;
    H.addExtra(id);
    selectTab("rota");
    renderCrossings(data_, now_);
  }

  // ---------------------------------------------------------------- harita araçları

  function bindMapTools(hesap) {
    const M = window.RadarMap;
    if (!M || !M.countsBy) return;
    const chips = $("#layer-chips");
    const SW = { kopru: ICON.kopru, gise: '<span class="sw-gate" aria-hidden="true"></span>', serbest: '<span class="sw-sgs" aria-hidden="true"></span>' };
    const layerHtml = (cls) => {
      const c = M.countsBy(), on = new Set(M.filter().types);
      return M.types().map(([t, label]) => `<button type="button" class="${cls}" data-type="${t}" aria-pressed="${on.has(t)}">
        ${SW[t]}${esc(label)}<span class="n">${c[t]}</span></button>`).join("");
    };
    const renderChips = () => { chips.innerHTML = layerHtml("layer-chip"); $("#fp-layers").innerHTML = layerHtml("fp-chip"); };
    const toggleType = (t) => {
      const on = new Set(M.filter().types);
      if (on.has(t)) on.delete(t); else on.add(t);
      M.setFilter({ types: [...on] });
      renderFilters();
    };
    chips.addEventListener("click", (e) => { const b = e.target.closest("[data-type]"); if (b) toggleType(b.dataset.type); });
    // Filtre penceresi: katmanlar, bölge, durum, il, otoyol. Seçenek sayıları diğer filtrelere göre hesaplanır.
    const roads = hesap ? hesap.roads() : [];
    const roadName = (id) => { const o = roads.find((r) => r.id === id); return o ? (o.yol ? o.yol + " · " : "") + (hesap ? hesap.roadShort(o) : o.ad) : id; };
    const DURUM = [["change", "Zammı yaklaşan"], ["free", "Ücretsiz geçiş"]];
    const pop = $("#filter-pop"), btn = $("#filter-btn");
    function renderFilters() {
      const f = M.filter(), o = M.options();
      $("#fp-bolge").innerHTML = o.regions.map((r) => {
        const n = o.bolge.get(r.id) || 0;
        return `<button type="button" class="fp-chip" data-bolge="${esc(r.id)}" aria-pressed="${f.bolge === r.id}" ${n || f.bolge === r.id ? "" : "disabled"}>${esc(r.ad)}<span class="n">${n}</span></button>`;
      }).join("");
      $("#fp-durum").innerHTML = DURUM.map(([id, label]) => {
        const n = o.durum.get(id) || 0;
        return `<button type="button" class="fp-chip" data-durum="${id}" aria-pressed="${f.durum === id}" ${n || f.durum === id ? "" : "disabled"}>${esc(label)}<span class="n">${n}</span></button>`;
      }).join("");
      const iller = [...o.il.keys()].concat(f.il && !o.il.has(f.il) ? [f.il] : []).sort((a, b) => a.localeCompare(b, "tr"));
      $("#f-il").innerHTML = `<option value="">Tüm iller</option>` + iller.map((il) => `<option value="${esc(il)}" ${il === f.il ? "selected" : ""}>${esc(il)} (${o.il.get(il) || 0})</option>`).join("");
      const rids = roads.map((r) => r.id).filter((id) => o.road.has(id) || id === f.road);
      $("#f-road").innerHTML = `<option value="">Tüm otoyollar</option>` + rids.map((id) => `<option value="${esc(id)}" ${id === f.road ? "selected" : ""}>${esc(roadName(id))} (${o.road.get(id) || 0})</option>`).join("");
      const active = [];
      if (f.bolge) active.push(["bolge", (o.regions.find((r) => r.id === f.bolge) || {}).ad || f.bolge]);
      if (f.il) active.push(["il", f.il]);
      if (f.road) active.push(["road", roadName(f.road)]);
      if (f.durum) active.push(["durum", (DURUM.find((d) => d[0] === f.durum) || [])[1]]);
      $("#active-filters").innerHTML = active.map(([k, label]) => `<button type="button" class="af-chip" data-clear="${k}" aria-label="${esc(label)} filtresini kaldır">${esc(label)}${ICON.x}</button>`).join("");
      const hiddenLayers = 3 - f.types.length;
      const n = active.length + hiddenLayers;
      $("#filter-count").hidden = !n;
      $("#filter-count").textContent = n;
      btn.classList.toggle("is-on", n > 0);
      renderChips();
    }
    const apply = (f) => { M.setFilter(f); renderFilters(); };
    const openPop = (open) => { pop.hidden = !open; btn.setAttribute("aria-expanded", String(open)); if (open) renderFilters(); };
    btn.addEventListener("click", () => openPop(pop.hidden));
    $("#fp-close").addEventListener("click", () => openPop(false));
    $("#fp-clear").addEventListener("click", () => apply({ bolge: "", il: "", road: "", durum: "", types: ["kopru", "gise", "serbest"], reset: true }));
    pop.addEventListener("click", (e) => {
      const t = e.target.closest("[data-type]");
      if (t) { toggleType(t.dataset.type); return; }
      const b = e.target.closest("[data-bolge]");
      if (b && !b.disabled) { const f = M.filter(); apply({ bolge: f.bolge === b.dataset.bolge ? "" : b.dataset.bolge, il: "", reset: true }); return; }
      const d = e.target.closest("[data-durum]");
      if (d && !d.disabled) { const f = M.filter(); apply({ durum: f.durum === d.dataset.durum ? "" : d.dataset.durum, reset: true }); }
    });
    $("#f-il").addEventListener("change", (e) => apply({ il: e.target.value, reset: true }));
    $("#f-road").addEventListener("change", (e) => apply({ road: e.target.value, reset: true }));
    $("#active-filters").addEventListener("click", (e) => {
      const c = e.target.closest("[data-clear]");
      if (c) apply({ [c.dataset.clear]: "", reset: true });
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { openPop(false); btn.focus(); } });
    document.addEventListener("click", (e) => { if (!pop.hidden && e.target.isConnected && !pop.contains(e.target) && !btn.contains(e.target)) openPop(false); });
    renderFilters();

    // Arama: yazdıkça en fazla 8 sonuç; seçilen noktaya gidilir ve açılır pencere açılır.
    const q = $("#map-q"), list = $("#map-q-list");
    let items = [], active = -1;
    const KIND = (x) => (x.type === "kopru" ? `<span class="mk-bridge">${(M.icons || {})[x.kind] || ICON.kopru}</span>` : x.type === "serbest" ? '<span class="mk-sgs flat"></span>' : '<span class="lg-gate"></span>');
    const close = () => { list.hidden = true; q.setAttribute("aria-expanded", "false"); q.removeAttribute("aria-activedescendant"); };
    const render = () => {
      if (!q.value.trim()) { close(); return; }
      list.innerHTML = items.length ? items.map((x, i) => `<li role="option" class="opt" id="mq-${i}" data-id="${esc(x.id)}" aria-selected="${i === active}">
        <span class="o-kind" aria-hidden="true">${KIND(x)}</span><span class="o-t"><span class="o-name">${esc(x.name)}</span><span class="o-sub">${esc(x.sub || "")}</span></span></li>`).join("")
        : `<li class="o-empty">Sonuç yok</li>`;
      list.hidden = false;
      q.setAttribute("aria-expanded", "true");
      if (active >= 0) q.setAttribute("aria-activedescendant", "mq-" + active);
    };
    const go = (id) => { close(); q.blur(); M.focusPoint(id); renderFilters(); };
    q.addEventListener("input", () => { items = M.search(q.value); active = -1; render(); });
    q.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(items.length - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") { e.preventDefault(); const x = items[active >= 0 ? active : 0]; if (x) go(x.id); }
      else if (e.key === "Escape") { q.value = ""; close(); }
    });
    q.addEventListener("blur", () => setTimeout(close, 120));
    list.addEventListener("mousedown", (e) => e.preventDefault());
    list.addEventListener("click", (e) => { const li = e.target.closest("[data-id]"); if (li) go(li.dataset.id); });
    // "/" kısayolu: haritada ara
    document.addEventListener("keydown", (e) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      e.preventDefault();
      q.focus();
    });
  }

  // İpucu balonu: ilk açılışta; kapatılınca bu cihazda bir daha gösterilmez.
  function bindHint() {
    const hint = $("#map-hint");
    const dismissed = () => store("radar.ipucu") === "1";
    hint.hidden = dismissed();
    $("#map-hint-close").addEventListener("click", () => { store("radar.ipucu", "1"); hint.hidden = true; });
    return (st) => { hint.hidden = dismissed() || st.hasAny; };
  }

  // ---------------------------------------------------------------- tema (açık varsayılan; seçim bu cihazda)

  function bindTheme() {
    const sync = () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark";
      document.querySelectorAll("[data-theme-toggle]").forEach((b) => {
        b.setAttribute("aria-label", dark ? "Açık temaya geç" : "Koyu temaya geç");
        b.title = b.getAttribute("aria-label");
      });
      const m = $("#theme-color");
      if (m) m.setAttribute("content", dark ? "#0f1916" : "#ffffff");
    };
    document.addEventListener("click", (e) => {
      const b = e.target.closest("[data-theme-toggle]");
      if (!b) return;
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      store("radar.tema", next);
      sync();
      window.dispatchEvent(new Event("radar-theme"));
    });
    sync();
  }

  // ---------------------------------------------------------------- başlatma

  async function main() {
    bindTheme();
    bindTz();
    bindTabs();
    const [data, table] = await Promise.all([load(), loadTable()]);
    if (!data) {
      $("#app").insertAdjacentHTML("beforeend", $("#error-tpl").innerHTML);
      $(".panel").hidden = true;
      $("#status").textContent = "Veri yok";
      return;
    }
    data_ = data;
    now_ = new Date();
    const saved = store("radar.sinif");
    cls_ = CLASSES.includes(saved) ? saved : "1";
    $("#sample-note").hidden = !data.ornek;
    renderStatus(data, now_);
    renderCountdown(data, now_);
    renderAnnouncements(data, now_);
    renderPlate(data, now_);
    renderFree(data);
    renderCalendar(data, now_);
    renderEvents(data, now_);
    renderTz(data, now_);
    renderSources(data, now_);
    renderDocuments(data);
    $("#footer").textContent = `Kaynak: KGM resmî tarifeleri · ${data.run_interval_minutes || 30} dakikada bir kontrol edilir.`;

    const regions = new Map((data.bolgeler || []).map((r) => [r.id, r.ad]));
    const helpers = { esc, money, date, dateTime, className, regionName: (id) => regions.get(id) || id, upcomingText };
    const hesap = window.RadarHesap;
    const onHint = bindHint();
    if (hesap) {
      try {
        const r = hesap.init({ table, crossings: data.crossings, helpers, cls: cls_, map: window.RadarMap,
          onClass: (c) => setClassEverywhere(c, "hesap"), onChange: (st) => onHint(st) });
        if (r.fromHash) selectTab("rota");
      } catch (e) { console.error("Ücret hesabı açılamadı", e); }
    }
    bindCrossings();
    renderCrossings(data, now_);
    if (window.RadarMap) {
      try {
        window.RadarMap.init({
          data, cls: cls_, helpers,
          stations: hesap ? hesap.allStations() : [],
          roads: hesap ? hesap.roads() : [],
          onShowCrossing: openCrossing,
          onAddExtra: addExtra,
          canAddExtra: (id) => !!(hesap && hesap.canAddExtra(id)),
          popupExtra: (p) => (hesap ? hesap.popupHtml(p) : ""),
          onTrip: (role, key) => { selectTab("rota"); if (hesap) hesap.pick(role, key); },
        });
        if (hesap) hesap.redraw();
        bindMapTools(hesap);
      } catch (e) { console.error("Harita açılamadı", e); }
    }
    $("#m-back").addEventListener("click", () => { if (hesap) hesap.reset(); });
    // Paylaşılan bir hesap bağlantısı aynı sekmede açılırsa (yalnızca # değişir) hesap yenilenir.
    window.addEventListener("hashchange", () => { if (hesap) { hesap.reload(); selectTab("rota"); } });
  }

  main();
})();
