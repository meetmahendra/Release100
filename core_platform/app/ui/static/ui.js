/* Copyright 2026 Mahendra GURAV - Licensed under the Apache License, Version 2.0 */
/* Shared UI helper (Plan 11, T14): window.t, window.uiFetch and dialog wiring. ASCII only. */
(function () {
  "use strict";

  var bundle = {};
  var node = document.getElementById("i18n-bundle");
  if (node) {
    try {
      bundle = JSON.parse(node.textContent || "{}");
    } catch (err) {
      bundle = {};
    }
  }

  function format(template, vars) {
    return template.replace(/\{([a-z_][a-z0-9_]*)\}/g, function (whole, name) {
      return vars && Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole;
    });
  }

  function t(key, vars) {
    var chosen = key;
    if (vars && typeof vars.count === "number") {
      var form = vars.count === 1 ? "_one" : "_other";
      if (Object.prototype.hasOwnProperty.call(bundle, key + form)) {
        chosen = key + form;
      }
    }
    if (!Object.prototype.hasOwnProperty.call(bundle, chosen)) {
      return "[[" + key + "]]";
    }
    return format(bundle[chosen], vars || {});
  }

  function errorCode(body) {
    if (!body || typeof body !== "object") {
      return "";
    }
    var detail = body.detail;
    var code = body.code || body.error_code || (detail && (detail.code || detail.error_code)) || (typeof detail === "string" ? detail : "");
    return typeof code === "string" ? code : "";
  }

  function messageFor(code) {
    if (code) {
      var key = "errors." + code.toLowerCase();
      if (Object.prototype.hasOwnProperty.call(bundle, key)) {
        return t(key);
      }
    }
    return t("errors.generic");
  }

  function showAlert(message) {
    var region = document.getElementById("ui-alerts");
    if (!region) {
      return;
    }
    var box = document.createElement("div");
    box.setAttribute("role", "alert");
    box.className = "ui-alert ui-alert--danger mb-3 rounded-md border border-danger px-4 py-3 text-sm text-danger";
    box.textContent = message;
    region.appendChild(box);
  }

  /* Resolves to {ok, status, data, code, message}; never rejects. The machine code stays in `code`. */
  function uiFetch(url, options) {
    return fetch(url, options).then(
      function (response) {
        return response.text().then(function (text) {
          var data = null;
          try {
            data = text ? JSON.parse(text) : null;
          } catch (err) {
            data = null;
          }
          if (response.ok) {
            return { ok: true, status: response.status, data: data, code: "", message: "" };
          }
          var code = errorCode(data);
          return { ok: false, status: response.status, data: data, code: code, message: messageFor(code) };
        });
      },
      function () {
        return { ok: false, status: 0, data: null, code: "network", message: t("errors.network") };
      }
    );
  }

  // Invalidate back-forward cache (bfcache) when session expires or navigation history is traversed
  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    window.addEventListener("pageshow", function (event) {
      if (event && (event.persisted || (window.performance && window.performance.navigation && window.performance.navigation.type === 2))) {
        if (window.location && typeof window.location.reload === "function") {
          window.location.reload();
        }
      }
    });
  }

  document.addEventListener("click", function (event) {
    var target = event.target instanceof Element ? event.target : null;
    var closer = target && target.closest("[data-ui-close]");
    if (closer) {
      var box = document.getElementById(closer.getAttribute("data-ui-close"));
      if (box) {
        box.classList.add("hidden");
      }
    }
    var opener = target && target.closest("[data-ui-open]");
    if (opener) {
      var dialog = document.getElementById(opener.getAttribute("data-ui-open"));
      if (dialog) {
        dialog.classList.remove("hidden");
      }
    }
  });

  window.t = t;
  window.uiFetch = uiFetch;
  window.uiShowError = showAlert;
})();
