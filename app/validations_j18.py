"""Présentation des volumes IDFM à leur maille publiée, distincts des départs GTFS."""
from pathlib import Path
import html
import pandas as pd
import streamlit as st

JOURS = {'JOHV':'Semaine, hors vacances','JOVS':'Semaine, vacances',
    'SAHV':'Samedi, hors vacances','SAVS':'Samedi, vacances','DIJFP':'Dimanche et jours assimilés'}


def intervalle(lo,hi,decimales=0):
    def f(x): return f'{float(x):,.{decimales}f}'.replace(',',' ').replace('.',',')
    if pd.isna(lo): return 'Non disponible'
    if pd.isna(hi): return 'Au moins '+f(lo)
    if abs(float(lo)-float(hi))<1e-9: return f(lo)
    return f(lo)+' à '+f(hi)


def afficher(root,bundle,dossier,signature,manifest,commune,iris=None):
    from app.transports_j18 import lire_parquet
    meta = manifest.get('validations',{})
    st.markdown('#### Validations observées — données IDFM')
    if not meta.get('actif'):
        st.info('Les validations ne sont pas chargées dans ce lot. Activer leur préparation dans le notebook J18, puis republier ses exports.')
        return
    d = Path(dossier)
    st.write('Ces données comptent les validations enregistrées. Elles ne donnent pas un nombre de voyageurs uniques ni le passage des piétons autour d’un commerce.')
    sources = [s for s in manifest['sources'] if s.get('type') in ['NB_FER','NB_SURFACE','PROFIL_FER','PROFIL_SURFACE']]
    st.caption('Périodes de validation : '+ ' · '.join(sorted({s.get('periode_debut','')+' au '+s.get('periode_fin','') for s in sources})))
    st.caption('GTFS affiché dans les autres onglets : '+manifest['date_service']+'. Les périodes restent distinctes ; aucun taux d’occupation des véhicules n’est calculé.')
    synth = lire_parquet(str(d/'validations_synthese.parquet'),signature)
    reseau = st.radio('Échelle publiée des validations',['FERRE','SURFACE'],horizontal=True,
        format_func=lambda x:'Gares et stations' if x=='FERRE' else 'Lignes du réseau de surface',key='j18_validations_reseau')
    choix = synth.loc[synth['RESEAU'].eq(reseau)].copy()
    if choix.empty:
        st.info('Cette source de validations n’a pas été chargée.'); return
    tout = st.checkbox('Explorer toutes les entités du fichier, au-delà du territoire sélectionné',False,key='j18_validations_tout')
    if reseau=='FERRE':
        st.caption('Rattachement au point de référence d’une gare/station. Les validations concernent l’ensemble de ce périmètre, pas la population de l’IRIS.')
        if not tout:
            choix = choix.loc[choix['IRIS'].eq(str(iris))] if iris else choix.loc[choix['CODGEO'].eq(str(commune))]
        if choix.empty:
            st.info('Aucune station de validation rattachée à ce territoire. Vérifier la correspondance géographique ou cocher l’exploration de toutes les entités. Une absence de rattachement n’est pas un volume nul.')
            return
    else:
        st.caption('Volume à l’échelle de la ligne administrative entière. Il n’est pas réparti entre ses arrêts, les communes ou les IRIS.')
        if not tout:
            liens = lire_parquet(str(d/'correspondance_surface_validations.parquet'),signature)
            lignes = pd.read_csv(d/'lignes_gtfs.csv',sep=';',dtype='string',keep_default_na=False,encoding='utf-8-sig')
            offre = lire_parquet(str(d/'offre_arrets.parquet'),signature,[('CODGEO','==',str(commune))])
            if iris: offre = offre.loc[offre['IRIS'].eq(str(iris))]
            ids = set(lignes.loc[lignes['route_id'].isin(offre['route_id']),'ID_LINE'])-{''}
            choix = choix.loc[choix['ID_ENTITE'].isin(liens.loc[liens['ID_LINE'].isin(ids),'ID_ENTITE'])]
            st.caption('Les lignes proposées sont reliées au réseau GTFS du territoire par une correspondance documentée. Leurs volumes restent ceux de toute la ligne, pour la période publiée.')
        if choix.empty:
            st.info('Aucune correspondance de ligne administrative disponible ici. Cocher l’exploration de toutes les entités pour consulter les volumes publiés.'); return
    labels = choix.set_index('ID_ENTITE')['NOM'].to_dict()
    key = 'j18_validation_entite_'+reseau+'_'+str(commune)+'_'+str(iris or '')
    selected = st.selectbox('Gare, station ou ligne à examiner',choix['ID_ENTITE'].tolist(),
        format_func=lambda x:str(labels.get(x,x))+' · '+x,key=key)
    r = choix.set_index('ID_ENTITE').loc[selected]
    a,b,c = st.columns(3)
    a.metric('Validations par jour renseigné',intervalle(r.get('MOYENNE_JOURS_PRESENTS_INF'),r.get('MOYENNE_JOURS_PRESENTS_SUP'),1),
        help='Moyenne sur les journées présentes dans le fichier ; les journées absentes ne sont pas remplacées par zéro.')
    b.metric('Validations cumulées renseignées',intervalle(r.get('TOTAL_INF'),r.get('TOTAL_SUP')))
    n,p = r.get('NB_JOURS_PRESENTS'),r.get('NB_JOURS_PERIODE')
    c.metric('Journées renseignées / période',('Non disponible' if pd.isna(n) else str(int(n))+' / '+str(int(p))))
    if r.get('NB_CELLULES_CENSUREES',0)>0 or r.get('NB_VALEURS_MANQUANTES',0)>0:
        st.caption('Des valeurs sont masquées ou manquantes : les nombres affichés sont des bornes, sans valeur médiane inventée. La règle de traitement des « 5 » numériques est documentée dans les sources du lot.')
    daily = lire_parquet(str(d/'validations_quotidiennes.parquet'),signature,
        [('RESEAU','==',reseau),('ID_ENTITE','==',selected)])
    profiles = lire_parquet(str(d/'profils_validations.parquet'),signature,
        [('RESEAU','==',reseau),('ID_ENTITE','==',selected)])
    import plotly.graph_objects as go
    if not daily.empty:
        t = daily.sort_values('JOUR')
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=t['JOUR'],y=t['VALIDATIONS_INF'],mode='lines+markers',
            line={'color':'#087f8c'},name='Valeur publiée ou borne basse',connectgaps=False))
        fig.add_trace(go.Scatter(x=t['JOUR'],y=t['VALIDATIONS_SUP'],mode='lines',
            line={'color':'#57a8b0'},fill='tonexty',fillcolor='rgba(8,127,140,.14)',
            name='Valeur publiée ou borne haute',connectgaps=False))
        fig.update_layout(title='Validations renseignées par journée d’exploitation',
            xaxis_title='Date IDFM',yaxis_title='Validations',legend={'orientation':'h'},margin={'t':55,'b':55})
        st.plotly_chart(fig,use_container_width=True,config={'displaylogo':False})
        st.caption('La documentation IDFM décrit une journée d’exploitation de 04 h à 03 h 59 le lendemain. Les dates absentes du fichier ne sont pas créées comme des journées à zéro.')
        st.download_button('Télécharger les validations quotidiennes de cette entité',daily.to_csv(index=False,sep=';').encode('utf-8-sig'),
            file_name='validations_'+selected.replace(':','_')+'.csv',mime='text/csv',key='j18_export_validations')
    if not profiles.empty:
        st.markdown('##### Répartition horaire publiée')
        cat = st.selectbox('Type de jour',sorted(profiles['CAT_JOUR'].unique()),format_func=lambda x:JOURS.get(x,x),key='j18_validations_type_jour')
        part = profiles.loc[profiles['CAT_JOUR'].eq(cat)].copy()
        part['SERIE'] = part['CLE_SOURCE']+' · '+part['PERIODE_DEBUT']+' au '+part['PERIODE_FIN']
        series = sorted(part['SERIE'].unique())
        serie = st.selectbox('Série publiée et période',series,key='j18_validations_serie') if len(series)>1 else series[0]
        part = part.loc[part['SERIE'].eq(serie)].sort_values('HEURE_SERVICE')
        f = go.Figure(go.Bar(x=part['TRANCHE'],y=part['PCT_VALIDATIONS'],marker_color='#087f8c'))
        f.update_layout(title='Part des validations selon l’heure — '+JOURS.get(cat,cat),
            yaxis_title='Part publiée (%)',xaxis_title='Tranche horaire',margin={'t':55,'b':70})
        st.plotly_chart(f,use_container_width=True,config={'displaylogo':False})
        somme = float(part['PCT_VALIDATIONS'].sum())
        st.caption(f'Série {serie} · Somme des parts disponibles : {somme:.2f} %. Les parts ne sont ni renormalisées ni multipliées par un volume journalier pour créer des observations horaires.')
        if abs(somme-100)>.5: st.warning('Ce profil est incomplet ou nécessite une vérification. Les tranches absentes restent indisponibles.')
    else: st.caption('Profil horaire non disponible pour cette entité.')
    if reseau=='FERRE' and pd.notna(r.get('LONGITUDE')) and pd.notna(r.get('LATITUDE')) and r.get('CODGEO') in bundle['_communes_geo']:
        voir = st.checkbox('Localiser cette gare ou station sur les contours détaillés',False,key='j18_carte_validations')
        if voir:
            from app.core import build_territory_map
            from app.territory_map import territory_map
            f,_ = build_territory_map(bundle,str(r['CODGEO']),show_restaurants=False,show_commune_outline=True)
            f.add_trace(go.Scattergeo(lon=[float(r['LONGITUDE'])],lat=[float(r['LATITUDE'])],mode='markers',
                marker={'size':12,'color':'#b45309'},text=[html.escape(str(r['NOM']))+'<br>Point de référence de la station'],
                hovertemplate='%{text}<extra></extra>',showlegend=False))
            territory_map(f,bundle,Path(root)/'app/assets',key='carte_validations_j18')
