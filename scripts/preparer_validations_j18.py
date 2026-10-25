"""Validations IDFM : volumes publiés, intervalles et profils sans allocation fictive."""
from pathlib import Path
from contextlib import contextmanager
from zipfile import ZipFile
from datetime import date, timedelta
import csv
import io
import json
import re
import sqlite3
import unicodedata

import numpy as np
import pandas as pd

from scripts.preparer_gtfs_j18 import sha256, ecrire_csv

DOC = 'https://eu.ftp.opendatasoft.com/stif/Validations/Documentation/Donnees_de_validation.pdf'
SOURCES = {
 'NB_FER':'https://data.iledefrance-mobilites.fr/explore/dataset/validations-reseau-ferre-nombre-validations-par-jour-1er-trimestre/',
 'NB_SURFACE':'https://data.iledefrance-mobilites.fr/explore/dataset/validations-reseau-surface-nombre-validations-par-jour-1er-trimestre/',
 'PROFIL_FER':'https://data.iledefrance-mobilites.fr/explore/dataset/validations-reseau-ferre-profils-horaires-par-jour-type-1er-trimestre/',
 'PROFIL_SURFACE':'https://data.iledefrance-mobilites.fr/explore/dataset/validation-reseau-surface-profils-horaires-par-jour-type-1er-trimestre/',
}
JOURS = {'JOHV':'Jour ouvré hors vacances scolaires','JOVS':'Jour ouvré pendant les vacances scolaires',
 'SAHV':'Samedi hors vacances scolaires','SAVS':'Samedi pendant les vacances scolaires',
 'DIJFP':'Dimanche, jour férié ou pont'}
ALIASES = {
 'JOUR':['JOUR','DATE'], 'TRNS':['CODE_STIF_TRNS','COD_STIF_TRNS'], 'RES':['CODE_STIF_RES','COD_STIF_RES'],
 'ARRET':['CODE_STIF_ARRET','COD_STIF_ARRET'], 'LIGNE':['CODE_STIF_LIGNE','COD_STIF_LIGNE'],
 'LDA':['ID_REFA_LDA','IDA'], 'GOL':['ID_GROUPOFLINES','ID_GROUPOFLIGNE','ID_GROUPOFLIGNES'],
 'NOM_FER':['LIBELLE_ARRET','LIBELLE_GARE'], 'NOM_SURFACE':['LIBELLE_LIGNE'],
 'TITRE':['CATEGORIE_TITRE'], 'NB':['NB_VALD','NB_VALIDATIONS'],
 'CAT_JOUR':['CAT_JOUR'], 'TRANCHE':['TRNC_HORR_60','TRANCHE_HORAIRE'],
 'PCT':['POURCENTAGE_VALIDATIONS','POURC_VALIDATIONS','POURC_VALIDATION','PCT_VALD'],
}


def normaliser(v):
    s = unicodedata.normalize('NFKD',str(v)).encode('ascii','ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]+','_',s).strip('_')


@contextmanager
def ouvrir(cfg):
    p = Path(cfg['fichier'])
    if p.suffix.lower()=='.zip':
        with ZipFile(p) as z:
            files = [i.filename for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(('.csv','.txt'))]
            membre = cfg.get('membre')
            if not membre:
                if len(files)!=1: raise ValueError(p.name+' : plusieurs CSV/TXT ; renseigner membre dans la configuration.')
                membre = files[0]
            with z.open(membre) as f: yield f
    else:
        with p.open('rb') as f: yield f


def blocs(cfg,chunksize):
    with ouvrir(cfg) as f:
        first = f.readline().decode('utf-8-sig')
    sep = cfg.get('sep') or max((len(next(csv.reader([first],delimiter=d))),d) for d in [';',',','\t'])[1]
    with ouvrir(cfg) as f:
        with pd.read_csv(f,sep=sep,dtype='string',keep_default_na=False,encoding='utf-8-sig',chunksize=chunksize) as reader:
            for t in reader:
                t.columns = [normaliser(c) for c in t.columns]
                if not t.columns.is_unique: raise ValueError('En-têtes de validations dupliqués.')
                yield t


def champ(t,key,required=True,cfg=None):
    override = (cfg or {}).get('colonnes',{}).get(key)
    options = [normaliser(override)] if override else ALIASES[key]
    found = [c for c in options if c in t]
    if len(found)>1:
        first = t[found[0]].astype('string').str.strip()
        if any(not first.equals(t[c].astype('string').str.strip()) for c in found[1:]):
            raise ValueError('Colonnes concurrentes pour '+key+' : renseigner colonnes explicitement.')
    if found: return t[found[0]].astype('string').str.strip()
    if required: raise ValueError('Champ de validations absent : '+key+' ; colonnes disponibles : '+str(list(t)))
    return pd.Series('',index=t.index,dtype='string')


def identifiant(s):
    return s.astype('string').str.strip().str.replace(r'\.0$','',regex=True).fillna('')


def grains(t,reseau,cfg):
    a,b = champ(t,'TRNS',cfg=cfg),champ(t,'RES',cfg=cfg)
    c = champ(t,'ARRET' if reseau=='FERRE' else 'LIGNE',cfg=cfg)
    for s in [a,b,c]:
        if not s.str.fullmatch(r'\d+(?:\.0)?',na=False).all(): raise ValueError('Codes STIF absents ou non numériques.')
    keys = [identifiant(s).str.lstrip('0').replace('','0') for s in [a,b,c]]
    source = keys[0]+':'+keys[1]+':'+keys[2]
    ref = identifiant(champ(t,'LDA' if reseau=='FERRE' else 'GOL',False,cfg))
    invalid = ref.str.upper().isin(['','0','ND','N_D','NA','NAN','NONE','NULL','A00000','NON DEFINI'])
    native = ('LDA:' if reseau=='FERRE' else 'GOL:')+ref
    entity = native.where(~invalid,'STIF:'+source)
    return pd.DataFrame({'RESEAU':reseau,'ID_ENTITE':entity,'CLE_SOURCE':source,'ID_REF':ref.where(~invalid,''),
        'NOM':champ(t,'NOM_FER' if reseau=='FERRE' else 'NOM_SURFACE',cfg=cfg)})


def valeurs(s,cinq='BORNE_PRUDENTE'):
    """Aucune valeur censurée/missing remplacée par une valeur ponctuelle inventée."""
    text = s.astype('string').str.strip()
    fold = text.map(normaliser)
    missing = fold.isin(['','S','SS','ND','N_D','NA','N_A','NAN','NULL','NONE'])
    small = fold.isin(['MOINS_DE_5','MOINS_DE_CINQ']) | text.str.fullmatch(r'<\s*5',na=False)
    clean = text.str.replace('\u202f','',regex=False).str.replace('\u00a0','',regex=False).str.replace(' ','',regex=False).str.replace(',','.',regex=False)
    n = pd.to_numeric(clean.where(~missing & ~small),errors='coerce')
    if ((~missing & ~small) & (n.isna() | ~np.isfinite(n) | n.lt(0) | n.mod(1).ne(0))).any():
        raise ValueError('NB_VALD non interprétable : '+str(text.loc[(~missing & ~small)&n.isna()].head(5).tolist()))
    if cinq not in ['BORNE_PRUDENTE','EXACT_CONFIRME']:
        raise ValueError('cinq_numerique attendu BORNE_PRUDENTE ou EXACT_CONFIRME après vérification de la source.')
    five = n.eq(5).fillna(False) & (cinq=='BORNE_PRUDENTE')
    lo = n.astype(float); hi = n.astype(float)
    lo.loc[small] = 1.; hi.loc[small] = 4.
    lo.loc[five] = 0.; hi.loc[five] = 5.
    lo.loc[missing] = 0.; hi.loc[missing] = np.nan
    return pd.DataFrame({'BORNE_INF':lo,'BORNE_SUP':hi,'NB_CENSURES':(small|five).astype(int),
        'NB_MANQUANTS':missing.astype(int),'NB_CINQ_PRUDENTS':five.astype(int)})


def parse_dates(s):
    # Formats explicites : aucun jour/mois ambigu interprété à l'américaine.
    text = s.astype('string').str.strip(); result = pd.Series(pd.NaT,index=s.index,dtype='datetime64[ns]')
    iso = text.str.fullmatch(r'\d{4}-\d{2}-\d{2}',na=False)
    fr = text.str.fullmatch(r'\d{2}/\d{2}/\d{4}',na=False)
    compact = text.str.fullmatch(r'\d{8}',na=False)
    for mask,fmt in [(iso,'%Y-%m-%d'),(fr,'%d/%m/%Y'),(compact,'%Y%m%d')]:
        result.loc[mask] = pd.to_datetime(text.loc[mask],format=fmt,errors='coerce')
    if result.isna().any(): raise ValueError('Dates de validation invalides ou ambiguës : '+str(text.loc[result.isna()].head(5).tolist()))
    return result.dt.strftime('%Y-%m-%d')


def analyser_tranche(s):
    rows = []
    for value in s:
        m = re.fullmatch(r'\s*(\d{1,2})\s*H\s*-\s*(\d{1,2})\s*H\s*',str(value).upper())
        if not m: raise ValueError('Tranche horaire de validations non reconnue : '+str(value))
        a,b = map(int,m.groups())
        if not (0<=a<=47 and 0<=b<=48 and (b-a==1 or (a==23 and b==0))):
            raise ValueError('Tranche de validations différente d’une heure : '+str(value))
        h = a%24
        rows.append((h if h>=4 else h+24,f'{h:02d}h–{(h+1)%24:02d}h'))
    return pd.DataFrame(rows,index=s.index,columns=['HEURE_SERVICE','TRANCHE'])


def preparer(configs,interim,chunksize=50000):
    """Contrôle global des doublons inter-fichiers via index SQLite uniques."""
    d = Path(interim); d.mkdir(parents=True,exist_ok=True); db = d/'validations_j18.sqlite'
    if db.exists(): db.unlink()
    con = sqlite3.connect(db); sources = []; expected = {'FERRE':set(),'SURFACE':set()}
    try:
        con.execute('CREATE TABLE cells (RESEAU TEXT,ID_ENTITE TEXT,CLE_SOURCE TEXT,ID_REF TEXT,NOM TEXT,JOUR TEXT,TITRE TEXT,BORNE_INF REAL,BORNE_SUP REAL,NB_CENSURES INTEGER,NB_MANQUANTS INTEGER,NB_CINQ_PRUDENTS INTEGER)')
        con.execute('CREATE UNIQUE INDEX cell_key ON cells(RESEAU,CLE_SOURCE,JOUR,TITRE)')
        con.execute('CREATE TABLE profiles (RESEAU TEXT,ID_ENTITE TEXT,CLE_SOURCE TEXT,ID_REF TEXT,NOM TEXT,CAT_JOUR TEXT,HEURE_SERVICE INTEGER,TRANCHE TEXT,PCT_VALIDATIONS REAL,PERIODE_DEBUT TEXT,PERIODE_FIN TEXT)')
        con.execute('CREATE UNIQUE INDEX profile_key ON profiles(RESEAU,CLE_SOURCE,CAT_JOUR,HEURE_SERVICE,PERIODE_DEBUT,PERIODE_FIN)')
        for cfg in configs:
            kind = cfg['type']; reseau = 'FERRE' if kind.endswith('_FER') else 'SURFACE'
            if kind not in SOURCES: raise ValueError('Type de validations inconnu : '+kind)
            start,end = date.fromisoformat(cfg['debut']),date.fromisoformat(cfg['fin'])
            if start>end or (end-start).days>370: raise ValueError('Période de validations invalide ou supérieure à un an.')
            if kind.startswith('NB_'): expected[reseau] |= {str(start+timedelta(days=i)) for i in range((end-start).days+1)}
            count = 0
            for t in blocs(cfg,chunksize):
                grain = grains(t,reseau,cfg)
                if kind.startswith('NB_'):
                    grain['JOUR'] = parse_dates(champ(t,'JOUR',cfg=cfg)); grain['TITRE'] = champ(t,'TITRE',cfg=cfg)
                    if grain['TITRE'].eq('').any(): raise ValueError('Catégorie de titre absente dans les validations.')
                    if not grain['JOUR'].between(str(start),str(end)).all():
                        raise ValueError(Path(cfg['fichier']).name+' : dates hors de la période déclarée. Vérifier le contenu, pas seulement le titre du portail.')
                    v = valeurs(champ(t,'NB',cfg=cfg),cfg.get('cinq_numerique','BORNE_PRUDENTE'))
                    out = pd.concat([grain,v],axis=1)
                    try: out.to_sql('cells',con,if_exists='append',index=False)
                    except Exception as e:
                        if 'UNIQUE constraint' in str(e): raise ValueError('Validations dupliquées entre blocs/fichiers : même réseau, triplet STIF, jour et titre. Ne pas additionner des téléchargements qui se recouvrent.') from e
                        raise
                else:
                    grain['CAT_JOUR'] = champ(t,'CAT_JOUR',cfg=cfg)
                    if not grain['CAT_JOUR'].isin(JOURS).all(): raise ValueError('CAT_JOUR inconnu : '+str(sorted(set(grain['CAT_JOUR'])-set(JOURS))))
                    hs = analyser_tranche(champ(t,'TRANCHE',cfg=cfg))
                    pct = pd.to_numeric(champ(t,'PCT',cfg=cfg).str.replace(',','.',regex=False),errors='coerce')
                    if not pct.between(0,100).all(): raise ValueError('Profil horaire : pourcentage manquant ou hors de 0 à 100.')
                    out = pd.concat([grain,hs],axis=1); out['PCT_VALIDATIONS'] = pct
                    out['PERIODE_DEBUT'] = str(start); out['PERIODE_FIN'] = str(end)
                    try: out.to_sql('profiles',con,if_exists='append',index=False)
                    except Exception as e:
                        if 'UNIQUE constraint' in str(e): raise ValueError('Profil horaire dupliqué : choisir un seul fichier par série et période.') from e
                        raise
                count += len(t)
            sources.append({'fichier':Path(cfg['fichier']).name,'source':'Île-de-France Mobilités — '+kind,
                'type':kind,'periode_debut':str(start),'periode_fin':str(end),'nb_lignes_lues':count,
                'annee_donnees':start.year,'annee_geographie':'','date_telechargement':cfg.get('date_telechargement',''),
                'url':cfg.get('url',SOURCES[kind]),'sha256':sha256(cfg['fichier']),
                'cinq_numerique':cfg.get('cinq_numerique','BORNE_PRUDENTE')})
        # Un total et ses composantes ne sont jamais additionnés ensemble.
        titles = pd.read_sql_query('SELECT DISTINCT RESEAU,ID_ENTITE,TITRE FROM cells',con)
        titles['TOTAL'] = titles['TITRE'].map(normaliser).isin(['TOTAL','TOUS','TOUS_TITRES','TOTAL_TITRES','ALL'])
        mixed = titles.groupby(['RESEAU','ID_ENTITE'])['TOTAL'].agg(['any','all'])
        if (mixed['any'] & ~mixed['all']).any(): raise ValueError('Totaux de titres et catégories détaillées mélangés : choisir un seul niveau avant calcul.')
        daily = pd.read_sql_query('''SELECT RESEAU,ID_ENTITE,JOUR,SUM(BORNE_INF) VALIDATIONS_INF,
            CASE WHEN SUM(NB_MANQUANTS)=0 THEN SUM(BORNE_SUP) ELSE NULL END VALIDATIONS_SUP,
            SUM(NB_CENSURES) NB_CELLULES_CENSUREES,SUM(NB_MANQUANTS) NB_VALEURS_MANQUANTES,
            SUM(NB_CINQ_PRUDENTS) NB_CINQ_PRUDENTS,COUNT(*) NB_CELLULES_PUBLIEES
            FROM cells GROUP BY RESEAU,ID_ENTITE,JOUR''',con)
        entities = pd.read_sql_query('''SELECT RESEAU,ID_ENTITE,MAX(ID_REF) ID_REF,MIN(NOM) NOM,
            COUNT(DISTINCT CLE_SOURCE) NB_GRAINS_SOURCE FROM
            (SELECT RESEAU,ID_ENTITE,ID_REF,NOM,CLE_SOURCE FROM cells UNION ALL
             SELECT RESEAU,ID_ENTITE,ID_REF,NOM,CLE_SOURCE FROM profiles)
             GROUP BY RESEAU,ID_ENTITE''',con)
        profiles = pd.read_sql_query('SELECT * FROM profiles',con)
        if not profiles.empty:
            qa = profiles.groupby(['RESEAU','ID_ENTITE','CLE_SOURCE','CAT_JOUR','PERIODE_DEBUT','PERIODE_FIN']).agg(
                SOMME_POURCENTAGES=('PCT_VALIDATIONS','sum'),NB_TRANCHES=('HEURE_SERVICE','nunique')).reset_index()
            qa['STATUT'] = np.where(qa['SOMME_POURCENTAGES'].sub(100).abs().le(.5),'PROCHE_100','PROFIL_INCOMPLET_OU_A_VERIFIER')
            ecrire_csv(qa,d/'controle_profils_horaires_j18.csv')
        else: qa = pd.DataFrame()
        summaries = []
        for (net,entity),g in daily.groupby(['RESEAU','ID_ENTITE']):
            n = g['JOUR'].nunique(); unknown = int(g['NB_VALEURS_MANQUANTES'].sum())
            low = float(g['VALIDATIONS_INF'].sum()); high = float(g['VALIDATIONS_SUP'].sum()) if not unknown else np.nan
            summaries.append({'RESEAU':net,'ID_ENTITE':entity,'TOTAL_INF':low,'TOTAL_SUP':high,
                'MOYENNE_JOURS_PRESENTS_INF':low/n,'MOYENNE_JOURS_PRESENTS_SUP':high/n,
                'NB_JOURS_PRESENTS':n,'NB_JOURS_PERIODE':len(expected[net]),
                'COUVERTURE_JOURS_PCT':100*n/len(expected[net]) if expected[net] else np.nan,
                'NB_CELLULES_CENSUREES':int(g['NB_CELLULES_CENSUREES'].sum()),'NB_VALEURS_MANQUANTES':unknown,
                'DATE_MIN':g['JOUR'].min(),'DATE_MAX':g['JOUR'].max()})
        summary = entities.merge(pd.DataFrame(summaries,columns=['RESEAU','ID_ENTITE','TOTAL_INF','TOTAL_SUP',
            'MOYENNE_JOURS_PRESENTS_INF','MOYENNE_JOURS_PRESENTS_SUP','NB_JOURS_PRESENTS','NB_JOURS_PERIODE',
            'COUVERTURE_JOURS_PCT','NB_CELLULES_CENSUREES','NB_VALEURS_MANQUANTES','DATE_MIN','DATE_MAX']),
            on=['RESEAU','ID_ENTITE'],how='left',validate='one_to_one')
        if daily.empty and profiles.empty: raise ValueError('Aucune donnée de validation chargée.')
        return {'quotidien':daily,'profils':profiles,'synthese':summary,'sources':sources,'controle_profils':qa,
            'meta':{'actif':True,'jour_exploitation':'04:00 à 03:59 le lendemain, selon la documentation IDFM',
                'nb_entites':len(summary),'nb_jours_entites':len(daily),'nb_lignes_profils':len(profiles),
                'nb_jours_attendus_par_reseau':{k:len(v) for k,v in expected.items()},
                'comparaison_directe_gtfs':False,'profils_multiplies_par_volumes':False}}
    finally:
        con.close()


def rattacher_geographie(bundle,full,base,interim,localisation=None,correspondance_surface=None,routes=None):
    import geopandas as gpd
    s = bundle['synthese'].copy()
    s['CODGEO'] = ''; s['IRIS'] = ''; s['LONGITUDE'] = np.nan; s['LATITUDE'] = np.nan
    s['STATUT_GEO'] = np.where(s['RESEAU'].eq('SURFACE'),'VOLUME_A_LA_LIGNE_NON_LOCALISABLE_A_UN_ARRET','REFERENCE_GEOGRAPHIQUE_NON_FOURNIE')
    if localisation:
        cfg = localisation; p = Path(cfg['fichier'])
        ref = pd.read_csv(p,sep=cfg.get('sep',';'),dtype='string',keep_default_na=False,encoding='utf-8-sig')
        fields = [cfg['id'],cfg['x'],cfg['y']]
        if set(fields)-set(ref): raise ValueError('Référence des stations : champs absents '+str(set(fields)-set(ref)))
        ref['ID_REF'] = identifiant(ref[cfg['id']])
        if ref['ID_REF'].eq('').any() or ref['ID_REF'].duplicated().any(): raise ValueError('Référence des stations : identifiants absents/dupliqués. Fournir une correspondance univoque, pas un point par quai.')
        x = pd.to_numeric(ref[cfg['x']].str.replace(',','.',regex=False),errors='coerce')
        y = pd.to_numeric(ref[cfg['y']].str.replace(',','.',regex=False),errors='coerce')
        if x.isna().any() or y.isna().any() or not np.isfinite(x).all() or not np.isfinite(y).all(): raise ValueError('Coordonnées invalides dans la référence stations.')
        points = gpd.GeoDataFrame(ref[['ID_REF']],geometry=gpd.points_from_xy(x,y),crs=cfg['crs']).to_crs(2154)
        joined = gpd.sjoin(points,full[['IRIS','CODGEO','geometry']],how='left',predicate='within')
        if joined['ID_REF'].duplicated().any(): raise ValueError('Station dans plusieurs IRIS : vérifier les contours.')
        coords = points.to_crs(4326); joined['LONGITUDE'] = coords.geometry.x; joined['LATITUDE'] = coords.geometry.y
        idx = joined.set_index('ID_REF')
        fer = s['RESEAU'].eq('FERRE'); match = fer & s['ID_REF'].ne('') & s['ID_REF'].isin(idx.index)
        s.loc[fer,'STATUT_GEO'] = 'IDENTIFIANT_NON_APPARIE_A_LA_REFERENCE'
        for c in ['IRIS','CODGEO','LONGITUDE','LATITUDE']: s.loc[match,c] = s.loc[match,'ID_REF'].map(idx[c])
        s[['IRIS','CODGEO']] = s[['IRIS','CODGEO']].fillna('')
        s.loc[match,'STATUT_GEO'] = np.where(s.loc[match,'IRIS'].ne(''),'POINT_STATION_INTERIEUR_UNIQUE','POINT_HORS_CONTOURS_OU_FRONTIERE')
        bundle['sources'].append({'fichier':p.name,'source':'Référence géographique des stations de validation',
            'url':cfg.get('url',''),'sha256':sha256(p),'annee_donnees':cfg.get('annee',''),'annee_geographie':'',
            'date_telechargement':cfg.get('date_telechargement','')})
    bridge = pd.DataFrame(columns=['ID_ENTITE','ID_LINE','SOURCE_URL'])
    if correspondance_surface:
        bridge = pd.read_csv(correspondance_surface,sep=';',dtype='string',keep_default_na=False,encoding='utf-8-sig')
        if not {'ID_ENTITE','ID_LINE','SOURCE_URL'}.issubset(bridge): raise ValueError('Correspondance surface : ID_ENTITE, ID_LINE, SOURCE_URL requis.')
        if bridge[['ID_ENTITE','ID_LINE']].duplicated().any() or bridge['SOURCE_URL'].eq('').any(): raise ValueError('Correspondance surface dupliquée ou non sourcée.')
        if not bridge['ID_ENTITE'].isin(s.loc[s['RESEAU'].eq('SURFACE'),'ID_ENTITE']).all() or not bridge['ID_LINE'].isin(base['lignes']['ID_LINE']).all():
            raise ValueError('Correspondance surface : identifiant administratif ou commercial non reconnu.')
        # relation de contexte plusieurs-à-plusieurs ; aucun volume copié dans cette table.
        bundle['sources'].append({'fichier':Path(correspondance_surface).name,'source':'Correspondance documentée lignes administratives/commerciales',
            'url':'https://data.iledefrance-mobilites.fr/explore/dataset/referentiel-des-lignes/',
            'sha256':sha256(correspondance_surface),'annee_donnees':'','annee_geographie':'','date_telechargement':''})
    bundle['synthese'] = s; bundle['correspondance_surface'] = bridge
    ecrire_csv(s[['RESEAU','ID_ENTITE','ID_REF','NOM','STATUT_GEO','CODGEO','IRIS']],Path(interim)/'couverture_localisation_validations_j18.csv')
    ecrire_csv(s.loc[s['RESEAU'].eq('FERRE'),['ID_REF','NOM']].drop_duplicates(),Path(interim)/'identifiants_stations_a_localiser_j18.csv')
    return bundle


def correspondance_depuis_referentiel(bundle,fichier,base,interim,url):
    parts = list(blocs({'fichier':fichier},50000))
    ref = pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
    if not {'ID_LINE','ID_GROUPOFLINES'}.issubset(ref):
        raise ValueError('Le référentiel doit contenir ID_Line et ID_GroupOfLines. Un nom de ligne ne suffit pas.')
    ref['ID_ENTITE'] = 'GOL:'+identifiant(ref['ID_GROUPOFLINES'])
    ref['ID_LINE'] = identifiant(ref['ID_LINE'])
    wanted = set(bundle['synthese'].loc[bundle['synthese']['RESEAU'].eq('SURFACE'),'ID_ENTITE'])
    match = ref['ID_ENTITE'].isin(wanted) & ref['ID_LINE'].isin(base['lignes']['ID_LINE'])
    bridge = ref.loc[match,['ID_ENTITE','ID_LINE']].drop_duplicates().copy()
    bridge['SOURCE_URL'] = url
    out = Path(interim)/'correspondance_surface_depuis_referentiel_j18.csv'
    ecrire_csv(bridge,out)
    return out


def exporter(bundle,dossier):
    d = Path(dossier); files = []
    for key,name in [('quotidien','validations_quotidiennes.parquet'),('profils','profils_validations.parquet'),
                     ('synthese','validations_synthese.parquet'),('correspondance_surface','correspondance_surface_validations.parquet')]:
        bundle[key].to_parquet(d/name,index=False); files.append(name)
    return files
