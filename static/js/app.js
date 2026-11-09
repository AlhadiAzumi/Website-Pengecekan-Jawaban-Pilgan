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

  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    var input = document.querySelector(button.dataset.passwordToggle);
    if (!input) return;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.setAttribute("aria-label", show ? "Sembunyikan password" : "Tampilkan password");
      var icon = button.querySelector("i");
      if (icon) {
        icon.classList.toggle("bi-eye", !show);
        icon.classList.toggle("bi-eye-slash", show);
      }
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

  var previewModalEl = document.getElementById("imagePreviewModal");
  if (previewModalEl && window.bootstrap) {
    var previewModal = bootstrap.Modal.getOrCreateInstance(previewModalEl);
    var previewImage = previewModalEl.querySelector("[data-preview-image]");
    var previewStage = previewModalEl.querySelector("[data-preview-stage]");
    var previewTitle = previewModalEl.querySelector("#imagePreviewTitle");
    var previewZoomLevel = previewModalEl.querySelector("[data-preview-zoom-level]");
    var previewOpen = previewModalEl.querySelector("[data-preview-open]");
    var previewScale = 1;
    var previewX = 0;
    var previewY = 0;
    var dragState = null;

    function clampPreviewPan() {
      var maxX = (previewStage.clientWidth * Math.max(0, previewScale - 1)) / 2;
      var maxY = (previewStage.clientHeight * Math.max(0, previewScale - 1)) / 2;
      previewX = Math.max(-maxX, Math.min(maxX, previewX));
      previewY = Math.max(-maxY, Math.min(maxY, previewY));
    }

    function applyPreviewTransform() {
      clampPreviewPan();
      previewImage.style.transform =
        "translate(" + previewX + "px, " + previewY + "px) scale(" + previewScale + ")";
      if (previewZoomLevel) {
        previewZoomLevel.textContent = Math.round(previewScale * 100) + "%";
      }
    }

    function resetPreview() {
      previewScale = 1;
      previewX = 0;
      previewY = 0;
      applyPreviewTransform();
    }

    function setPreviewZoom(value) {
      previewScale = Math.max(0.5, Math.min(4, value));
      applyPreviewTransform();
    }

    function openPreview(img) {
      previewImage.src = img.currentSrc || img.src;
      previewImage.alt = img.alt || "Pratinjau gambar";
      if (previewTitle) previewTitle.textContent = img.alt || "Pratinjau Gambar";
      if (previewOpen) previewOpen.href = img.currentSrc || img.src;
      resetPreview();
      previewModal.show();
    }

    document.querySelectorAll("[data-zoomable], .debug-item img").forEach(function (img) {
      if (img.tagName !== "IMG") return;
      img.style.cursor = "zoom-in";
      img.addEventListener("click", function () {
        openPreview(img);
      });
    });

    var zoomIn = previewModalEl.querySelector("[data-preview-zoom-in]");
    var zoomOut = previewModalEl.querySelector("[data-preview-zoom-out]");
    var zoomReset = previewModalEl.querySelector("[data-preview-reset]");
    if (zoomIn) zoomIn.addEventListener("click", function () { setPreviewZoom(previewScale + 0.25); });
    if (zoomOut) zoomOut.addEventListener("click", function () { setPreviewZoom(previewScale - 0.25); });
    if (zoomReset) zoomReset.addEventListener("click", resetPreview);

    previewStage.addEventListener("wheel", function (event) {
      event.preventDefault();
      setPreviewZoom(previewScale + (event.deltaY < 0 ? 0.2 : -0.2));
    }, { passive: false });

    previewStage.addEventListener("dblclick", function () {
      setPreviewZoom(previewScale > 1 ? 1 : 2);
    });

    previewStage.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      dragState = {
        startX: event.clientX,
        startY: event.clientY,
        originX: previewX,
        originY: previewY,
        pointerId: event.pointerId,
      };
      previewStage.classList.add("is-dragging");
      if (previewStage.setPointerCapture) {
        previewStage.setPointerCapture(event.pointerId);
      }
      event.preventDefault();
    });

    previewStage.addEventListener("pointermove", function (event) {
      if (!dragState) return;
      previewX = dragState.originX + (event.clientX - dragState.startX);
      previewY = dragState.originY + (event.clientY - dragState.startY);
      applyPreviewTransform();
    });

    function endPreviewDrag(event) {
      if (!dragState) return;
      if (previewStage.releasePointerCapture && event.pointerId !== undefined) {
        try { previewStage.releasePointerCapture(event.pointerId); } catch (error) { /* diabaikan */ }
      }
      dragState = null;
      previewStage.classList.remove("is-dragging");
    }

    previewStage.addEventListener("pointerup", endPreviewDrag);
    previewStage.addEventListener("pointercancel", endPreviewDrag);
    previewImage.addEventListener("dragstart", function (event) {
      event.preventDefault();
    });

    previewModalEl.addEventListener("hidden.bs.modal", function () {
      dragState = null;
      previewStage.classList.remove("is-dragging");
      resetPreview();
    });
  }
})();
