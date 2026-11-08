"""Model database aplikasi."""
import json
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

from config import DEFAULT_SETTINGS

db = SQLAlchemy()


class Template(db.Model):
    __tablename__ = "templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    original_filename = db.Column(db.String(255))
    source_path = db.Column(db.String(500), nullable=False)
    ref_path = db.Column(db.String(500), nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    n_questions = db.Column(db.Integer, nullable=False)
    n_options = db.Column(db.Integer, nullable=False)
    option_labels = db.Column(db.JSON, nullable=False)
    n_blocks = db.Column(db.Integer, nullable=False, default=1)
    bubble_radius = db.Column(db.Float, nullable=False, default=12.0)
    detect_params = db.Column(db.JSON)
    marker_positions = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bubbles = db.relationship(
        "TemplateBubble",
        backref="template",
        cascade="all, delete-orphan",
        order_by="TemplateBubble.question_no, TemplateBubble.option_index",
    )
    keys = db.relationship(
        "AnswerKey", backref="template", cascade="all, delete-orphan"
    )
    scans = db.relationship(
        "ScanResult", backref="template", cascade="all, delete-orphan"
    )

    @property
    def expected_bubbles(self):
        return self.n_questions * self.n_options

    def bubble_for(self, question_no, option_index):
        for bubble in self.bubbles:
            if (
                bubble.question_no == question_no
                and bubble.option_index == option_index
            ):
                return bubble
        return None


class TemplateBubble(db.Model):
    __tablename__ = "template_bubbles"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    question_no = db.Column(db.Integer, nullable=False)
    option_index = db.Column(db.Integer, nullable=False)
    option_label = db.Column(db.String(8), nullable=False)
    x = db.Column(db.Float, nullable=False)
    y = db.Column(db.Float, nullable=False)
    radius = db.Column(db.Float, nullable=False)
    blank_ratio = db.Column(db.Float, default=0.0)
    row_index = db.Column(db.Integer)
    block_index = db.Column(db.Integer)


class AnswerKey(db.Model):
    __tablename__ = "answer_keys"

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    package_name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship(
        "AnswerKeyItem",
        backref="key",
        cascade="all, delete-orphan",
        order_by="AnswerKeyItem.question_no",
    )

    @property
    def answer_map(self):
        return {item.question_no: item.answer for item in self.items}

    @property
    def answer_string(self):
        return "".join(item.answer for item in self.items)


class AnswerKeyItem(db.Model):
    __tablename__ = "answer_key_items"

    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(
        db.Integer,
        db.ForeignKey("answer_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_no = db.Column(db.Integer, nullable=False)
    answer = db.Column(db.String(8), nullable=False)


class ScanResult(db.Model):
    __tablename__ = "scan_results"

    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.String(64), index=True)
    template_id = db.Column(
        db.Integer, db.ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    key_id = db.Column(
        db.Integer, db.ForeignKey("answer_keys.id", ondelete="CASCADE"), nullable=False
    )
    student_name = db.Column(db.String(160), nullable=False)
    student_no = db.Column(db.String(80))
    class_name = db.Column(db.String(80))
    original_path = db.Column(db.String(500))
    aligned_path = db.Column(db.String(500))
    annotated_path = db.Column(db.String(500))
    threshold_path = db.Column(db.String(500))
    morph_path = db.Column(db.String(500))
    alignment_method = db.Column(db.String(80))
    threshold_method = db.Column(db.String(40))
    morph_kernel = db.Column(db.Integer)
    fill_ratio = db.Column(db.Float)
    correct = db.Column(db.Integer, default=0)
    wrong = db.Column(db.Integer, default=0)
    empty = db.Column(db.Integer, default=0)
    double = db.Column(db.Integer, default=0)
    score = db.Column(db.Float, default=0.0)
    quality_warning = db.Column(db.String(255))
    error_message = db.Column(db.String(255))
    debug_steps = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    key = db.relationship("AnswerKey", backref="scans")
    answers = db.relationship(
        "ScanAnswer",
        backref="result",
        cascade="all, delete-orphan",
        order_by="ScanAnswer.question_no",
    )

    @property
    def answered_questions(self):
        return [a for a in self.answers if a.status == "benar"]

    @property
    def status_class(self):
        if self.error_message:
            return "danger"
        if self.score >= 75:
            return "success"
        if self.score >= 60:
            return "warning"
        return "danger"


class ScanAnswer(db.Model):
    __tablename__ = "scan_answers"

    id = db.Column(db.Integer, primary_key=True)
    result_id = db.Column(
        db.Integer,
        db.ForeignKey("scan_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_no = db.Column(db.Integer, nullable=False)
    student_answer = db.Column(db.String(16))
    correct_answer = db.Column(db.String(8))
    status = db.Column(db.String(16), nullable=False)
    raw_ratio = db.Column(db.Float, default=0.0)
    ratio = db.Column(db.Float, default=0.0)
    all_ratios = db.Column(db.JSON)


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False)


def get_settings():
    """Ambil seluruh pengaturan aplikasi, lengkapi dengan nilai default."""
    settings = dict(DEFAULT_SETTINGS)
    for row in AppSetting.query.all():
        try:
            settings[row.key] = json.loads(row.value)
        except (ValueError, TypeError):
            settings[row.key] = row.value
    return settings


def set_setting(key, value):
    row = db.session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=json.dumps(value))
        db.session.add(row)
    else:
        row.value = json.dumps(value)
    return row


def seed_settings():
    """Pastikan seluruh default pengaturan tersedia di database."""
    existing = {row.key for row in AppSetting.query.all()}
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.session.add(AppSetting(key=key, value=json.dumps(value)))
    db.session.commit()
