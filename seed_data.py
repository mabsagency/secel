# ================================================================
# SECEL — Seed Sample IT Courses + Demo Users
# ================================================================
from datetime import datetime
from models import db, User, Course, Video, Enrollment, VideoProgress


def seed_all(app):
    with app.app_context():
        # ── Admin ──────────────────────────────────────────────
        if not User.query.filter_by(role='admin').first():
            admin = User(username='admin', email='admin@secel.com',
                         full_name='Administrateur SECEL', role='admin', is_active=True)
            admin.set_password('Admin@2024!')
            db.session.add(admin)
            db.session.commit()
            print("Admin cree")

        # ── Demo Teacher ──────────────────────────────────────
        teacher = User.query.filter_by(email='prof.ngoy@secel.com').first()
        if not teacher:
            teacher = User(
                username='prof_ngoy', email='prof.ngoy@secel.com',
                full_name='Prof. Thomas Ngoy', role='teacher', is_active=True,
                specialty='Informatique, Intelligence Artificielle',
                qualifications='MSc Informatique - Universite de Kinshasa | Certifie AWS',
                years_experience=8,
                bio='Professeur passionne par la technologie africaine et la democratisation de l\'IA.'
            )
            teacher.set_password('Teacher@2024!')
            db.session.add(teacher)

            teacher2 = User(
                username='dr_kamara', email='dr.kamara@secel.com',
                full_name='Dr. Aisha Kamara', role='teacher', is_active=True,
                specialty='Cybersecurite, Reseaux',
                qualifications='PhD Securite Informatique | CEH, CISSP',
                years_experience=12,
                bio='Experte en securite des systemes d\'information avec 12 ans d\'experience internationale.'
            )
            teacher2.set_password('Teacher@2024!')
            db.session.add(teacher2)

            teacher3 = User(
                username='mensah_kofi', email='k.mensah@secel.com',
                full_name='M. Kofi Mensah', role='teacher', is_active=True,
                specialty='Developpement Web, Mobile',
                qualifications='BEng Software Engineering | Google Certified Developer',
                years_experience=6,
                bio='Developpeur full-stack specialise dans les apps mobiles africaines.'
            )
            teacher3.set_password('Teacher@2024!')
            db.session.add(teacher3)
            db.session.commit()
            teacher  = User.query.filter_by(email='prof.ngoy@secel.com').first()
            teacher2 = User.query.filter_by(email='dr.kamara@secel.com').first()
            teacher3 = User.query.filter_by(email='k.mensah@secel.com').first()

        else:
            teacher2 = User.query.filter_by(email='dr.kamara@secel.com').first()
            teacher3 = User.query.filter_by(email='k.mensah@secel.com').first()
            if not teacher2: teacher2 = teacher
            if not teacher3: teacher3 = teacher

        # ── Demo Student ──────────────────────────────────────
        student = User.query.filter_by(email='etudiant@secel.com').first()
        if not student:
            student = User(
                username='jean_paul', email='etudiant@secel.com',
                full_name='Jean-Paul Mukendi', role='student', is_active=True,
                student_level='Debutant', learning_goals='Devenir developpeur full-stack'
            )
            student.set_password('Student@2024!')
            db.session.add(student)
            db.session.commit()
            student = User.query.filter_by(email='etudiant@secel.com').first()

        # ── IT Courses ─────────────────────────────────────────
        if Course.query.count() > 0:
            print("Courses already seeded")
            return

        courses_data = [
            {
                'title': 'Python pour Debutants — De Zero a Hero',
                'description': ('Maitrisez Python, le langage le plus demande au monde. '
                                'De la syntaxe de base aux projets concrets : web scraping, '
                                'automatisation, manipulation de donnees. Idéal pour commencer '
                                'une carriere en developpement logiciel.'),
                'category': 'Informatique & Programmation',
                'level': 'Debutant',
                'price': 0.0, 'is_free': True,
                'duration_hours': 24.0,
                'teacher': teacher,
                'videos': [
                    ('Introduction a Python & Installation', 'Installer Python et votre premier programme Hello World', 720, True),
                    ('Variables, Types et Operateurs', 'Les fondamentaux de la programmation Python', 1080, True),
                    ('Structures de Controle (if/else/for/while)', 'Prise de decision et boucles en Python', 1200, True),
                    ('Fonctions et Modules', 'Structurer votre code avec des fonctions réutilisables', 1440, True),
                    ('Listes, Tuples et Dictionnaires', 'Structures de donnees essentielles', 1320, True),
                    ('Programmation Orientee Objet (POO)', 'Classes, objets et heritage en Python', 1800, True),
                    ('Gestion des Fichiers & Exceptions', 'Lire/ecrire des fichiers et gerer les erreurs', 960, True),
                    ('Projet Final — Application de Gestion', 'Construire une vraie application Python', 2400, True),
                ],
            },
            {
                'title': 'Developpement Web Full Stack — HTML CSS JS & Python Flask',
                'description': ('Apprenez a construire des sites web professionnels de A a Z. '
                                'Front-end avec HTML5, CSS3, JavaScript moderne. Back-end avec '
                                'Python Flask et base de donnees SQLite. Deployez sur le cloud.'),
                'category': 'Developpement Web',
                'level': 'Intermediaire',
                'price': 29.99, 'is_free': False, 'currency': 'USD',
                'duration_hours': 40.0,
                'teacher': teacher,
                'videos': [
                    ('HTML5 Fondamentaux & Semantique', 'Structurer le contenu web avec HTML5', 900, True),
                    ('CSS3 Avance & Responsive Design', 'Styliser et adapter vos pages a tous les ecrans', 1200, True),
                    ('JavaScript ES6+ Moderne', 'Variables, fonctions fleches, async/await', 1500, True),
                    ('DOM Manipulation & Events', 'Rendre vos pages interactives', 1080, True),
                    ('Introduction a Flask (Python)', 'Creer votre premier serveur web', 1320, True),
                    ('Templates Jinja2 & Routes', 'Structurer une application Flask', 1080, True),
                    ('Bases de Donnees avec SQLAlchemy', 'CRUD complet avec SQLite et SQLAlchemy', 1440, True),
                    ('Authentification & Sessions', 'Login, logout, sessions securisees', 1200, True),
                    ('Deploiement sur Heroku/Railway', 'Mettre votre app en ligne gratuitement', 900, True),
                ],
            },
            {
                'title': 'Intelligence Artificielle & Machine Learning Pratique',
                'description': ('De la theorie a la pratique : reseaux de neurones, classification, '
                                'regression, NLP et vision par ordinateur. Utilisez scikit-learn, '
                                'TensorFlow et PyTorch. Projets reels inclus.'),
                'category': 'Intelligence Artificielle',
                'level': 'Avance',
                'price': 49.99, 'is_free': False, 'currency': 'USD',
                'duration_hours': 55.0,
                'teacher': teacher,
                'videos': [
                    ('Introduction au Machine Learning', 'Types d\'apprentissage et applications', 1200, True),
                    ('Numpy & Pandas pour la Data Science', 'Manipulation et analyse de donnees', 1440, True),
                    ('Visualisation avec Matplotlib & Seaborn', 'Graphiques et insights visuels', 960, True),
                    ('Regression Lineaire & Logistique', 'Predictions numeriques et classification', 1680, True),
                    ('Arbres de Decision & Random Forest', 'Modeles ensemblistes puissants', 1440, True),
                    ('Reseaux de Neurones avec TensorFlow', 'Deep Learning pas a pas', 2100, True),
                    ('CNN — Vision par Ordinateur', 'Reconnaissance d\'images et detection d\'objets', 1800, True),
                    ('NLP — Traitement du Langage Naturel', 'Analyse de texte, chatbots, sentiment', 1680, True),
                    ('Projet : Systeme de Recommandation', 'Application complete de bout en bout', 2400, True),
                ],
            },
            {
                'title': 'Cybersecurite Professionnelle — Ethical Hacking',
                'description': ('Devenez un expert en securite informatique. Apprenez le pentest, '
                                'la cryptographie, la detection d\'intrusions et la protection des '
                                'systemes. Preparez les certifications CEH et CompTIA Security+.'),
                'category': 'Cybersecurite',
                'level': 'Intermediaire',
                'price': 39.99, 'is_free': False, 'currency': 'USD',
                'duration_hours': 45.0,
                'teacher': teacher2,
                'videos': [
                    ('Introduction a la Cybersecurite', 'Panorama des menaces et carrieres', 1080, True),
                    ('Modele OSI & Protocoles Reseau', 'Comprendre TCP/IP, DNS, HTTP', 1320, True),
                    ('Kali Linux — Environnement de Test', 'Installer et configurer Kali Linux', 1200, True),
                    ('Reconnaissance & OSINT', 'Collecte d\'informations et footprinting', 1440, True),
                    ('Scanning & Enumeration avec Nmap', 'Detecter les ports et services ouverts', 1200, True),
                    ('Exploitation avec Metasploit', 'Framework de tests de penetration', 1680, True),
                    ('Attaques Web — SQL Injection & XSS', 'Les failles OWASP Top 10', 1560, True),
                    ('Cryptographie & Chiffrement', 'SSL/TLS, AES, RSA, hachage', 1320, True),
                    ('Incident Response & Forensics', 'Reponse aux incidents et analyse', 1440, True),
                ],
            },
            {
                'title': 'Administration de Bases de Donnees — SQL & NoSQL',
                'description': ('Maitrisez la gestion des bases de donnees relationnelles (MySQL, '
                                'PostgreSQL) et NoSQL (MongoDB, Redis). Optimisation, sauvegarde, '
                                'securite et administration avancee.'),
                'category': 'Bases de Donnees',
                'level': 'Intermediaire',
                'price': 24.99, 'is_free': False, 'currency': 'USD',
                'duration_hours': 30.0,
                'teacher': teacher,
                'videos': [
                    ('Fondamentaux SQL', 'SELECT, INSERT, UPDATE, DELETE', 1080, True),
                    ('Jointures et Sous-requetes', 'INNER JOIN, LEFT JOIN, requetes imbriquees', 1320, True),
                    ('Index et Optimisation', 'Ameliorer les performances des requetes', 1200, True),
                    ('Transactions et ACID', 'Intégrité des donnees et gestion des transactions', 960, True),
                    ('Administration MySQL', 'Installation, configuration et securite', 1440, True),
                    ('PostgreSQL Avance', 'Fonctions window, JSON, extensions', 1320, True),
                    ('Introduction a MongoDB', 'Documents, collections, aggregations', 1200, True),
                    ('Redis — Cache et Files de Messages', 'Sessions, cache, pub/sub', 960, True),
                ],
            },
            {
                'title': 'Developpement Mobile — Android & Flutter',
                'description': ('Creez des applications mobiles professionnelles pour Android et iOS '
                                'avec Flutter. De la conception UI/UX au deploiement sur les stores. '
                                'Projets concrets inclus.'),
                'category': 'Developpement Mobile',
                'level': 'Intermediaire',
                'price': 34.99, 'is_free': False, 'currency': 'USD',
                'duration_hours': 38.0,
                'teacher': teacher3,
                'videos': [
                    ('Introduction a Flutter & Dart', 'Installer Flutter et comprendre Dart', 1080, True),
                    ('Widgets et Layout Flutter', 'Row, Column, Stack, Scaffold', 1320, True),
                    ('Navigation et Routes', 'Navigation entre ecrans et parametres', 1080, True),
                    ('Gestion d\'Etat avec Provider', 'Architecture MVVM et state management', 1440, True),
                    ('Appels API REST & HTTP', 'Consommer des APIs avec Dart', 1320, True),
                    ('Base de Donnees Locale — SQLite & Hive', 'Persistence des donnees', 1200, True),
                    ('Notifications Push & Firebase', 'FCM et backend Firebase', 1440, True),
                    ('Projet Complet — App de Commerce', 'E-commerce mobile de bout en bout', 2700, True),
                ],
            },
            {
                'title': 'Cloud Computing & DevOps — AWS & Docker',
                'description': ('Maitrisez les services AWS (EC2, S3, Lambda, RDS), Docker, '
                                'Kubernetes et les pipelines CI/CD. Preparez la certification AWS '
                                'Cloud Practitioner.'),
                'category': 'Cloud & DevOps',
                'level': 'Avance',
                'price': 44.99, 'is_free': False, 'currency': 'USD',
                'duration_hours': 50.0,
                'teacher': teacher,
                'videos': [
                    ('Introduction au Cloud Computing', 'IaaS, PaaS, SaaS et fournisseurs', 1080, True),
                    ('AWS — EC2 et VPC', 'Instances cloud et reseau virtuel', 1440, True),
                    ('AWS S3 & IAM', 'Stockage d\'objets et gestion des droits', 1200, True),
                    ('Docker Fondamentaux', 'Images, conteneurs, Dockerfile', 1320, True),
                    ('Docker Compose', 'Orchestrer des applications multi-conteneurs', 1080, True),
                    ('Introduction a Kubernetes', 'Pods, Services, Deployments', 1680, True),
                    ('CI/CD avec GitHub Actions', 'Automatiser les tests et deployments', 1320, True),
                    ('AWS Lambda & Serverless', 'Architecture sans serveur', 1200, True),
                    ('Monitoring — CloudWatch & Grafana', 'Surveiller vos applications', 1080, True),
                ],
            },
            {
                'title': 'Reseaux Informatiques — CCNA & Administration',
                'description': ('Apprenez les fondamentaux des reseaux : protocoles, routage, '
                                'commutation, VLANs, VPN et securite reseau. Preparez le CCNA '
                                'Cisco et devenez administrateur reseau.'),
                'category': 'Reseaux',
                'level': 'Debutant',
                'price': 0.0, 'is_free': True,
                'duration_hours': 35.0,
                'teacher': teacher2,
                'videos': [
                    ('Modeles OSI et TCP/IP', 'Comprendre les 7 couches reseau', 1200, True),
                    ('Adressage IP et Sous-reseaux', 'IPv4, IPv6, CIDR, subnetting', 1440, True),
                    ('Routage Statique et Dynamique', 'RIP, OSPF, EIGRP', 1560, True),
                    ('Commutation et VLANs', 'Switch, trunk, STP, VLANs', 1320, True),
                    ('ACL et Securite Reseau', 'Filtrage de trafic et pare-feux', 1200, True),
                    ('VPN et Tunnels', 'IPSec, OpenVPN, site-to-site', 1080, True),
                    ('Wireless Networking', 'Wi-Fi 6, securite WPA3, optimisation', 960, True),
                    ('Depot de Paquets avec Wireshark', 'Analyser le trafic reseau', 1200, True),
                ],
            },
        ]

        for cdata in courses_data:
            teacher_obj = cdata.pop('teacher')
            videos_data = cdata.pop('videos')
            course = Course(teacher_id=teacher_obj.id, **cdata, is_published=True)
            db.session.add(course)
            db.session.flush()   # get course.id

            for idx, (vtitle, vdesc, vdur, approved) in enumerate(videos_data):
                video = Video(
                    title=vtitle, description=vdesc,
                    course_id=course.id,
                    is_local=False,
                    external_url='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
                    duration_seconds=vdur,
                    is_approved=approved,
                    order_index=idx + 1,
                )
                db.session.add(video)

        # ── Enroll demo student in free courses ───────────────
        db.session.flush()
        free_courses = Course.query.filter_by(is_free=True, is_published=True).all()
        for c in free_courses:
            enroll = Enrollment(student_id=student.id, course_id=c.id, progress=35.0)
            db.session.add(enroll)

        db.session.commit()
        print(f"Seeded {Course.query.count()} courses, {Video.query.count()} videos.")
