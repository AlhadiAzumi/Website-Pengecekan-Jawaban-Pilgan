"""Uji mandiri pipeline pengolahan citra tanpa membuka browser.

Jalankan: python scripts/selftest_core.py
Script membuat lembar kosong sintetis, mendeteksi 250 bulatan, membuat lima
lembar terisi dengan distorsi perspektif + pencahayaan, lalu membandingkan
hasil baca dengan jawaban yang digambar.
"""
import os
import random
import sys

import cv2
import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.alignment import align_to_template, prepare_reference  # noqa: E402
from core.detection import detect_template  # noqa: E402
from core.reading import measure_blank_baseline, process_aligned_sheet  # noqa: E402
from core.sheet_generator import draw_mark, generate_blank_sheet  # noqa: E402

OUTPUT_DIR = os.path.join(BASE_DIR, "uploads", "selftest")


def make_perspective_scan(image, rng, index):
    height, width = image.shape[:2]
    canvas_w, canvas_h = 1450, 1950
    margin = 100
    corners = np.float32(
        [
            [margin + rng.randint(-25, 25), margin + rng.randint(-25, 25)],
            [canvas_w - margin + rng.randint(-25, 25), margin + rng.randint(-25, 25)],
            [canvas_w - margin + rng.randint(-25, 25), canvas_h - margin + rng.randint(-25, 25)],
            [margin + rng.randint(-25, 25), canvas_h - margin + rng.randint(-25, 25)],
        ]
    )
    source = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    background = np.full((canvas_h, canvas_w, 3), 42 + index * 3, np.uint8)
    scan = cv2.warpPerspective(
        image,
        cv2.getPerspectiveTransform(source, corners),
        (canvas_w, canvas_h),
        dst=background,
        borderMode=cv2.BORDER_TRANSPARENT,
    )
    gradient = np.tile(
        np.linspace(rng.uniform(0.72, 0.84), 1.06, canvas_w)[None, :, None],
        (canvas_h, 1, 3),
    )
    noise = np.random.randint(-5, 6, scan.shape)
    return np.clip(scan * gradient + noise, 0, 255).astype(np.uint8)


def expected_status(answer_labels):
    if not answer_labels:
        return "kosong", "-"
    if len(answer_labels) > 1:
        return "ganda", "".join(answer_labels)
    return "terisi", answer_labels[0]


def main():
    rng = random.Random(21)
    np.random.seed(21)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    n_questions, n_options, n_blocks = 50, 5, 2
    params = {
        "detect_threshold": 0,
        "min_area": 120,
        "max_area": 4000,
        "circularity": 0.60,
        "threshold_method": "otsu",
        "adaptive_block_size": 31,
        "adaptive_c": 15,
        "morph_kernel": 3,
        "fill_ratio": 0.40,
        "blur_threshold": 45.0,
    }

    print("[1] Membuat lembar kosong...")
    blank, markers, _ = generate_blank_sheet(n_questions, n_options, n_blocks)
    cv2.imwrite(os.path.join(OUTPUT_DIR, "lembar_kosong.png"), blank)

    print("[2] Rektifikasi templat dan deteksi bulatan...")
    reference, info = prepare_reference(blank)
    detection = detect_template(
        reference, n_questions, n_options, n_blocks, params
    )
    print(
        f"    kandidat={len(detection['candidates'])} "
        f"bubbles={len(detection['bubbles'])} "
        f"strategi={detection['strategy']} blok={detection['n_blocks']}"
    )
    assert detection["success"], f"Deteksi templat gagal: {detection['warnings']}"
    cv2.imwrite(os.path.join(OUTPUT_DIR, "templat_preview.png"), detection["preview"])

    bubbles = detection["bubbles"]
    baseline = measure_blank_baseline(reference, bubbles, params)
    for bubble in bubbles:
        bubble["blank_ratio"] = baseline[
            (bubble["question_no"], bubble["option_index"])
        ]

    key = [rng.choice("ABCDE") for _ in range(n_questions)]
    key_map = {index + 1: answer for index, answer in enumerate(key)}

    print("[3] Membuat lima lembar terisi + distorsi perspektif...")
    styles = ["arsir", "silang", "setengah", "arsir"]
    total_mismatch = 0
    for scan_index in range(5):
        filled = reference.copy()
        expected = {}
        for question_no in range(1, n_questions + 1):
            if rng.random() < 0.82:
                selected = [key[question_no - 1]]
            else:
                selected = [rng.choice("ABCDE")]
            if question_no == 6:
                selected = []
            if question_no == 14:
                selected = ["A", "B"]
            expected[question_no] = expected_status(selected)
            for label in selected:
                bubble = next(
                    item
                    for item in bubbles
                    if item["question_no"] == question_no
                    and item["option_label"] == label
                )
                draw_mark(
                    filled,
                    bubble["x"],
                    bubble["y"],
                    bubble["radius"],
                    rng.choice(styles),
                )

        scan = make_perspective_scan(filled, rng, scan_index)
        cv2.imwrite(
            os.path.join(OUTPUT_DIR, f"scan_{scan_index + 1}.jpg"), scan
        )
        aligned, method, _, warnings = align_to_template(
            scan, reference, info["markers"], mode="auto"
        )
        result = process_aligned_sheet(
            aligned,
            bubbles,
            key_map,
            n_questions,
            params,
            reference=reference,
        )
        cv2.imwrite(
            os.path.join(OUTPUT_DIR, f"hasil_{scan_index + 1}.jpg"),
            result["annotated"],
        )

        mismatches = []
        for detail in result["details"]:
            status, label = expected[detail["question_no"]]
            if status == "terisi":
                if detail["student_answer"] != label:
                    mismatches.append(detail["question_no"])
            elif detail["status"] != status:
                mismatches.append(detail["question_no"])
        total_mismatch += len(mismatches)
        print(
            f"    scan {scan_index + 1}: alignment={method} "
            f"benar={result['correct']} salah={result['wrong']} "
            f"kosong={result['empty']} ganda={result['double']} "
            f"nilai={result['score']:.1f} "
            f"mismatch={len(mismatches)}"
        )
        if warnings:
            print(f"      catatan: {warnings}")
        if mismatches:
            print(f"      soal tidak cocok: {mismatches}")

    print("[4] Menguji tanda lingkaran dengan ambang rasio lebih rendah...")
    outline_sheet = reference.copy()
    for question_no in range(1, n_questions + 1):
        bubble = next(
            item
            for item in bubbles
            if item["question_no"] == question_no and item["option_label"] == "B"
        )
        draw_mark(
            outline_sheet,
            bubble["x"],
            bubble["y"],
            bubble["radius"],
            "lingkar",
        )
    outline_params = dict(params)
    outline_params["fill_ratio"] = 0.30
    outline_result = process_aligned_sheet(
        outline_sheet,
        bubbles,
        {number: "B" for number in range(1, n_questions + 1)},
        n_questions,
        outline_params,
        reference=reference,
    )
    print(
        "    lingkaran dengan fill_ratio 0.30: "
        f"benar={outline_result['correct']} (harus {n_questions})"
    )
    assert outline_result["correct"] == n_questions, (
        "Tanda lingkaran belum terbaca; turunkan fill_ratio pada pengaturan."
    )

    print("[5] Menguji threshold adaptif dan deteksi templat dengan noise...")
    noisy = reference.copy()
    shadow = np.tile(
        np.linspace(0.55, 1.0, reference.shape[1])[None, :, None],
        (reference.shape[0], 1, 3),
    )
    noisy = np.clip(noisy * shadow, 0, 255).astype(np.uint8)
    adaptive_params = dict(params)
    adaptive_params["threshold_method"] = "adaptive"
    noisy_result = process_aligned_sheet(
        noisy,
        bubbles,
        key_map,
        n_questions,
        adaptive_params,
        reference=reference,
    )
    print(
        "    adaptive pada templat kosong: "
        f"kosong={noisy_result['empty']} (harus {n_questions})"
    )
    assert noisy_result["empty"] == n_questions

    print()
    if total_mismatch:
        print(f"SELFTEST GAGAL: {total_mismatch} jawaban tidak terbaca sesuai target.")
        return 1
    print("SELFTEST LULUS: semua jawaban sintetis terbaca benar.")
    print(f"Berkas hasil: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
