"""Contours complets, frontières partagées et tracés sans raccord artificiel."""
from pathlib import Path
from itertools import groupby
import json
import sqlite3

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, shape, mapping

from scripts.preparer_gtfs_j18 import ecrire_csv, identifiant_commercial


def polygons(geom):
    if geom is None or geom.is_empty: return []
    if geom.geom_type=='Polygon': return [geom]
    if hasattr(geom,'geoms'): return [p for g in geom.geoms for p in polygons(g)]
    return []


def lignes(geom):
    if geom is None or geom.is_empty: return []
    if geom.geom_type=='LineString': return [geom] if geom.length>0 else []
    if hasattr(geom,'geoms'): return [p for g in geom.geoms for p in lignes(g)]
    return []


def charger_contours(path, layer, base, annee_geographie, interim, reparer=False):
    if int(annee_geographie)!=int(base['manifest']['geographie_iris']):
        raise ValueError('Choisir des contours du même millésime géographique que J15a. Ne pas mélanger les limites avant/après fusion.')
    p = Path(path)
    if not p.is_file(): raise FileNotFoundError('Contours complets manquants : '+str(p))
    if p.suffix.lower()=='.gpkg' and layer is None:
        layers = gpd.list_layers(p)
        if len(layers)>1: raise ValueError('Plusieurs couches dans le GPKG : renseigner COUCHE_IRIS. '+str(layers['name'].tolist()))
    g = gpd.read_file(p,**({'layer':layer} if layer else {}))
    names = {str(c).strip().upper():c for c in g.columns}
    key = next((names[k] for k in ['IRIS','CODE_IRIS','DCOMIRIS'] if k in names),None)
    if key is None or g.crs is None: raise ValueError('Contours : code IRIS et CRS déclaré requis.')
    g['IRIS'] = g[key].astype('string').str.strip()
    if not g['IRIS'].is_unique: raise ValueError('Contours : code IRIS dupliqué, vérifier le fichier choisi.')
    wanted = set(base['profil_iris']['IRIS'])
    g = g.loc[g['IRIS'].isin(wanted),['IRIS',g.geometry.name]].copy()
    if set(g['IRIS'])!=wanted:
        raise ValueError('IRIS absents des contours complets : '+str(sorted(wanted-set(g['IRIS']))[:20]))
    if g.geometry.name!='geometry': g = g.rename_geometry('geometry')
    g = g.to_crs(2154).merge(base['profil_iris'][['IRIS','CODGEO']],on='IRIS',validate='one_to_one')
    audit = []
    for idx,r in g.iterrows():
        geom = r.geometry
        if geom is None or geom.is_empty:
            raise ValueError('Contour vide/absent : '+r['IRIS'])
        invalid = not geom.is_valid or geom.geom_type not in ['Polygon','MultiPolygon']
        if invalid:
            fixed = shapely.union_all(polygons(shapely.make_valid(geom)))
            audit.append({'IRIS':r['IRIS'],'RAISON':shapely.is_valid_reason(geom),
                'SURFACE_AVANT_M2':geom.area,'SURFACE_APRES_M2':fixed.area,'REPARATION_AUTORISEE':reparer})
            if reparer and not fixed.is_empty and fixed.is_valid: g.at[idx,'geometry'] = fixed
    ecrire_csv(pd.DataFrame(audit,columns=['IRIS','RAISON','SURFACE_AVANT_M2','SURFACE_APRES_M2','REPARATION_AUTORISEE']),
               Path(interim)/'geometries_a_revoir_j18.csv')
    if audit and not reparer:
        raise ValueError('Contours invalides : consulter geometries_a_revoir_j18.csv puis autoriser une réparation contrôlée ou reprendre la source.')
    if not g.geometry.is_valid.all() or not g.geom_type.isin(['Polygon','MultiPolygon']).all() or not g.area.gt(0).all():
        raise ValueError('La source reste non polygonale/invalide après préparation.')
    union = g.geometry.union_all()
    overlap = max(0.,float(g.area.sum()-union.area))
    coverage = bool(shapely.coverage_is_valid(g.geometry.values))
    if not coverage:
        bad = shapely.coverage_invalid_edges(g.geometry.values)
        edges = gpd.GeoDataFrame({'IRIS':g['IRIS']},geometry=bad,crs=2154)
        edges = edges.loc[~edges.geometry.is_empty]
        if not edges.empty: edges.to_file(Path(interim)/'frontieres_a_revoir_j18.gpkg',layer='frontieres',driver='GPKG')
    if overlap>1:
        raise ValueError(f'Chevauchement des IRIS : {overlap:.2f} m². Reprendre la source ; aucun déplacement automatique des frontières.')
    quality = {'NB_IRIS':len(g),'NB_REPARATIONS':len(audit),'COUVERTURE_TOPOLOGIQUE_VALIDE':coverage,
               'CHEVAUCHEMENT_TOTAL_M2':overlap,'SURFACE_TOTALE_M2':float(union.area)}
    return g,quality


def vues_contours(full, quality, tolerances, interim):
    """Dissoudre les communes à partir de chaque même couverture IRIS."""
    views = {}; audits = []
    for nom,tolerance,max_distance in tolerances:
        before = full.geometry
        if tolerance<0 or max_distance<0: raise ValueError('Tolérances géométriques positives ou nulles attendues.')
        if tolerance and quality['COUVERTURE_TOPOLOGIQUE_VALIDE']:
            simplified = gpd.GeoSeries(shapely.coverage_simplify(before.values,tolerance,simplify_boundary=False),index=full.index,crs=2154)
            hd = shapely.hausdorff_distance(before.values,simplified.values)
            ok = bool(simplified.is_valid.all() and simplified.area.gt(0).all()
                and shapely.coverage_is_valid(simplified.values) and np.max(hd)<=max_distance)
            statut = 'SIMPLIFICATION_PARTAGEE' if ok else 'CONTOURS_COMPLETS_SEUIL_DEPASSE'
            after = simplified if ok else before.copy()
        else:
            after = before.copy()
            statut = 'CONTOURS_COMPLETS' if not tolerance else 'CONTOURS_COMPLETS_TOPOLOGIE_A_REVOIR'
        hd = shapely.hausdorff_distance(before.values,after.values)
        iris = full.copy(); iris.geometry = after
        communes = iris.dissolve(by='CODGEO',as_index=False)[['CODGEO','geometry']]
        for idx,r in iris.iterrows():
            audits.append({'LOD':nom,'IRIS':r['IRIS'],'STATUT':statut,
                'PARAMETRE_SIMPLIFICATION_M':tolerance,'ECART_HAUSDORFF_M':float(hd[full.index.get_loc(idx)]),
                'VARIATION_SURFACE_PCT':100*(r.geometry.area/before.loc[idx].area-1),
                'SOMMETS_COMPLETS':int(shapely.get_num_coordinates(before.loc[idx])),
                'SOMMETS_AFFICHAGE':int(shapely.get_num_coordinates(r.geometry))})
        views[nom] = {'IRIS':iris,'COMMUNE':communes}
    ecrire_csv(pd.DataFrame(audits),Path(interim)/'qualite_contours_affichage_j18.csv')
    return views,pd.DataFrame(audits)


def affecter_arrets(stops, full, interim):
    s = stops.loc[stops['location_type'].isin(['','0'])].copy()
    s['IRIS'] = ''; s['CODGEO'] = ''; s['STATUT_GEO'] = 'COORDONNEES_ABSENTES_OU_INVALIDES'
    valid = s['COORDONNEES_VALIDES']
    points = gpd.GeoDataFrame(s.loc[valid,['stop_id']],
        geometry=gpd.points_from_xy(s.loc[valid,'stop_lon'],s.loc[valid,'stop_lat']),crs=4326).to_crs(2154)
    join = gpd.sjoin(points,full[['IRIS','CODGEO','geometry']],how='left',predicate='within')
    hits = join.loc[join['IRIS'].notna()]
    if hits['stop_id'].duplicated().any():
        raise ValueError('Arrêt situé dans plusieurs IRIS : reprendre la topologie des contours.')
    idx = hits.set_index('stop_id')
    s.loc[valid,'STATUT_GEO'] = 'HORS_CONTOURS_OU_SUR_FRONTIERE'
    matched = s['stop_id'].isin(idx.index)
    s.loc[matched,'IRIS'] = s.loc[matched,'stop_id'].map(idx['IRIS'])
    s.loc[matched,'CODGEO'] = s.loc[matched,'stop_id'].map(idx['CODGEO'])
    s.loc[matched,'STATUT_GEO'] = 'INTERIEUR_UNIQUE_IRIS'
    ecrire_csv(s.loc[~matched],Path(interim)/'arrets_non_affectes_j18.csv')
    return s


def shapes_gtfs(flux, trips, interim, chunksize=100000):
    ids = set(trips.loc[trips['shape_id'].ne(''),'shape_id'])
    columns = ['shape_id','geometry']
    if not ids or 'shapes.txt' not in flux.membres:
        return gpd.GeoDataFrame(columns=columns,geometry='geometry',crs=4326),pd.DataFrame(columns=['shape_id','STATUT'])
    db = Path(interim)/'shapes_actifs_j18.sqlite'
    if db.exists(): db.unlink()
    con = sqlite3.connect(db); bad = set(); audits = []
    try:
        con.execute('PRAGMA temp_store=FILE')
        con.execute('CREATE TABLE points (shape_id TEXT,seq INTEGER,lon REAL,lat REAL)')
        for t in flux.lire('shapes.txt',['shape_id','shape_pt_lat','shape_pt_lon','shape_pt_sequence'],chunksize=chunksize):
            t = t.loc[t['shape_id'].isin(ids)].copy()
            if t.empty: continue
            seq = pd.to_numeric(t['shape_pt_sequence'],errors='coerce')
            lon = pd.to_numeric(t['shape_pt_lon'],errors='coerce'); lat = pd.to_numeric(t['shape_pt_lat'],errors='coerce')
            ok = seq.notna() & seq.ge(0) & seq.mod(1).eq(0) & lon.between(-180,180) & lat.between(-90,90)
            bad |= set(t.loc[~ok,'shape_id'])
            pd.DataFrame({'shape_id':t.loc[ok,'shape_id'],'seq':seq[ok].astype(int),'lon':lon[ok],'lat':lat[ok]}).to_sql('points',con,index=False,if_exists='append')
        bad |= {r[0] for r in con.execute('SELECT shape_id FROM points GROUP BY shape_id,seq HAVING COUNT(*)>1')}
        con.execute('CREATE INDEX idx_shape ON points(shape_id,seq)')
        rows = []
        for sid,group in groupby(con.execute('SELECT shape_id,lon,lat FROM points ORDER BY shape_id,seq'),lambda x:x[0]):
            coords = [(x[1],x[2]) for x in group]
            if sid in bad or len(set(coords))<2:
                audits.append({'shape_id':sid,'STATUT':'GEOMETRIE_REJETEE_ENTIERE'}); continue
            geom = LineString(coords)
            rows.append({'shape_id':sid,'geometry':geom})
        available = {r['shape_id'] for r in rows}
        audits += [{'shape_id':x,'STATUT':'ABSENT_OU_INVALIDE'} for x in sorted(ids-available) if x not in bad]
        return gpd.GeoDataFrame(rows,columns=columns,geometry='geometry',crs=4326),pd.DataFrame(audits,columns=['shape_id','STATUT'])
    finally:
        con.close()


def preparer_traces(flux, trips, routes, base, interim, complements=(), chunksize=100000):
    shapes,audit = shapes_gtfs(flux,trips,interim,chunksize)
    ecrire_csv(audit,Path(interim)/'shapes_absents_invalides_j18.csv')
    shapes_index = shapes.set_index('shape_id')['geometry'].to_dict()
    official = {}; invalid = []
    for cfg in complements:
        p = Path(cfg['fichier'])
        g = gpd.read_file(p,**({'layer':cfg['couche']} if cfg.get('couche') else {}))
        champ = cfg['id_ligne']
        if champ not in g or g.crs is None: raise ValueError('Tracés complémentaires : champ ou CRS absent : '+str(p))
        g = g.to_crs(4326)
        for r in g.to_dict('records'):
            ident = identifiant_commercial(r[champ])
            if not ident or ident not in set(base['lignes']['ID_LINE']):
                invalid.append({'SOURCE':p.name,'ID_BRUT':str(r[champ]),'STATUT':'IDENTIFIANT_NON_APPARIE'}); continue
            for geom in lignes(r[g.geometry.name]):
                if geom.is_valid: official.setdefault(ident,[]).append((geom,cfg.get('url','')))
    ecrire_csv(pd.DataFrame(invalid,columns=['SOURCE','ID_BRUT','STATUT']),Path(interim)/'traces_complementaires_non_apparies_j18.csv')
    legacy = {}
    for f in base['traces_idf']['features']:
        for geom in lignes(shape(f['geometry'])):
            legacy.setdefault(f['properties']['ID_LINE'],[]).append(geom)
    active = routes.loc[routes['route_id'].isin(trips['route_id'])]
    shape_ids = trips.groupby('route_id')['shape_id'].agg(lambda s:sorted(set(s)-{''})).to_dict()
    rows = []; qualities = []
    for r in active.to_dict('records'):
        available = [x for x in shape_ids.get(r['route_id'],[]) if x in shapes_index]
        requested = shape_ids.get(r['route_id'],[])
        if available:
            parts = [(shapes_index[s],s,'SHAPE_GTFS',GTFS_SOURCE_URL) for s in available]
            status = 'SHAPES_COMPLETS' if len(available)==len(requested) else 'SHAPES_PARTIELS'
        elif r['ID_LINE'] in official:
            parts = [(g,'','TRACE_IDFM_COMPLEMENTAIRE',url) for g,url in official[r['ID_LINE']]]
            status = 'TRACE_COMPLEMENTAIRE'
        else:
            parts = [(g,'','TRACE_HERITE_J15A','') for g in legacy.get(r['ID_LINE'],[])]
            status = 'TRACE_HERITE' if parts else 'TRACE_ABSENT'
        for i,(geom,sid,source,url) in enumerate(parts):
            # Aucun chaînage entre formes, sens ou branches distinctes.
            rows.append({'route_id':r['route_id'],'ID_LINE':r['ID_LINE'],'MODE':r['MODE'],
                'LIBELLE':r['LIBELLE'],'COULEUR':r['COULEUR'],'shape_id':sid,
                'ID_TRONCON':r['route_id']+'::'+str(i),'SOURCE_TRACE':source,'URL_SOURCE':url,'geometry':geom})
        qualities.append({'route_id':r['route_id'],'LIBELLE':r['LIBELLE'],'MODE':r['MODE'],
            'STATUT_TRACE':status,'NB_SHAPES_DEMANDES':len(requested),'NB_SHAPES_PRESENTS':len(available),'NB_TRONCONS':len(parts)})
    cols = ['route_id','ID_LINE','MODE','LIBELLE','COULEUR','shape_id','ID_TRONCON','SOURCE_TRACE','URL_SOURCE','geometry']
    traces = gpd.GeoDataFrame(rows,columns=cols,geometry='geometry',crs=4326)
    return traces,pd.DataFrame(qualities)


GTFS_SOURCE_URL = 'https://data.iledefrance-mobilites.fr/explore/dataset/offre-horaires-tc-gtfs-idfm/'


def parquet_geometries(g, path, niveau, lod):
    w = g.to_crs(4326)
    key = 'IRIS' if niveau=='IRIS' else 'CODGEO'
    t = pd.DataFrame({'CODE':w[key].astype(str),'CODGEO':w['CODGEO'].astype(str),'LOD':lod,
        'GEOJSON':[json.dumps(mapping(x),separators=(',',':')) for x in w.geometry]})
    return t


def exporter_geometries(views, traces, dossier):
    d = Path(dossier); d.mkdir(parents=True,exist_ok=True)
    for niveau,name in [('IRIS','contours_iris.parquet'),('COMMUNE','contours_communes.parquet')]:
        t = pd.concat([parquet_geometries(v[niveau],None,niveau,lod) for lod,v in views.items()],ignore_index=True)
        t.sort_values(['LOD','CODGEO','CODE']).to_parquet(d/name,index=False)
    t = pd.DataFrame(traces.drop(columns='geometry'))
    t['GEOJSON'] = [json.dumps(mapping(x),separators=(',',':')) for x in traces.geometry]
    bounds = traces.geometry.bounds
    for c,name in [('minx','MINX'),('miny','MINY'),('maxx','MAXX'),('maxy','MAXY')]: t[name] = bounds[c]
    t.sort_values(['route_id','ID_TRONCON']).to_parquet(d/'traces_gtfs.parquet',index=False)
