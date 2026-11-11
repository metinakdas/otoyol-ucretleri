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
  const S = {
    h: null, table: null, roads: [], stations: [], byKey: new Map(), entry: null, exit: null, cls: "1", onClass: null, map: null,
    links: new Map(), linkKeys: [], planCache: new Map(), alt: 0,
    extras: [], extra: new Set(),
  };
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
      const s = { key: `${oi}:${i}`, oi, i, ad: st.ad, lat: st.lat, lon: st.lon, il: st.il || null, bolge: st.bolge || null, road: o, serbest: !!st.serbest,
        search: fold([st.ad, st.il, o.ad, o.yol].join(" ")), nameKey: fold(st.ad) };
      S.stations.push(s);
      S.byKey.set(s.key, s);
    }));
    // Tarifeler arası bağlantılar (aynı kavşakta bir ücret sisteminden diğerine geçiş): config/giseler.yaml → baglantilar
    S.links.clear();
    S.planCache.clear();
    const find = (end) => {
      const oi = S.roads.findIndex((o) => o.id === (end && end.otoyol));
      if (oi < 0) return null;
      let s = S.byKey.get(`${oi}:${end.i}`);
      if (!s || (end.ad && s.nameKey !== fold(end.ad))) s = S.stations.find((x) => x.oi === oi && x.nameKey === fold(end.ad));
      return s || null;
    };
    // Bağlantı arasında geçilen serbest geçiş noktalarının (ara_serbest) ücretleri toplama eklenir;
    // tek_yon bağlantılar yalnızca a → b yönünde kullanılır.
    const sgsRow = (r) => {
      const o = S.roads.find((x) => x.id === (r && r.otoyol));
      const row = o && (o.serbest_gecis || [])[r.j];
      return row ? { road: o, ad: row.ad, yon: row.yon || r.yon || "", f: Array.isArray(row.ucret) ? row.ucret : null } : null;
    };
    (table.baglantilar || []).forEach((l) => {
      const a = find(l.a), b = find(l.b);
      if (!a || !b || a.oi === b.oi) return;
      const ara = l.ara_serbest || {};
      const dirs = [[a, b, ara.ab]];
      if (!l.tek_yon) dirs.push([b, a, ara.ba]);
      dirs.forEach(([x, y, rows]) => {
        const sgs = (rows || []).map(sgsRow).filter(Boolean);
        if (!S.links.has(x.key)) S.links.set(x.key, []);
        if (!S.links.get(x.key).some((e) => e.to === y.key)) S.links.get(x.key).push({ to: y.key, sgs, km: typeof l.yol_km === "number" ? l.yol_km : null });
      });
      [a, b].forEach((s) => { if (!S.links.has(s.key)) S.links.set(s.key, []); });
    });
    S.linkKeys = [...S.links.keys()];
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

  // Güzergâh planı: aynı tarifedeyse tek kalem; değilse bağlantı noktalarından geçen en az aktarmalı,
  // eşitlikte en ucuz yol (1. sınıf ücretine göre). Ücret, kalemlerin ayrı ayrı tarifelerinin toplamıdır.
  function planWith(a, b, penalty) {
    if (!a || !b || a.key === b.key) return null;
    const id = a.key + ">" + b.key + "@" + penalty;
    if (S.planCache.has(id)) return S.planCache.get(id);
    let legs = null;
    if (a.oi === b.oi) {
      legs = fares(a, b) ? [{ a, b }] : null;
    } else if (S.linkKeys.length) {
      // İki durumlu en kısa yol: bir düğüme ya bir tarife yolculuğuyla ("|L") ya da başlangıç/bağlantı
      // geçişiyle ("|T") varılır. Yolculuk yalnızca "|T" durumundan başlar; böylece aynı otoyoldan çıkıp
      // yeniden girmek (iki ayrı kalem) yol sayılmaz. Maliyet: toplam 1. sınıf ücreti + kalem başına küçük ceza.
      const nodes = [...new Set([a.key, b.key, ...S.linkKeys])].map((k) => S.byKey.get(k));
      const LEG_PENALTY = penalty;
      const dist = new Map(), prev = new Map(), done = new Set();
      const set = (state, c, from) => { if (c < (dist.has(state) ? dist.get(state) : Infinity)) { dist.set(state, c); prev.set(state, from); } };
      set(a.key + "|T", 0, null);
      let goal = null;
      while (true) {
        let u = null, du = Infinity;
        dist.forEach((c, st) => { if (!done.has(st) && c < du) { du = c; u = st; } });
        if (u === null) break;
        const [key, mode] = u.split("|");
        if (key === b.key) { goal = u; break; }
        done.add(u);
        const su = S.byKey.get(key);
        if (mode === "T") {
          nodes.forEach((v) => {   // aynı tarifede yolculuk (kalem)
            if (v.oi !== su.oi || v.key === su.key) return;
            const f = fare(su, v, "1");
            if (f != null) set(v.key + "|L", du + f + LEG_PENALTY, { from: u, leg: true });
          });
        } else {
          (S.links.get(key) || []).forEach((e) => {   // bağlantıdan diğer tarifeye geçiş (+ ara serbest geçişler)
            const c = du + e.sgs.reduce((t, g) => t + (g.f && typeof g.f[0] === "number" ? g.f[0] : 0), 0);
            set(e.to + "|T", c, { from: u, leg: false, link: e });
          });
        }
      }
      if (goal) {
        legs = [];
        for (let st = goal; prev.get(st); st = prev.get(st).from) {
          const p = prev.get(st);
          const to = S.byKey.get(st.split("|")[0]), from = S.byKey.get(p.from.split("|")[0]);
          if (p.leg) legs.unshift({ a: from, b: to });
          else {
            [...p.link.sgs].reverse().forEach((g) => legs.unshift({ sgs: true, road: g.road, ad: g.ad, yon: g.yon, f: g.f, km: null }));
            if (p.link.km != null) legs.unshift({ link: true, km: p.link.km });
          }
        }
        if (!legs.some((l) => !l.sgs && !l.link)) legs = null;
      }
    }
    // Kalemler: tarife yolculukları (a→b), ara serbest geçiş ücretleri (sgs) ve bağlantı yolu (link, yalnızca km).
    const result = legs && legs.length ? {
      legs: legs.map((l) => (l.sgs || l.link ? l : Object.assign(l, { f: fares(l.a, l.b), km: km(l.a, l.b) }))),
    } : null;
    if (result) {
      const paid = result.legs.filter((l) => !l.link);
      result.trips = result.legs.filter((l) => !l.sgs && !l.link);
      result.total = Object.keys(CLASSES).map((k) => {
        const parts = paid.map((l) => (l.f ? l.f[k - 1] : null));
        return parts.every((x) => typeof x === "number") ? parts.reduce((t, x) => t + x, 0) : null;
      });
      const kms = result.legs.filter((l) => !l.sgs).map((l) => l.km);
      result.km = kms.every((x) => typeof x === "number") ? kms.reduce((t, x) => t + x, 0) : null;
    }
    S.planCache.set(id, result);
    return result;
  }
  const planFare = (p, cls) => (p && typeof p.total[Number(cls) - 1] === "number" ? p.total[Number(cls) - 1] : null);

  // Güzergâh seçenekleri: "doğrudan" (en az kalem, eşitlikte en ucuz) ve varsa farklı bir "en ucuz" yol.
  // Ödenen ücret sürücünün gerçekte hangi yoldan gittiğine bağlıdır; ikisi de gösterilir, varsayılan doğrudandır.
  const DIRECT = 1e5, CHEAP = 15;
  const sig = (p) => p.legs.map((l) => (l.sgs ? "s:" + l.ad : l.link ? "" : l.a.key + ">" + l.b.key)).join(",");
  function plan(a, b) { return planWith(a, b, DIRECT); }
  function routes(a, b) {
    const d = planWith(a, b, DIRECT), c = a && b && a.oi !== b.oi ? planWith(a, b, CHEAP) : null;
    if (!d) return c ? [c] : [];
    if (!c || sig(c) === sig(d) || !(planFare(c, "1") < planFare(d, "1"))) return [d];
    return [d, c];
  }
  function chosen(a, b) {
    const r = routes(a, b);
    return r.length ? r[Math.min(S.alt, r.length - 1)] : null;
  }

  // ------------------------------------------------------------ seçenekler

  function optionsFor(role, q) {
    const other = role === "giris" ? S.exit : S.entry;
    const tokens = fold(q).split(" ").filter(Boolean);
    const qk = fold(q);
    const rank = (s) => (s.nameKey === qk ? -1 : s.nameKey.startsWith(qk) ? 0 : s.nameKey.split(" ").some((w) => w.startsWith(tokens[0])) ? 1 : s.nameKey.includes(qk) ? 2 : 3);
    const items = [];
    if (other) {
      // Diğer uç seçiliyse: ona ulaşılabilen bütün gişeler (önce aynı otoyol, sonra bağlantılı otoyollar).
      let pool = S.stations.filter((s) => s.key !== other.key && (!tokens.length || tokens.every((t) => s.search.includes(t))));
      const rows = pool.map((s) => ({ s, p: role === "cikis" ? plan(other, s) : plan(s, other) })).filter((x) => x.p);
      if (tokens.length) rows.sort((x, y) => rank(x.s) - rank(y.s) || (x.s.oi !== other.oi) - (y.s.oi !== other.oi));
      else rows.sort((x, y) => (x.s.oi !== other.oi) - (y.s.oi !== other.oi) || x.s.oi - y.s.oi || x.s.i - y.s.i);
      let last = -1;
      rows.forEach(({ s, p }) => {
        if (!tokens.length && s.oi !== last) { items.push({ head: (s.road.yol ? s.road.yol + " · " : "") + s.road.ad }); last = s.oi; }
        const f = planFare(p, S.cls);
        const via = p.trips.length > 1 ? `${p.trips.length} tarife` : "";
        items.push({ key: s.key, name: s.ad,
          sub: [tokens.length ? s.road.ad : s.il, p.km != null ? fmtKm.format(p.km) + " km" : "", via].filter(Boolean).join(" · "),
          price: f != null ? fmtNum.format(f) + " ₺" : "—" });
      });
      if (tokens.length && !rows.length && pool.length) items.push({ note: `${other.ad} ile bu gişe arasında bağlantılı tarife yok` });
      return items;
    }
    let pool = S.stations;
    if (tokens.length) {
      pool = pool.filter((s) => tokens.every((t) => s.search.includes(t)));
      pool = pool.slice().sort((a, b) => rank(a) - rank(b));
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
        const note = items.find((x) => x.note);
        list.innerHTML = `<li class="o-empty" role="option" aria-disabled="true">${esc(note ? note.note : "Eşleşen gişe yok")}</li>`;
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

  // ------------------------------------------------------------ köprü ve tüneller
  // KGM gişe tablolarına dahil olmayan geçişler (Avrasya Tüneli, Boğaz köprüleri) rotaya ayrıca eklenir.
  // Tabloya dahil olanlar (YSS, Osmangazi, 1915 Çanakkale) gişe ücretinin içindedir, iki kez sayılmaz.
  const XNOTE = {
    "15-temmuz-sehitler": "Yalnızca Avrupa → Asya yönünde ücretlidir",
    "fatih-sultan-mehmet": "Yalnızca Avrupa → Asya yönünde ücretlidir",
  };
  const CHECK = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 6.2 5 8.5l4.5-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function indexExtras(crossings, table) {
    const inTable = new Set();
    ((table && table.otoyollar) || []).forEach((o) => (o.dahil_gecisler || []).forEach((id) => inTable.add(id)));
    S.extras = (crossings || []).filter((c) => !inTable.has(c.id) && c.current && c.current.classes);
  }
  function xFare(c, cls) {
    const v = c.current.classes[cls];
    return v != null && v !== "" && !Number.isNaN(Number(v)) ? Number(v) : null;
  }
  const picked = () => S.extras.filter((c) => S.extra.has(c.id));
  // Seçili köprü/tünellerin sınıf başına toplamı; geçemeyen sınıf için null.
  function xTotal(cls) {
    let t = 0;
    for (const c of picked()) { const v = xFare(c, cls); if (v == null) return null; t += v; }
    return t;
  }
  const addFare = (base, cls) => { const x = xTotal(cls); return base == null || x == null ? null : Math.round((base + x) * 100) / 100; };
  function renderExtras() {
    const box = $("#trip-extras");
    if (!box) return;
    box.closest(".opt").hidden = !S.extras.length;
    box.innerHTML = S.extras.map((c) => {
      const v = xFare(c, S.cls);
      return `<button type="button" data-extra="${S.h.esc(c.id)}" aria-pressed="${S.extra.has(c.id)}">
        <span class="x-box">${CHECK}</span><span class="x-n">${S.h.esc(c.name)}</span>
        <span class="x-v${v == null ? " no" : ""}">${v != null ? S.h.esc(fmtNum.format(v)) + " ₺" : "Bu sınıf geçemez"}</span></button>`;
    }).join("");
    // Özet satırı: kapalıyken de seçim görünsün
    const sum = $("#extras-sum"), xs = picked(), t = xTotal(S.cls);
    if (sum) {
      sum.textContent = !xs.length ? "Eklenmedi"
        : `${xs.length === 1 ? xs[0].name : xs.length + " geçiş"}${t != null ? ` · +${fmtNum.format(t)} ₺` : " · geçemez"}`;
      sum.title = xs.map((c) => c.name).join(", ");
      sum.classList.toggle("is-set", xs.length > 0);
    }
  }
  function xLegsHtml(cls) {
    const esc = S.h.esc;
    return picked().map((c) => {
      const v = xFare(c, cls), g = c.current.gece, gv = g && g.classes ? g.classes[cls] : null;
      const sub = [XNOTE[c.id], gv != null ? `Gece ${g.saat || ""}: ${fmtNum.format(Number(gv))} ₺` : ""].filter(Boolean).join(" · ");
      return `<li class="is-x"><div class="leg-top"><span class="leg-road">${esc(c.name)}</span><b>${v != null ? esc(fmtNum.format(v)) + " ₺" : "Geçemez"}</b></div>
        ${sub ? `<div class="leg-trip">${esc(sub)}</div>` : ""}</li>`;
    }).join("");
  }
  function extrasOnlyHtml() {
    const esc = S.h.esc, xs = picked(), v = xTotal(S.cls);
    const rows = Object.keys(CLASSES).map((k) => {
      const t = xTotal(k);
      return `<li class="${k === S.cls ? "is-on" : ""}">${icon(k)}<span>${k}. sınıf · ${CLASSES[k].l}</span>
      <b>${t != null ? esc(fmtNum.format(t)) + " ₺" : "Geçemez"}</b></li>`;
    }).join("");
    return `<article class="fare" aria-label="Geçiş ücreti">
      <div class="fare-main">
        <div class="fare-label">${S.cls}. sınıf · ${CLASSES[S.cls].l}${xs.length > 1 ? " · toplam" : ""}</div>
        <div class="fare-amount">${v != null ? esc(fmtNum.format(v)) + '<span class="cur">₺</span>' : "—"}</div>
        <ol class="legs">${xLegsHtml(S.cls)}</ol>
        ${v == null ? `<p class="fare-note">Seçili araç sınıfı bu geçişlerden en az birini kullanamaz.</p>` : ""}
        <p class="fare-hint">Otoyol ücretini de eklemek için giriş ve çıkış gişesini seçin.</p>
      </div>
      <ul class="fare-classes">${rows}</ul>
    </article>`;
  }

  // ------------------------------------------------------------ seçim

  function pick(role, key) {
    const s = S.byKey.get(key);
    if (!s) return false;
    const other = role === "giris" ? S.exit : S.entry;
    // Aynı gişe ya da bağlantısı olmayan bir çift seçilirse diğer uç bırakılır.
    if (other && (other.key === s.key || !(role === "giris" ? plan(s, other) : plan(other, s)))) {
      if (role === "giris") S.exit = null; else S.entry = null;
    }
    if (role === "giris") S.entry = s; else S.exit = s;
    S.alt = 0;
    update();
    return !!(S.entry && S.exit);
  }
  function swap() { [S.entry, S.exit] = [S.exit, S.entry]; S.alt = 0; update(); }
  function setClass(cls, silent) {
    if (!CLASSES[cls]) return;
    S.cls = cls;
    renderClasses();
    renderExtras();
    if (!silent && S.onClass) S.onClass(cls);
    update(true);
  }

  // ------------------------------------------------------------ çizim

  function renderClasses() {
    $("#trip-classes").innerHTML = Object.keys(CLASSES).map((k) => `
      <button type="button" data-cls="${k}" aria-pressed="${k === S.cls}" title="${k}. sınıf · ${CLASSES[k].l}">
        ${icon(k)}<span class="v-l">${CLASSES[k].l}</span><span class="v-n">${k}. sınıf</span></button>`).join("");
    const sum = $("#veh-sum"), ic = $("#veh-ic");
    if (sum) sum.textContent = `${CLASSES[S.cls].l} · ${S.cls}. sınıf`;
    if (ic) ic.innerHTML = icon(S.cls);
  }

  function resultHtml(a, b) {
    const esc = S.h.esc;
    const all = routes(a, b);
    const p = all.length ? all[Math.min(S.alt, all.length - 1)] : null;
    if (!p) {
      return `<div class="result-empty"><strong>${esc(a.ad)} → ${esc(b.ad)}</strong>${a.oi === b.oi
        ? "KGM tarifesinde bu yönde bu iki gişe arasında ücret yazılmamış."
        : "Bu iki gişe arasında bağlantılı bir tarife bulunamadı."}</div>`;
    }
    const sgsLegs = p.legs.filter((l) => l.sgs);
    const xs = picked();
    const multi = p.trips.length > 1 || sgsLegs.length > 0 || xs.length > 0;
    const o = a.road;
    const v = addFare(planFare(p, S.cls), S.cls);
    const arrow = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 8h11M9.5 4.5 13 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    const rows = Object.keys(CLASSES).map((k) => `<li class="${k === S.cls ? "is-on" : ""}">${icon(k)}<span>${k}. sınıf · ${CLASSES[k].l}</span>
      <b>${clsTotal(p, k)}</b></li>`).join("");
    function clsTotal(r, k) {
      const t = typeof r.total[k - 1] === "number" ? addFare(r.total[k - 1], k) : null;
      if (t != null) return esc(fmtNum.format(t)) + " ₺";
      return xs.length && xTotal(k) == null ? "Geçemez" : "—";
    }
    const docLink = (r) => (r.belge && /^https?:\/\//i.test(r.belge) ? `<a href="${esc(r.belge)}" target="_blank" rel="noopener noreferrer">${multi ? esc(r.yol || "KGM") : "KGM tarifesi"} ↗</a>` : "");
    const roads = [...new Set(p.trips.map((l) => l.a.road).concat(sgsLegs.map((l) => l.road)))];
    const price = (f) => { const x = f ? f[Number(S.cls) - 1] : null; return typeof x === "number" ? esc(fmtNum.format(x)) + " ₺" : "—"; };
    const legsHtml = multi ? `<ol class="legs">${p.legs.filter((l) => !l.link).map((l) => (l.sgs
      ? `<li class="is-sgs"><div class="leg-top"><span class="sw sw-serbest" aria-hidden="true"></span><span class="leg-road">Serbest geçiş · ${esc(l.ad)}</span><b>${price(l.f)}</b></div>
          <div class="leg-trip">${esc(l.road.ad)}${l.yon ? " · " + esc(l.yon) : ""}</div></li>`
      : `<li><div class="leg-top">${l.a.road.yol ? `<span class="ref">${esc(l.a.road.yol)}</span>` : ""}<span class="leg-road">${esc(l.a.road.ad)}</span><b>${price(l.f)}</b></div>
          <div class="leg-trip">${esc(l.a.ad)} → ${esc(l.b.ad)}${l.km != null ? ` · ${esc(fmtKm.format(l.km))} km` : ""}</div></li>`)).join("")}${xLegsHtml(S.cls)}</ol>` : "";
    const valid = o.gecerlilik ? `Geçerlilik ${esc(S.h.date(o.gecerlilik))}` : "KDV dahil";
    const noPos = [a, b].some((s) => !hasPos(s));
    const roadsOf = (r) => [...new Set(r.trips.map((l) => l.a.road.ad.replace(/\s*\(.*\)\s*$/, "")))].join(" → ");
    const chooser = all.length > 1 ? `<div class="route-choice" role="radiogroup" aria-label="Güzergâh">${all.map((r, i) => `
      <button type="button" role="radio" data-route="${i}" aria-checked="${r === p}">
        <span class="rc-k">${i === 0 ? "Doğrudan" : "En ucuz"}</span><span class="rc-v">${clsTotal(r, S.cls)}</span>
        <span class="rc-s">${esc(roadsOf(r))}</span></button>`).join("")}</div>` : "";
    return `${chooser}<article class="fare" aria-label="Geçiş ücreti">
      <div class="fare-main">
        <div class="fare-label">${S.cls}. sınıf · ${CLASSES[S.cls].l}${multi ? " · toplam" : ""}</div>
        <div class="fare-amount">${v != null ? esc(fmtNum.format(v)) + '<span class="cur">₺</span>' : "—"}</div>
        <div class="fare-trip"><span>${esc(a.ad)}</span>${arrow}<span>${esc(b.ad)}</span></div>
        <div class="fare-meta">${multi ? `<span>${p.trips.length} tarife${sgsLegs.length ? ` + ${sgsLegs.length} serbest geçiş` : ""}${xs.length ? ` + ${xs.length} köprü/tünel` : ""}</span>`
          : `${o.yol ? `<span class="ref">${esc(o.yol)}</span>` : ""}<span>${esc(o.ad)}</span>`}${p.km != null ? `<span>· ${esc(fmtKm.format(p.km))} km</span>` : ""}</div>
        ${legsHtml}
        ${v == null ? `<p class="fare-note">${xs.length && xTotal(S.cls) == null ? "Seçili araç sınıfı eklenen geçişlerden en az birini kullanamaz." : "Tarifede bu sınıf için ücret yok."}</p>` : ""}
        ${noPos ? `<p class="fare-note">Gişelerden birinin konumu kayıtlı değil; güzergâh çizilemedi.</p>` : ""}
        ${multi ? `<p class="fare-hint">Her bölüm kendi tarifesine göre ayrı ücretlendirilir; toplam, bölümlerin ücretlerinin toplamıdır.</p>` : ""}
      </div>
      <ul class="fare-classes">${rows}</ul>
      <div class="fare-foot"><span>${valid}${roads.some((r) => r.yonlu) ? " · yöne göre değişir" : ""}</span><span class="docs">${roads.map(docLink).filter(Boolean).join(" ")}</span></div>
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
    $("#trip-result").innerHTML = S.entry && S.exit ? resultHtml(S.entry, S.exit)
      : !S.entry && !S.exit && S.extra.size ? extrasOnlyHtml() : emptyHtml();
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
    let path = [];
    const p = a && b ? chosen(a, b) : null;
    if (p) p.trips.forEach((l) => { if (hasPos(l.a) && hasPos(l.b)) path = path.concat(routePath(l.a, l.b)); });
    S.map.showRoute({ path, entry: a ? stop(a, "in") : null, exit: b ? stop(b, "out") : null, fit: !keepView });
  }

  // ------------------------------------------------------------ adres çubuğu

  function writeHash() {
    try {
      // Biçim: #hesap=<giriş otoyolu>/<giriş sırası>/<çıkış otoyolu>/<çıkış sırası>/<sınıf>[/<köprü,tünel>]
      const a = S.entry, b = S.exit, x = picked().map((c) => encodeURIComponent(c.id)).join(",");
      const end = (s) => (s ? `${encodeURIComponent(s.road.id || "")}/${s.i}` : "/");
      const hash = a || b || x ? `#hesap=${end(a)}/${end(b)}/${S.cls}${x ? "/" + x : ""}` : "";
      if (location.hash !== hash) history.replaceState(null, "", location.pathname + location.search + hash);
    } catch (e) { /* önemli değil */ }
  }
  function readHash() {
    const m = /(?:^#|&)hesap=([^&]*)/.exec(location.hash || "");
    if (!m) return false;
    const parts = m[1].split("/").map((x) => decodeURIComponent(x));
    // Eski biçim (tek otoyol): otoyol/giriş/çıkış/sınıf
    const [ga, gi, ca, ci, cls, xs] = parts.length === 4 ? [parts[0], parts[1], parts[0], parts[2], parts[3]] : parts;
    const get = (id, i) => {
      const oi = S.roads.findIndex((o) => o.id === id);
      return oi >= 0 && i !== "" && i != null ? S.byKey.get(`${oi}:${i}`) || null : null;
    };
    if (CLASSES[cls]) S.cls = cls;
    S.entry = get(ga, gi);
    S.exit = get(ca, ci);
    S.extra = new Set((xs || "").split(",").filter((id) => S.extras.some((c) => c.id === id)));
    return !!(S.entry || S.exit || S.extra.size);
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
    indexExtras(opts.crossings, S.table);
    const fromHash = S.table ? readHash() : false;
    renderClasses();
    renderExtras();
    $("#trip-extras").addEventListener("click", (e) => {
      const b = e.target.closest("[data-extra]");
      if (!b) return;
      const id = b.dataset.extra;
      if (S.extra.has(id)) S.extra.delete(id); else S.extra.add(id);
      renderExtras();
      update(true);
    });
    if (S.table) { combo("giris"); combo("cikis"); }
    else { $("#trip-giris").disabled = true; $("#trip-cikis").disabled = true; }
    $("#trip-swap").addEventListener("click", swap);
    $("#trip-classes").addEventListener("click", (e) => {
      const b = e.target.closest("[data-cls]");
      if (!b) return;
      setClass(b.dataset.cls);
      // Seçim yapıldı: bölüm kapanır, odak özet satırına döner
      const d = $("#opt-vehicle");
      if (d) { d.open = false; d.querySelector("summary").focus({ preventScroll: true }); }
    });
    $("#trip-result").addEventListener("click", (e) => {
      const r = e.target.closest("[data-route]");
      if (r) { S.alt = Number(r.dataset.route) || 0; update(); return; }
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
    roads: () => S.roads,
    reload: () => { if (readHash()) { renderClasses(); renderExtras(); update(); } },
    redraw: () => drawRoute(false),
    classIcon: (k) => icon(k),
    className: (k) => (CLASSES[k] ? CLASSES[k].l : ""),
  };
})();
