"""Pembacaan jawaban: thresholding, morfologi, analisis area piksel, penilaian."""
import math

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


# Gaya tanda yang diterima pada tiap mode instruksi. Mode "semua" sengaja
# tidak masuk daftar: semua bentuk tanda tetap diterima seperti sebelumnya.
SHAPE_ACCEPT = {
    "silang": {"silang"},
    "bulat": {"lingkar"},
    "bulat_hitam": {"hitam"},
}
SHAPE_LABEL = {
    "silang": "silang (X)",
    "lingkar": "lingkaran",
    "hitam": "hitam penuh",
    "lain": "tidak dikenal",
}


def _accepted_shape_label(mark_style):
    accepted = SHAPE_ACCEPT.get(str(mark_style or "")) or set()
    first = next(iter(accepted), "")
    return SHAPE_LABEL.get(first, str(mark_style or ""))


def _render_mark_mask(size, shape, cx, cy, radius, dx=0, dy=0):
    """Buat pola ideal X, lingkaran, bulatan hitam, atau setengah lingkaran."""
    mask = np.zeros(size, np.uint8)
    cx, cy = int(round(cx + dx)), int(round(cy + dy))
    thickness = max(2, int(round(radius * 0.20)))
    ring_radius = max(4, int(round(radius * 0.82)))
    if shape == "silang":
        span = max(4, int(round(radius * 0.70)))
        cv2.line(mask, (cx - span, cy - span), (cx + span, cy + span), 255, thickness, cv2.LINE_AA)
        cv2.line(mask, (cx - span, cy + span), (cx + span, cy - span), 255, thickness, cv2.LINE_AA)
    elif shape == "lingkar":
        cv2.circle(mask, (cx, cy), ring_radius, 255, thickness, cv2.LINE_AA)
    elif shape == "hitam":
        cv2.circle(mask, (cx, cy), ring_radius, 255, -1, cv2.LINE_AA)
    elif shape == "setengah":
        cv2.ellipse(mask, (cx, cy), (ring_radius, ring_radius), 0, 0, 180, 255, -1, cv2.LINE_AA)
    return mask


def _mark_shape_at(binary, reference_binary, x, y, radius, ink_ratio=None):
    """Kenali bentuk coretan dengan mencocokkan tinta tambahan ke pola ideal.

    Tinta cetak (cincin bulatan atau huruf opsi) dibuang lebih dulu memakai
    templat kosong. Tinta sisanya dibandingkan dengan pola X, lingkaran, dan
    bulatan hitam memakai jarak chamfer dua arah, sehingga ketebalan pensil dan
    sedikit pergeseran hasil penyelarasan tidak terlalu berpengaruh.
    """
    radius = max(4.0, float(radius))
    cx, cy = float(x), float(y)
    half = int(np.ceil(1.7 * radius)) + 4
    height, width = binary.shape[:2]
    x0, x1 = max(0, int(cx) - half), min(width, int(cx) + half + 1)
    y0, y1 = max(0, int(cy) - half), min(height, int(cy) + half + 1)
    if x1 <= x0 or y1 <= y0:
        return "lain"

    roi = binary[y0:y1, x0:x1]
    reference = cv2.dilate(
        reference_binary[y0:y1, x0:x1],
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        iterations=1,
    )
    extra = cv2.bitwise_and(roi, cv2.bitwise_not(reference))
    if int(np.count_nonzero(extra)) < 8:
        return "lain"

    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance = np.hypot(xx - cx, yy - cy)
    angles = (np.arctan2(yy - cy, xx - cx) + 2.0 * math.pi) % (2.0 * math.pi)
    sectors = np.floor((angles + math.pi / 8.0) / (math.pi / 4.0)).astype(int) % 8
    core = distance <= 0.45 * radius
    core_area = max(1, int(np.count_nonzero(core)))
    core_ratio = float(np.count_nonzero(extra[core])) / core_area
    # Templat cetak memuat huruf opsi di tengah bulatan. Pengurangan templat
    # ikut menghilangkan tengah tanda yang benar-benar dihitamkan, sehingga
    # ``extra`` tampak seperti cincin. Untuk membedakannya dari lingkaran,
    # kepenuhan tengah diukur langsung pada citra scan.
    raw_core = float(np.count_nonzero(roi[core])) / core_area
    annulus = (distance >= 0.50 * radius) & (distance <= 1.30 * radius)
    band = annulus & (extra > 0)
    diagonal_ratio = float(
        np.count_nonzero(band & np.isin(sectors, (1, 3, 5, 7)))
    ) / float(max(1, int(np.count_nonzero(band))))
    # Pengurangan templat bisa mengubah tanda hitam penuh menjadi pola cincin
    # atau X. Karena itu bentuk X diukur dari tinta asli hasil scan, bukan dari
    # sisa pengurangan. Tanda X menumpahkan tinta di sektor diagonal dan hampir
    # kosong di sektor samping. Pengukuran dilakukan juga pada cincin luar agar
    # huruf opsi cetak di tengah tidak ikut menutup celah sektor tersebut.
    diagonal_sectors = np.isin(sectors, (1, 3, 5, 7))
    cardinal_sectors = np.isin(sectors, (0, 2, 4, 6))

    def ink_counts_in(mask):
        pixels = mask & (roi > 0)
        diagonal = int(np.count_nonzero(pixels & diagonal_sectors))
        cardinal = int(np.count_nonzero(pixels & cardinal_sectors))
        return diagonal, cardinal

    diagonal_ink, cardinal_ink = ink_counts_in(annulus)
    outer_diag, outer_card = ink_counts_in(
        (distance >= 0.80 * radius) & (distance <= 1.30 * radius)
    )
    outer2_diag, outer2_card = ink_counts_in(
        (distance >= 0.90 * radius) & (distance <= 1.30 * radius)
    )

    # Celah tiga sektor berturut-turut yang nyaris kosong juga ciri khas X.
    # Bulatan hitam tetap mengisi sektor tersebut meski tinta scan sedikit
    # timpang, jadi pemeriksaan ini mencegah bulatan hitam salah ditolak.
    sector_counts = np.array(
        [
            int(np.count_nonzero(annulus & (roi > 0) & (sectors == sector)))
            for sector in range(8)
        ],
        dtype=np.float64,
    )
    total_sector_ink = max(float(sector_counts.sum()), 1.0)
    min_wedge = min(
        float(sector_counts[i] + sector_counts[(i + 1) % 8] + sector_counts[(i + 2) % 8])
        / total_sector_ink
        for i in range(8)
    )
    x_like = diagonal_ink > 0 and (
        cardinal_ink / float(diagonal_ink) < 0.50
        or (
            outer_diag > 0
            and outer2_diag > 0
            and outer_card / float(outer_diag) < 0.55
            and outer2_card / float(outer2_diag) < 0.55
            and min_wedge < 0.15
        )
    )
    # Citra hasil scan membuat tengah bulatan hitam tampak lebih terang daripada
    # simulasi, jadi ambang kepenuhan tengah sengaja direndahkan. Rasio tinta
    # total dipakai untuk memisahkan lingkaran tipis dari bulatan yang benar
    # benar dihitamkan pada hasil pemindaian.
    heavy_ink = ink_ratio is None or ink_ratio >= 0.60
    filled_center = raw_core >= 0.30 and not x_like and heavy_ink

    local_x, local_y = cx - x0, cy - y0
    dist_to_extra = cv2.distanceTransform(
        cv2.bitwise_not(extra), cv2.DIST_L2, 3
    )
    extra_pixels = extra > 0
    scores = {}
    shift = max(1, int(round(radius * 0.16)))
    for shape in ("silang", "lingkar", "hitam", "setengah"):
        best = float("inf")
        for dx in range(-shift, shift + 1):
            for dy in range(-shift, shift + 1):
                ideal = _render_mark_mask(
                    roi.shape, shape, local_x, local_y, radius, dx, dy
                )
                ideal = cv2.bitwise_and(ideal, cv2.bitwise_not(reference))
                ideal_pixels = ideal > 0
                if int(np.count_nonzero(ideal_pixels)) < 4:
                    continue
                dist_to_ideal = cv2.distanceTransform(
                    cv2.bitwise_not(ideal), cv2.DIST_L2, 3
                )
                score = float(
                    np.asarray(dist_to_ideal[extra_pixels], dtype=np.float64).mean()
                    + np.asarray(dist_to_extra[ideal_pixels], dtype=np.float64).mean()
                )
                best = min(best, score)
        scores[shape] = best

    # Setengah lingkaran bukan instruksi yang didukung, tapi dipakai sebagai
    # pembanding agar tanda setengah isi tidak ikut diterima sebagai bulat.
    best = min(scores, key=scores.get)
    if best == "setengah":
        return "lain"
    # Ciri X paling kuat ada pada tinta asli: empat sektor diagonal penuh,
    # empat sektor samping nyaris kosong. Ini mengalahkan kemiripan chamfer,
    # karena penghapusan templat sering membuat X tampak seperti bulatan penuh.
    if x_like:
        return "silang"
    if best == "silang" and diagonal_ratio < 0.55:
        # Lingkaran yang sedikit miring kadang lebih mirip X pada jarak chamfer.
        fallback = [
            shape for shape in ("lingkar", "hitam") if scores[shape] < float("inf")
        ]
        if fallback:
            best = min(fallback, key=lambda shape: scores[shape])
    # Pola setengah isi hampir selalu bersaing ketat dengan bulatan penuh pada
    # jarak chamfer. Bulatan hitam asli jauh lebih cocok ke pola hitam.
    if (
        filled_center
        and best in ("hitam", "lingkar")
        and scores["setengah"] <= scores["hitam"] + 0.25
    ):
        return "lain"
    if best == "lingkar" and filled_center:
        # Chamfer melihat sisa tinta setelah templat dibuang, sehingga bulatan
        # hitam yang tengahnya tertutup huruf cetak tampak seperti cincin.
        best = "hitam"
    if best == "hitam" and not filled_center:
        # Bagian tengah bulatan hitam penuh tinta. Lingkaran hanya mengisi
        # cincin luar, sedangkan tanda setengah isi hanya menutup separuh.
        if core_ratio < 0.30:
            best = "lingkar"
        elif core_ratio < 0.48:
            best = "lain"
    return best


def classify_mark_shapes(
    binary, reference_binary, measurements, mark_style="semua", fill_ratio=0.0
):
    """Isi ``mark_shape`` dan ``shape_ok`` pada tiap hasil pengukuran."""
    accepted = SHAPE_ACCEPT.get(str(mark_style or "semua"))
    if not accepted or reference_binary is None:
        for item in measurements:
            item["mark_shape"] = None
            item["shape_ok"] = True
        return measurements

    if reference_binary.shape[:2] != binary.shape[:2]:
        reference_binary = cv2.resize(
            reference_binary, (binary.shape[1], binary.shape[0])
        )
    for item in measurements:
        if fill_ratio and float(item.get("ratio", 0.0)) < fill_ratio:
            item["mark_shape"] = None
            item["shape_ok"] = True
            continue
        shape = _mark_shape_at(
            binary,
            reference_binary,
            item["x"],
            item["y"],
            item["radius"],
            ink_ratio=float(item.get("ratio", 0.0)),
        )
        item["mark_shape"] = shape
        item["shape_ok"] = shape in accepted
    return measurements


def decide_answers(measurements, fill_ratio=0.40, mark_style="semua"):
    """Tentukan jawaban tiap soal berdasarkan opsi terisi dan coretan ``=``.

    Opsi yang dicoret tidak dihitung. Pada mode instruksi khusus, tanda yang
    bentuknya tidak sesuai (misal lingkaran saat mode hanya silang) juga tidak
    dihitung dan soalnya diberi status salah. Jawaban ganda tetap diberi status
    ``ganda``; penilaian akhir dapat menerimanya bila kunci termasuk tanda
    dengan tinta terkuat.
    """
    strict = str(mark_style or "semua") in SHAPE_ACCEPT
    grouped = {}
    for item in measurements:
        grouped.setdefault(item["question_no"], []).append(item)

    decisions = {}
    for question_no, items in grouped.items():
        ordered = sorted(items, key=lambda item: item["option_index"])
        all_filled = [item for item in ordered if item["ratio"] >= fill_ratio]
        wrong_shape = (
            [item for item in all_filled if not item.get("shape_ok", True)]
            if strict
            else []
        )
        filled = (
            [item for item in all_filled if item.get("shape_ok", True)]
            if strict
            else all_filled
        )
        canceled = [item for item in filled if item.get("canceled")]
        remaining = [item for item in filled if not item.get("canceled")]
        canceled_labels = [item["option_label"] for item in canceled]
        shape_note = ""

        if not filled and wrong_shape:
            labels = [item["option_label"] for item in wrong_shape]
            shapes = sorted(
                {
                    SHAPE_LABEL.get(item.get("mark_shape"), "tanda tidak dikenal")
                    for item in wrong_shape
                }
            )
            shape_note = (
                "Tanda " + ", ".join(shapes) + " tidak sesuai instruksi "
                f"{_accepted_shape_label(mark_style)}; tidak dinilai benar."
            )
            decisions[question_no] = {
                "status": "salah",
                "student_answer": "".join(labels),
                "filled": wrong_shape,
                "canceled": [],
                "canceled_labels": [],
                "ratios": ordered,
                "top_ratio": max((item["ratio"] for item in wrong_shape), default=0.0),
                "shape_note": shape_note,
            }
            continue
        elif wrong_shape and remaining:
            ignored = ", ".join(item["option_label"] for item in wrong_shape)
            shape_note = f"Tanda pada opsi {ignored} tidak sesuai instruksi dan diabaikan."

        if not filled:
            decisions[question_no] = {
                "status": "kosong",
                "student_answer": "-",
                "filled": [],
                "canceled": [],
                "canceled_labels": [],
                "ratios": ordered,
                "top_ratio": max((item["ratio"] for item in ordered), default=0.0),
                "shape_note": shape_note,
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
                "shape_note": shape_note,
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
                "shape_note": shape_note,
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
                "shape_note": shape_note,
            }
    return decisions


def score_decisions(decisions, key_map, n_questions, mark_style="semua"):
    """Bandingkan jawaban siswa dengan kunci dan hitung rekap nilai.

    Pada mode ``bulat_hitam``, jawaban ganda tetap dihitung ganda kecuali kunci
    berada di antara tanda dengan tinta terkuat. Ini mencegah coretan tambahan
    yang jelas lebih lemah menggagalkan jawaban yang sebenarnya sudah tepat.
    """
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
        shape_note = decision.get("shape_note", "")
        if decision["status"] == "kosong":
            status = "kosong"
            empty += 1
        elif decision["status"] == "ganda":
            labels = set(student_answer)
            candidates = [
                item
                for item in decision.get("ratios", [])
                if item["option_label"] in labels and not item.get("canceled")
            ]
            key_ratios = [
                float(item["ratio"])
                for item in candidates
                if item["option_label"] == key_answer
            ]
            best_ratio = max(
                (float(item["ratio"]) for item in candidates), default=0.0
            )
            if (
                str(mark_style) == "bulat_hitam"
                and key_ratios
                and max(key_ratios) >= best_ratio - 0.20
            ):
                status = "benar"
                correct += 1
                shape_note = (
                    shape_note + "; " if shape_note else ""
                ) + "Jawaban ganda dengan kunci terkuat dinilai benar."
            else:
                status = "ganda"
                double += 1
        elif decision["status"] == "salah":
            status = "salah"
            wrong += 1
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
                "shape_note": shape_note,
                "all_ratios": [
                    {
                        "label": item["option_label"],
                        "ratio": round(float(item["ratio"]), 4),
                        "raw": round(float(item["raw_ratio"]), 4),
                        "canceled": bool(item.get("canceled")),
                        "shape": item.get("mark_shape"),
                        "shape_ok": bool(item.get("shape_ok", True)),
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

    # Nomor soal dicetak di sebelah kiri opsi pertama pada tiap blok. Posisi ini
    # dipakai untuk meletakkan keterangan "TANDA SALAH" di samping nomor, bukan
    # di atas pilihan supaya tidak menutupi coretan.
    first_x_by_question = {
        question_no: min(item["x"] for item in question_items.values())
        for question_no, question_items in by_question.items()
        if question_items
    }
    block_starts = sorted(set(first_x_by_question.values()))
    block_start_index = {
        question_no: min(
            range(len(block_starts)),
            key=lambda index: abs(block_starts[index] - first_x),
        )
        for question_no, first_x in first_x_by_question.items()
    }

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
            if detail.get("shape_note") and items:
                anchor = min(items.values(), key=lambda item: item["y"])
                first_item = min(items.values(), key=lambda item: item["x"])
                number_x = first_item["x"] - first_item["radius"] - max(
                    22, first_item["radius"] * 2.2
                )
                start_index = block_start_index.get(detail["question_no"], 0)
                if start_index and len(block_starts) > 1:
                    option_span = (
                        max(item["x"] for item in items.values()) - first_item["x"]
                    )
                    left_edge = (
                        block_starts[start_index - 1]
                        + option_span
                        + first_item["radius"]
                        + 8 * scale
                    )
                else:
                    left_edge = 16 * scale
                available_width = max(24 * scale, number_x - left_edge - 6 * scale)

                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = max(0.35, 0.48 * scale)
                thickness = max(1, int(round(1.5 * scale)))
                lines = ("TANDA", "SALAH")
                line_width = max(
                    cv2.getTextSize(line, font, font_scale, thickness)[0][0]
                    for line in lines
                )
                if line_width > available_width:
                    font_scale = max(
                        0.26 * scale, font_scale * available_width / line_width
                    )
                (line_w, line_h), _ = cv2.getTextSize(
                    lines[0], font, font_scale, thickness
                )
                text_x = int(number_x - line_w - 6 * scale)
                first_y = int(anchor["y"] - line_h * 0.5)
                for index, line in enumerate(lines):
                    text_y = first_y + index * int(line_h * 1.15)
                    cv2.putText(
                        output,
                        line,
                        (text_x, text_y),
                        font,
                        font_scale,
                        (0, 70, 220),
                        thickness + 2,
                        cv2.LINE_AA,
                    )
                    cv2.putText(
                        output,
                        line,
                        (text_x, text_y),
                        font,
                        font_scale,
                        (255, 255, 255),
                        thickness,
                        cv2.LINE_AA,
                    )
            # Kunci jawaban cukup diberi kotak biru tanpa panah penunjuk.
            for item in items.values():
                if item["option_label"] == detail["correct_answer"]:
                    center = (int(item["x"]), int(item["y"]))
                    box = int(item["radius"] * 1.25)
                    cv2.rectangle(
                        output,
                        (center[0] - box, center[1] - box),
                        (center[0] + box, center[1] + box),
                        (220, 110, 0),
                        max(2, int(round(3 * scale))),
                        cv2.LINE_AA,
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
    mark_style = str(params.get("mark_style", "semua") or "semua")
    fill_ratio = float(params.get("fill_ratio", 0.40))
    if mark_style in SHAPE_ACCEPT:
        classify_mark_shapes(
            binary, reference_binary, measurements, mark_style, fill_ratio
        )
    decisions = decide_answers(measurements, fill_ratio, mark_style)
    invalid_shape_count = sum(
        1 for decision in decisions.values() if decision.get("shape_note")
    )
    scored = score_decisions(
        decisions, key_map, n_questions, params.get("mark_style", "semua")
    )
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
        "invalid_shape_count": invalid_shape_count,
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
