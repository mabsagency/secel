import sys
import os

# Ajouter le répertoire racine au path Python
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

try:
    from app import app
    handler = app
except Exception as e:
    # En cas d'erreur d'import, retourner un message clair plutôt qu'un crash opaque
    import traceback
    from flask import Flask, jsonify
    _fallback = Flask(__name__)

    @_fallback.route('/', defaults={'path': ''})
    @_fallback.route('/<path:path>')
    def _error(path):
        return jsonify({
            'error': 'App failed to start',
            'detail': str(e),
            'trace': traceback.format_exc()
        }), 500

    handler = _fallback
