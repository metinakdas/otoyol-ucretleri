"use strict";

/*
 * Ücret hesabı: giriş ve çıkış gişesi + araç sınıfı → KGM tarifesindeki ücret ve mesafe.
 * Veri: data/ucret-tablosu.json (KGM tarife PDF'lerindeki gişe-gişe tablolar; gişe konumları config/giseler.yaml).
 * Seçim adres çubuğunda tutulur (#hesap=otoyol/giriş/otoyol/çıkış/sınıf[/köprü,tünel]), bağlantı paylaşılabilir.
 * Görünüm "Tabela dili": toplam plakası, güzergâh şeridi, gidiş-dönüş ve aylık maliyet, son rotalar (yalnızca bu cihazda).
 */
window.RadarHesap = (function () {
  const CLASSES = {
    "1": { l: "Otomobil", d: "aks aralığı 3,20 m'den küçük, iki akslı", i: '<path d="M3 15.5h1.5M9.5 15.5h11M25.5 15.5H27v-3.2c0-.9-.6-1.6-1.4-1.8l-3.6-.9-2.6-3a2.5 2.5 0 0 0-1.9-.9H11a2.5 2.5 0 0 0-2 1l-2.2 3.1-2.4.6A1.8 1.8 0 0 0 3 12.2v3.3"/><circle cx="7" cy="15.5" r="2.2"/><circle cx="23" cy="15.5" r="2.2"/>' },
    "2": { l: "Minibüs", d: "aks aralığı 3,20 m ve üzeri, iki akslı", i: '<path d="M3 15.5h1.5M9.5 15.5h11M25.5 15.5H27v-4l-3-5.5H5a2 2 0 0 0-2 2v7.5M17 6v4.5h8.6M3 10.5h14"/><circle cx="7" cy="15.5" r="2.2"/><circle cx="23" cy="15.5" r="2.2"/>' },
    "3": { l: "3 akslı", d: "üç akslı araçlar", i: '<path d="M2 15.5h1.5M8.5 15.5h4M17.5 15.5h1M23.5 15.5H28v-4.5l-2.5-4H20v9M2 15.5V5h18"/><circle cx="6" cy="15.5" r="2"/><circle cx="15" cy="15.5" r="2"/><circle cx="21" cy="15.5" r="2"/>' },
    "4": { l: "4-5 akslı", d: "dört ve beş akslı araçlar", i: '<path d="M1 15.5h1M6 15.5h1.5M11.5 15.5h4M19.5 15.5h1M24.5 15.5H29v-4.5l-2-3.5h-5v8M1 15.5V5h19v10.5"/><circle cx="4" cy="15.5" r="1.8"/><circle cx="9.5" cy="15.5" r="1.8"/><circle cx="17.5" cy="15.5" r="1.8"/><circle cx="22.5" cy="15.5" r="1.8"/>' },
    "5": { l: "6+ akslı", d: "altı ve daha fazla akslı araçlar", i: '<path d="M1 15.5h.5M10 15.5h3M24 15.5H29v-4.5l-2-3.5h-4v8M1 15.5V5h20v10.5"/><circle cx="3" cy="15.5" r="1.5"/><circle cx="6.5" cy="15.5" r="1.5"/><circle cx="15" cy="15.5" r="1.5"/><circle cx="18.5" cy="15.5" r="1.5"/><circle cx="22" cy="15.5" r="1.5"/>' },
    "6": { l: "Motosiklet", d: "motosikletler", i: '<circle cx="7" cy="14.5" r="3"/><circle cx="23" cy="14.5" r="3"/><path d="M7 14.5l4.5-6h5l3 6M16.5 8.5l1.5-3h3M11.5 8.5 10 6H7.5M20 14.5h-3l-2-3"/>' },
  };
  const NEAR_M = 1500;
  const S = {
    h: null, table: null, roads: [], stations: [], byKey: new Map(), entry: null, exit: null, cls: "1", onClass: null, onChange: null, map: null,
    links: new Map(), linkKeys: [], planCache: new Map(), alt: 0,
    extras: [], extra: new Set(), reg: "", vehOpen: false, xOpen: false, more: "", view: "main", days: 5, saved: false,
  };
  const $ = (sel) => document.querySelector(sel);
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;
  const I = {
    chev: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
    plus: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l4 4 10-10"/></svg>',
    info: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
    swap: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h13l-3-3M20 16H7l3 3"/></svg>',
    cal: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>',
    link: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1"/><path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1"/></svg>',
    card: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M8 7l4-4 4 4M5 13v6h14v-6"/></svg>',
    back: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15 6l-6 6 6 6"/></svg>',
    save: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h12v16l-6-4-6 4z"/></svg>',
    clock: '<svg class="q-ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>',
    x: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    bridge: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 16h18M5 16V9M19 16V9M5 9c3 4 11 4 14 0"/></svg>',
    tunnel: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V12a8 8 0 0 1 16 0v7M4 19h16"/></svg>',
    tunnelNo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V12a8 8 0 0 1 16 0v7M4 19h16"/><path d="M6 6l12 12"/></svg>',
  };

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
  const fmtKm = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 });
  const fmtNum = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const tl = (v) => (typeof v === "number" ? fmtNum.format(v) + " ₺" : "—");
  const esc = (s) => S.h.esc(s);
  // "Anadolu Otoyolu (Çamlıca – Akıncı)" → "Anadolu Otoyolu"; "Yavuz Sultan Selim Köprüsü ve Kuzey Çevre Otoyolu" → "Kuzey Çevre Otoyolu"
  const roadShort = (o) => {
    const ad = String(o.ad || "").replace(/\s*\(.*\)\s*$/, "").replace(/:.*$/, "").trim();
    const m = /\bve\s+(.+Otoyolu)$/.exec(ad);
    return m ? m[1] : ad;
  };
  const shield = (o, sm) => (o && o.yol ? `<span class="shield${sm ? " sm" : ""}"><span>${esc(o.yol)}</span></span>` : "");
  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* tarayıcı depolaması kapalı olabilir */ }
    return null;
  }

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
      return row ? { road: o, ad: row.ad, yon: row.yon || r.yon || "", f: Array.isArray(row.ucret) ? row.ucret : null,
        lat: row.lat, lon: row.lon, il: row.il || null } : null;
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
      // yeniden girmek (iki ayrı kalem) yol sayılmaz. Maliyet: toplam 1. sınıf ücreti + kalem başına ceza.
      const nodes = [...new Set([a.key, b.key, ...S.linkKeys])].map((k) => S.byKey.get(k));
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
          nodes.forEach((v) => {
            if (v.oi !== su.oi || v.key === su.key) return;
            const f = fare(su, v, "1");
            if (f != null) set(v.key + "|L", du + f + penalty, { from: u, leg: true });
          });
        } else {
          (S.links.get(key) || []).forEach((e) => {
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
            [...p.link.sgs].reverse().forEach((g) => legs.unshift({ sgs: true, road: g.road, ad: g.ad, yon: g.yon, f: g.f, km: null, lat: g.lat, lon: g.lon, il: g.il }));
            legs.unshift({ link: true, km: p.link.km, from, to });
          }
        }
        if (!legs.some((l) => !l.sgs && !l.link)) legs = null;
      }
    }
    const result = legs && legs.length ? {
      legs: legs.map((l) => (l.sgs || l.link ? l : Object.assign(l, { f: fares(l.a, l.b), km: km(l.a, l.b) }))),
    } : null;
    if (result) {
      const paid = result.legs.filter((l) => !l.link);
      result.trips = result.legs.filter((l) => !l.sgs && !l.link);
      result.sgs = result.legs.filter((l) => l.sgs);
      result.total = Object.keys(CLASSES).map((k) => {
        const parts = paid.map((l) => (l.f ? l.f[k - 1] : null));
        return parts.every((x) => typeof x === "number") ? Math.round(parts.reduce((t, x) => t + x, 0) * 100) / 100 : null;
      });
      const kms = result.legs.filter((l) => !l.sgs).map((l) => l.km);
      result.km = kms.every((x) => typeof x === "number") ? kms.reduce((t, x) => t + x, 0) : null;
    }
    S.planCache.set(id, result);
    return result;
  }
  const planFare = (p, cls) => (p && typeof p.total[Number(cls) - 1] === "number" ? p.total[Number(cls) - 1] : null);

  // Güzergâh seçenekleri: "doğrudan" (en az kalem, eşitlikte en ucuz) ve varsa farklı bir "en ucuz" yol.
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

  // ------------------------------------------------------------ köprü ve tüneller
  // KGM gişe tablolarına dahil olmayan geçişler (Avrasya Tüneli, Boğaz köprüleri) rotaya ayrıca eklenir.
  // Tabloya dahil olanlar (YSS, Osmangazi, 1915 Çanakkale) gişe ücretinin içindedir, iki kez sayılmaz.
  const ONE_WAY = { "15-temmuz-sehitler": true, "fatih-sultan-mehmet": true };   // yalnızca Avrupa → Asya ücretli
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
  function xTotal(cls) {
    let t = 0;
    for (const c of picked()) { const v = xFare(c, cls); if (v == null) return null; t += v; }
    return Math.round(t * 100) / 100;
  }
  const addFare = (base, cls) => { const x = xTotal(cls); return base == null || x == null ? null : Math.round((base + x) * 100) / 100; };
  const blockedBy = (cls) => picked().filter((c) => xFare(c, cls) == null);
  const xNote = (c) => (ONE_WAY[c.id] ? "Avrupa → Asya" : c.current && c.current.gece && c.current.gece.classes && c.current.gece.classes[S.cls] != null
    ? `Gece ${c.current.gece.saat || ""}: ${tl(Number(c.current.gece.classes[S.cls]))}` : c.operator || "");
  const xIcon = (c, no) => (no ? I.tunnelNo : c.tur === "tunel" ? I.tunnel : I.bridge);
  const allowedText = (c) => {
    const no = Object.keys(CLASSES).filter((k) => xFare(c, k) == null);
    const list = no.length > 1 ? no.slice(0, -1).join(", ") + " ve " + no[no.length - 1] : no[0];
    return `${list}. sınıf araçlar giremez`;
  };
  const passName = (c) => (/Tüneli$/.test(c.name) ? `${c.name}'nden` : /Köprüsü$/.test(c.name) ? `${c.name}'nden` : c.name);

  function toggleExtra(id, on) {
    if (on === undefined) on = !S.extra.has(id);
    if (on) S.extra.add(id); else S.extra.delete(id);
    renderExtras();
    update(true);
  }

  function renderExtras() {
    const box = $("#trip-extras");
    if (!box) return;
    box.innerHTML = S.extras.map((c) => {
      const v = xFare(c, S.cls), on = S.extra.has(c.id);
      const note = ONE_WAY[c.id] ? "yalnız Avrupa → Asya" : "";
      return `<label class="x-row${v == null ? " is-off" : ""}">
        <input type="checkbox" data-extra="${esc(c.id)}" ${on ? "checked" : ""} ${v == null && !on ? "disabled" : ""}>
        <span class="x-n">${esc(c.name)}${note ? `<small>${esc(note)}</small>` : ""}</span>
        ${v != null ? `<span class="x-v">${esc(tl(v))}</span>` : `<span class="tag no">${esc(S.cls)}. sınıf geçemez</span>`}</label>`;
    }).join("");
    const xs = picked(), t = xTotal(S.cls);
    const sum = $("#extras-sum");
    if (sum) {
      sum.textContent = !xs.length ? "Eklenmedi" : `${xs.length === 1 ? xs[0].name : xs.length + " geçiş"}${t != null ? ` · +${fmtNum.format(t)} ₺` : " · geçemez"}`;
      sum.classList.toggle("is-set", xs.length > 0);
    }
    const chip = $("#x-chip");
    if (chip) {
      chip.innerHTML = !xs.length ? `${I.plus}Köprü / tünel`
        : `${esc(xs.length === 1 ? xs[0].name.replace(/\s+(Şehitler\s+)?(Köprüsü|Tüneli)$/, "") : xs.length + " geçiş")}${t != null ? ` · +${esc(fmtNum.format(t))} ₺` : " · geçemez"}`;
      chip.classList.toggle("is-set", xs.length > 0 && t != null);
      chip.classList.toggle("is-bad", xs.length > 0 && t == null);
      chip.setAttribute("aria-expanded", String(S.xOpen));
    }
  }

  // ------------------------------------------------------------ araç sınıfı

  const clsGridHtml = (sel, attr) => Object.keys(CLASSES).map((k) => `<button type="button" role="radio" ${attr || "data-cls"}="${k}" aria-checked="${k === sel}" tabindex="${k === sel ? 0 : -1}" aria-label="${k}. sınıf, ${CLASSES[k].l}" title="${k}. sınıf · ${CLASSES[k].l}"><svg class="cls-ic" viewBox="0 0 30 20" aria-hidden="true">${CLASSES[k].i}</svg><span class="cls-n">${k}</span></button>`).join("");
  const clsChipHtml = (k) => `<span class="n">${esc(k)}</span>${esc(CLASSES[k].l)}${I.chev}`;

  function renderClasses() {
    $("#trip-classes").innerHTML = clsGridHtml(S.cls);
    $("#veh-desc").innerHTML = `<b>${esc(CLASSES[S.cls].l)}</b> · ${esc(CLASSES[S.cls].d)}`;
    const chip = $("#veh-chip");
    chip.innerHTML = clsChipHtml(S.cls);
    chip.setAttribute("aria-label", `Araç: ${S.cls}. sınıf, ${CLASSES[S.cls].l}. Değiştir`);
    chip.setAttribute("aria-expanded", String(S.vehOpen));
    chip.classList.toggle("is-warn", blockedBy(S.cls).length > 0);
  }

  // Ok tuşlarıyla radyo grubunda gezinme (tek sekme durağı)
  function radioKeys(el, onPick, attr) {
    el.addEventListener("keydown", (e) => {
      if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(e.key)) return;
      const btns = [...el.querySelectorAll(`[${attr}]`)];
      const i = btns.indexOf(document.activeElement);
      if (i < 0) return;
      e.preventDefault();
      const n = btns[(i + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : btns.length - 1)) % btns.length];
      onPick(n.getAttribute(attr), true);
      const again = el.querySelector(`[${attr}="${n.getAttribute(attr)}"]`);
      if (again) again.focus();
    });
  }

  // ------------------------------------------------------------ seçenekler (gişe listesi)

  function optionsFor(role, q) {
    const other = role === "giris" ? S.exit : S.entry;
    const current = role === "giris" ? S.entry : S.exit;
    const tokens = fold(q).split(" ").filter(Boolean);
    const qk = fold(q);
    const rank = (s) => (s.nameKey === qk ? -1 : s.nameKey.startsWith(qk) ? 0 : s.nameKey.split(" ").some((w) => w.startsWith(tokens[0])) ? 1 : s.nameKey.includes(qk) ? 2 : 3);
    const inReg = (s) => !S.reg || s.bolge === S.reg;
    const items = [{ regions: true }];
    const head = (o) => ({ head: roadShort(o), road: o });
    if (!tokens.length && !other) {
      const rec = recents().slice(0, 3).map((r, n) => ({ r, n, p: recentPlan(r) })).filter((x) => x.p);
      if (rec.length) {
        items.push({ head: "Son rotalar · bu cihazda" });
        rec.forEach(({ r, n, p }) => items.push({ recent: n, name: `${p.a.ad} → ${p.b.ad}`, sub: CLASSES[r.cls] ? CLASSES[r.cls].l : "", price: tl(p.v) }));
      }
    }
    if (other) {
      // Diğer uç seçiliyse: ona ulaşılabilen bütün gişeler (önce aynı otoyol, sonra bağlantılı otoyollar), ücretleriyle.
      const pool = S.stations.filter((s) => s.key !== other.key && inReg(s) && (!tokens.length || tokens.every((t) => s.search.includes(t))));
      const rows = pool.map((s) => ({ s, p: role === "cikis" ? plan(other, s) : plan(s, other) })).filter((x) => x.p);
      if (tokens.length) rows.sort((x, y) => rank(x.s) - rank(y.s) || (x.s.oi !== other.oi) - (y.s.oi !== other.oi));
      else rows.sort((x, y) => (x.s.oi !== other.oi) - (y.s.oi !== other.oi) || x.s.oi - y.s.oi || x.s.i - y.s.i);
      let last = -1;
      rows.forEach(({ s, p }) => {
        if (!tokens.length && s.oi !== last) { items.push(head(s.road)); last = s.oi; }
        const f = addFare(planFare(p, S.cls), S.cls);
        const via = p.trips.length > 1 ? `${p.trips.length} tarife` : "";
        items.push({ key: s.key, name: s.ad, current: current && current.key === s.key,
          sub: [tokens.length ? roadShort(s.road) : s.il, p.km != null ? fmtKm.format(p.km) + " km" : "", via].filter(Boolean).join(" · "),
          price: tl(f) });
      });
      if (!rows.length) items.push({ note: tokens.length && pool.length ? `${other.ad} ile bu gişe arasında bağlantılı tarife yok` : "Eşleşen gişe yok" });
      return items;
    }
    let pool = S.stations.filter(inReg);
    if (tokens.length) pool = pool.filter((s) => tokens.every((t) => s.search.includes(t))).sort((a, b) => rank(a) - rank(b));
    let last = -1;
    pool.slice(0, 400).forEach((s) => {
      if (!tokens.length && s.oi !== last) { items.push(head(s.road)); last = s.oi; }
      items.push({ key: s.key, name: s.ad, il: s.il || "", current: current && current.key === s.key,
        sub: tokens.length ? roadShort(s.road) : "" });
    });
    if (!pool.length) items.push({ note: "Eşleşen gişe yok" });
    if (role === "giris") items.push({ foot: "Çıkış listesinde her gişenin ücreti yazar." });
    return items;
  }

  function regionsHtml() {
    const regs = [];
    S.stations.forEach((s) => { if (s.bolge && !regs.includes(s.bolge)) regs.push(s.bolge); });
    const names = S.h.regionName || ((id) => id);
    return `<button type="button" class="chipbtn" data-reg="" aria-pressed="${!S.reg}">Tümü</button>` +
      regs.map((id) => `<button type="button" class="chipbtn" data-reg="${esc(id)}" aria-pressed="${S.reg === id}">${esc(names(id))}</button>`).join("");
  }

  // ------------------------------------------------------------ açılır liste (gişe arama)

  function combo(role) {
    const input = $(`#trip-${role}`);
    const list = $(`#trip-${role}-list`);
    const box = $(`#combo-${role}`);
    let items = [], active = -1;
    const picks = () => items.filter((x) => x.key || x.recent !== undefined);

    function render() {
      let n = 0;
      list.innerHTML = items.map((x) => {
        if (x.regions) return `<li class="o-regions" role="presentation">${regionsHtml()}</li>`;
        if (x.head) return `<li class="o-head" role="presentation">${x.road ? shield(x.road, true) : ""}${esc(x.head)}</li>`;
        if (x.note) return `<li class="o-note" role="presentation">${esc(x.note)}</li>`;
        if (x.foot) return `<li class="o-foot" role="presentation">${I.info}${esc(x.foot)}</li>`;
        const idx = n++;
        if (x.recent !== undefined) {
          return `<li role="option" class="opt" id="${role}-opt-${idx}" data-recent="${x.recent}" aria-selected="${idx === active}">
            ${I.clock}<span class="o-t"><span class="o-name">${esc(x.name)}</span><span class="o-sub">${esc(x.sub)}</span></span><span class="o-price">${esc(x.price)}</span></li>`;
        }
        return `<li role="option" class="opt${x.current ? " is-current" : ""}" id="${role}-opt-${idx}" data-key="${esc(x.key)}" aria-selected="${idx === active}">
          <span class="o-dot" aria-hidden="true"></span><span class="o-t"><span class="o-name">${esc(x.name)}</span>${x.sub ? `<span class="o-sub">${esc(x.sub)}</span>` : ""}</span>
          ${x.price ? `<span class="o-price">${esc(x.price)}</span>` : x.il ? `<span class="o-il">${esc(x.il)}</span>` : ""}${x.current ? `<svg class="o-check" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l4 4 10-10"/></svg>` : ""}</li>`;
      }).join("");
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      if (active >= 0) input.setAttribute("aria-activedescendant", `${role}-opt-${active}`); else input.removeAttribute("aria-activedescendant");
      const el = active >= 0 && list.querySelector(`#${role}-opt-${active}`);
      if (el) el.scrollIntoView({ block: "nearest" });
    }
    const open = (all) => {
      items = optionsFor(role, all ? "" : input.value); active = -1; render();
      if (narrow()) {
        $("#panel").classList.add("is-search");
        box.classList.add("is-active");
        $("#search-title").textContent = role === "giris" ? "Giriş gişesi seç" : "Çıkış gişesi seç";
      }
    };
    const close = () => {
      list.hidden = true; input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant");
      box.classList.remove("is-active");
      if (!document.querySelector("#trip .combo.is-active")) $("#panel").classList.remove("is-search");
    };
    const choose = (key) => { close(); input.blur(); pick(role, key); };
    const chooseRecent = (n) => { close(); input.blur(); applyRecent(recents()[n]); };

    input.addEventListener("focus", () => { input.select(); open(true); });
    input.addEventListener("input", () => open(false));
    input.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== input) { close(); syncInputs(); } }, 150));
    input.addEventListener("keydown", (e) => {
      const n = picks().length;
      if (e.key === "ArrowDown") { e.preventDefault(); if (list.hidden) open(false); active = Math.min(n - 1, active + 1); render(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(0, active - 1); render(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const x = picks()[active >= 0 ? active : 0];
        if (x && x.key) choose(x.key); else if (x) chooseRecent(x.recent);
      } else if (e.key === "Escape") { close(); input.blur(); }
    });
    list.addEventListener("mousedown", (e) => e.preventDefault());
    list.addEventListener("click", (e) => {
      const r = e.target.closest("[data-reg]");
      if (r) { S.reg = r.dataset.reg; items = optionsFor(role, input.value); active = -1; render(); input.focus(); return; }
      const li = e.target.closest("[data-key]");
      if (li) { choose(li.dataset.key); return; }
      const rc = e.target.closest("[data-recent]");
      if (rc) chooseRecent(Number(rc.dataset.recent));
    });
  }

  function syncInputs() {
    const gi = $("#trip-giris"), ci = $("#trip-cikis");
    if (document.activeElement !== gi) gi.value = S.entry ? S.entry.ad : "";
    if (document.activeElement !== ci) ci.value = S.exit ? S.exit.ad : "";
    const tiny = (s) => roadShort(s.road).replace(/\s+Otoyolu$/, "");
    $("#giris-road").textContent = S.entry ? tiny(S.entry) : "";
    $("#cikis-road").textContent = S.exit ? tiny(S.exit) : "";
  }

  // ------------------------------------------------------------ seçim

  function pick(role, key) {
    const s = S.byKey.get(key);
    if (!s) return false;
    const other = role === "giris" ? S.exit : S.entry;
    if (other && (other.key === s.key || !(role === "giris" ? plan(s, other) : plan(other, s)))) {
      if (role === "giris") S.exit = null; else S.entry = null;
    }
    if (role === "giris") S.entry = s; else S.exit = s;
    S.alt = 0; S.more = ""; S.view = "main";
    update();
    // Giriş seçilince çıkış listesi açılır (ücretleriyle)
    if (role === "giris" && !S.exit && !narrow()) setTimeout(() => $("#trip-cikis").focus(), 0);
    return !!(S.entry && S.exit);
  }
  function swap() { [S.entry, S.exit] = [S.exit, S.entry]; S.alt = 0; update(); }
  function reset() { S.entry = null; S.exit = null; S.alt = 0; S.more = ""; S.view = "main"; S.vehOpen = false; S.xOpen = false; update(); }
  function setClass(cls, silent) {
    if (!CLASSES[cls]) return;
    S.cls = cls;
    renderClasses();
    renderExtras();
    if (!silent && S.onClass) S.onClass(cls);
    update(true);
  }

  // ------------------------------------------------------------ son rotalar (yalnızca bu cihazda)

  function recents() {
    try { const v = JSON.parse(store("radar.rotalar") || "[]"); return Array.isArray(v) ? v : []; } catch (e) { return []; }
  }
  function remember(pin) {
    if (!S.entry || !S.exit) return;
    const r = { ga: S.entry.road.id, gi: S.entry.i, ca: S.exit.road.id, ci: S.exit.i, cls: S.cls, alt: S.alt, x: [...S.extra], pin: !!pin };
    const same = (x) => x.ga === r.ga && x.gi === r.gi && x.ca === r.ca && x.ci === r.ci;
    const old = recents();
    const prev = old.find(same);
    if (prev && prev.pin) r.pin = true;
    const list = [r].concat(old.filter((x) => !same(x))).slice(0, 8);
    store("radar.rotalar", JSON.stringify(list));
  }
  const stationOf = (rid, i) => { const oi = S.roads.findIndex((o) => o.id === rid); return oi >= 0 ? S.byKey.get(`${oi}:${i}`) || null : null; };
  function recentPlan(r) {
    const a = stationOf(r.ga, r.gi), b = stationOf(r.ca, r.ci);
    if (!a || !b) return null;
    const all = routes(a, b);
    const p = all[Math.min(r.alt || 0, all.length - 1)];
    if (!p) return null;
    let v = planFare(p, r.cls);
    (r.x || []).forEach((id) => { const c = S.extras.find((e) => e.id === id); const f = c ? xFare(c, r.cls) : null; v = v == null || f == null ? null : v + f; });
    return { a, b, p, v: v == null ? null : Math.round(v * 100) / 100 };
  }
  function applyRecent(r) {
    if (!r) return;
    const a = stationOf(r.ga, r.gi), b = stationOf(r.ca, r.ci);
    if (!a || !b) return;
    S.entry = a; S.exit = b; S.alt = r.alt || 0; S.more = ""; S.view = "main";
    S.extra = new Set((r.x || []).filter((id) => S.extras.some((c) => c.id === id)));
    if (CLASSES[r.cls] && r.cls !== S.cls) { S.cls = r.cls; if (S.onClass) S.onClass(r.cls); }
    renderClasses(); renderExtras(); update();
  }

  // Hızlı başla: doğrulanmış örnek rotalar (ücretleri canlı tablodan hesaplanır)
  const PRESETS = [
    { ga: "anadolu-camlica-akinci", gn: "Adapazarı", ca: "anadolu-camlica-akinci", cn: "Akyazı", cls: "1", alt: 0 },
    { ga: "kmo-kurtkoy-akyazi", gn: "İzmit Kuzey", ca: "yss-kuzey-cevre", cn: "Paşaköy", cls: "1", alt: 1, sub: "en ucuz" },
    { ga: "anadolu-camlica-akinci", gn: "Kurtköy", ca: "anadolu-camlica-akinci", cn: "Gerede", cls: "5", alt: 0, sub: "5. sınıf" },
  ];
  function presetRows() {
    return PRESETS.map((x) => {
      const a = S.stations.find((s) => s.road.id === x.ga && s.nameKey === fold(x.gn));
      const b = S.stations.find((s) => s.road.id === x.ca && s.nameKey === fold(x.cn));
      if (!a || !b) return null;
      const all = routes(a, b);
      const p = all[Math.min(x.alt, all.length - 1)];
      if (!p) return null;
      return { r: { ga: a.road.id, gi: a.i, ca: b.road.id, ci: b.i, cls: x.cls, alt: Math.min(x.alt, all.length - 1), x: [] }, a, b, v: planFare(p, x.cls), sub: x.sub || "" };
    }).filter(Boolean);
  }
  function renderQuick() {
    const q = $("#quick");
    if (S.entry || S.exit || S.extra.size || !S.table) { q.innerHTML = ""; return; }
    const rec = recents().map((r) => ({ r, p: recentPlan(r) })).filter((x) => x.p).slice(0, 3);
    if (rec.length) {
      q.innerHTML = `<h3>Son rotalar</h3>` + rec.map(({ r, p }, n) => `<button type="button" class="q-row" data-recent-q="${n}">
        ${I.clock}<span class="q-n">${esc(p.a.ad)} → ${esc(p.b.ad)}</span><span class="q-s">${esc(CLASSES[r.cls] ? CLASSES[r.cls].l : "")}</span><span class="q-p">${esc(tl(p.v))}</span></button>`).join("");
      q.dataset.mode = "recent";
      return;
    }
    const rows = presetRows();
    q.dataset.mode = "preset";
    q._rows = rows;
    q.innerHTML = rows.length ? `<h3>Hızlı başla</h3>` + rows.map((x, n) => `<button type="button" class="q-row" data-preset="${n}">
      ${shield(x.a.road, true)}<span class="q-n">${esc(x.a.ad)} → ${esc(x.b.ad)}</span>${x.sub ? `<span class="q-s">${esc(x.sub)}</span>` : ""}<span class="q-p">${esc(tl(x.v))}</span></button>`).join("") : "";
  }

  // ------------------------------------------------------------ sonuç

  function stripHtml(a, b, p) {
    const rows = [`<li class="st-end"><span class="st-pin a">A</span><span>${esc(a.ad)}</span><span></span></li>`];
    let prevTrip = false;
    p.legs.forEach((l) => {
      if (l.link) return;
      if (l.sgs) {
        const v = l.f ? l.f[Number(S.cls) - 1] : null;
        rows.push(`<li class="st-sgs"><span class="dia" aria-hidden="true"></span><span class="st-road"><span><span class="nm">${esc(l.ad)}</span></span><span class="st-sub">Serbest geçiş · HGS'den otomatik</span></span><span class="st-p">${esc(tl(v))}</span></li>`);
        prevTrip = false;
        return;
      }
      if (prevTrip) rows.push(`<li class="st-x"><span class="ring" aria-hidden="true"></span><span>Aktarma</span><span></span></li>`);
      const v = l.f ? l.f[Number(S.cls) - 1] : null;
      rows.push(`<li class="st-leg" title="${esc(l.a.ad)} → ${esc(l.b.ad)}${l.km != null ? " · " + esc(fmtKm.format(l.km)) + " km" : ""}"><span class="st-bar" aria-hidden="true"></span><span class="st-road"><span>${shield(l.a.road, true)}<span class="nm">${esc(roadShort(l.a.road))}</span></span></span>
        <span class="st-p${typeof v === "number" ? "" : " na"}">${typeof v === "number" ? esc(tl(v)) : "Tarifede yok"}</span></li>`);
      prevTrip = true;
    });
    rows.push(`<li class="st-end"><span class="st-pin b">B</span><span>${esc(b.ad)}</span><span></span></li>`);
    return `<ol class="strip" aria-label="Güzergâh dökümü">${rows.join("")}</ol>`;
  }

  function addedHtml() {
    const xs = picked();
    if (!xs.length) return "";
    return `<div class="added"><h3>Eklenen geçişler</h3>${xs.map((c) => {
      const v = xFare(c, S.cls);
      return `<div class="ad-row${v == null ? " is-bad" : ""}">
        <span class="ad-ic">${xIcon(c, v == null)}</span>
        <span class="ad-t"><b>${esc(c.name)}</b><span>${esc(v == null ? allowedText(c).replace(" araçlar giremez", " geçemez") : xNote(c))}</span></span>
        ${v != null ? `<span class="ad-p">${esc(tl(v))}</span>` : `<span class="no-tag">Geçemez</span>`}
        <button type="button" class="ad-x" data-xremove="${esc(c.id)}" aria-label="${esc(c.name)} rotadan çıkar">${I.x}</button></div>`;
    }).join("")}</div>`;
  }

  function blockAlertHtml() {
    const bad = blockedBy(S.cls);
    if (!bad.length) return "";
    const c = bad[0];
    return `<div class="block-alert" role="alert">
      <div class="ba-top"><span class="ba-ic">${I.tunnelNo}</span><div><b>${esc(passName(c))} geçemezsin</b>
        <p>${esc(allowedText(c))}. Toplam bu yüzden hesaplanmadı.</p></div></div>
      <div class="ba-acts"><button type="button" class="btn primary" data-xremove="${esc(c.id)}">Rotadan çıkar</button>
        <button type="button" class="btn" data-open-veh="1">Aracı değiştir</button></div></div>`;
  }

  function actsHtml() {
    return `<div class="acts">
      <button type="button" data-act="swap">${I.swap}Ters yön</button>
      <button type="button" data-act="aylik">${I.cal}Aylık</button>
      <button type="button" data-act="copy">${I.link}<span>Bağlantı</span></button>
      <button type="button" data-act="card">${I.card}<span>Kart</span></button></div>`;
  }

  function moreHtml(p, roads) {
    if (S.more === "cls") {
      return `<ul class="more" aria-label="Tüm sınıflar">${Object.keys(CLASSES).map((k) => {
        const t = p ? (typeof p.total[k - 1] === "number" ? addFare(p.total[k - 1], k) : null) : xTotal(k);
        const no = picked().some((c) => xFare(c, k) == null);
        return `<li class="${k === S.cls ? "is-on" : ""}"><span class="ov">${k}</span><span class="grow">${esc(CLASSES[k].l)}</span><b>${t != null ? esc(tl(t)) : no ? "Geçemez" : "—"}</b></li>`;
      }).join("")}</ul>`;
    }
    if (S.more === "docs") {
      const links = roads.filter((r) => r.belge && /^https?:\/\//i.test(r.belge)).map((r) => `<li><a href="${esc(r.belge)}" target="_blank" rel="noopener noreferrer">${esc(r.yol ? r.yol + " · " : "")}${esc(roadShort(r))} ↗</a></li>`)
        .concat(picked().filter((c) => c.current && c.current.source_url && /^https?:\/\//i.test(c.current.source_url)).map((c) => `<li><a href="${esc(c.current.source_url)}" target="_blank" rel="noopener noreferrer">${esc(c.name)} ↗</a></li>`));
      return `<ul class="more" aria-label="Tarife belgeleri">${links.join("") || `<li>Belge bağlantısı yok</li>`}</ul>`;
    }
    return "";
  }

  function resultHtml(a, b) {
    const all = routes(a, b);
    const idx = Math.min(S.alt, Math.max(0, all.length - 1));
    const p = all.length ? all[idx] : null;
    if (!p) {
      return `<div class="result-empty"><strong>${esc(a.ad)} → ${esc(b.ad)}</strong>${a.oi === b.oi
        ? "KGM tarifesinde bu yönde bu iki gişe arasında ücret yazılmamış."
        : "Bu iki gişe arasında bağlantılı bir tarife bulunamadı."}</div>`;
    }
    const v = addFare(planFare(p, S.cls), S.cls);
    const blocked = blockedBy(S.cls).length > 0;
    const xs = picked();
    const roads = [...new Set(p.trips.map((l) => l.a.road).concat(p.sgs.map((l) => l.road)))];
    // Doğrudan / En ucuz
    const label = (r, i) => {
      const t = r.trips.length - 1;
      return `${i === 0 ? "Doğrudan" : "En ucuz"}${t > 0 ? ` · ${t} aktarma` : ""}`;
    };
    const chooser = all.length > 1 ? `<div class="route-choice" role="radiogroup" aria-label="Rota seçeneği">${all.map((r, i) => {
      const t = addFare(planFare(r, S.cls), S.cls);
      return `<button type="button" role="radio" data-route="${i}" aria-checked="${i === idx}"><span class="rc-k">${esc(label(r, i))}</span><span class="rc-v">${esc(tl(t))}</span></button>`;
    }).join("")}</div>` : "";
    // Plaka
    let side, note = "";
    if (all.length > 1) side = `<span class="o">tek yön · ${esc(CLASSES[S.cls].l.toLocaleLowerCase("tr"))}</span>`;
    else side = `${p.km != null ? `<span class="km">${esc(fmtKm.format(p.km))} km</span>` : ""}<span class="o">${p.trips.length > 1 ? p.trips.length + " tarife" : "tek tarife"}${xs.length ? " + köprü/tünel" : ""}</span>`;
    if (all.length > 1 && !blocked) {
      const d = all[0], c = all[1];
      const diff = (planFare(d, S.cls) != null && planFare(c, S.cls) != null) ? Math.round((planFare(d, S.cls) - planFare(c, S.cls)) * 100) / 100 : null;
      const dx = c.trips.length - d.trips.length, ds = c.sgs.length - d.sgs.length;
      if (diff != null && diff > 0) {
        note = idx === 1
          ? `<div class="plate-note">${I.check}<span><b>${esc(tl(diff))}</b> daha ucuz${dx > 0 ? ` · +${dx} aktarma` : ""}${ds > 0 ? ` · +${ds} serbest geçiş` : ""}</span></div>`
          : `<div class="plate-note">${I.info}<span>En ucuz seçenek <b>${esc(tl(diff))}</b> daha ucuz</span></div>`;
      }
    }
    const plate = blocked
      ? `<div class="plate-off"><span class="plate-amount">— ₺</span><span class="plate-side">${esc(CLASSES[S.cls].l)} · tek yön<br>${esc(blockedBy(S.cls)[0].name)} çıkınca hesaplanır</span></div>`
      : `<div class="plate" aria-label="Toplam ücret"><div class="plate-in"><div class="plate-top"><span class="plate-amount">${v != null ? esc(fmtNum.format(v)) + " ₺" : "—"}</span><span class="plate-side">${side}</span></div>${note}</div></div>`;
    const noFare = !blocked && v == null ? `<div class="result-empty">Tarifede ${esc(S.cls)}. sınıf için ücret yazılmamış.</div>` : "";
    const noPos = [a, b].some((s) => !hasPos(s)) ? `<div class="result-empty">Gişelerden birinin konumu kayıtlı değil; güzergâh haritada çizilemedi.</div>` : "";
    return `${blockAlertHtml()}${chooser}${plate}${noFare}${stripHtml(a, b, p)}${addedHtml()}${noPos}${actsHtml()}
      <div class="res-links"><button type="button" class="linkbtn" data-more="cls" aria-expanded="${S.more === "cls"}">Diğer sınıflar</button>
        <button type="button" class="linkbtn" data-more="docs" aria-expanded="${S.more === "docs"}">Tarife belgeleri ↗</button></div>
      ${moreHtml(p, roads)}`;
  }

  function extrasOnlyHtml() {
    const v = xTotal(S.cls);
    const blocked = blockedBy(S.cls).length > 0;
    return `${blockAlertHtml()}${blocked ? "" : `<div class="plate"><div class="plate-in"><div class="plate-top"><span class="plate-amount">${esc(tl(v))}</span>
      <span class="plate-side"><span class="o">tek yön · ${esc(CLASSES[S.cls].l.toLocaleLowerCase("tr"))}</span></span></div></div></div>`}
      ${addedHtml()}<div class="result-empty">Otoyol ücretini de eklemek için giriş ve çıkış gişesini seç.</div>`;
  }

  function emptyHtml() {
    if (!S.table) return `<div class="result-empty"><strong>Ücret tablosu hazırlanıyor</strong>KGM tarifeleri okunduğunda hesap açılır.</div>`;
    const one = S.entry || S.exit;
    if (one) return `<div class="result-empty"><strong>${esc(one.ad)}</strong>${S.entry ? "Çıkış" : "Giriş"} gişesini seç ya da haritada bir gişeye dokun.</div>`;
    return "";
  }

  // ------------------------------------------------------------ gidiş-dönüş ve aylık maliyet

  function aylikHtml() {
    const a = S.entry, b = S.exit;
    const xs = picked();
    const cards = [];
    let goT = 0, backT = 0, ok = true;
    const add = (go, back) => { if (go == null || back == null) ok = false; else { goT += go; backT += back; } };
    if (a && b) {
      const go = chosen(a, b), back = routes(b, a);
      const pb = back.length ? back[Math.min(S.alt, back.length - 1)] : null;
      const vg = planFare(go, S.cls), vb = planFare(pb, S.cls);
      add(vg, vb);
      cards.push(`<section class="ay-card"><div class="ay-t">${shield(a.road, true)}<span>${esc(a.ad)} ↔ ${esc(b.ad)}</span></div>
        <div class="ay-row"><span class="k">Gidiş</span><span class="d">${esc(a.ad)} → ${esc(b.ad)}</span><span class="v">${esc(tl(vg))}</span></div>
        <div class="ay-row"><span class="k">Dönüş</span><span class="d">${esc(b.ad)} → ${esc(a.ad)}</span><span class="v">${esc(tl(vb))}</span></div></section>`);
    }
    xs.forEach((c) => {
      const v = xFare(c, S.cls);
      const back = ONE_WAY[c.id] ? 0 : v;
      add(v, back);
      cards.push(`<section class="ay-card"><div class="ay-t"><span class="ad-ic">${xIcon(c)}</span><span>${esc(c.name)}</span></div>
        <div class="ay-row"><span class="k">Gidiş</span><span class="d">${ONE_WAY[c.id] ? "Avrupa → Asya" : "Bir yön"}</span><span class="v">${esc(tl(v))}</span></div>
        <div class="ay-row"><span class="k">Dönüş</span><span class="d">${ONE_WAY[c.id] ? "Asya → Avrupa<small>Bu yönde ücret alınmaz</small>" : "Diğer yön"}</span><span class="v${back === 0 ? " zero" : ""}">${esc(tl(back))}</span></div></section>`);
    });
    const round = ok ? goT + backT : null;
    const weekly = round != null ? round * S.days : null;
    const yearly = weekly != null ? weekly * 52 : null;
    const monthly = yearly != null ? yearly / 12 : null;
    const days = [1, 2, 3, 4, 5, 6, 7].map((n) => `<button type="button" role="radio" data-day="${n}" aria-checked="${n === S.days}" tabindex="${n === S.days ? 0 : -1}" aria-label="Haftada ${n} gün">${n}</button>`).join("");
    const upcoming = S.h.upcomingText ? S.h.upcomingText() : "";
    return `<div class="ay-head"><button type="button" class="icon-btn" data-ay="back" aria-label="Sonuca dön">${I.back}</button>
        <h2>Gidiş-dönüş</h2><span class="veh-chip" aria-label="${esc(S.cls)}. sınıf, ${esc(CLASSES[S.cls].l)}"><span class="n">${esc(S.cls)}</span>${esc(CLASSES[S.cls].l)}</span></div>
      ${cards.join("")}
      <section class="ay-days" aria-labelledby="ay-gun"><h3 id="ay-gun">Haftada kaç gün?</h3><div class="cls-grid" role="radiogroup" aria-labelledby="ay-gun" id="ay-days">${days}</div></section>
      <div class="plate ay-plate"><div class="plate-in">
        <span class="ay-lbl">Aylık yaklaşık</span><span class="big">${esc(tl(monthly))}</span>
        <div class="grid2"><span>Haftalık<b>${esc(tl(weekly))}</b></span><span>Yıllık<b>${esc(tl(yearly))}</b></span></div></div></div>
      <p class="ay-note">Gidiş-dönüş ${esc(tl(round))}. Ay = 52 hafta ÷ 12.${upcoming ? " " + esc(upcoming) : ""}</p>
      <div class="ay-save"><button type="button" class="btn primary" data-ay="save">${S.saved ? I.check + "Kaydedildi" : I.save + "Rotalarıma kaydet"}</button>
        <span>Yalnızca bu cihazda saklanır, hesap gerekmez.</span></div>`;
  }

  // ------------------------------------------------------------ paylaşım kartı (PNG, tarayıcıda üretilir)

  async function makeCard(btn) {
    const a = S.entry, b = S.exit;
    if (!a || !b) return;
    const all = routes(a, b), idx = Math.min(S.alt, all.length - 1), p = all[idx];
    const v = addFare(planFare(p, S.cls), S.cls);
    try { await Promise.all([document.fonts.load('800 120px "Overpass"'), document.fonts.load('600 32px "Inter"')]); } catch (e) { /* yedek yazı tipi */ }
    const W = 1200, H = 630, c = document.createElement("canvas");
    c.width = W; c.height = H;
    const g = c.getContext("2d");
    const rr = (x, y, w, h, r) => { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); };
    g.fillStyle = "#f2f5f3"; g.fillRect(0, 0, W, H);
    g.fillStyle = "#0d5546"; rr(60, 60, W - 120, 400, 40); g.fill();
    g.strokeStyle = "rgba(255,255,255,.92)"; g.lineWidth = 6; rr(78, 78, W - 156, 364, 28); g.stroke();
    g.fillStyle = "#fff";
    g.font = '600 32px "Inter", sans-serif';
    g.fillText(`${all.length > 1 ? (idx === 0 ? "Doğrudan" : "En ucuz") + " · " : ""}${S.cls}. sınıf · ${CLASSES[S.cls].l}`, 120, 150);
    g.font = '800 140px "Overpass", sans-serif';
    g.fillText(v != null ? fmtNum.format(v) + " ₺" : "—", 112, 300);
    g.font = '800 40px "Overpass", sans-serif';
    g.fillText(`${a.ad} → ${b.ad}`, 120, 380);
    g.font = '500 28px "Inter", sans-serif';
    g.globalAlpha = 0.9;
    const meta = [p.trips.length > 1 ? `${p.trips.length} tarife` : "tek tarife", p.sgs.length ? `${p.sgs.length} serbest geçiş` : "", picked().length ? `${picked().length} köprü/tünel` : "", p.km != null ? fmtKm.format(p.km) + " km" : ""].filter(Boolean).join(" · ");
    g.fillText(meta, 120, 420);
    g.globalAlpha = 1;
    g.fillStyle = "#33443e";
    g.font = '700 30px "Overpass", sans-serif';
    g.fillText("Otoyol Ücretleri", 60, 540);
    g.fillStyle = "#5f716b";
    g.font = '500 24px "Inter", sans-serif';
    const today = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", timeZone: "Europe/Istanbul" }).format(new Date());
    g.fillText(`KGM resmî tarifesi · ${today} · tek yön`, 60, 580);
    c.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `otoyol-ucreti-${fold(a.ad).replace(/ /g, "-")}-${fold(b.ad).replace(/ /g, "-")}.png`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      flash(btn, "İndirildi", "Kart");
    }, "image/png");
  }

  function flash(btn, text, back) {
    const label = btn.querySelector("span");
    if (!label) return;
    label.textContent = text;
    setTimeout(() => { label.textContent = back; }, 1600);
  }
  async function copyLink(btn) {
    try { await navigator.clipboard.writeText(location.href); flash(btn, "Kopyalandı", "Bağlantı"); }
    catch (e) { flash(btn, "Kopyalanamadı", "Bağlantı"); }
  }

  // ------------------------------------------------------------ çizim

  function update(keepView) {
    syncInputs();
    const hasResult = !!(S.entry && S.exit);
    const panel = $("#panel");
    $("#route-fields").classList.toggle("is-compact", hasResult);
    $("#opt-chips").hidden = !hasResult;
    const veh = $("#veh-block");
    veh.hidden = hasResult && !S.vehOpen;
    veh.classList.toggle("is-open", S.vehOpen);
    const xb = $("#opt-extras");
    xb.hidden = !S.extras.length || (hasResult && !S.xOpen);
    xb.classList.toggle("is-open", S.xOpen);
    if (S.xOpen) xb.open = true;
    $("#x-chip").hidden = !S.extras.length;
    renderClasses();
    renderExtras();
    if (S.view === "aylik" && (hasResult || S.extra.size)) {
      $("#rota-main").hidden = true;
      $("#aylik").hidden = false;
      $("#aylik").innerHTML = aylikHtml();
    } else {
      S.view = "main";
      $("#rota-main").hidden = false;
      $("#aylik").hidden = true;
      $("#trip-result").innerHTML = hasResult ? resultHtml(S.entry, S.exit) : !S.entry && !S.exit && S.extra.size ? extrasOnlyHtml() : emptyHtml();
    }
    panel.classList.toggle("has-result", hasResult || S.extra.size > 0);
    panel.classList.toggle("has-trip", hasResult);
    $("#m-res-head").hidden = !hasResult;
    if (hasResult) {
      $("#m-res-title").textContent = `${S.entry.ad} → ${S.exit.ad}`;
      const mc = $("#m-veh-chip");
      mc.innerHTML = clsChipHtml(S.cls);
      mc.setAttribute("aria-expanded", String(S.vehOpen));
      mc.setAttribute("aria-label", `Araç: ${S.cls}. sınıf, ${CLASSES[S.cls].l}. Değiştir`);
      mc.classList.toggle("is-warn", blockedBy(S.cls).length > 0);
    }
    document.body.classList.toggle("has-route", hasResult);
    renderQuick();
    drawRoute(keepView);
    writeHash();
    if (hasResult) remember(false);
    if (S.onChange) S.onChange({ hasResult, hasAny: !!(S.entry || S.exit || S.extra.size) });
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
  // Rota parçaları: tarife yolculukları (sedir) ve aradaki bağlantılar; bağlantıda serbest geçiş varsa mor kesik çizgi.
  function geometry(p) {
    const segments = [], transfers = [], keys = [], roadIds = new Set();
    let prevEnd = null, pendingSgs = [];
    p.legs.forEach((l) => {
      if (l.link) return;
      if (l.sgs) { if (hasPos(l)) pendingSgs.push([l.lat, l.lon]); return; }
      const path = hasPos(l.a) && hasPos(l.b) ? routePath(l.a, l.b) : [];
      if (path.length) {
        if (prevEnd) {
          const bridge = [prevEnd].concat(pendingSgs, [path[0]]);
          if (bridge.length >= 2) segments.push({ path: bridge, kind: pendingSgs.length ? "sgs" : "trip" });
          transfers.push({ lat: path[0][0], lon: path[0][1] });
        }
        segments.push({ path, kind: "trip" });
        prevEnd = path[path.length - 1];
      }
      pendingSgs = [];
      keys.push(l.a.key, l.b.key);
      roadIds.add(l.a.road.id);
    });
    return { segments, transfers, keys, roadIds: [...roadIds] };
  }

  function drawRoute(keepView) {
    if (!S.map || !S.map.showRoute) return;
    const a = S.entry, b = S.exit;
    const stop = (s, role) => (hasPos(s) ? { lat: s.lat, lon: s.lon, name: s.ad, role } : null);
    if (!a && !b) { S.map.clearRoute(); return; }
    const all = a && b ? routes(a, b) : [];
    const idx = Math.min(S.alt, Math.max(0, all.length - 1));
    const p = all[idx] || null;
    const g = p ? geometry(p) : { segments: [], transfers: [], keys: [a, b].filter(Boolean).map((s) => s.key), roadIds: [] };
    let alt = null;
    if (all.length > 1) {
      const oi = idx === 0 ? 1 : 0, o = all[oi];
      const og = geometry(o);
      alt = {
        path: og.segments.reduce((t, s) => t.concat(s.path), []),
        label: `${oi === 0 ? "Doğrudan" : "En ucuz"} · ${tl(addFare(planFare(o, S.cls), S.cls))}`,
        onClick: () => { S.alt = oi; update(); },
      };
    }
    S.map.showRoute({ segments: g.segments, transfers: g.transfers, stationKeys: g.keys, roadIds: g.roadIds, alt,
      entry: a ? stop(a, "in") : null, exit: b ? stop(b, "out") : null, fit: !keepView });
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
    const [ga, gi, ca, ci, cls, xs] = parts.length === 4 ? [parts[0], parts[1], parts[0], parts[2], parts[3]] : parts;
    const get = (id, i) => (i !== "" && i != null ? stationOf(id, i) : null);
    if (CLASSES[cls]) S.cls = cls;
    S.entry = get(ga, gi);
    S.exit = get(ca, ci);
    S.extra = new Set((xs || "").split(",").filter((id) => S.extras.some((c) => c.id === id)));
    return !!(S.entry || S.exit || S.extra.size);
  }

  // ------------------------------------------------------------ dışa açık

  function popupHtml(p) {
    const list = Array.isArray(p.stations) ? p.stations.map((k) => S.byKey.get(k)).filter(Boolean) : [];
    if (!list.length) return "";
    return list.map((s) => `${list.length > 1 ? `<span class="pp-road">${esc(s.road.yol ? s.road.yol + " · " : "")}${esc(roadShort(s.road))}</span>` : ""}
      <button type="button" class="btn" data-trip-role="giris" data-trip-key="${esc(s.key)}"><span class="ab a">A</span>Giriş</button>
      <button type="button" class="btn" data-trip-role="cikis" data-trip-key="${esc(s.key)}"><span class="ab b">B</span>Çıkış</button>`).join("");
  }

  function stationsNear(lat, lon) {
    return S.stations.filter((s) => hasPos(s) && distM({ lat, lon }, s) <= NEAR_M);
  }

  function init(opts) {
    S.h = opts.helpers;
    S.table = opts.table && Array.isArray(opts.table.otoyollar) ? opts.table : null;
    S.cls = opts.cls || "1";
    S.onClass = opts.onClass;
    S.onChange = opts.onChange || null;
    S.map = opts.map || null;
    const d = Number(store("radar.gun"));
    if (d >= 1 && d <= 7) S.days = d;
    if (S.table) index(S.table);
    if (!S.stations.length) S.table = null;
    indexExtras(opts.crossings, S.table);
    const fromHash = S.table ? readHash() : false;

    $("#trip-extras").addEventListener("change", (e) => {
      const b = e.target.closest("[data-extra]");
      if (b) toggleExtra(b.dataset.extra, b.checked);
    });
    if (S.table) { combo("giris"); combo("cikis"); }
    else { $("#trip-giris").disabled = true; $("#trip-cikis").disabled = true; }
    $("#trip-swap").addEventListener("click", swap);
    $("#search-back").addEventListener("click", () => {
      document.querySelectorAll("#trip .combo-list").forEach((l) => { l.hidden = true; });
      document.querySelectorAll("#trip .combo").forEach((c) => c.classList.remove("is-active"));
      $("#panel").classList.remove("is-search");
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    });
    const pickCls = (k) => {
      setClass(k);
      if (S.entry && S.exit || narrow()) { S.vehOpen = false; update(true); }
    };
    $("#trip-classes").addEventListener("click", (e) => { const b = e.target.closest("[data-cls]"); if (b) pickCls(b.dataset.cls); });
    radioKeys($("#trip-classes"), (k) => setClass(k), "data-cls");
    const vehToggle = () => { S.vehOpen = !S.vehOpen; S.xOpen = false; update(true); };
    $("#veh-chip").addEventListener("click", vehToggle);
    $("#m-veh-chip").addEventListener("click", vehToggle);
    $("#x-chip").addEventListener("click", () => { S.xOpen = !S.xOpen; S.vehOpen = false; update(true); });
    $("#quick").addEventListener("click", (e) => {
      const r = e.target.closest("[data-recent-q]");
      if (r) { applyRecent(recents().filter((x) => recentPlan(x))[Number(r.dataset.recentQ)]); return; }
      const p = e.target.closest("[data-preset]");
      if (p && $("#quick")._rows) applyRecent($("#quick")._rows[Number(p.dataset.preset)].r);
    });
    $("#trip-result").addEventListener("click", (e) => {
      const r = e.target.closest("[data-route]");
      if (r) { S.alt = Number(r.dataset.route) || 0; update(); return; }
      const x = e.target.closest("[data-xremove]");
      if (x) { toggleExtra(x.dataset.xremove, false); return; }
      if (e.target.closest("[data-open-veh]")) { S.vehOpen = true; S.xOpen = false; update(true); $("#trip-classes [aria-checked='true']").focus(); return; }
      const m = e.target.closest("[data-more]");
      if (m) { S.more = S.more === m.dataset.more ? "" : m.dataset.more; update(true); return; }
      const b = e.target.closest("[data-act]");
      if (!b) return;
      const act = b.dataset.act;
      if (act === "swap") swap();
      else if (act === "copy") copyLink(b);
      else if (act === "card") makeCard(b);
      else if (act === "aylik") { S.view = "aylik"; S.saved = false; update(true); $("#aylik").scrollIntoView({ block: "start" }); }
    });
    $("#aylik").addEventListener("click", (e) => {
      const d = e.target.closest("[data-day]");
      if (d) { S.days = Number(d.dataset.day); store("radar.gun", String(S.days)); update(true); const f = $(`#ay-days [data-day="${S.days}"]`); if (f) f.focus(); return; }
      const a = e.target.closest("[data-ay]");
      if (!a) return;
      if (a.dataset.ay === "back") { S.view = "main"; update(true); }
      else if (a.dataset.ay === "save") { remember(true); S.saved = true; update(true); }
    });
    radioKeys($("#aylik"), (k) => { S.days = Number(k); store("radar.gun", k); update(true); }, "data-day");
    $("#trip").addEventListener("submit", (e) => e.preventDefault());
    update();
    if (fromHash && S.cls !== opts.cls && S.onClass) S.onClass(S.cls);
    return { ready: !!S.table, fromHash };
  }

  return {
    init, pick, popupHtml, stationsNear, fold, reset,
    setClass: (c) => setClass(c, true),
    allStations: () => S.stations,
    roads: () => S.roads,
    reload: () => { if (readHash()) update(); },
    redraw: () => drawRoute(false),
    className: (k) => (CLASSES[k] ? CLASSES[k].l : ""),
    classes: () => CLASSES,
    clsGridHtml, clsChipHtml, radioKeys, roadShort,
    canAddExtra: (id) => S.extras.some((c) => c.id === id),
    addExtra: (id) => { if (S.extras.some((c) => c.id === id)) { S.view = "main"; toggleExtra(id, true); } },
    hasExtra: (id) => S.extra.has(id),
  };
})();
