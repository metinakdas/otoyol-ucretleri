"use strict";

/*
 * Ücret hesabı: giriş ve çıkış gişesi + araç sınıfı → KGM tarifesindeki ücret ve mesafe.
 * Veri: data/ucret-tablosu.json (KGM tarife PDF'lerinden radarın çıkardığı gişe-gişe tablolar).
 * Seçim adres çubuğunda tutulur (#hesap=otoyol/giriş/çıkış/sınıf); bağlantı paylaşılabilir.
 */
window.RadarHesap = (function () {
  const CLASS_SHORT = { "1": "Otomobil", "2": "Minibüs", "3": "3 aks", "4": "4-5 aks", "5": "6+ aks", "6": "Motosiklet" };
  const LIST_LIMIT = 80;
  const NEAR_M = 1500;

  const S = {
    h: null, table: null, roads: [], stations: [], byKey: new Map(),
    entry: null, exit: null, cls: "1", onClass: null, map: null,
  };
  const $ = (sel) => document.querySelector(sel);

  // ------------------------------------------------------------ yardımcılar

  const FOLD = { "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u" };
  function fold(s) {
    return String(s || "").toLocaleLowerCase("tr").replace(/[çğıöşüâîû]/g, (c) => FOLD[c]).replace(/[^a-z0-9]+/g, " ").trim();
  }
  function distM(a, b) {
    const R = 6371000, r = Math.PI / 180;
    const dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
    const x = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  }
  const hasPos = (s) => s && typeof s.lat === "number" && typeof s.lon === "number";
  const fmtKm = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 1 });
  const fmtNum = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDay = new Intl.DateTimeFormat("tr-TR", { day: "2-digit", month: "2-digit", year: "numeric", timeZone: "Europe/Istanbul" });
  function className(k) {
    const d = S.table && S.table.siniflar && S.table.siniflar[k];
    return d ? `${k}. sınıf · ${d}` : `${k}. sınıf`;
  }

  // ------------------------------------------------------------ tablo

  function index(table) {
    S.roads = (table.otoyollar || []).filter((o) => Array.isArray(o.istasyonlar) && o.istasyonlar.length > 1);
    S.stations = [];
    S.byKey.clear();
    S.roads.forEach((o, oi) => {
      o.istasyonlar.forEach((st, i) => {
        const s = { key: `${oi}:${i}`, oi, i, ad: st.ad, lat: st.lat, lon: st.lon, road: o,
          search: fold([st.ad, o.ad, o.yol].join(" ")), nameKey: fold(st.ad) };
        S.stations.push(s);
        S.byKey.set(s.key, s);
      });
    });
  }

  function cell(grid, a, b) {
    const hi = Math.max(a, b), lo = Math.min(a, b);
    const row = grid && grid[hi];
    return row && row[lo] != null ? row[lo] : null;
  }
  // a = giriş, b = çıkış. Tablo alt üçgendir: ucret[i][j] (j < i) "j'den gir, i'den çık".
  // Yöne bağlı tarifelerde ters yön ucret_geri[i][j]: "i'den gir, j'den çık".
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

  // ------------------------------------------------------------ seçenek listeleri

  function optionsFor(role, q) {
    const other = role === "giris" ? S.exit : S.entry;
    let pool = other ? S.stations.filter((s) => s.oi === other.oi && s.i !== other.i) : S.stations;
    const tokens = fold(q).split(" ").filter(Boolean);
    if (tokens.length) {
      // Diğer uç seçiliyse otoyol zaten belli: yalnızca gişe adına bakılır.
      const field = other ? "nameKey" : "search";
      pool = pool.filter((s) => tokens.every((t) => s[field].includes(t)));
      const qk = fold(q);
      const rank = (s) => (s.nameKey.startsWith(qk) ? 0 : s.nameKey.split(" ").some((w) => w.startsWith(tokens[0])) ? 1 : s.nameKey.includes(qk) ? 2 : 3);
      pool = pool.slice().sort((a, b) => rank(a) - rank(b));
    }
    const items = [];
    if (other) {
      items.push({ head: `${other.road.ad} · ${other.ad} ile` });
      pool.forEach((s) => {
        const f = role === "cikis" ? fare(other, s, S.cls) : fare(s, other, S.cls);
        const d = km(other, s);
        items.push({ key: s.key, name: s.ad, sub: d != null ? `${fmtKm.format(d)} km` : "", price: f != null ? fmtNum.format(f) + " TL" : "—" });
      });
      return items;
    }
    let lastRoad = -1;
    pool.slice(0, tokens.length ? 200 : LIST_LIMIT * 4).forEach((s) => {
      if (!tokens.length && s.oi !== lastRoad) { items.push({ head: s.road.ad }); lastRoad = s.oi; }
      items.push({ key: s.key, name: s.ad, sub: tokens.length ? s.road.ad : "" });
    });
    return items;
  }

  // ------------------------------------------------------------ açılır liste (combobox)

  function combo(role) {
    const input = $(`#trip-${role}`);
    const list = $(`#trip-${role}-list`);
    let items = [], active = -1;

    function render() {
      const esc = S.h.esc;
      const picks = items.filter((x) => x.key);
      if (!picks.length) {
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
      input.setAttribute("aria-activedescendant", active >= 0 ? `${role}-opt-${active}` : "");
      const el = active >= 0 && list.querySelector(`#${role}-opt-${active}`);
      if (el) el.scrollIntoView({ block: "nearest" });
    }
    function open(all) {
      items = optionsFor(role, all ? "" : input.value);
      active = -1;
      render();
    }
    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }
    function choose(key) {
      close();
      pick(role, key);
    }
    input.addEventListener("focus", () => { input.select(); open(true); });
    input.addEventListener("input", () => { open(false); });
    input.addEventListener("blur", () => setTimeout(() => {
      close();
      syncInputs();
    }, 120));
    input.addEventListener("keydown", (e) => {
      const n = items.filter((x) => x.key).length;
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) open(false); active = Math.min(n - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const picks = items.filter((x) => x.key);
        const x = picks[active >= 0 ? active : 0];
        if (x) { choose(x.key); input.blur(); }
      } else if (e.key === "Escape") { close(); syncInputs(); }
    });
    list.addEventListener("mousedown", (e) => e.preventDefault());
    list.addEventListener("click", (e) => {
      const li = e.target.closest("[data-key]");
      if (li) { choose(li.dataset.key); input.blur(); }
    });
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

  function swap() {
    [S.entry, S.exit] = [S.exit, S.entry];
    update();
  }

  function setClass(cls, silent) {
    if (!CLASS_SHORT[cls]) return;
    S.cls = cls;
    renderClasses();
    if (!silent && S.onClass) S.onClass(cls);
    update(true);
  }

  // ------------------------------------------------------------ çizim

  function renderClasses() {
    const esc = S.h.esc;
    $("#trip-classes").innerHTML = Object.keys(CLASS_SHORT).map((k) => `
      <button type="button" data-cls="${k}" aria-pressed="${k === S.cls}" title="${esc(className(k))}">
        <span class="c-n">${k}</span><span class="c-l">${esc(CLASS_SHORT[k])}</span></button>`).join("");
  }

  // Boş fiş: ne yapılacağını yazıyla anlatmak yerine sonucun yerini gösterir.
  function ghostHtml(inName, outName, note) {
    const esc = S.h.esc;
    return `<div class="ticket ghost" aria-hidden="${note ? "false" : "true"}">
      <div class="t-route">
        <div class="t-stop in"><small><span class="tag tag-in">G</span>GİRİŞ</small><b>${inName ? esc(inName) : "—"}</b></div>
        <div class="t-arrow"><svg viewBox="0 0 46 12" aria-hidden="true"><path d="M1 6h41M36 1l6 5-6 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        <div class="t-stop out"><small>ÇIKIŞ<span class="tag tag-out">Ç</span></small><b>${outName ? esc(outName) : "—"}</b></div>
      </div>
      <div class="t-price"><small>${esc(S.cls)}. sınıf</small><strong>—<span class="cur">TL</span></strong></div>
      ${note ? `<p class="ghost-note">${esc(note)}</p>` : ""}
    </div>`;
  }

  function emptyHtml() {
    if (!S.table) return ghostHtml(null, null, "Ücret tablosu hazırlanıyor.");
    return ghostHtml(null, null, "");
  }

  function ticketHtml(a, b) {
    const h = S.h, esc = h.esc;
    const f = fares(a, b);
    const d = km(a, b);
    const o = a.road;
    const v = f ? f[Number(S.cls) - 1] : null;
    const no = String(((a.oi + 1) * 7919 + Math.min(a.i, b.i) * 131 + Math.max(a.i, b.i) * 17) % 1000000).padStart(6, "0");
    const rows = f ? Object.keys(CLASS_SHORT).map((k) => `<tr class="${k === S.cls ? "is-on" : ""}"><td>${esc(k)}. sınıf · ${esc(CLASS_SHORT[k])}</td>
      <td>${typeof f[k - 1] === "number" ? esc(fmtNum.format(f[k - 1])) + " TL" : "—"}</td></tr>`).join("") : "";
    const doc = o.belge && /^https?:\/\//i.test(o.belge) ? `<a href="${esc(o.belge)}" target="_blank" rel="noopener noreferrer">KGM belgesi</a>` : "KGM";
    const posNote = !hasPos(a) || !hasPos(b) ? `<div class="t-note">Konumu bilinmeyen gişe: güzergâh çizilemedi.</div>` : "";
    return `<article class="ticket" aria-label="Geçiş ücreti">
      <div class="t-head"><span class="t-title">Geçiş fişi</span><span class="t-no">Nº ${no} · ${esc(fmtDay.format(new Date()))}</span></div>
      <div class="t-route">
        <div class="t-stop in"><small><span class="tag tag-in">G</span>GİRİŞ</small><b>${esc(a.ad)}</b></div>
        <div class="t-arrow"><svg viewBox="0 0 46 12" aria-hidden="true"><path d="M1 6h41M36 1l6 5-6 5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>${d != null ? esc(fmtKm.format(d)) + " km" : ""}</div>
        <div class="t-stop out"><small>ÇIKIŞ<span class="tag tag-out">Ç</span></small><b>${esc(b.ad)}</b></div>
      </div>
      <div class="t-road">${o.yol ? `<span class="ref">${esc(o.yol)}</span>` : ""}${esc(o.ad)}</div>
      <div class="t-price"><small>${esc(S.cls)}. sınıf<br>${esc(CLASS_SHORT[S.cls])}</small>
        <span class="stamp" aria-hidden="true">KGM<br>tarifesi</span>
        <strong>${v != null ? esc(fmtNum.format(v)) + '<span class="cur">TL</span>' : "—"}</strong></div>
      ${v == null ? `<div class="t-note">Tarifede bu sınıf için ücret yok.</div>` : ""}
      ${rows ? `<table class="t-classes"><tbody>${rows}</tbody></table>` : ""}
      ${posNote}
      <div class="t-foot"><span>KDV dahil${o.yonlu ? " · yöne göre değişir" : " · iki yön aynı"}</span><span>${doc}</span></div>
    </article>
    <div class="trip-actions">
      <button type="button" class="tool-btn" data-trip-action="fit" title="Güzergâhı haritada göster">
        <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="6" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M10 1.5v4M10 14.5v4M1.5 10h4M14.5 10h4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>Haritada</button>
      <button type="button" class="tool-btn" data-trip-action="clear" title="Yeni hesap">
        <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10a6 6 0 1 0 1.8-4.3M4 3v3.5h3.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>Yeni hesap</button>
    </div>`;
  }

  function partialHtml(s, role) {
    return ghostHtml(role === "giris" ? s.ad : null, role === "cikis" ? s.ad : null, "");
  }

  function update(keepView) {
    syncInputs();
    const out = $("#trip-result");
    const a = S.entry, b = S.exit;
    if (a && b) out.innerHTML = ticketHtml(a, b);
    else if (a || b) out.innerHTML = partialHtml(a || b, a ? "giris" : "cikis");
    else out.innerHTML = emptyHtml();
    drawRoute(keepView);
    writeHash();
  }

  // ------------------------------------------------------------ harita

  // Tablodaki sıra yol boyuncadır; kola ayrılan gişeler (ör. bağlantı yolları) çizgiyi saptırmasın diye atlanır.
  function routePath(a, b) {
    const o = a.road;
    const step = a.i < b.i ? 1 : -1;
    let pts = [];
    for (let i = a.i; i !== b.i + step; i += step) {
      const st = o.istasyonlar[i];
      if (hasPos(st)) pts.push({ lat: st.lat, lon: st.lon, ad: st.ad, end: i === a.i || i === b.i });
    }
    let changed = true;
    while (changed && pts.length > 2) {
      changed = false;
      for (let k = 1; k < pts.length - 1; k++) {
        if (pts[k].end) continue;
        const direct = distM(pts[k - 1], pts[k + 1]);
        const via = distM(pts[k - 1], pts[k]) + distM(pts[k], pts[k + 1]);
        if (direct > 200 && via / direct > 1.45) { pts.splice(k, 1); changed = true; break; }
      }
    }
    return pts.map((p) => [p.lat, p.lon]);
  }

  function drawRoute(keepView) {
    if (!S.map || !S.map.showRoute) return;
    const a = S.entry, b = S.exit;
    const stop = (s, role) => (hasPos(s) ? { lat: s.lat, lon: s.lon, name: s.ad, role } : null);
    if (a && b) {
      S.map.showRoute({ path: hasPos(a) && hasPos(b) ? routePath(a, b) : [], entry: stop(a, "in"), exit: stop(b, "out"), fit: !keepView });
    } else if (a || b) {
      S.map.showRoute({ path: [], entry: a ? stop(a, "in") : null, exit: b ? stop(b, "out") : null, fit: !keepView });
    } else {
      S.map.clearRoute();
    }
  }

  // ------------------------------------------------------------ adres çubuğu

  function writeHash() {
    try {
      const a = S.entry, b = S.exit;
      const parts = [];
      if (a || b) {
        const o = (a || b).road;
        parts.push(`hesap=${encodeURIComponent(o.id || "")}/${a ? a.i : ""}/${b ? b.i : ""}/${S.cls}`);
      }
      const hash = parts.length ? "#" + parts.join("&") : "";
      if (location.hash !== hash) history.replaceState(null, "", location.pathname + location.search + hash);
    } catch (e) { /* önemli değil */ }
  }

  function readHash() {
    const m = /(?:^#|&)hesap=([^&]*)/.exec(location.hash || "");
    if (!m) return false;
    const [id, gi, ci, cls] = decodeURIComponent(m[1]).split("/");
    const oi = S.roads.findIndex((o) => o.id === id);
    if (oi < 0) return false;
    if (CLASS_SHORT[cls]) S.cls = cls;
    if (gi !== "" && S.byKey.has(`${oi}:${gi}`)) S.entry = S.byKey.get(`${oi}:${gi}`);
    if (ci !== "" && S.byKey.has(`${oi}:${ci}`)) S.exit = S.byKey.get(`${oi}:${ci}`);
    return !!(S.entry || S.exit);
  }

  // ------------------------------------------------------------ dışa açık

  function stationsNear(lat, lon, name) {
    if (!S.stations.length) return [];
    const p = { lat, lon };
    const nk = fold(String(name || "").replace(/gişe(ler)?(i|si)?/gi, ""));
    return S.stations
      .map((s) => ({ s, d: hasPos(s) ? distM(p, s) : Infinity }))
      .filter((x) => x.d <= NEAR_M || (nk && x.s.nameKey === nk && x.d <= 15000))
      .sort((x, y) => x.d - y.d)
      .map((x) => x.s);
  }

  function popupHtml(p) {
    const list = Array.isArray(p.stations) ? p.stations.map((k) => S.byKey.get(k)).filter(Boolean) : stationsNear(p.lat, p.lon, p.name).slice(0, 1);
    if (!list.length) return "";
    const esc = S.h.esc;
    // Aynı noktada birden çok tarife varsa (ör. iki otoyolun kesiştiği gişe) her biri ayrı satır.
    return list.map((s) => `<div class="pop-trip">
      ${list.length > 1 ? `<span class="pop-trip-s">${esc(s.road.yol || "")} ${esc(s.road.ad)}</span>` : ""}
      <button type="button" data-trip-role="giris" data-trip-key="${esc(s.key)}"><span class="tag tag-in">G</span>Giriş</button>
      <button type="button" data-trip-role="cikis" data-trip-key="${esc(s.key)}"><span class="tag tag-out">Ç</span>Çıkış</button>
    </div>`).join("");
  }

  function allStations() { return S.stations; }
  function redraw() { drawRoute(false); }

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
    if (S.table) {
      combo("giris");
      combo("cikis");
    } else {
      $("#trip-giris").disabled = true;
      $("#trip-cikis").disabled = true;
    }
    $("#trip-swap").addEventListener("click", swap);
    $("#trip-classes").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cls]");
      if (b) setClass(b.dataset.cls);
    });
    $("#trip-result").addEventListener("click", (e) => {
      const b = e.target.closest("[data-trip-action]");
      if (!b) return;
      if (b.dataset.tripAction === "clear") { S.entry = null; S.exit = null; update(); $("#trip-giris").focus(); }
      else drawRoute(false);
    });
    $("#trip").addEventListener("submit", (e) => e.preventDefault());
    update();
    if (fromHash && S.cls !== opts.cls && S.onClass) S.onClass(S.cls);
    return { ready: !!S.table, fromHash };
  }

  return { init, pick, setClass: (c) => setClass(c, true), popupHtml, stationsNear, fold, allStations, redraw };
})();
