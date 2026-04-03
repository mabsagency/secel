"""
storage.py — Couche de stockage hybride SECEL
=============================================
Supabase Storage si configuré, filesystem local sinon.
Transparent pour le reste de l'app : même API partout.

Valeur stockée en DB :
  - Supabase → URL complète  https://xxx.supabase.co/storage/v1/...
  - Local     → chemin relatif  'uploads/20240101_thumb.jpg'
                ou juste nom    '20240101_thumb.jpg'  (thumbnails)

Les templates vérifient déjà startswith('http') — aucun changement template requis.
"""

import os
from datetime import datetime
from werkzeug.utils import secure_filename

BUCKET = 'secel-uploads'

_CONTENT_TYPES = {
    'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'png': 'image/png',  'webp': 'image/webp',
    'pdf': 'application/pdf',
    'mp4': 'video/mp4',  'webm': 'video/webm',
    'avi': 'video/x-msvideo', 'mov': 'video/quicktime',
    'mkv': 'video/x-matroska', 'wmv': 'video/x-ms-wmv',
}

def _ct(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return _CONTENT_TYPES.get(ext, 'application/octet-stream')

def _supa():
    try:
        from supabase_client import get_supabase_service
        return get_supabase_service()
    except Exception:
        return None

def _static_folder():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

def _upload_folder():
    from config import Config
    return Config.STATIC_UPLOAD_FOLDER


# ── Upload ────────────────────────────────────────────────────

def upload_file(file_storage, prefix=''):
    """
    Upload un fichier. Retourne la valeur à stocker en DB.
    - Supabase OK  → URL https://...
    - Fallback     → nom seul  e.g. '20240101_thumb.jpg'
    """
    fname = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{prefix + '_' if prefix else ''}{secure_filename(file_storage.filename)}"

    client = _supa()
    if client:
        path = f"uploads/{fname}"
        try:
            data = file_storage.read()
            client.storage.from_(BUCKET).upload(
                path=path, file=data,
                file_options={'content-type': _ct(file_storage.filename), 'upsert': 'true'}
            )
            return client.storage.from_(BUCKET).get_public_url(path)
        except Exception as e:
            print(f'[STORAGE] Supabase upload failed, fallback local: {e}')
            file_storage.seek(0)

    # Fallback local
    upload_dir = _upload_folder()
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, fname))
    return fname                          # nom seul, sans préfixe uploads/


def upload_file_as_path(file_storage, prefix=''):
    """
    Comme upload_file() mais retourne 'uploads/fname' (convention
    utilisée par ebook_file, ebook_cover, video.file_path en local).
    """
    result = upload_file(file_storage, prefix)
    if result.startswith('http'):
        return result
    return f'uploads/{result}'


# ── Delete ───────────────────────────────────────────────────

def delete_file(stored_value):
    """
    Supprime un fichier depuis son emplacement de stockage.
    Accepte : URL https://, 'uploads/fname', ou 'fname' seul.
    """
    if not stored_value:
        return

    if stored_value.startswith('http://') or stored_value.startswith('https://'):
        marker = f'/storage/v1/object/public/{BUCKET}/'
        if marker in stored_value:
            path = stored_value.split(marker, 1)[1]
            client = _supa()
            if client:
                try:
                    client.storage.from_(BUCKET).remove([path])
                except Exception as e:
                    print(f'[STORAGE] Supabase delete failed: {e}')
    elif stored_value.startswith('uploads/'):
        fp = os.path.join(_static_folder(), stored_value)
        _rm(fp)
    else:
        fp = os.path.join(_upload_folder(), stored_value)
        _rm(fp)


def _rm(fp):
    if os.path.exists(fp):
        try:
            os.remove(fp)
        except OSError:
            pass


# ── Signed URL (pour contenu payant) ─────────────────────────

def get_signed_url(stored_value, expires_in=3600):
    """
    Retourne une URL signée temporaire pour contenu protégé.
    - Supabase : URL avec expiration
    - Local    : None (Flask sert le fichier directement via /uploads/<filename>)
    """
    if not stored_value or not stored_value.startswith('http'):
        return None
    marker = f'/storage/v1/object/public/{BUCKET}/'
    if marker not in stored_value:
        return None
    path = stored_value.split(marker, 1)[1]
    client = _supa()
    if not client:
        return None
    try:
        res = client.storage.from_(BUCKET).create_signed_url(path, expires_in)
        return res.get('signedURL') or res.get('signedUrl')
    except Exception as e:
        print(f'[STORAGE] Signed URL failed: {e}')
        return None


# ── Info ─────────────────────────────────────────────────────

def is_supabase_url(value):
    return bool(value and (value.startswith('http://') or value.startswith('https://')))
