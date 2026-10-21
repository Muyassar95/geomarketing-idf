"""Carte Plotly locale avec remontée des clics commune/IRIS vers Streamlit."""
from pathlib import Path
import hashlib
import streamlit.components.v1 as components
from app.core import legend_items

FRONTEND = Path(__file__).resolve().parent / 'territory_component'

def verifier_frontend(directory=FRONTEND):
    """Signaler les ressources absentes avant de monter le composant navigateur."""
    directory = Path(directory)
    for name in ['index.html', 'plotly.min.js', 'world_110m.json']:
        path = directory / name
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(
                f'Carte : ressource absente ou vide : {path}. '
                'Publier tous les fichiers du dossier app/territory_component dans la branche déployée.'
            )
        with path.open('rb') as stream:
            if stream.read(128).startswith(b'version https://git-lfs.github.com/spec/v1'):
                raise ValueError(f'Carte : {path} est un pointeur Git LFS ; publier son contenu réel.')
    return directory

verifier_frontend()
# Une nouvelle page HTML reçoit une nouvelle URL de composant, pour écarter
# les anciennes ressources conservées dans le navigateur entre déploiements.
FRONTEND_VERSION = hashlib.sha256((FRONTEND / 'index.html').read_bytes()).hexdigest()[:12]
_component=components.declare_component(
    'territoire_idf_' + FRONTEND_VERSION,path=str(FRONTEND)
)

def territory_map(fig,bundle,assets,key='carte_territoire'):
    return _component(figure=fig.to_json(),legend=legend_items(fig,bundle,assets),key=key,default=None)
