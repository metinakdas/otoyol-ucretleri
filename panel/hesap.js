"use strict";

/*
 * Ücret hesabı: giriş ve çıkış gişesi + araç sınıfı → KGM tarifesindeki ücret ve mesafe.
 * Veri: data/ucret-tablosu.json (KGM tarife PDF'lerindeki gişe-gişe tablolar; gişe konumları config/giseler.yaml).
 * Seçim adres çubuğunda tutulur (#hesap=otoyol/giriş/çıkış/sınıf), bağlantı paylaşılabilir.
 */
window.RadarHesap = (function () {
  const CLASSES = {
    "1": { l: "Otomobil", i: '<path d="M3 15.5h1.5M9.5 15.5h11M25.5 15.5H27v-3.2c0-.9-.6-1.6-1.4-1.8l-3.6-.9-2.6-3a2.5 2.5 0 0 0-1.9-.9H11a2.5 2.5 0 0 0-2 1l-2.2 3.1-2.4.6A1.8 1.8 0 0 0 3 12.2v3.3"/><circle cx="7" cy="15.5" r="2.2"/><circle cx="23" cy="15.5" r="2.2"/>' },
    "2": { l: "Minibüs", i: '<path d="M3 15.5h1.5M9.5 15.5h11M25.5 15.5H27v-4l-3-5.5H5a2 2 0 0 0-2 2v7.5M17 6v4.5h8.6M3 10.5h14"/><circle cx="7" cy="15.5" r="2.2"/><circle cx="23" cy="15.5" r="2.2"/>' },
    "3": { l: "3 akslı", i: '<path d="M2 15.5h1.5M8.5 15.5h4M17.5 15.5h1M23.5 15.5H28v-4.5l-2.5-4H20v9M2 15.5V5h18"/><circle cx="6" cy="15.5" r="2"/><circle cx="15" cy="15.5" r="2"/><circle cx="21" cy="15.5" r="2"/>' },
    "4": { l: "4-5 akslı", i: '<path d="M1 15.5h1M6 15.5h1.5M11.5 15.5h4M19.5 15.5h1M24.5 15.5H29v-4.5l-2-3.5h-5v8M1 15.5V5h19v10.5"/><circle cx="4" cy="15.5" r="1.8"/><circle cx="9.5" cy="15.5" r="1.8"/><circle cx="17.5" cy="15.5" r="1.8"/><circle cx="22.5" cy="15.5" r="1.8"/>' },
    "5": { l: "6+ akslı", i: '<path d="M1 15.5h.5M10 15.5h3M24 15.5H29v-4.5l-2-3.5h-4v8M1 15.5V5h20v10.5"/><circle cx="3" cy="15.5" r="1.5"/><circle cx="6.5" cy="15.5" r="1.5"/><circle cx="15" cy="15.5" r="1.5"/><circle cx="18.5" cy="15.5" r="1.5"/><circle cx="22" cy="15.5" r="1.5"/>' },
    "6": { l: "Motosiklet", i: '<circle cx="7" cy="14.5" r="3"/><circle cx="23" cy="14.5" r="3"/><path d="M7 14.5l4.5-6h5l3 6M16.5 8.5l1.5-3h3M11.5 8.5 10 6H7.5M20 14.5h-3l-2-3"/>' },
  };
  const NEAR_M = 1500;
  const S = { h: null, table: null, roads: [], stations: [], byKey: new Map(), entry: null, exit: null, cls: "1", onClass: null, map: null };
  const $ = (sel) => document.querySelector(sel);

  // ------------------------------------------------------------ yardımcılar

  const FOLD = { "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u" };
  function fold(s) {
    return String(s || "").toLocaleLowerCase("tr").replace(/[çğıöşüâîû]/g, (c) => FOLD[c]).replace(/[^a-z0-9]+/g, " ").trim();
  }
  function distM(a, b) {
    const r = Math.PI / 180;
    const x = Math.sin((b.lat - a.lat) * r / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin((b.lon - a.lon) * r / 2) ** 2;
    return 12742000 * Math.asin(Math.sqrt(x));
  }
  const hasPos = (s) => s && typeof s.lat === "number" && typeof s.lon === "number";
  const fmtKm = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });
  const fmtNum = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const icon = (k, cls) => `<svg viewBox="0 0 30 20" class="${cls || ""}" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${CLASSES[k].i}</svg>`;

  // ------------------------------------------------------------ tablo

  function index(table) {
    S.roads = (table.otoyollar || []).filter((o) => Array.isArray(o.istasyonlar) && o.istasyonlar.length > 1);
    S.stations = [];
    S.byKey.clear();
    S.roads.forEach((o, oi) => o.istasyonlar.forEach((st, i) => {
      const s = { key: `${oi}:${i}`, oi, i, ad: st.ad, lat: st.lat, lon: st.lon, il: st.il || null, road: o,
        search: fold([st.ad, st.il, o.ad, o.yol].join(" ")), nameKey: fold(st.ad) };
      S.stations.push(s);
      S.byKey.set(s.key, s);
    }));
  }

  function cell(grid, a, b) {
    const row = grid && grid[Math.max(a, b)];
    const v = row ? row[Math.min(a, b)] : null;
    return v == null ? null : v;
  }
  // a = giriş, b = çıkış. ucret[i][j] (j < i): "j'den gir, i'den çık"; yöne bağlıysa ters yön ucret_geri[i][j].
  function fares(a, b) {
    if (!a || !b || a.oi !== b.oi || a.i === b.i) return null;
    const o = a.road;
    const c = o.yonlu && a.i > b.i && Array.isArray(o.ucret_geri) ? cell(o.ucret_geri, a.i, b.i) : cell(o.ucret, a.i, b.i);
    return Array.isArray(c) ? c : null;
  }
  function fare(a, b, cls) {
    const f = fares(a, b);
    const v = f ? f[Number(cls) - 1] : null;
    return typeof v === "number" ? v : null;
  }
  function km(a, b) {
    if (!a || !b || a.oi !== b.oi || a.i === b.i) return null;
    const v = cell(a.road.km, a.i, b.i);
    return typeof v === "number" ? v : null;
  }

  // ------------------------------------------------------------ seçenekler

  function optionsFor(role, q) {
    const other = role === "giris" ? S.exit : S.entry;
    let pool = other ? S.stations.filter((s) => s.oi === other.oi && s.i !== other.i) : S.stations;
    const tokens = fold(q).split(" ").filter(Boolean);
    if (tokens.length) {
      const field = other ? "nameKey" : "search";   // diğer uç seçiliyse otoyol belli: yalnızca gişe adı
      pool = pool.filter((s) => tokens.every((t) => s[field].includes(t)));
      const qk = fold(q);
      const rank = (s) => (s.nameKey.startsWith(qk) ? 0 : s.nameKey.split(" ").some((w) => w.startsWith(tokens[0])) ? 1 : s.nameKey.includes(qk) ? 2 : 3);
      pool = pool.slice().sort((a, b) => rank(a) - rank(b));
    }
    const items = [];
    if (other) {
      items.push({ head: other.road.ad });
      pool.forEach((s) => {
        const f = role === "cikis" ? fare(other, s, S.cls) : fare(s, other, S.cls);
        const d = km(other, s);
        items.push({ key: s.key, name: s.ad, sub: [s.il, d != null ? fmtKm.format(d) + " km" : ""].filter(Boolean).join(" · "),
          price: f != null ? fmtNum.format(f) + " ₺" : "—" });
      });
      return items;
    }
    let last = -1;
    pool.slice(0, 400).forEach((s) => {
      if (!tokens.length && s.oi !== last) { items.push({ head: (s.road.yol ? s.road.yol + " · " : "") + s.road.ad }); last = s.oi; }
      items.push({ key: s.key, name: s.ad, sub: tokens.length ? [s.il, s.road.ad].filter(Boolean).join(" · ") : s.il || "" });
    });
    return items;
  }

  // ------------------------------------------------------------ açılır liste

  function combo(role) {
    const input = $(`#trip-${role}`);
    const list = $(`#trip-${role}-list`);
    let items = [], active = -1;
    const picks = () => items.filter((x) => x.key);

    function render() {
      const esc = S.h.esc;
      if (!picks().length) {
        list.innerHTML = `<li class="o-empty" role="option" aria-disabled="true">Eşleşen gişe yok</li>`;
      } else {
        let n = 0;
        list.innerHTML = items.map((x) => {
          if (x.head) return `<li class="o-head" role="presentation">${esc(x.head)}</li>`;
          const idx = n++;
          return `<li role="option" id="${role}-opt-${idx}" data-key="${esc(x.key)}" aria-selected="${idx === active}">
            <span class="o-name">${esc(x.name)}</span>${x.sub ? `<span class="o-sub">${esc(x.sub)}</span>` : ""}
            ${x.price ? `<span class="o-price">${esc(x.price)}</span>` : ""}</li>`;
        }).join("");
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      if (active >= 0) input.setAttribute("aria-activedescendant", `${role}-opt-${active}`); else input.removeAttribute("aria-activedescendant");
      const el = active >= 0 && list.querySelector(`#${role}-opt-${active}`);
      if (el) el.scrollIntoView({ block: "nearest" });
    }
    const open = (all) => { items = optionsFor(role, all ? "" : input.value); active = -1; render(); };
    const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant"); };
    const choose = (key) => { close(); pick(role, key); input.blur(); };

    input.addEventListener("focus", () => { input.select(); open(true); });
    input.addEventListener("input", () => open(false));
    input.addEventListener("blur", () => setTimeout(() => { close(); syncInputs(); }, 120));
    input.addEventListener("keydown", (e) => {
      const n = picks().length;
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) open(false); active = Math.min(n - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") { e.preventDefault(); const x = picks()[active >= 0 ? active : 0]; if (x) choose(x.key); }
      else if (e.key === "Escape") { close(); input.blur(); }
    });
    list.addEventListener("mousedown", (e) => e.preventDefault());
    list.addEventListener("click", (e) => { const li = e.target.closest("[data-key]"); if (li) choose(li.dataset.key); });
  }

  function syncInputs() {
    const gi = $("#trip-giris"), ci = $("#trip-cikis");
    if (document.activeElement !== gi) gi.value = S.entry ? S.entry.ad : "";
    if (document.activeElement !== ci) ci.value = S.exit ? S.exit.ad : "";
  }

  // ------------------------------------------------------------ seçim

  function pick(role, key) {
    const s = S.byKey.get(key);
    if (!s) return false;
    const other = role === "giris" ? S.exit : S.entry;
    if (other && (other.oi !== s.oi || other.i === s.i)) {
      // Diğer uç başka tarifedeyse aynı adlı gişeyi bu tarifede ara; yoksa temizle
      const same = other.oi !== s.oi ? S.stations.find((x) => x.oi === s.oi && x.nameKey === other.nameKey && x.i !== s.i) : null;
      if (role === "giris") S.exit = same || null; else S.entry = same || null;
    }
    if (role === "giris") S.entry = s; else S.exit = s;
    update();
    return !!(S.entry && S.exit);
  }
  function swap() { [S.entry, S.exit] = [S.exit, S.entry]; update(); }
  function setClass(cls, silent) {
    if (!CLASSES[cls]) return;
    S.cls = cls;
    renderClasses();
    if (!silent && S.onClass) S.onClass(cls);
    update(true);
  }

  // ------------------------------------------------------------ çizim

  function renderClasses() {
    $("#trip-classes").innerHTML = Object.keys(CLASSES).map((k) => `
      <button type="button" data-cls="${k}" aria-pressed="${k === S.cls}" title="${k}. sınıf · ${CLASSES[k].l}">
        ${icon(k)}<span class="v-l">${CLASSES[k].l}</span><span class="v-n">${k}. sınıf</span></button>`).join("");
  }

  function resultHtml(a, b) {
    const esc = S.h.esc;
    const f = fares(a, b);
    const d = km(a, b);
    const o = a.road;
    const v = f ? f[Number(S.cls) - 1] : null;
    const arrow = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8h11M9.5 4.5 13 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const rows = f ? Object.keys(CLASSES).map((k) => `<li class="${k === S.cls ? "is-on" : ""}">${icon(k)}<span>${k}. sınıf · ${CLASSES[k].l}</span>
      <b>${typeof f[k - 1] === "number" ? esc(fmtNum.format(f[k - 1])) + " ₺" : "—"}</b></li>`).join("") : "";
    const doc = o.belge && /^https?:\/\//i.test(o.belge) ? `<a href="${esc(o.belge)}" target="_blank" rel="noopener noreferrer">KGM tarifesi ↗</a>` : "KGM tarifesi";
    const valid = o.gecerlilik ? `Geçerlilik ${esc(S.h.date(o.gecerlilik))}` : "KDV dahil";
    return `<article class="fare" aria-label="Geçiş ücreti">
      <div class="fare-main">
        <div class="fare-label">${S.cls}. sınıf · ${CLASSES[S.cls].l}</div>
        <div class="fare-amount">${v != null ? esc(fmtNum.format(v)) + '<span class="cur">₺</span>' : "—"}</div>
        <div class="fare-trip"><span>${esc(a.ad)}</span>${arrow}<span>${esc(b.ad)}</span></div>
        <div class="fare-meta">${o.yol ? `<span class="ref">${esc(o.yol)}</span>` : ""}<span>${esc(o.ad)}</span>${d != null ? `<span>· ${esc(fmtKm.format(d))} km</span>` : ""}</div>
        ${v == null ? `<p class="fare-note">Tarifede bu sınıf için ücret yok.</p>` : ""}
        ${!hasPos(a) || !hasPos(b) ? `<p class="fare-note">Gişelerden birinin konumu kayıtlı değil; güzergâh çizilemedi.</p>` : ""}
      </div>
      ${rows ? `<ul class="fare-classes">${rows}</ul>` : ""}
      <div class="fare-foot"><span>${valid}${o.yonlu ? " · yöne göre değişir" : ""}</span>${doc}</div>
    </article>
    <div class="actions">
      <button type="button" class="btn" data-trip-action="swap"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 4v12M7 16l-3-3M7 16l3-3M13 16V4M13 4l-3 3M13 4l3 3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>Ters yön</button>
      <button type="button" class="btn" data-trip-action="copy"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8.5 11.5a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-.8.8M11.5 8.5a3 3 0 0 0-4.2 0L4.7 11.1a3 3 0 0 0 4.2 4.2l.8-.8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg><span>Bağlantıyı kopyala</span></button>
    </div>`;
  }

  function emptyHtml() {
    if (!S.table) return `<div class="result-empty"><strong>Ücret tablosu hazırlanıyor</strong>KGM tarifeleri okunduğunda hesap açılır.</div>`;
    const one = S.entry || S.exit;
    if (one) return `<div class="result-empty"><strong>${S.h.esc(one.ad)}</strong>${S.entry ? "Çıkış" : "Giriş"} gişesini seçin</div>`;
    return `<div class="result-empty"><strong>Giriş ve çıkış gişesini seçin</strong>ya da haritada bir gişeye dokunun</div>`;
  }

  function update(keepView) {
    syncInputs();
    $("#trip-result").innerHTML = S.entry && S.exit ? resultHtml(S.entry, S.exit) : emptyHtml();
    drawRoute(keepView);
    writeHash();
  }

  // ------------------------------------------------------------ harita

  // Tablo sırası yol boyuncadır; kola sapan gişeler çizgiyi saptırmasın diye atlanır.
  function routePath(a, b) {
    const o = a.road, step = a.i < b.i ? 1 : -1;
    const pts = [];
    for (let i = a.i; i !== b.i + step; i += step) {
      const st = o.istasyonlar[i];
      if (hasPos(st)) pts.push({ lat: st.lat, lon: st.lon, end: i === a.i || i === b.i });
    }
    let changed = true;
    while (changed && pts.length > 2) {
      changed = false;
      for (let k = 1; k < pts.length - 1; k++) {
        if (pts[k].end) continue;
        const direct = distM(pts[k - 1], pts[k + 1]);
        if (direct > 200 && (distM(pts[k - 1], pts[k]) + distM(pts[k], pts[k + 1])) / direct > 1.45) { pts.splice(k, 1); changed = true; break; }
      }
    }
    return pts.map((p) => [p.lat, p.lon]);
  }

  function drawRoute(keepView) {
    if (!S.map || !S.map.showRoute) return;
    const a = S.entry, b = S.exit;
    const stop = (s, role) => (hasPos(s) ? { lat: s.lat, lon: s.lon, name: s.ad, role } : null);
    if (!a && !b) { S.map.clearRoute(); return; }
    S.map.showRoute({ path: a && b && hasPos(a) && hasPos(b) ? routePath(a, b) : [],
      entry: a ? stop(a, "in") : null, exit: b ? stop(b, "out") : null, fit: !keepView });
  }

  // ------------------------------------------------------------ adres çubuğu

  function writeHash() {
    try {
      const a = S.entry, b = S.exit, o = (a || b) && (a || b).road;
      const hash = o ? `#hesap=${encodeURIComponent(o.id || "")}/${a ? a.i : ""}/${b ? b.i : ""}/${S.cls}` : "";
      if (location.hash !== hash) history.replaceState(null, "", location.pathname + location.search + hash);
    } catch (e) { /* önemli değil */ }
  }
  function readHash() {
    const m = /(?:^#|&)hesap=([^&]*)/.exec(location.hash || "");
    if (!m) return false;
    const [id, gi, ci, cls] = decodeURIComponent(m[1]).split("/");
    const oi = S.roads.findIndex((o) => o.id === id);
    if (oi < 0) return false;
    if (CLASSES[cls]) S.cls = cls;
    if (gi !== "" && S.byKey.has(`${oi}:${gi}`)) S.entry = S.byKey.get(`${oi}:${gi}`);
    if (ci !== "" && S.byKey.has(`${oi}:${ci}`)) S.exit = S.byKey.get(`${oi}:${ci}`);
    return !!(S.entry || S.exit);
  }

  async function copyLink(btn) {
    const label = btn.querySelector("span");
    try {
      await navigator.clipboard.writeText(location.href);
      label.textContent = "Kopyalandı";
    } catch (e) {
      label.textContent = "Kopyalanamadı";
    }
    setTimeout(() => { label.textContent = "Bağlantıyı kopyala"; }, 1600);
  }

  // ------------------------------------------------------------ dışa açık

  function popupHtml(p) {
    const list = Array.isArray(p.stations) ? p.stations.map((k) => S.byKey.get(k)).filter(Boolean) : [];
    if (!list.length) return "";
    const esc = S.h.esc;
    return list.map((s) => `<div class="pop-trip">
      ${list.length > 1 ? `<span class="pop-trip-s">${esc(s.road.yol ? s.road.yol + " · " : "")}${esc(s.road.ad)}</span>` : ""}
      <button type="button" class="btn" data-trip-role="giris" data-trip-key="${esc(s.key)}">Giriş</button>
      <button type="button" class="btn primary" data-trip-role="cikis" data-trip-key="${esc(s.key)}">Çıkış</button>
    </div>`).join("");
  }

  function stationsNear(lat, lon) {
    return S.stations.filter((s) => hasPos(s) && distM({ lat, lon }, s) <= NEAR_M);
  }

  function init(opts) {
    S.h = opts.helpers;
    S.table = opts.table && Array.isArray(opts.table.otoyollar) ? opts.table : null;
    S.cls = opts.cls || "1";
    S.onClass = opts.onClass;
    S.map = opts.map || null;
    if (S.table) index(S.table);
    if (!S.stations.length) S.table = null;
    const fromHash = S.table ? readHash() : false;
    renderClasses();
    if (S.table) { combo("giris"); combo("cikis"); }
    else { $("#trip-giris").disabled = true; $("#trip-cikis").disabled = true; }
    $("#trip-swap").addEventListener("click", swap);
    $("#trip-classes").addEventListener("click", (e) => { const b = e.target.closest("[data-cls]"); if (b) setClass(b.dataset.cls); });
    $("#trip-result").addEventListener("click", (e) => {
      const b = e.target.closest("[data-trip-action]");
      if (!b) return;
      if (b.dataset.tripAction === "swap") swap();
      else if (b.dataset.tripAction === "copy") copyLink(b);
    });
    $("#trip").addEventListener("submit", (e) => e.preventDefault());
    update();
    if (fromHash && S.cls !== opts.cls && S.onClass) S.onClass(S.cls);
    return { ready: !!S.table, fromHash };
  }

  return {
    init, pick, popupHtml, stationsNear, fold,
    setClass: (c) => setClass(c, true),
    allStations: () => S.stations,
    redraw: () => drawRoute(false),
    classIcon: (k) => icon(k),
    className: (k) => (CLASSES[k] ? CLASSES[k].l : ""),
  };
})();
