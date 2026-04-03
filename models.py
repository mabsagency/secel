from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ─────────────────────────────────────────────────────────────
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)   # nullable pour OAuth
    role          = db.Column(db.String(20), default='student')
    # OAuth social login
    google_id     = db.Column(db.String(200), unique=True, nullable=True)
    linkedin_id   = db.Column(db.String(200), unique=True, nullable=True)
    full_name     = db.Column(db.String(150))
    phone         = db.Column(db.String(20))
    avatar        = db.Column(db.String(255), default='default.png')
    bio           = db.Column(db.Text)
    is_active     = db.Column(db.Boolean, default=True)
    language      = db.Column(db.String(5), default='fr')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_login    = db.Column(db.DateTime)
    # Student fields
    learning_goals   = db.Column(db.Text)
    student_level    = db.Column(db.String(50))
    # Teacher fields
    specialty        = db.Column(db.String(200))
    qualifications   = db.Column(db.Text)
    portfolio_url    = db.Column(db.String(300))
    years_experience = db.Column(db.Integer, default=0)

    courses_taught = db.relationship('Course', backref='teacher', lazy='dynamic',
                                     foreign_keys='Course.teacher_id')
    enrollments    = db.relationship('Enrollment', backref='student', lazy='dynamic')
    watch_history  = db.relationship('WatchHistory', backref='user', lazy='dynamic')
    video_progress = db.relationship('VideoProgress', backref='user', lazy='dynamic')
    payments       = db.relationship('Payment', backref='user', lazy='dynamic')

    def set_password(self, p): self.password_hash = generate_password_hash(p)
    def check_password(self, p):
        if not self.password_hash: return False
        return check_password_hash(self.password_hash, p)

# ─────────────────────────────────────────────────────────────
class Course(db.Model):
    __tablename__ = 'courses'
    id             = db.Column(db.Integer, primary_key=True)
    title          = db.Column(db.String(200), nullable=False)
    description    = db.Column(db.Text)
    teacher_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category       = db.Column(db.String(100))
    level          = db.Column(db.String(50), default='Debutant')
    thumbnail      = db.Column(db.String(255))
    price          = db.Column(db.Float, default=0.0)
    currency       = db.Column(db.String(10), default='XAF')
    duration_hours = db.Column(db.Float, default=0)
    is_published   = db.Column(db.Boolean, default=False)
    is_free        = db.Column(db.Boolean, default=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow)
    # Course type & approval workflow
    course_type          = db.Column(db.String(20), default='video')   # 'video' | 'ebook'
    is_approved          = db.Column(db.Boolean, default=False)
    approval_status      = db.Column(db.String(20), default='pending') # 'pending'|'approved'|'rejected'
    rejection_reason     = db.Column(db.Text)
    ebook_cover          = db.Column(db.String(255))   # cover image relative path
    ebook_file           = db.Column(db.String(500))   # main ebook PDF path
    youtube_playlist_url = db.Column(db.String(500))   # admin-only YouTube playlist
    expires_at           = db.Column(db.DateTime, nullable=True)  # auto-suppression

    # ── Index PostgreSQL pour les requêtes fréquentes ──────────
    __table_args__ = (
        db.Index('ix_courses_published_approved', 'is_published', 'approval_status'),
        db.Index('ix_courses_category_published', 'category', 'is_published'),
        db.Index('ix_courses_teacher',            'teacher_id'),
        db.Index('ix_courses_updated',            'updated_at'),
    )

    videos      = db.relationship('Video', backref='course', lazy='dynamic',
                                  cascade='all, delete-orphan')
    pdfs        = db.relationship('PDFContent', backref='course', lazy='dynamic',
                                  cascade='all, delete-orphan')
    enrollments = db.relationship('Enrollment', backref='course', lazy='dynamic')
    payments    = db.relationship('Payment', backref='course', lazy='dynamic')

    @property
    def total_videos(self):
        return self.videos.filter_by(is_approved=True).count()

# ─────────────────────────────────────────────────────────────
class Video(db.Model):
    __tablename__ = 'videos'
    id               = db.Column(db.Integer, primary_key=True)
    title            = db.Column(db.String(200), nullable=False)
    description      = db.Column(db.Text)
    course_id        = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    file_path        = db.Column(db.String(500))
    external_url     = db.Column(db.String(500))
    is_local         = db.Column(db.Boolean, default=True)
    duration_seconds = db.Column(db.Integer, default=0)
    thumbnail        = db.Column(db.String(255))
    is_approved      = db.Column(db.Boolean, default=False)
    upload_date      = db.Column(db.DateTime, default=datetime.utcnow)
    last_watched     = db.Column(db.DateTime)
    watch_count      = db.Column(db.Integer, default=0)
    order_index      = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.Index('ix_videos_course_approved', 'course_id', 'is_approved'),
        db.Index('ix_videos_course_order',    'course_id', 'order_index'),
    )

    watch_history = db.relationship('WatchHistory', backref='video', lazy='dynamic',
                                    cascade='all, delete-orphan')
    progress_logs = db.relationship('VideoProgress', backref='video', lazy='dynamic',
                                    cascade='all, delete-orphan')

# ─────────────────────────────────────────────────────────────
class VideoProgress(db.Model):
    """Track per-user per-video watch progress. Progress only counts when >= 90%."""
    __tablename__ = 'video_progress'
    id                 = db.Column(db.Integer, primary_key=True)
    user_id            = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    video_id           = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    watch_percentage   = db.Column(db.Float, default=0.0)
    total_time_seconds = db.Column(db.Integer, default=0)
    completed          = db.Column(db.Boolean, default=False)
    last_position      = db.Column(db.Float, default=0.0)
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'video_id'),)

# ─────────────────────────────────────────────────────────────
class PDFContent(db.Model):
    __tablename__ = 'pdf_contents'
    id          = db.Column(db.Integer, primary_key=True)
    title       = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    course_id   = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    file_path   = db.Column(db.String(500), nullable=False)
    file_size   = db.Column(db.Integer)
    is_approved = db.Column(db.Boolean, default=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

# ─────────────────────────────────────────────────────────────
class Enrollment(db.Model):
    __tablename__ = 'enrollments'
    id                 = db.Column(db.Integer, primary_key=True)
    student_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id          = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    enrolled_at        = db.Column(db.DateTime, default=datetime.utcnow)
    progress           = db.Column(db.Float, default=0.0)   # 0-100, advances only on complete videos
    completed          = db.Column(db.Boolean, default=False)
    total_time_seconds = db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint('student_id', 'course_id'),
        db.Index('ix_enrollments_student', 'student_id'),
        db.Index('ix_enrollments_course',  'course_id'),
    )

# ─────────────────────────────────────────────────────────────
class WatchHistory(db.Model):
    __tablename__ = 'watch_history'
    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    video_id       = db.Column(db.Integer, db.ForeignKey('videos.id'), nullable=False)
    watched_at     = db.Column(db.DateTime, default=datetime.utcnow)
    watch_duration = db.Column(db.Integer, default=0)

# ─────────────────────────────────────────────────────────────
class Payment(db.Model):
    """Mobile money payment (Orange Money / MTN MoMo)."""
    __tablename__ = 'payments'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id    = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    amount       = db.Column(db.Float, nullable=False)
    currency     = db.Column(db.String(10), default='XAF')
    provider     = db.Column(db.String(30), default='moneroo')  # moneroo
    phone_number = db.Column(db.String(20))
    reference    = db.Column(db.String(100), unique=True)
    status       = db.Column(db.String(20), default='pending')  # pending|success|failed|cancelled
    description  = db.Column(db.String(300))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

# ─────────────────────────────────────────────────────────────
class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    message_en = db.Column(db.Text)
    message_zh = db.Column(db.Text)
    is_read    = db.Column(db.Boolean, default=False)
    notif_type = db.Column(db.String(50), default='info')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
