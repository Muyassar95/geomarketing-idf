"""Affichage commun : en-tête dégagé, indicateurs lisibles et petits écrans.

Remplacer ce seul module suffit si streamlit_app.py appelle déjà apply_design().
Les règles restent limitées à la présentation ; les calculs sont inchangés.
"""

import streamlit as st


DESIGN_CSS = """
<style>
.stApp {
    background: #f5f8fa;
    color: #132b3a;
}

/* La barre native reste utilisable. Le contenu commence sous cette barre. */
[data-testid="stHeader"] {
    background: #f5f8fa;
    border-bottom: 1px solid #e2eaee;
}
.stApp .block-container {
    max-width: 1450px;
    padding-top: 5.5rem !important;
    padding-bottom: 3rem;
    padding-left: clamp(1rem, 3vw, 3rem);
    padding-right: clamp(1rem, 3vw, 3rem);
}

.stApp h1, .stApp h2, .stApp h3 {
    color: #132b3a;
    letter-spacing: -.025em;
    overflow-wrap: anywhere;
    scroll-margin-top: 5.5rem;
}
.stApp h1 {
    font-size: clamp(1.8rem, 3.2vw, 2.65rem);
    line-height: 1.18;
    padding-top: .15rem;
    padding-bottom: .65rem;
}
.geo-kicker {
    display: block;
    font-size: .75rem;
    line-height: 1.65;
    letter-spacing: .13em;
    color: #086f7a;
    font-weight: 700;
    margin: 0 0 .55rem;
    white-space: normal;
    overflow-wrap: anywhere;
}

[data-testid="stSidebar"] {
    background: #edf3f5;
    border-right: 1px solid #d8e4e9;
}
[data-testid="stSidebar"] h2 {
    font-size: 1.2rem;
}

/* Les intitulés longs peuvent occuper plusieurs lignes. */
[data-testid="stMetric"] {
    height: 100%;
    box-sizing: border-box;
    background: #fff;
    border: 1px solid #dce7eb;
    border-radius: 14px;
    padding: 1rem 1.1rem;
    box-shadow: 0 3px 12px rgba(19, 43, 58, .035);
}
[data-testid="stMetricLabel"] {
    color: #354f60;
    min-height: 2.65rem;
    height: auto;
    align-items: flex-start;
}
[data-testid="stMetricLabel"] > div,
[data-testid="stMetricLabel"] p {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    line-height: 1.4;
    overflow-wrap: anywhere;
}
[data-testid="stMetricValue"] {
    color: #086f7a;
    font-size: clamp(1.55rem, 2.3vw, 2.15rem);
    font-weight: 650;
    font-variant-numeric: tabular-nums;
    line-height: 1.3;
}
[data-testid="stMetricValue"] > div {
    white-space: normal !important;
    overflow: visible !important;
    text-overflow: clip !important;
    overflow-wrap: anywhere;
}
[data-testid="stCaptionContainer"] {
    color: #526675;
    line-height: 1.5;
}

/* Les choix horizontaux peuvent revenir à la ligne. */
[data-testid="stRadio"] [role="radiogroup"] {
    flex-wrap: wrap;
    row-gap: .5rem;
}
[data-testid="stTabs"] [role="tablist"] {
    gap: .4rem;
}
[data-testid="stTabs"] [role="tab"] {
    white-space: normal;
    height: auto;
    min-height: 2.7rem;
    padding: .6rem .85rem;
}
[data-testid="stExpander"] {
    background: #fff;
    border-radius: 12px;
}
[data-testid="stExpander"] summary {
    line-height: 1.5;
}
[data-testid="stDataFrame"] {
    border-radius: 10px;
    overflow: hidden;
}
[data-testid="stDownloadButton"] button {
    border-radius: 9px;
    border-color: #087f8c;
    background: #fff;
    color: #086f7a;
    min-height: 2.6rem;
}
[data-testid="stDownloadButton"] button:hover {
    background: #eaf5f5;
    border-color: #086f7a;
    color: #075d66;
}

@media (max-width: 760px) {
    .stApp .block-container {
        padding-top: 5rem !important;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .geo-kicker {
        font-size: .68rem;
        letter-spacing: .075em;
    }
    [data-testid="stMetric"] {
        padding: .85rem 1rem;
    }
    [data-testid="stMetricLabel"] {
        min-height: 0;
        margin-bottom: .35rem;
    }
}
@media (prefers-reduced-motion: reduce) {
    .stApp { scroll-behavior: auto; }
}
</style>
"""


def apply_design():
    """Appliquer les styles sans modifier la navigation ni les données."""
    st.markdown(DESIGN_CSS, unsafe_allow_html=True)
