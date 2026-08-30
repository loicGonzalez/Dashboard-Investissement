"""Page CTO."""
import streamlit as st
from core.state import init_session, rebuild_portfolios
from core.style import inject_css
from core.nav import render_sidebar
from core.ui_detail import render_envelope_detail

st.set_page_config(page_title="CTO · Patrimoine", page_icon="◆", layout="wide")
init_session()
inject_css()
render_sidebar(active="cto")
if any(st.session_state.get(k) for k in ("pea_files_data", "pea_csv_data", "cto_files_data", "per_csv_data", "per_manual")):
    if "cto" not in st.session_state:
        rebuild_portfolios()

render_envelope_detail("CTO", "cto", show_fe=False)
