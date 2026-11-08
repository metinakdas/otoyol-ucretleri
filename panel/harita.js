"use strict";

/*
 * Harita: köprü/tünel ve otoyol gişeleri, arama, filtreler ve bölgeler.
 * Altlık: OpenStreetMap (ücretsiz). Kütüphane: Leaflet (vendor/leaflet). Leaflet yüklenemezse
 * arama, filtre ve liste yine çalışır; yalnızca harita görünmez.
 */
window.RadarMap = (function () {
  const TYPES = ["kopru", "gise", "serbest"];
  const TYPE_NAMES = { kopru: "Köprü ve tüneller", gise: "Otoyol gişeleri", serbest: "Serbest geçiş noktaları" };
  const TYPE_SHORT = { kopru: "Köprü, tünel", gise: "Gişe", serbest: "Serbest geçiş" };
  const KIND_NAMES = { kopru: "Köprü", tunel: "Tünel", gise: "Otoyol gişesi", serbest: "Serbest geçiş noktası" };
  const TR_BOUNDS = [[35.8, 25.6], [42.2, 44.9]];
  const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
  const LABEL_FONTS = { main: "600 12.5px " + FONT, gate: "500 11.5px " + FONT, chip: "650 11px " + FONT, region: "700 11px " + FONT };
  const LIST_LIMIT = 30;
  const ICONS = {
    kopru: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.8 11.6h12.4M3.2 11.6c1.3-4.2 8.3-4.2 9.6 0M5.6 8.3v3.3M10.4 8.3v3.3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
    tunel: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 12.4V9a4.8 4.8 0 0 1 9.6 0v3.4M1.8 12.4h12.4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  };

  const S = {
    h: null, data: null, mapData: null, cls: "1", onShowCrossing: null,
    points: [], byId: new Map(), regions: [], regionById: {},
    f: { q: "", bolge: "", il: "", yol: "", durum: "", types: new Set(TYPES) },
    visible: [], expanded: new Set(), selected: null,
    map: null, markers: new Map(), labelLayer: null, regionLayer: null, clusterLayer: null, gateRenderer: null,
    clusters: [], clustered: new Set(),
    widths: new Map(), measureCtx: null, colors: {}, searchTimer: null,
  };

  // ------------------------------------------------------------ yardımcılar

  const $ = (sel) => document.querySelector(sel);
  const FOLD = { "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u" };
  function fold(s) {
    return String(s || "").toLocaleLowerCase("tr").replace(/[çğıöşüâîû]/g, (c) => FOLD[c]).replace(/\s+/g, " ").trim();
  }
  function refKey(ref) {
    const m = /^([^\d]*?)[-\s]?(\d+)(.*)$/.exec(ref || "");
    return m ? [m[1].toUpperCase() === "O" ? 0 : 1, m[1], Number(m[2]), m[3]] : [2, ref || "", 0, ""];
  }
  function compareRefs(a, b) {
    const ka = refKey(a), kb = refKey(b);
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] < kb[i]) return -1;
      if (ka[i] > kb[i]) return 1;
    }
    return 0;
  }
  function regionName(id) { return (S.regionById[id] || {}).ad || "Bölgesi bilinmiyor"; }
  function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  // ------------------------------------------------------------ veri

  function buildPoints() {
    const freeSoon = new Set();
    (S.data.next_rules || []).forEach((r) => (r.crossings || []).forEach((id) => freeSoon.add(typeof id === "string" ? id : id.id)));
    const pts = [];
    (S.data.crossings || []).forEach((c) => {
      if (!c.konum) return;
      pts.push({
        id: "gecis:" + c.id, type: "kopru", kind: c.tur || "kopru", name: c.name, unnamed: false,
        lat: c.konum[0], lon: c.konum[1], iller: c.iller || [], bolge: c.bolge, yol: null, yolAdi: null,
        operator: c.operator, crossing: c, freeSoon: freeSoon.has(c.id), n: 99,
      });
    });
    ((S.mapData && S.mapData.noktalar) || []).forEach((p) => {
      pts.push({
        id: p.id, type: p.tur === "serbest" ? "serbest" : "gise", kind: p.tur === "serbest" ? "serbest" : "gise",
        name: p.ad, unnamed: !!p.adsiz, lat: p.lat, lon: p.lon, iller: p.il ? [p.il] : [], bolge: p.bolge,
        yol: p.yol, yolAdi: p.yol_adi, operator: p.isletmeci, osm: p.osm, n: p.nokta_sayisi || 1,
      });
    });
    pts.forEach((p) => {
      p.status = statusOf(p);
      p.search = fold([p.name, KIND_NAMES[p.kind], p.iller.join(" "), regionName(p.bolge), p.yol, p.yolAdi, p.operator,
        p.crossing ? p.crossing.id.replace(/-/g, " ") : "", p.crossing ? (p.crossing.diger_adlar || []).join(" ") : ""].join(" "));
      S.byId.set(p.id, p);
    });
    return pts;
  }

  function statusOf(p) {
    const c = p.crossing;
    if (!c) return null;
    if (c.free_now) return { key: "ucretsiz", cls: "free", short: "ücretsiz" };
    if (c.upcoming) return { key: "degisecek", cls: "change", short: "değişecek" };
    if (p.freeSoon) return { key: "ucretsiz", cls: "free", short: "ücretsiz olacak" };
    return null;
  }

  // ------------------------------------------------------------ filtre

  function matches(p, skip) {
    const f = S.f;
    if (skip !== "types" && !f.types.has(p.type)) return false;
    if (skip !== "bolge" && f.bolge && p.bolge !== f.bolge) return false;
    if (skip !== "il" && f.il && !p.iller.includes(f.il)) return false;
    if (skip !== "yol" && f.yol && p.yol !== f.yol) return false;
    if (skip !== "durum" && f.durum && !(p.status && p.status.key === f.durum)) return false;
    if (f.q) {
      for (const token of f.q.split(" ")) if (!p.search.includes(token)) return false;
    }
    return true;
  }

  function apply(opts) {
    const o = opts || {};
    S.visible = S.points.filter((p) => matches(p));
    if (S.selected && !S.visible.some((p) => p.id === S.selected)) deselect();
    renderTypeChips();
    renderRegionChips();
    renderSelects();
    renderList();
    renderMeta();
    syncMarkers();
    if (o.fit) fitTo(S.visible, o.region);
    placeLabels();
  }

  function clearFilters() {
    S.f = { q: "", bolge: "", il: "", yol: "", durum: "", types: new Set(TYPES) };
    $("#map-search").value = "";
    apply({ fit: true });
  }

  // ------------------------------------------------------------ denetimler

  function renderTypeChips() {
    const counts = {};
    S.points.forEach((p) => { if (matches(p, "types")) counts[p.type] = (counts[p.type] || 0) + 1; });
    const present = TYPES.filter((t) => S.points.some((p) => p.type === t));
    $("#map-types").innerHTML = `<span class="row-label">Göster</span>` + present.map((t) => `
      <button type="button" class="fchip type-chip" data-type="${t}" aria-pressed="${S.f.types.has(t)}">
        <span class="sw sw-${t}" aria-hidden="true"></span><span class="long">${TYPE_NAMES[t]}</span><span class="short">${TYPE_SHORT[t]}</span><span class="n">${counts[t] || 0}</span>
      </button>`).join("");
  }

  function renderRegionChips() {
    const counts = {};
    let total = 0;
    S.points.forEach((p) => {
      if (!matches(p, "bolge")) return;
      total++;
      counts[p.bolge] = (counts[p.bolge] || 0) + 1;
    });
    const chip = (id, label, n) => `<button type="button" class="fchip region-chip" data-region="${id}"
        aria-pressed="${S.f.bolge === id}" ${n || S.f.bolge === id ? "" : "disabled"}>${label}<span class="n">${n}</span></button>`;
    $("#map-regions").innerHTML = `<span class="row-label">Bölgeler</span>` + chip("", "Tümü", total) +
      S.regions.map((r) => chip(r.id, S.h.esc(r.ad), counts[r.id] || 0)).join("");
  }

  function renderSelects() {
    const esc = S.h.esc;
    const ilCounts = new Map();
    S.points.forEach((p) => { if (matches(p, "il")) p.iller.forEach((il) => ilCounts.set(il, (ilCounts.get(il) || 0) + 1)); });
    if (S.f.il && !ilCounts.has(S.f.il)) ilCounts.set(S.f.il, 0);
    const iller = [...ilCounts.keys()].sort((a, b) => a.localeCompare(b, "tr"));
    $("#f-il").innerHTML = `<option value="">Tüm iller</option>` +
      iller.map((il) => `<option value="${esc(il)}" ${il === S.f.il ? "selected" : ""}>${esc(il)} (${ilCounts.get(il)})</option>`).join("");

    const yolCounts = new Map(), yolNames = new Map();
    S.points.forEach((p) => {
      if (!p.yol || !matches(p, "yol")) return;
      yolCounts.set(p.yol, (yolCounts.get(p.yol) || 0) + 1);
      if (p.yolAdi && !yolNames.has(p.yol)) yolNames.set(p.yol, p.yolAdi);
    });
    if (S.f.yol && !yolCounts.has(S.f.yol)) yolCounts.set(S.f.yol, 0);
    const yollar = [...yolCounts.keys()].sort(compareRefs);
    const sel = $("#f-yol");
    sel.innerHTML = `<option value="">Tüm yollar</option>` + yollar.map((y) =>
      `<option value="${esc(y)}" ${y === S.f.yol ? "selected" : ""}>${esc(y)}${yolNames.has(y) ? " · " + esc(yolNames.get(y)) : ""} (${yolCounts.get(y)})</option>`).join("");
    sel.disabled = !yollar.length;
    $("#f-durum").value = S.f.durum;
  }

  function priceLine(p) {
    const c = p.crossing;
    const v = c.current && c.current.classes[S.cls];
    return v != null ? `${S.cls}. sınıf ${S.h.money(v)}` : c.id === "avrasya-tuneli" ? "duyurular izleniyor" : "ücret kaydı yok";
  }

  function itemSub(p) {
    if (p.crossing) return [p.iller.join(" / "), p.operator, priceLine(p)].filter(Boolean).join(" · ");
    return [p.iller.join(" / ") || "il bilinmiyor", p.yol ? p.yol + (p.yolAdi ? " " + p.yolAdi : "") : null].filter(Boolean).join(" · ");
  }

  function renderList() {
    const esc = S.h.esc;
    const el = $("#map-list");
    if (!S.visible.length) {
      el.innerHTML = `<div class="list-empty"><p>Bu arama ve filtrelerle eşleşen nokta yok.</p>
        <button type="button" class="link-btn" data-action="clear">Filtreleri temizle</button></div>`;
      return;
    }
    const groups = new Map();
    S.visible.forEach((p) => {
      const key = p.bolge || "";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(p);
    });
    const order = S.regions.map((r) => r.id).concat([""]);
    const html = [];
    order.forEach((rid) => {
      const items = groups.get(rid);
      if (!items) return;
      items.sort((a, b) => (a.type === "kopru" ? 0 : 1) - (b.type === "kopru" ? 0 : 1) || (a.unnamed - b.unnamed) ||
        a.name.localeCompare(b.name, "tr"));
      const limit = S.expanded.has(rid) ? items.length : LIST_LIMIT;
      html.push(`<div class="grp"><div class="grp-h"><span>${esc(regionName(rid))}</span><span>${items.length}</span></div>`);
      items.slice(0, limit).forEach((p) => {
        html.push(`<button type="button" class="pt${p.unnamed ? " unnamed" : ""}${p.id === S.selected ? " is-selected" : ""}" data-id="${esc(p.id)}">
          <span class="sw sw-${p.type}" aria-hidden="true"></span>
          <span class="pt-main"><span class="pt-name">${esc(p.name)}</span><span class="pt-sub">${esc(itemSub(p))}</span></span>
          ${p.status ? `<span class="pt-chip ${p.status.cls}">${esc(p.status.short)}</span>` : ""}
        </button>`);
      });
      if (items.length > limit) {
        html.push(`<button type="button" class="more" data-expand="${rid}">${items.length - limit} nokta daha göster</button>`);
      }
      html.push(`</div>`);
    });
    el.innerHTML = html.join("");
  }

  function renderMeta() {
    const nCross = S.points.filter((p) => p.type === "kopru").length;
    const nGates = S.points.length - nCross;
    const shown = S.visible.length === S.points.length ? "" : ` · ${S.visible.length} gösteriliyor`;
    $("#map-meta").textContent = `${nCross} köprü ve tünel · ${nGates} gişe noktası${shown}`;
  }

  function renderNote() {
    const h = S.h;
    const parts = [];
    const md = S.mapData;
    if (md && md.ornek) parts.push("Gişeler örnek veridir; gerçek konumlar OpenStreetMap'ten ayda bir alınır.");
    else if (md) parts.push(`Gişe konumları: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> katkıcıları (ODbL), güncelleme ${h.esc(h.date(md.olusturma))}.`);
    else parts.push("Otoyol gişeleri henüz alınmadı. Radar ilk turda OpenStreetMap'ten alır; elle almak için <code>python -m radar harita-guncelle</code>.");
    const err = S.data.harita && S.data.harita.hata;
    if (err) parts.push(`<span class="chip bad">Son gişe güncellemesi başarısız</span> ${h.esc(err.slice(0, 160))}`);
    parts.push("Köprü ve tünel konumları yaklaşıktır. Fareyle yakınlaştırmak için önce haritaya tıklayın.");
    $("#map-note").innerHTML = parts.join(" ");
  }

  // ------------------------------------------------------------ harita

  function readColors() {
    S.colors = { gise: cssVar("--m-gise") || "#eb6834", ring: cssVar("--surface") || "#ffffff" };
  }

  function gateRadius() {
    const z = S.map ? S.map.getZoom() : 6;
    return z <= 6 ? 4 : z <= 9 ? 5 : 6.5;
  }

  function gateStyle(selected) {
    return { radius: gateRadius() + (selected ? 3 : 0), color: S.colors.ring, weight: selected ? 3 : 2,
      fillColor: S.colors.gise, fillOpacity: 1, opacity: 1 };
  }

  function createMap() {
    const el = $("#map");
    if (!window.L) {
      el.innerHTML = `<p class="map-missing">Harita kütüphanesi yüklenemedi. Liste, arama ve filtreler çalışmaya devam eder.</p>`;
      return;
    }
    readColors();
    const map = L.map(el, {
      minZoom: 4, maxZoom: 18, zoomSnap: 0.5, scrollWheelZoom: false,
      maxBounds: L.latLngBounds([[32.5, 20], [45.5, 50]]), maxBoundsViscosity: 0.7,
    });
    S.map = map;
    map.createPane("regions").style.zIndex = 350;
    const labels = map.createPane("labels");
    labels.style.zIndex = 450;
    labels.style.pointerEvents = "none";
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> katkıcıları',
    }).addTo(map);
    S.gateRenderer = L.canvas({ padding: 0.5, tolerance: 7 });
    S.labelLayer = L.layerGroup().addTo(map);
    S.regionLayer = L.layerGroup().addTo(map);
    S.clusterLayer = L.layerGroup().addTo(map);
    map.fitBounds(TR_BOUNDS);

    S.points.forEach((p) => S.markers.set(p.id, createMarker(p)));

    map.on("click focus", () => map.scrollWheelZoom.enable());
    el.addEventListener("mouseleave", () => map.scrollWheelZoom.disable());
    map.on("zoomend", () => {
      const style = gateStyle(false);
      S.markers.forEach((m, id) => { if (m.options.isGate) m.setStyle(id === S.selected ? gateStyle(true) : style); });
      clusterMain();
    });
    map.on("zoomend moveend", placeLabels);
    map.on("popupclose", () => deselect());
    el.addEventListener("click", (e) => {
      const a = e.target.closest("[data-show-crossing]");
      if (a) {
        e.preventDefault();
        if (S.onShowCrossing) S.onShowCrossing(a.dataset.showCrossing);
      }
    });
    try {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        readColors();
        S.markers.forEach((m, id) => { if (m.options.isGate) m.setStyle(gateStyle(id === S.selected)); });
      });
    } catch (e) { /* eski tarayıcı */ }
  }

  function createMarker(p) {
    let m;
    if (p.type === "gise") {
      m = L.circleMarker([p.lat, p.lon], Object.assign(gateStyle(false), { renderer: S.gateRenderer, isGate: true }));
    } else if (p.type === "serbest") {
      m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "gantry-wrap", html: '<span class="gantry"></span>', iconSize: [14, 14], iconAnchor: [7, 7] }),
        title: p.name, keyboard: true,
      });
    } else {
      m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "pin-wrap", html: `<span class="pin pin-${p.kind}">${ICONS[p.kind] || ICONS.kopru}</span>`,
          iconSize: [26, 26], iconAnchor: [13, 13] }),
        title: p.name, keyboard: true, riseOnHover: true, zIndexOffset: 1000,
      });
    }
    m.bindTooltip(() => `<strong>${S.h.esc(p.name)}</strong><br><span>${S.h.esc(itemSub(p))}</span>`,
      { direction: "top", offset: [0, p.type === "kopru" ? -12 : -6], className: "radar-tip" });
    m.bindPopup(() => popupHtml(p), { maxWidth: 290, minWidth: 220, className: "radar-pop", autoPanPadding: [24, 24] });
    m.on("popupopen", () => select(p.id, false));
    return m;
  }

  function syncMarkers() {
    if (!S.map) return;
    const show = new Set(S.visible.map((p) => p.id));
    S.markers.forEach((m, id) => {
      const on = S.map.hasLayer(m);
      if (show.has(id) && !on) m.addTo(S.map);
      else if (!show.has(id) && on) m.remove();
    });
    clusterMain();
  }

  // Uzaklaşınca üst üste binen köprü/tünel işaretleri (ör. İstanbul'daki dört geçiş) tek işarette toplanır.
  function clusterMain() {
    if (!S.map) return;
    S.clusterLayer.clearLayers();
    S.clusters = [];
    S.clustered = new Set();
    const mains = S.visible.filter((p) => p.type === "kopru").map((p) => ({ p, pt: S.map.latLngToContainerPoint([p.lat, p.lon]) }));
    const groups = [];
    mains.forEach((a) => {
      const g = groups.find((grp) => grp.some((b) => Math.hypot(a.pt.x - b.pt.x, a.pt.y - b.pt.y) < 30));
      if (g) g.push(a); else groups.push([a]);
    });
    groups.forEach((g) => {
      if (g.length < 2 || g.some((x) => x.p.id === S.selected)) return;
      const pts = g.map((x) => x.p);
      pts.forEach((p) => S.clustered.add(p.id));
      const lat = pts.reduce((t, p) => t + p.lat, 0) / pts.length;
      const lon = pts.reduce((t, p) => t + p.lon, 0) / pts.length;
      const iller = [...new Set(pts.flatMap((p) => p.iller))];
      const regions = [...new Set(pts.map((p) => p.bolge))];
      const place = iller.length === 1 ? iller[0] : regions.length === 1 && regions[0] ? regionName(regions[0]) : "";
      const name = (place ? place + " · " : "") + pts.length + " geçiş";
      const cluster = { id: "kume:" + pts.map((p) => p.id).join(","), lat, lon, name, points: pts, type: "kume", n: 1000 };
      S.clusters.push(cluster);
      const esc = S.h.esc;
      L.marker([lat, lon], {
        icon: L.divIcon({ className: "pin-wrap", html: `<span class="pin pin-cluster">${pts.length}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] }),
        title: name, keyboard: true, zIndexOffset: 1100,
      })
        .bindTooltip(`<strong>${esc(name)}</strong><br><span>${pts.map((p) => esc(p.name)).join("<br>")}</span>`,
          { direction: "top", offset: [0, -14], className: "radar-tip" })
        .on("click", () => S.map.fitBounds(L.latLngBounds(pts.map((p) => [p.lat, p.lon])), { padding: [70, 70], maxZoom: 13 }))
        .addTo(S.clusterLayer);
    });
    S.markers.forEach((m, id) => {
      const p = S.byId.get(id);
      if (!p || p.type !== "kopru" || !S.visible.includes(p)) return;
      const on = S.map.hasLayer(m);
      if (S.clustered.has(id) && on) m.remove();
      else if (!S.clustered.has(id) && !on) m.addTo(S.map);
    });
  }

  function fitTo(points, regionId) {
    if (!S.map) return;
    if (!points.length) {
      const r = S.regionById[regionId];
      S.map.fitBounds(r ? r.sinir : TR_BOUNDS);
      return;
    }
    if (points.length === 1) {
      S.map.setView([points[0].lat, points[0].lon], Math.max(S.map.getZoom(), 11));
      return;
    }
    S.map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lon])), { padding: [40, 40], maxZoom: 11 });
  }

  // ------------------------------------------------------------ etiketler (çakışmasız)

  function textWidth(text, font) {
    if (!S.measureCtx) S.measureCtx = document.createElement("canvas").getContext("2d");
    const key = font + "|" + text;
    if (!S.widths.has(key)) {
      S.measureCtx.font = font;
      S.widths.set(key, S.measureCtx.measureText(text).width);
    }
    return S.widths.get(key);
  }

  function labelSize(p) {
    const main = p.type === "kopru" || p.type === "kume";
    let w = textWidth(p.name, main ? LABEL_FONTS.main : LABEL_FONTS.gate) + 6;
    if (main && p.status) w += textWidth(p.status.short, LABEL_FONTS.chip) + 16;
    return { w, h: main ? 20 : 16 };
  }

  // Kutular: [x1, y1, x2, y2, sahibi]. Etiket kendi işaretiyle çakışmış sayılmaz.
  const overlaps = (a, boxes, owner) => boxes.some((b) => (owner === undefined || b[4] !== owner) &&
    !(a[2] <= b[0] || a[0] >= b[2] || a[3] <= b[1] || a[1] >= b[3]));

  function placeLabels() {
    if (!S.map) return;
    S.labelLayer.clearLayers();
    S.regionLayer.clearLayers();
    const z = S.map.getZoom();
    const size = S.map.getSize();
    const view = S.map.getBounds().pad(0.02);
    const inView = S.visible.filter((p) => !S.clustered.has(p.id) && view.contains([p.lat, p.lon]))
      .concat(S.clusters.filter((c) => view.contains([c.lat, c.lon])));
    // Ana etiketler (köprü, tünel, küme) yalnızca işaretlerden ve diğer etiketlerden kaçar; gişe etiketleri noktalardan da.
    const boxes = [];      // ana işaretler + yerleşen etiketler
    const dots = [];       // gişe noktaları
    const pos = new Map();
    inView.forEach((p) => {
      const pt = S.map.latLngToContainerPoint([p.lat, p.lon]);
      pos.set(p.id, pt);
      const r = p.type === "kume" ? 16 : p.type === "kopru" ? 14 : 6;
      (r > 6 ? boxes : dots).push([pt.x - r, pt.y - r, pt.x + r, pt.y + r, p.id]);
    });
    const main = (p) => (p.type === "kume" || p.type === "kopru" ? 0 : 1);
    const cands = inView.filter((p) => main(p) === 0 || p.id === S.selected || (!p.unnamed && z >= 8));
    cands.sort((a, b) => (b.id === S.selected) - (a.id === S.selected) || main(a) - main(b) ||
      (b.n || 0) - (a.n || 0) || a.name.localeCompare(b.name, "tr"));
    let placed = 0;
    for (const p of cands) {
      if (placed >= 150) break;
      const pt = pos.get(p.id);
      const { w, h } = labelSize(p);
      const off = p.type === "kume" ? 19 : p.type === "kopru" ? 19 : 9;
      const options = [
        ["right", pt.x + off, pt.y - h / 2, pt.x + off + w, pt.y + h / 2],
        ["left", pt.x - off - w, pt.y - h / 2, pt.x - off, pt.y + h / 2],
        ["above", pt.x - w / 2, pt.y - off - h, pt.x + w / 2, pt.y - off],
        ["below", pt.x - w / 2, pt.y + off, pt.x + w / 2, pt.y + off + h],
      ];
      for (const [where, x1, y1, x2, y2] of options) {
        if (x1 < 2 || y1 < 2 || x2 > size.x - 2 || y2 > size.y - 18) continue;
        const box = [x1 - 3, y1 - 1, x2 + 3, y2 + 1];
        if (overlaps(box, boxes, p.id) || (main(p) === 1 && overlaps(box, dots, p.id))) continue;
        boxes.push(box);
        addLabel(p, where);
        placed++;
        break;
      }
    }
    if (z <= 7.5) placeRegionLabels(boxes.concat(dots));
  }

  function addLabel(p, where) {
    const esc = S.h.esc;
    const main = p.type === "kopru" || p.type === "kume";
    const chip = main && p.status ? `<span class="lbl-chip ${p.status.cls}">${esc(p.status.short)}</span>` : "";
    L.marker([p.lat, p.lon], {
      icon: L.divIcon({ className: `lbl-anchor pos-${where} ${main ? "is-main" : "is-gate"}${p.type === "kume" ? " is-cluster" : ""}`, iconSize: [0, 0], iconAnchor: [0, 0],
        html: `<span class="lbl${p.id === S.selected ? " is-selected" : ""}">${esc(p.name)}${chip}</span>` }),
      interactive: false, keyboard: false, pane: "labels",
    }).addTo(S.labelLayer);
  }

  function placeRegionLabels(boxes) {
    const size = S.map.getSize();
    S.regions.forEach((r) => {
      if (S.f.bolge && S.f.bolge !== r.id) return;
      const pt = S.map.latLngToContainerPoint(r.etiket);
      const w = textWidth(r.ad.toLocaleUpperCase("tr"), LABEL_FONTS.region) * 1.12 + 4;
      const box = [pt.x - w / 2, pt.y - 8, pt.x + w / 2, pt.y + 8];
      if (box[0] < 0 || box[1] < 0 || box[2] > size.x || box[3] > size.y || overlaps(box, boxes)) return;
      boxes.push(box);
      L.marker(r.etiket, {
        icon: L.divIcon({ className: "rlbl-anchor", iconSize: [0, 0], iconAnchor: [0, 0],
          html: `<span class="rlbl${S.f.bolge === r.id ? " is-active" : ""}">${S.h.esc(r.ad)}</span>` }),
        interactive: false, keyboard: false, pane: "regions",
      }).addTo(S.regionLayer);
    });
  }

  // ------------------------------------------------------------ açılır pencere ve seçim

  function popupHtml(p) {
    const h = S.h, esc = h.esc;
    const head = `<div class="pop-k">${esc(KIND_NAMES[p.kind] || "")}${p.operator && p.crossing ? " · " + esc(p.operator) : ""}</div>
      <div class="pop-t">${esc(p.name)}</div>
      <div class="pop-s">${esc([p.iller.join(" / "), regionName(p.bolge)].filter(Boolean).join(" · "))}</div>`;
    if (p.crossing) {
      const c = p.crossing;
      const cur = c.current && c.current.classes[S.cls];
      const rows = [`<div class="pop-row"><span>${esc(h.className(S.cls))}</span><b>${cur != null ? esc(h.money(cur)) : "—"}</b></div>`];
      if (c.free_now) rows.push(`<div class="pop-st free">Ücretsiz geçiş sürüyor · bitiş ${esc(h.dateTime(c.free_now.valid_to))}</div>`);
      if (c.upcoming) rows.push(`<div class="pop-st change">${esc(h.date(c.upcoming.valid_from))} tarihinden itibaren <b>${esc(h.money(c.upcoming.classes[S.cls]))}</b></div>`);
      (S.data.next_rules || []).filter((r) => (r.crossings || []).includes(c.id)).slice(0, 1).forEach((r) => rows.push(
        `<div class="pop-st free">Ücretsiz geçiş kararı: ${esc(h.dateTime(r.valid_from))} – ${esc(h.dateTime(r.valid_to))}</div>`));
      if (cur == null && c.id === "avrasya-tuneli") rows.push(`<div class="pop-n">Ücretler işletmecinin duyurularından izleniyor.</div>`);
      return `<div class="pop">${head}${rows.join("")}
        <div class="pop-a"><a href="#prices-title" data-show-crossing="${esc(c.id)}">Tüm sınıflar ve geçmiş</a></div></div>`;
    }
    const rows = [];
    if (p.yol) rows.push(`<div class="pop-row"><span>Yol</span><b>${esc(p.yol)}${p.yolAdi ? " · " + esc(p.yolAdi) : ""}</b></div>`);
    if (p.operator) rows.push(`<div class="pop-row"><span>İşletmeci</span><b>${esc(p.operator)}</b></div>`);
    rows.push(`<div class="pop-n">Otoyol ücreti giriş ve çıkış gişesine göre değişir; tutarlar KGM tarife belgelerindedir.</div>`);
    const osm = /^(node|way|relation)\/\d+$/.test(p.osm || "")
      ? `<div class="pop-a"><a href="https://www.openstreetmap.org/${esc(p.osm)}" target="_blank" rel="noopener noreferrer">OpenStreetMap'te aç</a></div>` : "";
    return `<div class="pop">${head}${rows.join("")}${osm}</div>`;
  }

  function markSelected(id, on) {
    const m = S.markers.get(id);
    if (!m) return;
    if (m.options.isGate) {
      m.setStyle(gateStyle(on));
      if (on) m.bringToFront();
    } else if (m.getElement && m.getElement()) {
      m.getElement().classList.toggle("is-selected", on);
    }
  }

  function select(id, scrollList) {
    if (S.selected === id) return;
    if (S.selected) markSelected(S.selected, false);
    S.selected = id;
    clusterMain();
    markSelected(id, true);
    const p = S.byId.get(id);
    if (p && !S.expanded.has(p.bolge || "")) {
      const group = S.visible.filter((q) => (q.bolge || "") === (p.bolge || ""));
      if (group.indexOf(p) >= LIST_LIMIT) S.expanded.add(p.bolge || "");
    }
    renderList();
    placeLabels();
    if (scrollList !== false) {
      const el = document.querySelector(`#map-list [data-id="${CSS.escape(id)}"]`);
      const list = $("#map-list");
      if (el && list && list.scrollHeight > list.clientHeight) {
        list.scrollTop = el.offsetTop - list.clientHeight / 2 + el.offsetHeight / 2;
      }
    }
  }

  function deselect() {
    if (!S.selected) return;
    markSelected(S.selected, false);
    S.selected = null;
    document.querySelectorAll("#map-list .pt.is-selected").forEach((b) => b.classList.remove("is-selected"));
    clusterMain();
    placeLabels();
  }

  function focusPoint(id, scrollToMap) {
    const p = S.byId.get(id);
    if (!p) return;
    if (!S.visible.includes(p)) clearFilters();
    select(id, true);
    if (scrollToMap) $("#map").scrollIntoView({ behavior: "smooth", block: "center" });
    if (!S.map) return;
    const m = S.markers.get(id);
    const zoom = Math.max(S.map.getZoom(), p.type === "kopru" ? 12 : 13);
    const target = L.latLng(p.lat, p.lon);
    if (S.map.getCenter().distanceTo(target) < 30 && S.map.getZoom() === zoom) {
      m.openPopup();
      return;
    }
    S.map.once("moveend", () => m.openPopup());
    S.map.flyTo(target, zoom, { duration: 0.6 });
  }

  // ------------------------------------------------------------ olaylar

  function bindEvents() {
    $("#map-search").addEventListener("input", (e) => {
      clearTimeout(S.searchTimer);
      S.searchTimer = setTimeout(() => { S.f.q = fold(e.target.value); apply(); }, 120);
    });
    $("#map-search").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        clearTimeout(S.searchTimer);
        S.f.q = fold(e.target.value);
        apply();
        const q = S.f.q;
        const best = S.visible.find((p) => fold(p.name) === q) || S.visible.find((p) => fold(p.name).startsWith(q)) || S.visible[0];
        if (best) focusPoint(best.id, false);
      } else if (e.key === "Escape" && e.target.value) {
        e.target.value = "";
        S.f.q = "";
        apply();
      }
    });
    $("#map-types").addEventListener("click", (e) => {
      const b = e.target.closest("[data-type]");
      if (!b) return;
      const t = b.dataset.type;
      if (S.f.types.has(t)) S.f.types.delete(t); else S.f.types.add(t);
      apply();
    });
    $("#map-regions").addEventListener("click", (e) => {
      const b = e.target.closest("[data-region]");
      if (!b || b.disabled) return;
      const id = b.dataset.region;
      S.f.bolge = S.f.bolge === id ? "" : id;
      if (S.f.il && !S.points.some((p) => p.iller.includes(S.f.il) && (!S.f.bolge || p.bolge === S.f.bolge))) S.f.il = "";
      apply({ fit: true, region: S.f.bolge });
    });
    $("#f-il").addEventListener("change", (e) => { S.f.il = e.target.value; apply({ fit: true }); });
    $("#f-yol").addEventListener("change", (e) => { S.f.yol = e.target.value; apply({ fit: true }); });
    $("#f-durum").addEventListener("change", (e) => { S.f.durum = e.target.value; apply({ fit: true }); });
    $("#f-temizle").addEventListener("click", clearFilters);
    $("#map-list").addEventListener("click", (e) => {
      const item = e.target.closest("[data-id]");
      if (item) { focusPoint(item.dataset.id, window.matchMedia("(max-width: 860px)").matches); return; }
      const more = e.target.closest("[data-expand]");
      if (more) { S.expanded.add(more.dataset.expand); renderList(); return; }
      if (e.target.closest('[data-action="clear"]')) clearFilters();
    });
  }

  // ------------------------------------------------------------ dışa açık

  function init(opts) {
    S.h = opts.helpers;
    S.data = opts.data;
    S.mapData = opts.mapData;
    S.cls = opts.cls || "1";
    S.onShowCrossing = opts.onShowCrossing;
    S.regions = S.data.bolgeler || [];
    S.regions.forEach((r) => { S.regionById[r.id] = r; });
    S.points = buildPoints();
    if (!S.points.length) {
      $("#map-card").hidden = true;
      return;
    }
    renderNote();
    bindEvents();
    createMap();
    apply({ fit: true });
  }

  function setClass(cls) {
    S.cls = cls;
    renderList();
  }

  function focusCrossing(crossingId) {
    focusPoint("gecis:" + crossingId, true);
  }

  return { init, setClass, focusCrossing, fold };
})();
