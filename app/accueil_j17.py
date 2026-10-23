"""Enrichissements J17 de l'accueil communal, indépendants des modules J15b."""
from pathlib import Path
import hashlib
import html
import json
import os

import pandas as pd
import streamlit as st


def _sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def _csv(p):
    return pd.read_csv(p,sep=';',encoding='utf-8-sig',dtype='string',keep_default_na=False)


@st.cache_data(show_spinner=False)
def _charger(directory,signature,base_signature):
    d=Path(directory);m=json.loads((d/'manifest.json').read_text(encoding='utf-8-sig'))
    if m.get('schema_version')!=1 or m.get('etape')!='J17_ATTRACTIVITE_ETUDES':
        raise ValueError('Manifeste J17 non reconnu.')
    if m.get('base_manifest_sha256')!=base_signature:
        raise ValueError('Les exports J17 utilisent une autre base J15a.')
    names=[]
    for e in m['fichiers']:
        n=e['nom']
        if Path(n).name!=n or '/' in n or '\\' in n:
            raise ValueError('Chemin J17 invalide.')
        if not (d/n).is_file() or _sha(d/n)!=e['sha256']:
            raise ValueError('Export J17 absent ou différent du manifeste : '+n)
        names.append(n)
    if len(names)!=len(set(names)):
        raise ValueError('Fichiers J17 dupliqués.')
    e=_csv(d/'population_etudes_communes_j17.csv')
    n=_csv(d/'nomenclature_types_j17.csv')
    if not e['CODGEO'].is_unique:
        raise ValueError('Plusieurs lignes d’études pour une commune.')
    s=_csv(d/'superieur_communes_j17.csv') if 'superieur_communes_j17.csv' in names else None
    return m,e,n,s


@st.cache_data(show_spinner=False)
def _commune_parquet(path,signature,code,colonne='CODGEO'):
    return pd.read_parquet(path,filters=[(colonne,'==',str(code))])


def _nombre(v):
    try:
        x=float(str(v).replace(' ','').replace(',','.'))
        return x if pd.notna(x) and abs(x)!=float('inf') else None
    except (ValueError,TypeError):
        return None


def _fmt(v):
    x=_nombre(v)
    return 'Non disponible' if x is None else f'{x:,.0f}'.replace(',',' ')


def afficher_accueil_j17(racine,code,dossier_base,bundle):
    root=Path(racine)
    force=os.environ.get('GEOMARKETING_APP_J17')
    candidats=[Path(force)] if force else [Path(dossier_base).parent/'j17',root/'data/app/j17',root/'app/data/app/j17']
    d=next((p for p in candidats if (p/'manifest.json').is_file()),None)
    if d is None:
        st.info('Les indicateurs sur les études, commerces et pôles sont en cours de préparation pour cette version.')
        return
    try:
        signature=_sha(d/'manifest.json')
        m,etudes,nomenclature,superieur=_charger(str(d),signature,_sha(Path(dossier_base)/'manifest.json'))
    except (OSError,ValueError,KeyError) as e:
        st.warning('Les enrichissements du territoire nécessitent une vérification avant leur affichage.')
        with st.expander('Détail pour la préparation des données'):
            st.code(str(e))
        return
    selection=etudes.loc[etudes['CODGEO'].eq(str(code))]
    r=selection.iloc[0] if not selection.empty else pd.Series(dtype='object')
    st.markdown('#### Personnes qui étudient dans la commune')
    extra=superieur is not None
    cards=st.columns(4 if extra else 3)
    cards[0].metric('Personnes étudiant sur place · 2 ans ou plus',_fmt(r.get('SCOLARISES_LIEU_ETUDES_2P')),
        help='Personnes inscrites dans un établissement d’enseignement dont le lieu d’études déclaré se situe dans la commune ; effectifs estimés du recensement.')
    cards[1].metric('18-24 ans scolarisés sur place',_fmt(r.get('SCOLARISES_18_24_LIEU_ETUDES')),
        help='Classe d’âge de 18 à 24 ans ; elle ne correspond pas uniquement aux étudiants du supérieur.')
    cards[2].metric('Venant étudier depuis une autre commune',_fmt(r.get('SCOLARISES_ENTRANTS_2P')))
    annee=str(r.get('ANNEE_RP','')).replace('.0','')
    st.caption(f'Insee — RP {annee or "millésime à préciser"} · Personnes scolarisées de 2 ans ou plus, tous niveaux d’enseignement. Effectifs pondérés ; présence quotidienne et fréquentation commerciale à étudier séparément.')
    if r.get('STATUT_ETUDES')!='SOURCE_CHARGEE':
        st.caption('Les effectifs d’études sont indisponibles lorsque la source n’est pas chargée ou que le périmètre n’est pas compatible.')
    if extra:
        sr=superieur.loc[superieur['CODGEO'].eq(str(code))]
        sr=sr.iloc[0] if not sr.empty else pd.Series(dtype='object')
        cards[3].metric('Inscrits de l’enseignement supérieur',_fmt(sr.get('NB_INSCRITS_SUPERIEUR')))
        st.caption('Supérieur : '+str(sr.get('ANNEE_UNIVERSITAIRE','année non renseignée'))+' · '+str(sr.get('CHAMP','champ non renseigné'))+' · Source : '+str(sr.get('SOURCE','non renseignée'))+'. Indicateur distinct des effectifs RP.')
    with st.expander('Comprendre les effectifs liés aux études'):
        st.write('Les personnes étudiant sur place regroupent celles qui résident et étudient dans la commune et celles qui viennent d’une autre commune. Les personnes scolarisées résidentes peuvent étudier ailleurs.')
        st.dataframe(pd.DataFrame([
            {'Indicateur':'Scolarisés résidant dans la commune','Personnes estimées':_nombre(r.get('SCOLARISES_RESIDENTS_2P'))},
            {'Indicateur':'Résidant et étudiant dans la commune','Personnes estimées':_nombre(r.get('SCOLARISES_INTERNES_2P'))},
            {'Indicateur':'Venant d’une autre commune','Personnes estimées':_nombre(r.get('SCOLARISES_ENTRANTS_2P'))},
        ]),hide_index=True,width='stretch')
        st.write('Les chiffres restent à la maille communale. Leur addition avec la population résidente, les salariés ou les autres sources ne donne pas un nombre de clients uniques.')
    try:
        comptages=_commune_parquet(str(d/'comptages_communes_j17.parquet'),signature,str(code),'CODE')
        points=_commune_parquet(str(d/'points_j17.parquet'),signature,str(code))
    except (OSError,ValueError,ImportError) as e:
        st.warning('Les observations de commerces ne sont pas disponibles dans cette version des exports.')
        return
    def compte(types):
        return int(comptages.loc[comptages['TYPEQU'].isin(types),'NB_OBSERVATIONS'].sum())
    st.markdown('#### Commerces, services et équipements recensés')
    a,b,c,e=st.columns(4)
    a.metric('Boulangeries-pâtisseries · BPE',compte(['B207']))
    b.metric('Hypermarchés, grands magasins et supermarchés · BPE',compte(['B104','B105']))
    c.metric('Coiffure · BPE',compte(['A501']))
    if 'CNC' in m['sources_actives']:
        e.metric('Cinémas recensés · CNC',int(points['SOURCE'].eq('CNC').sum()))
        st.caption('Cinémas : décompte du complément CNC chargé, consultable séparément des observations BPE.')
    else:
        e.metric('Cinémas recensés · BPE',compte(['F303']))
    st.caption('BPE : observations d’équipements dans le fichier chargé, affectées au territoire. Le champ coiffure comprend aussi des activités à domicile ; la grande distribution inclut les catégories officielles regroupées.')
    q=m.get('qualite_bpe',{})
    if not q.get('couverture_declaree_complete') or q.get('nb_sans_commune',0):
        st.caption('La couverture du fichier et les observations sans affectation restent à contrôler : un décompte nul décrit le fichier exploité et ne démontre pas l’absence d’une offre sur le terrain.')
    with st.expander('Explorer tous les types de commerces et d’équipements'):
        domaines=nomenclature[['DOMAINE','DOMAINE_LIBELLE']].drop_duplicates().sort_values('DOMAINE_LIBELLE')
        domaine=st.selectbox('Famille d’équipements',domaines['DOMAINE'].tolist(),
            format_func=lambda x:domaines.set_index('DOMAINE').at[x,'DOMAINE_LIBELLE'],
            index=domaines['DOMAINE'].tolist().index('B') if 'B' in domaines['DOMAINE'].tolist() else 0,key='j17_domaine')
        cadre=nomenclature.loc[nomenclature['DOMAINE'].eq(domaine),['TYPEQU','LIBELLE_TYPE']].merge(
            comptages[['TYPEQU','NB_OBSERVATIONS','PART_DANS_DOMAINE_PCT','DENSITE_10000_HAB']],on='TYPEQU',how='left',validate='one_to_one')
        # Zéro = aucune observation dans le fichier chargé pour cette catégorie.
        cadre['NB_OBSERVATIONS']=cadre['NB_OBSERVATIONS'].fillna(0).astype(int)
        total=int(cadre['NB_OBSERVATIONS'].sum())
        if total:
            cadre['PART_DANS_DOMAINE_PCT']=cadre['NB_OBSERVATIONS']/total*100
        st.dataframe(cadre.drop(columns='TYPEQU').rename(columns={'LIBELLE_TYPE':'Type d’équipement',
            'NB_OBSERVATIONS':'Observations BPE','PART_DANS_DOMAINE_PCT':'Part dans cette famille (%)',
            'DENSITE_10000_HAB':'Observations pour 10 000 habitants'}),hide_index=True,width='stretch')
        st.caption('La part compare les types du même domaine BPE. Les cinémas CNC et les pôles ajoutés ne sont pas inclus dans ce dénominateur.')
        st.download_button('Télécharger les observations de cette famille',cadre.to_csv(index=False,sep=';').encode('utf-8-sig'),
            file_name='offre_'+str(code)+'_'+domaine+'.csv',mime='text/csv',key='j17_export_types')
    with st.expander('Pôles documentés et sites d’attractivité potentielle'):
        noms=points['LIBELLE_TYPE'].fillna('').str.lower()
        potentiel=points['SOURCE'].eq('POLES')|points['TYPEQU'].isin(['B104','B105','F303'])|noms.str.contains('universit|enseignement supérieur|grande école',regex=True)
        poles=points.loc[potentiel,['NOM','LIBELLE_TYPE','PRODUCTEUR','URL_SOURCE','ANNEE_SOURCE']].copy()
        st.dataframe(poles.rename(columns={'NOM':'Site','LIBELLE_TYPE':'Type de site','PRODUCTEUR':'Source','URL_SOURCE':'Lien source','ANNEE_SOURCE':'Année'}),hide_index=True,width='stretch')
        st.caption('Les catégories BPE permettent un premier repérage de sites potentiels. Les centres commerciaux, campus et autres pôles ajoutés sont documentés dans un registre dédié. Leur force d’attraction et leur fréquentation restent à mesurer.')
    with st.expander('Carte des commerces, cinémas et pôles documentés'):
        types=points[['SOURCE','TYPEQU','LIBELLE_TYPE']].drop_duplicates().copy()
        types['CLE']=types['SOURCE']+'::'+types['TYPEQU']
        labels=types.set_index('CLE').apply(lambda x:x['LIBELLE_TYPE']+' — '+x['SOURCE'],axis=1).to_dict()
        options=types['CLE'].tolist()
        default=[x for x in ['BPE::B207','BPE::A501','CNC::F303' if 'CNC' in m['sources_actives'] else 'BPE::F303'] if x in options]
        choisis=st.multiselect('Types à représenter',options,default=default,format_func=lambda x:labels[x],key='j17_types_carte')
        voir=st.checkbox('Afficher cette carte',False,key='j17_voir_carte')
        if voir:
            from app.core import build_territory_map,territory_event
            from app.territory_map import territory_map
            import plotly.graph_objects as go
            keys=points['SOURCE']+'::'+points['TYPEQU']
            local=points.loc[keys.isin(choisis)&points['LONGITUDE'].notna()&points['LATITUDE'].notna()].copy()
            disponibles=len(local);local=local.head(5000)
            fig,_=build_territory_map(bundle,str(code),show_restaurants=False,show_commune_outline=True)
            for (source,typ),part in local.groupby(['SOURCE','TYPEQU']):
                titres=part['NOM'].fillna('').astype(str)
                titres=titres.where(titres.str.strip().ne(''),part['LIBELLE_TYPE']+' — nom non renseigné')
                texte=[html.escape(str(n))+'<br>'+html.escape(str(t))+'<br>Source : '+html.escape(source) for n,t in zip(titres,part['LIBELLE_TYPE'])]
                fig.add_trace(go.Scattergeo(lon=part['LONGITUDE'],lat=part['LATITUDE'],mode='markers',
                    marker={'size':8,'opacity':.8},name=labels[source+'::'+typ],text=texte,
                    hovertemplate='%{text}<extra></extra>',meta={'ROLE':'EQUIPEMENT_J17'}))
            event=territory_map(fig,bundle,root/'app/assets',key='carte_attractivite_j17')
            action=territory_event(event,bundle)
            if action and action['event_id']!=st.session_state.get('_last_j17_event'):
                st.session_state['_last_j17_event']=action['event_id'];st.session_state['_territoire_action']=action;st.rerun()
            st.caption(f'{len(local)} points affichés sur {disponibles} correspondant aux filtres. Le plafond de 5 000 points concerne uniquement cette carte. Les noms apparaissent au survol.')
        st.caption('Les observations cinéma BPE et CNC restent des couches distinctes. Sélectionner une source pour éviter leur superposition. Les pôles indiquent des sites documentés ; leur localisation ne mesure pas leur fréquentation.')
