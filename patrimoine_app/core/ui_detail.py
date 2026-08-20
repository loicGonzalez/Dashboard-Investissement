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

    # Alertes cours manquants
    try:
        from core.import_log import missing_price_alerts_from_open_df
        _ma = missing_price_alerts_from_open_df(open_df)
        if _ma:
            st.warning(
                f"⚠️ {len(_ma)} position(s) sans cours : "
                + ", ".join(f"{a.get('Nom') or a.get('ISIN')}" for a in _ma[:5])
                + ("…" if len(_ma) > 5 else "")
                + " — page Import → cours manuels."
            )
    except Exception:
        pass

    tab1, tab2, tab3, tab4 = st.tabs(["Synthèse", "Opérations", "Évolution", "Export"])

    with tab1:
        if open_df is not None and not open_df.empty:
            st.markdown("**Positions ouvertes**")
            if open_df is not None and not open_df.empty and open_df["Valorisation (€)"].isna().all():
                st.warning("Cours Yahoo indisponibles : valo à 0. Vérifie la connexion internet / tickers, ou saisis un cours manuel (page Import). Le fallback dernier cours d'opération devrait s'appliquer au prochain refresh.")
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

        fe_v = sum(v["valo"] for v in (fe_by_id or {}).values()) if show_fe else 0.0
        st.markdown("---")
        render_geo_section(open_df, fe_valo=fe_v, title="Répartition géographique")

    with tab2:
        if df is not None and not df.empty:
            cols = [c for c in ["date_str", "type", "quantite", "isin", "valeur", "cours", "montant", "frais", "source"] if c in df.columns]
            st.dataframe(df[cols], use_container_width=True, hide_index=True)

    with tab3:
        from core.portfolio import performance_periods

        hist = get_history(f"{env_key}_{len(txs)}", by_isin, txs)
        pv = hist["portfolio_value"]
        inv = hist["invested_cumul"]
        if not pv.empty:
            # —— Bloc A : PV latente (alignée KPI) ——
            st.markdown("**A · PV latente (aujourd’hui)**")
            st.caption(
                "Valorisation actuelle − coût de revient des positions encore ouvertes "
                "(même base que le KPI Plus-value)."
            )
            c_pv, c_detail = st.columns([1, 2])
            pv_latente = m["valo_titres"] - m["investi_ouvert"]
            pct_lat = (100 * pv_latente / m["investi_ouvert"]) if m["investi_ouvert"] else 0.0
            kpi_card(
                c_pv,
                "PV latente",
                fmt_eur(pv_latente, signed=True),
                delta=f"{pct_lat:+.1f}%",
                positive=pv_latente >= 0,
            )
            with c_detail:
                st.markdown(
                    f"<div style='padding:12px 8px;color:#9ca3af;font-size:0.9rem'>"
                    f"Valo titres <b style='color:#e5e7eb'>{fmt_eur(m['valo_titres'])}</b>"
                    f" &nbsp;−&nbsp; Investi ouvert "
                    f"<b style='color:#e5e7eb'>{fmt_eur(m['investi_ouvert'])}</b>"
                    f"<br/><span style='font-size:0.8rem'>"
                    f"Le KPI « Plus-value » en tête = patrimoine − apports "
                    f"(peut différer si cash / fonds euros)."
                    f"</span></div>",
                    unsafe_allow_html=True,
                )

            st.markdown("")
            # —— Bloc B : perf par période ——
            st.markdown("**B · Perf hors apports (par période)**")
            st.caption(
                "(Δ valo − Δ investi) / valo début de période. "
                "Les versements ne comptent pas comme performance. Pas un TRI exact."
            )
            rows = performance_periods(pv, inv)
            cols = st.columns(len(rows))
            for col, row in zip(cols, rows):
                if not row["available"]:
                    kpi_card(col, row["label"], "—", sub="n/d")
                    continue
                kpi_card(
                    col,
                    row["label"],
                    fmt_eur(row["delta_eur"], signed=True),
                    delta=f'{row["delta_pct"]:+.2f}%',
                    positive=row["delta_eur"] >= 0,
                )
            st.markdown("")
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


def render_geo_section(open_df, fe_valo=0.0, title="Répartition géographique"):
    """Donut + tableau geo à partir des positions ouvertes."""
    import plotly.graph_objects as go
    import streamlit as st
    from core.geography import allocate_geo, geo_to_frame, ZONE_COLORS, ZONES
    from core.style import PLOTLY_LAYOUT

    if open_df is None or (hasattr(open_df, "empty") and open_df.empty):
        if not fe_valo:
            st.caption("Pas de positions pour la géographie.")
            return
        positions = []
    else:
        positions = open_df.to_dict("records")

    geo = allocate_geo(positions, fe_valo=fe_valo)
    if not geo:
        st.caption("Aucune valorisation à ventiler.")
        return

    df = geo_to_frame(geo)
    st.markdown(f"**{title}**")
    c1, c2 = st.columns([1.1, 1])
    with c1:
        labels = list(geo.keys())
        values = list(geo.values())
        colors = [ZONE_COLORS.get(z, "#64748b") for z in labels]
        fig = go.Figure(data=[go.Pie(
            labels=labels, values=values, hole=0.55,
            marker=dict(colors=colors),
            textinfo="label+percent",
            textfont=dict(size=11, color="#e5e7eb"),
            hovertemplate="%{label}<br>%{value:,.0f} €<br>%{percent}<extra></extra>",
        )])
        total = sum(values)
        fig.update_layout(**PLOTLY_LAYOUT, height=320, showlegend=False)
        fig.add_annotation(
            text=f"<b>{total:,.0f} €</b>".replace(",", " "),
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#f9fafb"),
        )
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(
            "ETF Monde / EM : split indicatif type indice (pas un reporting émetteur exact)."
        )

    # —— Cibles d'allocation vs réel ——
    try:
        from core.db import get_allocation_targets
        from core.geography import allocation_gap, ALLOC_ZONES, DEFAULT_TARGETS
        targets = get_allocation_targets()
        gap_df = allocation_gap(geo, targets)
        st.markdown("**Allocation cible vs réelle**")
        st.caption(
            "Réel (%) sur la poche investie (hors fonds euros / non classé). "
            "Écart (€) = surplus ou manque vs cible."
        )
        st.dataframe(gap_df, use_container_width=True, hide_index=True)

        # Barres écart
        plot_df = gap_df[gap_df["Cible (%)"].notna()].copy()
        if not plot_df.empty:
            import plotly.graph_objects as go
            from core.style import PLOTLY_LAYOUT
            fig_g = go.Figure()
            fig_g.add_trace(go.Bar(
                name="Réel %", x=plot_df["Zone"], y=plot_df["Réel (%)"],
                marker_color="#3b82f6",
            ))
            fig_g.add_trace(go.Bar(
                name="Cible %", x=plot_df["Zone"], y=plot_df["Cible (%)"],
                marker_color="#64748b",
            ))
            fig_g.update_layout(
                **PLOTLY_LAYOUT, barmode="group", height=300,
                yaxis_title="%", xaxis_title=None,
            )
            st.plotly_chart(fig_g, use_container_width=True)
    except Exception as e:
        st.caption(f"Cibles d'allocation indisponibles : {e}")
