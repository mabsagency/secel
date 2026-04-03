#!/usr/bin/env python
# ================================================================
# SECEL — Script de demarrage
# Usage : python run.py
# ================================================================
import os
import sys

def main():
    # 1. Verifier les dependances
    try:
        import flask, flask_sqlalchemy, flask_login, werkzeug, apscheduler
    except ImportError as e:
        print(f"[ERREUR] Dependance manquante: {e}")
        print("Lancez : pip install -r requirements.txt")
        sys.exit(1)

    # 2. Importer l'application
    from app import app
    from models import db
    from seed_data import seed_all

    # 3. Creer les dossiers necessaires
    os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
    os.makedirs('uploads', exist_ok=True)

    # 4. Initialiser la base de donnees
    with app.app_context():
        db.create_all()
        uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        if uri.startswith('sqlite'):
            print("[DB] Tables verifiees/creees (SQLite local).")
        else:
            print("[DB] Tables verifiees/creees (PostgreSQL Supabase).")

        # 5. Seeder les donnees demo si la DB est vide
        from models import User, Course
        if User.query.count() == 0:
            print("[SEED] Base vide detectee - chargement des donnees demo...")
            seed_all(app)
        else:
            print(f"[SEED] {User.query.count()} utilisateur(s) existant(s) - pas de re-seed.")

        # 5b. Migrate: normaliser la devise en XAF pour tous les cours existants
        updated = Course.query.filter(Course.currency.in_(['FCFA', 'CFA', 'F CFA'])).update({'currency': 'XAF'}, synchronize_session=False)
        if updated:
            db.session.commit()
            print(f"[MIGRATE] {updated} cours migre(s) vers la devise XAF.")

    # 6. Afficher les comptes de demo
    with app.app_context():
        from models import User, Course, Video
        print("\n" + "="*55)
        print("  SECEL - Plateforme de Formation en Ligne")
        print("="*55)
        print(f"  URL : http://127.0.0.1:5000")
        print(f"  Mode: DEBUG")
        print("-"*55)
        print("  COMPTES DE DEMONSTRATION :")
        print(f"  Admin    : admin@secel.com / Admin@2024!")
        print(f"  Etudiant : etudiant@secel.com / Student@2024!")
        print(f"  Enseignant: prof.ngoy@secel.com / Teacher@2024!")
        print("-"*55)
        print(f"  Base de donnees :")
        print(f"    Utilisateurs : {User.query.count()}")
        print(f"    Cours        : {Course.query.count()}")
        print(f"    Videos       : {Video.query.count()}")
        print("="*55 + "\n")

    # 7. Lancer le serveur
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=True,
        use_reloader=True,
    )

if __name__ == '__main__':
    main()
