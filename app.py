"""Aplikasi web Sistem Pemeriksaan Lembar Jawaban Pilihan Ganda."""
import json
import mimetypes
import os
import shutil
from datetime import datetime

# Pastikan file font lokal dilayani dengan MIME yang benar (demo offline).
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")

import cv2
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from sqlalchemy import text

from config import (
    DATABASE_URL,
    DEBUG_UPLOAD_DIR,
    GENERATED_DIR,
    SCAN_UPLOAD_DIR,
    TEMPLATE_UPLOAD_DIR,
    UPLOAD_DIR,
    ensure_directories,
    load_secret_key,
)
from core.alignment import (
    align_to_template,
    detect_markers,
    prepare_reference,
    preprocess_debug,
)
from core.auth import (
    check_credentials,
    check_password,
    create_account,
    get_account,
    update_account,
    validate_password,
    validate_username,
)
from core.debug import (
    complete_debug_stages,
    debug_items,
    save_debug_image,
    save_debug_set,
)
from core.detection import detect_template, render_preview
from core.excel_io import build_key_example, export_results_excel, read_key_excel
from core.reading import measure_blank_baseline, process_aligned_sheet
from core.sheet_generator import generate_blank_sheet, to_pdf_bytes, to_png_bytes
from models import (
    AnswerKey,
    AnswerKeyItem,
    ScanAnswer,
    ScanResult,
    Template,
    TemplateBubble,
    db,
    get_settings,
    seed_settings,
    set_setting,
)
from utils import (
    abs_upload,
    new_id,
    rel_upload,
    safe_upload_path,
    save_upload_image,
)

APP_TITLE = "Sistem Pemeriksaan Lembar Jawaban Pilihan Ganda"


def _as_int(value, default, minimum=None, maximum=None):
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _as_float(value, default, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _read_params(form):
    return {
        "detect_threshold": _as_int(form.get("detect_threshold"), 0, 0, 255),
        "min_area": _as_int(form.get("min_area"), 120, 8, 100000),
        "max_area": _as_int(form.get("max_area"), 4000, 50, 500000),
        "circularity": _as_float(form.get("circularity"), 0.60, 0.1, 0.99),
        "threshold_method": form.get("threshold_method", "otsu"),
        "adaptive_block_size": _as_int(form.get("adaptive_block_size"), 31, 3, 151),
        "adaptive_c": _as_int(form.get("adaptive_c"), 15, -20, 50),
        "morph_kernel": _as_int(form.get("morph_kernel"), 3, 1, 15),
        "fill_ratio": _as_float(form.get("fill_ratio"), 0.40, 0.05, 0.95),
        "blur_threshold": _as_float(form.get("blur_threshold"), 45.0, 0.0, 500.0),
    }


def _template_form_state(form, settings):
    return {
        "name": form.get("name", "").strip(),
        "n_questions": _as_int(form.get("n_questions"), 50, 1, 300),
        "n_options": _as_int(form.get("n_options"), 5, 2, 10),
        "n_blocks": _as_int(form.get("n_blocks"), 0, 0, 4),
        "params": _read_params(form),
    }


def _template_preview_context(
    state,
    ref,
    rectified,
    markers,
    preview_path,
    debug_images,
    detection,
    tmp_ref,
    tmp_src,
    tmp_debug_id,
    original_name,
):
    return {
        "form": state,
        "preview_url": url_for("media", filename=preview_path),
        "debug_items": debug_images,
        "detection": detection,
        "tmp_ref": tmp_ref,
        "tmp_src": tmp_src,
        "tmp_debug_id": tmp_debug_id,
        "original_name": original_name,
        "rectified": rectified,
        "marker_count": len(markers or []),
        "ref_width": ref.shape[1],
        "ref_height": ref.shape[0],
    }


def safe_redirect_target(target):
    """Terima hanya path lokal agar tidak menjadi open redirect."""
    target = (target or "").strip()
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    if target.rstrip("/") in ("/login", "/logout"):
        return None
    return target


def create_app():
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=load_secret_key(),
        SQLALCHEMY_DATABASE_URI=DATABASE_URL,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,
        APP_TITLE=APP_TITLE,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    ensure_directories()
    db.init_app(app)

    with app.app_context():
        db.create_all()
        seed_settings()

    @app.route("/healthz")
    def healthz():
        try:
            db.session.execute(text("SELECT 1"))
            return {"status": "ok"}, 200
        except Exception:
            return {"status": "error"}, 500

    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            app.static_folder, "favicon.ico", mimetype="image/vnd.microsoft.icon"
        )

    @app.before_request
    def require_login():
        if request.endpoint in {"static", "healthz", "login", "favicon"}:
            return None
        account = get_account()
        if account is None:
            return redirect(url_for("login"))
        if session.get("auth_user") != account["username"]:
            target = request.full_path.rstrip("?") if request.method == "GET" else ""
            return redirect(url_for("login", next=target))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        account = get_account()
        setup = account is None
        next_url = safe_redirect_target(request.values.get("next", ""))

        if not setup and session.get("auth_user") == account["username"]:
            return redirect(next_url or url_for("index"))

        form_username = ""
        if request.method == "POST":
            form_username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            if setup:
                confirm = request.form.get("confirm_password", "")
                error = (
                    validate_username(form_username)
                    or validate_password(password)
                    or (
                        None
                        if password == confirm
                        else "Konfirmasi password tidak sama."
                    )
                )
                if error:
                    flash(error, "danger")
                else:
                    create_account(form_username, password)
                    session.clear()
                    session["auth_user"] = form_username
                    flash(
                        "Akun admin berhasil dibuat. Selamat datang di Pilgan Checker!",
                        "success",
                    )
                    return redirect(next_url or url_for("index"))
            elif check_credentials(form_username, password):
                session.clear()
                session["auth_user"] = account["username"]
                flash(f"Selamat datang, {account['username']}.", "success")
                return redirect(next_url or url_for("index"))
            else:
                flash("Username atau password salah.", "danger")

        return render_template(
            "auth.html",
            setup=setup,
            next_url=next_url or "",
            form_username=form_username,
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Anda sudah keluar dari aplikasi.", "info")
        return redirect(url_for("login"))

    @app.route("/account", methods=["POST"])
    def account_update():
        account = get_account()
        if account is None:
            return redirect(url_for("login"))

        current_password = request.form.get("current_password", "")
        if not check_password(account, current_password):
            flash("Password saat ini salah.", "danger")
            return redirect(url_for("settings_page"))

        username = request.form.get("new_username", "").strip()
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        error = validate_username(username)
        if not error and new_password:
            error = validate_password(new_password)
            if not error and new_password != confirm:
                error = "Konfirmasi password baru tidak sama."
        if error:
            flash(error, "danger")
            return redirect(url_for("settings_page"))

        update_account(username, new_password or None)
        session.clear()
        flash(
            "Akun berhasil diperbarui. Silakan masuk kembali dengan akun baru.",
            "success",
        )
        return redirect(url_for("login"))

    @app.template_filter("media_url")
    def media_url(path):
        if not path:
            return ""
        return url_for("media", filename=path)

    @app.template_filter("datetime_id")
    def datetime_id(value):
        if not value:
            return "-"
        return value.strftime("%d-%m-%Y %H:%M")

    @app.context_processor
    def inject_globals():
        def asset_version(*paths):
            latest = 0
            for path in paths:
                try:
                    latest = max(
                        latest,
                        os.path.getmtime(os.path.join(app.static_folder, path)),
                    )
                except OSError:
                    continue
            return str(int(latest))

        return {
            "app_title": APP_TITLE,
            "settings": get_settings(),
            "current_year": datetime.now().year,
            "asset_version": asset_version("css/style.css", "js/app.js"),
            "auth_page": request.endpoint == "login",
            "current_user": session.get("auth_user"),
        }

    @app.route("/")
    def index():
        stats = {
            "templates": Template.query.count(),
            "keys": AnswerKey.query.count(),
            "scans": ScanResult.query.count(),
        }
        recent = (
            ScanResult.query.order_by(ScanResult.created_at.desc()).limit(8).all()
        )
        average = None
        if stats["scans"]:
            average = (
                db.session.query(db.func.avg(ScanResult.score)).scalar() or 0.0
            )
        return render_template(
            "index.html", stats=stats, recent=recent, average=average
        )

    @app.route("/templates")
    def templates_list():
        templates = Template.query.order_by(Template.created_at.desc()).all()
        return render_template("templates_list.html", templates=templates)

    @app.route("/templates/new", methods=["GET", "POST"])
    def template_new():
        settings = get_settings()
        if request.method == "GET":
            return render_template(
                "template_new.html",
                form={
                    "name": "",
                    "n_questions": 50,
                    "n_options": 5,
                    "n_blocks": 0,
                    "params": settings,
                },
                detection=None,
            )

        state = _template_form_state(request.form, settings)
        action = request.form.get("action", "preview")
        tmp_ref = request.form.get("tmp_ref", "")
        tmp_src = request.form.get("tmp_src", "")
        tmp_debug_id = request.form.get("tmp_debug_id", "")
        original_name = request.form.get("original_name", "")

        try:
            upload = request.files.get("image")
            if upload is not None and upload.filename:
                src_path, src_rel, image = save_upload_image(
                    upload, prefix="template", subdir=TEMPLATE_UPLOAD_DIR
                )
                reference, info = prepare_reference(image)
                tmp_ref_id = new_id()
                ref_path = os.path.join(
                    TEMPLATE_UPLOAD_DIR, f"template_ref_{tmp_ref_id}.jpg"
                )
                if not cv2.imwrite(ref_path, reference):
                    raise ValueError("Gagal menyimpan citra acuan templat.")
                tmp_ref = rel_upload(ref_path)
                tmp_src = src_rel
                tmp_debug_id = tmp_ref_id
                original_name = upload.filename
                rectified = info["method"]
                markers = info["markers"]
            elif tmp_ref:
                ref_path = safe_upload_path(tmp_ref)
                if not ref_path or not os.path.exists(ref_path):
                    raise ValueError("Citra templat sementara tidak ditemukan. Unggah ulang.")
                reference = cv2.imread(ref_path)
                if reference is None:
                    raise ValueError("Citra templat tidak dapat dibaca. Unggah ulang.")
                rectified = request.form.get("rectified", "resize")
                markers = detect_markers(reference)
            else:
                raise ValueError("Pilih gambar lembar jawaban kosong terlebih dahulu.")

            n_blocks = state["n_blocks"] or None
            detection = detect_template(
                reference,
                state["n_questions"],
                state["n_options"],
                n_blocks,
                state["params"],
            )

            folder = os.path.join(DEBUG_UPLOAD_DIR, f"template_{tmp_debug_id or new_id()}")
            saved = save_debug_set(
                folder,
                {
                    "2_grayscale": detection["debug"]["grayscale"],
                    "7_threshold": detection["debug"]["threshold"],
                    "9_deteksi": detection["preview"],
                },
            )
            preview_path = save_debug_image(folder, "preview", detection["preview"])
            preview_items = debug_items(saved)

            if action == "save":
                if not detection["success"]:
                    flash(
                        "Templat belum dapat disimpan karena jumlah bulatan tidak sesuai. "
                        "Sesuaikan parameter deteksi lalu coba lagi.",
                        "warning",
                    )
                else:
                    baseline = measure_blank_baseline(
                        reference, detection["bubbles"], state["params"]
                    )
                    markers_final = markers or detect_markers(reference)
                    template = Template(
                        name=state["name"] or f"Templat {state['n_questions']} soal",
                        original_filename=original_name,
                        source_path=tmp_src,
                        ref_path=tmp_ref,
                        width=reference.shape[1],
                        height=reference.shape[0],
                        n_questions=state["n_questions"],
                        n_options=state["n_options"],
                        option_labels=[
                            chr(ord("A") + index)
                            for index in range(state["n_options"])
                        ],
                        n_blocks=int(detection["n_blocks"] or 1),
                        bubble_radius=float(
                            sum(item["radius"] for item in detection["bubbles"])
                            / max(1, len(detection["bubbles"]))
                        ),
                        detect_params={
                            **state["params"],
                            "cell_mode": detection.get("cell_mode", "bubble"),
                            "mark_gain": detection.get("mark_gain", 1.0),
                        },
                        marker_positions=markers_final,
                    )
                    db.session.add(template)
                    db.session.flush()
                    for item in detection["bubbles"]:
                        blank = baseline.get(
                            (item["question_no"], item["option_index"]), 0.0
                        )
                        db.session.add(
                            TemplateBubble(
                                template_id=template.id,
                                question_no=item["question_no"],
                                option_index=item["option_index"],
                                option_label=item["option_label"],
                                x=item["x"],
                                y=item["y"],
                                radius=item["radius"],
                                blank_ratio=blank,
                                row_index=item["row_index"],
                                block_index=item["block_index"],
                            )
                        )
                    db.session.commit()
                    flash(
                        f"Templat '{template.name}' berhasil disimpan dengan "
                        f"{len(detection['bubbles'])} bulatan.",
                        "success",
                    )
                    return redirect(
                        url_for("template_detail", template_id=template.id)
                    )

            return render_template(
                "template_new.html",
                **_template_preview_context(
                    state,
                    reference,
                    rectified,
                    markers,
                    preview_path,
                    preview_items,
                    detection,
                    tmp_ref,
                    tmp_src,
                    tmp_debug_id,
                    original_name,
                ),
            )
        except ValueError as exc:
            flash(str(exc), "danger")
        except Exception as exc:  # noqa: BLE001
            db.session.rollback()
            flash(f"Terjadi kesalahan saat memproses templat: {exc}", "danger")

        return render_template(
            "template_new.html", form=state, detection=None
        )

    @app.route("/templates/sample", methods=["GET", "POST"])
    def sample_sheet():
        settings = get_settings()
        form = {
            "n_questions": 50,
            "n_options": 5,
            "n_blocks": 2,
            "title": "LEMBAR JAWABAN PILIHAN GANDA",
        }
        generated = None
        if request.method == "POST":
            form = {
                "n_questions": _as_int(
                    request.form.get("n_questions"), 50, 1, 120
                ),
                "n_options": _as_int(request.form.get("n_options"), 5, 2, 10),
                "n_blocks": _as_int(request.form.get("n_blocks"), 0, 0, 4),
                "title": request.form.get("title", "").strip()
                or "LEMBAR JAWABAN PILIHAN GANDA",
            }
            try:
                image, _, _ = generate_blank_sheet(
                    form["n_questions"],
                    form["n_options"],
                    form["n_blocks"] or None,
                    title=form["title"],
                )
                file_id = new_id()
                png_name = f"lembar_{file_id}.png"
                pdf_name = f"lembar_{file_id}.pdf"
                png_path = os.path.join(GENERATED_DIR, png_name)
                pdf_path = os.path.join(GENERATED_DIR, pdf_name)
                with open(png_path, "wb") as handle:
                    handle.write(to_png_bytes(image))
                with open(pdf_path, "wb") as handle:
                    handle.write(to_pdf_bytes(image))
                generated = {
                    "png": f"generated/{png_name}",
                    "pdf": f"generated/{pdf_name}",
                    "png_size": os.path.getsize(png_path),
                    "pdf_size": os.path.getsize(pdf_path),
                }
                flash("Lembar contoh berhasil dibuat. Silakan unduh atau cetak.", "success")
            except (ValueError, OSError) as exc:
                flash(f"Gagal membuat lembar contoh: {exc}", "danger")
        return render_template(
            "sample_sheet.html", form=form, generated=generated, settings=settings
        )

    @app.route("/templates/<int:template_id>")
    def template_detail(template_id):
        template = db.get_or_404(Template, template_id)
        ref_path = abs_upload(template.ref_path)
        reference = cv2.imread(ref_path) if ref_path else None
        preview_url = ""
        if reference is not None:
            items = [
                {
                    "x": bubble.x,
                    "y": bubble.y,
                    "radius": bubble.radius,
                    "question_no": bubble.question_no,
                    "option_index": bubble.option_index,
                    "option_label": bubble.option_label,
                    "row_index": bubble.row_index,
                    "block_index": bubble.block_index,
                }
                for bubble in template.bubbles
            ]
            preview = render_preview(
                reference, items, marker_positions=template.marker_positions
            )
            folder = os.path.join(DEBUG_UPLOAD_DIR, f"template_{template.id}")
            preview_path = save_debug_image(folder, "preview", preview)
            preview_url = url_for("media", filename=preview_path)
        return render_template(
            "template_detail.html",
            template=template,
            preview_url=preview_url,
        )

    @app.route("/templates/<int:template_id>/delete", methods=["POST"])
    def template_delete(template_id):
        template = db.get_or_404(Template, template_id)
        if template.scans:
            flash(
                "Templat tidak dapat dihapus karena sudah memiliki hasil pemeriksaan. "
                "Hapus hasil terlebih dahulu.",
                "warning",
            )
            return redirect(url_for("template_detail", template_id=template.id))
        name = template.name
        db.session.delete(template)
        db.session.commit()
        flash(f"Templat '{name}' dihapus.", "success")
        return redirect(url_for("templates_list"))

    @app.route("/keys")
    def keys_list():
        keys = AnswerKey.query.order_by(AnswerKey.created_at.desc()).all()
        return render_template("keys_list.html", keys=keys)

    @app.route("/templates/<int:template_id>/keys")
    def key_list_for_template(template_id):
        template = db.get_or_404(Template, template_id)
        keys = (
            AnswerKey.query.filter_by(template_id=template.id)
            .order_by(AnswerKey.created_at.desc())
            .all()
        )
        return render_template(
            "key_list.html", template=template, keys=keys
        )

    def _create_key(template, package_name, answers):
        package_name = (package_name or "").strip()
        if not package_name:
            raise ValueError("Nama paket kunci wajib diisi.")
        duplicate = AnswerKey.query.filter_by(
            template_id=template.id, package_name=package_name
        ).first()
        if duplicate is not None:
            raise ValueError(
                f"Paket kunci '{package_name}' sudah ada pada templat ini."
            )
        labels = set(template.option_labels or [])
        for question_no in range(1, template.n_questions + 1):
            if question_no not in answers:
                raise ValueError(f"Kunci soal nomor {question_no} belum diisi.")
            if answers[question_no] not in labels:
                raise ValueError(
                    f"Kunci soal {question_no} bukan opsi yang valid."
                )
        key = AnswerKey(
            template_id=template.id, package_name=package_name
        )
        db.session.add(key)
        db.session.flush()
        for question_no in range(1, template.n_questions + 1):
            db.session.add(
                AnswerKeyItem(
                    key_id=key.id,
                    question_no=question_no,
                    answer=answers[question_no],
                )
            )
        db.session.commit()
        return key

    @app.route("/templates/<int:template_id>/keys/new", methods=["GET", "POST"])
    def key_new(template_id):
        template = db.get_or_404(Template, template_id)
        if request.method == "POST":
            answers = {}
            try:
                for question_no in range(1, template.n_questions + 1):
                    value = request.form.get(f"q_{question_no}", "").strip().upper()
                    if value:
                        answers[question_no] = value
                key = _create_key(
                    template,
                    request.form.get("package_name", ""),
                    answers,
                )
                flash(
                    f"Kunci '{key.package_name}' berhasil disimpan.",
                    "success",
                )
                return redirect(url_for("key_edit", key_id=key.id))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
                return render_template(
                    "key_form.html",
                    template=template,
                    key=None,
                    answers=answers,
                    package_name=request.form.get("package_name", ""),
                )
        return render_template(
            "key_form.html",
            template=template,
            key=None,
            answers={},
            package_name=request.args.get("package", ""),
        )

    @app.route("/templates/<int:template_id>/keys/upload", methods=["POST"])
    def key_upload(template_id):
        template = db.get_or_404(Template, template_id)
        upload = request.files.get("excel")
        if upload is None or not upload.filename:
            flash("Pilih file Excel terlebih dahulu.", "danger")
            return redirect(
                url_for("key_list_for_template", template_id=template.id)
            )
        if not upload.filename.lower().endswith(".xlsx"):
            flash("Format file harus .xlsx. Gunakan contoh yang disediakan.", "danger")
            return redirect(
                url_for("key_list_for_template", template_id=template.id)
            )
        package_name = request.form.get("package_name", "").strip()
        if not package_name:
            package_name = os.path.splitext(os.path.basename(upload.filename))[0]
        answers, errors = read_key_excel(
            upload, template.n_questions, template.option_labels
        )
        if errors:
            for error in errors[:8]:
                flash(error, "danger")
            if len(errors) > 8:
                flash(f"... dan {len(errors) - 8} kesalahan lain.", "danger")
            return redirect(
                url_for("key_list_for_template", template_id=template.id)
            )
        try:
            key = _create_key(template, package_name, answers)
            flash(
                f"Kunci '{key.package_name}' berhasil diimpor dari Excel.",
                "success",
            )
            return redirect(url_for("key_edit", key_id=key.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(
                url_for("key_list_for_template", template_id=template.id)
            )

    @app.route("/templates/<int:template_id>/keys/example.xlsx")
    def key_example(template_id):
        template = db.get_or_404(Template, template_id)
        output = build_key_example(
            template.n_questions, template.option_labels
        )
        return send_file(
            output,
            as_attachment=True,
            download_name=f"contoh_kunci_{template.n_questions}soal.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/keys/<int:key_id>", methods=["GET", "POST"])
    def key_edit(key_id):
        key = db.get_or_404(AnswerKey, key_id)
        template = key.template
        if request.method == "POST":
            answers = {}
            for question_no in range(1, template.n_questions + 1):
                value = request.form.get(f"q_{question_no}", "").strip().upper()
                if value:
                    answers[question_no] = value
            package_name = request.form.get("package_name", "").strip()
            try:
                if not package_name:
                    raise ValueError("Nama paket kunci wajib diisi.")
                duplicate = AnswerKey.query.filter(
                    AnswerKey.template_id == template.id,
                    AnswerKey.package_name == package_name,
                    AnswerKey.id != key.id,
                ).first()
                if duplicate is not None:
                    raise ValueError(
                        f"Paket kunci '{package_name}' sudah ada pada templat ini."
                    )
                labels = set(template.option_labels or [])
                for question_no in range(1, template.n_questions + 1):
                    if question_no not in answers:
                        raise ValueError(
                            f"Kunci soal nomor {question_no} belum diisi."
                        )
                    if answers[question_no] not in labels:
                        raise ValueError(
                            f"Kunci soal {question_no} bukan opsi yang valid."
                        )
                key.package_name = package_name
                for item in list(key.items):
                    db.session.delete(item)
                db.session.flush()
                for question_no in range(1, template.n_questions + 1):
                    db.session.add(
                        AnswerKeyItem(
                            key_id=key.id,
                            question_no=question_no,
                            answer=answers[question_no],
                        )
                    )
                db.session.commit()
                flash("Kunci jawaban diperbarui.", "success")
                return redirect(url_for("key_edit", key_id=key.id))
            except ValueError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
        return render_template(
            "key_form.html",
            template=template,
            key=key,
            answers=key.answer_map,
            package_name=key.package_name,
        )

    @app.route("/keys/<int:key_id>/delete", methods=["POST"])
    def key_delete(key_id):
        key = db.get_or_404(AnswerKey, key_id)
        template_id = key.template_id
        if key.scans:
            flash(
                "Kunci tidak dapat dihapus karena sudah dipakai pada hasil scan.",
                "warning",
            )
            return redirect(url_for("key_edit", key_id=key.id))
        name = key.package_name
        db.session.delete(key)
        db.session.commit()
        flash(f"Kunci '{name}' dihapus.", "success")
        return redirect(
            url_for("key_list_for_template", template_id=template_id)
        )

    @app.route("/scan", methods=["GET", "POST"])
    def scan_page():
        templates = Template.query.order_by(Template.name).all()
        selected_template_id = request.values.get("template_id", type=int)
        selected_template = (
            db.session.get(Template, selected_template_id)
            if selected_template_id
            else None
        )
        selected_key_id = request.values.get("key_id", type=int)
        templates_json = {
            template.id: {
                "name": template.name,
                "keys": [
                    {"id": key.id, "package_name": key.package_name}
                    for key in template.keys
                ],
            }
            for template in templates
        }

        if request.method == "POST":
            if selected_template is None:
                flash("Pilih templat terlebih dahulu.", "danger")
            else:
                key = (
                    db.session.get(AnswerKey, selected_key_id)
                    if selected_key_id
                    else None
                )
                if key is None or key.template_id != selected_template.id:
                    flash("Pilih paket kunci yang sesuai dengan templat.", "danger")
                else:
                    files = [
                        item
                        for item in request.files.getlist("photos")
                        if item is not None and item.filename
                    ]
                    if not files:
                        flash("Pilih minimal satu foto lembar jawaban.", "danger")
                    else:
                        names = request.form.getlist("student_names")
                        numbers = request.form.getlist("student_nos")
                        common_class = request.form.get("class_name", "").strip()
                        alignment_mode = request.form.get("alignment_mode", "auto")
                        params = dict(get_settings())
                        stored = selected_template.detect_params or {}
                        params["cell_mode"] = stored.get("cell_mode", "bubble")
                        params["mark_gain"] = float(
                            stored.get("mark_gain", 1.0) or 1.0
                        )
                        params.update(
                            {
                                "fill_ratio": _as_float(
                                    request.form.get("fill_ratio"), 0.40, 0.05, 0.95
                                ),
                                "threshold_method": request.form.get(
                                    "threshold_method", "otsu"
                                ),
                                "morph_kernel": _as_int(
                                    request.form.get("morph_kernel"), 3, 1, 15
                                ),
                                "adaptive_block_size": _as_int(
                                    request.form.get("adaptive_block_size"), 31, 3, 151
                                ),
                                "adaptive_c": _as_int(
                                    request.form.get("adaptive_c"), 15, -20, 50
                                ),
                            }
                        )
                        ref_path = abs_upload(selected_template.ref_path)
                        reference = cv2.imread(ref_path) if ref_path else None
                        if reference is None:
                            flash(
                                "Citra acuan templat tidak ditemukan. Buat ulang templat.",
                                "danger",
                            )
                        else:
                            batch_id = new_id()
                            key_map = key.answer_map
                            success = 0
                            failures = []
                            for index, upload in enumerate(files):
                                default_name = os.path.splitext(
                                    os.path.basename(upload.filename)
                                )[0]
                                student_name = (
                                    names[index].strip()
                                    if index < len(names) and names[index].strip()
                                    else default_name
                                )
                                student_no = (
                                    numbers[index].strip()
                                    if index < len(numbers)
                                    else ""
                                )
                                saved_rel = ""
                                try:
                                    saved_abs, saved_rel, image = save_upload_image(
                                        upload, prefix="scan", subdir=SCAN_UPLOAD_DIR
                                    )
                                except ValueError as exc:
                                    failures.append(f"{student_name}: {exc}")
                                    continue
                                except Exception as exc:  # noqa: BLE001
                                    failures.append(f"{student_name}: {exc}")
                                    continue

                                try:
                                    aligned, method, steps, warnings = align_to_template(
                                        image,
                                        reference,
                                        selected_template.marker_positions,
                                        mode=alignment_mode,
                                    )
                                    pipeline = process_aligned_sheet(
                                        aligned,
                                        selected_template.bubbles,
                                        key_map,
                                        selected_template.n_questions,
                                        params,
                                    )
                                    result = ScanResult(
                                        batch_id=batch_id,
                                        template_id=selected_template.id,
                                        key_id=key.id,
                                        student_name=student_name,
                                        student_no=student_no,
                                        class_name=common_class,
                                        original_path=saved_rel,
                                        alignment_method=method,
                                        threshold_method=pipeline["threshold_label"],
                                        morph_kernel=params["morph_kernel"],
                                        fill_ratio=params["fill_ratio"],
                                        correct=pipeline["correct"],
                                        wrong=pipeline["wrong"],
                                        empty=pipeline["empty"],
                                        double=pipeline["double"],
                                        score=pipeline["score"],
                                        quality_warning=(
                                            " ".join(
                                                part
                                                for part in [
                                                    pipeline["quality_warning"],
                                                    " ".join(warnings),
                                                ]
                                                if part
                                            )[:250]
                                            or None
                                        ),
                                    )
                                    db.session.add(result)
                                    db.session.flush()
                                    folder = os.path.join(
                                        DEBUG_UPLOAD_DIR, f"scan_{result.id}"
                                    )
                                    original_gray, original_blur, original_edges = preprocess_debug(image)
                                    debug_images = {
                                        "1_original": image,
                                        "2_grayscale": original_gray,
                                        "3_blur": original_blur,
                                        "4_canny": steps.get("edges", original_edges),
                                        "6_aligned": aligned,
                                        "7_threshold": pipeline["binary"],
                                        "8_morphology": pipeline["morph"],
                                        "9_deteksi": pipeline["annotated"],
                                    }
                                    for step_name, image_name in (
                                        ("outline", "5_kontur"),
                                        ("marker", "5_marker"),
                                        ("orb", "5_orb"),
                                    ):
                                        if step_name in steps:
                                            debug_images[image_name] = steps[step_name]
                                    saved = save_debug_set(folder, debug_images)
                                    result.aligned_path = saved.get("6_aligned", "")
                                    result.threshold_path = saved.get("7_threshold", "")
                                    result.morph_path = saved.get("8_morphology", "")
                                    result.annotated_path = saved.get("9_deteksi", "")
                                    result.debug_steps = saved
                                    for detail in pipeline["details"]:
                                        db.session.add(
                                            ScanAnswer(
                                                result_id=result.id,
                                                question_no=detail["question_no"],
                                                student_answer=detail["student_answer"],
                                                correct_answer=detail["correct_answer"],
                                                status=detail["status"],
                                                ratio=detail["ratio"],
                                                all_ratios=detail["all_ratios"],
                                            )
                                        )
                                    db.session.commit()
                                    success += 1
                                except Exception as exc:  # noqa: BLE001
                                    db.session.rollback()
                                    failures.append(f"{student_name}: {exc}")
                                    if saved_rel:
                                        try:
                                            os.remove(abs_upload(saved_rel))
                                        except OSError:
                                            pass

                            if success:
                                flash(
                                    f"{success} lembar berhasil diperiksa."
                                    + (
                                        f" {len(failures)} lembar gagal."
                                        if failures
                                        else ""
                                    ),
                                    "success",
                                )
                            for failure in failures[:6]:
                                flash(failure, "danger")
                            if len(failures) > 6:
                                flash(
                                    f"... dan {len(failures) - 6} kegagalan lain.",
                                    "danger",
                                )
                            if success:
                                return redirect(
                                    url_for("results_list", batch=batch_id)
                                )
                            return redirect(
                                url_for(
                                    "scan_page",
                                    template_id=selected_template.id,
                                    key_id=key.id,
                                )
                            )

        if selected_template is None and selected_template_id:
            selected_template = None
        keys = selected_template.keys if selected_template else []
        if selected_key_id is None and keys:
            selected_key_id = keys[0].id
        return render_template(
            "scan.html",
            templates=templates,
            templates_json=templates_json,
            selected_template=selected_template,
            selected_key_id=selected_key_id,
            keys=keys,
        )

    def _filtered_results():
        batch = request.args.get("batch", "").strip()
        template_id = request.args.get("template_id", type=int)
        grade = request.args.get("grade", "").strip()
        query = ScanResult.query
        if batch:
            query = query.filter(ScanResult.batch_id == batch)
        if template_id:
            query = query.filter(ScanResult.template_id == template_id)
        if grade == "lulus":
            query = query.filter(ScanResult.score >= 75)
        elif grade == "remedial":
            query = query.filter(ScanResult.score < 75)
        return query.order_by(ScanResult.created_at.desc()).limit(500).all(), {
            "batch": batch,
            "template_id": template_id,
            "grade": grade,
        }

    def _result_summary(results):
        total = len(results)
        scores = [float(result.score or 0.0) for result in results]
        return {
            "total": total,
            "average": (sum(scores) / total) if total else 0.0,
            "highest": max(scores) if scores else 0.0,
            "lowest": min(scores) if scores else 0.0,
            "passed": sum(1 for score in scores if score >= 75),
        }

    def _delete_result_files(result):
        paths = {result.original_path}
        for path in (result.debug_steps or {}).values():
            paths.add(path)
        for relative in paths:
            absolute = safe_upload_path(relative) if relative else ""
            if absolute and os.path.isfile(absolute):
                try:
                    os.remove(absolute)
                except OSError:
                    pass
        shutil.rmtree(
            os.path.join(DEBUG_UPLOAD_DIR, f"scan_{result.id}"), ignore_errors=True
        )

    @app.route("/results")
    def results_list():
        results, filters = _filtered_results()
        templates = Template.query.order_by(Template.name).all()
        active_filters = {
            key: value for key, value in filters.items() if value
        }
        return render_template(
            "results_list.html",
            results=results,
            filters=filters,
            summary=_result_summary(results),
            templates=templates,
            export_url=url_for("results_export", **active_filters),
        )

    @app.route("/results/export.xlsx")
    def results_export():
        results, filters = _filtered_results()
        if not results:
            flash("Belum ada hasil untuk diekspor.", "warning")
            return redirect(url_for("results_list", **request.args))
        output = export_results_excel(results)
        suffix = ""
        if filters["batch"]:
            suffix = "_batch"
        elif filters["template_id"]:
            suffix = "_templat"
        download_name = (
            f"hasil_pemeriksaan{suffix}_{datetime.now():%Y%m%d_%H%M}.xlsx"
        )
        return send_file(
            output,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/results/<int:result_id>")
    def result_detail(result_id):
        result = db.get_or_404(ScanResult, result_id)
        stored = result.debug_steps or {}
        completed = complete_debug_stages(stored)
        if completed != stored:
            result.debug_steps = completed
            db.session.commit()
        steps = debug_items(completed)
        return render_template(
            "result_detail.html", result=result, debug_items=steps
        )

    @app.route("/results/<int:result_id>/export.xlsx")
    def result_export(result_id):
        result = db.get_or_404(ScanResult, result_id)
        output = export_results_excel([result])
        safe_name = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in result.student_name
        ).strip("_") or f"hasil_{result.id}"
        return send_file(
            output,
            as_attachment=True,
            download_name=f"{safe_name}.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.route("/results/<int:result_id>/delete", methods=["POST"])
    def result_delete(result_id):
        result = db.get_or_404(ScanResult, result_id)
        batch_id = result.batch_id
        name = result.student_name
        _delete_result_files(result)
        db.session.delete(result)
        db.session.commit()
        flash(f"Hasil pemeriksaan '{name}' dihapus.", "success")
        if batch_id:
            return redirect(url_for("results_list", batch=batch_id))
        return redirect(url_for("results_list"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        if request.method == "POST":
            values = {
                "detect_threshold": _as_int(
                    request.form.get("detect_threshold"), 0, 0, 255
                ),
                "min_area": _as_int(request.form.get("min_area"), 120, 8, 100000),
                "max_area": _as_int(request.form.get("max_area"), 4000, 50, 500000),
                "circularity": _as_float(
                    request.form.get("circularity"), 0.60, 0.1, 0.99
                ),
                "threshold_method": request.form.get("threshold_method", "otsu")
                if request.form.get("threshold_method") in {"otsu", "adaptive"}
                else "otsu",
                "adaptive_block_size": _as_int(
                    request.form.get("adaptive_block_size"), 31, 3, 151
                ),
                "adaptive_c": _as_int(request.form.get("adaptive_c"), 15, -20, 50),
                "morph_kernel": _as_int(request.form.get("morph_kernel"), 3, 1, 15),
                "fill_ratio": _as_float(
                    request.form.get("fill_ratio"), 0.40, 0.05, 0.95
                ),
                "blur_threshold": _as_float(
                    request.form.get("blur_threshold"), 45.0, 0.0, 500.0
                ),
            }
            for key, value in values.items():
                set_setting(key, value)
            db.session.commit()
            flash("Pengaturan default berhasil disimpan.", "success")
            return redirect(url_for("settings_page"))
        return render_template(
            "settings.html",
            stats={
                "templates": Template.query.count(),
                "keys": AnswerKey.query.count(),
                "scans": ScanResult.query.count(),
            },
        )

    @app.route("/media/<path:filename>")
    def media(filename):
        return send_from_directory(UPLOAD_DIR, filename)

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="Halaman tidak ditemukan."), 404

    @app.errorhandler(413)
    def too_large(error):
        return (
            render_template(
                "error.html",
                code=413,
                message="Ukuran file terlalu besar. Maksimal 32 MB per permintaan.",
            ),
            413,
        )

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return (
            render_template(
                "error.html",
                code=500,
                message="Terjadi kesalahan pada server. Silakan coba lagi.",
            ),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
