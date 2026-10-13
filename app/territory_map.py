"""Carte Plotly locale avec remontée des clics commune/IRIS vers Streamlit."""
from pathlib import Path
import streamlit.components.v1 as components
from app.core import legend_items

_component=components.declare_component(
    'territoire_idf',path=str(Path(__file__).parent/'territory_component')
)

def territory_map(fig,bundle,assets,key='carte_territoire'):
    return _component(figure=fig.to_json(),legend=legend_items(fig,bundle,assets),key=key,default=None)
