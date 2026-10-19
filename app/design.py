"""Présentation commune, sans connexion LLM ni clé API."""
import streamlit as st


def apply_design():
    st.markdown('''<style>
    .stApp {background:#f5f8fa;color:#132b3a;}
    .block-container {max-width:1450px;padding-top:2.2rem;padding-bottom:3rem;}
    h1,h2,h3 {color:#132b3a;letter-spacing:-.025em;}
    [data-testid="stSidebar"] {background:#edf3f5;border-right:1px solid #d8e4e9;}
    [data-testid="stMetric"] {background:white;border:1px solid #dce7eb;border-radius:12px;padding:16px;}
    [data-testid="stMetricValue"] {color:#087f8c;}
    [data-testid="stMetricLabel"] {color:#132b3a;}
    [data-testid="stDownloadButton"] button {border-radius:9px;border-color:#087f8c;color:#086f7a;}
    .geo-kicker {font-size:.77rem;letter-spacing:.17em;color:#087f8c;font-weight:700;margin-bottom:.6rem;}
    </style>''',unsafe_allow_html=True)
