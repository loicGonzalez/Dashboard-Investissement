"""Page PER."""
import streamlit as st
from core.state import init_session, rebuild_portfolios
from core.style import inject_css
from core.nav import render_sidebar
from core.ui_detail import render_envelope_detail

st.set_page_config(page_title="PER — Patrimoine", page_icon="◆", layout="wide")
init_session()
inject_css()
render_sidebar(active="per")
if any(st.session_state.get(k) for k in ("pea_files_data", "pea_csv_data", "cto_files_data", "per_csv_data", "per_manual")):
    if "per" not in st.session_state:
        rebuild_portfolios()

render_envelope_detail("PER", "per", show_fe=True)
