"""Import kunci jawaban dari Excel dan export hasil pemeriksaan."""
import io
import re

import pandas as pd


def _normalize(name):
    return re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()


def _find_column(columns, candidates):
    normalized = {_normalize(column): column for column in columns}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    for normalized_name, original in normalized.items():
        for candidate in candidates:
            if candidate in normalized_name:
                return original
    return None


def read_key_excel(file_stream, n_questions, option_labels):
    """Baca file Excel kunci jawaban. Kembalikan (answers, errors)."""
    errors = []
    labels = [str(label).upper() for label in option_labels]
    try:
        frame = pd.read_excel(file_stream, engine="openpyxl")
    except Exception as exc:  # noqa: BLE001 - pesan perlu ramah ke pengguna
        return {}, [f"File Excel tidak dapat dibaca: {exc}"]

    if frame.empty:
        return {}, ["File Excel kosong."]

    no_column = _find_column(frame.columns, ["no", "nomor", "nomor soal", "soal"])
    key_column = _find_column(frame.columns, ["kunci", "jawaban", "answer", "key"])
    if no_column is None or key_column is None:
        return {}, [
            "Kolom 'No' dan 'Kunci' tidak ditemukan. "
            "Gunakan header persis seperti contoh: No | Kunci."
        ]

    answers = {}
    for _, row in frame.iterrows():
        raw_no = row.get(no_column)
        raw_key = row.get(key_column)
        if pd.isna(raw_no) or pd.isna(raw_key):
            continue
        try:
            question_no = int(float(raw_no))
        except (TypeError, ValueError):
            errors.append(f"Nomor soal tidak valid: {raw_no}")
            continue
        answer = str(raw_key).strip().upper()
        if answer.endswith(".0"):
            answer = answer[:-2]
        if question_no < 1 or question_no > n_questions:
            errors.append(f"Nomor soal {question_no} di luar rentang 1-{n_questions}.")
            continue
        if answer not in labels:
            errors.append(
                f"Kunci soal {question_no} ('{answer}') bukan opsi yang valid "
                f"({', '.join(labels)})."
            )
            continue
        if question_no in answers:
            errors.append(f"Nomor soal {question_no} muncul lebih dari sekali.")
            continue
        answers[question_no] = answer

    missing = [number for number in range(1, n_questions + 1) if number not in answers]
    if missing:
        preview = ", ".join(str(number) for number in missing[:12])
        suffix = "..." if len(missing) > 12 else ""
        errors.append(
            f"Jumlah kunci tidak lengkap: {len(answers)} dari {n_questions}. "
            f"Nomor yang belum ada: {preview}{suffix}"
        )
    return answers, errors


def build_key_example(n_questions, option_labels):
    """Buat file contoh Excel kunci jawaban."""
    labels = list(option_labels)
    rows = {
        "No": list(range(1, n_questions + 1)),
        "Kunci": [labels[index % len(labels)] for index in range(n_questions)],
    }
    frame = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name="Kunci Jawaban")
        worksheet = writer.sheets["Kunci Jawaban"]
        worksheet.column_dimensions["A"].width = 10
        worksheet.column_dimensions["B"].width = 14
        worksheet.freeze_panes = "A2"
    output.seek(0)
    return output


def export_results_excel(results):
    """Export ringkasan, detail per soal, dan rekap soal ke satu workbook."""
    summary_rows = []
    detail_rows = []
    question_stats = {}

    for result in results:
        summary_rows.append(
            {
                "No": len(summary_rows) + 1,
                "Nama Siswa": result.student_name,
                "NIM / Kelas": " / ".join(
                    part for part in [result.student_no, result.class_name] if part
                ),
                "Templat": result.template.name if result.template else "",
                "Paket Kunci": result.key.package_name if result.key else "",
                "Benar": result.correct,
                "Salah": result.wrong,
                "Kosong": result.empty,
                "Ganda": result.double,
                "Nilai": round(result.score, 2),
                "Tanggal": result.created_at.strftime("%d-%m-%Y %H:%M")
                if result.created_at
                else "",
            }
        )
        for answer in result.answers:
            detail_rows.append(
                {
                    "Nama Siswa": result.student_name,
                    "No Soal": answer.question_no,
                    "Kunci": answer.correct_answer,
                    "Jawaban Siswa": answer.student_answer,
                    "Status": answer.status.title(),
                    "Rasio": round(answer.ratio or 0.0, 4),
                }
            )
            stats = question_stats.setdefault(
                answer.question_no, {"benar": 0, "total": 0}
            )
            stats["total"] += 1
            if answer.status == "benar":
                stats["benar"] += 1

    recap_rows = []
    for question_no in sorted(question_stats):
        stats = question_stats[question_no]
        recap_rows.append(
            {
                "No Soal": question_no,
                "Jumlah Benar": stats["benar"],
                "Jumlah Siswa": stats["total"],
                "Persentase Benar": round(
                    stats["benar"] / float(stats["total"]) * 100.0, 2
                )
                if stats["total"]
                else 0.0,
            }
        )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(summary_rows).to_excel(
            writer, index=False, sheet_name="Ringkasan"
        )
        pd.DataFrame(detail_rows).to_excel(
            writer, index=False, sheet_name="Detail Jawaban"
        )
        pd.DataFrame(recap_rows).to_excel(
            writer, index=False, sheet_name="Rekap Soal"
        )
        for sheet_name, widths in {
            "Ringkasan": [6, 28, 20, 24, 16, 8, 8, 8, 8, 8, 18],
            "Detail Jawaban": [28, 10, 8, 14, 12, 10],
            "Rekap Soal": [10, 14, 14, 18],
        }.items():
            worksheet = writer.sheets[sheet_name]
            for index, width in enumerate(widths, start=1):
                worksheet.column_dimensions[
                    worksheet.cell(row=1, column=index).column_letter
                ].width = width
    output.seek(0)
    return output
