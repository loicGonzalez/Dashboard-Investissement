#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  cp -n env.example .env 2>/dev/null || cp env.example .env
  echo "Créé .env — à éditer avec tes clés Powens"
else
  echo ".env existe déjà"
fi
mkdir -p data secrets
touch data/.gitkeep secrets/.gitkeep
echo "OK. Puis : pip install -r requirements.txt && streamlit run streamlit_app.py"
