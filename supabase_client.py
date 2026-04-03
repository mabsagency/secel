"""
supabase_client.py
──────────────────
Client Supabase côté serveur pour SECEL.
Utilisé pour :
  - les opérations Admin (service_role) : envoi de notifications, accès garanti
  - l'accès public anonyme (anon) : lecture des données publiques

Le client Python Supabase est utilisé EN COMPLÉMENT de SQLAlchemy :
  - SQLAlchemy : CRUD standard (ORM Flask)
  - Supabase client : real-time, Storage, Auth natif (optionnel), RPC
"""

import os
from dotenv import load_dotenv

load_dotenv()

_SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
_ANON_KEY     = os.environ.get('SUPABASE_ANON_KEY', '')
_SERVICE_KEY  = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')

# Clients lazily initialisés (None si Supabase non configuré)
_supabase_anon    = None
_supabase_service = None


def get_supabase_anon():
    """Client public (anon key) — lecture seule, respect des RLS."""
    global _supabase_anon
    if _supabase_anon is None and _SUPABASE_URL and _ANON_KEY:
        try:
            from supabase import create_client
            _supabase_anon = create_client(_SUPABASE_URL, _ANON_KEY)
        except Exception as e:
            print(f'[SUPABASE] Impossible de créer le client anon : {e}')
    return _supabase_anon


def get_supabase_service():
    """Client service (service_role key) — accès admin, bypass RLS."""
    global _supabase_service
    if _supabase_service is None and _SUPABASE_URL and _SERVICE_KEY:
        try:
            from supabase import create_client
            _supabase_service = create_client(_SUPABASE_URL, _SERVICE_KEY)
        except Exception as e:
            print(f'[SUPABASE] Impossible de créer le client service : {e}')
    return _supabase_service


def notify_realtime(user_id: int, message: str, notif_type: str = 'info'):
    """
    Insère une notification via le client Supabase service.
    Déclenche automatiquement le broadcast Realtime pour l'abonné côté client.

    Usage : appelé depuis app.py après chaque événement métier important.
    """
    client = get_supabase_service()
    if client is None:
        return  # Supabase non configuré — pas d'erreur fatale
    try:
        client.table('notifications').insert({
            'user_id':    user_id,
            'message':    message,
            'notif_type': notif_type,
            'is_read':    False,
        }).execute()
    except Exception as e:
        print(f'[SUPABASE] Erreur notify_realtime : {e}')


def broadcast_event(channel: str, event: str, payload: dict):
    """
    Envoie un événement Broadcast Supabase Realtime (pas lié à une table).
    Utile pour les événements transactionnels : approbation cours, live stats, etc.
    """
    client = get_supabase_service()
    if client is None:
        return
    try:
        client.channel(channel).send({
            'type':    'broadcast',
            'event':   event,
            'payload': payload,
        })
    except Exception as e:
        print(f'[SUPABASE] Erreur broadcast_event : {e}')
