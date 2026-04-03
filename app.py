import os, re, json, uuid, logging
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)

from flask import (Flask, render_template, request, redirect, url_for,
                   flash, jsonify, session, send_from_directory, abort,
                   Response, stream_with_context)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from authlib.integrations.flask_client import OAuth
from werkzeug.utils import secure_filename

from config import Config
from models import (db, User, Course, Video, PDFContent, Enrollment,
                    WatchHistory, Notification, VideoProgress, Payment)
from storage import upload_file, upload_file_as_path, delete_file, get_signed_url, is_supabase_url
from chatbot_data import get_chatbot_response
from payment_api import (initiate_moneroo_payment, verify_moneroo_payment,
                         confirm_payment_from_callback, check_payment_status,
                         get_payment_stats)
from supabase_client import notify_realtime, broadcast_event

# ── App Setup ─────────────────────────────────────────────────
app = Flask(__name__)
app.config.from_object(Config)

# ── Cache mémoire simple (TTL en secondes) ─────────────────────
# Utilisé pour éviter de requêter la DB à chaque visite sur les pages publiques.
# Remplaçable par Redis en production : pip install redis flask-caching
import time as _time, threading as _threading
_cache_store: dict = {}
_cache_lock = _threading.Lock()
_CACHE_MAX_ENTRIES = 200   # Limite anti-DoS RAM : max 200 entrées en cache

def _simple_cache(ttl: int = 300):
    """Décorateur de cache mémoire pour les routes GET sans paramètres utilisateur."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Ne pas mettre en cache pour les utilisateurs connectés (contenu personnalisé)
            if current_user.is_authenticated:
                return f(*args, **kwargs)
            # Limiter les paramètres à 3 clés max pour éviter la pollution du cache
            safe_args = dict(list(request.args.items())[:3])
            key = f.__name__ + str(sorted(safe_args.items()))
            with _cache_lock:
                entry = _cache_store.get(key)
                if entry and _time.time() < entry['exp']:
                    return entry['val']
            result = f(*args, **kwargs)
            with _cache_lock:
                # Si cache plein, supprimer les entrées expirées ou les plus anciennes
                if len(_cache_store) >= _CACHE_MAX_ENTRIES:
                    now = _time.time()
                    expired = [k for k, v in _cache_store.items() if now >= v['exp']]
                    if expired:
                        for k in expired:
                            del _cache_store[k]
                    else:
                        # Supprimer le premier tiers pour faire de la place
                        keys_to_del = list(_cache_store.keys())[:_CACHE_MAX_ENTRIES // 3]
                        for k in keys_to_del:
                            del _cache_store[k]
                _cache_store[key] = {'val': result, 'exp': _time.time() + ttl}
            return result
        return wrapper
    return decorator

def _clear_cache(prefix: str = ''):
    """Vide tout le cache ou seulement les clés commençant par prefix."""
    with _cache_lock:
        if prefix:
            for k in list(_cache_store.keys()):
                if k.startswith(prefix):
                    del _cache_store[k]
        else:
            _cache_store.clear()

# ── CSRF : protège tous les formulaires POST contre les attaques CSRF
app.config['WTF_CSRF_TIME_LIMIT'] = 3600   # token valide 1h
csrf = CSRFProtect(app)

# ── Rate Limiting : protection contre le brute-force
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],          # pas de limite globale — uniquement sur login
    storage_uri="memory://",
)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Connectez-vous pour acceder a cette page.'
login_manager.login_message_category = 'warning'

# ── OAuth Setup ────────────────────────────────────────────────
oauth = OAuth(app)

oauth.register(
    name='google',
    client_id=app.config.get('GOOGLE_CLIENT_ID'),
    client_secret=app.config.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)

oauth.register(
    name='linkedin',
    client_id=app.config.get('LINKEDIN_CLIENT_ID'),
    client_secret=app.config.get('LINKEDIN_CLIENT_SECRET'),
    authorize_url='https://www.linkedin.com/oauth/v2/authorization',
    access_token_url='https://www.linkedin.com/oauth/v2/accessToken',
    api_base_url='https://api.linkedin.com/v2/',
    client_kwargs={'scope': 'openid profile email'},
)

def _oauth_find_or_create(provider_id_field, provider_id, email, full_name):
    """Trouve ou crée un utilisateur via OAuth."""
    # 1. Chercher par provider ID
    user = User.query.filter(
        getattr(User, provider_id_field) == provider_id
    ).first()
    if user:
        return user
    # 2. Chercher par email
    if email:
        user = User.query.filter_by(email=email).first()
        if user:
            setattr(user, provider_id_field, provider_id)
            db.session.commit()
            return user
    # 3. Créer nouveau compte étudiant
    base = (email or 'user').split('@')[0]
    username = base
    suffix = 1
    while User.query.filter_by(username=username).first():
        username = f'{base}{suffix}'; suffix += 1
    user = User(
        username=username,
        email=email or f'{base}_{uuid.uuid4().hex[:6]}@oauth.local',
        full_name=full_name or base,
        role='student',
    )
    setattr(user, provider_id_field, provider_id)
    db.session.add(user)
    db.session.commit()
    return user

# ── Logique de nettoyage automatique ─────────────────────────
def _run_cleanup():
    """Supprime vidéos inactives + cours expirés. Appelé par le scheduler
    (local) ou par le Cron Job Vercel via /api/cron/cleanup (production)."""
    # 1. Supprimer vidéos inactives
    cutoff = datetime.utcnow() - timedelta(days=Config.VIDEO_INACTIVITY_DAYS)
    old = Video.query.filter(Video.last_watched < cutoff,
                             Video.last_watched.isnot(None)).all()
    deleted_videos = 0
    for v in old:
        if v.is_local and v.file_path:
            fp = os.path.join(app.static_folder, v.file_path)
            if os.path.exists(fp):
                try: os.remove(fp)
                except OSError: pass
        db.session.delete(v)
        deleted_videos += 1

    # 2. Supprimer cours dont la date d'expiration est dépassée
    now_utc = datetime.utcnow()
    expired_courses = Course.query.filter(
        Course.expires_at.isnot(None),
        Course.expires_at <= now_utc
    ).all()
    deleted_courses = 0
    for course in expired_courses:
        for v in course.videos.all():
            if v.is_local and v.file_path:
                fp = os.path.join(app.static_folder, v.file_path)
                if os.path.exists(fp):
                    try: os.remove(fp)
                    except OSError: pass
        for p in course.pdfs.all():
            if p.file_path:
                fp = os.path.join(app.static_folder, p.file_path)
                if os.path.exists(fp):
                    try: os.remove(fp)
                    except OSError: pass
        for asset in [course.ebook_cover, course.ebook_file]:
            if asset:
                fp = os.path.join(app.static_folder, asset)
                if os.path.exists(fp):
                    try: os.remove(fp)
                    except OSError: pass
        db.session.delete(course)
        deleted_courses += 1

    db.session.commit()
    return deleted_videos, deleted_courses

# ── Auto-delete scheduler (local uniquement) ──────────────────
# Sur Vercel (serverless), le cron job appelle /api/cron/cleanup à la place.
if not os.environ.get('VERCEL'):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
        def _scheduled_cleanup():
            with app.app_context():
                _run_cleanup()
        _scheduler.add_job(_scheduled_cleanup, 'interval', hours=24)
        _scheduler.start()
    except Exception:
        pass

# ── DB Migration OAuth columns ────────────────────────────────
def _run_oauth_migration():
    """Ajoute les colonnes OAuth et expires_at si elles n'existent pas encore."""
    try:
        with db.engine.connect() as conn:
            dialect = db.engine.dialect.name
            if dialect == 'sqlite':
                existing_users = [row[1] for row in conn.execute(
                    db.text("PRAGMA table_info(users)")
                ).fetchall()]
                for col, typedef in [('google_id', 'VARCHAR(200)'),
                                     ('linkedin_id', 'VARCHAR(200)')]:
                    if col not in existing_users:
                        conn.execute(db.text(f'ALTER TABLE users ADD COLUMN {col} {typedef}'))
                # Migration colonne expires_at sur courses
                existing_courses = [row[1] for row in conn.execute(
                    db.text("PRAGMA table_info(courses)")
                ).fetchall()]
                if 'expires_at' not in existing_courses:
                    conn.execute(db.text('ALTER TABLE courses ADD COLUMN expires_at DATETIME'))
                conn.commit()
            else:  # PostgreSQL
                for col in ('google_id', 'linkedin_id'):
                    try:
                        conn.execute(db.text(
                            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} VARCHAR(200) UNIQUE"
                        ))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                # Migration expires_at sur PostgreSQL
                try:
                    conn.execute(db.text(
                        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP"
                    ))
                    conn.commit()
                except Exception:
                    conn.rollback()
    except Exception as e:
        app.logger.warning(f'OAuth migration skipped: {e}')

with app.app_context():
    try:
        db.create_all()
        _run_oauth_migration()
    except Exception as _db_init_err:
        app.logger.error(f'DB init error (non-fatal): {_db_init_err}')

# ── Helpers ───────────────────────────────────────────────────
@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

def allowed_video(f):  return '.' in f and f.rsplit('.', 1)[1].lower() in Config.ALLOWED_VIDEO_EXTENSIONS
def allowed_pdf(f):    return '.' in f and f.rsplit('.', 1)[1].lower() in Config.ALLOWED_PDF_EXTENSIONS
def allowed_image(f):  return '.' in f and f.rsplit('.', 1)[1].lower() in Config.ALLOWED_IMAGE_EXTENSIONS

# Protocoles dangereux et plages IP privées (protection SSRF)
_PRIVATE_IP_RE = re.compile(
    r'^https?://(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)', re.I)
_SAFE_VIDEO_HOSTS = {
    'youtube.com', 'www.youtube.com', 'youtu.be',
    'vimeo.com', 'player.vimeo.com',
    'dailymotion.com', 'dai.ly',
    'drive.google.com',
}

def _validate_external_url(url: str) -> tuple[bool, str]:
    """Valide une URL externe pour les vidéos en ligne.
    Retourne (valide, message_erreur).
    Bloque : javascript:, data:, file://, SSRF vers IPs privées.
    """
    if not url:
        return False, 'URL manquante.'
    url = url.strip()
    parsed = urlparse(url)
    # Protocoles autorisés uniquement
    if parsed.scheme not in ('http', 'https'):
        return False, 'Seules les URLs http:// et https:// sont autorisées.'
    # Bloquer les IPs privées (SSRF)
    if _PRIVATE_IP_RE.match(url):
        return False, 'Les URLs vers des adresses locales sont interdites.'
    # Hôte valide requis
    if not parsed.netloc or '.' not in parsed.netloc:
        return False, 'URL invalide (domaine manquant).'
    return True, ''

def _extract_playlist_id(url: str) -> str | None:
    """Extract YouTube playlist ID from a playlist URL."""
    if not url: return None
    import re
    m = re.search(r'list=([A-Za-z0-9_-]+)', url)
    return m.group(1) if m else None

def role_required(*roles):
    def deco(f):
        @wraps(f)
        def inner(*a, **kw):
            if not current_user.is_authenticated or current_user.role not in roles:
                flash('Acces non autorise.', 'danger')
                return redirect(url_for('home'))
            return f(*a, **kw)
        return inner
    return deco

def get_lang(): return (current_user.language if current_user.is_authenticated
                        else session.get('lang', 'fr'))

def _is_safe_url(target: str) -> bool:
    """Vérifie qu'une URL de redirection est interne (protection open-redirect)."""
    if not target:
        return False
    ref_url  = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

@app.after_request
def add_security_headers(response):
    """Ajoute des en-têtes de sécurité HTTP sur toutes les réponses."""
    response.headers.setdefault('X-Content-Type-Options',  'nosniff')
    response.headers.setdefault('X-Frame-Options',         'SAMEORIGIN')
    response.headers.setdefault('X-XSS-Protection',        '1; mode=block')
    response.headers.setdefault('Referrer-Policy',         'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy',
        'camera=(), microphone=(), geolocation=(), payment=()')

    # ── HSTS : forcer HTTPS (activé uniquement en production) ──────────────
    if not app.debug and request.is_secure:
        response.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
        )

    # ── Content Security Policy ────────────────────────────────────────────
    # Bloque les scripts/ressources externes non autorisés tout en permettant
    # Bootstrap CDN, FontAwesome, Google Fonts, YouTube embeds, Supabase.
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
            "cdn.jsdelivr.net cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' "
            "fonts.googleapis.com cdn.jsdelivr.net cdnjs.cloudflare.com; "
        "font-src 'self' fonts.gstatic.com cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob: https:; "
        "frame-src 'self' www.youtube-nocookie.com www.youtube.com; "
        "connect-src 'self' https://*.supabase.co wss://*.supabase.co "
            "https://api.moneroo.io "
            "https://generativelanguage.googleapis.com; "
        "media-src 'self' blob:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers.setdefault('Content-Security-Policy', csp)
    return response

def _recalc_progress(student_id: int, course_id: int):
    """Recompute course progress based on completed videos only (>= 90%)."""
    course   = Course.query.get(course_id)
    total    = course.videos.filter_by(is_approved=True).count()
    if total == 0: return
    completed_count = 0
    total_time = 0
    for v in course.videos.filter_by(is_approved=True).all():
        vp = VideoProgress.query.filter_by(user_id=student_id, video_id=v.id).first()
        if vp and vp.completed:
            completed_count += 1
            total_time += vp.total_time_seconds
    progress_pct = (completed_count / total) * 100
    enroll = Enrollment.query.filter_by(student_id=student_id, course_id=course_id).first()
    if enroll:
        enroll.progress = progress_pct
        enroll.total_time_seconds = total_time
        enroll.completed = (progress_pct >= 100)
        db.session.commit()

# ── Context processor ─────────────────────────────────────────
@app.context_processor
def _globals():
    notifs, unread = [], 0
    pending_courses_count = 0
    if current_user.is_authenticated:
        notifs = (Notification.query
                  .filter_by(user_id=current_user.id, is_read=False)
                  .order_by(Notification.created_at.desc()).limit(5).all())
        unread = len(notifs)
        if current_user.role == 'admin':
            pending_courses_count = Course.query.filter_by(approval_status='pending').count()
    return dict(notifications=notifs, unread_count=unread,
                current_lang=get_lang(), now=datetime.utcnow(),
                pending_courses_count=pending_courses_count)

# ══════════════════════════════════════════════════════════════
#  SEO — SITEMAP + ROBOTS
# ══════════════════════════════════════════════════════════════
@app.route('/sitemap.xml')
def sitemap():
    """Sitemap dynamique pour Google — toutes les pages publiques de SECEL."""
    BASE = request.url_root.rstrip('/')

    # Pages statiques avec leur priorité
    static_pages = [
        ('/',           '1.0', 'daily'),
        ('/courses',    '0.9', 'daily'),
        ('/login',      '0.5', 'monthly'),
        ('/register',   '0.5', 'monthly'),
    ]

    # Cours publiés et approuvés
    courses = (Course.query
               .filter_by(is_published=True, approval_status='approved')
               .order_by(Course.updated_at.desc()).all())

    # Enseignants publics (avec au moins 1 cours publié)
    teachers = (User.query.filter_by(role='teacher', is_active=True)
                .join(Course, Course.teacher_id == User.id)
                .filter(Course.is_published == True)
                .distinct().all())

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']

    for path, priority, freq in static_pages:
        lines.append(f'''  <url>
    <loc>{BASE}{path}</loc>
    <changefreq>{freq}</changefreq>
    <priority>{priority}</priority>
  </url>''')

    for c in courses:
        lastmod = (c.updated_at or c.created_at or datetime.utcnow()).strftime('%Y-%m-%d')
        lines.append(f'''  <url>
    <loc>{BASE}/course/{c.id}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.8</priority>
  </url>''')

    for t in teachers:
        lines.append(f'''  <url>
    <loc>{BASE}/teacher/{t.id}</loc>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>''')

    lines.append('</urlset>')
    return Response('\n'.join(lines), mimetype='application/xml',
                    headers={'Cache-Control': 'public, max-age=3600'})


@app.route('/robots.txt')
def robots():
    """robots.txt — autorise Google à indexer les pages publiques uniquement."""
    BASE = request.url_root.rstrip('/')
    content = f"""User-agent: *
Allow: /
Allow: /courses
Allow: /course/
Allow: /login
Allow: /register

Disallow: /admin/
Disallow: /student/
Disallow: /teacher/
Disallow: /api/
Disallow: /uploads/
Disallow: /payment/
Disallow: /auth/

# Pas de crawl sur les pages de tri (éviter contenu dupliqué)
Disallow: /*?sort=
Disallow: /*?page=

Sitemap: {BASE}/sitemap.xml
"""
    return Response(content, mimetype='text/plain')


# ══════════════════════════════════════════════════════════════
#  PUBLIC ROUTES
# ══════════════════════════════════════════════════════════════
@app.route('/')
@_simple_cache(ttl=300)   # Cache 5 min — page d'accueil très visitée par Google
def index():
    # Authenticated users go straight to their dashboard
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    stats = {
        'students': User.query.filter_by(role='student').count(),
        'teachers': User.query.filter_by(role='teacher').count(),
        'courses':  Course.query.filter_by(is_published=True).count(),
        'videos':   Video.query.filter_by(is_approved=True).count(),
    }
    featured = Course.query.filter_by(is_published=True).limit(6).all()
    return render_template('index.html', stats=stats, featured_courses=featured)

@app.route('/set-lang/<lang>')
def set_lang(lang):
    if lang in ['fr', 'en', 'zh']:
        session['lang'] = lang
        if current_user.is_authenticated:
            current_user.language = lang
            db.session.commit()
    return redirect(request.referrer or url_for('index'))

# ══════════════════════════════════════════════════════════════
#  AUTH — COMMON LOGIN
# ══════════════════════════════════════════════════════════════
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", error_message='Trop de tentatives. Réessayez dans 1 minute.')
def login():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))
        user     = User.query.filter_by(email=email).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash(f'Bienvenue, {user.full_name or user.username} !', 'success')
            # Protection open-redirect : rejeter les URLs externes
            next_page = request.args.get('next', '')
            if next_page and not _is_safe_url(next_page):
                next_page = ''
            return redirect(next_page or url_for('home'))
        flash('Email ou mot de passe incorrect.', 'danger')
    return render_template('auth/login.html')

# ── OAuth — Google ─────────────────────────────────────────────
@app.route('/auth/google')
def auth_google():
    if current_user.is_authenticated: return redirect(url_for('home'))
    redirect_uri = url_for('auth_google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/auth/google/callback')
def auth_google_callback():
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo') or oauth.google.userinfo()
        google_id = str(userinfo.get('sub', ''))
        email     = userinfo.get('email', '')
        full_name = userinfo.get('name', '')
        user = _oauth_find_or_create('google_id', google_id, email, full_name)
        login_user(user, remember=True)
        user.last_login = datetime.utcnow()
        db.session.commit()
        flash(f'Bienvenue, {user.full_name or user.username} !', 'success')
        return redirect(url_for('home'))
    except Exception as e:
        flash('Connexion Google échouée. Réessayez.', 'danger')
        app.logger.error(f'Google OAuth error: {e}')
        return redirect(url_for('login'))

# ── OAuth — LinkedIn ───────────────────────────────────────────
@app.route('/auth/linkedin')
def auth_linkedin():
    if current_user.is_authenticated: return redirect(url_for('home'))
    redirect_uri = url_for('auth_linkedin_callback', _external=True)
    return oauth.linkedin.authorize_redirect(redirect_uri)

@app.route('/auth/linkedin/callback')
def auth_linkedin_callback():
    try:
        token = oauth.linkedin.authorize_access_token()
        # LinkedIn OpenID Connect userinfo endpoint
        resp = oauth.linkedin.get(
            'https://api.linkedin.com/v2/userinfo',
            token=token
        )
        userinfo  = resp.json()
        linkedin_id = str(userinfo.get('sub', ''))
        email       = userinfo.get('email', '')
        full_name   = userinfo.get('name', '')
        user = _oauth_find_or_create('linkedin_id', linkedin_id, email, full_name)
        login_user(user, remember=True)
        user.last_login = datetime.utcnow()
        db.session.commit()
        flash(f'Bienvenue, {user.full_name or user.username} !', 'success')
        return redirect(url_for('home'))
    except Exception as e:
        flash('Connexion LinkedIn échouée. Réessayez.', 'danger')
        app.logger.error(f'LinkedIn OAuth error: {e}')
        return redirect(url_for('login'))

# ── Registration: choose role ──────────────────────────────────
@app.route('/register')
def register():
    return render_template('auth/register_choose.html')

@app.route('/register/student', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=['POST'],
               error_message='Trop de tentatives d\'inscription. Réessayez dans quelques minutes.')
def register_student():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        user = _create_user(request.form, 'student')
        if user:
            login_user(user)
            flash('Bienvenue sur SECEL, etudiant(e) !', 'success')
            return redirect(url_for('student_dashboard'))
    return render_template('auth/register_student.html')

@app.route('/register/teacher', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=['POST'],
               error_message='Trop de tentatives d\'inscription. Réessayez dans quelques minutes.')
def register_teacher():
    if current_user.is_authenticated: return redirect(url_for('home'))
    if request.method == 'POST':
        user = _create_user(request.form, 'teacher')
        if user:
            # ⚠️  BUG FIX: les enseignants nécessitent une validation admin avant
            # de pouvoir accéder à la plateforme. On ne les connecte pas
            # automatiquement — on les redirige vers la page de connexion avec
            # un message explicatif.
            flash(
                'Votre compte enseignant a été créé et est en attente de '
                'validation par l\'équipe SECEL. Vous recevrez un email dès '
                'que votre compte sera activé.',
                'warning'
            )
            # Notifier les admins d'un nouveau compte enseignant à valider
            admins = User.query.filter_by(role='admin').all()
            for admin in admins:
                notif = Notification(
                    user_id    = admin.id,
                    message    = (f'Nouveau compte enseignant en attente de validation : '
                                  f'{user.full_name or user.username} ({user.email})'),
                    notif_type = 'info'
                )
                db.session.add(notif)
            db.session.commit()
            # Realtime : notifier les admins connectés
            for admin in admins:
                notify_realtime(
                    admin.id,
                    f'Nouvel enseignant à valider : {user.full_name or user.username}',
                    'info'
                )
            return redirect(url_for('login'))
    return render_template('auth/register_teacher.html')

def _create_user(form, role):
    username = form.get('username', '').strip()
    email    = form.get('email', '').strip()
    password = form.get('password', '')
    confirm  = form.get('confirm_password', '')

    # Validations de base
    if len(password) < 8:
        flash('Le mot de passe doit contenir au moins 8 caractères.', 'danger')
        return None
    if password != confirm:
        flash('Les mots de passe ne correspondent pas.', 'danger')
        return None
    if not username or len(username) < 3:
        flash("Le nom d'utilisateur doit contenir au moins 3 caractères.", 'danger')
        return None
    if User.query.filter_by(email=email).first():
        flash('Cette adresse email est déjà utilisée.', 'danger')
        return None
    if User.query.filter_by(username=username).first():
        flash("Ce nom d'utilisateur est déjà pris.", 'danger')
        return None

    # ⚠️  BUG FIX: les enseignants sont inactifs par défaut (validation admin requise)
    is_active = (role != 'teacher')

    user = User(username=username, email=email,
                full_name=form.get('full_name', '').strip(),
                role=role, is_active=is_active)
    user.set_password(password)
    user.phone    = form.get('phone', '').strip() or None
    user.language = form.get('language', 'fr')

    if role == 'student':
        user.learning_goals  = form.get('learning_goals', '')
        user.student_level   = form.get('student_level', 'Debutant')
    elif role == 'teacher':
        user.specialty       = form.get('specialty', '')
        user.qualifications  = form.get('qualifications', '')
        user.portfolio_url   = form.get('portfolio_url', '')
        user.years_experience= int(form.get('years_experience', 0) or 0)
    db.session.add(user)
    db.session.commit()
    notif = Notification(user_id=user.id,
                         message=f'Bienvenue sur SECEL, {user.full_name or username} !',
                         notif_type='success')
    db.session.add(notif)
    db.session.commit()
    return user

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Deconnecte avec succes.', 'info')
    return redirect(url_for('index'))

# ── Home redirect ─────────────────────────────────────────────
@app.route('/home')
@login_required
def home():
    if current_user.role == 'admin':    return redirect(url_for('admin_dashboard'))
    if current_user.role == 'teacher':  return redirect(url_for('teacher_dashboard'))
    return redirect(url_for('student_dashboard'))

# ══════════════════════════════════════════════════════════════
#  STUDENT
# ══════════════════════════════════════════════════════════════
@app.route('/student/dashboard')
@login_required
@role_required('student')
def student_dashboard():
    enrollments  = Enrollment.query.filter_by(student_id=current_user.id).all()
    watch_history = (WatchHistory.query.filter_by(user_id=current_user.id)
                     .order_by(WatchHistory.watched_at.desc()).limit(10).all())

    # KPI stats
    total_watch_secs  = sum(e.total_time_seconds for e in enrollments)
    total_watch_hours = round(total_watch_secs / 3600, 1)
    videos_completed  = (VideoProgress.query
                         .filter_by(user_id=current_user.id, completed=True).count())
    avg_progress      = (sum(e.progress for e in enrollments) / len(enrollments)
                         if enrollments else 0)

    # Donut chart: [completed, in-progress, not-started]
    done_count    = sum(1 for e in enrollments if e.completed)
    active_count  = sum(1 for e in enrollments if not e.completed and e.progress > 0)
    unstarted     = len(enrollments) - done_count - active_count
    enroll_chart_data = {'donut': [done_count, active_count, unstarted]}

    # Weekly watch bar (minutes per day, last 7 days)
    weekly_watch_data = []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        mins = (db.session.query(db.func.sum(WatchHistory.watch_duration))
                .filter(WatchHistory.user_id == current_user.id,
                        db.func.date(WatchHistory.watched_at) == d.date())
                .scalar() or 0) // 60
        weekly_watch_data.append(int(mins))

    return render_template('student/dashboard.html',
                           enrollments=enrollments,
                           watch_history=watch_history,
                           total_watch_hours=total_watch_hours,
                           videos_completed=videos_completed,
                           avg_progress=avg_progress,
                           enroll_chart_data=enroll_chart_data,
                           weekly_watch_data=weekly_watch_data)

@app.route('/student/enroll/<int:course_id>', methods=['POST'])
@login_required
def enroll(course_id):
    course = Course.query.get_or_404(course_id)

    # Vérifier que le cours est publié (sauf pour admin)
    if not course.is_published and current_user.role != 'admin':
        flash('Ce cours n\'est pas encore disponible.', 'warning')
        return redirect(url_for('course_detail', course_id=course_id))

    # Vérifier si déjà inscrit
    existing = Enrollment.query.filter_by(student_id=current_user.id,
                                          course_id=course_id).first()
    if existing:
        flash('Vous êtes déjà inscrit à ce cours.', 'info')
        return redirect(url_for('course_detail', course_id=course_id))

    # Admin : inscription gratuite et immédiate
    if current_user.role == 'admin':
        enroll_obj = Enrollment(student_id=current_user.id, course_id=course_id)
        db.session.add(enroll_obj)
        db.session.commit()
        flash(f'Inscrit avec succès au cours "{course.title}" ! (accès admin)', 'success')
        return redirect(url_for('course_detail', course_id=course_id))

    # Enseignant propriétaire du cours : inscription gratuite
    if current_user.role == 'teacher' and course.teacher_id == current_user.id:
        enroll_obj = Enrollment(student_id=current_user.id, course_id=course_id)
        db.session.add(enroll_obj)
        db.session.commit()
        flash(f'Inscrit à votre propre cours "{course.title}" !', 'success')
        return redirect(url_for('course_detail', course_id=course_id))

    # Étudiant ou enseignant non-propriétaire : vérifier si le cours est payant
    if not course.is_free and course.price > 0:
        # Vérifier si un paiement validé existe pour ce cours
        paid = Payment.query.filter_by(
            user_id=current_user.id,
            course_id=course_id,
            status='success'
        ).first()
        if not paid:
            flash(
                f'Ce cours coûte {course.price:,.0f} {course.currency}. '
                f'Veuillez procéder au paiement pour vous inscrire.',
                'warning'
            )
            return redirect(url_for('course_detail', course_id=course_id))

    # Inscription (étudiant — cours gratuit ou paiement confirmé)
    enroll_obj = Enrollment(student_id=current_user.id, course_id=course_id)
    db.session.add(enroll_obj)
    db.session.commit()

    # Notification à l'enseignant (realtime)
    notif_msg = (f'{current_user.full_name or current_user.username} '
                 f's\'est inscrit à votre cours "{course.title}".')
    db.session.add(Notification(
        user_id=course.teacher_id, message=notif_msg, notif_type='success'
    ))
    db.session.commit()
    notify_realtime(course.teacher_id, notif_msg, 'success')

    flash(f'Inscrit avec succès à "{course.title}" !', 'success')
    return redirect(url_for('course_detail', course_id=course_id))

# ══════════════════════════════════════════════════════════════
#  TEACHER
# ══════════════════════════════════════════════════════════════
@app.route('/teacher/dashboard')
@login_required
@role_required('teacher')
def teacher_dashboard():
    courses        = Course.query.filter_by(teacher_id=current_user.id).all()
    pending_videos = (Video.query.join(Course)
                      .filter(Course.teacher_id == current_user.id,
                              Video.is_approved == False).all())
    total_students = (db.session.query(db.func.count(Enrollment.id))
                      .join(Course).filter(Course.teacher_id == current_user.id)
                      .scalar() or 0)
    total_views    = (db.session.query(db.func.sum(Video.watch_count))
                      .join(Course).filter(Course.teacher_id == current_user.id)
                      .scalar() or 0) or 0
    total_videos   = (db.session.query(db.func.count(Video.id))
                      .join(Course).filter(Course.teacher_id == current_user.id,
                                           Video.is_approved == True)
                      .scalar() or 0)

    # Bar chart: enrollments per course
    enroll_bar_data = {
        'labels': [c.title[:18] + ('…' if len(c.title) > 18 else '') for c in courses],
        'values': [c.enrollments.count() for c in courses],
    }

    # Line chart: video views last 7 days (WatchHistory by date)
    views_line_data = []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        cnt = (db.session.query(db.func.count(WatchHistory.id))
               .join(Video).join(Course)
               .filter(Course.teacher_id == current_user.id,
                       db.func.date(WatchHistory.watched_at) == d.date())
               .scalar() or 0)
        views_line_data.append(int(cnt))

    return render_template('teacher/dashboard.html',
                           courses=courses,
                           pending_videos=pending_videos,
                           total_students=total_students,
                           total_views=total_views,
                           total_videos=total_videos,
                           enroll_bar_data=enroll_bar_data,
                           views_line_data=views_line_data)

@app.route('/teacher/course/new', methods=['GET', 'POST'])
@login_required
@role_required('teacher', 'admin')
def new_course():
    if request.method == 'POST':
        price       = float(request.form.get('price', 0) or 0)
        is_free     = price == 0
        course_type = request.form.get('course_type', 'video')
        # Admin-created courses are auto-approved and published
        is_admin    = current_user.role == 'admin'
        expires_raw = request.form.get('expires_at', '').strip()
        expires_at  = None
        if expires_raw:
            try:
                expires_at = datetime.strptime(expires_raw, '%Y-%m-%d')
            except ValueError:
                pass
        course = Course(
            title               = request.form.get('title'),
            description         = request.form.get('description'),
            category            = request.form.get('category'),
            level               = request.form.get('level', 'Debutant'),
            price               = price,
            currency            = 'FCFA',
            is_free             = is_free,
            teacher_id          = current_user.id,
            course_type         = course_type,
            is_approved         = is_admin,
            approval_status     = 'approved' if is_admin else 'pending',
            is_published        = is_admin,
            expires_at          = expires_at,
        )
        db.session.add(course)
        db.session.commit()
        if course_type == 'ebook':
            flash('Cours eBook créé ! Uploadez maintenant la couverture et le PDF.', 'success')
            return redirect(url_for('upload_ebook', course_id=course.id))
        else:
            flash('Cours créé ! Ajoutez maintenant des vidéos.', 'success')
            return redirect(url_for('upload_content', course_id=course.id))
    return render_template('teacher/new_course.html', now=datetime.utcnow())

@app.route('/teacher/course/<int:course_id>/upload', methods=['GET', 'POST'])
@login_required
@role_required('teacher', 'admin')
def upload_content(course_id):
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        content_type = request.form.get('content_type', 'video')
        title        = request.form.get('title', '').strip()
        description  = request.form.get('description', '').strip()

        if content_type == 'video':
            video_type = request.form.get('video_type', 'local')
            order_idx  = Video.query.filter_by(course_id=course_id).count() + 1
            duration   = int(request.form.get('duration_seconds', 0) or 0)
            vid        = None

            if video_type == 'local' and 'video_file' in request.files:
                f = request.files['video_file']
                if f and f.filename and allowed_video(f.filename):
                    # Sur Vercel les uploads vidéo locaux sont impossibles (limite 50 MB)
                    if os.environ.get('VERCEL'):
                        if is_ajax:
                            return jsonify({'success': False, 'message': 'Upload vidéo local non disponible sur Vercel. Utilisez une URL YouTube ou externe.'}), 400
                        flash('Upload vidéo local non disponible en production. Utilisez une URL YouTube.', 'warning')
                    else:
                        stored = upload_file_as_path(f, 'video')
                        vid = Video(title=title or f.filename, description=description,
                                    course_id=course_id, file_path=stored,
                                    is_local=not is_supabase_url(stored), order_index=order_idx,
                                    duration_seconds=duration)
                        db.session.add(vid)
                        db.session.commit()
                    if not is_ajax:
                        flash('Vidéo locale uploadée ! En attente de validation admin.', 'success')
                elif is_ajax:
                    return jsonify({'success': False, 'message': 'Format de fichier invalide.'}), 400
            elif video_type == 'online':
                ext_url = request.form.get('external_url', '').strip()
                url_ok, url_err = _validate_external_url(ext_url)
                if url_ok:
                    vid = Video(title=title or 'Vidéo sans titre', description=description,
                                course_id=course_id, external_url=ext_url,
                                is_local=False, order_index=order_idx,
                                duration_seconds=duration)
                    db.session.add(vid)
                    db.session.commit()
                    if not is_ajax:
                        flash('Vidéo en ligne ajoutée ! En attente de validation.', 'success')
                else:
                    if is_ajax:
                        return jsonify({'success': False, 'message': url_err}), 400
                    flash(f'URL invalide : {url_err}', 'danger')

            if is_ajax:
                if vid:
                    return jsonify({
                        'success': True,
                        'video_id': vid.id,
                        'title': vid.title,
                        'is_local': vid.is_local,
                        'message': 'Vidéo ajoutée avec succès !'
                    })
                return jsonify({'success': False, 'message': 'Erreur lors de l\'ajout.'}), 400

        elif content_type == 'pdf':
            if 'pdf_file' in request.files:
                f = request.files['pdf_file']
                if f and f.filename and allowed_pdf(f.filename):
                    # Vérifier la taille (lecture partielle pour éviter de charger en RAM)
                    f.seek(0, 2)
                    file_size = f.tell()
                    f.seek(0)
                    if file_size > Config.MAX_PDF_SIZE_BYTES:
                        flash(f'PDF trop volumineux (max {Config.MAX_PDF_SIZE_BYTES // (1024*1024)} MB).', 'danger')
                    else:
                        stored = upload_file_as_path(f, 'pdf')
                        pdf = PDFContent(title=title, description=description,
                                         course_id=course_id, file_path=stored)
                        db.session.add(pdf)
                        db.session.commit()
                        flash('PDF uploadé ! En attente de validation.', 'success')

        elif content_type == 'playlist' and current_user.role == 'admin':
            playlist_url = request.form.get('youtube_playlist_url', '').strip()
            if playlist_url:
                course.youtube_playlist_url = playlist_url
                db.session.commit()
                flash('Playlist YouTube enregistrée.', 'success')

        return redirect(url_for('upload_content', course_id=course_id))

    videos = Video.query.filter_by(course_id=course_id).order_by(Video.order_index).all()
    pdfs   = PDFContent.query.filter_by(course_id=course_id).all()
    return render_template('teacher/upload_content.html', course=course,
                           videos=videos, pdfs=pdfs)

@app.route('/teacher/course/<int:course_id>/upload-ebook', methods=['GET', 'POST'])
@login_required
@role_required('teacher', 'admin')
def upload_ebook(course_id):
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)
    if course.course_type != 'ebook':
        return redirect(url_for('upload_content', course_id=course_id))

    if request.method == 'POST':
        file_type = request.form.get('_file_type', 'both')
        updated   = False

        # ── Cover image ───────────────────────────────────────────
        if file_type in ('cover', 'both'):
            cover_file = request.files.get('cover_image')
            if cover_file and cover_file.filename and allowed_image(cover_file.filename):
                cover_file.seek(0, 2); cover_size = cover_file.tell(); cover_file.seek(0)
                if cover_size > Config.MAX_IMAGE_SIZE_BYTES:
                    return jsonify({'success': False, 'message': f'Image trop volumineuse (max {Config.MAX_IMAGE_SIZE_BYTES//(1024*1024)} MB).'}), 400
                delete_file(course.ebook_cover)
                course.ebook_cover = upload_file_as_path(cover_file, 'cover')
                updated = True

        # ── eBook PDF ─────────────────────────────────────────────
        if file_type in ('pdf', 'both'):
            pdf_file = request.files.get('ebook_pdf')
            if pdf_file and pdf_file.filename and allowed_pdf(pdf_file.filename):
                pdf_file.seek(0, 2); ebook_size = pdf_file.tell(); pdf_file.seek(0)
                if ebook_size > Config.MAX_PDF_SIZE_BYTES:
                    return jsonify({'success': False, 'message': f'PDF trop volumineux (max {Config.MAX_PDF_SIZE_BYTES//(1024*1024)} MB).'}), 400
                delete_file(course.ebook_file)
                course.ebook_file = upload_file_as_path(pdf_file, 'ebook')
                updated = True

        if updated:
            db.session.commit()
            flash('eBook mis à jour avec succès !', 'success')
        else:
            flash('Aucun fichier valide reçu.', 'warning')

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if is_ajax:
            cover_val = course.ebook_cover
            cover_url = cover_val if is_supabase_url(cover_val) else (url_for('static', filename=cover_val) if cover_val else None)
            return jsonify({'success': updated, 'cover_url': cover_url, 'has_pdf': bool(course.ebook_file)})
        return redirect(url_for('upload_ebook', course_id=course_id))

    return render_template('teacher/upload_ebook.html', course=course)


@app.route('/teacher/course/<int:course_id>/delete-ebook-file', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def delete_ebook_file(course_id):
    """Delete the ebook PDF file from disk and clear the DB field."""
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)
    if course.ebook_file:
        delete_file(course.ebook_file)
        course.ebook_file = None
        db.session.commit()
        flash('PDF supprimé avec succès.', 'success')
    else:
        flash('Aucun PDF à supprimer.', 'info')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return jsonify({'success': True, 'message': 'PDF supprimé.'})
    return redirect(url_for('upload_ebook', course_id=course_id))


@app.route('/teacher/course/<int:course_id>/delete-ebook-cover', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def delete_ebook_cover(course_id):
    """Delete the ebook cover image from disk and clear the DB field."""
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)
    if course.ebook_cover:
        delete_file(course.ebook_cover)
        course.ebook_cover = None
        db.session.commit()
        flash('Image de couverture supprimée.', 'success')
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return jsonify({'success': True})
    return redirect(url_for('upload_ebook', course_id=course_id))


@app.route('/teacher/course/<int:course_id>/edit', methods=['GET'])
@login_required
@role_required('teacher', 'admin')
def edit_course(course_id):
    """Page d'édition du cours (titre, description, prix, thumbnail…)."""
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin':
        abort(403)
    return render_template('teacher/edit_course.html', course=course, now=datetime.utcnow())


@app.route('/teacher/course/<int:course_id>/update', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def update_course(course_id):
    """Update course meta-info (title, desc, thumbnail, price, category, level)."""
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    os.makedirs(Config.STATIC_UPLOAD_FOLDER, exist_ok=True)

    # Text fields
    new_title = request.form.get('title', '').strip()
    if new_title:
        course.title = new_title
    course.description = request.form.get('description', course.description or '').strip()
    cat = request.form.get('category', '').strip()
    if cat:
        course.category = cat
    lvl = request.form.get('level', '').strip()
    if lvl:
        course.level = lvl

    # Price — always FCFA
    try:
        price_val = float(request.form.get('price', course.price or 0) or 0)
    except (ValueError, TypeError):
        price_val = 0.0
    course.price    = price_val
    course.is_free  = (price_val == 0)
    course.currency = 'XAF'

    # Thumbnail upload
    thumb_file = request.files.get('thumbnail')
    thumb_url  = None
    if thumb_file and thumb_file.filename and allowed_image(thumb_file.filename):
        thumb_file.seek(0, 2); thumb_size = thumb_file.tell(); thumb_file.seek(0)
        if thumb_size > Config.MAX_IMAGE_SIZE_BYTES:
            if is_ajax:
                return jsonify({'success': False, 'message': f'Image trop volumineuse (max {Config.MAX_IMAGE_SIZE_BYTES//(1024*1024)} MB).'}), 400
            flash(f'Image trop volumineuse (max {Config.MAX_IMAGE_SIZE_BYTES//(1024*1024)} MB).', 'danger')
            thumb_file = None
    if thumb_file and thumb_file.filename and allowed_image(thumb_file.filename):
        delete_file(course.thumbnail)
        stored = upload_file(thumb_file, 'thumb')
        course.thumbnail = stored
        thumb_url = stored if is_supabase_url(stored) else url_for('static', filename=f'uploads/{stored}')

    # Expiration date
    expires_raw = request.form.get('expires_at', '').strip()
    if expires_raw:
        try:
            course.expires_at = datetime.strptime(expires_raw, '%Y-%m-%d')
        except ValueError:
            pass
    elif request.form.get('expires_at') == '':
        # Champ soumis vide = supprimer l'expiration
        course.expires_at = None

    course.updated_at = datetime.utcnow()
    db.session.commit()

    if is_ajax:
        return jsonify({
            'success': True,
            'message': 'Cours mis à jour !',
            'title': course.title,
            'thumb_url': thumb_url,
        })
    flash('Cours mis à jour avec succès !', 'success')
    return redirect(request.referrer or url_for('upload_content', course_id=course_id))


@app.route('/teacher/video/<int:video_id>/delete', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def delete_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)
    if video.file_path:
        delete_file(video.file_path)
    db.session.delete(video)
    db.session.commit()
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return jsonify({'success': True})
    flash('Vidéo supprimée.', 'success')
    return redirect(request.referrer or url_for('teacher_dashboard'))

@app.route('/teacher/video/<int:video_id>/edit', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def edit_video(video_id):
    video = Video.query.get_or_404(video_id)
    if video.course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)
    new_title = request.form.get('title', '').strip()
    if new_title:
        video.title = new_title
    video.description = request.form.get('description', video.description or '')
    dur = request.form.get('duration_seconds', '').strip()
    if dur.isdigit():
        video.duration_seconds = int(dur)
    if not video.is_local:
        new_url = request.form.get('external_url', '').strip()
        if new_url:
            video.external_url = new_url
    db.session.commit()
    return jsonify({'success': True, 'title': video.title, 'description': video.description})

@app.route('/teacher/course/<int:course_id>/reorder-videos', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def reorder_videos(course_id):
    course = Course.query.get_or_404(course_id)
    if course.teacher_id != current_user.id and current_user.role != 'admin': abort(403)
    data  = request.get_json(silent=True) or {}
    order = data.get('order', [])
    for idx, vid_id in enumerate(order, 1):
        v = Video.query.filter_by(id=int(vid_id), course_id=course_id).first()
        if v:
            v.order_index = idx
    db.session.commit()
    return jsonify({'success': True})

# ══════════════════════════════════════════════════════════════
#  ADMIN  (completely separate section)
# ══════════════════════════════════════════════════════════════
@app.route('/admin')
@app.route('/admin/dashboard')
@login_required
@role_required('admin')
def admin_dashboard():
    total_users       = User.query.count()
    total_students    = User.query.filter_by(role='student').count()
    total_teachers    = User.query.filter_by(role='teacher').count()
    total_courses     = Course.query.count()                              # TOUS les cours réels
    courses_published = Course.query.filter_by(is_published=True).count()
    courses_pending   = Course.query.filter_by(approval_status='pending').count()
    total_enrollments = Enrollment.query.count()
    pending_count     = Video.query.filter_by(is_approved=False).count()
    pending_vids      = Video.query.filter_by(is_approved=False).all()
    pending_courses_count = Course.query.filter_by(approval_status='pending').count()
    all_users      = User.query.order_by(User.created_at.desc()).all()
    recent_courses = Course.query.order_by(Course.created_at.desc()).limit(15).all()
    pay_stats      = get_payment_stats()
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(10).all()

    # Chart: user registrations last 7 days
    reg_labels, reg_data = [], []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        cnt = (User.query.filter(
                   db.func.date(User.created_at) == d.date()
               ).count())
        reg_labels.append(d.strftime('%d/%m'))
        reg_data.append(cnt)

    # Chart: enrollments last 7 days
    enroll_labels, enroll_data_7 = [], []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        cnt = (Enrollment.query.filter(
                   db.func.date(Enrollment.enrolled_at) == d.date()
               ).count())
        enroll_labels.append(d.strftime('%d/%m'))
        enroll_data_7.append(cnt)

    # Chart: users by role (donut)
    role_data = [total_students, total_teachers,
                 User.query.filter_by(role='admin').count()]

    # Chart: courses by category
    cat_rows = (db.session.query(Course.category, db.func.count(Course.id))
                .group_by(Course.category).all())
    cat_labels = [r[0] or 'Autre' for r in cat_rows]
    cat_data   = [r[1] for r in cat_rows]

    return render_template('admin/dashboard.html',
                           total_users=total_users, total_students=total_students,
                           total_teachers=total_teachers, total_courses=total_courses,
                           courses_published=courses_published, courses_pending=courses_pending,
                           total_enrollments=total_enrollments,
                           pending_count=pending_count, pending_vids=pending_vids,
                           pending_courses_count=pending_courses_count,
                           all_users=all_users, recent_courses=recent_courses,
                           pay_stats=pay_stats, recent_payments=recent_payments,
                           reg_labels=reg_labels, reg_data=reg_data,
                           enroll_labels=enroll_labels, enroll_data_7=enroll_data_7,
                           role_data=role_data,
                           cat_labels=cat_labels, cat_data=cat_data)

@app.route('/admin/users')
@login_required
@role_required('admin')
def admin_users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', all_users=all_users)

@app.route('/admin/payments')
@login_required
@role_required('admin')
def admin_payments():
    payments = Payment.query.order_by(Payment.created_at.desc()).all()
    stats    = get_payment_stats()
    return render_template('admin/payments.html', payments=payments, stats=stats)

@app.route('/admin/video/<int:video_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_video(video_id):
    video = Video.query.get_or_404(video_id)
    video.is_approved = True
    if not video.course.is_published:
        video.course.is_published = True
    db.session.commit()
    msg = f'Votre vidéo "{video.title}" a été approuvée et est maintenant visible !'
    notif = Notification(user_id=video.course.teacher_id, message=msg, notif_type='success')
    db.session.add(notif)
    db.session.commit()
    notify_realtime(video.course.teacher_id, msg, 'success')
    flash(f'Vidéo "{video.title}" approuvée.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/video/<int:video_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_video(video_id):
    video = Video.query.get_or_404(video_id)
    tid, ttl = video.course.teacher_id, video.title
    reason = request.form.get('reason', '').strip()
    if video.file_path:
        delete_file(video.file_path)
    db.session.delete(video)
    db.session.commit()
    msg = f'Votre vidéo "{ttl}" a été refusée.'
    if reason: msg += f' Raison : {reason}'
    db.session.add(Notification(user_id=tid, message=msg, notif_type='warning'))
    db.session.commit()
    notify_realtime(tid, msg, 'warning')
    flash(f'Vidéo "{ttl}" rejetée.', 'warning')
    return redirect(request.referrer or url_for('admin_dashboard'))

@app.route('/admin/courses/approval')
@login_required
@role_required('admin')
def admin_courses_approval():
    pending  = Course.query.filter_by(approval_status='pending').order_by(Course.created_at.desc()).all()
    approved = Course.query.filter_by(approval_status='approved').order_by(Course.updated_at.desc()).limit(20).all()
    rejected = Course.query.filter_by(approval_status='rejected').order_by(Course.updated_at.desc()).limit(10).all()
    return render_template('admin/courses_approval.html',
                           pending=pending, approved=approved, rejected=rejected,
                           now=datetime.utcnow())

@app.route('/admin/course/<int:course_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def admin_approve_course(course_id):
    course = Course.query.get_or_404(course_id)
    playlist_url = request.form.get('youtube_playlist_url', '').strip()
    course.is_approved      = True
    course.approval_status  = 'approved'
    course.is_published     = True
    course.rejection_reason = None
    if playlist_url:
        course.youtube_playlist_url = playlist_url
    # Auto-approuver toutes les vidéos et PDFs du cours
    for v in course.videos.all():
        v.is_approved = True
    for p in course.pdfs.all():
        p.is_approved = True
    db.session.commit()
    # Invalider le cache public (nouveau cours visible sur accueil + catalogue)
    _clear_cache('index')
    _clear_cache('courses')
    msg_approve = f'Votre cours "{course.title}" a été approuvé et publié ! Félicitations !'
    db.session.add(Notification(user_id=course.teacher_id, message=msg_approve, notif_type='success'))
    db.session.commit()
    notify_realtime(course.teacher_id, msg_approve, 'success')
    flash(f'Cours "{course.title}" approuvé et publié. {course.videos.count()} vidéo(s) activée(s).', 'success')
    return redirect(url_for('admin_courses_approval'))

@app.route('/admin/course/<int:course_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def admin_reject_course(course_id):
    course = Course.query.get_or_404(course_id)
    reason = request.form.get('rejection_reason', '').strip()
    course.is_approved      = False
    course.approval_status  = 'rejected'
    course.is_published     = False
    course.rejection_reason = reason
    db.session.commit()
    msg_reject = f'Votre cours "{course.title}" a été refusé.'
    if reason: msg_reject += f' Raison : {reason}'
    db.session.add(Notification(user_id=course.teacher_id, message=msg_reject, notif_type='warning'))
    db.session.commit()
    notify_realtime(course.teacher_id, msg_reject, 'warning')
    flash(f'Cours "{course.title}" refusé.', 'warning')
    return redirect(url_for('admin_courses_approval'))

@app.route('/course/<int:course_id>/delete', methods=['POST'])
@login_required
@role_required('teacher', 'admin')
def delete_course(course_id):
    """
    Suppression d'un cours — accessible par :
      • L'enseignant auteur du cours
      • Un administrateur
    Supprime en cascade : vidéos, PDF, inscriptions, progression, historique, paiements liés.
    """
    course = Course.query.get_or_404(course_id)

    # Vérification des droits
    if current_user.role != 'admin' and course.teacher_id != current_user.id:
        abort(403)

    title = course.title  # garder pour le message flash

    # Supprimer tous les fichiers du cours (Supabase Storage ou local)
    for video in course.videos.all():
        if video.file_path:
            delete_file(video.file_path)
    for pdf in course.pdfs.all():
        if pdf.file_path:
            delete_file(pdf.file_path)
    delete_file(course.ebook_cover)
    delete_file(course.ebook_file)
    delete_file(course.thumbnail)

    # Supprimer le cours (SQLAlchemy cascade supprime les enfants)
    db.session.delete(course)
    db.session.commit()

    flash(f'Le cours "{title}" a été supprimé définitivement.', 'success')

    # Rediriger selon le rôle
    if current_user.role == 'admin':
        return redirect(url_for('admin_courses_approval'))
    return redirect(url_for('teacher_dashboard'))


@app.route('/admin/course/<int:course_id>/set-playlist', methods=['POST'])
@login_required
@role_required('admin')
def admin_set_playlist(course_id):
    course = Course.query.get_or_404(course_id)
    playlist_url = request.form.get('youtube_playlist_url', '').strip()
    course.youtube_playlist_url = playlist_url or None
    db.session.commit()
    flash('Playlist YouTube mise à jour.', 'success')
    return redirect(url_for('upload_content', course_id=course_id))

@app.route('/admin/enrollments')
@login_required
@role_required('admin')
def admin_enrollments():
    course_id = request.args.get('course_id', type=int)
    q = (Enrollment.query
         .join(User, Enrollment.student_id == User.id)
         .join(Course, Enrollment.course_id == Course.id))
    if course_id:
        q = q.filter(Enrollment.course_id == course_id)
    enrollments = q.order_by(Enrollment.enrolled_at.desc()).all()
    courses     = Course.query.order_by(Course.title).all()
    selected_course = Course.query.get(course_id) if course_id else None
    return render_template('admin/enrollments.html',
                           enrollments=enrollments, courses=courses,
                           selected_course=selected_course)

@app.route('/admin/enrollment/<int:enrollment_id>/remove', methods=['POST'])
@login_required
@role_required('admin')
def admin_remove_enrollment(enrollment_id):
    enrollment = Enrollment.query.get_or_404(enrollment_id)
    student_name = enrollment.student.full_name or enrollment.student.username
    course_title = enrollment.course.title
    db.session.delete(enrollment)
    db.session.commit()
    flash(f'Inscription de {student_name} au cours "{course_title}" supprimée.', 'success')
    return redirect(request.referrer or url_for('admin_enrollments'))

@app.route('/admin/user/add', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_add_user():
    if request.method == 'POST':
        user = _create_user(request.form, request.form.get('role', 'student'))
        if user:
            flash(f'Utilisateur {user.full_name} cree.', 'success')
        return redirect(url_for('admin_users'))
    return render_template('admin/add_user.html')

@app.route('/admin/user/<int:uid>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def toggle_user(uid):
    u = User.query.get_or_404(uid)
    # ⚠️  BUG FIX: empêcher l'admin de se désactiver lui-même
    if u.id == current_user.id:
        flash('Vous ne pouvez pas vous désactiver vous-même.', 'danger')
        return redirect(url_for('admin_users'))
    if u.role == 'admin':
        flash('Impossible de modifier un compte admin.', 'danger')
        return redirect(url_for('admin_users'))
    u.is_active = not u.is_active
    db.session.commit()

    # Notifier l'enseignant si son compte vient d'être activé
    if u.is_active and u.role == 'teacher':
        msg = ('Votre compte enseignant a été activé ! '
               'Vous pouvez maintenant vous connecter et créer vos cours.')
        db.session.add(Notification(user_id=u.id, message=msg, notif_type='success'))
        db.session.commit()
        notify_realtime(u.id, msg, 'success')

    state = 'activé' if u.is_active else 'désactivé'
    flash(f'Compte de {u.username} {state}.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/user/<int:uid>/delete', methods=['POST'])
@login_required
@role_required('admin')
def delete_user(uid):
    u = User.query.get_or_404(uid)
    if u.role == 'admin':
        flash('Impossible de supprimer un admin.', 'danger')
        return redirect(url_for('admin_users'))
    username = u.username
    try:
        # Supprimer les enregistrements liés avant de supprimer l'utilisateur
        # (évite les erreurs de contrainte de clé étrangère)
        VideoProgress.query.filter_by(user_id=u.id).delete()
        WatchHistory.query.filter_by(user_id=u.id).delete()
        Enrollment.query.filter_by(student_id=u.id).delete()
        Notification.query.filter_by(user_id=u.id).delete()
        Payment.query.filter_by(user_id=u.id).delete()

        # Si l'utilisateur est enseignant, gérer ses cours
        if u.role == 'teacher':
            teacher_courses = Course.query.filter_by(teacher_id=u.id).all()
            for course in teacher_courses:
                # Supprimer tous les fichiers (Supabase ou local)
                for video in course.videos.all():
                    if video.file_path:
                        delete_file(video.file_path)
                for pdf in course.pdfs.all():
                    if pdf.file_path:
                        delete_file(pdf.file_path)
                delete_file(course.ebook_cover)
                delete_file(course.ebook_file)
                delete_file(course.thumbnail)
                # Supprimer les inscriptions et progressions liées aux cours
                Enrollment.query.filter_by(course_id=course.id).delete()
                for v in course.videos.all():
                    VideoProgress.query.filter_by(video_id=v.id).delete()
                    WatchHistory.query.filter_by(video_id=v.id).delete()

        db.session.flush()
        db.session.delete(u)
        db.session.commit()
        flash(f'Utilisateur "{username}" supprimé définitivement.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Erreur suppression utilisateur {uid}: {e}')
        flash('Une erreur est survenue lors de la suppression. Veuillez réessayer.', 'danger')
    return redirect(url_for('admin_users'))

# ══════════════════════════════════════════════════════════════
#  COURSES
# ══════════════════════════════════════════════════════════════
@app.route('/courses')
@_simple_cache(ttl=120)   # Cache 2 min pour les visiteurs non connectés
def courses():
    category    = request.args.get('category', '')
    level       = request.args.get('level', '')
    search      = request.args.get('search', '')
    course_type = request.args.get('type', '')
    is_free     = request.args.get('free', '')
    sort        = request.args.get('sort', 'newest')

    q = Course.query.filter_by(is_published=True, is_approved=True)
    if category:    q = q.filter(Course.category.ilike(f'%{category}%'))
    if level:       q = q.filter(Course.level == level)
    if course_type: q = q.filter(Course.course_type == course_type)
    if is_free == '1': q = q.filter(Course.is_free == True)
    if search:      q = q.filter(Course.title.ilike(f'%{search}%') |
                                 Course.description.ilike(f'%{search}%'))
    if sort == 'popular':
        all_courses = sorted(q.all(), key=lambda c: c.enrollments.count(), reverse=True)
    else:
        all_courses = q.order_by(Course.created_at.desc()).all()

    categories = (db.session.query(Course.category)
                  .filter(Course.is_published == True, Course.is_approved == True,
                          Course.category.isnot(None))
                  .distinct().all())
    return render_template('courses/list.html', courses=all_courses,
                           categories=[c[0] for c in categories if c[0]])

@app.route('/course/<int:course_id>')
def course_detail(course_id):
    course    = Course.query.get_or_404(course_id)
    videos    = (Video.query.filter_by(course_id=course_id, is_approved=True)
                 .order_by(Video.order_index).all())
    pdfs      = PDFContent.query.filter_by(course_id=course_id, is_approved=True).all()
    is_enrolled = False
    if current_user.is_authenticated:
        is_enrolled = bool(Enrollment.query.filter_by(
            student_id=current_user.id, course_id=course_id).first())
    playlist_id = _extract_playlist_id(course.youtube_playlist_url or '')
    return render_template('courses/detail.html', course=course, videos=videos,
                           pdfs=pdfs, is_enrolled=is_enrolled, playlist_id=playlist_id)

@app.route('/video/<int:video_id>')
@login_required
def watch_video(video_id):
    video = Video.query.get_or_404(video_id)

    enrolled = (Enrollment.query.filter_by(student_id=current_user.id,
                                           course_id=video.course_id).first())

    # Admin ou enseignant propriétaire du cours : accès libre sans inscription
    course = Course.query.get(video.course_id)
    is_free_access = (current_user.role == 'admin' or
                      (current_user.role == 'teacher' and course and course.teacher_id == current_user.id))
    can_access = is_free_access or enrolled

    if not can_access:
        if not course.is_free and course.price > 0:
            flash('Payez ce cours pour accéder aux vidéos.', 'warning')
        else:
            flash('Inscrivez-vous pour voir cette vidéo.', 'warning')
        return redirect(url_for('course_detail', course_id=video.course_id))

    # Pour les non-inscrits non-admin (ne devrait pas arriver), bloquer les vidéos non approuvées
    if not video.is_approved and not can_access:
        flash('Video en attente de validation.', 'warning')
        return redirect(url_for('course_detail', course_id=video.course_id))

    # Record history
    db.session.add(WatchHistory(user_id=current_user.id, video_id=video_id))
    video.last_watched = datetime.utcnow()
    video.watch_count  = (video.watch_count or 0) + 1
    db.session.commit()

    # Load existing progress for this video
    progress = VideoProgress.query.filter_by(
        user_id=current_user.id, video_id=video_id).first()

    next_video = (Video.query
                  .filter(Video.course_id == video.course_id,
                          Video.order_index > video.order_index)
                  .order_by(Video.order_index).first())

    # All course videos for sidebar playlist (inscrits voient toutes, sinon approuvées seulement)
    if can_access:
        videos = (Video.query.filter_by(course_id=video.course_id)
                  .order_by(Video.order_index).all())
    else:
        videos = (Video.query.filter_by(course_id=video.course_id, is_approved=True)
                  .order_by(Video.order_index).all())

    # Build progress map {video_id: VideoProgress} for sidebar completion indicators
    all_vp = VideoProgress.query.filter_by(user_id=current_user.id).all()
    video_progress_map = {vp.video_id: vp for vp in all_vp}

    return render_template('courses/video_player.html',
                           video=video,
                           videos=videos,
                           next_video=next_video,
                           progress=progress,
                           enrollment=enrolled,
                           video_progress_map=video_progress_map)

# ══════════════════════════════════════════════════════════════
#  API — VIDEO PROGRESS
# ══════════════════════════════════════════════════════════════
@app.route('/api/video-progress', methods=['POST'])
@login_required
def api_video_progress():
    data       = request.get_json() or {}
    video_id   = data.get('video_id')
    # Accept both old 'percentage' and new 'watch_percentage' field names
    percentage = float(data.get('watch_percentage', data.get('percentage', 0)))
    cur_time   = float(data.get('last_position', data.get('current_time', 0)))
    elapsed    = int(data.get('total_time_seconds', data.get('elapsed_seconds', 0)))

    video = Video.query.get(video_id)
    if not video: return jsonify({'status': 'error'}), 404

    # ── Vérification IDOR : s'assurer que l'utilisateur a accès à cette vidéo ──
    _prog_course   = Course.query.get(video.course_id)
    _prog_enrolled = Enrollment.query.filter_by(
        student_id=current_user.id, course_id=video.course_id).first()
    _prog_free_access = (
        current_user.role == 'admin' or
        (current_user.role == 'teacher' and _prog_course and
         _prog_course.teacher_id == current_user.id)
    )
    if not _prog_enrolled and not _prog_free_access:
        return jsonify({'status': 'forbidden'}), 403

    vp = VideoProgress.query.filter_by(
        user_id=current_user.id, video_id=video_id).first()
    if not vp:
        vp = VideoProgress(user_id=current_user.id, video_id=video_id)
        db.session.add(vp)

    # Only advance if higher percentage (never go backwards)
    if percentage > (vp.watch_percentage or 0):
        vp.watch_percentage = percentage
    vp.last_position      = cur_time
    # Accumulate watch time (capped to avoid inflation)
    vp.total_time_seconds = min((vp.total_time_seconds or 0) + elapsed, 86400)
    vp.updated_at         = datetime.utcnow()

    # Mark complete only when >= 90%
    newly_completed = False
    if percentage >= 90 and not vp.completed:
        vp.completed    = True
        newly_completed = True

    db.session.commit()

    # Recalculate course progress
    enroll = Enrollment.query.filter_by(
        student_id=current_user.id, course_id=video.course_id).first()
    if enroll:
        _recalc_progress(current_user.id, video.course_id)

    return jsonify({
        'status':          'ok',
        'percentage':      vp.watch_percentage,
        'completed':       vp.completed,
        'newly_completed': newly_completed,
        'course_progress': enroll.progress if enroll else 0,
    })

# ══════════════════════════════════════════════════════════════
#  PAIEMENT — MONEROO
# ══════════════════════════════════════════════════════════════

def _payment_guard(course_id):
    """Retourne (course, erreur_redirect) — vérifie les pré-conditions."""
    course = Course.query.get_or_404(course_id)
    if course.is_free:
        return course, redirect(url_for('enroll', course_id=course_id))
    if not current_user.is_authenticated:
        return course, redirect(url_for('login'))
    enrolled = Enrollment.query.filter_by(
        student_id=current_user.id, course_id=course_id).first()
    if enrolled:
        flash('Vous êtes déjà inscrit à ce cours.', 'info')
        return course, redirect(url_for('course_detail', course_id=course_id))
    return course, None


@app.route('/payment/checkout/<int:course_id>')
@login_required
def payment_checkout(course_id):
    """Page de checkout — récapitulatif avant paiement."""
    course, err = _payment_guard(course_id)
    if err:
        return err
    # Paiement en attente existant ?
    pending_pay = Payment.query.filter_by(
        user_id=current_user.id, course_id=course_id, status='pending'
    ).order_by(Payment.created_at.desc()).first()
    return render_template('payment/checkout.html', course=course, pending_pay=pending_pay)


@app.route('/payment/initiate/<int:course_id>', methods=['POST'])
@login_required
def payment_initiate(course_id):
    """Crée la session Moneroo et redirige vers la page de paiement Moneroo."""
    course, err = _payment_guard(course_id)
    if err:
        return err

    return_url = url_for('payment_callback', course_id=course_id, _external=True)

    result = initiate_moneroo_payment(
        user=current_user,
        course=course,
        return_url=return_url,
    )

    if result.get('status') != 'ok':
        flash(f"Erreur : {result.get('message', 'Service de paiement indisponible.')}", 'danger')
        return redirect(url_for('payment_checkout', course_id=course_id))

    # Stocker la référence en session pour la retrouver au callback
    session['pay_ref'] = result['reference']
    session['pay_moneroo_id'] = result.get('moneroo_id', '')
    logger.info("Paiement initié — cours %s — réf %s", course_id, result['reference'])
    return redirect(result['checkout_url'])


@app.route('/payment/callback/<int:course_id>')
@login_required
def payment_callback(course_id):
    """
    Moneroo redirige ici après paiement.
    Paramètres attendus : ?transaction_id=xxx
    Vérification TOUJOURS côté serveur (jamais confiance au ?status= client).
    """
    course = Course.query.get_or_404(course_id)

    # Récupérer l'ID Moneroo depuis le paramètre URL ou la session
    moneroo_id = (
        request.args.get('transaction_id')
        or request.args.get('id')
        or session.get('pay_moneroo_id', '')
    )

    if not moneroo_id:
        # Tenter de retrouver via la référence session
        ref = session.get('pay_ref', '')
        if ref:
            pay = Payment.query.filter(Payment.reference.like(f'{ref}%')).first()
            if pay and '|' in (pay.reference or ''):
                moneroo_id = pay.reference.split('|', 1)[1]

    if not moneroo_id:
        flash('Transaction introuvable. Contactez le support si vous avez été débité.', 'warning')
        return redirect(url_for('payment_checkout', course_id=course_id))

    # ── Vérification serveur ──────────────────────────────────
    verification = verify_moneroo_payment(moneroo_id)
    v_status = verification.get('status', 'error')

    # Retrouver l'enregistrement en base
    payment = Payment.query.filter(
        Payment.reference.like(f'%|{moneroo_id}')
    ).first()

    if v_status == 'success':
        if payment and payment.status != 'success':
            payment.status       = 'success'
            payment.completed_at = datetime.utcnow()
            db.session.commit()
            from payment_api import _handle_post_payment
            _handle_post_payment(payment)
        # Nettoyer la session
        session.pop('pay_ref', None)
        session.pop('pay_moneroo_id', None)
        return render_template('payment/success.html', course=course, payment=payment)

    elif v_status == 'pending':
        ref = payment.reference.split('|')[0] if payment else ''
        return render_template('payment/pending.html',
                               course=course, moneroo_id=moneroo_id, reference=ref)

    else:
        if payment and payment.status == 'pending':
            payment.status = 'failed'
            db.session.commit()
        session.pop('pay_ref', None)
        session.pop('pay_moneroo_id', None)
        return render_template('payment/failed.html',
                               course=course, moneroo_id=moneroo_id)


@app.route('/payment/check/<moneroo_id>')
@login_required
def payment_check(moneroo_id):
    """
    Endpoint AJAX — utilisé par la page pending pour vérifier
    si le paiement a enfin été confirmé.
    """
    course_id = request.args.get('course_id', type=int)
    # Vérification IDOR : s'assurer que ce paiement appartient à l'utilisateur courant
    _pay_obj = Payment.query.filter(Payment.reference.like(f'%|{moneroo_id}')).first()
    if _pay_obj and _pay_obj.user_id != current_user.id and current_user.role != 'admin':
        return jsonify({'status': 'forbidden'}), 403
    verification = verify_moneroo_payment(moneroo_id)
    v_status = verification.get('status', 'pending')

    if v_status == 'success':
        payment = Payment.query.filter(
            Payment.reference.like(f'%|{moneroo_id}')
        ).first()
        if payment and payment.status != 'success':
            payment.status       = 'success'
            payment.completed_at = datetime.utcnow()
            db.session.commit()
            from payment_api import _handle_post_payment
            _handle_post_payment(payment)
        redirect_url = url_for('course_detail', course_id=course_id) if course_id else '/'
        return jsonify({'status': 'success', 'redirect': redirect_url})

    return jsonify({'status': v_status})


@app.route('/payment/webhook', methods=['POST'])
@csrf.exempt   # Webhook serveur-à-serveur Moneroo — pas de session navigateur
def payment_webhook():
    """
    Webhook Moneroo (server-to-server) — appelé par Moneroo
    indépendamment du navigateur de l'utilisateur.
    """
    data = request.get_json(force=True, silent=True) or {}
    transaction_id = (
        data.get('id')
        or data.get('transaction_id')
        or (data.get('data') or {}).get('id', '')
    )
    if not transaction_id:
        logger.warning("Webhook Moneroo sans transaction_id: %s", data)
        return jsonify({'status': 'ignored'}), 200

    verification = verify_moneroo_payment(transaction_id)
    if verification.get('status') == 'success':
        payment = Payment.query.filter(
            Payment.reference.like(f'%|{transaction_id}')
        ).first()
        if payment and payment.status != 'success':
            payment.status       = 'success'
            payment.completed_at = datetime.utcnow()
            db.session.commit()
            from payment_api import _handle_post_payment
            _handle_post_payment(payment)
            logger.info("Webhook Moneroo — paiement confirmé: %s", transaction_id)

    return jsonify({'status': 'ok'}), 200


@app.route('/api/admin/moneroo-test', methods=['GET'])
@login_required
def moneroo_api_test():
    """Route de debug admin — teste la connexion Moneroo avec un payload minimal."""
    if current_user.role != 'admin':
        return jsonify({'error': 'Accès refusé'}), 403
    import os, requests as req
    key  = os.environ.get('MONEROO_SECRET_KEY', '')
    base = os.environ.get('MONEROO_BASE_URL', 'https://api.moneroo.io/v1')
    test_payload = {
        'amount':      100,
        'currency':    'XAF',
        'description': 'Test SECEL',
        'return_url':  'https://example.com/return',
        'customer':    {'email': current_user.email, 'first_name': 'Test', 'last_name': 'User'},
        'metadata':    {'test': 'true'},
    }
    try:
        r = req.post(f'{base}/payments/initialize',
                     headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'Accept': 'application/json'},
                     json=test_payload, timeout=10)
        return jsonify({'status': r.status_code, 'body': r.json() if r.headers.get('content-type','').startswith('application/json') else r.text, 'payload_sent': test_payload})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/payment/status/<reference>', methods=['GET'])
@login_required
def api_payment_status(reference):
    """Statut de paiement sans montant (accès étudiant)."""
    result = check_payment_status(reference)
    return jsonify(result)


@app.route('/api/admin/stats', methods=['GET'])
@login_required
@role_required('admin')
def api_admin_stats():
    """Real-time dashboard stats — admin only."""
    from models import Payment as PaymentModel
    pay_stats = get_payment_stats()

    # Registrations last 7 days
    reg_labels, reg_data = [], []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        cnt = User.query.filter(db.func.date(User.created_at) == d.date()).count()
        reg_labels.append(d.strftime('%d/%m'))
        reg_data.append(cnt)

    # Enrollments last 7 days
    enroll_labels, enroll_data = [], []
    for i in range(6, -1, -1):
        d = datetime.utcnow() - timedelta(days=i)
        cnt = Enrollment.query.filter(db.func.date(Enrollment.enrolled_at) == d.date()).count()
        enroll_labels.append(d.strftime('%d/%m'))
        enroll_data.append(cnt)

    total_students = User.query.filter_by(role='student').count()
    total_teachers = User.query.filter_by(role='teacher').count()
    total_admins   = User.query.filter_by(role='admin').count()

    # Recent payments (last 5) — admin view with amounts
    recent = PaymentModel.query.order_by(PaymentModel.created_at.desc()).limit(5).all()
    recent_payments = [{
        'user':       p.user.full_name or p.user.username if p.user else '—',
        'amount':     float(p.amount),
        'currency':   p.currency,
        'status':     p.status,
        'date':       p.created_at.strftime('%d/%m/%Y'),
        'course':     p.course.title[:30] if p.course else '—',
    } for p in recent]

    _total_courses     = Course.query.count()
    _courses_published = Course.query.filter_by(is_published=True).count()
    _courses_pending   = Course.query.filter_by(approval_status='pending').count()

    return jsonify({
        'total_users':       User.query.count(),
        'total_students':    total_students,
        'total_teachers':    total_teachers,
        'total_admins':      total_admins,
        'total_courses':     _total_courses,
        'courses_published': _courses_published,
        'courses_pending':   _courses_pending,
        'pending_videos':    Video.query.filter_by(is_approved=False).count(),
        'total_enrollments': Enrollment.query.count(),
        'revenue_xaf':       pay_stats.get('revenue_xaf', 0),
        'successful_payments': pay_stats.get('successful', 0),
        'pending_payments':    pay_stats.get('pending', 0),
        'failed_payments':     pay_stats.get('failed', 0),
        'reg_labels':      reg_labels,
        'reg_data':        reg_data,
        'enroll_labels':   enroll_labels,
        'enroll_data':     enroll_data,
        'role_data':       [total_students, total_teachers, total_admins],
        'recent_payments': recent_payments,
    })


@app.route('/api/admin/payment/detail/<reference>', methods=['GET'])
@login_required
@role_required('admin')
def api_admin_payment_detail(reference):
    """Détail complet d'un paiement avec montant — admin uniquement."""
    from models import Payment as PaymentModel
    payment = PaymentModel.query.filter(
        PaymentModel.reference.like(f"{reference}%")
    ).first()
    if not payment:
        return jsonify({'status': 'not_found'}), 404
    return jsonify({
        'status':       payment.status,
        'reference':    payment.reference,
        'provider':     payment.provider,
        'amount':       float(payment.amount),
        'currency':     payment.currency,
        'phone':        payment.phone_number,
        'created_at':   payment.created_at.isoformat(),
        'completed_at': payment.completed_at.isoformat() if payment.completed_at else None,
    })

# ══════════════════════════════════════════════════════════════
#  API — CHATBOT
# ══════════════════════════════════════════════════════════════
@app.route('/api/chatbot', methods=['POST'])
@csrf.exempt   # API publique (widget chatbot sans session)
@limiter.limit("20 per minute; 100 per hour",
               error_message='Trop de messages. Attendez une minute avant de réessayer.')
def chatbot():
    data    = request.get_json() or {}
    message = data.get('message', '').strip()
    lang    = data.get('lang')
    history = data.get('history', [])
    if not isinstance(history, list):
        history = []
    history = history[-20:]
    clean_history = []
    for entry in history:
        if isinstance(entry, dict):
            role    = str(entry.get('role', 'user'))[:10]
            content = str(entry.get('content', ''))[:2000]
            if role in ('user', 'assistant') and content.strip():
                clean_history.append({'role': role, 'content': content})
    if not message:
        return jsonify({'response': '...', 'lang': 'fr'})
    if len(message) > 1000:
        return jsonify({'response': 'Message trop long (max 1000 caractères).', 'lang': 'fr'}), 400
    response, detected_lang = get_chatbot_response(message, lang, clean_history)
    return jsonify({'response': response, 'lang': detected_lang})

# ══════════════════════════════════════════════════════════════
#  NOTIFICATIONS + REAL-TIME
# ══════════════════════════════════════════════════════════════
@app.route('/notifications/mark-read/<int:nid>', methods=['POST'])
@login_required
def mark_notification_read(nid):
    n = Notification.query.filter_by(id=nid, user_id=current_user.id).first()
    if n: n.is_read = True; db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/notifications/count')
@login_required
def notification_count():
    count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    latest = (Notification.query
              .filter_by(user_id=current_user.id, is_read=False)
              .order_by(Notification.created_at.desc())
              .limit(5).all())
    return jsonify({
        'count': count,
        'notifications': [
            {
                'id':         n.id,
                'message':    n.message,
                'type':       n.notif_type,
                'created_at': n.created_at.isoformat(),
            }
            for n in latest
        ]
    })

@app.route('/api/sse/notifications')
@login_required
def sse_notifications():
    user_id = current_user.id

    def event_stream():
        import time
        last_check  = datetime.utcnow()
        retry_count = 0
        while retry_count < 120:
            time.sleep(3)
            retry_count += 1
            with app.app_context():
                new_notifs = (Notification.query
                              .filter(Notification.user_id == user_id,
                                      Notification.is_read == False,
                                      Notification.created_at > last_check)
                              .order_by(Notification.created_at.asc())
                              .all())
                if new_notifs:
                    last_check = datetime.utcnow()
                    for n in new_notifs:
                        data = json.dumps({
                            'id':      n.id,
                            'message': n.message,
                            'type':    n.notif_type,
                        })
                        yield f'data: {data}\n\n'
                else:
                    yield ': ping\n\n'

    return Response(
        stream_with_context(event_stream()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control':     'no-cache',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': request.host_url.rstrip('/'),
        }
    )

# ══════════════════════════════════════════════════════════════
#  PROFILE
# ══════════════════════════════════════════════════════════════
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name', current_user.full_name)
        current_user.phone     = request.form.get('phone', current_user.phone)
        current_user.bio       = request.form.get('bio', current_user.bio)
        if current_user.role == 'student':
            current_user.learning_goals = request.form.get('learning_goals', '')
            current_user.student_level  = request.form.get('student_level', '')
        elif current_user.role == 'teacher':
            current_user.specialty       = request.form.get('specialty', '')
            current_user.qualifications  = request.form.get('qualifications', '')
            current_user.portfolio_url   = request.form.get('portfolio_url', '')
            current_user.years_experience = int(request.form.get('years_experience', 0) or 0)
        pwd     = request.form.get('new_password', '').strip()
        old_pwd = request.form.get('current_password', '')
        if pwd:
            if not current_user.check_password(old_pwd):
                flash('Mot de passe actuel incorrect.', 'danger')
                return redirect(url_for('profile'))
            if len(pwd) < 8:
                flash('Le nouveau mot de passe doit contenir au moins 8 caractères.', 'danger')
                return redirect(url_for('profile'))
            current_user.set_password(pwd)
        portfolio = request.form.get('portfolio_url', '').strip()
        if portfolio and not portfolio.lower().startswith(('http://', 'https://')):
            portfolio = ''
        if hasattr(current_user, 'portfolio_url'):
            current_user.portfolio_url = portfolio
        db.session.commit()
        flash('Profil mis a jour.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')

# ══════════════════════════════════════════════════════════════
#  STATIC UPLOADS
# ══════════════════════════════════════════════════════════════
@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    """Sert les fichiers uploadés avec contrôle d'accès.
    - Fichiers locaux : servis par Flask directement.
    - Fichiers Supabase : cette route n'est jamais appelée (URLs directes dans les templates).
    """
    file_path = f'uploads/{filename}'
    _video_exts = ('.mp4', '.webm', '.avi', '.mov', '.mkv', '.wmv')

    def _check_enrolled(course_obj):
        """Vérifie que l'utilisateur a accès au contenu payant."""
        if not current_user.is_authenticated:
            abort(403)
        if current_user.role == 'admin':
            return
        if current_user.role == 'teacher' and course_obj.teacher_id == current_user.id:
            return
        if not Enrollment.query.filter_by(student_id=current_user.id, course_id=course_obj.id).first():
            abort(403)

    # Ebooks PDF payants
    if filename.lower().endswith('.pdf'):
        paid_ebook = Course.query.filter_by(ebook_file=file_path).first()
        if paid_ebook and not paid_ebook.is_free:
            _check_enrolled(paid_ebook)
            # Si stocké sur Supabase → URL signée temporaire
            if is_supabase_url(paid_ebook.ebook_file):
                signed = get_signed_url(paid_ebook.ebook_file)
                if signed:
                    return redirect(signed)

    # Vidéos locales payantes
    if filename.lower().endswith(_video_exts):
        vid_obj = Video.query.filter_by(file_path=file_path).first()
        if vid_obj:
            course_obj = Course.query.get(vid_obj.course_id)
            if course_obj and not course_obj.is_free:
                _check_enrolled(course_obj)
                if is_supabase_url(vid_obj.file_path):
                    signed = get_signed_url(vid_obj.file_path)
                    if signed:
                        return redirect(signed)

    return send_from_directory(app.static_folder, file_path)

# ══════════════════════════════════════════════════════════════
#  ERROR HANDLERS
# ══════════════════════════════════════════════════════════════
@app.errorhandler(404)
def not_found(e):
    return render_template('errors/404.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('errors/403.html'), 403

@app.errorhandler(500)
def server_error(e):
    return render_template('errors/500.html'), 500

# ── Cron Vercel — nettoyage nocturne ─────────────────────────
@app.route('/api/cron/cleanup', methods=['GET', 'POST'])
def cron_cleanup():
    """Appelé par Vercel Cron Jobs à 02:00 UTC. Protégé par CRON_SECRET."""
    cron_secret = os.environ.get('CRON_SECRET', '')
    if os.environ.get('VERCEL') and cron_secret:
        auth = request.headers.get('Authorization', '')
        if auth != f'Bearer {cron_secret}':
            return jsonify({'error': 'Unauthorized'}), 401
    try:
        videos, courses = _run_cleanup()
        return jsonify({'ok': True, 'deleted_videos': videos,
                        'deleted_courses': courses,
                        'timestamp': datetime.utcnow().isoformat()})
    except Exception as e:
        app.logger.error(f'Cron cleanup error: {e}')
        return jsonify({'ok': False, 'error': str(e)}), 500

if __name__ == '__main__':
    if os.environ.get('VERCEL'):
        pass  # Running on Vercel serverless — don't call app.run()
    else:
        app.run(debug=True, host='0.0.0.0', port=5000)
