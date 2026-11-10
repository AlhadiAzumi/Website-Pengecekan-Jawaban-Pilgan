"""Pembacaan jawaban: thresholding, morfologi, analisis area piksel, penilaian."""
import cv2
import numpy as np

from core.alignment import blur_score


def _attr(item, name, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def binarize(gray, method="otsu", block_size=31, c=15):
    """Thresholding Otsu atau adaptive untuk pencahayaan tidak merata."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    if method == "adaptive":
        block_size = int(block_size)
        if block_size % 2 == 0:
            block_size += 1
        block_size = max(3, block_size)
        binary = cv2.adaptiveThreshold(
            blur,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            block_size,
            int(c),
        )
        return binary, f"adaptive (block {block_size}, C {int(c)})"
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary, "otsu"


def apply_morphology(binary, kernel_size=3):
    """Opening membuang bintik noise, closing menutup celah arsiran."""
    kernel_size = int(kernel_size)
    if kernel_size <= 1:
        return binary.copy()
    if kernel_size % 2 == 0:
        kernel_size += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=1)
    return closed


def _prepared_binary(image, params):
    """Biner + morfologi dengan parameter baca yang sama."""
    gray = (
        cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if image.ndim == 3
        else image.copy()
    )
    binary, label = binarize(
        gray,
        params.get("threshold_method", "otsu"),
        params.get("adaptive_block_size", 31),
        params.get("adaptive_c", 15),
    )
    return binary, apply_morphology(binary, params.get("morph_kernel", 3)), label


def _cancellation_bands(binary, reference_binary, x, y, radius):
    """Cari garis horizontal (tanda ``=``) pada tinta tambahan di sekitar bulatan.

    Tinta cetak lembar kosong dibuang dengan membandingkan hasil biner scan
    terhadap biner templat. Hanya coretan yang melewati sisi kiri dan kanan
    bulatan yang dihitung agar tanda silang (X) tidak ikut dianggap coretan.
    """
    radius = max(4.0, float(radius))
    half = int(np.ceil(2.6 * radius))
    height, width = binary.shape[:2]
    cx, cy = int(round(x)), int(round(y))
    x0, x1 = cx - half, cx + half + 1
    y0, y1 = cy - half, cy + half + 1
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(width, x1), min(height, y1)
    if sx1 <= sx0 or sy1 <= sy0:
        return []
    roi = binary[sy0:sy1, sx0:sx1]
    ref = reference_binary[sy0:sy1, sx0:sx1]

    # Toleransi kecil untuk selisih penyelarasan, tanpa menghapus coretan.
    dilate_size = max(3, int(round(radius * 0.18)) * 2 + 1)
    ref_mask = cv2.dilate(
        ref,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_size, dilate_size)),
        iterations=1,
    )
    extra = cv2.bitwise_and(roi, cv2.bitwise_not(ref_mask))
    if not extra.any():
        return []

    local_cx = cx - sx0
    local_cy = cy - sy0
    # Hanya periksa tinta di luar cincin bulatan. Bagian dalam bulatan yang
    # dihitamkan tidak boleh ikut membentuk komponen garis.
    annulus = np.zeros(roi.shape[:2], np.uint8)
    cv2.circle(annulus, (local_cx, local_cy), half, 255, -1)
    cv2.circle(
        annulus,
        (local_cx, local_cy),
        max(2, int(round(1.16 * radius))),
        0,
        -1,
    )
    extra = cv2.bitwise_and(extra, annulus)
    if not extra.any():
        return []

    close_w = max(3, int(round(radius * 0.18)) * 2 + 1)
    # Hanya menutup celah horizontal. Penutupan vertikal dapat menyatukan dua
    # garis "=" menjadi satu komponen tinggi yang lalu ditolak.
    extra = cv2.morphologyEx(
        extra, cv2.MORPH_CLOSE, np.ones((1, close_w), np.uint8)
    )
    open_w = max(4, int(round(radius * 0.35)))
    horizontal = cv2.morphologyEx(
        extra, cv2.MORPH_OPEN, np.ones((1, open_w), np.uint8)
    )

    count, _, stats, _ = cv2.connectedComponentsWithStats(horizontal, 8)
    min_width = max(3.0, 0.20 * radius)
    # Dua garis "=" dapat menyatu menjadi satu komponen tinggi setelah
    # thresholding + morfologi, jadi batas tinggi dibuat longgar.
    max_height = max(6.0, 1.70 * radius)
    min_area = max(4.0, 0.12 * radius)
    components = []
    for index in range(1, count):
        bx, by, bw, bh, area = stats[index]
        if bw < min_width or bh > max_height or area < min_area:
            continue
        component_y = by + bh / 2.0
        if abs(component_y - local_cy) > 0.85 * radius:
            continue
        components.append(
            {
                "x": int(bx),
                "y": int(by),
                "w": int(bw),
                "h": int(bh),
                "cy": float(component_y),
            }
        )

    components.sort(key=lambda item: item["cy"])
    groups = []
    for component in components:
        if not groups:
            groups.append([component])
            continue
        previous_y = sum(item["cy"] for item in groups[-1]) / len(groups[-1])
        tolerance = max(4.0, 0.40 * radius)
        if component["cy"] - previous_y > tolerance:
            groups.append([component])
        else:
            groups[-1].append(component)

    bands = []
    for group in groups:
        left = any(item["x"] + item["w"] <= local_cx for item in group)
        right = any(item["x"] >= local_cx for item in group)
        if not (left and right):
            continue
        span = max(item["x"] + item["w"] for item in group) - min(
            item["x"] for item in group
        )
        # Coretan "=" harus lebih lebar dari diameter bulatan agar potongan
        # lingkaran tipis tidak salah dianggap pembatalan.
        if span < 2.0 * radius:
            continue
        bands.append(float(span))
    return bands


def detect_cancellations(
    binary,
    reference_binary,
    measurements,
    radius_scale=1.0,
    require_two_bands=False,
):
    """Tandai tiap bulatan yang dicoret dengan garis ``=``.

    Satu garis horizontal panjang yang melewati bulatan juga dianggap
    pembatalan. Pada lembar huruf, ``require_two_bands`` diaktifkan agar hanya
    tanda ``=`` (dua garis sejajar) yang dianggap pembatalan; ini mencegah
    lingkaran jawaban terbaca sebagai coretan.
    """
    if reference_binary is None:
        return measurements
    for item in measurements:
        bands = _cancellation_bands(
            binary,
            reference_binary,
            item["x"],
            item["y"],
            item["radius"] * radius_scale,
        )
        item["cancel_marks"] = len(bands)
        if require_two_bands:
            canceled = len(bands) >= 2
        else:
            canceled = bool(
                len(bands) >= 2
                or (
                    len(bands) == 1
                    and bands[0] >= 2.2 * max(4.0, item["radius"] * radius_scale)
                )
            )
        item["canceled"] = canceled
    return measurements


def _bubble_ratio(binary, x, y, radius, inner_scale=1.0):
    radius = max(2.0, float(radius) * inner_scale)
    half = int(np.ceil(radius)) + 1
    height, width = binary.shape[:2]
    cx, cy = int(round(x)), int(round(y))
    x0, x1 = max(0, cx - half), min(width, cx + half + 1)
    y0, y1 = max(0, cy - half), min(height, cy + half + 1)
    if x1 <= x0 or y1 <= y0:
        return 0.0, 0
    roi = binary[y0:y1, x0:x1]
    mask = np.zeros(roi.shape[:2], np.uint8)
    local_center = (cx - x0, cy - y0)
    cv2.circle(mask, local_center, int(round(radius)), 255, -1)
    total = int(cv2.countNonZero(mask))
    if total <= 0:
        return 0.0, 0
    white = int(cv2.countNonZero(cv2.bitwise_and(roi, roi, mask=mask)))
    return white / float(total), white


def measure_bubbles(binary, bubbles, inner_scale=1.0):
    """Ukur rasio piksel putih di dalam mask setiap bulatan."""
    measurements = []
    for bubble in bubbles:
        raw, white = _bubble_ratio(
            binary,
            float(_attr(bubble, "x")),
            float(_attr(bubble, "y")),
            float(_attr(bubble, "radius")),
            inner_scale,
        )
        blank = _attr(bubble, "blank_ratio", 0.0) or 0.0
        if 0.0 < blank < 0.95:
            corrected = (raw - blank) / max(1e-6, 1.0 - blank)
        else:
            corrected = raw
        corrected = float(min(1.0, max(0.0, corrected)))
        measurements.append(
            {
                "question_no": int(_attr(bubble, "question_no")),
                "option_index": int(_attr(bubble, "option_index")),
                "option_label": _attr(bubble, "option_label"),
                "x": float(_attr(bubble, "x")),
                "y": float(_attr(bubble, "y")),
                "radius": float(_attr(bubble, "radius")),
                "raw_ratio": float(raw),
                "ratio": corrected,
                "white_pixels": white,
            }
        )
    return measurements


def decide_answers(measurements, fill_ratio=0.40):
    """Tentukan jawaban tiap soal berdasarkan opsi terisi dan coretan ``=``.

    Opsi yang dicoret tidak dihitung. Jika dua opsi terisi tetapi salah satunya
    dicoret, jawaban diambil dari opsi yang tersisa. Jawaban ganda sejati tetap
    diberi status ``ganda`` dan dianggap belum dijawab saat penilaian.
    """
    grouped = {}
    for item in measurements:
        grouped.setdefault(item["question_no"], []).append(item)

    decisions = {}
    for question_no, items in grouped.items():
        ordered = sorted(items, key=lambda item: item["option_index"])
        filled = [item for item in ordered if item["ratio"] >= fill_ratio]
        canceled = [item for item in filled if item.get("canceled")]
        remaining = [item for item in filled if not item.get("canceled")]
        canceled_labels = [item["option_label"] for item in canceled]

        if not filled:
            decisions[question_no] = {
                "status": "kosong",
                "student_answer": "-",
                "filled": [],
                "canceled": [],
                "canceled_labels": [],
                "ratios": ordered,
                "top_ratio": max((item["ratio"] for item in ordered), default=0.0),
            }
        elif len(remaining) == 1:
            item = remaining[0]
            decisions[question_no] = {
                "status": "terisi",
                "student_answer": item["option_label"],
                "filled": filled,
                "canceled": canceled,
                "canceled_labels": canceled_labels,
                "ratios": ordered,
                "top_ratio": item["ratio"],
            }
        elif not remaining:
            # Semua opsi yang terisi dicoret: soal dianggap tidak dijawab.
            decisions[question_no] = {
                "status": "kosong",
                "student_answer": "-",
                "filled": filled,
                "canceled": canceled,
                "canceled_labels": canceled_labels,
                "ratios": ordered,
                "top_ratio": max(
                    (item["ratio"] for item in filled), default=0.0
                ),
            }
        else:
            decisions[question_no] = {
                "status": "ganda",
                "student_answer": "".join(
                    item["option_label"] for item in remaining
                ),
                "filled": filled,
                "canceled": canceled,
                "canceled_labels": canceled_labels,
                "ratios": ordered,
                "top_ratio": max(item["ratio"] for item in remaining),
            }
    return decisions


def score_decisions(decisions, key_map, n_questions):
    """Bandingkan jawaban siswa dengan kunci dan hitung rekap nilai."""
    details = []
    correct = wrong = empty = double = 0
    for question_no in range(1, n_questions + 1):
        decision = decisions.get(question_no)
        key_answer = key_map.get(question_no)
        if decision is None:
            decision = {
                "status": "kosong",
                "student_answer": "-",
                "filled": [],
                "canceled": [],
                "canceled_labels": [],
                "ratios": [],
                "top_ratio": 0.0,
            }
        student_answer = decision["student_answer"]
        canceled_labels = decision.get("canceled_labels", [])
        if decision["status"] == "kosong":
            status = "kosong"
            empty += 1
        elif decision["status"] == "ganda":
            status = "ganda"
            double += 1
        elif student_answer == key_answer:
            status = "benar"
            correct += 1
        else:
            status = "salah"
            wrong += 1
        details.append(
            {
                "question_no": question_no,
                "student_answer": student_answer,
                "correct_answer": key_answer,
                "status": status,
                "ratio": float(decision.get("top_ratio", 0.0)),
                "canceled_labels": canceled_labels,
                "all_ratios": [
                    {
                        "label": item["option_label"],
                        "ratio": round(float(item["ratio"]), 4),
                        "raw": round(float(item["raw_ratio"]), 4),
                        "canceled": bool(item.get("canceled")),
                    }
                    for item in decision.get("ratios", [])
                ],
                "filled": decision.get("filled", []),
                "ratios": decision.get("ratios", []),
            }
        )
    score = correct / float(n_questions) * 100.0 if n_questions else 0.0
    return {
        "details": details,
        "correct": correct,
        "wrong": wrong,
        "empty": empty,
        "double": double,
        "score": score,
    }


def _scale(image):
    return max(0.55, image.shape[1] / 1131.0)


def annotate_sheet(aligned, measurements, details, correct, wrong, empty, double, score):
    """Beri tanda hasil: hijau benar, merah salah, kuning kosong/ganda."""
    output = aligned.copy()
    scale = _scale(aligned)
    by_question = {}
    for item in measurements:
        by_question.setdefault(item["question_no"], {})[item["option_index"]] = item

    for detail in details:
        items = by_question.get(detail["question_no"], {})
        status = detail["status"]
        if status == "benar":
            for item in items.values():
                if item["option_label"] == detail["student_answer"]:
                    cv2.circle(
                        output,
                        (int(item["x"]), int(item["y"])),
                        int(item["radius"] * 1.25),
                        (0, 165, 0),
                        max(2, int(round(3 * scale))),
                        cv2.LINE_AA,
                    )
        elif status == "salah":
            for item in items.values():
                if item["option_label"] == detail["student_answer"]:
                    cv2.circle(
                        output,
                        (int(item["x"]), int(item["y"])),
                        int(item["radius"] * 1.25),
                        (0, 0, 220),
                        max(2, int(round(3 * scale))),
                        cv2.LINE_AA,
                    )
            # Tandai posisi kunci dengan garis biru tipis agar mudah dibandingkan.
            for item in items.values():
                if item["option_label"] == detail["correct_answer"]:
                    cv2.drawMarker(
                        output,
                        (int(item["x"]), int(item["y"] - item["radius"] * 1.6)),
                        (220, 110, 0),
                        cv2.MARKER_TRIANGLE_DOWN,
                        max(8, int(round(12 * scale))),
                        max(1, int(round(2 * scale))),
                    )
        elif status == "kosong":
            for item in items.values():
                if item["option_label"] == detail["correct_answer"]:
                    cv2.circle(
                        output,
                        (int(item["x"]), int(item["y"])),
                        int(item["radius"] * 1.25),
                        (0, 215, 255),
                        max(2, int(round(3 * scale))),
                        cv2.LINE_AA,
                    )
        else:
            for item in items.values():
                if item["ratio"] >= 0.0 and item in detail.get("filled", []):
                    cv2.circle(
                        output,
                        (int(item["x"]), int(item["y"])),
                        int(item["radius"] * 1.25),
                        (0, 215, 255),
                        max(2, int(round(3 * scale))),
                        cv2.LINE_AA,
                    )

        # Opsi yang dicoret dengan tanda "=" diberi penanda oranye.
        canceled_labels = set(detail.get("canceled_labels") or [])
        for item in items.values():
            if item["option_label"] not in canceled_labels:
                continue
            center = (int(item["x"]), int(item["y"]))
            box = int(item["radius"] * 1.4)
            cv2.rectangle(
                output,
                (center[0] - box, center[1] - box),
                (center[0] + box, center[1] + box),
                (0, 140, 255),
                max(1, int(round(2 * scale))),
                cv2.LINE_AA,
            )
            cv2.putText(
                output,
                "=",
                (center[0] + box + int(3 * scale), center[1] + int(5 * scale)),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.5, 0.8 * scale),
                (0, 140, 255),
                max(1, int(round(2 * scale))),
                cv2.LINE_AA,
            )

        # Jawaban ganda sejati diberi keterangan jelas di lembar.
        if status == "ganda":
            candidates = detail.get("filled") or []
            if candidates:
                anchor = min(candidates, key=lambda item: (item["y"], item["x"]))
                text = "GANDA"
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = max(0.45, 0.62 * scale)
                thickness = max(1, int(round(2 * scale)))
                text_x = int(anchor["x"] - anchor["radius"] * 1.1)
                text_y = int(anchor["y"] - anchor["radius"] * 1.9)
                text_y = max(int(18 * scale), text_y)
                cv2.putText(
                    output,
                    text,
                    (text_x, text_y),
                    font,
                    font_scale,
                    (255, 255, 255),
                    thickness + 3,
                    cv2.LINE_AA,
                )
                cv2.putText(
                    output,
                    text,
                    (text_x, text_y),
                    font,
                    font_scale,
                    (0, 80, 230),
                    thickness,
                    cv2.LINE_AA,
                )

    panel_w = int(430 * scale)
    panel_h = int(78 * scale)
    cv2.rectangle(output, (8, 8), (8 + panel_w, 8 + panel_h), (255, 255, 255), -1)
    cv2.rectangle(output, (8, 8), (8 + panel_w, 8 + panel_h), (180, 180, 180), 1)
    font_scale = max(0.45, 0.72 * scale)
    thickness = max(1, int(round(2 * scale)))
    cv2.putText(
        output,
        f"Benar {correct}  Salah {wrong}  Kosong {empty}  Ganda {double}",
        (18, int(8 + 26 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale * 0.78,
        (30, 30, 30),
        thickness,
        cv2.LINE_AA,
    )
    cv2.putText(
        output,
        f"Nilai {score:.1f}",
        (18, int(8 + 60 * scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        (20, 20, 20),
        thickness + 1,
        cv2.LINE_AA,
    )
    return output


def quality_warning(gray, threshold=45.0):
    score = blur_score(gray)
    if score < float(threshold):
        return f"Foto terlihat buram (skor ketajaman {score:.0f}). Hasil baca mungkin kurang akurat."
    return None


def process_aligned_sheet(
    aligned, bubbles, key_map, n_questions, params, reference=None
):
    """Pipeline baca lengkap pada citra yang sudah diselaraskan.

    ``reference`` adalah citra templat kosong. Jika diberikan, tinta tambahan
    dibandingkan dengan templat untuk mendeteksi coretan pembatalan ``=``.
    """
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    binary, morph, method_label = _prepared_binary(aligned, params)
    measurements = measure_bubbles(morph, bubbles)
    # Pada lembar huruf, tanda lingkaran lebih tipis daripada bulatan yang
    # dihitamkan sehingga rasio tinta dikalikan faktor koreksi templat.
    gain = float(params.get("mark_gain", 1.0) or 1.0)
    if gain != 1.0:
        for item in measurements:
            item["ratio"] = float(min(1.0, max(0.0, item["ratio"] * gain)))
    reference_binary = None
    if reference is not None:
        if reference.shape[:2] != aligned.shape[:2]:
            reference = cv2.resize(
                reference, (aligned.shape[1], aligned.shape[0])
            )
        reference_binary, _, _ = _prepared_binary(reference, params)
        detect_cancellations(
            binary,
            reference_binary,
            measurements,
            require_two_bands=params.get("cell_mode", "bubble") == "letter",
        )
    decisions = decide_answers(
        measurements, float(params.get("fill_ratio", 0.40))
    )
    scored = score_decisions(decisions, key_map, n_questions)
    annotated = annotate_sheet(
        aligned,
        measurements,
        scored["details"],
        scored["correct"],
        scored["wrong"],
        scored["empty"],
        scored["double"],
        scored["score"],
    )
    warning = quality_warning(
        gray,
        params.get("blur_threshold", 45.0),
    )
    return {
        "gray": gray,
        "binary": binary,
        "morph": morph,
        "measurements": measurements,
        "decisions": decisions,
        "annotated": annotated,
        "threshold_label": method_label,
        "quality_warning": warning,
        **scored,
    }


def measure_blank_baseline(reference, bubbles, params):
    """Hitung rasio tinta bawaan (garis/ huruf) pada lembar kosong."""
    gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    binary, _ = binarize(
        gray,
        params.get("threshold_method", "otsu"),
        params.get("adaptive_block_size", 31),
        params.get("adaptive_c", 15),
    )
    morph = apply_morphology(binary, params.get("morph_kernel", 3))
    measurements = measure_bubbles(morph, bubbles)
    return {
        (item["question_no"], item["option_index"]): item["raw_ratio"]
        for item in measurements
    }
