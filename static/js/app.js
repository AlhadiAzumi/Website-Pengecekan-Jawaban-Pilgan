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
      if (event.ctrlKey || event.metaKey) {
        setPreviewZoom(previewScale + (event.deltaY < 0 ? 0.2 : -0.2));
        return;
      }
      if (previewScale > 1) {
        previewX -= event.deltaX;
        previewY -= event.deltaY;
        applyPreviewTransform();
      }
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

  var cameraModalEl = document.getElementById("cameraModal");
  if (cameraModalEl && window.bootstrap) {
    var cameraModal = bootstrap.Modal.getOrCreateInstance(cameraModalEl);
    var cameraVideo = cameraModalEl.querySelector("[data-camera-video]");
    var cameraPhoto = cameraModalEl.querySelector("[data-camera-photo]");
    var cameraStage = cameraModalEl.querySelector("[data-camera-stage]");
    var cameraState = cameraModalEl.querySelector("[data-camera-state]");
    var cameraStateText = cameraModalEl.querySelector("[data-camera-state-text]");
    var cameraStatus = cameraModalEl.querySelector("[data-camera-status]");
    var cameraShoot = cameraModalEl.querySelector("[data-camera-shoot]");
    var cameraRetake = cameraModalEl.querySelector("[data-camera-retake]");
    var cameraUse = cameraModalEl.querySelector("[data-camera-use]");
    var cameraFallbackBtn = cameraModalEl.querySelector("[data-camera-fallback]");
    var cameraDefaultStatus = cameraStatus ? cameraStatus.textContent.trim() : "";
    var cameraStream = null;
    var cameraFile = null;
    var cameraPhotoUrl = null;
    var cameraTrigger = null;
    var cameraFallbackSelector = null;
    var cameraSession = 0;

    if (cameraVideo) {
      cameraVideo.addEventListener("loadedmetadata", function () {
        if (cameraStream) cameraHideState();
      });
    }

    function cameraCanUseLive() {
      return !!(
        window.isSecureContext &&
        navigator.mediaDevices &&
        typeof navigator.mediaDevices.getUserMedia === "function"
      );
    }

    function cameraToggle(el, visible) {
      if (el) el.hidden = !visible;
    }

    function cameraShowState(message, isError) {
      if (!cameraState) return;
      cameraState.hidden = false;
      cameraState.classList.toggle("is-error", !!isError);
      if (cameraStateText) cameraStateText.textContent = message;
    }

    function cameraHideState() {
      if (cameraState) cameraState.hidden = true;
    }

    function cameraSetStatus(message) {
      if (cameraStatus) cameraStatus.textContent = message;
    }

    function cameraStopStream() {
      if (cameraStream) {
        cameraStream.getTracks().forEach(function (track) {
          track.stop();
        });
        cameraStream = null;
      }
      if (cameraVideo) cameraVideo.srcObject = null;
    }

    function cameraReleasePhoto() {
      if (cameraPhotoUrl) {
        URL.revokeObjectURL(cameraPhotoUrl);
        cameraPhotoUrl = null;
      }
      cameraFile = null;
      if (cameraPhoto) {
        cameraPhoto.hidden = true;
        cameraPhoto.removeAttribute("src");
      }
    }

    function cameraResetButtons() {
      cameraToggle(cameraShoot, false);
      cameraToggle(cameraRetake, false);
      cameraToggle(cameraUse, false);
      cameraToggle(cameraFallbackBtn, false);
    }

    function cameraShowLive() {
      cameraReleasePhoto();
      if (cameraStage) cameraStage.classList.remove("is-captured");
      if (cameraVideo) cameraVideo.hidden = false;
      cameraResetButtons();
    }

    function cameraShowError(message) {
      cameraStopStream();
      if (cameraVideo) cameraVideo.hidden = true;
      cameraShowState(message, true);
      cameraResetButtons();
      cameraToggle(cameraFallbackBtn, !!cameraFallbackSelector);
      cameraSetStatus(
        cameraFallbackSelector
          ? "Klik tombol Kamera perangkat untuk membuka kamera bawaan HP, atau tutup jendela ini."
          : "Kamera langsung tidak dapat dipakai. Tutup jendela ini lalu pilih file foto."
      );
    }

    function cameraStartStream() {
      var session = ++cameraSession;
      cameraShowLive();
      cameraShowState("Menyiapkan kamera...");
      cameraSetStatus(cameraDefaultStatus);
      cameraToggle(cameraFallbackBtn, false);

      if (!cameraCanUseLive()) {
        cameraShowError(
          "Kamera langsung hanya bisa dipakai lewat localhost atau HTTPS. " +
            "Pada akses LAN biasa (http://), gunakan kamera perangkat lewat tombol di bawah."
        );
        return;
      }

      navigator.mediaDevices
        .getUserMedia({
          audio: false,
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1440 },
          },
        })
        .then(function (stream) {
          if (session !== cameraSession) {
            stream.getTracks().forEach(function (track) {
              track.stop();
            });
            return;
          }
          cameraStream = stream;
          if (cameraVideo) {
            cameraVideo.srcObject = stream;
            var playPromise = cameraVideo.play();
            if (playPromise && typeof playPromise.catch === "function") {
              playPromise.catch(function () {
                /* autoplay bisa ditolak; gambar tetap tampil setelah metadata siap */
              });
            }
          }
          cameraHideState();
          cameraToggle(cameraShoot, true);
        })
        .catch(function (error) {
          if (session !== cameraSession) return;
          var name = error && error.name ? error.name : "";
          if (name === "NotAllowedError" || name === "SecurityError") {
            cameraShowError(
              "Izin kamera ditolak. Izinkan akses kamera pada browser, lalu coba lagi."
            );
          } else if (name === "NotFoundError" || name === "OverconstrainedError") {
            cameraShowError(
              "Kamera tidak ditemukan. Pastikan perangkat memiliki kamera yang aktif."
            );
          } else if (name === "NotReadableError") {
            cameraShowError(
              "Kamera sedang dipakai aplikasi lain. Tutup aplikasi tersebut lalu coba lagi."
            );
          } else {
            cameraShowError(
              "Kamera tidak bisa dibuka. Periksa izin browser, lalu coba lagi."
            );
          }
        });
    }

    function cameraCapture() {
      if (!cameraVideo || !cameraVideo.videoWidth || !cameraVideo.videoHeight) {
        cameraSetStatus("Kamera belum siap. Tunggu sebentar lalu coba lagi.");
        return;
      }

      var canvas = document.createElement("canvas");
      canvas.width = cameraVideo.videoWidth;
      canvas.height = cameraVideo.videoHeight;
      var context = canvas.getContext("2d");
      if (!context) {
        cameraSetStatus("Browser tidak mendukung pengambilan foto. Gunakan pilih file.");
        return;
      }
      context.drawImage(cameraVideo, 0, 0, canvas.width, canvas.height);

      var session = cameraSession;
      canvas.toBlob(
        function (blob) {
          if (session !== cameraSession || !cameraModalEl.classList.contains("show")) {
            return;
          }
          if (!blob) {
            cameraSetStatus("Foto gagal diambil. Coba lagi.");
            return;
          }
          cameraFile = new File([blob], "kamera-" + Date.now() + ".jpg", {
            type: "image/jpeg",
            lastModified: Date.now(),
          });
          cameraPhotoUrl = URL.createObjectURL(cameraFile);
          if (cameraPhoto) {
            cameraPhoto.src = cameraPhotoUrl;
            cameraPhoto.hidden = false;
          }
          if (cameraVideo) cameraVideo.hidden = true;
          if (cameraStage) cameraStage.classList.add("is-captured");
          cameraStopStream();
          cameraHideState();
          cameraToggle(cameraShoot, false);
          cameraToggle(cameraRetake, true);
          cameraToggle(cameraUse, true);
          cameraSetStatus(
            "Foto siap. Periksa apakah seluruh lembar terlihat jelas, lalu pilih Gunakan Foto."
          );
        },
        "image/jpeg",
        0.92
      );
    }

    function cameraUsePhoto() {
      if (!cameraFile) return;
      var file = cameraFile;
      var trigger = cameraTrigger;
      cameraModal.hide();
      document.dispatchEvent(
        new CustomEvent("camera:captured", {
          detail: { file: file, trigger: trigger },
        })
      );
    }

    document.querySelectorAll("[data-camera-open]").forEach(function (trigger) {
      trigger.addEventListener("click", function () {
        cameraFallbackSelector = trigger.getAttribute("data-camera-fallback") || null;
        cameraTrigger = trigger;

        if (!cameraCanUseLive() && cameraFallbackSelector) {
          var input = document.querySelector(cameraFallbackSelector);
          if (input) {
            input.click();
            return;
          }
        }

        cameraModal.show();
        cameraStartStream();
      });
    });

    if (cameraShoot) cameraShoot.addEventListener("click", cameraCapture);
    if (cameraRetake) {
      cameraRetake.addEventListener("click", function () {
        cameraStartStream();
      });
    }
    if (cameraUse) cameraUse.addEventListener("click", cameraUsePhoto);
    if (cameraFallbackBtn) {
      cameraFallbackBtn.addEventListener("click", function () {
        var input = cameraFallbackSelector
          ? document.querySelector(cameraFallbackSelector)
          : null;
        if (input) input.click();
        cameraModal.hide();
      });
    }

    cameraModalEl.addEventListener("hidden.bs.modal", function () {
      cameraSession += 1;
      cameraStopStream();
      cameraReleasePhoto();
      cameraHideState();
      if (cameraStage) cameraStage.classList.remove("is-captured");
      if (cameraVideo) cameraVideo.hidden = false;
      cameraResetButtons();
      cameraSetStatus(cameraDefaultStatus);
      cameraTrigger = null;
      cameraFallbackSelector = null;
    });
  }
})();
