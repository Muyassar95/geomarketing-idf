"""Exports J18 indépendants des manifestes J15a, J15b et J17."""
from pathlib import Path
from datetime import datetime, timezone
import json
import shutil

import pandas as pd

from scripts.preparer_gtfs_j18 import sha256, ecrire_csv, MODES
from scripts.geometries_j18 import exporter_geometries


def agreger_territoires(offre, arrets, base, creneaux, jour, qualite):
    local = offre.merge(arrets[['stop_id','IRIS','CODGEO','STATUT_GEO']],on='stop_id',how='left',validate='many_to_one')
    affecte = local.loc[local['STATUT_GEO'].eq('INTERIEUR_UNIQUE_IRIS')].copy()
    result = {}
    for niveau,key,table in [('COMMUNE','CODGEO',base['profil_communes']),('IRIS','IRIS',base['profil_iris'])]:
        blocks = []
        for w in creneaux.to_dict('records'):
            wrows = affecte.loc[affecte['CRENEAU'].eq(w['CRENEAU'])]
            for mode in [*MODES,'TOUS']:
                sub = wrows if mode=='TOUS' else wrows.loc[wrows['MODE'].eq(mode)]
                sums = sub.groupby(key).agg(NB_ARRETS_AVEC_DEPART=('stop_id','nunique'),
                    NB_LIGNES_GTFS=('route_id','nunique'),NB_DEPARTS_PROGRAMMES=('NB_DEPARTS_PROGRAMMES','sum'),
                    NB_DEPARTS_ESTIMES_CADENCE=('NB_DEPARTS_ESTIMES_CADENCE','sum')).reset_index()
                fields = [key]+(['CODGEO'] if niveau=='IRIS' else [])
                b = table[fields].merge(sums,on=key,how='left',validate='one_to_one')
                counts = ['NB_ARRETS_AVEC_DEPART','NB_LIGNES_GTFS','NB_DEPARTS_PROGRAMMES','NB_DEPARTS_ESTIMES_CADENCE']
                b[counts] = b[counts].fillna(0)
                for c in counts[:-1]: b[c] = b[c].astype('int64')
                b['DATE_SERVICE'] = str(jour); b['CRENEAU'] = w['CRENEAU']; b['MODE'] = mode
                b['DUREE_HEURES'] = w['DUREE_HEURES']
                b['DEPARTS_PROGRAMMES_PAR_HEURE'] = b['NB_DEPARTS_PROGRAMMES']/w['DUREE_HEURES']
                b['STATUT_OFFRE'] = ('HORAIRES_NON_RENSEIGNES_DANS_LE_FLUX' if qualite['NB_HEURES_NON_RENSEIGNEES']
                    else 'DEPARTS_RENSEIGNES_DU_FLUX')
                blocks.append(b)
        result[niveau] = pd.concat(blocks,ignore_index=True)
    return result,local


def dictionnaire():
    return pd.DataFrame([
        {'COLONNE':'NB_DEPARTS_PROGRAMMES','LIBELLE':'Départs programmés aux arrêts',
         'UNITE':'départs à un arrêt','DEFINITION':'Horaires publiés et cadences exact_times=1 dans [début, fin[, montées libres. Une course peut compter à plusieurs arrêts.'},
        {'COLONNE':'NB_DEPARTS_ESTIMES_CADENCE','LIBELLE':'Volume estimé des services en cadence',
         'UNITE':'équivalents de départs à un arrêt','DEFINITION':'Durée de recouvrement / headway_secs pour exact_times=0. Valeur distincte des départs programmés, sans horaires individuels inventés.'},
        {'COLONNE':'DEPARTS_PROGRAMMES_PAR_HEURE','LIBELLE':'Départs programmés par heure sur le créneau',
         'UNITE':'départs à un arrêt / heure','DEFINITION':'NB_DEPARTS_PROGRAMMES / durée du créneau. Ne mesure ni la régularité, ni le temps d’attente.'},
        {'COLONNE':'NB_ARRETS_AVEC_DEPART','LIBELLE':'Arrêts GTFS proposant un départ',
         'UNITE':'stop_id distincts','DEFINITION':'Quais/points d’arrêt physiques ; les quais d’une station restent distincts.'},
        {'COLONNE':'NB_LIGNES_GTFS','LIBELLE':'Lignes GTFS proposant un départ',
         'UNITE':'route_id distincts','DEFINITION':'Route IDs distincts sur le créneau. Les noms courts seuls ne servent jamais de clé.'},
        {'COLONNE':'VALIDATIONS_INF','LIBELLE':'Validations — valeur publiée ou borne basse',
         'UNITE':'validations / journée d’exploitation','DEFINITION':'Somme des valeurs et bornes basses des cellules publiées. Ne représente pas des voyageurs uniques.'},
        {'COLONNE':'VALIDATIONS_SUP','LIBELLE':'Validations — valeur publiée ou borne haute',
         'UNITE':'validations / journée d’exploitation','DEFINITION':'Somme des bornes hautes. Indisponible si une valeur manque ; aucune valeur censurée remplacée par une moyenne arbitraire.'},
        {'COLONNE':'PCT_VALIDATIONS','LIBELLE':'Part horaire publiée des validations',
         'UNITE':'%','DEFINITION':'Profil de la source par entité, série et type de jour. Pas de conversion automatique en volumes horaires.'},
    ])


def exporter(root, base_directory, views, traces, routes, stops, offre, profils,
             creneaux, jour, qualite, qualite_geo, qualite_traces, sources, perimetre, validations=None):
    root = Path(root); d = root/'data/app/j18'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    if (d/'manifest.json').is_file():
        backup = root/'data/interim/j18/sauvegardes_exports'/stamp
        backup.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(d,backup)
    d.mkdir(parents=True,exist_ok=True)
    exporter_geometries(views,traces,d)
    ecrire_csv(routes,d/'lignes_gtfs.csv')
    ecrire_csv(creneaux,d/'creneaux.csv')
    ecrire_csv(qualite_traces,d/'qualite_traces.csv')
    ecrire_csv(dictionnaire(),d/'dictionnaire.csv')
    stops.sort_values(['CODGEO','IRIS','stop_id']).to_parquet(d/'arrets_gtfs.parquet',index=False)
    offre.sort_values(['CODGEO','IRIS','CRENEAU','route_id']).to_parquet(d/'offre_arrets.parquet',index=False)
    for niveau,t in profils.items():
        t.sort_values(['CODGEO','CRENEAU','MODE']).to_parquet(d/('offre_'+niveau.lower()+'.parquet'),index=False)
    files = ['contours_iris.parquet','contours_communes.parquet','traces_gtfs.parquet','lignes_gtfs.csv',
             'creneaux.csv','qualite_traces.csv','dictionnaire.csv','arrets_gtfs.parquet','offre_arrets.parquet',
             'offre_commune.parquet','offre_iris.parquet']
    if validations is not None:
        from scripts.preparer_validations_j18 import exporter as exporter_validations
        files.extend(exporter_validations(validations,d))
    m = {'schema_version':1,'etape':'J18_GTFS_GEOMETRIES','generation_utc':datetime.now(timezone.utc).isoformat(),
        'base_manifest_sha256':sha256(Path(base_directory)/'manifest.json'),
        'date_service':str(jour),'fuseau':'Europe/Paris','type_journee':'JOURNEE_DE_SERVICE_GTFS',
        'geographie_iris':perimetre['geographie_iris'],'nb_communes':len(profils['COMMUNE']['CODGEO'].unique()),
        'nb_iris':len(profils['IRIS']['IRIS'].unique()),'creneaux':creneaux.to_dict('records'),
        'qualite_horaires':qualite,'qualite_contours':qualite_geo,
        'sources':sources+(validations['sources'] if validations is not None else []),
        'validations':validations['meta'] if validations is not None else {'actif':False},
        'geometries_affichage_seulement':True,
        'limites':[
            'GTFS : horaires théoriques du flux archivé. Validations observées IDFM distinctes ; aucune donnée de temps réel.',
            'Comptage par arrêt : ne pas interpréter les sommes territoriales comme des courses ou des voyageurs uniques.',
            'Créneaux exprimés dans la journée de service, pouvant dépasser 24 h ; pas de conversion en journée civile.',
            'Horaires intermédiaires absents non interpolés ; montées sur réservation et services flexibles hors du comptage.',
            'Cadences exact_times=0 séparées des départs programmés ; aucune heure fictive créée.',
            'Affectations territoriales par intérieur unique des contours complets ; frontières/coordonnées absentes restent non affectées.',
            'Contours améliorés pour l’affichage ; les indicateurs spatiaux J14 et les données J15b restent ceux de leurs traitements d’origine.',
            'Tracés conservés par forme/branche ; leur disponibilité et leur origine sont documentées par ligne.',
            'Validations ferrées au périmètre de station, surface au périmètre de ligne administrative. Aucune répartition des volumes de ligne entre arrêts ou IRIS.',
            'Les validations et les profils conservent leur période publiée ; aucun ratio d’occupation des véhicules déduit du GTFS d’une autre période.',
            'Les jours absents restent absents et les valeurs censurées sont traitées par bornes. La moyenne porte sur les jours renseignés.',
        ],
        'fichiers':[{'nom':n,'sha256':sha256(d/n),'octets':(d/n).stat().st_size} for n in files]}
    for r in m['fichiers']:
        if r['octets']>80_000_000:
            raise ValueError(r['nom']+' dépasse 80 Mo : répartir les exports avant publication, sans supprimer de territoires.')
    (d/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
    # Préparations conservées en Parquet ; diagnostics lisibles en CSV.
    processed = root/'data/processed/j18'; processed.mkdir(parents=True,exist_ok=True)
    for name in ['offre_commune.parquet','offre_iris.parquet','offre_arrets.parquet']:
        shutil.copy2(d/name,processed/name)
    ecrire_csv(pd.DataFrame(m['fichiers']),root/'data/interim/j18/fichiers_a_publier_j18.csv')
    return m


def controler_export(dossier, base_directory):
    d = Path(dossier); m = json.loads((d/'manifest.json').read_text(encoding='utf-8'))
    if m['etape']!='J18_GTFS_GEOMETRIES' or m['schema_version']!=1:
        raise ValueError('Manifeste J18 inconnu.')
    if m['base_manifest_sha256']!=sha256(Path(base_directory)/'manifest.json'):
        raise ValueError('J18 et J15a ne correspondent pas.')
    names = [r['nom'] for r in m['fichiers']]
    if len(names)!=len(set(names)): raise ValueError('Fichiers J18 dupliqués.')
    for row in m['fichiers']:
        name = row['nom']
        if Path(name).name!=name or '/' in name or '\\' in name:
            raise ValueError('Nom d’export J18 invalide.')
        p = d/name
        if sha256(p)!=row['sha256'] or p.stat().st_size!=row['octets']:
            raise ValueError('Export différent du manifeste : '+name)
    for niveau,key in [('commune','CODGEO'),('iris','IRIS')]:
        t = pd.read_parquet(d/('offre_'+niveau+'.parquet'))
        if t.duplicated([key,'CRENEAU','MODE']).any(): raise ValueError('Clés de l’offre dupliquées.')
        if t[key].nunique()!=m['nb_'+('communes' if niveau=='commune' else 'iris')]:
            raise ValueError('Couverture territoriale incomplète.')
        if not t[['NB_DEPARTS_PROGRAMMES','NB_DEPARTS_ESTIMES_CADENCE']].ge(0).all().all():
            raise ValueError('Offre négative.')
    if m.get('validations',{}).get('actif'):
        s = pd.read_parquet(d/'validations_synthese.parquet')
        v = pd.read_parquet(d/'validations_quotidiennes.parquet')
        p = pd.read_parquet(d/'profils_validations.parquet')
        if s.duplicated(['RESEAU','ID_ENTITE']).any() or v.duplicated(['RESEAU','ID_ENTITE','JOUR']).any():
            raise ValueError('Clés des validations dupliquées.')
        if len(s)!=m['validations']['nb_entites'] or len(v)!=m['validations']['nb_jours_entites'] or len(p)!=m['validations']['nb_lignes_profils']:
            raise ValueError('Dimensions des validations différentes du manifeste.')
        if not v['VALIDATIONS_INF'].ge(0).all() or (v['VALIDATIONS_SUP'].notna() & v['VALIDATIONS_SUP'].lt(v['VALIDATIONS_INF'])).any():
            raise ValueError('Bornes de validations incohérentes.')
        if s.loc[s['RESEAU'].eq('SURFACE'),['CODGEO','IRIS']].ne('').any().any():
            raise ValueError('Une ligne de surface ne doit pas recevoir une allocation territoriale de volume.')
        if not s['COUVERTURE_JOURS_PCT'].dropna().between(0,100).all():
            raise ValueError('Couverture des journées de validation hors limites.')
        if not p.empty and (not p['PCT_VALIDATIONS'].between(0,100).all() or p.duplicated(
            ['RESEAU','CLE_SOURCE','CAT_JOUR','HEURE_SERVICE','PERIODE_DEBUT','PERIODE_FIN']).any()):
            raise ValueError('Profils de validations incohérents.')
    return m
