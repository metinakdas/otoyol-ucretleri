"use strict";

/*
 * Harita: köprü/tüneller (config/crossings.yaml) ve otoyol gişeleri (config/giseler.yaml → ucret-tablosu.json).
 * Haritadan veri alınmaz; OpenStreetMap yalnızca altlık karolarıdır. Kütüphane: Leaflet (vendor/leaflet).
 */
window.RadarMap = (function () {
  const TR_BOUNDS = [[35.8, 25.9], [42.2, 44.8]];
  const FONT = '"Inter", system-ui, sans-serif';
  const LABEL_FONTS = { main: "650 12.5px " + FONT, gate: "550 11.5px " + FONT, route: "650 12px " + FONT };
  const KIND_NAMES = { kopru: "Köprü", tunel: "Tünel", gise: "Otoyol gişesi" };
  const ICONS = {
    kopru: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.8 11.6h12.4M3.2 11.6c1.3-4.2 8.3-4.2 9.6 0M5.6 8.3v3.3M10.4 8.3v3.3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    tunel: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.2 12.4V9a4.8 4.8 0 0 1 9.6 0v3.4M1.8 12.4h12.4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  };

  const S = {
    h: null, data: null, stations: [], cls: "1",
    onShowCrossing: null, onTrip: null, popupExtra: null,
    map: null, gateRenderer: null, markers: new Map(), labelLayer: null, clusterLayer: null, routeLayer: null,
    points: [], byId: new Map(), clusters: [], clustered: new Set(), selected: null, route: null,
    widths: new Map(), measureCtx: null, colors: {},
  };
  const $ = (sel) => document.querySelector(sel);
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

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
        sub: [(c.iller || []).join(" / "), c.operator].filter(Boolean).join(" · "), crossing: c, status, n: 99 });
    });
    gates().forEach((g) => pts.push(g));
    pts.forEach((p) => S.byId.set(p.id, p));
    return pts;
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
      // "X (İzmir Yönü)" ve "X (İstanbul Yönü)" aynı yerdedir: haritada tek ad.
      const names = [...new Set(g.stations.map((s) => s.ad.replace(/\s*\([^)]*yönü\)\s*$/i, "")))];
      const refs = [...new Set(g.stations.map((s) => s.road.yol).filter(Boolean))];
      return {
        id: "gise:" + first.key, type: "gise", kind: "gise", name: names.join(" / "), lat: g.lat, lon: g.lon,
        sub: [first.il, refs.join(", ") || first.road.ad].filter(Boolean).join(" · "),
        stations: g.stations.map((s) => s.key), roads: [...new Set(g.stations.map((s) => s.road.ad))], n: 1,
      };
    });
  }

  // ------------------------------------------------------------ harita

  function readColors() {
    S.colors = {
      gate: cssVar("--m-gate") || "#fff", ring: cssVar("--m-gate-ring") || "#334155",
      route: cssVar("--route") || "#2563eb", casing: cssVar("--route-casing") || "#fff",
    };
  }
  function gateRadius() {
    const z = S.map ? S.map.getZoom() : 6;
    return z < 7 ? 3.5 : z < 9 ? 4.5 : z < 11 ? 5.5 : 6.5;
  }
  function gateStyle(on) {
    return { radius: gateRadius() + (on ? 2.5 : 0), color: on ? S.colors.route : S.colors.ring, weight: on ? 3 : 1.8,
      fillColor: S.colors.gate, fillOpacity: 1, opacity: 1 };
  }

  function createMap() {
    const el = $("#map");
    if (!window.L) {
      el.innerHTML = `<p class="empty" style="padding:24px">Harita yüklenemedi; ücret hesabı çalışmaya devam eder.</p>`;
      return;
    }
    readColors();
    const map = L.map(el, {
      minZoom: 5, maxZoom: 17, zoomSnap: 0.25, zoomDelta: 0.5, zoomControl: false,
      // Sınır, panelin kapladığı alana rağmen Türkiye'nin görünür alana kaydırılabilmesi için geniş tutulur.
      maxBounds: L.latLngBounds([[28, 8], [48, 58]]), maxBoundsViscosity: 0.8, worldCopyJump: false,
    });
    S.map = map;
    L.control.zoom({ position: "bottomright", zoomInTitle: "Yakınlaştır", zoomOutTitle: "Uzaklaştır" }).addTo(map);
    map.attributionControl.setPrefix(false);
    map.createPane("route").style.zIndex = 390;
    map.createPane("stops").style.zIndex = 640;
    const labels = map.createPane("labels");
    labels.style.zIndex = 650;
    labels.style.pointerEvents = "none";
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> katkıcıları',
    }).addTo(map);
    S.gateRenderer = L.canvas({ padding: 0.5, tolerance: 8 });
    S.routeLayer = L.layerGroup().addTo(map);
    S.labelLayer = L.layerGroup().addTo(map);
    S.clusterLayer = L.layerGroup().addTo(map);
    fitTurkey();

    S.points.forEach((p) => {
      const m = createMarker(p);
      S.markers.set(p.id, m);
      m.addTo(map);
    });
    clusterMain();

    map.on("zoomend", () => {
      S.markers.forEach((m, id) => { if (m.options.isGate) m.setStyle(gateStyle(id === S.selected)); });
      clusterMain();
    });
    map.on("zoomend moveend", placeLabels);
    map.on("popupclose", () => select(null));
    el.addEventListener("click", (e) => {
      const a = e.target.closest("[data-show-crossing]");
      if (a) { e.preventDefault(); if (S.onShowCrossing) S.onShowCrossing(a.dataset.showCrossing); return; }
      const t = e.target.closest("[data-trip-role]");
      if (t && S.onTrip) { e.preventDefault(); map.closePopup(); S.onTrip(t.dataset.tripRole, t.dataset.tripKey); }
    });
    try {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        readColors();
        S.markers.forEach((m, id) => { if (m.options.isGate) m.setStyle(gateStyle(id === S.selected)); });
        if (S.route) showRoute(Object.assign({}, S.route, { fit: false }));
      });
    } catch (e) { /* eski tarayıcı */ }
    window.addEventListener("resize", () => map.invalidateSize());
  }

  function fitTurkey() {
    const narrow = window.matchMedia("(max-width: 900px)").matches;
    const panelW = narrow ? 0 : ($(".panel") ? $(".panel").offsetWidth + 24 : 0);
    S.map.fitBounds(TR_BOUNDS, { paddingTopLeft: [panelW + 8, 8], paddingBottomRight: [8, 8] });
  }

  function createMarker(p) {
    const esc = S.h.esc;
    let m;
    if (p.type === "gise") {
      m = L.circleMarker([p.lat, p.lon], Object.assign(gateStyle(false), { renderer: S.gateRenderer, isGate: true }));
    } else {
      m = L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "pin-wrap", html: `<span class="pin ${p.status}">${ICONS[p.kind] || ICONS.kopru}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
        title: p.name, keyboard: true, riseOnHover: true, zIndexOffset: 1000,
      });
    }
    m.bindTooltip(() => `${esc(p.name)}${p.sub ? `<br><span>${esc(p.sub)}</span>` : ""}`,
      { direction: "top", offset: [0, p.type === "kopru" ? -14 : -6], className: "tip" });
    m.bindPopup(() => popupHtml(p), { maxWidth: 300, minWidth: 230, autoPanPaddingTopLeft: [S.map && !window.matchMedia("(max-width: 900px)").matches ? 440 : 20, 20] });
    m.on("popupopen", () => select(p.id));
    return m;
  }

  // Uzaklaşınca üst üste binen köprü işaretleri (İstanbul'daki dört geçiş) tek işarette toplanır.
  function clusterMain() {
    if (!S.map) return;
    S.clusterLayer.clearLayers();
    S.clusters = [];
    S.clustered = new Set();
    const mains = S.points.filter((p) => p.type === "kopru").map((p) => ({ p, pt: S.map.latLngToContainerPoint([p.lat, p.lon]) }));
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
        icon: L.divIcon({ className: "pin-wrap", html: `<span class="pin pin-cluster">${pts.length}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] }),
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
      if (S.clustered.has(id) && on) m.remove();
      else if (!S.clustered.has(id) && !on) m.addTo(S.map);
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
    const items = routeStops.concat(S.points.filter((p) => !S.clustered.has(p.id)), S.clusters)
      .filter((p) => view.contains([p.lat, p.lon]));
    const boxes = [], dots = [], pos = new Map();
    // Yüzen panelin altına etiket konmaz.
    const panel = $(".panel");
    if (panel && !window.matchMedia("(max-width: 900px)").matches) boxes.push([0, 0, panel.offsetLeft + panel.offsetWidth + 8, size.y, "panel"]);
    items.forEach((p) => {
      const pt = S.map.latLngToContainerPoint([p.lat, p.lon]);
      pos.set(p.id, pt);
      const r = p.type === "gise" ? 6 : p.type === "rota" ? 11 : 14;
      (p.type === "gise" ? dots : boxes).push([pt.x - r, pt.y - r, pt.x + r, pt.y + r, p.id]);
    });
    const rank = (p) => (p.type === "rota" ? 0 : p.type === "kopru" || p.type === "kume" ? 1 : 2);
    const cands = items.filter((p) => rank(p) < 2 || p.id === S.selected || z >= 8.5);
    cands.sort((a, b) => rank(a) - rank(b) || (b.id === S.selected) - (a.id === S.selected) || a.name.localeCompare(b.name, "tr"));
    let placed = 0;
    for (const p of cands) {
      if (placed >= 160) break;
      const pt = pos.get(p.id);
      const kind = rank(p) === 0 ? "route" : rank(p) === 1 ? "main" : "gate";
      const w = textWidth(p.name, LABEL_FONTS[kind]) + (kind === "route" ? 18 : 6);
      const h = kind === "route" ? 22 : kind === "main" ? 20 : 16;
      const off = kind === "route" ? 16 : kind === "main" ? 19 : 12;
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
    const head = `<div class="pop-k">${esc(KIND_NAMES[p.kind] || "")}</div><div class="pop-t">${esc(p.name)}</div>
      ${p.sub ? `<div class="pop-s">${esc(p.sub)}</div>` : ""}`;
    if (p.crossing) {
      const c = p.crossing;
      const cur = c.current && c.current.classes[S.cls];
      const rows = [`<div class="pop-row"><span>${esc(h.className(S.cls))}</span><b>${cur != null ? esc(h.money(cur)) : "—"}</b></div>`];
      if (c.free_now) rows.push(`<div class="pop-st free">Ücretsiz geçiş sürüyor · bitiş ${esc(h.dateTime(c.free_now.valid_to))}</div>`);
      if (c.upcoming) rows.push(`<div class="pop-st change">${esc(h.date(c.upcoming.valid_from))} itibarıyla ${esc(h.money(c.upcoming.classes[S.cls]))}</div>`);
      return `${head}${rows.join("")}<div class="pop-a"><a href="#" data-show-crossing="${esc(c.id)}">Tüm sınıflar ve geçmiş</a></div>`;
    }
    const extra = S.popupExtra ? S.popupExtra(p) : "";
    return `${head}${p.roads && p.roads.length ? `<div class="pop-row"><span>Otoyol</span><b>${esc(p.roads.join(", "))}</b></div>` : ""}${extra}`;
  }

  function select(id) {
    if (S.selected === id) return;
    const prev = S.selected && S.markers.get(S.selected);
    if (prev && prev.options.isGate) prev.setStyle(gateStyle(false));
    else if (prev && prev.getElement && prev.getElement()) prev.getElement().classList.remove("is-selected");
    S.selected = id;
    const m = id && S.markers.get(id);
    if (m && m.options.isGate) { m.setStyle(gateStyle(true)); m.bringToFront(); }
    else if (m && m.getElement && m.getElement()) m.getElement().classList.add("is-selected");
    clusterMain();
    placeLabels();
  }

  // ------------------------------------------------------------ güzergâh

  function showRoute(r) {
    S.route = r;
    if (!S.map) return;
    readColors();
    S.routeLayer.clearLayers();
    const path = (r.path || []).filter((p) => Array.isArray(p) && p.length === 2);
    if (path.length >= 2) {
      const o = { pane: "route", interactive: false, lineCap: "round", lineJoin: "round" };
      L.polyline(path, Object.assign({ color: S.colors.casing, weight: 10, opacity: 1 }, o)).addTo(S.routeLayer);
      L.polyline(path, Object.assign({ color: S.colors.route, weight: 5, opacity: 1 }, o)).addTo(S.routeLayer);
    }
    const stops = [r.entry, r.exit].filter((s) => s && typeof s.lat === "number");
    stops.forEach((s) => L.marker([s.lat, s.lon], {
      icon: L.divIcon({ className: "stop-wrap", html: `<span class="stop ${s.role}"></span>`, iconSize: [18, 18], iconAnchor: [9, 9] }),
      pane: "stops", keyboard: false, interactive: false,
    }).addTo(S.routeLayer));
    placeLabels();
    if (r.fit === false) return;
    const pts = path.concat(stops.map((s) => [s.lat, s.lon]));
    const narrow = window.matchMedia("(max-width: 900px)").matches;
    const pad = { paddingTopLeft: [narrow ? 40 : ($(".panel").offsetWidth + 72), 70], paddingBottomRight: [60, 60], maxZoom: 12, duration: 0.6 };
    if (pts.length >= 2) S.map.flyToBounds(L.latLngBounds(pts), pad);
    else if (pts.length === 1) S.map.flyTo(pts[0], Math.max(S.map.getZoom(), 10), { duration: 0.5 });
  }

  function clearRoute() {
    S.route = null;
    if (S.routeLayer) S.routeLayer.clearLayers();
    placeLabels();
  }

  // ------------------------------------------------------------ dışa açık

  function init(opts) {
    S.h = opts.helpers;
    S.data = opts.data;
    S.stations = opts.stations || [];
    S.cls = opts.cls || "1";
    S.onShowCrossing = opts.onShowCrossing || null;
    S.onTrip = opts.onTrip || null;
    S.popupExtra = opts.popupExtra || null;
    S.points = buildPoints();
    createMap();
    if (S.map) placeLabels();
  }

  function setClass(cls) { S.cls = cls; }

  function focusCrossing(id) {
    const p = S.byId.get("gecis:" + id);
    if (!p || !S.map) return;
    const m = S.markers.get(p.id);
    select(p.id);
    S.map.once("moveend", () => { if (!S.map.hasLayer(m)) m.addTo(S.map); m.openPopup(); });
    S.map.flyTo([p.lat, p.lon], Math.max(S.map.getZoom(), 12), { duration: 0.6 });
  }

  function counts() {
    return { gates: S.points.filter((p) => p.type === "gise").length, crossings: S.points.filter((p) => p.type === "kopru").length };
  }

  return { init, setClass, focusCrossing, showRoute, clearRoute, counts, invalidate: () => S.map && S.map.invalidateSize() };
})();
