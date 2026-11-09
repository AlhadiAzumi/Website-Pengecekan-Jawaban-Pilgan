/* Utilitas UI umum: slider, pencarian/sort tabel, dan konfirmasi hapus. */
(function () {
  "use strict";

  var confirmModalEl = document.getElementById("confirmModal");
  var confirmModal = confirmModalEl ? bootstrap.Modal.getOrCreateInstance(confirmModalEl) : null;
  var confirmMessage = confirmModalEl ? confirmModalEl.querySelector(".confirm-message") : null;
  var confirmOk = confirmModalEl ? confirmModalEl.querySelector("[data-confirm-ok]") : null;
  var pendingForm = null;

  function updateRangeOutput(input) {
    var target = document.querySelector(input.dataset.output);
    if (!target) return;
    var decimals = parseInt(input.dataset.decimals || "0", 10);
    target.textContent = Number(input.value).toFixed(decimals);
  }

  document.querySelectorAll('input[type="range"][data-output]').forEach(function (input) {
    updateRangeOutput(input);
    input.addEventListener("input", function () {
      updateRangeOutput(input);
    });
  });

  document.querySelectorAll("[data-table-filter]").forEach(function (input) {
    var table = document.querySelector(input.dataset.tableFilter);
    if (!table) return;
    input.addEventListener("input", function () {
      var term = input.value.toLowerCase().trim();
      table.querySelectorAll("tbody tr").forEach(function (row) {
        row.style.display = row.textContent.toLowerCase().indexOf(term) !== -1 ? "" : "none";
      });
    });
  });

  document.querySelectorAll("table[data-sortable]").forEach(function (table) {
    table.querySelectorAll("thead th[data-sort]").forEach(function (th, index) {
      th.style.cursor = "pointer";
      th.addEventListener("click", function () {
        var tbody = table.querySelector("tbody");
        var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
        var dir = th.dataset.dir === "asc" ? "desc" : "asc";
        table.querySelectorAll("thead th").forEach(function (item) {
          item.removeAttribute("data-dir");
          item.classList.remove("sorted-asc", "sorted-desc");
        });
        th.dataset.dir = dir;
        th.classList.add(dir === "asc" ? "sorted-asc" : "sorted-desc");
        var col = parseInt(th.dataset.sort, 10);
        rows.sort(function (a, b) {
          var av = a.children[col] ? a.children[col].textContent.trim() : "";
          var bv = b.children[col] ? b.children[col].textContent.trim() : "";
          var an = parseFloat(av.replace(/[^0-9.-]/g, ""));
          var bn = parseFloat(bv.replace(/[^0-9.-]/g, ""));
          if (!isNaN(an) && !isNaN(bn)) {
            return dir === "asc" ? an - bn : bn - an;
          }
          return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
        });
        rows.forEach(function (row) {
          tbody.appendChild(row);
        });
      });
    });
  });

  if (confirmModal && confirmMessage && confirmOk) {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.confirmed === "1") return;
        event.preventDefault();
        pendingForm = form;
        confirmMessage.textContent = form.dataset.confirm || "Lanjutkan tindakan ini?";
        confirmModal.show();
      });
    });

    confirmOk.addEventListener("click", function () {
      if (!pendingForm) return;
      var form = pendingForm;
      pendingForm = null;
      form.dataset.confirmed = "1";
      confirmModal.hide();
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit();
      } else {
        form.submit();
      }
    });

    confirmModalEl.addEventListener("hidden.bs.modal", function () {
      pendingForm = null;
    });
  } else {
    // Fallback bila modal tidak tersedia (mis. halaman kustom).
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (!window.confirm(form.dataset.confirm || "Lanjutkan tindakan ini?")) {
          event.preventDefault();
        }
      });
    });
  }

  document.querySelectorAll("[data-flash]").forEach(function (toast) {
    var dismissed = false;

    function dismiss() {
      if (dismissed) return;
      dismissed = true;
      toast.classList.add("is-leaving");
      window.setTimeout(function () {
        toast.remove();
      }, 260);
    }

    var close = toast.querySelector("[data-flash-close]");
    if (close) close.addEventListener("click", dismiss);

    var progress = toast.querySelector(".flash-progress");
    if (progress) {
      progress.addEventListener("animationend", function (event) {
        if (event.animationName === "flash-progress") dismiss();
      });
    }

    toast.addEventListener("keydown", function (event) {
      if (event.key === "Escape") dismiss();
    });
  });

  document.querySelectorAll(".debug-item img, .image-frame img[data-zoomable]").forEach(function (img) {
    img.style.cursor = "zoom-in";
    img.addEventListener("click", function () {
      var modalEl = document.getElementById("imagePreviewModal");
      if (!modalEl) return;
      var target = modalEl.querySelector("img");
      target.src = img.src;
      target.alt = img.alt || "Pratinjau gambar";
      bootstrap.Modal.getOrCreateInstance(modalEl).show();
    });
  });
})();
