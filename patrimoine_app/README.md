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
