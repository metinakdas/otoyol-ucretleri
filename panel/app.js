"use strict";

(function () {
  const TZ = "Europe/Istanbul";
  const fmtMoney = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDate = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", year: "numeric", timeZone: TZ });
  const fmtShort = new Intl.DateTimeFormat("tr-TR", { day: "numeric", month: "long", timeZone: TZ });
  const fmtDateTime = new Intl.DateTimeFormat("tr-TR", {
    day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: TZ,
  });
  const fmtYmd = new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: TZ });
  const CLASSES = ["1", "2", "3", "4", "5", "6"];
  const CLASS_NAMES = {
    "1": "1. sınıf (otomobil)", "2": "2. sınıf", "3": "3. sınıf", "4": "4. sınıf", "5": "5. sınıf", "6": "6. sınıf (motosiklet)",
  };

  const $ = (sel) => document.querySelector(sel);
  let data_ = null;
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (v) => (v == null ? "—" : fmtMoney.format(Number(v)) + " TL");
  const date = (iso) => (iso ? fmtDate.format(new Date(iso)) : "belirsiz");
  const dateTime = (iso) => (iso ? fmtDateTime.format(new Date(iso)) : "belirsiz");
  // Yalnızca http(s) bağlantıları tıklanabilir; "javascript:" gibi adresler düz yazı olarak gösterilir.
  const safeUrl = (url) => (typeof url === "string" && /^https?:\/\/[^\s]+$/i.test(url.trim()) ? url.trim() : null);
  const link = (url, label) => (safeUrl(url) ? `<a href="${esc(safeUrl(url))}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>` : esc(label));

  function store(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, value);
    } catch (e) { /* tarayıcı depolaması kapalı olabilir */ }
    return null;
  }

  function dayDiff(iso, now) {
    const a = Date.parse(fmtYmd.format(new Date(iso)));
    const b = Date.parse(fmtYmd.format(now));
    return Math.round((a - b) / 86400000);
  }

  function ago(iso, now) {
    if (!iso) return "—";
    const minutes = (now - new Date(iso)) / 60000;
    if (minutes < 1) return "az önce";
    if (minutes < 60) return Math.round(minutes) + " dk önce";
    if (minutes < 60 * 24) return Math.round(minutes / 60) + " saat önce";
    return Math.round(minutes / 1440) + " gün önce";
  }

  function countdown(iso, now) {
    const n = dayDiff(iso, now);
    if (n > 1) return { big: n + " gün", small: "kaldı" };
    if (n === 1) return { big: "Yarın", small: dateTime(iso) };
    if (n === 0) return { big: "Bugün", small: dateTime(iso) };
    return { big: -n + " gün", small: "önce başladı" };
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

  async function load() {
    const sample = new URLSearchParams(location.search).has("ornek");
    const data = await fetchFirst(sample ? ["ornek-panel.json"] : ["data/panel.json", "../data/panel.json"]);
    if (!data) throw new Error("panel verisi bulunamadı");
    return data;
  }

  function loadMap() {
    const sample = new URLSearchParams(location.search).has("ornek");
    return fetchFirst(sample ? ["ornek-harita.json"] : ["data/harita.json", "../data/harita.json"]);
  }

  // ---------------------------------------------------------------- bölümler

  function renderStatus(data, now) {
    const enabled = data.sources.filter((s) => s.enabled);
    const failing = enabled.filter((s) => s.ok === false);
    const stale = data.last_run && now - new Date(data.last_run) > 6 * 3600 * 1000;
    const cls = failing.length ? "bad" : stale ? "warn" : "good";
    const tail = failing.length ? `${failing.length} kaynak okunamıyor` : "tüm kaynaklar çalışıyor";
    $("#status").innerHTML = `<span class="dot ${cls}" aria-hidden="true"></span>Son kontrol ${esc(ago(data.last_run, now))} · ${tail}`;
  }

  function renderHighlight(data, now) {
    const el = $("#highlight");
    const active = data.active_rules && data.active_rules[0];
    const next = data.upcoming && data.upcoming[0];
    if (active) {
      const c = countdown(active.valid_to, now);
      el.className = "highlight free";
      el.innerHTML = `
        <div>
          <div class="eyebrow">Ücretsiz geçiş sürüyor</div>
          <div class="title">${esc(active.title)}</div>
          <div class="meta">Kapsam: ${esc(names(data, active.crossings))} · Bitiş: ${esc(dateTime(active.valid_to))}</div>
        </div>
        <div class="count"><strong>${esc(dayDiff(active.valid_to, now) <= 0 ? "Bugün" : c.big)}</strong><span>bitiyor</span></div>`;
      return;
    }
    if (next) {
      const c = countdown(next.effective_from, now);
      const src = next.sources && next.sources[next.sources.length - 1];
      el.className = "highlight accent";
      el.innerHTML = `
        <div>
          <div class="eyebrow">Yaklaşan değişiklik</div>
          <div class="title">${esc(next.title)}</div>
          <div class="meta">Yürürlük: <strong>${esc(dateTime(next.effective_from))}</strong>
            ${next.crossings.length ? " · " + esc(names(data, next.crossings)) : ""}
            ${src ? " · Kaynak: " + link(src.url, src.publisher || "kaynak") : ""}</div>
        </div>
        <div class="count"><strong>${esc(c.big)}</strong><span>${esc(c.small)}</span></div>`;
      return;
    }
    const period = (data.calendar || [])[0];
    el.className = "highlight";
    el.innerHTML = `
      <div>
        <div class="eyebrow">Durum</div>
        <div class="title">Yaklaşan değişiklik yok</div>
        <div class="meta">${period ? `Sıradaki dönem: ${esc(period.name)} (${esc(date(period.start))}). İzleme ${esc(date(period.watch_start))} tarihinde başlar.` : "Radar resmi kaynakları izlemeye devam ediyor."}</div>
      </div>`;
  }

  function priceState(c, cls, now) {
    if (c.free_now) {
      return `<span class="state free">ücretsiz (bayram)<span class="next">bitiş ${esc(fmtShort.format(new Date(c.free_now.valid_to)))}</span></span>`;
    }
    if (c.upcoming) {
      return `<span class="state change">değişecek · ${esc(fmtShort.format(new Date(c.upcoming.valid_from)))}<span class="next">→ ${esc(money(c.upcoming.classes[cls]))}</span></span>`;
    }
    if (c.current) return `<span class="state">sabit</span>`;
    return `<span class="state">${c.operator === "YİD" && c.id === "avrasya-tuneli" ? "duyurular izleniyor" : "veri yok"}</span>`;
  }

  function historyChart(history, now) {
    const pts = (history || []).filter((h) => h.class1 != null).map((h) => ({ t: new Date(h.valid_from).getTime(), v: Number(h.class1) }));
    if (pts.length < 2) return `<p class="empty">Geçmiş grafiği için en az iki ücret kaydı gerekir.</p>`;
    const W = 360, H = 140, L = 12, R = 52, T = 18, B = 22;
    const tMin = pts[0].t, tMax = Math.max(pts[pts.length - 1].t, now.getTime()) + 30 * 86400000;
    const vMax = Math.max(...pts.map((p) => p.v)) * 1.15, vMin = 0;
    const x = (t) => L + ((t - tMin) / (tMax - tMin)) * (W - L - R);
    const y = (v) => T + (1 - (v - vMin) / (vMax - vMin)) * (H - T - B);
    let past = "", future = "";
    pts.forEach((p, i) => {
      const nextT = i + 1 < pts.length ? pts[i + 1].t : tMax;
      const seg = `M${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}H${x(nextT).toFixed(1)}` +
        (i + 1 < pts.length ? `V${y(pts[i + 1].v).toFixed(1)}` : "");
      if (p.t > now.getTime()) future += seg; else past += seg;
    });
    const years = [];
    for (let yr = new Date(tMin).getFullYear(); yr <= new Date(tMax).getFullYear(); yr++) {
      const t = Date.UTC(yr, 0, 1);
      if (t >= tMin && t <= tMax) years.push(`<text x="${x(t).toFixed(1)}" y="${H - 6}" text-anchor="middle">${yr}</text>`);
    }
    const labels = pts.map((p) => `<circle cx="${x(p.t).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="3"/>
      <text x="${(x(p.t) + 4).toFixed(1)}" y="${(y(p.v) - 6).toFixed(1)}">${esc(fmtMoney.format(p.v))}</text>`).join("");
    return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="1. sınıf ücret geçmişi">
      <line class="axis" x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}"/>
      <path class="line" d="${past}"/><path class="line future" d="${future}"/>${labels}${years.join("")}</svg>`;
  }

  function detailRow(c, now) {
    const rows = CLASSES.map((k) => `<tr><td>${esc(CLASS_NAMES[k])}</td>
      <td>${esc(money(c.current && c.current.classes[k]))}</td>
      <td>${c.upcoming ? esc(money(c.upcoming.classes[k])) : "—"}</td></tr>`).join("");
    const since = c.current ? `Geçerlilik: ${esc(date(c.current.valid_from))}` : "Kayıtlı ücret yok";
    const src = (c.current && c.current.source_url ? " · " + link(c.current.source_url, "tarife belgesi") : "") +
      (c.konum && window.RadarMap ? ` · <a href="#map-title" data-map-focus="${esc(c.id)}">Haritada göster</a>` : "");
    return `<tr class="detail"><td colspan="3"><div class="detail-grid">
      <div><table class="mini"><thead><tr><th>Sınıf</th><th>Şimdi</th><th>${c.upcoming ? esc(fmtShort.format(new Date(c.upcoming.valid_from))) + "’den" : "Yeni"}</th></tr></thead>
      <tbody>${rows}</tbody></table><p class="hint">${since}${src}</p></div>
      <div><div class="muted chart-title">1. sınıf ücret geçmişi</div>${historyChart(c.history, now)}</div>
    </div></td></tr>`;
  }

  function renderPrices(data, now, cls) {
    const picker = $("#class-picker");
    picker.innerHTML = CLASSES.map((k) => `<button type="button" data-class="${k}" aria-pressed="${k === cls}" title="${esc(CLASS_NAMES[k])}">${k}<span class="long">. sınıf</span></button>`).join("");
    picker.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      store("radar.sinif", b.dataset.class);
      renderPrices(data, now, b.dataset.class);
      if (window.RadarMap) window.RadarMap.setClass(b.dataset.class);
    }));
    const tbody = $("#prices-table tbody");
    if (!data.crossings.length) {
      tbody.innerHTML = `<tr><td colspan="3" class="empty">Henüz ücret kaydı yok.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.crossings.map((c, i) => `
      <tr class="row" tabindex="0" data-i="${i}" aria-expanded="false">
        <td>${esc(c.name)}<span class="op">${esc(c.operator)}</span></td>
        <td class="num price">${esc(money(c.current && c.current.classes[cls]))}</td>
        <td class="num">${priceState(c, cls, now)}</td>
      </tr>`).join("");
    tbody.querySelectorAll("tr.row").forEach((tr) => {
      const toggle = () => {
        const open = tr.nextElementSibling && tr.nextElementSibling.classList.contains("detail");
        tbody.querySelectorAll("tr.detail").forEach((d) => d.remove());
        tbody.querySelectorAll("tr.row").forEach((r) => r.setAttribute("aria-expanded", "false"));
        if (!open) {
          tr.insertAdjacentHTML("afterend", detailRow(data.crossings[Number(tr.dataset.i)], now));
          tr.setAttribute("aria-expanded", "true");
        }
      };
      tr.addEventListener("click", (e) => { if (!e.target.closest("a")) toggle(); });
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
    });
  }

  function renderFree(data, now) {
    const el = $("#free");
    const parts = [];
    (data.active_rules || []).forEach((r) => parts.push(`<p><strong>Sürüyor:</strong> ${esc(r.title)}<br>
      <span class="muted">Kapsam: ${esc(names(data, r.crossings))} · Bitiş: ${esc(dateTime(r.valid_to))}</span></p>`));
    (data.next_rules || []).forEach((r) => parts.push(`<p><strong>Karar çıktı:</strong> ${esc(r.title)}<br>
      <span class="muted">${esc(dateTime(r.valid_from))} – ${esc(dateTime(r.valid_to))} · ${esc(names(data, r.crossings))}</span>
      ${r.excluded && r.excluded.length ? `<br><span class="muted">Kapsam dışı: ${esc(names(data, r.excluded))}</span>` : ""}</p>`));
    if (!parts.length) {
      parts.push(`<p>Şu an aktif kural yok.</p>`);
      const bayram = (data.calendar || []).find((p) => p.kind === "bayram");
      if (bayram) {
        parts.push(`<p class="muted">Sıradaki: ${esc(bayram.name)} · ${esc(date(bayram.start))}<br>
          İzleme ${esc(date(bayram.watch_start))} tarihinde başlar.</p>`);
      }
    }
    el.innerHTML = parts.join("");
  }

  function renderSources(data, now) {
    const enabled = data.sources.filter((s) => s.enabled);
    const off = data.sources.length - enabled.length;
    $("#sources").innerHTML = enabled.map((s) => {
      const cls = s.ok === true ? "good" : s.ok === false ? "bad" : "";
      return `<li><span class="dot ${cls}" aria-hidden="true"></span>
        <span>${link(s.url, s.name)}</span>
        <span class="when">${esc(ago(s.last_success, now))}</span>
        ${s.ok === false ? `<span class="err">Okunamıyor (${esc(ago(s.failing_since, now))}): ${esc((s.error || "").slice(0, 120))}</span>` : ""}</li>`;
    }).join("") + (off ? `<li class="muted sources-off">${off} kaynak kapalı (config/sources.yaml)</li>` : "");
  }

  function renderEvents(data, now) {
    const list = data.events || [];
    if (!list.length) {
      $("#events").innerHTML = `<li><p class="empty">Henüz kayıt yok. Değişiklik bulunduğunda burada görünür.</p></li>`;
      return;
    }
    $("#events").innerHTML = list.map((e) => {
      const src = e.sources && e.sources[e.sources.length - 1];
      const when = e.effective_from ? ` · yürürlük ${esc(date(e.effective_from))}` : "";
      const flags = (e.flags || []).filter((f) => f.id !== "takvim")
        .map((f) => `<span class="chip ${f.id === "kacirildi" ? "bad" : ""}">${esc(f.label)}</span>`).join("");
      return `<li>
        <span class="pill ${esc(e.status)}">${esc(e.status_label)}</span>
        <div><div class="title">${src ? link(src.url, e.title) : esc(e.title)}</div>
          <div class="sub">${esc(e.kind_label)}${e.crossings.length ? " · " + esc(names(data, e.crossings)) : ""}${when}</div>
          ${flags ? `<div>${flags}</div>` : ""}</div>
        <span class="when">${esc(ago(e.updated_at, now))}</span></li>`;
    }).join("");
  }

  function renderDocuments(data) {
    const docs = data.documents || [];
    $("#doc-count").textContent = docs.length ? `(${docs.filter((d) => !d.removed).length})` : "";
    $("#documents").innerHTML = docs.length ? docs.map((d) => `
      <li class="${d.removed ? "removed" : ""}">
        <span>${link(d.url, d.title || d.key)}${d.removed ? " (listeden kaldırıldı)" : ""}</span>
        <span class="muted">${d.crossings.length ? esc(d.crossings.join(", ")) : "otoyol"}</span>
        <span class="sub">Geçerlilik: ${esc(date(d.effective_from))} · Son değişiklik: ${esc(date(d.changed_at))}${d.error ? ` · <span class="chip bad">${esc(d.error)}</span>` : ""}</span>
      </li>`).join("") : `<li class="empty">Henüz belge okunmadı.</li>`;
  }

  function renderFooter(data) {
    $("#footer").textContent = `Radar resmi kaynakları ${data.run_interval_minutes || 30} dakikada bir kontrol eder. ` +
      "Ücretler KGM tarife belgelerinden otomatik okunur; kesin bilgi için kaynağa bakın.";
  }

  async function main() {
    let data;
    try {
      data = await load();
    } catch (e) {
      $("#app").replaceChildren($("#error-tpl").content.cloneNode(true));
      $("#status").textContent = "Veri yok";
      return;
    }
    const now = new Date();
    data_ = data;
    $("#sample-note").hidden = !data.ornek;
    const saved = store("radar.sinif");
    const cls = CLASSES.includes(saved) ? saved : "1";
    renderStatus(data, now);
    renderHighlight(data, now);
    renderPrices(data, now, cls);
    renderFree(data, now);
    renderSources(data, now);
    renderEvents(data, now);
    renderDocuments(data);
    renderFooter(data);
    initMap(data, cls);
  }

  function openPriceRow(crossingId) {
    const i = data_.crossings.findIndex((c) => c.id === crossingId);
    const row = document.querySelector(`#prices-table tr.row[data-i="${i}"]`);
    if (!row) return;
    if (row.getAttribute("aria-expanded") !== "true") row.click();
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    row.focus({ preventScroll: true });
  }

  async function initMap(data, cls) {
    if (!window.RadarMap) return;
    const mapData = await loadMap();
    try {
      window.RadarMap.init({
        data, mapData, cls,
        helpers: { esc, money, date, dateTime, className: (k) => CLASS_NAMES[k] || k + ". sınıf" },
        onShowCrossing: openPriceRow,
      });
    } catch (e) {
      console.error("Harita açılamadı", e);
    }
    document.addEventListener("click", (e) => {
      const a = e.target.closest("[data-map-focus]");
      if (!a) return;
      e.preventDefault();
      window.RadarMap.focusCrossing(a.dataset.mapFocus);
    });
  }

  main();
})();
