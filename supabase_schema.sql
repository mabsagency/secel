-- ================================================================
-- SECEL — Schéma SQL Supabase (PostgreSQL)
-- Exécutez ce script dans SQL Editor > Supabase Dashboard
-- URL : https://supabase.com/dashboard/project/yzcycszswnpplrepuzqe/sql
-- ================================================================

-- ── Extensions ───────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Nettoyage (optionnel — décommentez pour repartir de zéro) ─
-- DROP TABLE IF EXISTS notifications, payments, watch_history, video_progress,
--   enrollments, pdf_contents, videos, courses, users CASCADE;

-- ══════════════════════════════════════════════════════════════
--  TABLE : users
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS users (
    id               SERIAL       PRIMARY KEY,
    username         VARCHAR(80)  UNIQUE NOT NULL,
    email            VARCHAR(120) UNIQUE NOT NULL,
    password_hash    VARCHAR(256) NOT NULL,
    role             VARCHAR(20)  NOT NULL DEFAULT 'student'
                       CHECK (role IN ('student', 'teacher', 'admin')),
    full_name        VARCHAR(150),
    phone            VARCHAR(20),
    avatar           VARCHAR(255) DEFAULT 'default.png',
    bio              TEXT,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    language         VARCHAR(5)   DEFAULT 'fr',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login       TIMESTAMPTZ,
    -- Champs étudiant
    learning_goals   TEXT,
    student_level    VARCHAR(50),
    -- Champs enseignant
    specialty        VARCHAR(200),
    qualifications   TEXT,
    portfolio_url    VARCHAR(300),
    years_experience INTEGER      DEFAULT 0
);

-- Index utilisateurs
CREATE INDEX IF NOT EXISTS idx_users_email    ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
CREATE INDEX IF NOT EXISTS idx_users_role     ON users (role);

-- ══════════════════════════════════════════════════════════════
--  TABLE : courses
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS courses (
    id                   SERIAL      PRIMARY KEY,
    title                VARCHAR(200) NOT NULL,
    description          TEXT,
    teacher_id           INTEGER      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    category             VARCHAR(100),
    level                VARCHAR(50)  DEFAULT 'Debutant'
                           CHECK (level IN ('Debutant', 'Intermédiaire', 'Avancé')),
    thumbnail            VARCHAR(255),
    price                NUMERIC(12,2) NOT NULL DEFAULT 0.00,
    currency             VARCHAR(10)  DEFAULT 'FCFA',
    duration_hours       NUMERIC(8,2) DEFAULT 0,
    is_published         BOOLEAN      NOT NULL DEFAULT FALSE,
    is_free              BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    -- Workflow de validation
    course_type          VARCHAR(20)  DEFAULT 'video'
                           CHECK (course_type IN ('video', 'ebook')),
    is_approved          BOOLEAN      NOT NULL DEFAULT FALSE,
    approval_status      VARCHAR(20)  NOT NULL DEFAULT 'pending'
                           CHECK (approval_status IN ('pending', 'approved', 'rejected')),
    rejection_reason     TEXT,
    -- eBook
    ebook_cover          VARCHAR(255),
    ebook_file           VARCHAR(500),
    -- YouTube
    youtube_playlist_url VARCHAR(500)
);

-- Index cours
CREATE INDEX IF NOT EXISTS idx_courses_teacher_id      ON courses (teacher_id);
CREATE INDEX IF NOT EXISTS idx_courses_approval_status ON courses (approval_status);
CREATE INDEX IF NOT EXISTS idx_courses_is_published    ON courses (is_published);

-- Trigger : mettre à jour updated_at automatiquement
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_courses_updated_at ON courses;
CREATE TRIGGER trg_courses_updated_at
  BEFORE UPDATE ON courses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ══════════════════════════════════════════════════════════════
--  TABLE : videos
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS videos (
    id               SERIAL      PRIMARY KEY,
    title            VARCHAR(200) NOT NULL,
    description      TEXT,
    course_id        INTEGER      NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    file_path        VARCHAR(500),
    external_url     VARCHAR(500),
    is_local         BOOLEAN      NOT NULL DEFAULT TRUE,
    duration_seconds INTEGER      DEFAULT 0,
    thumbnail        VARCHAR(255),
    is_approved      BOOLEAN      NOT NULL DEFAULT FALSE,
    upload_date      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_watched     TIMESTAMPTZ,
    watch_count      INTEGER      NOT NULL DEFAULT 0,
    order_index      INTEGER      NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_videos_course_id   ON videos (course_id);
CREATE INDEX IF NOT EXISTS idx_videos_is_approved ON videos (is_approved);
CREATE INDEX IF NOT EXISTS idx_videos_order_index ON videos (course_id, order_index);

-- ══════════════════════════════════════════════════════════════
--  TABLE : video_progress
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS video_progress (
    id                 SERIAL     PRIMARY KEY,
    user_id            INTEGER    NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    video_id           INTEGER    NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    watch_percentage   NUMERIC(5,2) DEFAULT 0.00,
    total_time_seconds INTEGER    DEFAULT 0,
    completed          BOOLEAN    NOT NULL DEFAULT FALSE,
    last_position      NUMERIC(10,2) DEFAULT 0.00,
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, video_id)
);

CREATE INDEX IF NOT EXISTS idx_vp_user_video ON video_progress (user_id, video_id);

-- ══════════════════════════════════════════════════════════════
--  TABLE : pdf_contents
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS pdf_contents (
    id          SERIAL      PRIMARY KEY,
    title       VARCHAR(200) NOT NULL,
    description TEXT,
    course_id   INTEGER      NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    file_path   VARCHAR(500) NOT NULL,
    file_size   INTEGER,
    is_approved BOOLEAN      NOT NULL DEFAULT FALSE,
    upload_date TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pdf_course_id ON pdf_contents (course_id);

-- ══════════════════════════════════════════════════════════════
--  TABLE : enrollments
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS enrollments (
    id                 SERIAL     PRIMARY KEY,
    student_id         INTEGER    NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    course_id          INTEGER    NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    enrolled_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    progress           NUMERIC(5,2) NOT NULL DEFAULT 0.00, -- 0-100 %
    completed          BOOLEAN    NOT NULL DEFAULT FALSE,
    total_time_seconds INTEGER    NOT NULL DEFAULT 0,
    UNIQUE (student_id, course_id)
);

CREATE INDEX IF NOT EXISTS idx_enrollments_student  ON enrollments (student_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_course   ON enrollments (course_id);

-- ══════════════════════════════════════════════════════════════
--  TABLE : watch_history
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS watch_history (
    id             SERIAL     PRIMARY KEY,
    user_id        INTEGER    NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    video_id       INTEGER    NOT NULL REFERENCES videos (id) ON DELETE CASCADE,
    watched_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    watch_duration INTEGER    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_wh_user_id  ON watch_history (user_id);
CREATE INDEX IF NOT EXISTS idx_wh_video_id ON watch_history (video_id);
CREATE INDEX IF NOT EXISTS idx_wh_date     ON watch_history (user_id, watched_at);

-- ══════════════════════════════════════════════════════════════
--  TABLE : payments
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS payments (
    id           SERIAL       PRIMARY KEY,
    user_id      INTEGER      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    course_id    INTEGER      REFERENCES courses (id) ON DELETE SET NULL,
    amount       NUMERIC(12,2) NOT NULL,
    currency     VARCHAR(10)  DEFAULT 'FCFA',
    provider     VARCHAR(30)  CHECK (provider IN ('orange_money', 'mtn_momo', 'cash', NULL)),
    phone_number VARCHAR(20),
    reference    VARCHAR(100) UNIQUE,
    status       VARCHAR(20)  NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'success', 'failed', 'cancelled')),
    description  VARCHAR(300),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payments_user_id   ON payments (user_id);
CREATE INDEX IF NOT EXISTS idx_payments_course_id ON payments (course_id);
CREATE INDEX IF NOT EXISTS idx_payments_status    ON payments (status);

-- ══════════════════════════════════════════════════════════════
--  TABLE : notifications
-- ══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL      PRIMARY KEY,
    user_id    INTEGER     NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    message    TEXT        NOT NULL,
    message_en TEXT,
    message_zh TEXT,
    is_read    BOOLEAN     NOT NULL DEFAULT FALSE,
    notif_type VARCHAR(50) DEFAULT 'info'
                 CHECK (notif_type IN ('info', 'success', 'warning', 'danger')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notif_user_id ON notifications (user_id);
CREATE INDEX IF NOT EXISTS idx_notif_is_read ON notifications (user_id, is_read);

-- ══════════════════════════════════════════════════════════════
--  ROW LEVEL SECURITY (RLS) — Protection des données
-- ══════════════════════════════════════════════════════════════

-- Activer RLS sur toutes les tables sensibles
ALTER TABLE users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses        ENABLE ROW LEVEL SECURITY;
ALTER TABLE videos         ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrollments    ENABLE ROW LEVEL SECURITY;
ALTER TABLE video_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE watch_history  ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments       ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications  ENABLE ROW LEVEL SECURITY;
ALTER TABLE pdf_contents   ENABLE ROW LEVEL SECURITY;

-- ── Politiques pour notifications ─────────────────────────────
-- Un utilisateur ne voit que SES notifications
CREATE POLICY "notif_select_own" ON notifications
  FOR SELECT USING (user_id::text = auth.uid()::text);

CREATE POLICY "notif_insert_service" ON notifications
  FOR INSERT WITH CHECK (true);  -- service_role insère librement

CREATE POLICY "notif_update_own" ON notifications
  FOR UPDATE USING (user_id::text = auth.uid()::text);

-- ── Politiques pour courses ────────────────────────────────────
-- Tout le monde peut voir les cours publiés et approuvés
CREATE POLICY "courses_select_published" ON courses
  FOR SELECT USING (is_published = TRUE AND is_approved = TRUE);

-- Les enseignants voient leurs propres cours (même non publiés)
CREATE POLICY "courses_select_own_teacher" ON courses
  FOR SELECT USING (teacher_id::text = auth.uid()::text);

-- ── Politiques pour enrollments ───────────────────────────────
CREATE POLICY "enroll_select_own" ON enrollments
  FOR SELECT USING (student_id::text = auth.uid()::text);

-- ── Politiques pour video_progress ───────────────────────────
CREATE POLICY "vp_select_own" ON video_progress
  FOR SELECT USING (user_id::text = auth.uid()::text);

-- ── Politiques pour payments ──────────────────────────────────
CREATE POLICY "payments_select_own" ON payments
  FOR SELECT USING (user_id::text = auth.uid()::text);

-- ══════════════════════════════════════════════════════════════
--  REALTIME — Activer la réplication pour les notifications
-- ══════════════════════════════════════════════════════════════
-- Activer Realtime sur la table notifications
-- (Peut aussi être fait dans Dashboard > Database > Replication)
ALTER PUBLICATION supabase_realtime ADD TABLE notifications;

-- ══════════════════════════════════════════════════════════════
--  DONNÉES INITIALES — Admin SECEL
-- ══════════════════════════════════════════════════════════════
-- ⚠️  Le mot de passe est hashé avec Werkzeug scrypt.
-- L'admin sera créé automatiquement par seed_data.py au premier lancement.
-- Si vous voulez créer l'admin manuellement en SQL, utilisez run.py.

-- ══════════════════════════════════════════════════════════════
--  VUES UTILES (optionnel)
-- ══════════════════════════════════════════════════════════════

-- Vue : stats par cours (nombre d'inscrits, progression moyenne)
CREATE OR REPLACE VIEW course_stats AS
SELECT
    c.id                                              AS course_id,
    c.title,
    c.teacher_id,
    COUNT(DISTINCT e.id)                              AS total_enrollments,
    ROUND(AVG(e.progress), 1)                         AS avg_progress,
    COUNT(DISTINCT e.id) FILTER (WHERE e.completed)  AS completions,
    COALESCE(SUM(v.watch_count), 0)                  AS total_views
FROM courses c
LEFT JOIN enrollments e ON e.course_id = c.id
LEFT JOIN videos      v ON v.course_id = c.id AND v.is_approved
GROUP BY c.id, c.title, c.teacher_id;

-- Vue : activité hebdomadaire par utilisateur
CREATE OR REPLACE VIEW weekly_user_activity AS
SELECT
    wh.user_id,
    DATE_TRUNC('day', wh.watched_at)        AS day,
    COUNT(*)                                 AS sessions,
    COALESCE(SUM(wh.watch_duration), 0)      AS total_seconds
FROM watch_history wh
WHERE wh.watched_at >= NOW() - INTERVAL '7 days'
GROUP BY wh.user_id, DATE_TRUNC('day', wh.watched_at);
