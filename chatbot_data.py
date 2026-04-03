# ============================================================
# SECEL Multilingual Chatbot Knowledge Base + Gemini AI
# Languages: Français (fr), English (en), 中文 (zh)
# ============================================================

import os
import re

# ── Gemini SDK (optional – graceful fallback if not installed) ──
try:
    from google import genai
    from google.genai import types as genai_types
    _GEMINI_AVAILABLE = True
except ImportError:
    _GEMINI_AVAILABLE = False

# ── Initialise Gemini once ──────────────────────────────────
_GEMINI_CLIENT = None

def _init_gemini():
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is not None:
        return _GEMINI_CLIENT
    if not _GEMINI_AVAILABLE:
        return None
    try:
        from config import Config
        api_key = Config.GEMINI_API_KEY
        if not api_key:
            return None
        _GEMINI_CLIENT = genai.Client(api_key=api_key)
        return _GEMINI_CLIENT
    except Exception:
        return None


# ── System prompt sent to Gemini for every conversation ─────
_GEMINI_SYSTEM_PROMPT = """
Tu es SELA, l'assistante virtuelle intelligente et polyvalente de la plateforme SECEL
(Société d'Enseignement et de Compétences En Ligne).

=== INFORMATIONS SUR SECEL ===
• Plateforme d'apprentissage en ligne basée à Kinshasa, RDC (Congo).
• Propose des formations vidéo, PDF et cours interactifs.
• Catégories : Technologie & Informatique, Management, Langues, Finance, Développement personnel.
• Rôles utilisateurs : Étudiant, Enseignant (validation admin requise), Administrateur.
• Paiements : Orange Money et MTN MoMo (Mobile Money).
• Langues supportées : Français, Anglais, Mandarin.
• Contact : support@secel.com | Lun-Ven 8h-18h.
• Certificats disponibles à 100% de complétion du cours.
• Vidéos non vues depuis 30 jours supprimées automatiquement.
• Les contenus des enseignants sont validés par l'admin avant publication.

=== RÈGLES DE COMPORTEMENT ===
1. Réponds TOUJOURS dans la même langue que l'utilisateur (FR/EN/ZH).
2. Sois chaleureux, précis et professionnel.
3. Utilise des emojis modérément pour rendre la réponse vivante.
4. Tu es une IA GÉNÉRALISTE. Réponds à TOUTES les questions sans exception :
   - Questions sur SECEL (cours, inscription, paiements, etc.)
   - Questions générales : science, technologie, histoire, culture, mathématiques
   - Questions techniques : programmation, code, algorithmes, bases de données
   - Aide scolaire et universitaire
   - Conseils professionnels et personnels
   - Traductions, rédaction, résumés
   - Tout autre sujet que l'utilisateur te pose
5. Pour les questions liées à SECEL, donne des informations précises sur la plateforme.
6. Pour les questions générales, réponds avec la précision et la profondeur nécessaires.
7. N'invente jamais de prix, tarifs ou fonctionnalités inexistantes pour SECEL.
8. Adapte la longueur de ta réponse à la complexité de la question :
   - Question simple → réponse courte et directe
   - Question complexe → réponse détaillée avec exemples si utile
9. Formate en HTML léger (<b>, <br>, <i>, <code>, listes avec •) — pas de Markdown brut.
10. Si quelqu'un te demande qui tu es : tu es SELA, l'assistante IA de SECEL, propulsée par Gemini.
11. Mémorise le contexte de la conversation et utilise-le pour des réponses cohérentes.
""".strip()


# ── Keyword Knowledge Base (réponses instantanées sans API) ──
CHATBOT_KB = {
    "fr": {
        "greetings": {
            "triggers": ["bonjour", "salut", "bonsoir", "hello", "hey", "hi", "bonne journée"],
            "response": "👋 Bonjour ! Je suis <b>SELA</b>, votre assistante IA alimentée par Gemini. Je peux répondre à <b>toutes vos questions</b> — sur SECEL, la technologie, la science, le code, l'histoire, et bien plus encore. Comment puis-je vous aider ?"
        },
        "secel_info": {
            "triggers": ["qu'est-ce que secel", "c'est quoi secel", "secel c'est quoi", "présente secel", "information secel", "à propos", "about"],
            "response": "🎓 <b>SECEL</b> est une plateforme d'apprentissage en ligne premium basée à Kinshasa, RDC. Nous offrons des formations de qualité par vidéo, PDF et cours interactifs dans 5+ domaines. Notre mission : rendre l'excellence accessible à tous."
        },
        "inscription": {
            "triggers": ["inscription", "inscrire", "créer compte", "s'enregistrer", "nouveau compte", "enregistrement", "comment rejoindre"],
            "response": "📝 Pour vous inscrire :<br>1. Cliquez sur <b>'S'inscrire'</b> en haut à droite<br>2. Choisissez votre rôle : <b>Étudiant</b> ou <b>Enseignant</b><br>3. Remplissez vos informations<br>4. Confirmez votre compte<br>C'est gratuit et rapide !"
        },
        "connexion": {
            "triggers": ["connexion", "connecter", "login", "se connecter", "mot de passe", "accès"],
            "response": "🔐 Pour vous connecter, cliquez sur <b>'Connexion'</b>, entrez votre email et mot de passe. Si vous avez oublié votre mot de passe, utilisez 'Mot de passe oublié' sur la page de connexion."
        },
        "cours": {
            "triggers": ["cours", "formation", "apprendre", "programme", "matière", "contenu", "catalogue"],
            "response": "📚 SECEL propose des cours dans :<br>• <b>Technologie & Informatique</b><br>• <b>Management & Leadership</b><br>• <b>Langues</b><br>• <b>Finance & Business</b><br>• <b>Développement personnel</b><br>Explorez notre catalogue pour découvrir tous les programmes."
        },
        "videos": {
            "triggers": ["vidéo", "regarder", "visionner", "lecture", "player", "video"],
            "response": "🎬 Pour regarder les vidéos :<br>1. Connectez-vous<br>2. Accédez à vos cours<br>3. Sélectionnez une vidéo<br><i>Note : Les vidéos non regardées depuis 30 jours sont supprimées automatiquement.</i>"
        },
        "enseignant": {
            "triggers": ["enseignant", "professeur", "teacher", "formateur", "publier", "ajouter cours", "uploader"],
            "response": "👨‍🏫 En tant qu'enseignant :<br>• Ajoutez des cours vidéo (MP4, AVI, MKV)<br>• Publiez des documents PDF<br>• Vos contenus sont validés par l'admin avant publication<br>Accédez à votre tableau de bord enseignant pour commencer."
        },
        "paiement": {
            "triggers": ["payer", "paiement", "orange money", "mtn", "mobile money", "momo", "recharge"],
            "response": "💳 SECEL accepte :<br>• <b>Orange Money</b> (080, 082, 084, 085)<br>• <b>MTN MoMo</b> (089, 090, 091, 097, 098)<br>Le paiement se fait par Mobile Money. Entrez votre numéro et suivez les instructions USSD."
        },
        "contact": {
            "triggers": ["contact", "support", "aide", "problème", "assistance", "email", "téléphone", "joindre"],
            "response": "📞 Contactez-nous :<br>• <b>Email :</b> support@secel.com<br>• <b>Horaires :</b> Lun-Ven, 8h-18h"
        },
        "prix": {
            "triggers": ["prix", "tarif", "coût", "gratuit", "abonnement", "combien"],
            "response": "💰 Certains cours SECEL sont gratuits, d'autres sont payants (via Mobile Money). Consultez la page de chaque cours pour voir son prix. Contactez support@secel.com pour plus d'informations."
        },
        "certificat": {
            "triggers": ["certificat", "diplôme", "attestation", "certification", "réussite"],
            "response": "🏆 SECEL délivre des certificats de réussite pour chaque cours complété à 100%. Ces certificats sont téléchargeables et partageables sur LinkedIn."
        },
        "default": "🤔 Je réfléchis... Un instant ! Je suis SELA, votre assistante IA. Posez-moi n'importe quelle question — SECEL, code, science, culture, ou tout autre sujet. Je suis là pour vous aider !"
    },

    "en": {
        "greetings": {
            "triggers": ["hello", "hi", "hey", "good morning", "good evening", "greetings", "howdy"],
            "response": "👋 Hello! I'm <b>SELA</b>, your AI assistant powered by Gemini. I can answer <b>any question</b> — about SECEL, technology, science, coding, history, and much more. How can I help you?"
        },
        "secel_info": {
            "triggers": ["what is secel", "about secel", "secel info", "tell me about", "describe secel", "what does secel do"],
            "response": "🎓 <b>SECEL</b> is a premium online learning platform based in Kinshasa, DRC. We offer high-quality training through video, PDF, and interactive courses in 5+ domains."
        },
        "inscription": {
            "triggers": ["register", "sign up", "create account", "new account", "join", "enrollment", "how to join"],
            "response": "📝 To register:<br>1. Click <b>'Sign Up'</b> at the top right<br>2. Choose your role: <b>Student</b> or <b>Teacher</b><br>3. Fill in your information<br>4. Confirm your account<br>It's free and quick!"
        },
        "connexion": {
            "triggers": ["login", "log in", "sign in", "password", "access", "connect"],
            "response": "🔐 To log in, click <b>'Login'</b>, enter your email and password. If you forgot your password, use 'Forgot Password' on the login page."
        },
        "cours": {
            "triggers": ["courses", "training", "learn", "program", "subject", "content", "catalog", "curriculum"],
            "response": "📚 SECEL offers courses in:<br>• <b>Technology & IT</b><br>• <b>Management & Leadership</b><br>• <b>Languages</b><br>• <b>Finance & Business</b><br>• <b>Personal Development</b><br>Browse our catalog to discover all programs."
        },
        "videos": {
            "triggers": ["video", "watch", "stream", "lecture", "play", "viewing"],
            "response": "🎬 To watch videos:<br>1. Log in to your account<br>2. Access your courses from the dashboard<br>3. Select a video<br><i>Note: Videos not watched for 30 days are automatically deleted.</i>"
        },
        "enseignant": {
            "triggers": ["teacher", "instructor", "professor", "publish", "add course", "upload", "educator"],
            "response": "👨‍🏫 As a teacher:<br>• Add video courses (MP4, AVI, MKV)<br>• Publish PDF documents<br>• Content validated by admin before publishing<br>Access your teacher dashboard to get started."
        },
        "paiement": {
            "triggers": ["payment", "pay", "orange money", "mtn", "mobile money", "momo", "recharge"],
            "response": "💳 SECEL accepts:<br>• <b>Orange Money</b> (080, 082, 084, 085)<br>• <b>MTN MoMo</b> (089, 090, 091, 097, 098)<br>Payment is done via Mobile Money. Enter your number and follow USSD instructions."
        },
        "contact": {
            "triggers": ["contact", "support", "help", "problem", "assistance", "email", "phone", "reach"],
            "response": "📞 Contact us:<br>• <b>Email:</b> support@secel.com<br>• <b>Hours:</b> Mon-Fri, 8am-6pm"
        },
        "prix": {
            "triggers": ["price", "cost", "free", "subscription", "how much", "pricing", "fee"],
            "response": "💰 Some SECEL courses are free, others are paid (via Mobile Money). Check each course page for pricing. Contact support@secel.com for more information."
        },
        "certificat": {
            "triggers": ["certificate", "diploma", "certification", "completion", "achievement"],
            "response": "🏆 SECEL issues completion certificates for every course completed at 100%. These certificates are downloadable and shareable on LinkedIn."
        },
        "default": "🤔 Let me think... I'm SELA, your AI assistant. Ask me anything — SECEL, coding, science, culture, or any topic. I'm here to help!"
    }
}


def detect_language(text):
    """Detect language from input text (FR or EN only)."""
    french_words = ['bonjour', 'salut', "qu'est", 'comment', 'merci', 'oui', 'non',
                    'je', 'tu', 'il', 'nous', 'vous', 'le', 'la', 'les', 'des',
                    'inscription', 'cours', 'vidéo', 'aide', 'connexion', 'pourquoi',
                    'quand', 'où', 'qui', 'quoi', 'est-ce', 'une', 'un',
                    'sur', 'pour', 'dans', 'avec', 'par', 'pas', 'plus', 'tout',
                    'est', 'sont', 'avoir', 'faire', 'être', 'quel', 'quelle']
    text_lower = text.lower()
    french_count = sum(1 for w in french_words if w in text_lower.split() or w in text_lower)
    if french_count >= 1:
        return 'fr'
    return 'en'


def _build_gemini_contents(history: list, message: str, lang: str):
    """
    Build multi-turn conversation contents for Gemini.
    history: list of {'role': 'user'|'assistant', 'content': str}
    """
    lang_map = {'fr': 'en français', 'en': 'in English'}
    lang_instruction = lang_map.get(lang, 'en français')

    contents = []

    # Add conversation history (keep last 10 exchanges = 20 messages max)
    recent_history = history[-20:] if len(history) > 20 else history
    for entry in recent_history:
        role = 'user' if entry.get('role') == 'user' else 'model'
        text = entry.get('content', '').strip()
        if text:
            contents.append(
                genai_types.Content(
                    role=role,
                    parts=[genai_types.Part(text=text)]
                )
            )

    # Add current message with language instruction
    user_prompt = (
        f"[Réponds OBLIGATOIREMENT {lang_instruction}. "
        f"Formate en HTML léger uniquement.]\n\n{message}"
    )
    contents.append(
        genai_types.Content(
            role='user',
            parts=[genai_types.Part(text=user_prompt)]
        )
    )
    return contents


def _call_gemini(message: str, lang: str, history: list = None) -> str | None:
    """Call Gemini API with full conversation history. Returns HTML-formatted response, or None on failure."""
    client = _init_gemini()
    if client is None:
        return None
    try:
        history = history or []
        contents = _build_gemini_contents(history, message, lang)

        # Ordre de préférence : modèles légers et rapides en premier
        _MODELS = [
            'gemini-2.5-flash-lite',
            'gemini-flash-lite-latest',
            'gemini-flash-latest',
            'gemini-2.5-flash',
            'gemini-2.0-flash',
        ]
        result = None
        last_err = None
        for _model in _MODELS:
            try:
                result = client.models.generate_content(
                    model=_model,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=_GEMINI_SYSTEM_PROMPT,
                        max_output_tokens=2000,
                        temperature=0.7,
                    )
                )
                break  # succès → on sort de la boucle
            except Exception as _e:
                last_err = _e
                # 404 = modèle non dispo, 429 = quota dépassé → essayer le suivant
                err_str = str(_e)
                if '404' in err_str or '429' in err_str:
                    continue
                raise  # autre erreur → remonter
        if result is None:
            raise last_err
        text = result.text.strip() if result.text else ''
        if not text:
            return None

        # Convert Markdown → HTML for chat UI
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'__(.+?)__',     r'<b>\1</b>', text)
        text = re.sub(r'\*(.+?)\*',     r'<i>\1</i>', text)
        text = re.sub(r'`(.+?)`',       r'<code>\1</code>', text)
        # Headings → bold
        text = re.sub(r'(?m)^#{1,3}\s+(.+)$', r'<b>\1</b>', text)
        # Lists
        text = re.sub(r'(?m)^[-*]\s+(.+)$',    r'• \1', text)
        text = re.sub(r'(?m)^\d+\.\s+(.+)$',   lambda m: f'• {m.group(1)}', text)
        # Newlines
        text = re.sub(r'\n{2,}', '<br><br>', text)
        text = re.sub(r'\n',     '<br>',     text)
        return text
    except Exception:
        return None


def get_chatbot_response(message: str, lang: str = None, history: list = None):
    """
    Get chatbot response with full conversation memory:
    1. Detect language
    2. For exact short keyword matches (greetings, SECEL info), use KB (instant, no API cost)
    3. For everything else → Gemini AI with full conversation history
    4. Fallback keyword matching if Gemini unavailable
    5. Static fallback
    Returns (response_html, detected_lang)
    """
    if not lang:
        lang = detect_language(message)
    if lang not in CHATBOT_KB:
        lang = 'fr'

    kb = CHATBOT_KB[lang]
    msg_lower = message.lower().strip()
    history = history or []

    # ── Step 1: Exact keyword matching ONLY for simple greetings (≤ 3 mots) ──
    # On ne bloque PAS les vraies questions avec les mots-clés
    word_count = len(msg_lower.split())
    if word_count <= 3:
        for category, data in kb.items():
            if category == 'default':
                continue
            if isinstance(data, dict) and 'triggers' in data:
                for trigger in data['triggers']:
                    # Correspondance exacte ou quasi-exacte uniquement
                    if msg_lower == trigger or msg_lower in [t.lower() for t in data['triggers']]:
                        return data['response'], lang

    # ── Step 2: Gemini AI avec historique complet ────────────────────────────
    gemini_response = _call_gemini(message, lang, history)
    if gemini_response:
        return gemini_response, lang

    # ── Step 3: Keyword matching complet si Gemini indisponible ─────────────
    for category, data in kb.items():
        if category == 'default':
            continue
        if isinstance(data, dict) and 'triggers' in data:
            for trigger in data['triggers']:
                if trigger in msg_lower or msg_lower in trigger:
                    return data['response'], lang

    # ── Step 4: Static fallback ──────────────────────────────────────────────
    return kb['default'], lang
