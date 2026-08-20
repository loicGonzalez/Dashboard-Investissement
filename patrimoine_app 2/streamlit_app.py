#!/usr/bin/env python3
"""Point d'entrée — navigation multipage Streamlit."""
import streamlit as st

st.set_page_config(
    page_title="Patrimoine",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

from core.state import init_session, rebuild_portfolios
from core.style import inject_css

init_session()
inject_css()

# Recalcule si des données sont déjà en session
if (
    st.session_state.get("pea_files_data")
    or st.session_state.get("pea_csv_data")
    or st.session_state.get("cto_files_data")
    or st.session_state.get("per_csv_data")
    or st.session_state.get("per_manual")
):
    rebuild_portfolios()

st.sidebar.markdown("### ◆ Patrimoine")
st.sidebar.caption("PEA · PER · CTO · SQLite local")
st.sidebar.markdown("---")
st.sidebar.info("Utilise le menu de pages ci-dessus pour naviguer.")
st.sidebar.markdown(
    """
**Parcours conseillé**
1. **Import** — charge PDF / CSV  
2. **Vue globale** — synthèse  
3. PEA / PER / CTO — détail
"""
)
