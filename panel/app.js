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
      if (window.RadarSheet && window.RadarSheet.state() === "is-collapsed") window.RadarSheet.set(1);
    });
    bindSheet();
  }

  // Telefonda alt panel üç konumda durur: kapalı (yalnızca başlık), orta, tam. Panel parmağı iki yönde de
  // izler; bırakınca hıza ya da en yakın konuma göre yerine oturur. Tutamaç ve başlıktan her zaman, içerikten
  // ise en üstteyken aşağı çekerek (ya da sığmıyorsa yukarı iterek) sürüklenir. Animasyon gerçek yükseklik
  // üzerindendir; max-height geçişindeki "boşta bekleme" yoktur.
  function bindSheet() {
    const p = $("#panel"), h = $("#sheet-handle");
    const mobile = window.matchMedia("(max-width: 900px)");
    const CLS = ["is-collapsed", "", "is-expanded"];
    const cur = () => (p.classList.contains("is-expanded") ? 2 : p.classList.contains("is-collapsed") ? 0 : 1);
    const classes = (n) => {
      p.classList.toggle("is-expanded", n === 2);
      p.classList.toggle("is-collapsed", n === 0);
    };
    // Her konumun CSS'teki gerçek yüksekliği (içerik kısaysa orta ile tam aynı olabilir)
    const heights = () => {
      const n = cur(), inline = p.style.height;
      const had = ["is-measuring", "is-dragging", "is-snapping"].filter((c) => p.classList.contains(c));
      p.classList.remove("is-dragging", "is-snapping");
      p.classList.add("is-measuring");
      p.style.height = "";
      const out = [0, 1, 2].map((i) => { classes(i); return p.offsetHeight; });
      classes(n);
      p.style.height = inline;
      p.classList.remove("is-measuring");
      p.classList.add(...had);
      return out;
    };
    let anim = 0;
    const set = (n, fromH) => {
      n = Math.max(0, Math.min(2, n));
      if (!mobile.matches || p.classList.contains("is-search")) { classes(n); return; }
      const hs = heights();
      const start = fromH != null ? fromH : p.offsetHeight;
      clearTimeout(anim);
      p.classList.add("is-measuring");      // geçişsiz: başlangıç yüksekliğine sabitle
      p.style.height = start + "px";
      classes(n);
      h.setAttribute("aria-expanded", String(n > 0));
      void p.offsetHeight;
      p.classList.remove("is-measuring");
      p.classList.add("is-snapping");
      p.style.height = hs[n] + "px";
      const done = () => {
        clearTimeout(anim);
        p.removeEventListener("transitionend", onEnd);
        p.classList.remove("is-snapping");
        p.style.height = "";
        if (window.RadarMap) window.RadarMap.invalidate();
      };
      const onEnd = (e) => { if (e.target === p && e.propertyName === "height") done(); };
      p.addEventListener("transitionend", onEnd);
      anim = setTimeout(done, Math.abs(hs[n] - start) < 2 ? 0 : 400);
    };
    // Dokunma: tutamak bir üst konuma (en üstteyse ortaya); kapalıyken başlık açar
    const tapHandle = () => {
      const n = cur(), hs = heights();
      if (n === 0) set(1);
      else if (n === 1) set(hs[2] > hs[1] + 8 ? 2 : 0);
      else set(1);
    };

    let g = null, swallow = 0;
    const tabPanel = () => p.querySelector(".tab-panel:not([hidden])");
    const begin = (y, target, kind) => {
      if (!mobile.matches || p.classList.contains("is-search")) return;
      const onHead = !!target.closest(".sheet-handle, .m-head, .k-head");
      const onCtl = !!target.closest("button:not(.sheet-handle), input, select, textarea, a, label");
      g = { y, kind, onHead, onCtl, handle: !!target.closest(".sheet-handle"), live: false, done: false, pts: [[y, performance.now()]] };
    };
    const shouldGrab = (dy) => {
      if (g.onHead) return true;
      const n = cur(), tp = tabPanel();
      if (n === 0) return true;
      if (dy > 0) return !tp || tp.scrollTop <= 0;                 // içerik en üstte: aşağı çek = paneli indir
      if (n === 1) { const hs = heights(); return hs[2] > hs[1] + 8; } // ortada ve sığmıyor: yukarı it = büyüt
      return false;
    };
    const moveTo = (y, ev) => {
      if (!g || g.done) return;
      const dy = y - g.y;
      if (!g.live) {
        if (Math.abs(dy) < 6) return;
        if (!shouldGrab(dy)) { g.done = true; return; }  // içerik kaydırması; bu harekette karışma
        g.live = true;
        g.hs = heights();
        clearTimeout(anim);
        p.classList.remove("is-snapping");
        g.h0 = p.offsetHeight;
        g.n0 = cur();
        g.pts = [[y, performance.now()]];
        p.classList.add("is-dragging");
        if (document.activeElement && p.contains(document.activeElement) && document.activeElement.blur) document.activeElement.blur();
      }
      if (ev && ev.cancelable) ev.preventDefault();
      const max = g.hs[2], min = g.hs[0];
      let nh = g.h0 - (y - g.y);
      if (nh > max) nh = max + (nh - max) * 0.25;   // uçlarda lastik etkisi
      if (nh < min) nh = min - (min - nh) * 0.25;
      p.style.height = Math.round(nh) + "px";
      g.pts.push([y, performance.now()]);
      if (g.pts.length > 5) g.pts.shift();
    };
    const end = (cancel) => {
      if (!g) return;
      const s = g; g = null;
      if (!s.live) {
        if (cancel || s.done) return;
        if (s.handle) { tapHandle(); swallow = Date.now(); }
        else if (s.onHead && !s.onCtl && cur() === 0) { set(1); swallow = Date.now(); }
        return;
      }
      swallow = Date.now();
      const nowH = p.offsetHeight;            // sürükleme sınıfı kalkmadan (max-height devreye girmeden) ölç
      p.classList.remove("is-dragging");
      // Son ~100 ms'deki hız (px/ms, + aşağı)
      const t1 = s.pts[s.pts.length - 1];
      const t0 = s.pts.find((q) => t1[1] - q[1] <= 100) || s.pts[0];
      const v = t1[1] - t0[1] > 0 ? (t1[0] - t0[0]) / (t1[1] - t0[1]) : 0;
      const hs = s.hs, moved = nowH - s.h0;     // + yukarı (büyüdü)
      const dir = Math.abs(v) > 0.3 ? -Math.sign(v) : Math.abs(moved) > 48 ? Math.sign(moved) : 0;
      let n = s.n0;
      if (dir) {
        // O yöndeki konumlardan bırakılan yüksekliğe en yakını (en az bir adım ilerler)
        const ahead = [0, 1, 2].filter((i) => (dir > 0 ? hs[i] > s.h0 + 4 : hs[i] < s.h0 - 4));
        if (ahead.length) {
          n = ahead.reduce((b2, i) => (Math.abs(hs[i] - nowH) < Math.abs(hs[b2] - nowH) ? i : b2));
          if (dir < 0 && v > 1.5) n = 0;        // çok hızlı aşağı: doğrudan kapat
        }
      }
      if (n === 2 && hs[2] <= hs[1] + 8) n = 1;
      set(n, nowH);
    };

    // Dokunmatik (touchmove pasif değil: sürüklerken sayfa/içerik kaymasın)
    p.addEventListener("touchstart", (e) => { if (e.touches.length === 1) begin(e.touches[0].clientY, e.target, "touch"); else end(true); }, { passive: true });
    p.addEventListener("touchmove", (e) => { if (g && g.kind === "touch") moveTo(e.touches[0].clientY, e); }, { passive: false });
    p.addEventListener("touchend", () => { if (g && g.kind === "touch") end(false); });
    p.addEventListener("touchcancel", () => { if (g && g.kind === "touch") end(true); });
    // Fare (masaüstü tarayıcı dar pencerede): yalnızca tutamak ve başlıktan
    p.addEventListener("pointerdown", (e) => {
      if (e.pointerType !== "mouse" || e.button !== 0 || !e.target.closest(".sheet-handle, .m-head, .k-head")) return;
      begin(e.clientY, e.target, "mouse");
      const mv = (ev) => moveTo(ev.clientY, ev);
      const up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); end(false); };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
    });
    // Klavye: Enter/Boşluk tutamağı bir konum ilerletir (dokunma/fare yukarıda işlendi)
    h.addEventListener("click", (e) => { if (e.detail === 0) tapHandle(); });
    // Sürükleme ya da açma dokunuşunun ardından gelen tıklamayı yut; kapalıyken gizli içerik tıklanmasın
    p.addEventListener("click", (e) => {
      if (Date.now() - swallow < 450) { e.preventDefault(); e.stopPropagation(); return; }
      if (p.classList.contains("is-collapsed") && !e.target.closest(".sheet-handle")) {
        e.preventDefault(); e.stopPropagation();
        set(1);
      }
    }, true);
    // open: içerik (ör. yeni hesap sonucu) çizildikten sonra ölçülsün diye bir kare sonra
    window.RadarSheet = { open: () => { if (cur() === 0) requestAnimationFrame(() => { if (cur() === 0) set(1); }); },
      set, state: () => CLS[cur()] };
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

  // ---------------------------------------------------------------- saat dilimleri: Duyurular kartı, üst çubuk noktası

  const TZ_SEEN = "radar.tz.gorulen", TZ_PIN = "radar.tz.sabit";
  const regionTr = (() => { try { return new Intl.DisplayNames(["tr"], { type: "region" }); } catch (e) { return null; } })();
  const ccName = (cc, en) => { const tr = regionTr && cc ? regionTr.of(cc) : ""; return tr && tr !== cc ? tr : en || cc || ""; };
  const zoneCity = (zone) => { const c = zone.split("/").pop().replace(/_/g, " "); return CITY_TR[c] || c; };
  const CITY_TR = { Istanbul: "İstanbul", Tehran: "Tahran", Moscow: "Moskova", Kyiv: "Kiev", Kiev: "Kiev", Athens: "Atina", Baku: "Bakü",
    Tbilisi: "Tiflis", Yerevan: "Erivan", Cairo: "Kahire", Riyadh: "Riyad", Baghdad: "Bağdat", Damascus: "Şam", Beirut: "Beyrut",
    Jerusalem: "Kudüs", Kabul: "Kabil", Vienna: "Viyana", Brussels: "Brüksel", Lisbon: "Lizbon", Warsaw: "Varşova", Prague: "Prag",
    Bucharest: "Bükreş", Sofia: "Sofya", Belgrade: "Belgrad", Copenhagen: "Kopenhag", Stockholm: "Stokholm", Algiers: "Cezayir",
    Tripoli: "Trablus", Tunis: "Tunus", Rome: "Roma", London: "Londra", Qatar: "Katar", Kuwait: "Kuveyt", Bahrain: "Bahreyn",
    Muscat: "Maskat", Karachi: "Karaçi", Shanghai: "Şanghay", Seoul: "Seul", Nicosia: "Lefkoşa", Famagusta: "Gazimağusa",
    Chisinau: "Kişinev", Tashkent: "Taşkent", Bishkek: "Bişkek", Dushanbe: "Duşanbe", Ashgabat: "Aşkabat", Almaty: "Almatı" };
  function tzNames(fs) {
    const n = [...new Set(fs.map((f) => ccName(f.cc, zoneCity(f.zone))))];
    return n.slice(0, 3).join(", ") + (n.length > 3 ? ` +${n.length - 3}` : "");
  }
  function tzLatest() {
    const t = data_ && data_.saat_dilimi;
    const last = t && (t.degisiklikler || [])[0];
    return last && (last.farklar || []).length && (Date.now() - new Date(last.at)) / 864e5 < 30 ? last : null;
  }
  function tzSyncDot() {
    const last = tzLatest();
    const unseen = !!last && store(TZ_SEEN) !== last.at;
    document.querySelectorAll(".tz-dot").forEach((d) => { d.hidden = !unseen; });
    document.querySelectorAll(".tz-btn, .tz-mbtn").forEach((b) => b.setAttribute("aria-label",
      unseen ? `Saat dilimleri, ${last.farklar.length} yeni değişiklik` : "Saat dilimleri"));
  }
  function renderTz(data) {
    const t = data.saat_dilimi;
    $("#tz-card").hidden = !t;
    document.querySelectorAll(".tz-btn, .tz-mbtn").forEach((b) => { b.hidden = !t; });
    if (!t) return;
    const last = tzLatest();
    $("#tz-card-t").innerHTML = `IANA tzdata <span class="ov">${esc(t.iana || "?")}</span> izleniyor`;
    $("#tz-card-s").innerHTML = last ? `<b class="tz-c">${last.farklar.length} değişiklik</b> · ${esc(tzNames(last.farklar))}` : "Son sürümde saat farkı değişen ülke yok";
    tzSyncDot();
  }

  // ---------------------------------------------------------------- saat dilimleri penceresi

  const TZW = { data: null, failed: false, zones: [], countries: [], byZone: {}, filter: "all", sort: "az",
    open: new Set(), more: new Set(), pins: null, timer: 0, tick: 0 };
  const AY = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"];
  const tzFold = (s) => String(s || "").toLocaleLowerCase("tr").replace(/ı/g, "i").normalize("NFD").replace(/[̀-ͯ]/g, "");
  const two = (n) => String(n).padStart(2, "0");
  const hm = (sec) => `${two(Math.floor(Math.abs(sec) / 3600))}:${two(Math.floor((Math.abs(sec) % 3600) / 60))}`;
  const sgn = (sec) => (sec < 0 ? "−" : "+");
  const utcLabel = (sec) => `UTC${sgn(sec)}${hm(sec)}`;
  const shifted = (ms, off) => new Date(ms + off * 1000);
  const clock = (ms, off) => { const d = shifted(ms, off); return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`; };
  const dayStr = (ms, off) => { const d = shifted(ms, off); return `${d.getUTCDate()} ${AY[d.getUTCMonth()]} ${d.getUTCFullYear()}`; };
  const dur = (s) => { const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60); return h && m ? `${h} sa ${m} dk` : h ? `${h} sa` : `${m} dk`; };
  const ICO = {
    star: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
    arr: '<svg class="tz-arr" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    chev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>',
    nores: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5M8 11h6"/></svg>',
    ok: '<svg class="ok" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>',
    globe: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></svg>',
  };

  function tzAt(t, ms) {
    let v = t[0];
    for (const x of t) { if (Date.parse(x[0]) <= ms) v = x; else break; }
    return v;
  }
  const trOff = (ms) => { const z = TZW.byZone["Europe/Istanbul"]; return z ? tzAt(z.t, ms)[1] : 10800; };
  function relTr(off, ms, zone) {
    if (zone === "Europe/Istanbul") return "referans";
    const d = off - trOff(ms);
    return d === 0 ? "Türkiye ile aynı" : `${dur(Math.abs(d))} ${d > 0 ? "ileri" : "geri"}`;
  }
  function dayWord(off, ms) {
    const a = shifted(ms, off), b = shifted(ms, trOff(ms));
    const n = (Date.UTC(a.getUTCFullYear(), a.getUTCMonth(), a.getUTCDate()) - Date.UTC(b.getUTCFullYear(), b.getUTCMonth(), b.getUTCDate())) / 864e5;
    return n > 0 ? " yarın" : n < 0 ? " dün" : "";
  }
  function tzPins() {
    if (!TZW.pins) {
      try { TZW.pins = JSON.parse(store(TZ_PIN) || "null"); } catch (e) { TZW.pins = null; }
      if (!Array.isArray(TZW.pins)) TZW.pins = ["Europe/Istanbul"];
    }
    return TZW.pins;
  }

  function tzBuild() {
    const d = TZW.data, names = d.ulkeler || {};
    const chg = (data_ && data_.saat_dilimi && data_.saat_dilimi.farklar) || {};
    const byCc = {};
    TZW.zones = Object.entries(d.zones || {}).map(([zone, z], i) => {
      const cityEn = zone.split("/").pop().replace(/_/g, " ");
      const r = { zone, cc: z.cc, i, t: z.t, en: names[z.cc] || z.cc, country: ccName(z.cc, names[z.cc]), city: zoneCity(zone), cityEn,
        dst: z.t.some((x) => x[2]), offs: [...new Set(z.t.map((x) => x[1]))], chg: chg[zone] || null };
      r.text = tzFold(["utc gmt", r.country, r.en, r.city, cityEn, zone.replace(/[_/]/g, " "), z.cc].join(" "));
      (byCc[z.cc] = byCc[z.cc] || []).push(r);
      return r;
    });
    TZW.byZone = Object.fromEntries(TZW.zones.map((r) => [r.zone, r]));
    TZW.countries = Object.entries(byCc).map(([cc, zs]) => ({ cc, name: zs[0].country, zones: zs }))
      .sort((a, b) => a.name.localeCompare(b.name, "tr"));
    TZW.zones.forEach((r) => { r.multi = byCc[r.cc].length > 1; });
    const n = TZW.zones.filter((r) => r.chg).length;
    $("#tz-nchg").hidden = !n;
    $("#tz-nchg").textContent = String(n);
    $("#tz-sub").innerHTML = `<span class="tz-d">IANA tzdata</span><span class="tz-m">tzdata</span> <b class="ov">${esc(d.iana || "?")}</b><span class="tz-d"> · ${TZW.zones.length} bölge, ${TZW.countries.length} ülke · saatler şu an</span><span class="tz-m"> · ${TZW.zones.length} bölge · ${TZW.countries.length} ülke</span>`;
  }

  // "+5.5", "5:30", "utc+3", "gmt-4" → saniye; düz sayı ("3") metin olarak aranır
  function tzOffsetQuery(tok) {
    const m = tok.match(/^(utc|gmt)?([+\-−])?(\d{1,2})(?:([:.,])(\d{1,2}))?$/);
    if (!m || (!m[1] && !m[2] && !m[4])) return null;
    const h = +m[3];
    const min = m[5] === undefined ? 0 : m[4] === ":" ? +m[5] : Math.round(parseFloat("0." + m[5]) * 60);
    if (h > 14 || min >= 60) return null;
    return { v: (h * 3600 + min * 60) * (m[2] === "-" || m[2] === "−" ? -1 : 1), signed: !!m[2] };
  }
  function tzMatcher() {
    const toks = tzFold($("#tz-q").value).split(/\s+/).filter(Boolean);
    const tests = toks.map((tok) => {
      const o = tzOffsetQuery(tok);
      if (!o) return (r) => r.text.includes(tok);
      const eq = (x) => (o.signed ? x === o.v : Math.abs(x) === Math.abs(o.v));
      return (r) => r.offs.some(eq) || (!!r.chg && r.chg.eski != null && eq(r.chg.eski));
    });
    const f = TZW.filter;
    return { q: toks.length > 0, test: (r) => (f !== "dst" || r.dst) && (f !== "changed" || !!r.chg) && tests.every((t) => t(r)) };
  }

  function tzRow(r, ms, o) {
    const cur = tzAt(r.t, ms), off = cur[1], c = r.chg;
    const kind = c ? (c.eski == null ? " is-new" : " is-changed") : "";
    const title = o.child ? r.city : r.multi ? r.city : r.country;
    const meta = o.child ? r.zone : r.multi ? `${r.country} · ${r.zone}` : `${r.city} · ${r.zone}`;
    const pin = tzPins().includes(r.zone);
    const chgPill = c ? `<span class="tz-pill chg">${c.eski == null ? "Yeni bölge" : "Değişti"} · tzdata ${esc(c.iana)}</span>` : "";
    const pill = c ? `<span class="tz-d">${chgPill}</span>` : r.dst ? '<span class="tz-pill dst">Yaz saati</span>' : "";
    const next = r.t.find((x) => Date.parse(x[0]) > ms);
    let detail = "";
    if (c && c.eski == null) detail = "Bu sürümde veritabanına eklendi";
    else if (!c) detail = next ? `${ICO.arr}<span>Sonraki geçiş <b class="ov">${dayStr(Date.parse(next[0]), next[1])}</b> → <b class="ov">${utcLabel(next[1])}</b>${next[2] ? " (yaz saati)" : ""}</span>` : "Yaz saati yok, sabit";
    const diff = c && c.eski != null ? `<div class="tz-diff"><span class="tz-m">${chgPill}</span><span class="tz-diff-in">
        <span class="l">Eski</span><span class="ov old">${utcLabel(c.eski)}</span>${ICO.arr}<span class="l">Yeni</span><span class="ov new">${utcLabel(c.yeni)}</span>
        <span class="when"><span class="tz-d">· </span>${c.tarih ? `${esc(c.tarih)} itibarıyla` : "şimdiden geçerli"}</span></span></div>` : "";
    return `<article class="tz-row${kind}${o.child ? " is-child" : ""}" data-z="${esc(r.zone)}">
      <button type="button" class="tz-star" data-pin="${esc(r.zone)}" aria-pressed="${pin}" aria-label="${pin ? "Sabitlemeyi kaldır" : "Sabitle"}: ${esc(title)}">${ICO.star}</button>
      <div class="tz-mid"><span class="tz-nl"><span class="tz-name">${esc(title)}</span>${pill}</span><span class="tz-meta">${esc(meta)}</span>${detail ? `<span class="tz-det">${detail}</span>` : ""}</div>
      <div class="tz-r"><span class="tz-utc ov">${utcLabel(off)}</span><span class="tz-tm"><b class="ov">${clock(ms, off)}</b>${dayWord(off, ms)} · ${relTr(off, ms, r.zone)}</span></div>${diff}</article>`;
  }

  function tzRange(zs, ms) {
    const offs = zs.map((r) => tzAt(r.t, ms)[1]), lo = Math.min(...offs), hi = Math.max(...offs), tr = trOff(ms);
    const utc = lo === hi ? utcLabel(lo) : `${utcLabel(lo)} … ${sgn(hi)}${hm(hi)}`;
    const a = lo - tr, b = hi - tr;
    let rel;
    if (a === b) rel = a === 0 ? "Türkiye ile aynı" : `${dur(Math.abs(a))} ${a > 0 ? "ileri" : "geri"}`;
    else if (b <= 0) rel = (a % 3600 || b % 3600) ? `${dur(-b)} – ${dur(-a)} geri` : `${-b / 3600}–${-a / 3600} sa geri`;
    else if (a >= 0) rel = (a % 3600 || b % 3600) ? `${dur(a)} – ${dur(b)} ileri` : `${a / 3600}–${b / 3600} sa ileri`;
    else rel = `${dur(-a)} geri – ${dur(b)} ileri`;
    return { utc, rel };
  }
  function tzReps(zs, ms) {
    const seen = new Set();
    return zs.filter((r) => { const o = tzAt(r.t, ms)[1]; if (seen.has(o)) return false; seen.add(o); return true; });
  }
  function tzGroup(ctry, zs, ms, auto) {
    const rg = tzRange(ctry.zones, ms), cc = esc(ctry.cc);
    const open = auto || TZW.open.has(ctry.cc);
    const head = (exp) => `<button type="button" class="tz-chev" data-grp="${cc}" aria-expanded="${exp}" aria-label="${esc(ctry.name)}, ${ctry.zones.length} bölgeyi ${exp ? "gizle" : "göster"}">${ICO.chev}</button>`;
    const nl = (pillCls) => `<span class="tz-nl"><span class="tz-name">${esc(ctry.name)}</span><span class="tz-pill cnt ov${pillCls}">${ctry.zones.length} bölge</span></span>`;
    if (!open) {
      const reps = tzReps(ctry.zones, ms);
      const sub = reps.slice(0, 4).map((r) => r.city).join(", ") + (ctry.zones.length > 4 ? "…" : "");
      return `<article class="tz-row tz-group">${head(false)}<div class="tz-mid">${nl(" tz-d")}<span class="tz-meta tz-d">${esc(sub)}</span>
        <span class="tz-meta tz-m"><b>${ctry.zones.length} bölge</b> · ${rg.rel}</span></div>
        <div class="tz-r"><span class="tz-utc sm ov">${rg.utc}</span><span class="tz-tm tz-d">${rg.rel}</span></div></article>`;
    }
    const all = auto || TZW.more.has(ctry.cc);
    const shown = all ? zs : tzReps(zs, ms);
    const rest = zs.length - shown.length;
    return `<div class="tz-gbox"><div class="tz-ghead">${head(true)}${nl("")}<span class="tz-tm">${rg.rel}</span></div>
      ${shown.map((r) => tzRow(r, ms, { child: true })).join("")}
      ${rest > 0 ? `<button type="button" class="tz-more" data-more="${cc}">${rest} bölge daha göster</button>` : ""}</div>`;
  }

  function tzEmpty(icon, title, text, act, label, primary) {
    return `<div class="tz-empty">${icon}<b>${title}</b><span>${text}</span>${act ? `<button type="button" class="tz-ebtn${primary ? " pri" : ""}" data-tz-act="${act}">${label}</button>` : ""}</div>`;
  }
  function tzHistory() {
    const t = (data_ && data_.saat_dilimi) || {}, cur = TZW.data.iana || t.iana;
    const list = (t.degisiklikler || []).slice();
    if (!list.length || list[0].iana !== cur) list.unshift({ iana: cur, farklar: [], none: true });
    const items = list.map((c, i) => `<li><span class="tz-tl"><i class="${i === 0 ? "on" : ""}"></i><i class="ln"></i></span><div class="tz-tlb">
        <span class="tz-tlh"><span class="ov">${esc(c.iana)}</span><span>${i === 0 ? "şu an izlenen" : esc(date(c.at))}</span></span>
        ${c.none || !(c.farklar || []).length ? '<span class="tz-tls">Bu sürümde saat farkı değişen ülke yok</span>'
          : c.farklar.map((f) => `<span class="tz-tls">${esc(ccName(f.cc, zoneCity(f.zone)))} · <span class="ov">${f.eski == null ? "yeni bölge, " + utcLabel(f.yeni) : `${utcLabel(f.eski)} → ${utcLabel(f.yeni)}`}</span></span>`).join("")}</div></li>`);
    items.push('<li class="end"><span class="tz-tl"><i></i></span><span class="tz-tls">Yeni sürümler yayımlandıkça değişiklikleri burada birikir.</span></li>');
    return `<h3 class="tz-sec">Sürüm geçmişi</h3><ol class="tz-hist">${items.join("")}</ol>
      <div class="tz-foot"><span>Kaynak: IANA Time Zone Database</span>${link(t.kaynak || "https://data.iana.org/time-zones/tzdb/NEWS", `${cur} sürüm notlarını aç ↗`)}</div>`;
  }

  function tzRender() {
    const box = $("#tz-rows"), st = $("#tz-status");
    if (!TZW.data) {
      if (TZW.failed) { st.textContent = ""; box.innerHTML = tzEmpty(ICO.globe, "Saat dilimi verisi henüz hazır değil", "İlk kontrol bitince ülkeler burada listelenir.", "retry", "Yeniden dene", true); return; }
      st.textContent = "Saat dilimleri yükleniyor…";
      box.innerHTML = `<div class="tz-skel" aria-hidden="true">${"<div><i></i><span><i></i><i></i></span><i></i></div>".repeat(3)}</div>`;
      return;
    }
    const ms = Date.now(), m = tzMatcher(), pins = tzPins(), parts = [];
    const hits = TZW.zones.filter(m.test);
    const total = TZW.zones.length;
    st.textContent = !m.q && TZW.filter === "all" ? `${TZW.countries.length} ülke · ${total} bölge` : `${total} bölgeden ${hits.length} gösteriliyor`;
    const changed = hits.filter((r) => r.chg).sort((a, b) => a.country.localeCompare(b.country, "tr"));
    const cur = TZW.data.iana;

    if (TZW.filter === "changed") {
      if (changed.length) parts.push(changed.map((r) => tzRow(r, ms, {})).join(""));
      else parts.push(m.q ? tzEmpty(ICO.nores, `“${esc($("#tz-q").value.trim())}” için eşleşme yok`, "Türkçe ya da İngilizce ülke adı, şehir ya da UTC+3 gibi bir fark dene.", "clear", "Aramayı temizle")
        : tzEmpty(ICO.ok, "Son IANA sürümlerinde saat farkı değişen ülke yok", "Yeni sürüm bir ülkenin saatini değiştirirse burada en üstte görünür.", "all", "Tüm ülkeleri gör"));
      parts.push(tzHistory());
      box.innerHTML = parts.join("");
      return;
    }
    if (!hits.length) {
      box.innerHTML = tzEmpty(ICO.nores, `“${esc($("#tz-q").value.trim())}” için eşleşme yok`, "Türkçe ya da İngilizce ülke adı, şehir ya da UTC+3 gibi bir fark dene.", "clear", "Aramayı temizle");
      return;
    }
    const top = new Set();
    if (changed.length) {
      const allCur = changed.every((r) => r.chg.iana === cur);
      parts.push(`<h3 class="tz-sec chg">${allCur ? "Bu sürümde değişti" : "Son sürümlerde değişti"}</h3>` + changed.map((r) => tzRow(r, ms, {})).join(""));
      changed.forEach((r) => top.add(r.zone));
    }
    const pinned = pins.map((z) => TZW.byZone[z]).filter((r) => r && m.test(r) && !top.has(r.zone));
    if (pinned.length) {
      parts.push('<h3 class="tz-sec">Sabitlediklerin</h3>' + pinned.map((r) => tzRow(r, ms, {})).join(""));
      pinned.forEach((r) => top.add(r.zone));
    }
    const rest = hits.filter((r) => !top.has(r.zone));
    const label = TZW.filter === "dst" ? "Yaz saati uygulayanlar" : TZW.sort === "utc" ? "Tüm bölgeler" : "Tüm ülkeler";
    if (rest.length) {
      if (TZW.sort === "utc") {
        rest.sort((a, b) => tzAt(a.t, ms)[1] - tzAt(b.t, ms)[1] || a.country.localeCompare(b.country, "tr") || a.i - b.i);
        parts.push(`<h3 class="tz-sec">${label} · UTC'ye göre</h3>` + rest.map((r) => tzRow(r, ms, {})).join(""));
      } else {
        const restSet = new Set(rest.map((r) => r.zone));
        parts.push(`<h3 class="tz-sec">${label} · A–Z</h3>` + TZW.countries.map((c) => {
          const zs = c.zones.filter((r) => restSet.has(r.zone));
          if (!zs.length) return "";
          if (c.zones.length === 1) return tzRow(zs[0], ms, {});
          return tzGroup(c, zs, ms, m.q);
        }).join(""));
      }
    }
    box.innerHTML = parts.join("");
  }

  // Saatler dakika başında yenilenir; satırlar yeniden çizilmez (odak kaybolmasın)
  function tzTick() {
    if (!TZW.data) return;
    const ms = Date.now();
    document.querySelectorAll("#tz-rows .tz-row[data-z]").forEach((el) => {
      const r = TZW.byZone[el.dataset.z];
      if (!r) return;
      const off = tzAt(r.t, ms)[1];
      el.querySelector(".tz-utc").textContent = utcLabel(off);
      el.querySelector(".tz-tm").innerHTML = `<b class="ov">${clock(ms, off)}</b>${dayWord(off, ms)} · ${relTr(off, ms, r.zone)}`;
    });
  }
  function tzStartClock() {
    clearTimeout(TZW.tick); clearInterval(TZW.timer);
    TZW.tick = setTimeout(() => { tzTick(); TZW.timer = setInterval(tzTick, 60000); }, 60000 - (Date.now() % 60000) + 50);
  }
  async function tzLoad() {
    TZW.failed = false;
    tzRender();
    TZW.data = await fetchFirst(sample() ? [] : ["data/saat-dilimleri.json", "../data/saat-dilimleri.json"]);
    if (!TZW.data || !TZW.data.zones) { TZW.data = null; TZW.failed = true; tzRender(); return; }
    tzBuild();
    tzRender();
  }
  function tzOpen() {
    const dlg = $("#tz-dialog");
    if (!dlg.open) dlg.showModal();
    document.querySelectorAll(".tz-btn").forEach((b) => b.setAttribute("aria-expanded", "true"));
    $("#tz-q").placeholder = matchMedia("(max-width: 600px)").matches ? "Ülke, şehir ya da UTC+3" : "Ülke, şehir ya da UTC+3 ara";
    $("#tz-q").focus();
    const last = tzLatest();
    if (last) { store(TZ_SEEN, last.at); tzSyncDot(); }
    if (!TZW.data) tzLoad(); else tzRender();
    tzStartClock();
  }
  function tzSetFilter(f) {
    TZW.filter = f;
    document.querySelectorAll("#tz-dialog [data-tzf]").forEach((x) => x.setAttribute("aria-checked", String(x.dataset.tzf === f)));
    $("#tz-scroll").scrollTop = 0;
    tzRender();
  }
  function tzSetSort(s) {
    TZW.sort = s;
    document.querySelectorAll("#tz-dialog [data-tzs]").forEach((x) => x.setAttribute("aria-checked", String(x.dataset.tzs === s)));
    const t = $("#tz-dialog [data-tzs-toggle]");
    t.textContent = s === "utc" ? "UTC" : "A–Z";
    t.setAttribute("aria-label", `Sıralama: ${s === "utc" ? "UTC farkı" : "A–Z"}`);
    $("#tz-scroll").scrollTop = 0;
    tzRender();
  }
  function bindTz() {
    const dlg = $("#tz-dialog");
    document.addEventListener("click", (e) => { if (e.target.closest("[data-tz-open]")) tzOpen(); });
    dlg.addEventListener("close", () => {
      clearTimeout(TZW.tick); clearInterval(TZW.timer);
      document.querySelectorAll(".tz-btn").forEach((b) => b.setAttribute("aria-expanded", "false"));
    });
    $("#tz-q").addEventListener("input", () => { $("#tz-scroll").scrollTop = 0; tzRender(); });
    dlg.addEventListener("click", (e) => {
      if (e.target === dlg || e.target.closest("[data-tz-close]")) { dlg.close(); return; }
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.tzf) tzSetFilter(b.dataset.tzf);
      else if (b.dataset.tzs) tzSetSort(b.dataset.tzs);
      else if (b.hasAttribute("data-tzs-toggle")) tzSetSort(TZW.sort === "az" ? "utc" : "az");
      else if (b.dataset.pin) {
        const pins = tzPins(), z = b.dataset.pin, i = pins.indexOf(z);
        if (i >= 0) pins.splice(i, 1); else pins.push(z);
        store(TZ_PIN, JSON.stringify(pins));
        tzRender();
        const again = $(`#tz-rows [data-pin="${CSS.escape(z)}"]`);
        if (again) again.focus();
      } else if (b.dataset.grp) {
        const cc = b.dataset.grp;
        if (TZW.open.has(cc)) { TZW.open.delete(cc); TZW.more.delete(cc); } else TZW.open.add(cc);
        tzRender();
        const again = $(`#tz-rows [data-grp="${CSS.escape(cc)}"]`);
        if (again) again.focus();
      } else if (b.dataset.more) { TZW.more.add(b.dataset.more); tzRender(); }
      else if (b.dataset.tzAct === "clear") { $("#tz-q").value = ""; tzRender(); $("#tz-q").focus(); }
      else if (b.dataset.tzAct === "all") { $("#tz-q").value = ""; tzSetFilter("all"); }
      else if (b.dataset.tzAct === "retry") tzLoad();
    });
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
        if (window.RadarSheet && window.RadarSheet.state() === "is-expanded") window.RadarSheet.set(1);
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
    renderTz(data);
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
