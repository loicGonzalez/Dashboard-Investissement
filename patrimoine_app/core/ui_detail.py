"""Rendu détail enveloppe (PEA / PER / CTO)."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.state import enrich, metrics_for, get_history
from core.style import kpi_card, fmt_eur, PLOTLY_LAYOUT


def render_envelope_detail(title, env_key, show_fe=False):
    data = st.session_state.get(env_key)
    if not data or not data.get("txs"):
        st.warning(f"Aucune opération {title}. Va dans **Import** pour charger des fichiers.")
        return

    by_isin = data["by_isin"]
    txs = data["txs"]
    df = data["df"]
    fe_by_id = data.get("fe_by_id") if show_fe else {}

    info = enrich(by_isin)
    open_df, sold_df, summary = info["open"], info["sold"], info["summary"]
    m = metrics_for(txs, open_df, fe_by_id)

    st.markdown(f"## {title}")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    kpi_card(k1, "Apports", fmt_eur(m["apports"]))
    kpi_card(k2, "Cash estimé", fmt_eur(m["flow"]["cash"]))
    kpi_card(k3, "Valo titres", fmt_eur(m["valo_titres"]))
    kpi_card(k4, "Patrimoine", fmt_eur(m["patrimoine"]))
    kpi_card(
        k5, "Plus-value",
        fmt_eur(m["pv"], signed=True),
        delta=f'{m["pct"]:+.1f}%',
        positive=m["pv"] >= 0,
    )
    kpi_card(
        k6, "Frais d'achat",
        fmt_eur(m.get("frais_achat", 0)),
        sub="cumul ACHAT",
        positive=False,
    )

    tab1, tab2, tab3, tab4 = st.tabs(["Synthèse", "Opérations", "Évolution", "Export"])

    with tab1:
        if open_df is not None and not open_df.empty:
            st.markdown("**Positions ouvertes**")
            st.dataframe(open_df, use_container_width=True, hide_index=True)
        if sold_df is not None and not sold_df.empty:
            with st.expander(f"Positions soldées ({len(sold_df)})"):
                st.dataframe(sold_df, use_container_width=True, hide_index=True)
        if show_fe and fe_by_id:
            fe_rows = [{
                "ID": fid,
                "Nom": v["name"],
                "Versements": round(v["verse"], 2),
                "Retraits": round(v["retire"], 2),
                "Intérêts": round(v["interets"], 2),
                "Apports nets": round(v["apports"], 2),
                "Valorisation": round(v["valo"], 2),
            } for fid, v in fe_by_id.items()]
            st.markdown("**Fonds euros**")
            st.dataframe(pd.DataFrame(fe_rows), use_container_width=True, hide_index=True)

    with tab2:
        if df is not None and not df.empty:
            cols = [c for c in ["date_str", "type", "quantite", "isin", "valeur", "cours", "montant", "frais", "source"] if c in df.columns]
            st.dataframe(df[cols], use_container_width=True, hide_index=True)

    with tab3:
        hist = get_history(f"{env_key}_{len(txs)}", by_isin, txs)
        pv = hist["portfolio_value"]
        inv = hist["invested_cumul"]
        if not pv.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=pv.index, y=pv, name="Valorisation",
                line=dict(color="#60a5fa", width=2.2),
                fill="tozeroy", fillcolor="rgba(96,165,250,0.08)",
            ))
            fig.add_trace(go.Scatter(
                x=inv.index, y=inv, name="Investi",
                line=dict(color="#a78bfa", width=2, dash="dot"),
            ))
            fig.update_layout(
                **PLOTLY_LAYOUT, height=380, hovermode="x unified",
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#1f2937", ticksuffix=" €"),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Pas encore d'historique traçable.")

    with tab4:
        if summary is not None and not summary.empty:
            st.download_button(
                "Télécharger synthèse CSV",
                summary.to_csv(index=False).encode("utf-8-sig"),
                f"synthese_{env_key}.csv",
                "text/csv",
            )
