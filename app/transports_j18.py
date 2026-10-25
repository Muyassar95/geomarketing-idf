"""Lecture légère des exports J18 et carte Plotly sans fond distant ni clé API."""
from pathlib import Path
import hashlib
import html
import json
import os

import pandas as pd
import streamlit as st

MODES = {'TOUS':'Tous les modes','METRO':'Métro','RER':'RER','TRANSILIEN':'Transilien',
         'TRAM':'Tramway','BUS':'Bus et trolleybus','TRAIN':'Train — réseau non distingué','AUTRE':'Autres modes'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


@st.cache_data(show_spinner=False,max_entries=3)
def charger(directory,signature,base_signature):
    d = Path(directory); m = json.loads((d/'manifest.json').read_text(encoding='utf-8-sig'))
    if m.get('schema_version')!=1 or m.get('etape')!='J18_GTFS_GEOMETRIES':
        raise ValueError('Manifeste J18 non reconnu.')
    if m.get('base_manifest_sha256')!=base_signature:
        raise ValueError('J18 a été préparé avec un autre manifeste J15a. Repréparer J18 avec le socle publié.')
    names = [r['nom'] for r in m['fichiers']]
    required = {'contours_iris.parquet','contours_communes.parquet','traces_gtfs.parquet','offre_commune.parquet',
        'offre_iris.parquet','offre_arrets.parquet','arrets_gtfs.parquet','lignes_gtfs.csv','creneaux.csv','qualite_traces.csv'}
    if m.get('validations',{}).get('actif'):
        required |= {'validations_quotidiennes.parquet','profils_validations.parquet',
            'validations_synthese.parquet','correspondance_surface_validations.parquet'}
    if len(names)!=len(set(names)) or required-set(names): raise ValueError('Liste de fichiers J18 incomplète/dupliquée.')
    for row in m['fichiers']:
        name = row['nom']
        if Path(name).name!=name or '/' in name or '\\' in name: raise ValueError('Chemin J18 invalide.')
        p = d/name
        if not p.is_file() or sha(p)!=row['sha256']: raise ValueError('Export J18 absent ou modifié : '+name)
    routes = pd.read_csv(d/'lignes_gtfs.csv',sep=';',dtype='string',keep_default_na=False,encoding='utf-8-sig')
    creneaux = pd.read_csv(d/'creneaux.csv',sep=';',dtype='string',encoding='utf-8-sig')
    qualite = pd.read_csv(d/'qualite_traces.csv',sep=';',dtype='string',keep_default_na=False,encoding='utf-8-sig')
    return m,routes,creneaux,qualite


@st.cache_data(show_spinner=False,max_entries=24)
def lire_parquet(path,signature,filters=None):
    return pd.read_parquet(path,filters=filters)


def activer_couches_j18(root,base_directory,bundle):
    root = Path(root); forced = os.environ.get('GEOMARKETING_APP_J18')
    choices = [Path(forced)] if forced else [Path(base_directory).parent/'j18',root/'data/app/j18',root/'app/data/app/j18']
    d = next((p for p in choices if (p/'manifest.json').is_file()),None)
    if d is None: return bundle
    try:
        signature = sha(d/'manifest.json')
        m,_,_,_ = charger(str(d),signature,sha(Path(base_directory)/'manifest.json'))
        if m['nb_iris']!=len(bundle['profil_iris']) or m['nb_communes']!=len(bundle['profil_communes']):
            raise ValueError('Couverture J18 différente de J15a.')
        for filename,key,expected in [('contours_iris.parquet','CODE',set(bundle['profil_iris']['IRIS'])),
                                      ('contours_communes.parquet','CODE',set(bundle['profil_communes']['CODGEO']))]:
            keys = pd.read_parquet(d/filename,columns=[key,'LOD'])
            for lod in ['LOCAL','REGIONAL']:
                s = keys.loc[keys['LOD'].eq(lod),key]
                if not s.is_unique or set(s)!=expected: raise ValueError(filename+' : codes manquants/dupliqués.')
        out = dict(bundle); out['_j18_directory'] = str(d); out['_j18_signature'] = signature
        out['_j18_base_signature'] = m['base_manifest_sha256']
        return out
    except (OSError,ValueError,KeyError,ImportError) as e:
        st.warning('Le complément GTFS nécessite une vérification ; les cartes de base restent disponibles.')
        with st.expander('Détail du contrôle J18'): st.code(str(e))
        return bundle


def enrichir_carte_j18(bundle,commune_code,regional=False):
    """Remplacer les géométries d'affichage à la demande, sans toucher aux profils."""
    d = bundle.get('_j18_directory')
    if not d or bundle.get('_j18_geometries_appliquees')==(str(commune_code),bool(regional)): return bundle
    d = Path(d); signature = bundle['_j18_signature']; out = dict(bundle)
    def features(table,old,key):
        result = dict(old)
        for r in table.to_dict('records'):
            if r['CODE'] not in old: raise ValueError('Contour J18 hors du socle : '+r['CODE'])
            f = dict(old[r['CODE']]); f['properties'] = dict(f['properties'])
            if key=='IRIS' and f['properties']['CODGEO']!=r['CODGEO']:
                raise ValueError('Commune de l’IRIS J18 incompatible.')
            f['geometry'] = json.loads(r['GEOJSON']); f.pop('bbox',None)
            result[r['CODE']] = f
        return result
    filtres = [('LOD','==','REGIONAL')] if regional else [('LOD','==','LOCAL'),('CODGEO','==',str(commune_code))]
    c = lire_parquet(str(d/'contours_communes.parquet'),signature,filtres)
    out['_communes_geo'] = features(c,bundle['_communes_geo'],'CODGEO')
    if not regional:
        i = lire_parquet(str(d/'contours_iris.parquet'),signature,filtres)
        if set(i['CODE'])!=set(bundle['_iris_par_commune'][str(commune_code)]): raise ValueError('IRIS locaux J18 incomplets.')
        out['_iris_geo'] = features(i,bundle['_iris_geo'],'IRIS')
    out['_j18_geometries_appliquees'] = (str(commune_code),bool(regional))
    return out


def fmt(v,decimals=0):
    return 'Non disponible' if pd.isna(v) else f'{float(v):,.{decimals}f}'.replace(',',' ').replace('.',',')


def afficher_transports_j18(root,base_directory,bundle,commune,iris=None):
    if not bundle.get('_j18_directory'):
        st.info('Préparer et publier les exports J18 pour consulter les horaires GTFS.')
        return
    d = Path(bundle['_j18_directory']); signature = bundle['_j18_signature']
    m,routes,creneaux,qualite = charger(str(d),signature,bundle['_j18_base_signature'])
    st.subheader('Horaires prévus et réseau de transport')
    st.caption('Journée de service : '+m['date_service']+' · Fuseau Europe/Paris · Source Île-de-France Mobilités')
    st.write('Choisissez un créneau pour examiner les départs proposés aux arrêts du territoire et leurs tracés disponibles.')
    a,b = st.columns(2)
    w = a.selectbox('Créneau de service',creneaux['CRENEAU'].tolist(),key='j18_creneau',
        format_func=lambda x:x+' · '+str(creneaux.set_index('CRENEAU').at[x,'DEBUT'])+'–'+str(creneaux.set_index('CRENEAU').at[x,'FIN']))
    mode = b.selectbox('Mode de transport',list(MODES),format_func=lambda x:MODES[x],key='j18_mode')
    niveau = 'iris' if iris else 'commune'; key = 'IRIS' if iris else 'CODGEO'; code = str(iris or commune)
    profil = lire_parquet(str(d/('offre_'+niveau+'.parquet')),signature,
        [(key,'==',code),('CRENEAU','==',w),('MODE','==',mode)])
    r = profil.iloc[0] if not profil.empty else pd.Series(dtype=float)
    a,b,c,e = st.columns(4)
    a.metric('Départs programmés aux arrêts',fmt(r.get('NB_DEPARTS_PROGRAMMES')),
        help='Une même course peut être comptée à plusieurs arrêts. Ne représente pas des voyageurs uniques.')
    b.metric('Arrêts proposant un départ',fmt(r.get('NB_ARRETS_AVEC_DEPART')),
        help='Points d’arrêt/quais GTFS distincts ; pas un nombre de gares regroupées.')
    c.metric('Lignes GTFS proposant un départ',fmt(r.get('NB_LIGNES_GTFS')))
    e.metric('Volume estimé en cadence',fmt(r.get('NB_DEPARTS_ESTIMES_CADENCE'),1),
        help='Services sans heures fixes (exact_times=0), exprimés en équivalents de départs. Distincts des départs programmés.')
    st.caption('Les créneaux se rapportent à la journée de service affichée : 25:00 signifie 01:00 le lendemain. Les créneaux peuvent se chevaucher et ne doivent pas être additionnés.')
    if m['qualite_horaires']['NB_HEURES_NON_RENSEIGNEES']:
        st.warning('Certains horaires intermédiaires sont absents du flux : les départs correspondants ne sont pas interpolés. Consulter le contrôle qualité.')
    tab_map,tab_table,tab_validations,tab_quality = st.tabs(['Carte du réseau et des territoires','Départs par arrêt','Validations observées IDFM','Qualité et méthode'])
    details = lire_parquet(str(d/'offre_arrets.parquet'),signature,[('CODGEO','==',str(commune)),('CRENEAU','==',w)])
    if iris: details = details.loc[details['IRIS'].eq(str(iris))]
    if mode!='TOUS': details = details.loc[details['MODE'].eq(mode)]
    stops = lire_parquet(str(d/'arrets_gtfs.parquet'),signature,[('CODGEO','==',str(commune))])
    with tab_map:
        local_ids = sorted(set(details['route_id']))
        labels = routes.set_index('route_id')['LIBELLE'].to_dict()
        # Le plafond concerne le rendu initial, jamais les comptages ni les exports.
        chosen = st.multiselect('Lignes à représenter',local_ids,default=local_ids[:30],
            format_func=lambda x:labels.get(x,x)+' · '+x,key='j18_lignes_'+str(commune)+'_'+str(iris or '')+'_'+w+'_'+mode)
        if len(local_ids)>30: st.caption('Les 30 premières lignes sont cochées initialement. Toutes restent sélectionnables ; les indicateurs portent sur l’ensemble du filtre.')
        a,b,c,e = st.columns(4)
        show_iris = a.checkbox('Afficher les IRIS',True,key='j18_polygones')
        show_outline = b.checkbox('Afficher la limite communale',True,key='j18_contour')
        show_stops = c.checkbox('Afficher les arrêts',True,key='j18_arrets')
        show_restaurants = e.checkbox('Afficher les restaurants BPE',False,key='j18_restaurants')
        fig,legend_bundle = construire_carte(bundle,d,signature,str(commune),iris,chosen,routes,
            stops,details,show_iris,show_outline,show_stops,show_restaurants)
        from app.territory_map import territory_map
        from app.core import territory_event
        event = territory_map(fig,legend_bundle,Path(root)/'app/assets',key='carte_gtfs_j18')
        action = territory_event(event,bundle)
        if action and action['event_id']!=st.session_state.get('_last_j18_event'):
            st.session_state['_last_j18_event'] = action['event_id']; st.session_state['_territoire_action'] = action; st.rerun()
        st.caption('Noms au survol des points. Les couleurs et logos disponibles reprennent le référentiel des lignes. Les branches restent séparées ; aucune liaison droite entre arrêts ne remplace un tracé absent.')
        q = qualite.loc[qualite['route_id'].isin(chosen),['LIBELLE','MODE','STATUT_TRACE']]
        st.dataframe(q.rename(columns={'LIBELLE':'Ligne','MODE':'Mode','STATUT_TRACE':'Origine/disponibilité du tracé'}),hide_index=True,width='stretch')
    with tab_table:
        t = details.merge(stops[['stop_id','stop_name']],on='stop_id',how='left',validate='many_to_one')
        cols = ['stop_name','LIBELLE','direction_id','NB_DEPARTS_PROGRAMMES','NB_DEPARTS_ESTIMES_CADENCE','DEPARTS_PROGRAMMES_PAR_HEURE']
        names = {'stop_name':'Arrêt','LIBELLE':'Ligne','direction_id':'Sens GTFS',
            'NB_DEPARTS_PROGRAMMES':'Départs programmés','NB_DEPARTS_ESTIMES_CADENCE':'Volume estimé en cadence',
            'DEPARTS_PROGRAMMES_PAR_HEURE':'Départs programmés / heure'}
        st.dataframe(t[cols].rename(columns=names),hide_index=True,width='stretch')
        st.caption('Les sens 0 et 1 sont ceux du GTFS ; ils ne signifient pas automatiquement entrant et sortant de la commune.')
        st.download_button('Télécharger les départs de la sélection',t.to_csv(index=False,sep=';').encode('utf-8-sig'),
            file_name='offre_gtfs_'+code+'_'+m['date_service']+'_'+w+'.csv',mime='text/csv',key='j18_export')
    with tab_quality:
        st.write('Les nombres décrivent les horaires publiés dans le flux archivé. Ils ne mesurent pas la fréquentation, la capacité ou le chiffre d’affaires potentiel.')
        st.dataframe(pd.DataFrame([{'Contrôle':k.replace('_',' ').capitalize(),'Valeur':str(v)}
            for k,v in m['qualite_horaires'].items()]),hide_index=True,width='stretch')
        st.write('Les arrêts sur une frontière ou sans coordonnées exploitables restent non affectés. Les quais restent distincts ; les volumes ne représentent pas des voyageurs uniques.')
        st.write('Les géométries J18 améliorent l’affichage. Les indicateurs de distances et de surfaces calculés en J14 conservent leur méthode et leurs sources d’origine.')
        for source in m['sources']:
            st.write(source.get('source','Source')+' · '+source.get('fichier',''))
            if source.get('url'): st.link_button('Consulter la source',source['url'])
    with tab_validations:
        from app.validations_j18 import afficher as afficher_validations
        afficher_validations(root,bundle,d,signature,m,str(commune),iris)


def construire_carte(bundle,d,signature,commune,iris,chosen,routes,stops,offre,show_iris=True,show_outline=True,show_stops=True,show_restaurants=False):
    from app.core import build_territory_map,map_bounds,clip_line,line_parts
    import plotly.graph_objects as go
    adapted = enrichir_carte_j18(bundle,commune,False)
    fig,_ = build_territory_map(adapted,commune,iris,show_restaurants=show_restaurants,show_commune_outline=show_outline)
    if not show_iris:
        fig.data = tuple(t for t in fig.data if not (isinstance(t.meta,dict) and t.meta.get('ROLE')=='IRIS'))
    bounds = map_bounds(adapted,commune,iris); west,south,east,north = bounds
    tr = lire_parquet(str(Path(d)/'traces_gtfs.parquet'),signature,
        [('MINX','<=',east),('MAXX','>=',west),('MINY','<=',north),('MAXY','>=',south)])
    tr = tr.loc[tr['route_id'].isin(chosen)]
    ref = routes.set_index('route_id'); legends = dict(bundle); extra = []
    for rid in chosen:
        r = ref.loc[rid]; ident = r['ID_LINE'] or 'GTFS::'+rid
        if not r['ID_LINE']:
            extra.append({'ID_LINE':ident,'NUMERO':r['route_short_name'] or rid,'MODE':r['MODE'],
                'LIBELLE_LIGNE':r['LIBELLE'],'COULEUR_WEB':r['COULEUR'],'PICTO_URL':''})
        lon = []; lat = []; sources = set()
        for row in tr.loc[tr['route_id'].eq(rid)].to_dict('records'):
            sources.add(row['SOURCE_TRACE'])
            for coords in line_parts(json.loads(row['GEOJSON'])):
                for part in clip_line(coords,bounds):
                    lon += [p[0] for p in part]+[None]; lat += [p[1] for p in part]+[None]
        if not lon: continue
        group = 'ligne_'+ident
        fig.add_trace(go.Scattergeo(lon=lon,lat=lat,mode='lines',line={'color':'white','width':4.2},
            legendgroup=group,showlegend=False,hoverinfo='skip'))
        label = html.escape(str(r['LIBELLE']))+'<br>'+html.escape(' / '.join(sorted(sources)))
        fig.add_trace(go.Scattergeo(lon=lon,lat=lat,mode='lines',line={'color':r['COULEUR'],'width':2.7},
            name=str(r['LIBELLE']),text=[label]*len(lon),hovertemplate='%{text}<extra></extra>',
            legendgroup=group,showlegend=False,meta={'ROLE':'LIGNE','ID_LINE':ident}))
    if extra: legends['lignes'] = pd.concat([bundle['lignes'],pd.DataFrame(extra)],ignore_index=True)
    if show_stops:
        counts = offre.loc[offre['route_id'].isin(chosen)].groupby('stop_id')[
            ['NB_DEPARTS_PROGRAMMES','NB_DEPARTS_ESTIMES_CADENCE']].sum()
        p = stops.loc[stops['stop_id'].isin(counts.index)&stops['stop_lon'].between(west,east)&stops['stop_lat'].between(south,north)].copy()
        if not p.empty:
            labels = [html.escape(str(r.stop_name))+'<br>Départs programmés : '+fmt(counts.at[r.stop_id,'NB_DEPARTS_PROGRAMMES'])+
                '<br>Volume estimé en cadence : '+fmt(counts.at[r.stop_id,'NB_DEPARTS_ESTIMES_CADENCE'],1) for r in p.itertuples()]
            fig.add_trace(go.Scattergeo(lon=p['stop_lon'],lat=p['stop_lat'],mode='markers',
                marker={'size':7,'color':'#132b3a','line':{'width':1,'color':'white'}},text=labels,
                hovertemplate='%{text}<extra></extra>',name='Arrêts GTFS',showlegend=False))
    fig.update_layout(title='Offre de transport prévue — '+str(bundle['profil_communes'].set_index('CODGEO').at[commune,'NOM_COMMUNE']),
        margin={'l':5,'r':160,'t':65,'b':30},showlegend=False)
    return fig,legends
