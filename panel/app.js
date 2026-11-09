"use strict";

(function () {
  const TZ = "Europe/Istanbul";
  const fmtMoney = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDate = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", timeZone: TZ });
  const fmtShort = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", timeZone: TZ });
  const fmtDateTime = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: TZ });
  const fmtYmd = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: TZ });
  const CLASSES = ["1", "2", "3", "4", "5", "6"];

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => (v == null ? "—" : fmtMoney.format(Number(v)) + " ₺");
  const date = (iso) => (iso ? fmtDate.format(new Date(iso)) : "belirsiz");
  const dateTime = (iso) => (iso ? fmtDateTime.format(new Date(iso)) : "belirsiz");
  // Yalnızca http(s) bağlantıları tıklanabilir.
  const safeUrl = (url) => (typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url.trim()) ? url.trim() : null);
  const link = (url, label) => (safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : esc(label));
  const className = (k) => `${k}. sınıf` + (window.RadarHesap && window.RadarHesap.className(k) ? " · " + window.RadarHesap.className(k) : "");
  const ICON = {
    kopru: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.8 11.6h12.4M3.2 11.6c1.3-4.2 8.3-4.2 9.6 0M5.6 8.3v3.3M10.4 8.3v3.3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    tunel: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 12.4V9a4.8 4.8 0 0 1 9.6 0v3.4M1.8 12.4h12.4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
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

  // ---------------------------------------------------------------- sekmeler

  function selectTab(name, focus) {
    document.querySelectorAll('.tabs [role="tab"]').forEach((t) => {
      const on = t.getAttribute("aria-controls") === "tab-" + name;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      if (on && focus) t.focus();
    });
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
  }

  // Sınıf seçimi hesap, köprü listesi ve harita arasında ortaktır.
  function setClassEverywhere(cls, from) {
    cls_ = cls;
    store("radar.sinif", cls);
    renderCrossings(data_, now_);
    if (from !== "hesap" && window.RadarHesap) window.RadarHesap.setClass(cls);
    if (window.RadarMap) window.RadarMap.setClass(cls);
  }

  // ---------------------------------------------------------------- üst bilgi

  function renderStatus(data, now) {
    const enabled = data.sources.filter((s) => s.enabled);
    const failing = enabled.filter((s) => s.ok === false);
    const stale = data.last_run && now - new Date(data.last_run) > 6 * 3600 * 1000;
    const cls = failing.length ? "bad" : stale ? "warn" : "good";
    const el = $("#status");
    el.title = `Son kontrol ${ago(data.last_run, now)} · ${failing.length ? failing.length + " kaynak okunamıyor" : "tüm kaynaklar çalışıyor"}`;
    el.innerHTML = `<span class="dot ${cls}" aria-hidden="true"></span>${failing.length ? esc(failing.length + " kaynak okunamıyor")
      : `<span><span class="txt-long">Güncel · </span>${esc(ago(data.last_run, now))}</span>`}`;
  }

  // Yaklaşan değişiklik / süren ücretsiz geçiş: haritada kısa bir hap, Duyurular'da ayrıntı.
  function renderAnnouncements(data, now) {
    const items = [];
    (data.active_rules || []).forEach((r) => items.push({ cls: "free", k: "Ücretsiz geçiş sürüyor", t: r.title,
      m: `${names(data, r.crossings)} · bitiş ${dateTime(r.valid_to)}`, cd: inDays(r.valid_to, now), src: null }));
    (data.upcoming || []).forEach((u) => {
      const src = u.sources && u.sources[u.sources.length - 1];
      items.push({ cls: "change", k: "Yaklaşan değişiklik", t: u.title,
        m: `Yürürlük ${dateTime(u.effective_from)}${u.crossings.length ? " · " + names(data, u.crossings) : ""}`,
        cd: inDays(u.effective_from, now), src });
    });
    $("#announcements").innerHTML = items.map((x) => `<div class="announce ${x.cls}">
      <div class="k">${esc(x.k)}</div><div class="t">${esc(x.t)}</div><div class="m">${esc(x.m)}${x.src ? " · " + link(x.src.url, x.src.publisher || "kaynak") : ""}</div>
      <div class="cd">${esc(x.cd)}</div></div>`).join("");
    const badge = $("#duyuru-badge");
    badge.hidden = !items.length;
    badge.textContent = items.length;
    const n = $("#notice");
    if (!items.length) { n.hidden = true; return; }
    const top = items[0];
    n.hidden = false;
    n.innerHTML = `<span class="tag ${top.cls}">${esc(top.cd)}</span><span>${esc(top.t)}</span>`;
    n.onclick = () => selectTab("duyuru");
  }

  // ---------------------------------------------------------------- köprüler

  function historyChart(history, now) {
    const pts = (history || []).filter((h) => h.class1 != null).map((h) => ({ t: new Date(h.valid_from).getTime(), v: Number(h.class1) }));
    if (pts.length < 2) return "";
    const W = 330, H = 120, L = 8, R = 48, T = 16, B = 20;
    const tMin = pts[0].t, tMax = Math.max(pts[pts.length - 1].t, now.getTime()) + 30 * 86400000;
    const vMax = Math.max(...pts.map((p) => p.v)) * 1.15;
    const x = (t) => L + ((t - tMin) / (tMax - tMin)) * (W - L - R);
    const y = (v) => T + (1 - v / vMax) * (H - T - B);
    let past = "", future = "";
    pts.forEach((p, i) => {
      const nextT = i + 1 < pts.length ? pts[i + 1].t : tMax;
      const seg = `M${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}H${x(nextT).toFixed(1)}` + (i + 1 < pts.length ? `V${y(pts[i + 1].v).toFixed(1)}` : "");
      if (p.t > now.getTime()) future += seg; else past += seg;
    });
    const years = [];
    for (let yr = new Date(tMin).getFullYear(); yr <= new Date(tMax).getFullYear(); yr++) {
      const t = Date.UTC(yr, 0, 1);
      if (t >= tMin && t <= tMax) years.push(`<text x="${x(t).toFixed(1)}" y="${H - 4}" text-anchor="middle">${yr}</text>`);
    }
    const labels = pts.map((p) => `<circle cx="${x(p.t).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="2.5"/>
      <text x="${(x(p.t) + 4).toFixed(1)}" y="${(y(p.v) - 5).toFixed(1)}">${esc(fmtMoney.format(p.v))}</text>`).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="1. sınıf ücret geçmişi">
      <line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
      <path class="line" d="${past}"/><path class="line future" d="${future}"/>${labels}${years.join("")}</svg>`;
  }

  function crossingDetail(c, now) {
    const rows = CLASSES.map((k) => `<tr><td>${esc(className(k))}</td><td>${esc(money(c.current && c.current.classes[k]))}</td>
      ${c.upcoming ? `<td>${esc(money(c.upcoming.classes[k]))}</td>` : ""}</tr>`).join("");
    const links = [c.konum ? `<a href="#" data-map-focus="${esc(c.id)}">Haritada göster</a>` : "",
      c.current && c.current.source_url ? link(c.current.source_url, "Tarife belgesi") : ""].filter(Boolean).join("");
    return `<div class="crossing-detail">
      <table class="mini"><thead><tr><th>Sınıf</th><th>Şimdi</th>${c.upcoming ? `<th>${esc(fmtShort.format(new Date(c.upcoming.valid_from)))}</th>` : ""}</tr></thead>
      <tbody>${rows}</tbody></table>
      ${historyChart(c.history, now)}
      ${links ? `<div class="detail-links">${links}</div>` : ""}</div>`;
  }

  function renderCrossings(data, now) {
    if (!data) return;
    $("#kopru-sinif").textContent = className(cls_);
    const list = data.crossings || [];
    if (!list.length) { $("#crossings").innerHTML = `<li><p class="empty" style="padding:12px">Henüz ücret kaydı yok.</p></li>`; return; }
    const open = $("#crossings").dataset.open || "";
    $("#crossings").innerHTML = list.map((c) => {
      const v = c.current && c.current.classes[cls_];
      let tag = "";
      if (c.free_now) tag = `<small class="tag free">Ücretsiz</small>`;
      else if (c.upcoming) tag = `<small class="tag change">${esc(fmtShort.format(new Date(c.upcoming.valid_from)))} → ${esc(money(c.upcoming.classes[cls_]))}</small>`;
      const sub = [(c.iller || []).join(" / "), c.operator].filter(Boolean).join(" · ");
      return `<li><button type="button" class="crossing-row" data-id="${esc(c.id)}" aria-expanded="${open === c.id}">
          <span class="ic">${ICON[c.tur] || ICON.kopru}</span>
          <span><span class="nm">${esc(c.name)}</span><span class="sub">${esc(sub)}</span></span>
          <span class="pr">${v != null ? esc(money(v)) : c.id === "avrasya-tuneli" ? `<small class="tag neutral">Duyurular izleniyor</small>` : "—"}${tag}</span>
        </button>${open === c.id ? crossingDetail(c, now) : ""}</li>`;
    }).join("");
  }

  function bindCrossings() {
    $("#crossings").addEventListener("click", (e) => {
      const f = e.target.closest("[data-map-focus]");
      if (f) {
        e.preventDefault();
        if (window.RadarMap) window.RadarMap.focusCrossing(f.dataset.mapFocus);
        if (window.matchMedia("(max-width: 900px)").matches) $(".map-area").scrollIntoView({ behavior: "smooth" });
        return;
      }
      const row = e.target.closest(".crossing-row");
      if (!row) return;
      const box = $("#crossings");
      box.dataset.open = box.dataset.open === row.dataset.id ? "" : row.dataset.id;
      renderCrossings(data_, now_);
    });
  }

  function openCrossing(id) {
    selectTab("kopru");
    $("#crossings").dataset.open = id;
    renderCrossings(data_, now_);
    const row = document.querySelector(`.crossing-row[data-id="${CSS.escape(id)}"]`);
    if (row) row.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // ---------------------------------------------------------------- duyurular

  function renderFree(data) {
    const parts = [];
    (data.active_rules || []).forEach((r) => parts.push(`<p><strong>Sürüyor:</strong> ${esc(r.title)}<br>
      <span class="muted small">${esc(names(data, r.crossings))} · bitiş ${esc(dateTime(r.valid_to))}</span></p>`));
    (data.next_rules || []).forEach((r) => parts.push(`<p><strong>Karar çıktı:</strong> ${esc(r.title)}<br>
      <span class="muted small">${esc(dateTime(r.valid_from))} – ${esc(dateTime(r.valid_to))} · ${esc(names(data, r.crossings))}</span></p>`));
    if (!parts.length) {
      const b = (data.calendar || []).find((p) => p.kind === "bayram");
      parts.push(b ? `<div class="next"><div><strong>${esc(b.name)}</strong><span>Sıradaki bayram</span></div><span>${esc(date(b.start))}</span></div>`
        : `<p class="empty">Karar çıktığında burada görünür.</p>`);
    }
    $("#free").innerHTML = parts.join("");
  }

  function renderEvents(data, now) {
    const list = data.events || [];
    $("#events-head").hidden = !list.length;
    $("#events").innerHTML = list.slice(0, 8).map((e) => {
      const src = e.sources && e.sources[e.sources.length - 1];
      const when = e.effective_from ? ` · yürürlük ${esc(date(e.effective_from))}` : "";
      const flags = (e.flags || []).filter((f) => f.id !== "takvim").map((f) => `<span class="chip ${f.id === "kacirildi" ? "bad" : ""}">${esc(f.label)}</span>`).join("");
      return `<li><div class="top"><span class="pill ${esc(e.status)}">${esc(e.status_label)}</span><span class="when">${esc(ago(e.updated_at, now))}</span></div>
        <div class="title">${src ? link(src.url, e.title) : esc(e.title)}</div>
        <div class="sub">${esc(e.kind_label)}${e.crossings.length ? " · " + esc(names(data, e.crossings)) : ""}${when}</div>${flags}</li>`;
    }).join("");
  }

  function renderSources(data, now) {
    const enabled = data.sources.filter((s) => s.enabled);
    const failing = enabled.filter((s) => s.ok === false).length;
    $("#source-summary").textContent = failing ? `· ${failing} sorunlu` : `· ${enabled.length} çalışıyor`;
    $("#sources").innerHTML = enabled.map((s) => `<li><span class="dot ${s.ok === true ? "good" : s.ok === false ? "bad" : ""}" aria-hidden="true"></span>
      <span>${link(s.url, s.name)}</span><span class="when">${esc(ago(s.last_success, now))}</span>
      ${s.ok === false ? `<span class="err">${esc((s.error || "").slice(0, 120))}</span>` : ""}</li>`).join("");
  }

  function renderDocuments(data) {
    const docs = data.documents || [];
    $("#doc-count").textContent = docs.length ? `· ${docs.filter((d) => !d.removed).length}` : "";
    $("#documents").innerHTML = docs.length ? docs.map((d) => `<li class="${d.removed ? "removed" : ""}">
      <span>${link(d.url, d.title || d.key)}</span>
      <span class="sub">Geçerlilik ${esc(date(d.effective_from))}${d.error ? ` · <span class="chip bad">${esc(d.error)}</span>` : ""}</span></li>`).join("")
      : `<li class="empty">Henüz belge okunmadı.</li>`;
  }

  // Takvim: yılbaşı ücret dönemi ve bayramlar (config/calendar.yaml). Kararlar çıktığında yukarıda duyuru olur.
  function renderCalendar(data, now) {
    const KIND = { yilbasi: "Ücret güncellemesi dönemi", bayram: "Bayram · ücretsiz geçiş kararı beklenir" };
    const list = (data.calendar || []).filter((p) => dayDiff(p.end || p.start, now) >= 0).slice(0, 4);
    $("#calendar-head").hidden = !list.length;
    $("#calendar").innerHTML = list.map((p) => `<li>
      <div><strong>${esc(p.name)}</strong><span>${esc(KIND[p.kind] || "")}</span></div>
      <div class="when"><b>${esc(inDays(p.start, now))}</b><span>${esc(date(p.start))}</span></div></li>`).join("");
  }

  // ---------------------------------------------------------------- harita araçları

  function bindMapTools(hesap) {
    const M = window.RadarMap;
    if (!M || !M.countsBy) return;
    const chips = $("#layer-chips");
    const renderChips = () => {
      const c = M.countsBy(), on = new Set(M.filter().types);
      chips.innerHTML = M.types().map(([t, label]) => `<button type="button" class="layer-chip" data-type="${t}" aria-pressed="${on.has(t)}">
        <span class="sw sw-${t}" aria-hidden="true"></span>${esc(label)}<span class="n">${c[t]}</span></button>`).join("");
    };
    chips.addEventListener("click", (e) => {
      const b = e.target.closest("[data-type]");
      if (!b) return;
      const on = new Set(M.filter().types);
      if (on.has(b.dataset.type)) on.delete(b.dataset.type); else on.add(b.dataset.type);
      M.setFilter({ types: [...on] });
      renderFilters();   // tıklama anında tanımlıdır
    });
    // Filtre penceresi: bölge, durum, il, otoyol. Seçenek sayıları diğer filtrelere göre hesaplanır.
    const roads = hesap ? hesap.roads() : [];
    const roadName = (id) => { const o = roads.find((r) => r.id === id); return o ? (o.yol ? o.yol + " · " : "") + o.ad : id; };
    const DURUM = [["change", "Zammı yaklaşan"], ["free", "Ücretsiz geçiş"]];
    const pop = $("#filter-pop"), btn = $("#filter-btn");
    const renderFilters = () => {
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
      // Seçili filtreler araç çubuğunda kaldırılabilir etiket olarak görünür.
      const active = [];
      if (f.bolge) active.push(["bolge", (o.regions.find((r) => r.id === f.bolge) || {}).ad || f.bolge]);
      if (f.il) active.push(["il", f.il]);
      if (f.road) active.push(["road", roadName(f.road)]);
      if (f.durum) active.push(["durum", (DURUM.find((d) => d[0] === f.durum) || [])[1]]);
      $("#active-filters").innerHTML = active.map(([k, label]) => `<button type="button" class="af-chip" data-clear="${k}" title="Filtreyi kaldır">${esc(label)}
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></button>`).join("");
      $("#filter-count").hidden = !active.length;
      $("#filter-count").textContent = active.length;
      btn.classList.toggle("is-on", active.length > 0);
      renderChips();
    };
    const apply = (f) => { M.setFilter(f); renderFilters(); };
    const openPop = (open) => { pop.hidden = !open; btn.setAttribute("aria-expanded", String(open)); if (open) renderFilters(); };
    btn.addEventListener("click", () => openPop(pop.hidden));
    $("#fp-close").addEventListener("click", () => openPop(false));
    $("#fp-clear").addEventListener("click", () => apply({ bolge: "", il: "", road: "", durum: "", reset: true }));
    pop.addEventListener("click", (e) => {
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
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) openPop(false); });
    // Dışarı tıklanınca kapanır. (Çip tıklanınca liste yeniden çizildiği için hedef sayfadan çıkmış olabilir; o tıklama içeridedir.)
    document.addEventListener("click", (e) => { if (!pop.hidden && e.target.isConnected && !pop.contains(e.target) && !btn.contains(e.target)) openPop(false); });
    renderFilters();

    // Arama: yazdıkça en fazla 8 sonuç; seçilen noktaya gidilir ve açılır pencere açılır.
    const q = $("#map-q"), list = $("#map-q-list");
    let items = [], active = -1;
    const TYPE_LABEL = { kopru: "Köprü / tünel", gise: "Gişe", serbest: "Serbest geçiş" };
    const close = () => { list.hidden = true; q.setAttribute("aria-expanded", "false"); };
    const render = () => {
      if (!q.value.trim()) { close(); return; }
      list.innerHTML = items.length ? items.map((x, i) => `<li role="option" id="mq-${i}" data-id="${esc(x.id)}" aria-selected="${i === active}">
        <span class="o-name">${esc(x.name)}</span><span class="o-sub">${esc(TYPE_LABEL[x.type] || "")}${x.sub ? " · " + esc(x.sub) : ""}</span></li>`).join("")
        : `<li class="o-empty">Sonuç yok</li>`;
      list.hidden = false;
      q.setAttribute("aria-expanded", "true");
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
  }

  // ---------------------------------------------------------------- başlatma

  async function main() {
    bindTabs();
    bindCrossings();
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
    renderAnnouncements(data, now_);
    renderFree(data);
    renderCalendar(data, now_);
    renderEvents(data, now_);
    renderSources(data, now_);
    renderDocuments(data);
    $("#footer").textContent = `Kaynak: KGM resmi tarifeleri · ${data.run_interval_minutes || 30} dakikada bir kontrol edilir.`;

    const helpers = { esc, money, date, dateTime, className };
    const hesap = window.RadarHesap;
    if (hesap) {
      try {
        const r = hesap.init({ table, helpers, cls: cls_, map: window.RadarMap, onClass: (c) => setClassEverywhere(c, "hesap") });
        if (r.fromHash) selectTab("rota");
      } catch (e) { console.error("Ücret hesabı açılamadı", e); }
    }
    renderCrossings(data, now_);
    if (window.RadarMap) {
      try {
        window.RadarMap.init({
          data, cls: cls_, helpers,
          stations: hesap ? hesap.allStations() : [],
          roads: hesap ? hesap.roads() : [],
          onShowCrossing: openCrossing,
          popupExtra: (p) => (hesap ? hesap.popupHtml(p) : ""),
          onTrip: (role, key) => {
            selectTab("rota");
            const done = hesap && hesap.pick(role, key);
            if (done && window.matchMedia("(max-width: 900px)").matches) $("#trip-result").scrollIntoView({ behavior: "smooth", block: "start" });
          },
        });
        if (hesap) hesap.redraw();
        bindMapTools(hesap);
      } catch (e) { console.error("Harita açılamadı", e); }
    }
    // Paylaşılan bir hesap bağlantısı aynı sekmede açılırsa (yalnızca # değişir) hesap yenilenir.
    window.addEventListener("hashchange", () => { if (hesap) { hesap.reload(); selectTab("rota"); } });
  }

  main();
})();
