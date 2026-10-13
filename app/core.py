"""Lecture contrôlée des exports et fonctions de présentation sans Streamlit."""
from pathlib import Path
import csv, json, hashlib, re, html, math
import pandas as pd
import plotly.graph_objects as go

MODES = {'METRO': 'Métro', 'BUS': 'Bus', 'RER': 'RER', 'TRANSILIEN': 'Transilien'}
TABLES = ['profil_iris.csv', 'profil_communes.csv', 'arrets.csv', 'lignes.csv',
          'relations.csv', 'restaurants.csv', 'sources.csv']
GEOS = ['iris_focus.geojson', 'traces_focus.geojson']
LABELS = {'IRIS':'Code IRIS','CODGEO':'Code commune','NOM_IRIS':'Quartier / IRIS',
          'NOM_COMMUNE':'Commune','TYP_IRIS':'Type IRIS','POPULATION':'Population',
          'RESTAURANTS':'Restaurants observés','RAPIDES':'Restauration rapide observée',
          'DENSITE_RESTAURANTS':'Restaurants pour 10 000 habitants',
          'MEDIANE_UC':'Niveau de vie médian annuel par UC (€)',
          'PAUVRETE_PCT':'Taux de pauvreté (%)','STATUT_REVENUS':'Disponibilité des revenus',
          'PART_1529_PCT':'Population de 15 à 29 ans (%)',
          'MOBPRO_ENTRANTS':'Actifs venant travailler dans la commune',
          'MOBPRO_SORTANTS':'Actifs travaillant dans une autre commune française',
          'ANNEE_REVENUS':'Année des revenus', 'GEOGRAPHIE_REVENUS':'Géographie des revenus'}
for mode, nom in MODES.items():
    LABELS.update({f'DIST_{mode}_M':f'{nom} : distance directe du point IRIS (m)',
                  f'LIGNES_{mode}':f'{nom} : lignes proches des points IRIS',
                  f'SURFACE_{mode}_PCT':f'{nom} : surface proche des arrêts (%)',
                  f'ARRETS_{mode}':f'{nom} : entités d’arrêt affectées',
                  f'STATUT_{mode}':f'{nom} : statut des observations'})

def sha256(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for part in iter(lambda:f.read(1048576),b''):h.update(part)
    return h.hexdigest()

def read_csv(p):
    with Path(p).open(encoding='utf-8-sig',newline='') as f:
        reader=csv.reader(f,strict=True);cols=next(reader)
        if not cols or len(cols)!=len(set(cols)):raise ValueError(f'{Path(p).name} : en-têtes invalides.')
        for r in reader:
            if r and len(r)!=len(cols):raise ValueError(f'{Path(p).name} : ligne CSV {reader.line_num} mal formée.')
    return pd.read_csv(p,dtype='string',encoding='utf-8-sig')

def numeric(series):
    s=series.astype('string').str.strip().replace('',pd.NA)
    s=s.str.replace('\u202f','',regex=False).str.replace('\u00a0','',regex=False).str.replace(' ','',regex=False).str.replace(',','.',regex=False)
    n=pd.to_numeric(s,errors='coerce').astype(float)
    if (s.notna() & (n.isna() | ~n.map(math.isfinite))).any():raise ValueError('Nombre non interprétable dans un export.')
    return n

def load_bundle(directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version')!=1:raise ValueError('Version des exports non reconnue. Relancer J15a.')
    listed=manifest.get('fichiers',[])
    names=[r['nom'] for r in listed]
    if len(names)!=len(set(names)) or set(TABLES+GEOS)-set(names):raise ValueError('Manifeste incomplet ou dupliqué.')
    for row in listed:
        name=row['nom']
        if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Chemin de fichier non reconnu.')
        p=directory/name
        if not p.is_file() or sha256(p)!=row['sha256']:raise ValueError(name+' : export absent ou différent du manifeste. Relancer J15a.')
    bundle={Path(n).stem:read_csv(directory/n) for n in TABLES}
    bundle.update({Path(n).stem:json.loads((directory/n).read_text(encoding='utf-8')) for n in GEOS})
    bundle['manifest']=manifest
    i=bundle['profil_iris'];c=bundle['profil_communes'];a=bundle['arrets'];l=bundle['lignes'];rel=bundle['relations']
    if len(i)!=manifest['nb_iris'] or set(i['IRIS'].str[:2])!={'75','77','78','91','92','93','94','95'}:raise ValueError('Couverture régionale des IRIS différente du manifeste.')
    for t, key, pattern in [(i,'IRIS',r'\d{9}'),(c,'CODGEO',r'\d{5}')]:
        if key not in t or not t[key].is_unique or not t[key].str.fullmatch(pattern,na=False).all():raise ValueError(key+' : codes invalides/dupliqués.')
    if not i['CODGEO'].isin(c['CODGEO']).all():raise ValueError('Codes communaux des IRIS non appariés.')
    for t in [i,c]:
        for col in t:
            if col in {'POPULATION','RESTAURANTS','RAPIDES','DENSITE_RESTAURANTS','MEDIANE_UC','PAUVRETE_PCT','PART_1529_PCT','MOBPRO_ENTRANTS','MOBPRO_SORTANTS','ANNEE_REVENUS','GEOGRAPHIE_REVENUS'} or col.startswith(('DIST_','LIGNES_','SURFACE_','ARRETS_')):
                t[col]=numeric(t[col])
                if t[col].dropna().lt(0).any():raise ValueError(col+' : valeur négative.')
                if col.endswith('_PCT') and not t[col].dropna().between(0,100+1e-8).all():raise ValueError(col+' : pourcentage hors limites.')
    if not a['ID_ARRET'].is_unique or not l['ID_LINE'].is_unique:raise ValueError('Identifiants des objets cartographiques dupliqués.')
    if rel[['ID_ARRET','ID_LINE']].duplicated().any():raise ValueError('Relations arrêt–ligne dupliquées.')
    if not rel['ID_ARRET'].isin(a['ID_ARRET']).all() or not rel['ID_LINE'].isin(l['ID_LINE']).all():raise ValueError('Relations cartographiques non appariées.')
    if not l['MODE'].isin(MODES).all() or not l['COULEUR_WEB'].str.fullmatch(r'#[0-9a-fA-F]{6}',na=False).all():raise ValueError('Modes/couleurs non reconnus.')
    for t in [a,bundle['restaurants']]:
        for col in ['LONGITUDE','LATITUDE']:t[col]=numeric(t[col])
        if t[['LONGITUDE','LATITUDE']].isna().any().any() or not t['LONGITUDE'].between(-180,180).all() or not t['LATITUDE'].between(-90,90).all():raise ValueError('Coordonnées cartographiques invalides.')
    for n in ['iris_focus','traces_focus']:
        if bundle[n].get('type')!='FeatureCollection':raise ValueError(n+' : GeoJSON non reconnu.')
    if any(f['properties']['ID_LINE'] not in set(l['ID_LINE']) for f in bundle['traces_focus']['features']):raise ValueError('Tracé sans ligne du catalogue.')
    return bundle

def fmt(value,unit='',decimals=0):
    if value is None or pd.isna(value):return 'Non disponible'
    return f'{float(value):,.{decimals}f}'.replace(',',' ').replace('.',',')+unit

def client_table(t,cols=None):
    if cols is not None:t=t[[c for c in cols if c in t]].copy()
    return t.rename(columns=LABELS)

def fiche(row,manifest,iris=False):
    name=str(row.get('NOM_IRIS') if iris else row.get('NOM_COMMUNE'))
    lines=[f'# Diagnostic descriptif — {name}',f"Population RP {manifest['annee_rp']} : {fmt(row.get('POPULATION'))} habitants.",
           f"Restaurants observés : {fmt(row.get('RESTAURANTS'))}.",f"Restaurants pour 10 000 habitants : {fmt(row.get('DENSITE_RESTAURANTS'),decimals=1)}."]
    if iris:
        lines += [f"Niveau de vie médian annuel par UC : {fmt(row.get('MEDIANE_UC'),' €')}.",
                  f"Taux de pauvreté : {fmt(row.get('PAUVRETE_PCT'),' %',1)}.",
                  'Les revenus sont des indicateurs fiscaux publiés à cette maille. Une médiane IRIS ne se somme pas.']
    else:lines += [f"Actifs venant travailler dans la commune, RP {manifest['annee_rp']} : {fmt(row.get('MOBPRO_ENTRANTS'))}."]
    lines += ['', 'Transports :']
    for mode,nom in MODES.items():
        lines.append(f"- {nom} : {fmt(row.get('LIGNES_'+mode))} lignes observées près des points IRIS ; {fmt(row.get('SURFACE_'+mode+'_PCT'),' %',1)} de surface proche des arrêts.")
    lines += ['', 'Ces observations décrivent le territoire. Elles ne prédisent ni les ventes ni la rentabilité.',
              'Les distances sont directes ; les surfaces proches ne sont pas des parts de population. Les flux de travail restent communaux.',
              'Horaires, fréquence, marche réelle et fréquentation ne sont pas mesurés dans cette version.',
              f"Géographie IRIS : {manifest['geographie_iris']}. Les dates IDFM/BPE peuvent être différentes du RP."]
    return '\n\n'.join(lines)

def line_parts(geom):
    if not geom:return []
    if geom['type']=='LineString':return [geom['coordinates']]
    if geom['type']=='MultiLineString':return geom['coordinates']
    if geom['type']=='GeometryCollection':return [p for g in geom['geometries'] for p in line_parts(g)]
    return []

def build_map(bundle,modes,line_ids,show_restaurants=True,iris_code=None):
    """La carte décrit la sélection locale J14 ; elle ne recalcule pas les indicateurs."""
    geo=bundle['iris_focus']; features=geo['features']
    ids=[f['properties']['IRIS'] for f in features]
    prof=bundle['profil_iris'].set_index('IRIS')
    texts=[html.escape(str(prof.loc[x,'NOM_IRIS']))+'<br>Population : '+fmt(prof.loc[x,'POPULATION'])+'<br>Restaurants observés : '+fmt(prof.loc[x,'RESTAURANTS']) for x in ids]
    fig=go.Figure(go.Choropleth(geojson=geo,featureidkey='properties.IRIS',locationmode='geojson-id',locations=ids,
        z=[1 if x==iris_code else 0 for x in ids],zmin=0,zmax=1,colorscale=[[0,'#f1f5f9'],[1,'#cbd5e1']],showscale=False,
        marker_line_color='#a5b4c4',marker_line_width=.7,text=texts,hovertemplate='%{text}<extra></extra>'))
    catalog=bundle['lignes'].set_index('ID_LINE')
    chosen=set(catalog.index[catalog['MODE'].isin(modes)]) & set(line_ids)
    grouped={}
    for f in bundle['traces_focus']['features']:
        ident=f['properties']['ID_LINE']
        if ident in chosen:grouped.setdefault(ident,[]).extend(line_parts(f['geometry']))
    for ident,parts in grouped.items():
        lon=[];lat=[]
        for coords in parts:
            lon += [c[0] for c in coords]+[None];lat += [c[1] for c in coords]+[None]
        r=catalog.loc[ident];name=html.escape(str(r['LIBELLE_LIGNE']));group='ligne_'+ident
        fig.add_trace(go.Scattergeo(lon=lon,lat=lat,mode='lines',line=dict(color='white',width=4),hoverinfo='skip',showlegend=False,legendgroup=group))
        fig.add_trace(go.Scattergeo(lon=lon,lat=lat,mode='lines',line=dict(color=r['COULEUR_WEB'],width=2.5),name=name,
            legendgroup=group,text=[name]*len(lon),hovertemplate='%{text}<extra></extra>',meta={'ROLE':'LIGNE','ID_LINE':ident}))
    rel=bundle['relations'].loc[bundle['relations']['ID_LINE'].isin(chosen)].merge(bundle['lignes'][['ID_LINE','LIBELLE_LIGNE']],on='ID_LINE',validate='many_to_one')
    ar=bundle['arrets'].loc[bundle['arrets']['ID_ARRET'].isin(rel['ID_ARRET'])].sort_values('ID_ARRET')
    desc=rel.groupby('ID_ARRET')['LIBELLE_LIGNE'].agg(lambda s:' ; '.join(sorted(set(s))))
    maxpoints=5000;ap=ar.head(maxpoints)
    hover=[html.escape(str(r.NOM_ARRET))+'<br>'+html.escape(desc.get(r.ID_ARRET,'')) for r in ap.itertuples()]
    fig.add_trace(go.Scattergeo(lon=ap['LONGITUDE'],lat=ap['LATITUDE'],mode='markers',marker=dict(size=5,color='#172b4d'),text=hover,
        hovertemplate='%{text}<extra></extra>',name='Arrêts observés'))
    rr=bundle['restaurants'];rp=rr.sort_values('CLE_POINT').head(maxpoints) if show_restaurants else rr.iloc[:0]
    if not rp.empty:
        texts=[html.escape(str(r.NOM))+'<br>'+html.escape(str(r.CATEGORIE)) for r in rp.itertuples()]
        fig.add_trace(go.Scattergeo(lon=rp['LONGITUDE'],lat=rp['LATITUDE'],mode='markers',marker=dict(size=6,color='#c2410c'),text=texts,
            hovertemplate='%{text}<extra></extra>',name='Restaurants observés'))
    fig.update_geos(visible=False,fitbounds='locations',projection_type='mercator')
    fig.update_layout(title='Transports et restauration — secteur pilote',height=660,margin=dict(l=5,r=5,t=50,b=5),legend=dict(font=dict(size=11)))
    return fig, {'arrets_disponibles':len(ar),'arrets_affiches':len(ap),'restaurants_disponibles':len(rr),
                 'restaurants_affiches':len(rp),'lignes_avec_trace':len(grouped),'lignes_selectionnees':len(chosen)}

def map_html(fig,bundle,assets):
    """Plotly, logos et ressource géographique intégrés ; aucune clé API."""
    topo=json.loads((Path(assets)/'world_110m.json').read_text(encoding='utf-8'))
    palette=json.loads((Path(assets)/'pictogrammes_idfm.json').read_text(encoding='utf-8'))
    catalog=bundle['lignes'].set_index('ID_LINE');buttons=[]
    for t in fig.data:
        if not isinstance(t.meta,dict) or t.meta.get('ROLE')!='LIGNE':continue
        ident=t.meta['ID_LINE'];r=catalog.loc[ident];nom=html.escape(str(r['LIBELLE_LIGNE']),quote=True)
        logo=palette.get(ident);url=r.get('PICTO_URL')
        def resource(v):
            if v is None or pd.isna(v):return None
            m=re.search(r'/files/([a-zA-Z0-9]+)',str(v));return m.group(1) if m else str(v)
        if logo and resource(url)==resource(logo['picto_url']):visual='<img width="32" height="32" alt="'+nom+'" src="'+logo['picto_data_uri']+'">'
        else:visual='<span style="background:'+str(r['COULEUR_WEB'])+';padding:7px;color:white;text-shadow:0 1px 3px #000">'+html.escape(str(r['NUMERO']))+'</span>'
        buttons.append('<button class="ligne-idfm" aria-pressed="true" data-groupe="ligne_'+ident+'">'+visual+'<span>'+nom+'</span></button>')
    panel='<style>body{font-family:Arial}.legende{padding:12px}.boutons{display:flex;flex-wrap:wrap;gap:8px}.ligne-idfm{display:flex;align-items:center;gap:7px;border:1px solid #ccd5df;border-radius:7px;background:white;padding:6px;color:#172b4d;cursor:pointer}.ligne-idfm[aria-pressed="false"]{opacity:.4}</style><section class="legende"><b>Lignes représentées</b><p>Cliquer pour masquer ou afficher un tracé.</p><div class="boutons">'+''.join(buttons)+'</div></section>'
    panel += """<script>(function(){function init(){const gd=document.querySelector('.plotly-graph-div');
    const bs=Array.from(document.querySelectorAll('button.ligne-idfm'));
    function ids(g){return gd.data.map((t,i)=>t.legendgroup===g?i:-1).filter(i=>i>=0);}
    function sync(){bs.forEach(b=>b.setAttribute('aria-pressed',String(ids(b.dataset.groupe).some(i=>gd.data[i].visible!==false&&gd.data[i].visible!=='legendonly'))));}
    bs.forEach(b=>b.addEventListener('click',()=>{const ix=ids(b.dataset.groupe);const visible=ix.some(i=>gd.data[i].visible!==false&&gd.data[i].visible!=='legendonly');Plotly.restyle(gd,{visible:visible?'legendonly':true},ix).then(sync);}));
    gd.on('plotly_restyle',sync);sync();}
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();})();</script>"""
    body=fig.to_html(include_plotlyjs=True,full_html=True,config={'displaylogo':False,'scrollZoom':True})
    bootstrap='<script>window.PlotlyGeoAssets={topojson:{world_110m:'+json.dumps(topo,separators=(',',':'))+'}};</script>'
    return body.replace('</head>',bootstrap+'\n</head>',1).replace('</body>',panel+'\n</body>')
