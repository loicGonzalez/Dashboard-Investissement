"""Barre latérale personnalisée."""
from __future__ import annotations

import streamlit as st

from core.style import inject_css


def render_sidebar(active: str = "home") -> None:
    """
    Navigation custom.
    active: home | pea | per | cto | import
    """
    inject_css()

    st.sidebar.markdown(
        """
        <div style="padding:0.2rem 0 0.8rem 0;">
          <div style="font-size:1.15rem;font-weight:700;color:#f9fafb;letter-spacing:-0.02em;">
            Patrimoine
          </div>
          <div style="font-size:0.78rem;color:#6b7280;margin-top:0.15rem;">
            PEA · PER · CTO · local
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Indicateurs mini si données chargées
    has = any(
        st.session_state.get(k)
        for k in ("pea_files_data", "pea_csv_data", "cto_files_data", "per_csv_data", "per_manual", "livrets_data")
    )
    if has:
        pea = st.session_state.get("pea") or {}
        per = st.session_state.get("per") or {}
        cto = st.session_state.get("cto") or {}
        n_pea = len(pea.get("txs") or [])
        n_per = len(per.get("txs") or [])
        n_cto = len(cto.get("txs") or [])
        st.sidebar.caption(f"Ops : PEA {n_pea} · PER {n_per} · CTO {n_cto}")

    st.sidebar.markdown("#### Navigation")

    def _link(label: str, page: str, key: str, icon: str = ""):
        # page_link : page relative au projet
        is_active = active == key
        prefix = "● " if is_active else "○ "
        try:
            st.sidebar.page_link(page, label=f"{prefix}{label}", icon=icon or None)
        except TypeError:
            # anciennes versions sans icon=
            st.sidebar.page_link(page, label=f"{prefix}{label}")
        except Exception:
            st.sidebar.markdown(f"{prefix}{label}")

    _link("Vue globale", "streamlit_app.py", "home", "🏠")
    _link("PEA", "pages/2_PEA.py", "pea", "📘")
    _link("PER", "pages/3_PER.py", "per", "🟣")
    _link("CTO", "pages/4_CTO.py", "cto", "📗")
    _link("Livrets", "pages/6_Livrets.py", "livrets", "🛡️")
    _link("Import", "pages/5_Import.py", "import", "📥")

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        """
        <div style="font-size:0.75rem;color:#6b7280;line-height:1.45;">
          <b style="color:#9ca3af;">Raccourci</b><br/>
          1. Import PDF / CSV<br/>
          2. Vue globale<br/>
          3. Détail par enveloppe
        </div>
        """,
        unsafe_allow_html=True,
    )
