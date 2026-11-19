/* ════════════════════════════════════════════════════════════════
   BusControl — ajustes de pantalla comunes a todas las vistas

   Envuelve en un contenedor con scroll horizontal las tablas que no
   caben en el ancho disponible, para que ninguna columna quede
   cortada en pantallas pequeñas o con zoom. No toca los datos: solo
   mete la <table> dentro de un <div class="bc-scroll-x">.
   ════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var MOVIL = 720;      // debajo de esto cada vista usa su modo de tarjetas
  var trabajando = false;

  // ¿Algún contenedor cercano ya hace el scroll horizontal?
  function yaTieneScroll(tabla) {
    var p = tabla.parentElement;
    for (var i = 0; p && i < 3; i++, p = p.parentElement) {
      var ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll') return true;
    }
    return false;
  }

  function ajustar() {
    if (trabajando) return;
    trabajando = true;
    try {
      if (window.innerWidth <= MOVIL) return;
      var tablas = document.querySelectorAll('table');
      for (var i = 0; i < tablas.length; i++) {
        var t = tablas[i];
        var p = t.parentElement;
        if (!p || p.classList.contains('bc-scroll-x')) continue;
        if (t.closest('.bc-scroll-x')) continue;
        if (yaTieneScroll(t)) continue;
        // Solo si de verdad no cabe en su contenedor
        if (t.scrollWidth <= p.clientWidth + 1) continue;
        var caja = document.createElement('div');
        caja.className = 'bc-scroll-x';
        p.insertBefore(caja, t);
        caja.appendChild(t);
      }
    } finally {
      trabajando = false;
    }
  }

  var tmr;
  function pedirAjuste() {
    clearTimeout(tmr);
    tmr = setTimeout(ajustar, 120);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', pedirAjuste);
  } else {
    pedirAjuste();
  }
  window.addEventListener('resize', pedirAjuste);
  window.addEventListener('message', function (e) {
    if (e.data && e.data.type === 'VIEW_SHOWN') pedirAjuste();
  });

  // Las vistas redibujan sus tablas con innerHTML: hay que volver a envolverlas
  if (window.MutationObserver) {
    new MutationObserver(function (cambios) {
      for (var i = 0; i < cambios.length; i++) {
        if (cambios[i].addedNodes.length) { pedirAjuste(); return; }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
})();
