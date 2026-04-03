"""
Lance le tunnel ngrok et garde la connexion active.
Exécuter : python run_ngrok.py
"""
from pyngrok import ngrok
import time, sys

TOKEN = "3BD6ZGb6N9ZFLu76j6zihsUxaRk_8a2spcCRxeh3XZkfzEH6n"

ngrok.set_auth_token(TOKEN)
public_url = ngrok.connect(5000, "http")

print("\n" + "=" * 60)
print(f"  🌐  URL publique SECEL : {public_url.public_url}")
print("=" * 60)
print("  Partagez ce lien avec votre client.")
print("  ⚠️  Appuyez sur Ctrl+C pour arrêter le tunnel.")
print("=" * 60 + "\n")

try:
    while True:
        time.sleep(30)
except KeyboardInterrupt:
    print("\n[SECEL] Arrêt du tunnel ngrok...")
    ngrok.disconnect(public_url.public_url)
    ngrok.kill()
    sys.exit(0)
