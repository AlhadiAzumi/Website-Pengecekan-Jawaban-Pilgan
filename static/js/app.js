/* Utilitas UI umum: slider, pencarian/sort tabel, dan konfirmasi hapus. */
(function () {
  "use strict";

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

  document.querySelectorAll("[data-confirm]").forEach(function (el) {
    el.addEventListener("click", function (event) {
      if (!window.confirm(el.dataset.confirm)) {
        event.preventDefault();
      }
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
