"""Generator lembar jawaban kosong yang siap dicetak.

Lembar dibuat pada ukuran A4 200 DPI dan dilengkapi empat marker kotak hitam
di sudut. Marker membantu proses penyelarasan (perspective transform) saat
lembar difoto.
"""
import io
import math

import cv2
import numpy as np
from PIL import Image

PAGE_W = 1654
PAGE_H = 2339
PAGE_DPI = 200
MARKER_SIZE = 44
MARKER_INSET = 52


def option_labels_for(n_options):
    """Buat label opsi A, B, C, ... sesuai jumlah opsi."""
    if n_options < 2 or n_options > 10:
        raise ValueError("Jumlah opsi harus antara 2 sampai 10.")
    return [chr(ord("A") + i) for i in range(n_options)]


def choose_blocks(n_questions):
    """Pilih jumlah blok yang membagi habis jumlah soal (maksimal 4 blok)."""
    ideal = max(1, math.ceil(n_questions / 25))
    for blocks in range(min(4, ideal), 0, -1):
        if n_questions % blocks == 0:
            return blocks
    return 1


def _text_center(image, text, cx, cy, scale, color, thickness=1):
    size, baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    x = int(cx - size[0] / 2)
    y = int(cy + size[1] / 2)
    cv2.putText(
        image,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        scale,
        color,
        thickness,
        cv2.LINE_AA,
    )


def generate_blank_sheet(
    n_questions=50,
    n_options=5,
    n_blocks=None,
    title="LEMBAR JAWABAN PILIHAN GANDA",
    subtitle="Isi dengan menghitamkan bulatan jawaban yang dipilih",
):
    """Kembalikan (citra BGR, daftar marker, daftar bubble teoretis)."""
    if n_questions < 1:
        raise ValueError("Jumlah soal minimal 1.")
    labels = option_labels_for(n_options)
    n_blocks = int(n_blocks or choose_blocks(n_questions))
    if n_questions % n_blocks != 0:
        raise ValueError("Jumlah soal harus habis dibagi jumlah blok.")

    rows_per_block = n_questions // n_blocks
    if rows_per_block > 60:
        raise ValueError(
            "Terlalu banyak baris per blok. Tambah jumlah blok atau kurangi soal."
        )

    image = np.full((PAGE_H, PAGE_W, 3), 255, np.uint8)
    ink = (45, 45, 45)

    # ------------------------------------------------------------------ header
    _text_center(image, title, PAGE_W / 2, 126, 0.95, (20, 20, 20), 2)
    _text_center(image, subtitle, PAGE_W / 2, 170, 0.52, (90, 90, 90), 1)
    cv2.line(image, (100, 200), (PAGE_W - 100, 200), (120, 120, 120), 2)

    field_y = 246
    cv2.putText(image, "Nama", (110, field_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ink, 1, cv2.LINE_AA)
    cv2.line(image, (190, field_y + 4), (770, field_y + 4), (80, 80, 80), 1)
    cv2.putText(image, "Kelas / NIM", (830, field_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ink, 1, cv2.LINE_AA)
    cv2.line(image, (990, field_y + 4), (1540, field_y + 4), (80, 80, 80), 1)

    cv2.putText(image, "Tanggal", (110, field_y + 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ink, 1, cv2.LINE_AA)
    cv2.line(image, (215, field_y + 66), (560, field_y + 66), (80, 80, 80), 1)
    cv2.putText(image, "Paket / Kode", (830, field_y + 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, ink, 1, cv2.LINE_AA)
    cv2.line(image, (1015, field_y + 66), (1540, field_y + 66), (80, 80, 80), 1)

    # ------------------------------------------------------- area grid jawaban
    grid_top = 400
    grid_bottom = PAGE_H - 110
    available_h = grid_bottom - grid_top
    row_step = min(46.0, available_h / float(rows_per_block))
    radius = max(7.0, min(15.0, row_step * 0.30))

    gap = 120.0 if n_blocks > 1 else 0.0
    max_total = PAGE_W - 200
    spacing = max(radius * 3.6, 46.0)
    block_width = (n_options - 1) * spacing + 2 * radius
    total_width = n_blocks * block_width + (n_blocks - 1) * gap
    if total_width > max_total:
        scale = (max_total - (n_blocks - 1) * gap) / (n_blocks * block_width)
        spacing *= scale
        radius *= max(0.65, scale)
        block_width = (n_options - 1) * spacing + 2 * radius
        total_width = n_blocks * block_width + (n_blocks - 1) * gap

    x_start = (PAGE_W - total_width) / 2.0
    y_start = grid_top + max(14.0, (available_h - rows_per_block * row_step) / 2.0) + 18

    markers = []
    for name, (mx, my) in {
        "tl": (MARKER_INSET, MARKER_INSET),
        "tr": (PAGE_W - MARKER_INSET - MARKER_SIZE, MARKER_INSET),
        "br": (PAGE_W - MARKER_INSET - MARKER_SIZE, PAGE_H - MARKER_INSET - MARKER_SIZE),
        "bl": (MARKER_INSET, PAGE_H - MARKER_INSET - MARKER_SIZE),
    }.items():
        cv2.rectangle(image, (mx, my), (mx + MARKER_SIZE, my + MARKER_SIZE), (0, 0, 0), -1)
        markers.append(
            {
                "name": name,
                "x": float(mx + MARKER_SIZE / 2),
                "y": float(my + MARKER_SIZE / 2),
            }
        )

    bubbles = []
    thickness = max(1, int(round(radius * 0.16)))
    label_scale = max(0.32, min(0.52, radius / 27.0))

    for block in range(n_blocks):
        first_x = x_start + block * (block_width + gap) + radius
        last_x = first_x + (n_options - 1) * spacing
        label_y = int(y_start - max(24, row_step * 0.55))
        cv2.putText(
            image,
            f"{block * rows_per_block + 1} - {(block + 1) * rows_per_block}",
            (int(first_x - radius), label_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (110, 110, 110),
            1,
            cv2.LINE_AA,
        )
        for row in range(rows_per_block):
            y = y_start + row * row_step + radius
            question_no = block * rows_per_block + row + 1
            cv2.putText(
                image,
                str(question_no),
                (int(first_x - radius - max(22, radius * 2.2)), int(y + 5)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (100, 100, 100),
                1,
                cv2.LINE_AA,
            )
            for opt_idx, label in enumerate(labels):
                x = first_x + opt_idx * spacing
                cv2.circle(image, (int(round(x)), int(round(y))), int(round(radius)), ink, thickness, cv2.LINE_AA)
                _text_center(image, label, x, y + 1, label_scale, (80, 80, 80), 1)
                bubbles.append(
                    {
                        "question_no": question_no,
                        "option_index": opt_idx,
                        "option_label": label,
                        "x": float(x),
                        "y": float(y),
                        "radius": float(radius),
                        "row_index": row,
                        "block_index": block,
                    }
                )

    # footer
    cv2.putText(
        image,
        "Hitamkan penuh bulatan. Jangan menandai lebih dari satu opsi per soal.",
        (110, PAGE_H - 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (110, 110, 110),
        1,
        cv2.LINE_AA,
    )
    _ = last_x  # menjaga variabel tetap terbaca saat debug

    return image, markers, bubbles


def draw_mark(image, x, y, radius, style="arsir"):
    """Gambar tanda jawaban sintetis untuk pengujian."""
    x, y, radius = int(round(x)), int(round(y)), int(round(radius))
    color = (25, 25, 25)
    if style == "lingkar":
        cv2.circle(image, (x, y), max(4, radius - 2), color, max(3, radius // 3), cv2.LINE_AA)
    elif style == "silang":
        d = max(4, radius - 3)
        cv2.line(image, (x - d, y - d), (x + d, y + d), color, 2, cv2.LINE_AA)
        cv2.line(image, (x - d, y + d), (x + d, y - d), color, 2, cv2.LINE_AA)
    elif style == "setengah":
        cv2.ellipse(image, (x, y), (radius, radius), 0, 0, 180, color, -1, cv2.LINE_AA)
    else:
        cv2.circle(image, (x, y), max(4, radius - 2), color, -1, cv2.LINE_AA)
    return image


def to_png_bytes(image):
    ok, buffer = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Gagal membuat berkas PNG.")
    return buffer.tobytes()


def to_pdf_bytes(image, dpi=PAGE_DPI):
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    output = io.BytesIO()
    pil_image.save(output, format="PDF", resolution=float(dpi))
    return output.getvalue()


def save_sheet(image, path):
    if not cv2.imwrite(path, image):
        raise IOError(f"Gagal menyimpan lembar ke {path}")
