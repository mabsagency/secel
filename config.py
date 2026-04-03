import os, secrets
from datetime import timedelta
from dotenv import load_dotenv

# Charger les variables d'environnement depuis .env
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _get_secret_key() -> str:
    """Retourne une SECRET_KEY sécurisée.
    Priorité : 1) variable d'env (obligatoire en prod), 2) fichier local (dev), 3) génération éphémère."""
    # 1. Variable d'environnement (Vercel / production)
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY']
    # 2. Fichier local (développement)
    if not os.environ.get('VERCEL'):
        key_file = os.path.join(BASE_DIR, '.secret_key')
        if os.path.exists(key_file):
            with open(key_file, 'r') as f:
                k = f.read().strip()
                if k:
                    return k
        new_key = secrets.token_hex(32)
        try:
            with open(key_file, 'w') as f:
                f.write(new_key)
        except OSError:
            pass
        return new_key
    # 3. Éphémère (Vercel sans SECRET_KEY — sessions non persistantes entre cold starts)
    return secrets.token_hex(32)

# Cache pour eviter de tester la connexion plusieurs fois
_DB_URI_CACHE = None


def _test_postgres(uri: str) -> bool:
    """Teste rapidement si l'URI PostgreSQL est accessible (timeout 5s)."""
    try:
        import psycopg2
        conn = psycopg2.connect(uri, connect_timeout=5)
        conn.close()
        return True
    except Exception:
        return False


def _build_db_uri() -> str:
    """
    Construit l'URI de base de donnees.
    Priorite :
      1. DATABASE_URL  (variable complete, definie dans .env ou l'environnement)
      2. SUPABASE_DB_PASSWORD + constantes du projet  (URI via connection pooler)
         -> teste la connexion ; si echec, bascule sur SQLite
      3. Fallback SQLite local (developpement sans Supabase)
    """
    global _DB_URI_CACHE
    if _DB_URI_CACHE is not None:
        return _DB_URI_CACHE

    from urllib.parse import quote_plus

    # 1. URL complete fournie directement
    if os.environ.get('DATABASE_URL'):
        url = os.environ['DATABASE_URL']
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        _DB_URI_CACHE = url
        return _DB_URI_CACHE

    # 2. Construction via le mot de passe Supabase
    pwd_raw = os.environ.get('SUPABASE_DB_PASSWORD', '')
    if pwd_raw and pwd_raw not in ('VOTRE_MOT_DE_PASSE_ICI', ''):
        pwd_encoded = quote_plus(pwd_raw)
        project_ref = 'yzcycszswnpplrepuzqe'
        postgres_uri = (
            f'postgresql://postgres.{project_ref}:{pwd_encoded}'
            f'@aws-0-eu-central-1.pooler.supabase.com:6543/postgres'
        )
        print('[CONFIG] Test de connexion Supabase...')
        if _test_postgres(postgres_uri):
            print('[CONFIG] Supabase connecte avec succes.')
            _DB_URI_CACHE = postgres_uri
            return _DB_URI_CACHE
        else:
            print('[CONFIG] Supabase inaccessible - basculement sur SQLite local.')
            print('[CONFIG]   -> Recuperez DATABASE_URL dans :')
            print('[CONFIG]      Supabase Dashboard > Settings > Database > Connection string')

    # 3. SQLite local (fallback développement)
    # Sur Vercel /var/task est read-only → utiliser /tmp (éphémère mais accessible)
    if os.environ.get('VERCEL'):
        _DB_URI_CACHE = 'sqlite:////tmp/secel.db'
    else:
        _DB_URI_CACHE = 'sqlite:///' + os.path.join(BASE_DIR, 'secel.db')
    return _DB_URI_CACHE


def _get_engine_options():
    """Retourne les options SQLAlchemy adaptees au dialecte (PostgreSQL ou SQLite)."""
    uri = _build_db_uri()
    if uri.startswith('sqlite'):
        return {'pool_pre_ping': True}
    return {
        'pool_pre_ping': True,
        'pool_recycle': 280,
        'pool_size': 5,
        'max_overflow': 10,
        'connect_args': {
            'connect_timeout': 10,
            'application_name': 'secel_flask',
        },
    }


class Config:
    # -- Securite -------------------------------------------------------
    SECRET_KEY = _get_secret_key()   # jamais une valeur fixe connue

    # -- Base de donnees ------------------------------------------------
    SQLALCHEMY_DATABASE_URI    = _build_db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS  = _get_engine_options()

    # -- Supabase -------------------------------------------------------
    SUPABASE_URL      = os.environ.get('SUPABASE_URL', '')
    SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
    SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')

    # -- Uploads --------------------------------------------------------
    UPLOAD_FOLDER        = os.path.join(BASE_DIR, 'uploads')
    STATIC_UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    # 200 MB max par requête (vidéos pédagogiques). Les PDFs/images sont
    # validés individuellement dans les routes (5 MB et 10 MB respectivement).
    MAX_CONTENT_LENGTH   = 200 * 1024 * 1024   # 200 MB

    MAX_PDF_SIZE_BYTES   = 10 * 1024 * 1024    # 10 MB par PDF
    MAX_IMAGE_SIZE_BYTES = 5  * 1024 * 1024    # 5  MB par image

    ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'wmv', 'mkv', 'webm'}
    ALLOWED_PDF_EXTENSIONS   = {'pdf'}
    # Pas de GIF (potentiellement malveillant / gourmand CPU)
    ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

    # -- Autres ---------------------------------------------------------
    VIDEO_INACTIVITY_DAYS      = 30
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    LANGUAGES                  = ['fr', 'en', 'zh']
    DEFAULT_LANGUAGE           = 'fr'

    # ── Moneroo (paiement) ─────────────────────────────────────────
    MONEROO_SECRET_KEY = os.environ.get('MONEROO_SECRET_KEY', '')
    MONEROO_BASE_URL   = os.environ.get('MONEROO_BASE_URL', 'https://api.moneroo.io/v1')

    # Google Gemini AI -- chatbot SELA
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

    # ── OAuth Google ────────────────────────────────────────────
    GOOGLE_CLIENT_ID     = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

    # ── OAuth LinkedIn ──────────────────────────────────────────
    LINKEDIN_CLIENT_ID     = os.environ.get('LINKEDIN_CLIENT_ID', '')
    LINKEDIN_CLIENT_SECRET = os.environ.get('LINKEDIN_CLIENT_SECRET', '')
