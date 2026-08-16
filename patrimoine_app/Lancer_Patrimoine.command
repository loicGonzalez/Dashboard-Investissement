#!/bin/bash
# Double-clic dans le Finder pour lancer le dashboard Patrimoine (Streamlit).
set -e
cd "$(dirname "$0")"

echo "═══════════════════════════════════════"
echo "  Patrimoine — PEA · PER · CTO"
echo "═══════════════════════════════════════"
echo "Dossier : $(pwd)"
echo ""

# Préfère un venv local s'il existe
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
  echo "Environnement : .venv"
elif [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
  echo "Environnement : venv"
else
  echo "Environnement : Python système"
fi

if ! command -v streamlit >/dev/null 2>&1; then
  echo ""
  echo "ERREUR : streamlit introuvable."
  echo "Installe les dépendances une fois :"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -r requirements.txt"
  echo ""
  read -r -p "Appuie sur Entrée pour fermer…"
  exit 1
fi

if [ ! -f "streamlit_app.py" ]; then
  echo "ERREUR : streamlit_app.py introuvable dans ce dossier."
  read -r -p "Appuie sur Entrée pour fermer…"
  exit 1
fi

echo "Lancement de Streamlit…"
echo "Une fenêtre de navigateur devrait s'ouvrir (http://localhost:8501)"
echo "Pour arrêter : Ctrl+C dans cette fenêtre."
echo ""

exec streamlit run streamlit_app.py
