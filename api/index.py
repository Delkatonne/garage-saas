"""Point d'entrée Vercel (fonction serverless Python).

Vercel exécute ce fichier ; `vercel.json` envoie TOUTES les URL vers cette fonction.
"""
import os
import sys

# La racine du projet doit être importable (package `app`).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

app = create_app()
