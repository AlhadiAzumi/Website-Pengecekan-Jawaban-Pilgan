"""Deteksi bulatan jawaban pada citra templat kosong.

Tahapan:
- grayscale dan Gaussian blur
- thresholding (Otsu atau nilai manual)
- THRESH_BINARY_INV agar tinta menjadi putih
- findContours + filter luas, circularity, dan aspect ratio
- pengurutan grid: baris = nomor soal, kolom = opsi
"""
import math

import cv2
import numpy as np


def _cluster_1d(items, key, tolerance):
    """Kelompokkan item berdasarkan jarak nilai (1 dimensi)."""
    ordered = sorted(items, key=lambda item: item[key])
    clusters = []
    for item in ordered:
        if not clusters or abs(item[key] - clusters[-1][-1][key]) > tolerance:
            clusters.append([item])
        else:
            clusters[-1].append(item)
    return clusters


def _divisors(value):
    return [number for number in range(1, min(6, value) + 1) if value % number == 0]


def _deduplicate(candidates):
    candidates = sorted(candidates, key=lambda item: item["area"], reverse=True)
    kept = []
    for candidate in candidates:
        duplicate = False
        for other in kept:
            distance = math.hypot(candidate["x"] - other["x"], candidate["y"] - other["y"])
            if distance < max(candidate["radius"], other["radius"]) * 0.9:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


def _filter_dominant_size(candidates, tolerance=0.35):
    """Buang kandidat yang ukurannya jauh dari kelompok ukuran dominan.

    Bulatan jawaban berukuran seragam dan jumlahnya paling banyak. Logo, huruf
    berongga pada kop surat, atau ornamen lain biasanya jauh lebih kecil/besar
    sehingga dapat disaring dengan histogram radius.
    """
    if len(candidates) < 6:
        return candidates
    radii = np.array([item["radius"] for item in candidates], dtype=float)
    low = float(radii.min())
    high = float(radii.max())
    if high - low < 1e-6:
        return candidates
    median = float(np.median(radii))
    bin_width = max(1.0, median * 0.15)
    bins = max(1, int(math.ceil((high - low) / bin_width)))
    histogram, edges = np.histogram(radii, bins=bins, range=(low, high + 1e-6))
    peak = int(np.argmax(histogram))
    center = float((edges[peak] + edges[peak + 1]) / 2.0)
    lower = center * (1.0 - tolerance)
    upper = center * (1.0 + tolerance)
    kept = [item for item in candidates if lower <= item["radius"] <= upper]
    if len(kept) < max(6, int(len(candidates) * 0.3)):
        return candidates
    return kept


def _hough_candidates(gray, params):
    estimated_min = max(4, int(round(math.sqrt(float(params.get("min_area", 120)) / math.pi) * 0.6)))
    estimated_max = max(estimated_min + 2, int(round(math.sqrt(float(params.get("max_area", 4000)) / math.pi) * 1.1)))
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(12, estimated_min * 1.8),
        param1=100,
        param2=24,
        minRadius=estimated_min,
        maxRadius=estimated_max,
    )
    candidates = []
    if circles is None:
        return candidates
    for x, y, radius in np.round(circles[0]).astype("float32"):
        candidates.append(
            {
                "x": float(x),
                "y": float(y),
                "radius": float(radius),
                "area": float(math.pi * radius * radius),
                "source": "hough",
            }
        )
    return candidates


def _letter_line_rows(image_bgr, n_options, n_blocks, params):
    """Deteksi baris huruf opsi pada lembar yang tidak punya bulatan cetak.

    Lembar seperti ini hanya mencetak huruf A-E, lalu mahasiswa melingkari
    huruf. Nomor soal dipisahkan dari kolom jawaban oleh celah horizontal
    terbesar pada tiap baris, sehingga tiap blok menyisakan tepat n_options
    huruf jawaban.
    """
    gray = (
        cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        if image_bgr.ndim == 3
        else image_bgr.copy()
    )
    block_size = int(params.get("adaptive_block_size", 31) or 31)
    if block_size % 2 == 0:
        block_size += 1
    block_size = max(3, block_size)
    adaptive_c = int(params.get("adaptive_c", 15) or 0)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        adaptive_c,
    )
    contours, _ = cv2.findContours(
        binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    height, width = gray.shape[:2]
    glyphs = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        cx, cy = x + w / 2.0, y + h / 2.0
        if not (0.05 * width < cx < 0.98 * width and 0.10 * height < cy < 0.95 * height):
            continue
        if w < 2 or h < 2 or w > 80 or h > 80:
            continue
        glyphs.append(
            {
                "x": float(cx),
                "y": float(cy),
                "radius": max(w, h) / 2.0,
                "area": max(float(cv2.contourArea(contour)), 1.0),
                "source": "letter",
            }
        )

    glyphs.sort(key=lambda item: item["y"])
    clusters = []
    for glyph in glyphs:
        if not clusters or glyph["y"] - clusters[-1][-1]["y"] > 6:
            clusters.append([glyph])
        else:
            clusters[-1].append(glyph)

    target = n_blocks * n_options
    rows = []
    for cluster in clusters:
        cluster.sort(key=lambda item: item["x"])
        if len(cluster) < target:
            continue
        gaps = np.diff([item["x"] for item in cluster])
        if len(gaps) == 0:
            continue
        median_gap = float(np.median(gaps))
        splits = []
        for index in np.argsort(gaps)[::-1]:
            if len(splits) >= n_blocks - 1:
                break
            if gaps[index] > max(2.2 * median_gap, 55.0):
                splits.append(int(index))
        if len(splits) != n_blocks - 1:
            continue
        splits.sort()
        segments, start = [], 0
        for split in splits:
            segments.append(cluster[start : split + 1])
            start = split + 1
        segments.append(cluster[start:])

        cells, valid = [], True
        for segment in segments:
            if len(segment) < n_options:
                valid = False
                break
            cells.extend(segment[-n_options:])
        if valid:
            rows.append(cells)
    return rows


def _order_letter_grid(image_bgr, n_questions, n_options, blocks_to_try, params):
    """Susun huruf A-E menjadi grid soal x opsi (fallback lembar tanpa bulatan)."""
    for blocks in blocks_to_try:
        if blocks <= 0 or n_questions % blocks != 0:
            continue
        rows_per_block = n_questions // blocks
        rows = _letter_line_rows(image_bgr, n_options, blocks, params)
        if len(rows) < rows_per_block:
            continue
        selected = _select_row_grid(
            rows, n_questions, n_options, blocks, 7.0
        )
        if selected is None:
            continue
        bubbles = _build_from_rows(selected, n_questions, n_options, blocks)
        if bubbles is None or len(bubbles) != n_questions * n_options:
            continue

        ys = [float(np.mean([item["y"] for item in row])) for row in selected]
        gaps = np.diff(ys)
        row_step = float(np.median(gaps)) if len(gaps) else 0.0
        column_steps = []
        for block in range(blocks):
            columns = []
            for row in selected:
                ordered = sorted(row, key=lambda item: item["x"])
                chunk = ordered[block * n_options : (block + 1) * n_options]
                columns.append([item["x"] for item in chunk])
            medians = np.median(np.array(columns, dtype=float), axis=0)
            column_steps.extend(np.diff(medians).tolist())
        min_step = min(column_steps) if column_steps else row_step
        radius = max(6.0, min(row_step * 0.5, min_step * 0.42))
        for bubble in bubbles:
            bubble["radius"] = float(radius)
        return bubbles, blocks
    return None, None


def detect_bubble_candidates(image_bgr, params):
    """Kembalikan kandidat bulatan serta citra debug tiap tahap."""
    if image_bgr is None:
        raise ValueError("Citra templat tidak dapat dibaca.")

    gray = (
        cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
        if image_bgr.ndim == 3
        else image_bgr.copy()
    )
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    manual_threshold = int(params.get("detect_threshold", 0) or 0)
    if manual_threshold > 0:
        threshold_value = manual_threshold
        _, binary = cv2.threshold(
            blur, threshold_value, 255, cv2.THRESH_BINARY_INV
        )
    else:
        threshold_value, binary = cv2.threshold(
            blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )
        threshold_value = float(threshold_value)

    # Tutup celah kecil pada garis lingkaran agar kontur lebih utuh.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

    area_scale = (gray.shape[0] * gray.shape[1]) / float(1131 * 1600)
    min_area = max(8.0, float(params.get("min_area", 120)) * max(0.35, area_scale))
    max_area = max(min_area + 10.0, float(params.get("max_area", 4000)) * max(0.35, area_scale))
    min_circularity = float(params.get("circularity", 0.60))

    contours, hierarchy = cv2.findContours(
        closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    hierarchy = hierarchy[0] if hierarchy is not None else []

    candidates = []
    for index, contour in enumerate(contours):
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if w < 6 or h < 6:
            continue
        aspect = w / float(h)
        if not (0.62 <= aspect <= 1.62):
            continue
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        circularity = 4.0 * math.pi * area / (perimeter * perimeter)
        if circularity < min_circularity:
            continue
        has_hole = (
            index < len(hierarchy)
            and len(hierarchy[index]) > 2
            and hierarchy[index][2] != -1
        )
        if not has_hole:
            # Bulatan jawaban pada lembar kosong selalu berupa cincin (punya lubang).
            continue
        moments = cv2.moments(contour)
        if abs(moments["m00"]) < 1e-6:
            cx, cy = x + w / 2.0, y + h / 2.0
        else:
            cx = moments["m10"] / moments["m00"]
            cy = moments["m01"] / moments["m00"]
        radius = (w + h) / 4.0
        candidates.append(
            {
                "x": float(cx),
                "y": float(cy),
                "radius": float(radius),
                "area": float(area),
                "circularity": float(circularity),
                "source": "contour",
            }
        )

    candidates = _deduplicate(candidates)

    # Fallback bila filter kontur terlalu ketat atau kualitas gambar rendah.
    if len(candidates) < 10:
        hough = _deduplicate(_hough_candidates(gray, params))
        if len(hough) > len(candidates):
            candidates = hough

    # Seragamkan ukuran: abaikan logo/huruf kop surat yang ikut terdeteksi.
    candidates = _filter_dominant_size(candidates)

    preview = image_bgr.copy()
    for candidate in candidates:
        cv2.circle(
            preview,
            (int(candidate["x"]), int(candidate["y"])),
            int(candidate["radius"]),
            (0, 170, 0) if candidate["source"] == "contour" else (200, 120, 0),
            2,
            cv2.LINE_AA,
        )

    debug = {
        "grayscale": gray,
        "blur": blur,
        "threshold": closed,
        "candidates": preview,
        "threshold_value": threshold_value,
        "min_area": min_area,
        "max_area": max_area,
    }
    return candidates, debug


def _build_from_rows(rows, n_questions, n_options, n_blocks):
    rows_per_block = n_questions // n_blocks
    if len(rows) != rows_per_block:
        return None
    if any(len(row) != n_blocks * n_options for row in rows):
        return None

    bubbles = []
    for row_index, row in enumerate(rows):
        ordered = sorted(row, key=lambda item: item["x"])
        for block in range(n_blocks):
            chunk = ordered[block * n_options : (block + 1) * n_options]
            question_no = block * rows_per_block + row_index + 1
            for option_index, candidate in enumerate(chunk):
                bubbles.append(
                    {
                        "question_no": question_no,
                        "option_index": option_index,
                        "option_label": chr(ord("A") + option_index),
                        "x": candidate["x"],
                        "y": candidate["y"],
                        "radius": candidate["radius"],
                        "row_index": row_index,
                        "block_index": block,
                    }
                )
    return bubbles


def _row_y(row):
    return float(np.mean([item["y"] for item in row]))


def _row_xs(row):
    return sorted(float(item["x"]) for item in row)


def _grid_consistent(window, x_tolerance):
    """Pastikan sekumpulan baris membentuk grid yang rapi dan berjarak seragam."""
    if not window:
        return False
    reference = _row_xs(window[0])
    for row in window[1:]:
        xs = _row_xs(row)
        if len(xs) != len(reference):
            return False
        for expected, actual in zip(reference, xs):
            if abs(expected - actual) > x_tolerance:
                return False
    ys = [_row_y(row) for row in window]
    gaps = [ys[index + 1] - ys[index] for index in range(len(ys) - 1)]
    if gaps:
        if min(gaps) <= 0:
            return False
        mean_gap = float(np.mean(gaps))
        if max(gaps) / min(gaps) > 1.6:
            return False
        if (max(gaps) - min(gaps)) > max(8.0, mean_gap * 0.4):
            return False
    return True


def _grid_score(window):
    ys = [_row_y(row) for row in window]
    gaps = np.diff(ys)
    if len(gaps) == 0:
        return 0.0
    mean_gap = float(np.mean(gaps))
    if mean_gap <= 0:
        return float("inf")
    return float(np.std(gaps) / mean_gap)


def _select_row_grid(rows, n_questions, n_options, blocks, radius_tolerance):
    """Pilih subset baris yang membentuk grid jawaban, abaikan baris kop surat."""
    if blocks <= 0 or n_questions % blocks != 0:
        return None
    target = blocks * n_options
    rows_per_block = n_questions // blocks
    valid = [row for row in rows if len(row) == target]
    if len(valid) < rows_per_block:
        return None
    valid.sort(key=_row_y)
    x_tolerance = max(8.0, radius_tolerance * 1.2)
    best = None
    for start in range(len(valid) - rows_per_block + 1):
        window = valid[start : start + rows_per_block]
        if not _grid_consistent(window, x_tolerance):
            continue
        score = _grid_score(window)
        if best is None or score < best[0]:
            best = (score, window)
    return best[1] if best is not None else None


def _order_by_rows(candidates, n_questions, n_options, blocks_to_try, radius_tolerance):
    rows = _cluster_1d(candidates, "y", radius_tolerance)
    for blocks in blocks_to_try:
        selected = _select_row_grid(
            rows, n_questions, n_options, blocks, radius_tolerance
        )
        if selected is None:
            continue
        bubbles = _build_from_rows(selected, n_questions, n_options, blocks)
        if bubbles is not None and len(bubbles) == n_questions * n_options:
            return bubbles, blocks, rows
    return None, None, rows


def _build_from_columns(columns, n_questions, n_options, n_blocks, radius_tolerance):
    rows_per_block = n_questions // n_blocks
    bubbles = []
    for block in range(n_blocks):
        block_columns = columns[block * n_options : (block + 1) * n_options]
        block_candidates = [item for column in block_columns for item in column]
        rows = _cluster_1d(block_candidates, "y", radius_tolerance)
        if len(rows) != rows_per_block:
            return None
        if any(len(row) != n_options for row in rows):
            return None
        for row_index, row in enumerate(rows):
            ordered = sorted(row, key=lambda item: item["x"])
            question_no = block * rows_per_block + row_index + 1
            for option_index, candidate in enumerate(ordered):
                bubbles.append(
                    {
                        "question_no": question_no,
                        "option_index": option_index,
                        "option_label": chr(ord("A") + option_index),
                        "x": candidate["x"],
                        "y": candidate["y"],
                        "radius": candidate["radius"],
                        "row_index": row_index,
                        "block_index": block,
                    }
                )
    return bubbles


def _column_x(column):
    return float(np.mean([item["x"] for item in column]))


def _select_column_grid(columns, n_questions, n_options, blocks, radius_tolerance):
    """Pilih subset kolom yang membentuk grid jawaban."""
    if blocks <= 0 or n_questions % blocks != 0:
        return None
    rows_per_block = n_questions // blocks
    target = blocks * n_options
    valid = [column for column in columns if len(column) == rows_per_block]
    if len(valid) < target:
        return None
    valid.sort(key=_column_x)
    y_tolerance = max(8.0, radius_tolerance * 1.2)
    best = None
    for start in range(len(valid) - target + 1):
        window = valid[start : start + target]
        xs = [_column_x(column) for column in window]
        gaps = np.diff(xs)
        if len(gaps) and (min(gaps) <= 0 or max(gaps) / min(gaps) > 3.0):
            continue
        reference = sorted(float(item["y"]) for item in window[0])
        consistent = True
        for column in window[1:]:
            ys = sorted(float(item["y"]) for item in column)
            if len(ys) != len(reference) or any(
                abs(expected - actual) > y_tolerance
                for expected, actual in zip(reference, ys)
            ):
                consistent = False
                break
        if not consistent:
            continue
        score = float(np.std(gaps) / np.mean(gaps)) if len(gaps) else 0.0
        if best is None or score < best[0]:
            best = (score, window)
    return best[1] if best is not None else None


def _order_by_columns(candidates, n_questions, n_options, blocks_to_try, radius_tolerance):
    columns = _cluster_1d(candidates, "x", radius_tolerance)
    for blocks in blocks_to_try:
        selected = _select_column_grid(
            columns, n_questions, n_options, blocks, radius_tolerance
        )
        if selected is None:
            continue
        bubbles = _build_from_columns(
            selected, n_questions, n_options, blocks, radius_tolerance
        )
        if bubbles is not None and len(bubbles) == n_questions * n_options:
            return bubbles, blocks, columns
    return None, None, columns


def order_bubbles(candidates, n_questions, n_options, n_blocks=None):
    """Susun kandidat bulatan menjadi grid soal x opsi."""
    expected = n_questions * n_options
    result = {
        "bubbles": [],
        "expected": expected,
        "detected": len(candidates),
        "n_blocks": n_blocks,
        "strategy": None,
        "warnings": [],
        "rows_info": None,
    }
    if not candidates:
        result["warnings"].append(
            "Tidak ada bulatan yang terdeteksi. Turunkan threshold atau luas minimum."
        )
        return result

    radii = [item["radius"] for item in candidates]
    median_radius = float(np.median(radii)) if radii else 10.0
    radius_tolerance = max(7.0, median_radius * 1.35)

    if n_blocks:
        blocks_to_try = [int(n_blocks)]
    else:
        blocks_to_try = _divisors(n_questions)

    bubbles, used_blocks, rows = _order_by_rows(
        candidates, n_questions, n_options, blocks_to_try, radius_tolerance
    )
    strategy = "rows" if bubbles else None
    if bubbles is None:
        bubbles, used_blocks, columns = _order_by_columns(
            candidates, n_questions, n_options, blocks_to_try, radius_tolerance
        )
        strategy = "columns" if bubbles else None
        if bubbles is None:
            row_lengths = sorted({len(row) for row in rows})
            result["rows_info"] = row_lengths
            result["warnings"].append(
                f"Terdeteksi {len(candidates)} bulatan, seharusnya {expected}. "
                "Pola baris/kolom belum sesuai."
            )
            if row_lengths:
                result["warnings"].append(
                    "Jumlah bulatan per baris yang terdeteksi: "
                    + ", ".join(str(value) for value in row_lengths)
                    + f". Seharusnya kelipatan {n_options}."
                )
            result["warnings"].append(
                "Coba atur threshold, luas minimum, luas maksimum, atau circularity."
            )
            return result

    result["bubbles"] = bubbles
    result["n_blocks"] = used_blocks
    result["strategy"] = strategy
    if len(bubbles) != expected:
        result["warnings"].append(
            f"Jumlah bulatan tidak sesuai ({len(bubbles)} dari {expected})."
        )
    return result


def render_preview(
    image_bgr, bubbles, candidates=None, marker_positions=None, draw_labels=True
):
    preview = image_bgr.copy()
    if candidates and not bubbles:
        for candidate in candidates:
            cv2.circle(
                preview,
                (int(candidate["x"]), int(candidate["y"])),
                int(candidate["radius"]),
                (0, 160, 220),
                2,
                cv2.LINE_AA,
            )

    for bubble in bubbles:
        center = (int(round(bubble["x"])), int(round(bubble["y"])))
        radius = int(round(bubble["radius"]))
        cv2.circle(preview, center, radius, (0, 170, 0), 2, cv2.LINE_AA)
        if draw_labels:
            cv2.putText(
                preview,
                bubble["option_label"],
                (center[0] - max(4, radius // 2), center[1] + max(4, radius // 2)),
                cv2.FONT_HERSHEY_SIMPLEX,
                max(0.3, radius / 34.0),
                (0, 130, 0),
                1,
                cv2.LINE_AA,
            )

    if draw_labels:
        seen = set()
        for bubble in bubbles:
            key = (bubble["block_index"], bubble["row_index"])
            if key in seen:
                continue
            seen.add(key)
            first = min(
                (item for item in bubbles if (item["block_index"], item["row_index"]) == key),
                key=lambda item: item["x"],
            )
            cv2.putText(
                preview,
                str(bubble["question_no"]),
                (int(first["x"] - first["radius"] - 24), int(first["y"] + 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (150, 40, 40),
                1,
                cv2.LINE_AA,
            )

    if marker_positions:
        for marker in marker_positions:
            cv2.drawMarker(
                preview,
                (int(marker["x"]), int(marker["y"])),
                (180, 0, 180),
                cv2.MARKER_CROSS,
                18,
                2,
            )

    cv2.rectangle(preview, (0, 0), (preview.shape[1] - 1, preview.shape[0] - 1), (220, 220, 220), 1)
    return preview


def detect_template(image_bgr, n_questions, n_options, n_blocks, params):
    """Pipeline lengkap deteksi templat dan pengurutan grid."""
    expected = n_questions * n_options
    candidates, debug = detect_bubble_candidates(image_bgr, params)
    ordered = order_bubbles(candidates, n_questions, n_options, n_blocks)
    cell_mode = "bubble"
    mark_gain = 1.0

    # Bila kontur gagal membentuk grid, coba kandidat HoughCircles sebagai cadangan.
    if len(ordered["bubbles"]) < expected:
        hough = _filter_dominant_size(
            _deduplicate(_hough_candidates(debug["grayscale"], params))
        )
        alternative = order_bubbles(hough, n_questions, n_options, n_blocks)
        if len(alternative["bubbles"]) > len(ordered["bubbles"]):
            candidates = hough
            ordered = alternative

    # Lembar tanpa bulatan cetak (mis. lembar UIN yang hanya mencetak huruf
    # A-E): pakai huruf sebagai sel jawaban. Nilai rasio tinta diperbesar
    # karena lingkaran pensil tidak pernah sepadat bulatan yang dihitamkan.
    if len(ordered["bubbles"]) < expected:
        blocks_to_try = (
            [int(n_blocks)] if n_blocks else _divisors(n_questions)
        )
        letter_bubbles, used_blocks = _order_letter_grid(
            image_bgr, n_questions, n_options, blocks_to_try, params
        )
        if letter_bubbles:
            ordered = {
                "bubbles": letter_bubbles,
                "expected": expected,
                "detected": len(letter_bubbles),
                "n_blocks": used_blocks,
                "strategy": "letters",
                "warnings": [],
                "rows_info": None,
            }
            cell_mode = "letter"
            mark_gain = 2.5

    preview = render_preview(
        image_bgr,
        ordered["bubbles"],
        candidates,
        draw_labels=cell_mode != "letter",
    )
    return {
        "candidates": candidates,
        "debug": debug,
        "preview": preview,
        "cell_mode": cell_mode,
        "mark_gain": mark_gain,
        **ordered,
        "success": len(ordered["bubbles"]) == expected,
    }
