# ================================================================
# SECEL — Moneroo Payment Integration
# API : https://api.moneroo.io/v1
# Docs : https://docs.moneroo.io
# ================================================================
# SÉCURITÉ :
#   - La clé API est lue depuis .env (MONEROO_SECRET_KEY), jamais en dur
#   - Les montants ne sont exposés qu'aux admins (contrôle dans app.py)
#   - La vérification du paiement se fait côté serveur (jamais côté client)
#   - Les webhooks sont traités et loggés avec référence croisée DB
# ================================================================

import os
import logging
import random
import string
from datetime import datetime

import requests

from models import db, Payment, Enrollment, Notification

logger = logging.getLogger(__name__)

# ── Constantes Moneroo ────────────────────────────────────────
_MONEROO_BASE   = os.environ.get('MONEROO_BASE_URL', 'https://api.moneroo.io/v1')
_MONEROO_KEY    = os.environ.get('MONEROO_SECRET_KEY', '')
_REQUEST_TIMEOUT = 15   # secondes


def _moneroo_headers() -> dict:
    """Headers sécurisés pour toutes les requêtes Moneroo."""
    if not _MONEROO_KEY:
        raise RuntimeError("MONEROO_SECRET_KEY non définie dans .env")
    return {
        'Authorization': f'Bearer {_MONEROO_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def generate_reference() -> str:
    """Génère une référence de paiement unique."""
    ts  = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    rnd = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"SECEL-{ts}-{rnd}"


# ── Initialisation du paiement ────────────────────────────────
def initiate_moneroo_payment(
    user,
    course,
    return_url: str,
) -> dict:
    """
    Crée une session de paiement Moneroo et retourne le checkout_url.

    Paramètres :
        user       : objet User Flask-Login (current_user)
        course     : objet Course SQLAlchemy
        return_url : URL de retour après paiement (ex: /payment/callback)

    Retourne :
        {
          'status': 'ok' | 'error',
          'checkout_url': str,      # URL Moneroo où rediriger l'utilisateur
          'payment_id': int,        # ID interne SECEL
          'moneroo_id': str,        # ID Moneroo de la transaction
          'reference': str,
          'message': str            # en cas d'erreur
        }
    """
    reference = generate_reference()

    # Montant en entier (Moneroo attend un integer)
    amount_int = int(round(float(course.price)))

    # Normaliser la devise — Moneroo n'accepte que 'XAF', pas 'FCFA' ou 'CFA'
    _currency_map = {'FCFA': 'XAF', 'CFA': 'XAF', 'F CFA': 'XAF', 'XOF': 'XOF'}
    raw_currency = (course.currency or 'XAF').strip().upper()
    currency     = _currency_map.get(raw_currency, raw_currency)

    # Construire le nom/prénom du client
    full = (user.full_name or user.username or '').strip()
    parts = full.split(' ', 1)
    first_name = parts[0] if parts else user.username
    last_name  = parts[1] if len(parts) > 1 else ''

    # Construire le customer — ne pas envoyer les champs vides
    customer = {
        'email':      user.email,
        'first_name': first_name or user.username,
        'last_name':  last_name  or first_name or user.username,
    }
    if user.phone:
        # Moneroo exige un entier (pas une chaîne) — strip +, espaces, tirets
        phone_digits = ''.join(filter(str.isdigit, str(user.phone)))
        if phone_digits:
            try:
                customer['phone'] = int(phone_digits)
            except ValueError:
                pass  # Ignorer si conversion impossible

    payload = {
        'amount':      amount_int,
        'currency':    currency,
        'description': f'Formation SECEL - {course.title[:80]}',
        'return_url':  return_url,
        'customer':    customer,
        'metadata': {
            'secel_reference': reference,
            'course_id':       str(course.id),
            'user_id':         str(user.id),
        },
    }

    # Enregistrer le paiement en base AVANT l'appel API (status = pending)
    payment = Payment(
        user_id     = user.id,
        course_id   = course.id,
        amount      = course.price,
        currency    = currency,
        provider    = 'moneroo',
        phone_number= user.phone or '',
        reference   = reference,
        status      = 'pending',
        description = payload['description'],
    )
    db.session.add(payment)
    db.session.commit()

    # Appel API Moneroo
    try:
        resp = requests.post(
            f'{_MONEROO_BASE}/payments/initialize',
            headers=_moneroo_headers(),
            json=payload,
            timeout=_REQUEST_TIMEOUT,
        )
        if not resp.ok:
            logger.error("Moneroo 422 payload: %s", payload)
            logger.error("Moneroo 422 response: %s", resp.text)
        resp.raise_for_status()
        data = resp.json().get('data', {})
        moneroo_id   = data.get('id', '')
        checkout_url = data.get('checkout_url', '')

        if not checkout_url:
            raise ValueError("Moneroo n'a pas retourné de checkout_url")

        # Stocker l'ID Moneroo dans la référence pour faciliter la vérif
        payment.reference = f"{reference}|{moneroo_id}"
        db.session.commit()

        logger.info("Paiement Moneroo initialisé: %s -> %s", reference, moneroo_id)
        return {
            'status':       'ok',
            'checkout_url': checkout_url,
            'payment_id':   payment.id,
            'moneroo_id':   moneroo_id,
            'reference':    payment.reference,
        }

    except requests.exceptions.HTTPError as exc:
        # Extraire le vrai message d'erreur Moneroo
        try:
            err_body = exc.response.json()
            err_msg  = err_body.get('message') or str(err_body)
        except Exception:
            err_msg = exc.response.text if exc.response else str(exc)
        logger.error("Erreur Moneroo HTTP %s: %s", exc.response.status_code if exc.response else '?', err_msg)
        payment.status = 'failed'
        db.session.commit()
        return {
            'status':  'error',
            'message': f"Moneroo: {err_msg}",
            'payment_id': payment.id,
        }
    except requests.exceptions.RequestException as exc:
        logger.error("Erreur Moneroo réseau: %s", exc)
        payment.status = 'failed'
        db.session.commit()
        return {
            'status':  'error',
            'message': f"Erreur réseau: {exc}",
            'payment_id': payment.id,
        }
    except Exception as exc:
        logger.error("Erreur inattendue Moneroo: %s", exc)
        payment.status = 'failed'
        db.session.commit()
        return {
            'status':  'error',
            'message': str(exc),
            'payment_id': payment.id,
        }


# ── Vérification du paiement (côté serveur uniquement) ────────
def verify_moneroo_payment(moneroo_id: str) -> dict:
    """
    Vérifie le statut d'un paiement via l'API Moneroo.
    ⚠️  Toujours appeler côté serveur — jamais exposer au client.

    Retourne :
        {
          'status': 'success' | 'pending' | 'failed' | 'error',
          'amount': float,
          'currency': str,
          'is_processed': bool,
          'raw': dict   # données brutes Moneroo (admin only)
        }
    """
    try:
        resp = requests.get(
            f'{_MONEROO_BASE}/payments/{moneroo_id}/verify',
            headers=_moneroo_headers(),
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get('data', {})

        moneroo_status = data.get('status', 'pending')
        # Normaliser le statut Moneroo → statut interne SECEL
        status_map = {
            'success':    'success',
            'pending':    'pending',
            'failed':     'failed',
            'cancelled':  'failed',
            'processing': 'pending',
        }
        secel_status = status_map.get(moneroo_status, 'pending')

        currency_obj = data.get('currency', {})
        currency_code = (
            currency_obj.get('iso_code', '')
            if isinstance(currency_obj, dict)
            else str(currency_obj)
        )

        return {
            'status':       secel_status,
            'amount':       data.get('amount', 0),
            'currency':     currency_code,
            'is_processed': data.get('is_processed', False),
            'raw':          data,   # réservé admin
        }

    except requests.exceptions.RequestException as exc:
        logger.error("Erreur vérification Moneroo %s: %s", moneroo_id, exc)
        return {'status': 'error', 'message': str(exc)}
    except Exception as exc:
        logger.error("Erreur inattendue vérification: %s", exc)
        return {'status': 'error', 'message': str(exc)}


# ── Mise à jour DB après confirmation ─────────────────────────
def confirm_payment_from_callback(reference: str) -> dict:
    """
    Appelé depuis le callback return_url OU le webhook Moneroo.
    Vérifie côté serveur puis met à jour la DB.
    """
    payment = Payment.query.filter(
        Payment.reference.like(f"{reference}%")
    ).first()

    if not payment:
        logger.warning("confirm_payment: référence introuvable: %s", reference)
        return {'status': 'not_found'}

    if payment.status == 'success':
        return {'status': 'success', 'already': True}

    # Extraire l'ID Moneroo depuis la référence composée "SECEL-...|moneroo_id"
    moneroo_id = ''
    if '|' in (payment.reference or ''):
        moneroo_id = payment.reference.split('|', 1)[1]

    if not moneroo_id:
        logger.error("Impossible de vérifier: pas d'ID Moneroo pour %s", reference)
        return {'status': 'error', 'message': 'ID Moneroo manquant'}

    result = verify_moneroo_payment(moneroo_id)

    payment.status       = result['status']
    payment.completed_at = datetime.utcnow() if result['status'] == 'success' else None
    db.session.commit()

    if result['status'] == 'success' and payment.course_id:
        _handle_post_payment(payment)

    return {
        'status':     payment.status,
        'reference':  payment.reference,
        'payment_id': payment.id,
    }


def _handle_post_payment(payment: Payment):
    """Inscription automatique + notification après paiement validé."""
    existing = Enrollment.query.filter_by(
        student_id=payment.user_id, course_id=payment.course_id
    ).first()
    if not existing:
        enroll = Enrollment(
            student_id=payment.user_id,
            course_id=payment.course_id,
        )
        db.session.add(enroll)

    notif = Notification(
        user_id    = payment.user_id,
        message    = f"Paiement confirmé ! Vous avez accès à la formation. Réf : {payment.reference}",
        message_en = f"Payment confirmed! You now have access to the course. Ref: {payment.reference}",
        notif_type = 'success',
    )
    db.session.add(notif)
    db.session.commit()


# ── Statut depuis DB (public, sans montant) ───────────────────
def check_payment_status(reference: str) -> dict:
    """
    Retourne le statut d'un paiement sans exposer les montants.
    ⚠️  Les montants sont filtrés ici — disponibles uniquement via
        l'endpoint admin /admin/payments.
    """
    payment = Payment.query.filter(
        Payment.reference.like(f"{reference}%")
    ).first()
    if not payment:
        return {'status': 'not_found', 'message': 'Référence introuvable'}
    return {
        'status':    payment.status,
        'reference': reference,
        'provider':  payment.provider,
        # Pas d'amount, pas de currency ici (admin seulement)
    }


# ── Stats admin ───────────────────────────────────────────────
def get_payment_stats() -> dict:
    """Statistiques agrégées pour le dashboard admin."""
    total      = Payment.query.count()
    successful = Payment.query.filter_by(status='success').count()
    pending    = Payment.query.filter_by(status='pending').count()
    failed     = Payment.query.filter_by(status='failed').count()

    revenue_xaf = db.session.query(
        db.func.sum(Payment.amount)
    ).filter(
        Payment.status == 'success',
        Payment.currency.in_(['XAF', 'FCFA', 'CFA'])
    ).scalar() or 0.0

    revenue_usd = db.session.query(
        db.func.sum(Payment.amount)
    ).filter(
        Payment.status == 'success',
        Payment.currency == 'USD'
    ).scalar() or 0.0

    return {
        'total':       total,
        'successful':  successful,
        'pending':     pending,
        'failed':      failed,
        'revenue_xaf': float(revenue_xaf),
        'revenue_usd': float(revenue_usd),
    }
