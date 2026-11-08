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
    """Tentukan jawaban tiap soal berdasarkan jumlah opsi yang terisi."""
    grouped = {}
    for item in measurements:
        grouped.setdefault(item["question_no"], []).append(item)

    decisions = {}
    for question_no, items in grouped.items():
        ordered = sorted(items, key=lambda item: item["option_index"])
        filled = [item for item in ordered if item["ratio"] >= fill_ratio]
        if not filled:
            decisions[question_no] = {
                "status": "kosong",
                "student_answer": "-",
                "filled": [],
                "ratios": ordered,
                "top_ratio": max((item["ratio"] for item in ordered), default=0.0),
            }
        elif len(filled) > 1:
            decisions[question_no] = {
                "status": "ganda",
                "student_answer": "".join(item["option_label"] for item in filled),
                "filled": filled,
                "ratios": ordered,
                "top_ratio": max(item["ratio"] for item in filled),
            }
        else:
            item = filled[0]
            decisions[question_no] = {
                "status": "terisi",
                "student_answer": item["option_label"],
                "filled": filled,
                "ratios": ordered,
                "top_ratio": item["ratio"],
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
                "ratios": [],
                "top_ratio": 0.0,
            }
        student_answer = decision["student_answer"]
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
                "all_ratios": [
                    {
                        "label": item["option_label"],
                        "ratio": round(float(item["ratio"]), 4),
                        "raw": round(float(item["raw_ratio"]), 4),
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


def process_aligned_sheet(aligned, bubbles, key_map, n_questions, params):
    """Pipeline baca lengkap pada citra yang sudah diselaraskan."""
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
    binary, method_label = binarize(
        gray,
        params.get("threshold_method", "otsu"),
        params.get("adaptive_block_size", 31),
        params.get("adaptive_c", 15),
    )
    morph = apply_morphology(binary, params.get("morph_kernel", 3))
    measurements = measure_bubbles(morph, bubbles)
    # Pada lembar huruf, tanda lingkaran lebih tipis daripada bulatan yang
    # dihitamkan sehingga rasio tinta dikalikan faktor koreksi templat.
    gain = float(params.get("mark_gain", 1.0) or 1.0)
    if gain != 1.0:
        for item in measurements:
            item["ratio"] = float(min(1.0, max(0.0, item["ratio"] * gain)))
    decisions = decide_answers(measurements, float(params.get("fill_ratio", 0.40)))
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
    warning = quality_warning(gray, params.get("blur_threshold", 45.0))
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
