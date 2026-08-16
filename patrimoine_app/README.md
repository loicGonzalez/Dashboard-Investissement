# Patrimoine — PEA · PER · CTO

Application Streamlit multipage (style sombre).

## Installation

```bash
pip install streamlit pdfplumber pandas yfinance plotly matplotlib
```

## Lancement

Depuis ce dossier :

```bash
cd patrimoine_app
streamlit run streamlit_app.py
```

## Pages

| Page | Rôle |
|------|------|
| **Import** | PDF CIC / Trade Republic, CSV PEA/PER, cours manuels |
| **Vue globale** | KPI, évolution, répartition, positions |
| **PEA / PER / CTO** | Détail par enveloppe |

## Parcours

1. Ouvre **Import** → charge tes fichiers → bouton *Charger / rafraîchir*
2. Ouvre **Vue globale** pour la synthèse
3. Zoom sur PEA, PER ou CTO si besoin


## Base SQLite

- Fichier : `data/patrimoine.db`
- Créée automatiquement au premier import
- Les opérations et cours manuels sont rechargés à chaque ouverture de l'app
- Mode **Fusionner** : ignore les doublons
- Mode **Remplacer** : réécrit l'enveloppe (CTO / PER CSV)


## Powens (optionnel)

1. Créer un compte sandbox sur [powens.com](https://www.powens.com/)
2. Copier `.env.example` → `.env` et renseigner domaine + client_id/secret
3. `pip install requests cryptography`
4. Page **Import** → section Powens : Init user → Webview → Synchroniser

**Ne jamais committer** : `.env`, `secrets/`, `data/*.db`


## Lancer sur Mac (double-clic)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x Lancer_Patrimoine.command
```

Ensuite double-clic sur `Lancer_Patrimoine.command` (détails dans `INSTALL_MAC.txt`).
