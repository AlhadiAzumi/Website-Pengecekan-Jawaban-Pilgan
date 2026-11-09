"""Penyelarasan lembar jawaban terhadap citra templat.

Urutan metode pada mode otomatis:
1. Empat marker sudut  -> homography (paling akurat untuk lembar generator).
2. Empat sudut kertas  -> perspective transform.
3. ORB feature matching + homography.
4. Resize langsung (khusus gambar hasil scan yang sudah lurus).
"""
import cv2
import numpy as np

from config import CANONICAL_LONG_SIDE


def order_points(pts):
    """Urutkan 4 titik menjadi kiri-atas, kanan-atas, kanan-bawah, kiri-bawah."""
    pts = np.asarray(pts, dtype="float32").reshape(4, 2)
    rect = np.zeros((4, 2), dtype="float32")
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)
    rect[0] = pts[np.argmin(sums)]
    rect[2] = pts[np.argmax(sums)]
    rect[1] = pts[np.argmin(diffs)]
    rect[3] = pts[np.argmax(diffs)]
    return rect


def four_point_transform(image, pts, width, height):
    rect = order_points(pts)
    dst = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(
        image, matrix, (int(width), int(height)), borderValue=(255, 255, 255)
    )


def blur_score(gray):
    """Variance of Laplacian: nilai kecil menandakan gambar buram."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _resize_long_side(image, long_side):
    h, w = image.shape[:2]
    scale = long_side / float(max(h, w))
    if scale >= 1.0:
        return image.copy(), 1.0
    return (
        cv2.resize(image, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA),
        scale,
    )


def _edge_map(gray):
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blur, 60, 180)
    return cv2.dilate(edged, np.ones((3, 3), np.uint8), iterations=1)


def preprocess_debug(image):
    """Grayscale, blur, dan peta tepi citra asli untuk galeri tahapan."""
    resized, _ = _resize_long_side(image, 1000)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if resized.ndim == 3 else resized
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    return gray, blur, _edge_map(gray)


def detect_paper_corners(image):
    """Cari kontur kertas terbesar yang menyerupai segi empat."""
    resized, scale = _resize_long_side(image, 1000)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if resized.ndim == 3 else resized
    edged = _edge_map(gray)
    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:12]
    image_area = float(resized.shape[0] * resized.shape[1])
    outline = resized.copy()
    best = None
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < image_area * 0.18:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            best = approx
            break
    debug = {"edges": edged}
    if best is None:
        return None, debug
    cv2.drawContours(outline, [best], -1, (0, 200, 0), 4)
    debug["outline"] = outline
    corners = best.reshape(4, 2).astype("float32") / max(scale, 1e-6)
    return corners, debug


def _center_of(contour):
    moments = cv2.moments(contour)
    if abs(moments["m00"]) < 1e-6:
        x, y, w, h = cv2.boundingRect(contour)
        return float(x + w / 2.0), float(y + h / 2.0)
    return float(moments["m10"] / moments["m00"]), float(moments["m01"] / moments["m00"])


def detect_markers(image):
    """Deteksi marker kotak hitam dan kembalikan 4 titik terurut."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(gray.shape[0] * gray.shape[1])
    min_area = image_area * 0.00004
    max_area = image_area * 0.02
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area or area > max_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if h == 0 or w == 0:
            continue
        aspect = w / float(h)
        extent = area / float(w * h)
        if not (0.78 <= aspect <= 1.28):
            continue
        if extent < 0.82:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
        if len(approx) != 4:
            continue
        cx, cy = _center_of(contour)
        candidates.append(
            {
                "x": cx,
                "y": cy,
                "area": area,
                "size": float(max(w, h)),
                "contour": contour,
            }
        )

    if len(candidates) < 4:
        return []

    h, w = gray.shape[:2]
    for item in candidates:
        # jarak relatif ke sudut terdekat, dipakai untuk memilih 4 marker terluar
        item["corner_score"] = min(
            (item["x"] ** 2 + item["y"] ** 2) ** 0.5,
            ((w - item["x"]) ** 2 + item["y"] ** 2) ** 0.5,
            (item["x"] ** 2 + (h - item["y"]) ** 2) ** 0.5,
            ((w - item["x"]) ** 2 + (h - item["y"]) ** 2) ** 0.5,
        )
    candidates.sort(key=lambda item: item["corner_score"])
    chosen = candidates[:4]
    points = np.array([[item["x"], item["y"]] for item in chosen], dtype="float32")
    ordered = order_points(points)
    return [{"x": float(p[0]), "y": float(p[1])} for p in ordered]


def _valid_homography(matrix, src_shape, dst_w, dst_h):
    if matrix is None or not np.all(np.isfinite(matrix)):
        return False
    if abs(float(np.linalg.det(matrix))) < 1e-6:
        return False
    src_h, src_w = src_shape[:2]
    corners = np.array(
        [[0, 0], [src_w, 0], [src_w, src_h], [0, src_h]], dtype="float32"
    ).reshape(-1, 1, 2)
    transformed = cv2.perspectiveTransform(corners, matrix).reshape(4, 2)
    area = abs(cv2.contourArea(transformed.astype("float32")))
    target_area = float(dst_w * dst_h)
    return target_area * 0.15 <= area <= target_area * 8.0


def _warp(image, matrix, width, height):
    return cv2.warpPerspective(
        image,
        matrix,
        (int(width), int(height)),
        borderValue=(255, 255, 255),
    )


def _marker_warp(image, template_markers, template_shape):
    if not template_markers or len(template_markers) != 4:
        return None, None
    scan_markers = detect_markers(image)
    if len(scan_markers) != 4:
        return None, None
    src = np.array([[m["x"], m["y"]] for m in scan_markers], dtype="float32")
    dst = np.array(
        [[m["x"], m["y"]] for m in template_markers], dtype="float32"
    )
    src = order_points(src)
    dst = order_points(dst)
    h, w = template_shape[:2]
    matrix = cv2.getPerspectiveTransform(src, dst)
    if not _valid_homography(matrix, image.shape, w, h):
        return None, None
    debug = image.copy()
    for point in src:
        cv2.circle(debug, (int(point[0]), int(point[1])), 12, (0, 200, 0), 3)
    return _warp(image, matrix, w, h), debug


def _orb_warp(image, template_ref):
    gray_ref = cv2.cvtColor(template_ref, cv2.COLOR_BGR2GRAY)
    gray_img = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=2500)
    kp_ref, des_ref = orb.detectAndCompute(gray_ref, None)
    kp_img, des_img = orb.detectAndCompute(gray_img, None)
    if des_ref is None or des_img is None or len(kp_ref) < 10 or len(kp_img) < 10:
        return None, None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    knn = matcher.knnMatch(des_ref, des_img, k=2)
    good = []
    for pair in knn:
        if len(pair) < 2:
            continue
        first, second = pair
        if first.distance < 0.75 * second.distance:
            good.append(first)
    if len(good) < 12:
        return None, None
    src = np.array([kp_ref[m.queryIdx].pt for m in good], dtype="float32")
    dst = np.array([kp_img[m.trainIdx].pt for m in good], dtype="float32")
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    if matrix is None:
        return None, None
    inliers = int(mask.sum()) if mask is not None else 0
    if inliers < 12:
        return None, None
    try:
        inverse = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return None, None
    h, w = template_ref.shape[:2]
    if not _valid_homography(inverse, image.shape, w, h):
        return None, None
    debug = cv2.drawMatches(
        template_ref,
        kp_ref,
        image,
        kp_img,
        good[:60],
        None,
        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS,
    )
    return _warp(image, inverse, w, h), debug


def align_to_template(image, template_ref, template_markers=None, mode="auto"):
    """Selaraskan gambar siswa ke ukuran dan orientasi templat."""
    target_h, target_w = template_ref.shape[:2]
    steps = {}
    warnings = []
    wanted = (mode or "auto").lower()

    if wanted in ("auto", "marker") and template_markers:
        aligned, debug = _marker_warp(image, template_markers, template_ref.shape)
        if aligned is not None:
            steps["marker"] = debug
            return aligned, "marker", steps, warnings
        if wanted == "marker":
            warnings.append("Marker sudut tidak terdeteksi.")

    if wanted in ("auto", "paper"):
        corners, debug = detect_paper_corners(image)
        steps.update(debug)
        if corners is not None:
            aligned = four_point_transform(image, corners, target_w, target_h)
            return aligned, "paper", steps, warnings
        if wanted == "paper":
            warnings.append("Sudut kertas tidak terdeteksi.")

    if wanted in ("auto", "orb"):
        aligned, debug = _orb_warp(image, template_ref)
        if aligned is not None:
            steps["orb"] = debug
            return aligned, "orb", steps, warnings
        if wanted == "orb":
            warnings.append("ORB gagal menemukan kecocokan yang cukup.")

    if wanted in ("auto", "resize"):
        resized = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)
        warnings.append(
            "Penyelarasan otomatis gagal; gambar hanya diperkecil. "
            "Pastikan seluruh lembar terlihat atau gunakan mode scan lurus."
        )
        return resized, "resize", steps, warnings

    raise ValueError(
        "Gambar tidak dapat diselaraskan dengan templat. "
        "Pastikan marker/sudut kertas terlihat jelas."
    )


def prepare_reference(image):
    """Rektifikasi citra templat kosong dan deteksi marker acuannya."""
    resized, scale = _resize_long_side(image, 1800)
    corners, debug = detect_paper_corners(resized)
    if corners is not None:
        rect = order_points(corners)
        width = max(np.linalg.norm(rect[0] - rect[1]), np.linalg.norm(rect[2] - rect[3]))
        height = max(np.linalg.norm(rect[0] - rect[3]), np.linalg.norm(rect[1] - rect[2]))
        if width <= 0 or height <= 0:
            reference = resized
            method = "resize"
        else:
            if height >= width:
                target_h = CANONICAL_LONG_SIDE
                target_w = max(1, int(round(CANONICAL_LONG_SIDE * width / height)))
            else:
                target_w = CANONICAL_LONG_SIDE
                target_h = max(1, int(round(CANONICAL_LONG_SIDE * height / width)))
            reference = four_point_transform(resized, corners, target_w, target_h)
            method = "paper"
    else:
        reference = resized
        method = "resize"

    markers = detect_markers(reference)
    return reference, {"method": method, "markers": markers, "debug": debug, "scale": scale}
