"""Lancer depuis la racine : python -m streamlit run app/streamlit_app.py"""
import os
for variable in ['OMP_NUM_THREADS','NUMEXPR_NUM_THREADS','MKL_NUM_THREADS']:os.environ[variable]='1'
from pathlib import Path
import sys,hashlib
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.express as px
from app.core import (load_bundle,fmt,client_table,fiche,MODES,LABELS,
                      build_territory_map,local_network,territory_event)
from app.territory_map import territory_map
from app.reports import generate_report
from app.design import apply_design
from app.explorer import show_explorer

st.set_page_config(page_title='Diagnostic territorial | Île-de-France',page_icon='📍',layout='wide')
apply_design()
st.markdown('<div class="geo-kicker">DONNÉES · TERRITOIRES · IMPLANTATION</div>',unsafe_allow_html=True)
st.title('Diagnostic territorial en Île-de-France')
st.write('Explorer la population, la restauration et les transports pour préparer une étude de marché et d’implantation.')
DATA = Path(
    os.environ.get(
        "GEOMARKETING_APP_DATA",
        str(ROOT / "data/app/j15"),
    )
)

st.warning("DIAGNOSTIC J15 — chemin des données")

manifeste = DATA / "manifest.json"

st.json({
    "script_execute": str(Path(__file__).resolve()),
    "racine_calculee": str(ROOT),
    "variable_GEOMARKETING_APP_DATA": os.environ.get(
        "GEOMARKETING_APP_DATA"
    ),
    "dossier_utilise": str(DATA.resolve()),
    "dossier_existe": DATA.is_dir(),
    "manifeste_recherche": str(manifeste.resolve()),
    "manifeste_existe": manifeste.is_file(),
    "fichiers_dans_ce_dossier": (
        sorted(f.name for f in DATA.iterdir())
        if DATA.is_dir()
        else []
    ),
})

FICHIER_MANIFESTE = DATA / "manifest.json"

if not FICHIER_MANIFESTE.is_file():
    st.error("Le manifeste des données J15a est introuvable.")

    st.write("Chemin recherché :")
    st.code(str(FICHIER_MANIFESTE))

    st.write(
        "Publier les exports générés par le notebook J15a "
        "dans data/app/j15/ du dépôt GitHub."
    )
    st.stop()
    st.stop()
@st.cache_data(show_spinner='Chargement des indicateurs…')
def charger(directory,signature):return load_bundle(directory)
try:
    signature=hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest()
    data=charger(str(DATA),signature)
except (ValueError,OSError,KeyError) as e:
    st.error('Les exports nécessitent une vérification : '+str(e));st.stop()
meta=data['manifest'];communes=data['profil_communes'];iris=data['profil_iris']
st.caption(f"Population : RP {meta['annee_rp']} · Géographie IRIS : {meta['geographie_iris']} · Diagnostic descriptif")

# Appliquer les clics avant de créer les widgets liés à leur sélection.
pending=st.session_state.pop('_territoire_action',None)
if pending:
    st.session_state['commune']=pending['commune']
    st.session_state['iris']=pending['iris']
    if st.session_state.get('departement','Tous') not in ['Tous',pending['commune'][:2]]:
        st.session_state['departement']=pending['commune'][:2]
    st.session_state['niveau_carte']='Commune et IRIS'
    if pending.get('detail_niveau'):st.session_state['detail_niveau']=pending['detail_niveau']
    if pending['iris'] and st.session_state.get('vue')!='Indicateurs détaillés':st.session_state['vue']='IRIS'

def changer_commune():
    st.session_state['iris']=''
    st.session_state['niveau_carte']='Commune et IRIS'

def changer_departement():
    st.session_state['iris']=''
    st.session_state['niveau_carte']='Île-de-France'

def changer_iris():
    st.session_state['niveau_carte']='Commune et IRIS'
    if st.session_state.get('iris') and st.session_state.get('vue') not in ['Transports','Indicateurs détaillés']:
        st.session_state['vue']='IRIS'

def vue_regionale():
    st.session_state['niveau_carte']='Île-de-France'
    st.session_state['iris']=''
    st.session_state['vue']='Communes'
    st.session_state['departement']='Tous'

def vue_commune():
    st.session_state['niveau_carte']='Commune et IRIS'
    st.session_state['iris']=''

st.sidebar.header('Territoire étudié')
show_outline=st.sidebar.checkbox('Afficher les contours communaux',True,key='contours_communes')
deps=['Tous']+sorted(communes['CODGEO'].str[:2].unique())
dep=st.sidebar.selectbox('Département',deps,key='departement',on_change=changer_departement)
available=communes if dep=='Tous' else communes.loc[communes['CODGEO'].str[:2].eq(dep)]
options=available['CODGEO'].tolist();names=available.set_index('CODGEO')['NOM_COMMUNE'].to_dict()
index=options.index('95127') if '95127' in options else 0
if st.session_state.get('commune') not in options:
    st.session_state['commune']=options[index];st.session_state['iris']=''
code=st.sidebar.selectbox('Commune',options,index=options.index(st.session_state['commune']),format_func=lambda c:names.get(c,c)+' ('+c+')',key='commune',on_change=changer_commune)
local=iris.loc[iris['CODGEO'].eq(code)].copy()
iris_options=['']+local['IRIS'].tolist();iris_names=local.set_index('IRIS')['NOM_IRIS'].to_dict()
if st.session_state.get('iris','') not in iris_options:st.session_state['iris']=''
ident=st.sidebar.selectbox('IRIS',iris_options,index=iris_options.index(st.session_state.get('iris','')),format_func=lambda x:'Tous les IRIS de la commune' if not x else str(iris_names.get(x,x))+' ('+x+')',key='iris',on_change=changer_iris)
row=communes.set_index('CODGEO').loc[code]
view=st.radio('Explorer',['Communes','IRIS','Indicateurs détaillés','Transports','Sources et méthode'],horizontal=True,key='vue')
st.sidebar.caption('Cliquer sur une commune pour afficher ses IRIS, puis sur un IRIS pour consulter sa fiche. Les flux de travail restent communaux.')

def afficher_carte(regional=False,transports=False):
    navigation=st.columns(2)
    navigation[0].button('Vue Île-de-France',on_click=vue_regionale,key='vue_regionale')
    navigation[1].button('Voir toute la commune',on_click=vue_commune,key='vue_commune')
    table=communes if regional else local
    indicators=[c for c in ['POPULATION','RESTAURANTS','RAPIDES','DENSITE_RESTAURANTS','PART_1529_PCT','MEDIANE_UC','PAUVRETE_PCT'] if c in table]
    if st.session_state.get('indicateur_carte','POPULATION') not in indicators:
        st.session_state['indicateur_carte']='POPULATION'
    indicator=st.selectbox('Indicateur de la carte',indicators,format_func=lambda x:LABELS[x],key='indicateur_carte')
    modes=[];chosen=[]
    if transports:
        modes=st.multiselect('Modes à afficher',list(MODES),default=list(MODES),format_func=lambda m:MODES[m],key='modes')
        if 'TRAM' in modes and not data['lignes']['MODE'].eq('TRAM').any():
            st.info('Le tramway est activé dans l’application, mais les exports ne contiennent aucune ligne TRAM. Appliquer le correctif J14, puis régénérer les exports J15a.')
        catalog,_=local_network(data,code,ident or None)
        catalog=catalog.loc[catalog['MODE'].isin(modes)]
        ls=catalog['ID_LINE'].tolist();labels=catalog.set_index('ID_LINE')['LIBELLE_LIGNE'].to_dict()
        context=code+'_'+ident+'_'+','.join(modes)
        if st.session_state.get('_network_context')!=context:
            st.session_state['lignes']=ls;st.session_state['_network_context']=context
        chosen=st.multiselect('Lignes à afficher',ls,format_func=lambda x:labels[x],key='lignes')
    restos=st.checkbox('Afficher les restaurants',True,key='restaurants') if not regional else False
    fig,counts=build_territory_map(data,code,ident or None,regional=regional,department=dep,
        indicator=indicator,modes=modes,line_ids=chosen,show_restaurants=restos,show_commune_outline=show_outline)
    event=territory_map(fig,data,ROOT/'app/assets')
    action=territory_event(event,data)
    if action and action['event_id']!=st.session_state.get('_last_territory_event'):
        st.session_state['_last_territory_event']=action['event_id']
        st.session_state['_territoire_action']=action
        st.rerun()
    st.caption('Gris : indicateur indisponible. Les contours sont simplifiés pour l’affichage ; les indicateurs reprennent les calculs J14.')
    if not regional:
        st.caption(f"Restaurants affichés : {counts['restaurants_affiches']} / {counts['restaurants_disponibles']} · Arrêts affichés : {counts['arrets_affiches']} / {counts['arrets_disponibles']}")
    if transports:
        st.caption('Les lignes et arrêts sont sélectionnés dans la fenêtre cartographique. Les filtres ne modifient pas les indicateurs. Les tracés ne mesurent ni fréquence ni fréquentation.')
        table=catalog[['LIBELLE_LIGNE','MODE','STATUT_GEOMETRIQUE']].copy()
        table['MODE']=table['MODE'].map(MODES)
        table['STATUT_GEOMETRIQUE']=table['STATUT_GEOMETRIQUE'].map({'ARRETS_ET_TRACES':'Arrêts et tracés disponibles',
            'ARRETS_SANS_TRACE':'Arrêts disponibles, tracé absent','TRACE_SANS_ARRET_CORPUS':'Tracé disponible, aucun arrêt dans le corpus',
            'AUCUN_OBJET_CORPUS':'Aucun objet dans le corpus'})
        st.dataframe(table.rename(columns={'LIBELLE_LIGNE':'Ligne','MODE':'Mode','STATUT_GEOMETRIQUE':'Disponibilité arrêts/tracés'}),hide_index=True,width='stretch')

if view not in ['Sources et méthode','Indicateurs détaillés']:
    st.subheader('Carte des communes et IRIS')
    afficher_carte(
        regional=view=='Communes' and st.session_state.get('niveau_carte','Île-de-France')=='Île-de-France',
        transports=view=='Transports',
    )

if view=='Communes':
    st.subheader(row['NOM_COMMUNE'])
    a,b,c,d=st.columns(4)
    a.metric('Population',fmt(row['POPULATION']))
    b.metric('Restaurants observés',fmt(row['RESTAURANTS']))
    c.metric('Restaurants / 10 000 hab.',fmt(row['DENSITE_RESTAURANTS'],decimals=1))
    d.metric('Actifs venant travailler',fmt(row.get('MOBPRO_ENTRANTS')))
    st.caption('Les actifs venant travailler sont issus du recensement ; ce ne sont pas des passages quotidiens ni des voyageurs attribués aux lignes.')
    st.write('Comparer les communes du département sélectionné')
    cols=['NOM_COMMUNE','POPULATION','RESTAURANTS','RAPIDES','DENSITE_RESTAURANTS','MOBPRO_ENTRANTS']
    st.dataframe(client_table(available,cols),hide_index=True,width='stretch')
    chart=available.loc[available['POPULATION'].gt(0)&available['RESTAURANTS'].notna()].copy()
    if not chart.empty:
        fig=px.scatter(chart,x='POPULATION',y='RESTAURANTS',hover_name='NOM_COMMUNE',
            labels={'POPULATION':'Population','RESTAURANTS':'Restaurants observés'},title='Population et offre de restauration observée')
        st.plotly_chart(fig,use_container_width=True,config={'displaylogo':False})
    st.caption('Une faible densité ne démontre pas un besoin non satisfait. Une forte densité ne démontre pas une saturation.')
    pdf=generate_report(data,code)
    st.download_button('Télécharger la fiche communale (PDF)',pdf,file_name='fiche_commune_'+code+'.pdf',mime='application/pdf')
    st.download_button('Télécharger le tableau comparatif',client_table(available,cols).to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='comparaison_communes.csv',mime='text/csv')
elif view=='IRIS':
    st.subheader('Population et marché à l’échelle des IRIS')
    cols=['NOM_IRIS','TYP_IRIS','POPULATION','PART_1529_PCT','RESTAURANTS','RAPIDES','DENSITE_RESTAURANTS','MEDIANE_UC','PAUVRETE_PCT']
    st.dataframe(client_table(local,cols),hide_index=True,width='stretch')
    if not ident:
        st.info('Cliquer sur un IRIS de la carte ou le choisir dans la liste pour afficher sa fiche.')
        st.stop()
    r=local.set_index('IRIS').loc[ident]
    a,b,c,d=st.columns(4)
    a.metric('Population',fmt(r['POPULATION']));b.metric('Restaurants observés',fmt(r['RESTAURANTS']))
    c.metric('Niveau de vie médian / UC',fmt(r['MEDIANE_UC'],' €'));d.metric('Taux de pauvreté',fmt(r['PAUVRETE_PCT'],' %',1))
    st.caption('Le niveau de vie médian est annuel et calculé par unité de consommation. Les valeurs absentes restent indisponibles.')
    statuts={'DISPONIBLE':'Indicateurs disponibles','PARTIEL':'Indicateurs partiellement disponibles',
        'VALEURS_NON_DIFFUSEES_OU_MANQUANTES':'Valeurs non diffusées ou manquantes',
        'GEOGRAPHIE_NON_HARMONISEE':'Géographie fiscale à harmoniser',
        'REVENUS_NON_CHARGES':'Source fiscale non chargée','IRIS_SOURCE_NON_DIFFUSE':'IRIS absent de la diffusion fiscale',
        'Source fiscale indisponible':'Source fiscale indisponible'}
    st.write('Revenus : '+statuts.get(str(r['STATUT_REVENUS']),'Statut fiscal à vérifier')+' · Année : '+fmt(r['ANNEE_REVENUS']))
    transport=pd.DataFrame([{'Mode':nom,'Distance directe du point IRIS (m)':r.get('DIST_'+m+'_M',float('nan')),
        'Lignes proches du point IRIS':r.get('LIGNES_'+m,float('nan')),'Surface proche des arrêts (%)':r.get('SURFACE_'+m+'_PCT',float('nan')),
        'Rayon de travail (m)':meta['rayons_metres'].get(m,float('nan'))} for m,nom in MODES.items()])
    st.dataframe(transport,hide_index=True,width='stretch')
    if 'TRAM' not in meta['rayons_metres']:
        st.caption('Les indicateurs tramway ne sont pas encore calculés dans ces exports. Recalculer J14 puis J15a avec le mode TRAM.')
    st.caption('Le point IRIS est une référence géométrique intérieure. La distance directe ne mesure pas le temps de marche ; la surface proche ne mesure pas la population desservie.')
    st.download_button('Télécharger la fiche IRIS (PDF)',generate_report(data,code,ident),file_name='fiche_iris_'+ident+'.pdf',mime='application/pdf')
elif view=='Indicateurs détaillés':
    show_explorer(data,DATA,Path(os.environ.get('GEOMARKETING_APP_DETAIL',ROOT/'data/app/j15b')),code,ident or None,ROOT/'app/assets',outline=show_outline)
elif view=='Transports':
    st.subheader('Lignes, arrêts et restauration — '+row['NOM_COMMUNE'])
else:
    st.subheader('Sources, dates et méthode')
    st.dataframe(data['sources'].rename(columns={'source':'Source','annee_donnees':'Année des données','annee_geographie':'Géographie','date_telechargement':'Téléchargement','url':'Lien'}),hide_index=True,width='stretch')
    st.write('Les dates non renseignées restent à documenter. Le recensement, les revenus, la BPE et le réseau peuvent avoir des millésimes différents.')
    if not meta['couverture_arrets_confirmee_idf']:
        st.caption('La couverture du fichier d’arrêts reste à vérifier : la proximité est calculée parmi les observations chargées.')
    st.markdown('''- Population : habitants du recensement, à la maille publiée.
- Restauration : observations des fichiers préparés ; une observation n’est pas un chiffre d’affaires.
- Revenus : indicateurs fiscaux IRIS ; les médianes ne sont pas additionnées.
- Mobilités : contexte communal du recensement, conservé à cette maille.
- Transports : arrêts et lignes du corpus ; unités d’arrêt différentes selon les modes, rayons directs et part de surface.
- Fréquence, horaires, accès piétons et fréquentation : à compléter dans la suite.''')
    st.download_button('Télécharger les sources',data['sources'].to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='sources_application.csv',mime='text/csv')
