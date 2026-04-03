#!/usr/bin/env python3
"""
SECEL — Partage de l'application avec un client via tunnel public.

Usage:
  python share_app.py                  # Utilise localtunnel (sans compte requis)
  python share_app.py --ngrok TOKEN    # Utilise ngrok avec votre authtoken

Pour obtenir un authtoken ngrok gratuit : https://dashboard.ngrok.com/signup
"""

import subprocess
import sys
import os
import time
import threading
import signal

PORT = 5000
_procs = []


def _cleanup(*_):
    print("\n[SECEL] Arrêt des tunnels...")
    for p in _procs:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)


signal.signal(signal.SIGINT, _cleanup)
signal.signal(signal.SIGTERM, _cleanup)


def start_localtunnel(port: int):
    """Démarre localtunnel (Node.js requis, pas de compte nécessaire)."""
    print(f"[SECEL] Démarrage du tunnel via LocalTunnel sur le port {port}...")
    try:
        proc = subprocess.Popen(
            ["npx", "localtunnel", "--port", str(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _procs.append(proc)
        for line in proc.stdout:
            print(f"[LocalTunnel] {line.strip()}")
            if "your url is:" in line.lower():
                url = line.strip().split("is: ")[-1]
                print("\n" + "=" * 60)
                print(f"  🌐  URL publique SECEL : {url}")
                print("=" * 60)
                print("  Partagez ce lien avec votre client.")
                print("  ⚠️  Ce lien est temporaire (valide tant que ce script tourne).")
                print("=" * 60 + "\n")
        proc.wait()
    except FileNotFoundError:
        print("[ERREUR] npx/Node.js introuvable. Installez Node.js : https://nodejs.org")


def start_ngrok(port: int, authtoken: str):
    """Démarre ngrok avec un authtoken."""
    try:
        from pyngrok import ngrok, conf
        if authtoken:
            ngrok.set_auth_token(authtoken)
        public_url = ngrok.connect(port, "http")
        url = public_url.public_url
        print("\n" + "=" * 60)
        print(f"  🌐  URL publique SECEL : {url}")
        print("=" * 60)
        print("  Partagez ce lien avec votre client.")
        print("  ⚠️  Ce lien est temporaire (valide tant que ce script tourne).")
        print("=" * 60 + "\n")
        print("Appuyez sur Ctrl+C pour arrêter le tunnel.\n")
        # Keep alive
        while True:
            time.sleep(1)
    except ImportError:
        print("[ERREUR] pyngrok non installé. Exécutez : pip install pyngrok")
    except Exception as e:
        print(f"[ERREUR ngrok] {e}")
        print("Conseil : Vérifiez votre authtoken sur https://dashboard.ngrok.com/get-started/your-authtoken")


if __name__ == "__main__":
    args = sys.argv[1:]

    # Récupérer l'authtoken depuis .env si disponible
    authtoken = os.environ.get("NGROK_AUTHTOKEN", "")

    if "--ngrok" in args:
        idx = args.index("--ngrok")
        if idx + 1 < len(args):
            authtoken = args[idx + 1]
        if not authtoken:
            print("Usage : python share_app.py --ngrok VOTRE_AUTHTOKEN")
            print("Obtenez un token gratuit : https://dashboard.ngrok.com/get-started/your-authtoken")
            sys.exit(1)
        start_ngrok(PORT, authtoken)
    else:
        # Utiliser localtunnel par défaut
        start_localtunnel(PORT)
