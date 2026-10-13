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
from app.core import load_bundle,fmt,client_table,fiche,build_map,map_html,MODES

st.set_page_config(page_title='Diagnostic territorial | Île-de-France',page_icon='📍',layout='wide')
st.title('Diagnostic territorial en Île-de-France')
st.write('Explorer la population, la restauration et les transports pour préparer une étude de marché et d’implantation.')
DATA=Path(os.environ.get('GEOMARKETING_APP_DATA',ROOT/'data/app/j15'))
if not (DATA/'manifest.json').is_file():
    st.info('Les données de l’application ne sont pas encore préparées. Exécuter le notebook J15a, puis relancer l’application.')
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
st.sidebar.header('Territoire étudié')
deps=['Tous']+sorted(communes['CODGEO'].str[:2].unique())
dep=st.sidebar.selectbox('Département',deps,key='departement')
available=communes if dep=='Tous' else communes.loc[communes['CODGEO'].str[:2].eq(dep)]
options=available['CODGEO'].tolist();names=available.set_index('CODGEO')['NOM_COMMUNE'].to_dict()
index=options.index('95127') if '95127' in options else 0
code=st.sidebar.selectbox('Commune',options,index=index,format_func=lambda c:names[c]+' ('+c+')',key='commune')
row=communes.set_index('CODGEO').loc[code]
view=st.radio('Explorer',['Communes','IRIS','Transports','Sources et méthode'],horizontal=True,key='vue')
st.sidebar.caption('Les flux de travail sont communaux. Les cartes détaillées portent sur le secteur pilote préparé.')

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
    text=fiche(row,meta)
    st.download_button('Télécharger la fiche descriptive',text.encode('utf-8'),file_name='fiche_commune_'+code+'.md',mime='text/markdown')
    st.download_button('Télécharger le tableau comparatif',client_table(available,cols).to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='comparaison_communes.csv',mime='text/csv')
elif view=='IRIS':
    local=iris.loc[iris['CODGEO'].eq(code)].copy()
    st.subheader('Population et marché à l’échelle des IRIS')
    opts=local['IRIS'].tolist();noms=local.set_index('IRIS')['NOM_IRIS'].to_dict()
    ident=st.selectbox('IRIS',opts,format_func=lambda x:str(noms[x])+' ('+x+')',key='iris')
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
    cols=['NOM_IRIS','TYP_IRIS','POPULATION','PART_1529_PCT','RESTAURANTS','RAPIDES','DENSITE_RESTAURANTS','MEDIANE_UC','PAUVRETE_PCT']
    st.dataframe(client_table(local,cols),hide_index=True,width='stretch')
    transport=pd.DataFrame([{'Mode':nom,'Distance directe du point IRIS (m)':r['DIST_'+m+'_M'],
        'Lignes proches du point IRIS':r['LIGNES_'+m],'Surface proche des arrêts (%)':r['SURFACE_'+m+'_PCT'],
        'Rayon de travail (m)':meta['rayons_metres'][m]} for m,nom in MODES.items()])
    st.dataframe(transport,hide_index=True,width='stretch')
    st.caption('Le point IRIS est une référence géométrique intérieure. La distance directe ne mesure pas le temps de marche ; la surface proche ne mesure pas la population desservie.')
    st.download_button('Télécharger la fiche IRIS',fiche(r,meta,True).encode('utf-8'),file_name='fiche_iris_'+ident+'.md',mime='text/markdown')
elif view=='Transports':
    st.subheader('Lignes, arrêts et restauration dans le secteur pilote')
    if code not in meta['codes_focus']:
        st.info('La carte locale couvre les communes du secteur pilote : '+', '.join(meta['noms_focus'])+'. Les indicateurs du territoire choisi restent dans les vues Communes et IRIS.')
    modes=st.multiselect('Modes à afficher',list(MODES),default=list(MODES),format_func=lambda m:MODES[m],key='modes')
    catalog=data['lignes'].loc[data['lignes']['MODE'].isin(modes)]
    ls=catalog['ID_LINE'].tolist();labels=catalog.set_index('ID_LINE')['LIBELLE_LIGNE'].to_dict()
    chosen=st.multiselect('Lignes à afficher',ls,default=ls,format_func=lambda x:labels[x],key='lignes')
    restos=st.checkbox('Afficher les restaurants',True,key='restaurants')
    fig,counts=build_map(data,modes,chosen,restos)
    components.html(map_html(fig,data,ROOT/'app/assets'),height=870,scrolling=True)
    st.caption(f"Arrêts affichés : {counts['arrets_affiches']} / {counts['arrets_disponibles']} · Restaurants affichés : {counts['restaurants_affiches']} / {counts['restaurants_disponibles']}")
    st.caption('La carte reprend la sélection locale de J14. Les filtres d’affichage ne modifient pas les indicateurs régionaux. Les tracés ne mesurent ni fréquence ni fréquentation.')
    table=catalog[['LIBELLE_LIGNE','MODE','STATUT_GEOMETRIQUE']].copy()
    table['MODE']=table['MODE'].map(MODES)
    table['STATUT_GEOMETRIQUE']=table['STATUT_GEOMETRIQUE'].map({'ARRETS_ET_TRACES':'Arrêts et tracés disponibles',
        'ARRETS_SANS_TRACE':'Arrêts disponibles, tracé absent','TRACE_SANS_ARRET_CORPUS':'Tracé disponible, aucun arrêt dans le corpus',
        'AUCUN_OBJET_CORPUS':'Aucun objet dans le corpus'})
    st.dataframe(table.rename(columns={'LIBELLE_LIGNE':'Ligne','MODE':'Mode','STATUT_GEOMETRIQUE':'Disponibilité arrêts/tracés'}),hide_index=True,width='stretch')
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
