// Comportamiento mínimo de la interfaz. Sin scripts en línea (CSP estricta).
(function () {
  "use strict";

  // Cambiar de compañía al seleccionar en la barra superior.
  document.querySelectorAll("[data-autoenviar]").forEach(function (el) {
    el.addEventListener("change", function () {
      el.form.submit();
    });
  });

  // Confirmación antes de acciones delicadas.
  document.querySelectorAll("form[data-confirmar]").forEach(function (form) {
    form.addEventListener("submit", function (evento) {
      if (!window.confirm(form.getAttribute("data-confirmar"))) {
        evento.preventDefault();
      }
    });
  });

  // Aviso de expiración de sesión por inactividad.
  var cuerpo = document.body;
  var minutos = parseInt(cuerpo.getAttribute("data-minutos-sesion") || "0", 10);
  if (minutos > 0) {
    var aviso = document.getElementById("aviso-sesion");
    var limite = minutos * 60 * 1000;
    var ultimo = Date.now();
    var reiniciar = function () { ultimo = Date.now(); if (aviso) aviso.classList.add("oculto"); };
    document.addEventListener("htmx:afterRequest", reiniciar);
    window.setInterval(function () {
      var transcurrido = Date.now() - ultimo;
      if (aviso && transcurrido > limite - 60 * 1000) {
        aviso.classList.remove("oculto");
      }
      if (transcurrido > limite) {
        window.location.reload();
      }
    }, 10000);
  }
})();
