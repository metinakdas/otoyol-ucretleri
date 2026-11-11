"use strict";

/*
 * Harita: köprü/tüneller (config/crossings.yaml), otoyol gişeleri ve serbest geçişler (config/giseler.yaml → ucret-tablosu.json).
 * Haritadan veri alınmaz; OpenStreetMap yalnızca altlık karolarıdır. Kütüphane: Leaflet (vendor/leaflet).
 *
 * Yoğunluk kuralı (tasarım: "Tabela dili"): yakınlık ≤ 9'da gişeler kümelenir; 10–11'de rota çizilmişse yalnızca
 * rotadaki otoyolların gişeleri; ≥ 12'de hepsi. Etiket önceliği: rota › köprü › gişe.
 */
window.RadarMap = (function () {
  const TR_BOUNDS = [[35.8, 25.9], [42.2, 44.8]];
  const FONT = '"Inter", system-ui, sans-serif';
  const LABEL_FONTS = { main: "600 12px " + FONT, gate: "600 11.5px " + FONT, route: "700 13px " + FONT };
  const KIND_NAMES = { kopru: "Köprü", tunel: "Tünel", gise: "Otoyol gişesi", serbest: "Serbest geçiş" };
  const TYPES = [["kopru", "Köprü ve tünel"], ["gise", "Gişe"], ["serbest", "Serbest geçiş"]];
  const ICONS = {
    kopru: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 16h18M5 16V9M19 16V9M5 9c3 4 11 4 14 0"/></svg>',
    tunel: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V12a8 8 0 0 1 16 0v7M4 19h16"/></svg>',
  };
  const GANTRY = '<svg viewBox="0 0 28 20" aria-hidden="true"><path d="M2 16h24M6 16V6h16v10"/><path d="M10 6V3M18 6V3"/><path d="M10 11h8" stroke-dasharray="2 2"/></svg>';
  const CLUSTER_ZOOM = 9;      // bu yakınlık ve altında gişeler kümelenir
  const ROAD_ONLY_ZOOM = 12;   // rota varken bu yakınlığın altında yalnızca rotadaki otoyolların gişeleri

  const S = {
    h: null, data: null, stations: [], cls: "1",
    onShowCrossing: null, onTrip: null, onAddExtra: null, canAddExtra: null, popupExtra: null,
    map: null, gateRenderer: null, markers: new Map(), labelLayer: null, clusterLayer: null, gateClusterLayer: null, routeLayer: null,
    points: [], byId: new Map(), clusters: [], clustered: new Set(), gateClustered: new Set(), selected: null, route: null,
    widths: new Map(), measureCtx: null, colors: {},
    roads: [], f: { types: new Set(["kopru", "gise", "serbest"]), road: "", bolge: "", il: "", durum: "" },
  };
  const FOLD = { "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u" };
  const fold = (s) => String(s || "").toLocaleLowerCase("tr").replace(/[çğıöşüâîû]/g, (c) => FOLD[c]).replace(/[^a-z0-9]+/g, " ").trim();
  const $ = (sel) => document.querySelector(sel);
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const narrow = () => window.matchMedia("(max-width: 900px)").matches;

  function distM(lat1, lon1, lat2, lon2) {
    const r = Math.PI / 180;
    const x = Math.sin((lat2 - lat1) * r / 2) ** 2 + Math.cos(lat1 * r) * Math.cos(lat2 * r) * Math.sin((lon2 - lon1) * r / 2) ** 2;
    return 12742000 * Math.asin(Math.sqrt(x));
  }

  // ------------------------------------------------------------ veri

  function buildPoints() {
    const freeSoon = new Set();
    (S.data.next_rules || []).forEach((r) => (r.crossings || []).forEach((id) => freeSoon.add(typeof id === "string" ? id : id.id)));
    const pts = [];
    (S.data.crossings || []).forEach((c) => {
      if (!c.konum) return;
      const status = c.free_now || freeSoon.has(c.id) ? "free" : c.upcoming ? "change" : "";
      pts.push({ id: "gecis:" + c.id, type: "kopru", kind: c.tur || "kopru", name: c.name, lat: c.konum[0], lon: c.konum[1],
        bolge: c.bolge || null, iller: c.iller || [],
        sub: [(c.iller || []).join(" / "), c.operator].filter(Boolean).join(" · "), crossing: c, status, n: 99 });
    });
    gates().forEach((g) => pts.push(g));
    freeFlow().forEach((g) => pts.push(g));
    pts.forEach((p) => {
      p.roadIds = p.roadIds || [];
      p.q = fold([p.name, p.sub, (p.roads || []).join(" "), (p.iller || []).join(" ")].join(" "));
      S.byId.set(p.id, p);
    });
    return pts;
  }

  // Serbest geçiş (SGS) noktaları: tarifelerin "serbest_gecis" listesinden. A/B ya da iki yön aynı yerdedir.
  function freeFlow() {
    const out = [];
    S.roads.forEach((o) => {
      const groups = [];
      (o.serbest_gecis || []).forEach((g) => {
        if (typeof g.lat !== "number" || typeof g.lon !== "number") return;
        const x = groups.find((y) => distM(y.lat, y.lon, g.lat, g.lon) < 300);
        if (x) x.items.push(g); else groups.push({ lat: g.lat, lon: g.lon, items: [g] });
      });
      groups.forEach((x, n) => {
        const names = [...new Set(x.items.map((g) => g.ad.replace(/\s+[AB]$/, "")))];
        out.push({
          id: `sgs:${o.id}:${n}`, type: "serbest", kind: "serbest", name: names.join(" / "), lat: x.lat, lon: x.lon,
          sub: ["Serbest geçiş", x.items[0].il].filter(Boolean).join(" · "), roads: [o.ad], roadIds: [o.id], sgs: x.items, n: 1,
          bolge: x.items[0].bolge || null, iller: x.items[0].il ? [x.items[0].il] : [],
        });
      });
    });
    return out;
  }

  // Aynı yerdeki (300 m) farklı tarifelerin gişeleri tek işarettir (ör. iki otoyolun kesiştiği gişe).
  function gates() {
    const groups = [];
    S.stations.forEach((s) => {
      if (typeof s.lat !== "number" || typeof s.lon !== "number") return;
      const g = groups.find((x) => distM(x.lat, x.lon, s.lat, s.lon) < 300);
      if (g) g.stations.push(s); else groups.push({ lat: s.lat, lon: s.lon, stations: [s] });
    });
    return groups.map((g) => {
      const first = g.stations[0];
      const names = [...new Set(g.stations.map((s) => s.ad.replace(/\s*\([^)]*yönü\)\s*$/i, "")))];
      const refs = [...new Set(g.stations.map((s) => s.road.yol).filter(Boolean))];
      const free = g.stations.every((s) => s.serbest);
      return {
        id: "gise:" + first.key, type: free ? "serbest" : "gise", kind: free ? "serbest" : "gise", name: names.join(" / "), lat: g.lat, lon: g.lon,
        sub: [refs.join(", ") || first.road.ad, first.il].filter(Boolean).join(" · "),
        bolge: first.bolge || null, iller: [...new Set(g.stations.map((s) => s.il).filter(Boolean))],
        stations: g.stations.map((s) => s.key), roads: [...new Set(g.stations.map((s) => s.road.ad))],
        roadIds: [...new Set(g.stations.map((s) => s.road.id))], n: 1,
      };
    });
  }

  // ------------------------------------------------------------ harita

  function readColors() {
    S.colors = {
      fill: cssVar("--mk-gate-fill") || "#fff", ring: cssVar("--mk-gate-ring") || "#14735f", faded: cssVar("--dash") || "#9fb3ab",
      route: cssVar("--route") || "#14735f", casing: cssVar("--route-casing") || "#fff", free: cssVar("--free") || "#7c3aed",
      alt: cssVar("--route-alt") || "#5f716b",
    };
  }
  function gateRadius() {
    const z = S.map ? S.map.getZoom() : 6;
    return z < 9 ? 4 : z < 11 ? 5 : z < 13 ? 6 : 7;
  }
  function onRoute(id) { return !!(S.route && S.route.gateIds && S.route.gateIds.has(id)); }
  function gateStyle(id) {
    const sel = id === S.selected;
    const faded = S.route && S.route.path && S.route.path.length && !onRoute(id) && !sel;
    return { radius: gateRadius() + (sel ? 2.5 : 0), color: faded ? S.colors.faded : S.colors.ring, weight: 3,
      fillColor: S.colors.fill, fillOpacity: 1, opacity: 1 };
  }
  function restyleGates() { S.markers.forEach((m, id) => { if (m.options.isGate) m.setStyle(gateStyle(id)); }); }

  function createMap() {
    const el = $("#map");
    if (!window.L) {
      el.innerHTML = `<p class="empty pad">Harita yüklenemedi; ücret hesabı çalışmaya devam eder.</p>`;
      return;
    }
    readColors();
    const map = L.map(el, {
      minZoom: narrow() ? 4 : 5, maxZoom: 17, zoomSnap: 0.25, zoomDelta: 0.5, zoomControl: false,
      // Sınır, panelin kapladığı alana rağmen Türkiye'nin görünür alana kaydırılabilmesi için geniş tutulur.
      maxBounds: L.latLngBounds([[8, 0], [56, 66]]), maxBoundsViscosity: 0.8, worldCopyJump: false,
    });
    S.map = map;
    map.attributionControl.setPrefix(false);
    map.createPane("route").style.zIndex = 390;
    map.createPane("stops").style.zIndex = 640;
    const labels = map.createPane("labels");
    labels.style.zIndex = 650;
    labels.style.pointerEvents = "none";
    map.createPane("altlbl").style.zIndex = 655;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> katkıcıları',
    }).addTo(map);
    S.gateRenderer = L.canvas({ padding: 0.5, tolerance: 8 });
    S.routeLayer = L.layerGroup().addTo(map);
    S.labelLayer = L.layerGroup().addTo(map);
    S.clusterLayer = L.layerGroup().addTo(map);
    S.gateClusterLayer = L.layerGroup().addTo(map);
    fitTurkey();

    S.points.forEach((p) => S.markers.set(p.id, createMarker(p)));
    syncMarkers();

    map.on("zoomend", () => { restyleGates(); syncMarkers(); });
    map.on("moveend", () => { clusterGates(); placeLabels(); });
    map.on("popupclose", () => select(null));
    el.addEventListener("click", (e) => {
      const a = e.target.closest("[data-show-crossing]");
      if (a) { e.preventDefault(); map.closePopup(); if (S.onShowCrossing) S.onShowCrossing(a.dataset.showCrossing); return; }
      const x = e.target.closest("[data-add-extra]");
      if (x) { e.preventDefault(); map.closePopup(); if (S.onAddExtra) S.onAddExtra(x.dataset.addExtra); return; }
      const t = e.target.closest("[data-trip-role]");
      if (t && S.onTrip) { e.preventDefault(); map.closePopup(); S.onTrip(t.dataset.tripRole, t.dataset.tripKey); }
    });
    const zin = $("#zoom-in"), zout = $("#zoom-out");
    if (zin) zin.addEventListener("click", () => map.zoomIn());
    if (zout) zout.addEventListener("click", () => map.zoomOut());
    try {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        readColors();
        restyleGates();
        if (S.route) showRoute(Object.assign({}, S.route, { fit: false }));
      });
    } catch (e) { /* eski tarayıcı */ }
    window.addEventListener("resize", () => map.invalidateSize());
  }

  // Görünür harita alanı: masaüstünde soldaki panel, telefonda alttaki sayfa ve üstteki araç çubuğu hariç.
  function viewPad(extra) {
    const e = extra || 0;
    if (narrow()) {
      const panel = $(".panel");
      const sheet = panel ? panel.getBoundingClientRect() : null;
      const mapRect = $("#map").getBoundingClientRect();
      const bottom = sheet ? Math.max(40, mapRect.bottom - sheet.top + 24) : 40;
      return { paddingTopLeft: [28 + e, 120 + e], paddingBottomRight: [28 + e, bottom + e] };
    }
    const panelW = $(".panel") ? $(".panel").offsetWidth + 32 : 0;
    return { paddingTopLeft: [panelW + 40 + e, 84 + e], paddingBottomRight: [56 + e, 56 + e] };
  }
  function fitTurkey() {
    const p = viewPad(0);
    S.map.fitBounds(TR_BOUNDS, { paddingTopLeft: [p.paddingTopLeft[0] - 24, p.paddingTopLeft[1] - 40], paddingBottomRight: [8, p.paddingBottomRight[1] - 24] });
  }

  function createMarker(p) {
    const esc = S.h.esc;
    let m;
    if (p.type === "gise") {
      m = L.circleMarker([p.lat, p.lon], Object.assign(gateStyle(p.id), { renderer: S.gateRenderer, isGate: true }));
    } else if (p.type === "serbest") {
      m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "mk", html: '<span class="mk-sgs"></span>', iconSize: [20, 20], iconAnchor: [10, 10] }),
        title: p.name, keyboard: true, riseOnHover: true, zIndexOffset: 500,
      });
    } else {
      m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "mk", html: `<span class="mk-bridge ${p.status ? "st-" + p.status : ""}">${ICONS[p.kind] || ICONS.kopru}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
        title: p.name, keyboard: true, riseOnHover: true, zIndexOffset: 1000,
      });
    }
    m.bindTooltip(() => `${esc(p.name)}${p.sub ? `<br><span>${esc(p.sub)}</span>` : ""}`,
      { direction: "top", offset: [0, p.type === "kopru" ? -14 : -7], className: "tip" });
    m.bindPopup(() => popupHtml(p), { maxWidth: 300, minWidth: 260, autoPanPaddingTopLeft: narrow() ? [16, 120] : [($(".panel") ? $(".panel").offsetWidth + 40 : 20), 80], autoPanPaddingBottomRight: [20, narrow() ? 80 : 20] });
    m.on("popupopen", () => select(p.id));
    return m;
  }

  // ------------------------------------------------------------ filtre

  // Filtreler: tür (katman), bölge, il, otoyol ve durum. "skip" verilen filtre sayım için yok sayılır.
  // Otoyol seçiliyse köprüler gizlenir; durum filtresi (zam / ücretsiz) yalnızca köprü ve tünellere uygulanır.
  function matches(p, skip) {
    const f = S.f;
    if (skip !== "types" && !f.types.has(p.type)) return false;
    if (skip !== "bolge" && f.bolge && p.bolge !== f.bolge) return false;
    if (skip !== "il" && f.il && !(p.iller || []).includes(f.il)) return false;
    if (skip !== "road" && f.road && (p.type === "kopru" || !p.roadIds.includes(f.road))) return false;
    if (skip !== "durum" && f.durum && !(p.type === "kopru" && p.status === f.durum)) return false;
    return true;
  }
  // Rota varken orta yakınlıkta yalnızca rotadaki otoyolların gişeleri (köprüler ve serbest geçişler hep görünür).
  function densityOk(p) {
    if (p.type !== "gise" || !S.map || !S.route || !S.route.roadIds || !S.route.roadIds.size) return true;
    const z = S.map.getZoom();
    if (z <= CLUSTER_ZOOM || z >= ROAD_ONLY_ZOOM) return true;
    return p.roadIds.some((r) => S.route.roadIds.has(r)) || p.id === S.selected;
  }
  const visible = (p) => matches(p) && densityOk(p);

  function syncMarkers() {
    if (!S.map) return;
    clusterGates();
    S.markers.forEach((m, id) => {
      const p = S.byId.get(id);
      if (p.type === "kopru") return;
      const on = S.map.hasLayer(m);
      const want = visible(p) && !S.gateClustered.has(id);
      if (want && !on) m.addTo(S.map);
      else if (!want && on) m.remove();
    });
    clusterMain();
    placeLabels();
  }

  function setFilter(f) {
    ["road", "bolge", "il", "durum"].forEach((k) => { if (f[k] !== undefined) S.f[k] = f[k] || ""; });
    if (f.types) S.f.types = new Set(f.types);
    syncMarkers();
    if (f.fit === false) return;
    const narrowed = f.road || f.bolge || f.il || f.durum;
    if (!narrowed && !f.reset) return;
    const pts = S.points.filter((p) => matches(p));
    const region = S.f.bolge && (S.data.bolgeler || []).find((r) => r.id === S.f.bolge);
    if (pts.length) S.map.flyToBounds(L.latLngBounds(pts.map((x) => [x.lat, x.lon])), Object.assign(viewPad(0), { maxZoom: 11, duration: 0.6 }));
    else if (region && region.sinir) S.map.flyToBounds(region.sinir, Object.assign(viewPad(0), { maxZoom: 9, duration: 0.6 }));
    else if (f.reset) fitTurkey();
  }

  function countsBy() {
    const c = { kopru: 0, gise: 0, serbest: 0 };
    S.points.forEach((p) => { if (matches(p, "types")) c[p.type]++; });
    return c;
  }

  // Filtre seçeneklerinin sayıları (her filtre kendi dışındakilere göre sayılır).
  function options() {
    const count = (skip, key) => {
      const m = new Map();
      S.points.forEach((p) => {
        if (!matches(p, skip)) return;
        [].concat(key(p) || []).forEach((v) => { if (v) m.set(v, (m.get(v) || 0) + 1); });
      });
      return m;
    };
    return {
      bolge: count("bolge", (p) => p.bolge),
      il: count("il", (p) => p.iller),
      road: count("road", (p) => p.roadIds),
      durum: count("durum", (p) => (p.type === "kopru" ? p.status : null)),
      regions: (S.data.bolgeler || []).map((r) => ({ id: r.id, ad: r.ad })),
    };
  }

  function search(q) {
    const t = fold(q).split(" ").filter(Boolean);
    if (!t.length) return [];
    const k = fold(q);
    return S.points.filter((p) => t.every((x) => p.q.includes(x)))
      .sort((a, b) => (fold(b.name).startsWith(k) - fold(a.name).startsWith(k)) || a.name.localeCompare(b.name, "tr"))
      .slice(0, 8).map((p) => ({ id: p.id, name: p.name, sub: p.sub, type: p.type, kind: p.kind }));
  }

  function focusPoint(id) {
    const p = S.byId.get(id);
    if (!p || !S.map) return;
    if (!matches(p)) { S.f = { types: new Set(["kopru", "gise", "serbest"]), road: "", bolge: "", il: "", durum: "" }; syncMarkers(); }
    const m = S.markers.get(p.id);
    select(p.id);
    S.map.once("moveend", () => { syncMarkers(); if (!S.map.hasLayer(m)) m.addTo(S.map); m.openPopup(); });
    S.map.flyTo([p.lat, p.lon], Math.max(S.map.getZoom(), 12), { duration: 0.6 });
  }

  // Uzaklaşınca üst üste binen köprü işaretleri (İstanbul'daki geçişler) tek işarette toplanır.
  function clusterMain() {
    if (!S.map) return;
    S.clusterLayer.clearLayers();
    S.clusters = [];
    S.clustered = new Set();
    const mains = S.points.filter((p) => p.type === "kopru" && visible(p)).map((p) => ({ p, pt: S.map.latLngToContainerPoint([p.lat, p.lon]) }));
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
      const name = `${pts.length} köprü ve tünel`;
      S.clusters.push({ id: "kume:" + pts.map((p) => p.id).join(","), lat, lon, name, type: "kume", n: 1000 });
      L.marker([lat, lon], {
        icon: L.divIcon({ className: "mk", html: `<span class="mk-bcl">${pts.length}${ICONS.kopru}</span>`, iconSize: [44, 28], iconAnchor: [22, 14] }),
        title: name, keyboard: true, zIndexOffset: 1100,
      })
        .bindTooltip(pts.map((p) => S.h.esc(p.name)).join("<br>"), { direction: "top", offset: [0, -14], className: "tip" })
        .on("click", () => S.map.flyToBounds(L.latLngBounds(pts.map((p) => [p.lat, p.lon])), { padding: [80, 80], maxZoom: 12, duration: 0.6 }))
        .addTo(S.clusterLayer);
    });
    S.markers.forEach((m, id) => {
      const p = S.byId.get(id);
      if (!p || p.type !== "kopru") return;
      const on = S.map.hasLayer(m);
      const want = visible(p) && !S.clustered.has(id);
      if (!want && on) m.remove();
      else if (want && !on) m.addTo(S.map);
    });
  }

  // Uzak yakınlıkta gişeler ızgara kümelerine toplanır; kümeye dokununca yakınlaşır. Rotadaki gişeler kümeye girmez.
  function clusterGates() {
    if (!S.map) return;
    S.gateClusterLayer.clearLayers();
    S.gateClustered = new Set();
    if (S.map.getZoom() > CLUSTER_ZOOM) return;
    const CELL = 46;
    const cells = new Map();
    S.points.forEach((p) => {
      if (p.type !== "gise" || !visible(p) || p.id === S.selected || onRoute(p.id)) return;
      const pt = S.map.latLngToContainerPoint([p.lat, p.lon]);
      const key = Math.floor(pt.x / CELL) + ":" + Math.floor(pt.y / CELL);
      if (!cells.has(key)) cells.set(key, []);
      cells.get(key).push(p);
    });
    cells.forEach((list) => {
      if (list.length < 3) return;
      list.forEach((p) => S.gateClustered.add(p.id));
      const lat = list.reduce((t, p) => t + p.lat, 0) / list.length;
      const lon = list.reduce((t, p) => t + p.lon, 0) / list.length;
      L.marker([lat, lon], {
        icon: L.divIcon({ className: "mk", html: `<span class="mk-gcl">${list.length}</span>`, iconSize: [36, 28], iconAnchor: [18, 14] }),
        title: `${list.length} gişe`, keyboard: true, zIndexOffset: 200,
      })
        .bindTooltip(`${list.length} gişe<br><span>Yakınlaşmak için dokun</span>`, { direction: "top", offset: [0, -14], className: "tip" })
        .on("click", () => S.map.flyToBounds(L.latLngBounds(list.map((p) => [p.lat, p.lon])), { padding: [60, 60], maxZoom: CLUSTER_ZOOM + 1.5, duration: 0.6 }))
        .addTo(S.gateClusterLayer);
    });
    S.markers.forEach((m, id) => {
      const p = S.byId.get(id);
      if (!p || p.type !== "gise") return;
      if (S.gateClustered.has(id) && S.map.hasLayer(m)) m.remove();
      else if (!S.gateClustered.has(id) && visible(p) && !S.map.hasLayer(m)) m.addTo(S.map);
    });
  }

  // ------------------------------------------------------------ etiketler (çakışmasız)

  function textWidth(text, font) {
    if (!S.measureCtx) S.measureCtx = document.createElement("canvas").getContext("2d");
    const key = font + "|" + text;
    if (!S.widths.has(key)) { S.measureCtx.font = font; S.widths.set(key, S.measureCtx.measureText(text).width); }
    return S.widths.get(key);
  }
  const overlaps = (a, boxes, owner) => boxes.some((b) => (owner === undefined || b[4] !== owner) &&
    !(a[2] <= b[0] || a[0] >= b[2] || a[3] <= b[1] || a[1] >= b[3]));

  function placeLabels() {
    if (!S.map) return;
    S.labelLayer.clearLayers();
    const z = S.map.getZoom();
    const size = S.map.getSize();
    const view = S.map.getBounds().pad(0.02);
    const routeStops = S.route ? [S.route.entry, S.route.exit].filter((s) => s && typeof s.lat === "number")
      .map((s, i) => ({ id: "rota:" + i, type: "rota", name: s.name, lat: s.lat, lon: s.lon })) : [];
    const items = routeStops.concat(S.points.filter((p) => visible(p) && !S.clustered.has(p.id) && !S.gateClustered.has(p.id)), S.clusters)
      .filter((p) => view.contains([p.lat, p.lon]));
    const boxes = [], dots = [], pos = new Map();
    // Panelin, alt sayfanın ve araç çubuğunun altına etiket konmaz.
    const mapRect = $("#map").getBoundingClientRect();
    [".panel", ".map-tools", ".map-corner"].forEach((sel) => {
      const el = $(sel);
      if (!el || el.offsetParent === null) return;
      const r = el.getBoundingClientRect();
      if (r.width && r.height) boxes.push([r.left - mapRect.left - 6, r.top - mapRect.top - 6, r.right - mapRect.left + 6, r.bottom - mapRect.top + 6, sel]);
    });
    items.forEach((p) => {
      const pt = S.map.latLngToContainerPoint([p.lat, p.lon]);
      pos.set(p.id, pt);
      const r = p.type === "gise" ? 7 : p.type === "rota" ? 16 : 14;
      (p.type === "gise" ? dots : boxes).push([pt.x - r, pt.y - r, pt.x + r, pt.y + r, p.id]);
    });
    const rank = (p) => (p.type === "rota" ? 0 : p.type === "kopru" || p.type === "kume" ? 1 : 2);
    const cands = items.filter((p) => rank(p) < 2 || p.id === S.selected || (z >= 9.5 && !(S.route && S.route.path && S.route.path.length && !onRoute(p.id) && z < ROAD_ONLY_ZOOM)));
    cands.sort((a, b) => rank(a) - rank(b) || (b.id === S.selected) - (a.id === S.selected) || a.name.localeCompare(b.name, "tr"));
    let placed = 0;
    for (const p of cands) {
      if (placed >= 140) break;
      const pt = pos.get(p.id);
      const kind = rank(p) === 0 ? "route" : rank(p) === 1 ? "main" : "gate";
      const w = textWidth(p.name, LABEL_FONTS[kind]) + (kind === "route" ? 18 : 6);
      const h = kind === "route" ? 26 : kind === "main" ? 20 : 16;
      const off = kind === "route" ? 21 : kind === "main" ? 19 : 12;
      const options = [
        ["right", pt.x + off, pt.y - h / 2, pt.x + off + w, pt.y + h / 2],
        ["left", pt.x - off - w, pt.y - h / 2, pt.x - off, pt.y + h / 2],
        ["above", pt.x - w / 2, pt.y - off - h, pt.x + w / 2, pt.y - off],
        ["below", pt.x - w / 2, pt.y + off, pt.x + w / 2, pt.y + off + h],
      ];
      for (const [where, x1, y1, x2, y2] of options) {
        if (x1 < 2 || y1 < 2 || x2 > size.x - 2 || y2 > size.y - 18) continue;
        const box = [x1 - 3, y1 - 1, x2 + 3, y2 + 1];
        if (overlaps(box, boxes, p.id) || (kind !== "route" && overlaps(box, dots, p.id))) continue;
        boxes.push(box);
        L.marker([p.lat, p.lon], {
          icon: L.divIcon({ className: `lbl-anchor pos-${where} is-${kind}`, iconSize: [0, 0], iconAnchor: [0, 0],
            html: `<span class="lbl${p.id === S.selected ? " is-selected" : ""}">${S.h.esc(p.name)}</span>` }),
          interactive: false, keyboard: false, pane: "labels",
        }).addTo(S.labelLayer);
        placed++;
        break;
      }
    }
  }

  // ------------------------------------------------------------ açılır pencere ve seçim

  function popupHtml(p) {
    const h = S.h, esc = h.esc;
    const cls = S.cls, clsName = h.className(cls);
    if (p.crossing) {
      const c = p.crossing;
      const cur = c.current && c.current.classes[cls];
      const night = c.current && c.current.gece && c.current.gece.classes ? c.current.gece : null;
      const rows = [`<div class="pp-row"><span>${esc(clsName)}${night ? " · gündüz" : ""}</span>${cur != null ? `<b class="big">${esc(h.money(cur))}</b>` : c.current ? `<b class="no">Bu sınıf geçemez</b>` : "<b>—</b>"}</div>`];
      if (night && night.classes[cls] != null) rows.push(`<div class="pp-row"><span>Gece ${esc(night.saat || "")}</span><b>${esc(h.money(night.classes[cls]))}</b></div>`);
      const st = [];
      if (c.free_now) st.push(`<div class="pp-st free">Ücretsiz geçiş sürüyor · bitiş ${esc(h.dateTime(c.free_now.valid_to))}</div>`);
      if (c.upcoming) st.push(`<div class="pp-st change">${esc(h.date(c.upcoming.valid_from))} itibarıyla ${esc(h.money(c.upcoming.classes[cls]))}</div>`);
      const canAdd = S.canAddExtra && S.canAddExtra(c.id);
      return `<div class="pp">
        <div class="pp-h"><span class="ic mk-bridge">${ICONS[p.kind] || ICONS.kopru}</span><span class="t"><b>${esc(p.name)}</b><span>${esc(p.sub || "")}</span></span></div>
        <div class="pp-rows">${rows.join("")}</div>${st.join("")}
        <div class="pp-acts">
          ${canAdd ? `<button type="button" class="btn primary" data-add-extra="${esc(c.id)}">Rotaya ekle</button>` : ""}
          <button type="button" class="btn${canAdd ? "" : " wide"}" data-show-crossing="${esc(c.id)}">Tüm sınıflar</button>
        </div></div>`;
    }
    if (p.sgs) {
      const rows = p.sgs.map((g) => {
        const v = Array.isArray(g.ucret) ? g.ucret[Number(cls) - 1] : null;
        const label = p.sgs.length > 1 ? [g.ad, g.yon].filter(Boolean).join(" · ") : (g.yon ? g.yon + " · " : "") + clsName;
        return `<div class="pp-row"><span>${esc(label)}</span><b${p.sgs.length === 1 ? ' class="big"' : ""}>${typeof v === "number" ? esc(h.money(v)) : "—"}</b></div>`;
      }).join("");
      return `<div class="pp">
        <div class="pp-h"><span class="ic pp-dia"></span><span class="t"><b>${esc(p.name)}</b><span>${esc(p.sub || "")}</span></span></div>
        <div class="pp-info">${GANTRY}<span>Gişe yok. Altından geçerken <b>HGS'den otomatik</b> kesilir.</span></div>
        <div class="pp-rows">${rows}</div>
        ${p.sgs.length > 1 ? `<div class="pp-link muted">${esc(clsName)} · ${esc(p.roads.join(", "))}</div>` : `<div class="pp-link muted">${esc(p.roads.join(", "))}</div>`}
      </div>`;
    }
    const extra = S.popupExtra ? S.popupExtra(p) : "";
    return `<div class="pp">
      <div class="pp-h"><span class="ic pp-gate"></span><span class="t"><b>${esc(p.name)}</b><span>${esc(p.sub || "")}</span></span></div>
      ${extra ? `<div class="pp-acts">${extra}</div>` : ""}</div>`;
  }

  function select(id) {
    if (S.selected === id) return;
    const prevId = S.selected;
    const prev = prevId && S.markers.get(prevId);
    S.selected = id;
    if (prev && prev.options.isGate) prev.setStyle(gateStyle(prevId));
    else if (prev && prev.getElement && prev.getElement()) prev.getElement().classList.remove("is-selected");
    const m = id && S.markers.get(id);
    if (m && m.options.isGate) { m.setStyle(gateStyle(id)); m.bringToFront(); }
    else if (m && m.getElement && m.getElement()) m.getElement().classList.add("is-selected");
    clusterMain();
    placeLabels();
  }

  // ------------------------------------------------------------ güzergâh

  // r: { segments:[{path, kind:"trip"|"sgs"}], alt:{path, label, onClick}, entry, exit, transfers:[{lat,lon}], stationKeys:[], roadIds:[] }
  function showRoute(r) {
    S.route = Object.assign({}, r);
    const keys = new Set(r.stationKeys || []);
    S.route.gateIds = new Set(S.points.filter((p) => p.type === "gise" && (p.stations || []).some((k) => keys.has(k))).map((p) => p.id));
    S.route.roadIds = new Set(r.roadIds || []);
    const segs = (r.segments || []).filter((s) => Array.isArray(s.path) && s.path.length >= 2);
    S.route.path = segs.reduce((t, s) => t.concat(s.path), []);
    if (!S.map) return;
    readColors();
    S.routeLayer.clearLayers();
    const o = { pane: "route", interactive: false, lineCap: "round", lineJoin: "round" };
    // Alternatif rota: soluk noktalı çizgi + tıklanabilir etiket
    if (r.alt && Array.isArray(r.alt.path) && r.alt.path.length >= 2) {
      L.polyline(r.alt.path, Object.assign({ color: S.colors.alt, weight: 3, opacity: 0.8, dashArray: "2 7" }, o)).addTo(S.routeLayer);
      const mid = r.alt.path[Math.floor(r.alt.path.length / 2)];
      if (r.alt.label) {
        const lbl = L.marker(mid, {
          icon: L.divIcon({ className: "lbl-anchor", iconSize: [0, 0], iconAnchor: [0, 0], html: `<span class="alt-lbl">${S.h.esc(r.alt.label)}</span>` }),
          pane: "altlbl", keyboard: false, interactive: true, title: "Bu rotayı seç",
        }).addTo(S.routeLayer);
        if (r.alt.onClick) lbl.on("click", r.alt.onClick);
      }
    }
    if (segs.length) {
      const all = segs.reduce((t, s) => t.concat([s.path]), []);
      L.polyline(all, Object.assign({ color: S.colors.casing, weight: 11, opacity: 1 }, o)).addTo(S.routeLayer);
      segs.forEach((s) => {
        if (s.kind === "sgs") L.polyline(s.path, Object.assign({ color: S.colors.free, weight: 6, opacity: 1, dashArray: "8 5", lineCap: "butt" }, o)).addTo(S.routeLayer);
        else L.polyline(s.path, Object.assign({ color: S.colors.route, weight: 6, opacity: 1 }, o)).addTo(S.routeLayer);
      });
    }
    (r.transfers || []).forEach((t) => L.marker([t.lat, t.lon], {
      icon: L.divIcon({ className: "mk", html: '<span class="mk-xfer"></span>', iconSize: [14, 14], iconAnchor: [7, 7] }),
      pane: "stops", keyboard: false, interactive: false,
    }).addTo(S.routeLayer));
    const stops = [r.entry, r.exit].filter((s) => s && typeof s.lat === "number");
    stops.forEach((s) => L.marker([s.lat, s.lon], {
      icon: L.divIcon({ className: "mk", html: `<span class="mk-stop ${s.role === "in" ? "a" : "b"}">${s.role === "in" ? "A" : "B"}</span>`, iconSize: [30, 30], iconAnchor: [15, 15] }),
      pane: "stops", keyboard: false, interactive: false,
    }).addTo(S.routeLayer));
    restyleGates();
    syncMarkers();
    if (r.fit === false) return;
    const pts = S.route.path.concat(stops.map((s) => [s.lat, s.lon]), r.alt && r.alt.path ? r.alt.path : []);
    if (pts.length >= 2) S.map.flyToBounds(L.latLngBounds(pts), Object.assign(viewPad(0), { maxZoom: 12, duration: 0.6 }));
    else if (pts.length === 1) S.map.flyTo(pts[0], Math.max(S.map.getZoom(), 10), { duration: 0.5 });
  }

  function clearRoute() {
    S.route = null;
    if (S.routeLayer) S.routeLayer.clearLayers();
    restyleGates();
    syncMarkers();
  }

  // ------------------------------------------------------------ dışa açık

  function init(opts) {
    S.h = opts.helpers;
    S.data = opts.data;
    S.stations = opts.stations || [];
    S.cls = opts.cls || "1";
    S.onShowCrossing = opts.onShowCrossing || null;
    S.onTrip = opts.onTrip || null;
    S.onAddExtra = opts.onAddExtra || null;
    S.canAddExtra = opts.canAddExtra || null;
    S.popupExtra = opts.popupExtra || null;
    S.roads = opts.roads || [];
    S.points = buildPoints();
    createMap();
    if (S.map) placeLabels();
  }

  function setClass(cls) { S.cls = cls; }

  function focusCrossing(id) { focusPoint("gecis:" + id); }

  function counts() {
    return { gates: S.points.filter((p) => p.type === "gise").length, crossings: S.points.filter((p) => p.type === "kopru").length,
      free: S.points.filter((p) => p.type === "serbest").length };
  }

  return {
    init, setClass, focusCrossing, focusPoint, showRoute, clearRoute, counts, search, setFilter, countsBy,
    types: () => TYPES, icons: ICONS, options, filter: () => ({ types: [...S.f.types], road: S.f.road, bolge: S.f.bolge, il: S.f.il, durum: S.f.durum }),
    invalidate: () => { if (S.map) { S.map.invalidateSize(); placeLabels(); } },
    refit: () => { if (S.map && S.route && S.route.path && S.route.path.length) showRoute(Object.assign({}, S.route, { fit: true })); },
    closePopup: () => { if (S.map) S.map.closePopup(); },
    view: () => (S.map ? { c: S.map.getCenter(), z: S.map.getZoom(), b: S.map.getBounds().toBBoxString() } : null),
  };
})();
