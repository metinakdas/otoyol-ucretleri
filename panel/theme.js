"use strict";
// Tema sayfa çizilmeden önce uygulanır (renk sıçraması olmasın). Varsayılan açık tema; seçim bu cihazda saklanır.
(function () {
  var t = "light";
  try { var s = localStorage.getItem("radar.tema"); if (s === "dark" || s === "light") t = s; } catch (e) { /* depolama kapalı */ }
  document.documentElement.setAttribute("data-theme", t);
})();
