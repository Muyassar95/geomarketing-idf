"""Horaires GTFS J18 : lecture bornée en mémoire et journée de service explicite."""
from pathlib import Path
from zipfile import ZipFile
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import csv
import hashlib
import math
import re
import sqlite3

import numpy as np
import pandas as pd

GTFS_URL = 'https://data.iledefrance-mobilites.fr/explore/dataset/offre-horaires-tc-gtfs-idfm/'
JOURS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
TYPES = {'0':'TRAM', '1':'METRO', '2':'TRAIN', '3':'BUS', '11':'BUS', '12':'TRAIN'}
MODES = {'TRAM':'Tramway', 'METRO':'Métro', 'TRAIN':'Train — réseau non distingué',
         'RER':'RER', 'TRANSILIEN':'Transilien', 'BUS':'Bus et trolleybus', 'AUTRE':'Autres modes'}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def ecrire_csv(table, path):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(p, index=False, sep=';', encoding='utf-8-sig')
    return p


class FluxGTFS:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError('Télécharger le ZIP GTFS et renseigner FICHIER_GTFS : '+str(path))
        with ZipFile(self.path) as z:
            self.membres = {}
            self.inventaire = []
            for i in z.infolist():
                if i.is_dir() or not i.filename.lower().endswith('.txt'):
                    continue
                name = Path(i.filename).name.lower()
                if name in self.membres:
                    raise ValueError('Plusieurs '+name+' dans le ZIP. Choisir un seul flux GTFS.')
                self.membres[name] = i.filename
                self.inventaire.append({'FICHIER':name,'OCTETS_DECOMPRESSES':i.file_size})
        absent = {'agency.txt','routes.txt','trips.txt','stops.txt','stop_times.txt'} - set(self.membres)
        if absent or not {'calendar.txt','calendar_dates.txt'} & set(self.membres):
            raise ValueError('Archive GTFS incomplète : '+str(sorted(absent))+' ; calendrier requis.')

    @contextmanager
    def ouvrir(self, name):
        with ZipFile(self.path) as z:
            with z.open(self.membres[name]) as f:
                yield f

    def colonnes(self, name):
        if name not in self.membres:
            return []
        with self.ouvrir(name) as f:
            return next(csv.reader([f.readline().decode('utf-8-sig')]))

    def lire(self, name, required=(), optional=(), chunksize=None):
        cols = self.colonnes(name)
        if not cols:
            return pd.DataFrame(columns=list(required)+list(optional))
        absent = set(required)-set(cols)
        if absent or len(cols) != len(set(cols)):
            raise ValueError(name+' : colonnes absentes/dupliquées : '+str(sorted(absent)))
        use = [c for c in list(required)+list(optional) if c in cols]
        if not use:
            use = cols
        if chunksize:
            def gen():
                with self.ouvrir(name) as f:
                    with pd.read_csv(f, usecols=use, dtype='string', encoding='utf-8-sig',
                                     keep_default_na=False, chunksize=chunksize) as reader:
                        for t in reader:
                            yield t
            return gen()
        with self.ouvrir(name) as f:
            t = pd.read_csv(f, usecols=use, dtype='string', encoding='utf-8-sig', keep_default_na=False)
        for c in optional:
            if c not in t:
                t[c] = ''
        return t


def uniques(t, cols, contexte):
    if t[list(cols)].eq('').any().any() or t[list(cols)].isna().any().any() or t.duplicated(list(cols)).any():
        raise ValueError(contexte+' : clés vides/dupliquées : '+str(cols))


def secondes(values, contexte, vides=True):
    s = values.astype('string').str.strip()
    valides = s.str.fullmatch(r'\d{1,3}:[0-5]\d:[0-5]\d', na=False)
    if ((s.ne('') & s.notna()) & ~valides).any() or (not vides and ~valides.all()):
        raise ValueError(contexte+' : heure GTFS invalide ; utiliser HH:MM:SS, y compris 25:00:00.')
    parts = s.where(valides).str.split(':', expand=True).reindex(columns=range(3))
    n = parts.apply(pd.to_numeric, errors='coerce')
    return (n[0]*3600+n[1]*60+n[2]).astype('Int64')


def date_gtfs(s):
    if not re.fullmatch(r'\d{8}', str(s)):
        raise ValueError('Date GTFS invalide : '+str(s))
    return datetime.strptime(str(s), '%Y%m%d').date()


def charger_calendriers(flux):
    c = flux.lire('calendar.txt', ['service_id',*JOURS,'start_date','end_date'])
    x = flux.lire('calendar_dates.txt', ['service_id','date','exception_type'])
    if not c.empty:
        uniques(c, ['service_id'], 'calendar.txt')
        if not c[JOURS].isin(['0','1']).all().all():
            raise ValueError('calendar.txt : jours attendus 0 ou 1.')
        c['DEBUT'] = c['start_date'].map(date_gtfs); c['FIN'] = c['end_date'].map(date_gtfs)
        if (c['DEBUT'] > c['FIN']).any():
            raise ValueError('calendar.txt : début après fin.')
    if not x.empty:
        uniques(x, ['service_id','date'], 'calendar_dates.txt')
        x['DATE'] = x['date'].map(date_gtfs)
        if not x['exception_type'].isin(['1','2']).all():
            raise ValueError('calendar_dates.txt : exception_type attendu 1 ou 2.')
    return c, x


def services_actifs(c, x, jour):
    d = date.fromisoformat(str(jour)) if not isinstance(jour, date) else jour
    actifs = set()
    if not c.empty:
        mask = (c['DEBUT'] <= d) & (c['FIN'] >= d) & c[JOURS[d.weekday()]].eq('1')
        actifs = set(c.loc[mask,'service_id'])
    if not x.empty:
        e = x.loc[x['DATE'].eq(d)]
        actifs -= set(e.loc[e['exception_type'].eq('2'),'service_id'])
        actifs |= set(e.loc[e['exception_type'].eq('1'),'service_id'])
    return actifs


def dates_disponibles(c, x, maximum=90):
    starts = ([] if c.empty else c['DEBUT'].tolist()) + ([] if x.empty else x['DATE'].tolist())
    ends = ([] if c.empty else c['FIN'].tolist()) + ([] if x.empty else x['DATE'].tolist())
    if not starts:
        raise ValueError('Aucune date de service dans le flux.')
    start, end = min(starts), max(ends)
    if (end-start).days+1 > maximum:
        raise ValueError('Flux couvrant plus de '+str(maximum)+' jours : augmenter MAX_JOURS_CALENDRIER explicitement.')
    return pd.DataFrame([{'DATE_SERVICE':str(start+timedelta(days=i)),
        'JOUR':JOURS[(start+timedelta(days=i)).weekday()],
        'NB_SERVICES_ACTIFS':len(services_actifs(c,x,start+timedelta(days=i)))}
        for i in range((end-start).days+1)])


def identifiant_commercial(value):
    s = str(value).strip()
    if re.fullmatch(r'C\d+',s):
        return s
    # Le suffixe est conservé à l'identique : aucun ajout de zéro à C0173.
    m = re.search(r'(?:^|:)\s*(C\d+):?$',s)
    return m.group(1) if m else ''


def preparer_routes(flux, reference, manuel=None):
    r = flux.lire('routes.txt',['route_id','route_type'],
        ['route_short_name','route_long_name','route_color','agency_id'])
    uniques(r,['route_id'],'routes.txt')
    ref = reference.set_index('ID_LINE')
    if not ref.index.is_unique:
        raise ValueError('Référentiel J15a : lignes dupliquées.')
    r['ID_LINE'] = r['route_id'].map(identifiant_commercial)
    r['STATUT_APPARIEMENT'] = np.where(r['ID_LINE'].isin(ref.index),'IDENTIFIANT_COMMERCIAL_RECONNU','NON_APPARIE')
    r.loc[~r['ID_LINE'].isin(ref.index),'ID_LINE'] = ''
    if manuel is not None:
        m = pd.read_csv(manuel,sep=';',dtype='string',keep_default_na=False,encoding='utf-8-sig')
        if not {'route_id','ID_LINE'}.issubset(m):
            raise ValueError('Correspondance manuelle : route_id et ID_LINE requis.')
        uniques(m,['route_id'],'Correspondance manuelle')
        if not m['route_id'].isin(r['route_id']).all() or not m['ID_LINE'].isin(ref.index).all():
            raise ValueError('Correspondance manuelle : identifiants hors du flux/référentiel.')
        index = m.set_index('route_id')['ID_LINE']; mask = r['route_id'].isin(index.index)
        r.loc[mask,'ID_LINE'] = r.loc[mask,'route_id'].map(index)
        r.loc[mask,'STATUT_APPARIEMENT'] = 'CORRESPONDANCE_MANUELLE'
    r['MODE'] = r['route_type'].map(TYPES).fillna('AUTRE')
    connu = r['ID_LINE'].ne('')
    modes_ref = r.loc[connu,'ID_LINE'].map(ref['MODE'])
    attendus = r.loc[connu,'route_type'].map(TYPES)
    compatibles = [(pd.isna(a) or a==b or (a=='TRAIN' and b in ['RER','TRANSILIEN','TRAIN']))
                   for a,b in zip(attendus,modes_ref)]
    if not all(compatibles):
        raise ValueError('Appariement route/mode incohérent : vérifier les versions et la table manuelle.')
    r.loc[connu,'MODE'] = modes_ref
    r['LIBELLE'] = r['route_long_name'].where(r['route_long_name'].ne(''),r['route_short_name'])
    r['LIBELLE'] = r['LIBELLE'].where(r['LIBELLE'].ne(''),r['route_id'])
    r.loc[connu,'LIBELLE'] = r.loc[connu,'ID_LINE'].map(ref['LIBELLE_LIGNE'])
    r['COULEUR'] = r['route_color'].map(lambda s:'#'+s if re.fullmatch(r'[a-fA-F0-9]{6}',str(s)) else '#526675')
    r.loc[connu,'COULEUR'] = r.loc[connu,'ID_LINE'].map(ref['COULEUR_WEB'])
    return r


def preparer_arrets(flux):
    s = flux.lire('stops.txt',['stop_id','stop_name'],['stop_lon','stop_lat','location_type','parent_station'])
    uniques(s,['stop_id'],'stops.txt')
    for col in ['stop_lon','stop_lat']:
        s[col] = pd.to_numeric(s[col],errors='coerce')
    s['COORDONNEES_VALIDES'] = s['stop_lon'].between(-180,180) & s['stop_lat'].between(-90,90)
    return s


def courses_actives(flux, services, routes, chunksize=100000):
    parts = []
    for t in flux.lire('trips.txt',['route_id','service_id','trip_id'],['shape_id','direction_id'],chunksize):
        t = t.loc[t['service_id'].isin(services)].copy()
        for col in ['shape_id','direction_id']:
            if col not in t: t[col] = ''
        if not t.empty: parts.append(t)
    t = pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=['route_id','service_id','trip_id','shape_id','direction_id'])
    uniques(t,['trip_id'],'trips actifs')
    if t.empty:
        raise ValueError('Aucune course active à cette date : choisir une date proposée.')
    if not t['route_id'].isin(routes['route_id']).all():
        raise ValueError('Course active sans route correspondante.')
    if not t['direction_id'].isin(['','0','1']).all():
        raise ValueError('direction_id attendu vide, 0 ou 1.')
    return t


def frequences_actives(flux, trips):
    f = flux.lire('frequencies.txt',['trip_id','start_time','end_time','headway_secs'],['exact_times'])
    if f.empty: return f
    f = f.loc[f['trip_id'].isin(trips['trip_id'])].copy()
    if f.empty: return f
    uniques(f,['trip_id','start_time'],'frequencies actifs')
    f['START'] = secondes(f['start_time'],'frequencies start_time',False)
    f['END'] = secondes(f['end_time'],'frequencies end_time',False)
    f['HEADWAY'] = pd.to_numeric(f['headway_secs'],errors='coerce')
    f['EXACT'] = f['exact_times'].replace('','0')
    if (f['HEADWAY'].isna() | f['HEADWAY'].le(0) | f['HEADWAY'].mod(1).ne(0)).any() or not f['EXACT'].isin(['0','1']).all() or f['END'].le(f['START']).any():
        raise ValueError('frequencies.txt : cadence, bornes ou exact_times invalides.')
    for _,g in f.sort_values('START').groupby('trip_id'):
        if any(b>a for b,a in zip(g['END'].iloc[:-1],g['START'].iloc[1:])):
            raise ValueError('Plages de fréquences chevauchantes pour '+str(g.iloc[0]['trip_id']))
    return f


def importer_horaires(flux, trips, stops, frequences, db, chunksize=100000, progres=print):
    """Les horaires actifs sont stockés sur disque ; pas de concat national en RAM."""
    p = Path(db); p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists(): p.unlink()
    con = sqlite3.connect(p)
    try:
        con.execute('PRAGMA temp_store=FILE')
        con.execute('PRAGMA cache_size=-32000')
        trips[['trip_id','route_id','direction_id']].to_sql('trips',con,index=False)
        con.execute('CREATE UNIQUE INDEX idx_trips ON trips(trip_id)')
        con.execute('CREATE TABLE events (trip_id TEXT,stop_id TEXT,seq INTEGER,dep INTEGER,pickup TEXT,timepoint TEXT)')
        ids = set(trips['trip_id']); stop_ids = set(stops['stop_id'])
        physiques = set(stops.loc[stops['location_type'].isin(['','0']),'stop_id'])
        n_all = n_kept = n_missing = n_restreint = 0
        required = ['trip_id','stop_id','stop_sequence','departure_time']
        for i,t in enumerate(flux.lire('stop_times.txt',required,['pickup_type','timepoint'],chunksize),1):
            n_all += len(t); t = t.loc[t['trip_id'].isin(ids)].copy()
            if t.empty: continue
            if not t['stop_id'].isin(stop_ids).all() or not t['stop_id'].isin(physiques).all():
                raise ValueError('Horaires actifs : arrêt absent, non physique ou service flexible non pris en charge.')
            seq = pd.to_numeric(t['stop_sequence'],errors='coerce')
            if (seq.isna() | seq.lt(0) | seq.mod(1).ne(0)).any():
                raise ValueError('stop_sequence invalide dans les horaires actifs.')
            dep = secondes(t['departure_time'],'stop_times departure_time')
            pickup = t['pickup_type'].replace('','0') if 'pickup_type' in t else pd.Series('0',index=t.index)
            if not pickup.isin(['0','1','2','3']).all():
                raise ValueError('pickup_type GTFS invalide.')
            timepoint = t['timepoint'].replace('','1') if 'timepoint' in t else pd.Series('1',index=t.index)
            if not timepoint.isin(['0','1']).all(): raise ValueError('timepoint GTFS invalide.')
            out = pd.DataFrame({'trip_id':t['trip_id'],'stop_id':t['stop_id'],'seq':seq.astype(int),
                'dep':dep,'pickup':pickup,'timepoint':timepoint})
            out.to_sql('events',con,if_exists='append',index=False)
            n_kept += len(t); n_missing += int(dep.isna().sum()); n_restreint += int(pickup.ne('0').sum())
            if i % 10 == 0: progres(f'Horaires lus : {n_all:,} ; actifs conservés sur disque : {n_kept:,}')
        con.execute('CREATE INDEX idx_events_trip ON events(trip_id,seq)')
        if con.execute('SELECT 1 FROM events GROUP BY trip_id,seq HAVING COUNT(*)>1 LIMIT 1').fetchone():
            raise ValueError('Doublon de trip_id/stop_sequence dans stop_times actifs.')
        if con.execute('SELECT 1 FROM trips t LEFT JOIN events e USING(trip_id) WHERE e.trip_id IS NULL LIMIT 1').fetchone():
            raise ValueError('Une course active ne possède aucun horaire.')
        if con.execute('''SELECT 1 FROM (SELECT dep,LAG(dep) OVER(PARTITION BY trip_id ORDER BY seq) prev
              FROM events WHERE dep IS NOT NULL) WHERE dep<prev LIMIT 1''').fetchone():
            raise ValueError('Horaires décroissants : utiliser des heures GTFS après 24 h, sans revenir à 00 h.')
        con.execute('CREATE TABLE bases AS SELECT e.trip_id,e.dep base FROM events e JOIN '
                    '(SELECT trip_id,MIN(seq) seq FROM events GROUP BY trip_id) m USING(trip_id,seq)')
        con.execute('CREATE UNIQUE INDEX idx_bases ON bases(trip_id)')
        freq_ids = set() if frequences.empty else set(frequences['trip_id'])
        pd.DataFrame({'trip_id':pd.Series(sorted(freq_ids),dtype='string')}).to_sql('freq_ids',con,index=False)
        if freq_ids:
            bases = dict(con.execute('SELECT trip_id,base FROM bases'))
            if any(bases.get(t) is None for t in freq_ids):
                raise ValueError('Course en cadence sans heure au premier arrêt : calcul des décalages impossible.')
        con.commit()
        return {'NB_LIGNES_STOP_TIMES_LUES':n_all,'NB_HORAIRES_ACTIFS':n_kept,
                'NB_HEURES_NON_RENSEIGNEES':n_missing,'NB_MONTEES_NON_LIBRES':n_restreint,
                'NB_COURSES_EN_CADENCE':len(freq_ids)}
    finally:
        con.close()


def valider_creneaux(creneaux):
    rows = []
    for nom,a,b in creneaux:
        start = int(secondes(pd.Series([a]),str(nom),False).iloc[0])
        end = int(secondes(pd.Series([b]),str(nom),False).iloc[0])
        if end <= start: raise ValueError('Créneau '+nom+' : fin après début, par exemple 26:00:00 après minuit.')
        rows.append({'CRENEAU':nom,'DEBUT':a,'FIN':b,'START':start,'END':end,'DUREE_HEURES':(end-start)/3600})
    t = pd.DataFrame(rows)
    if t.empty or t['CRENEAU'].duplicated().any(): raise ValueError('Créneaux vides/dupliqués.')
    return t


def compter_depart_cadence(start,end,headway,offset,a,b,exact):
    lo,hi = max(start,a-offset), min(end,b-offset)
    if hi <= lo: return 0.0
    if not exact: return (hi-lo)/headway
    first = max(0,math.ceil((lo-start)/headway))
    last_excluded = math.ceil((hi-start)/headway)
    return float(max(0,last_excluded-first))


def compter_offre(db, freq, creneaux, routes, jour):
    con = sqlite3.connect(db); parts = []
    try:
        for w in creneaux.to_dict('records'):
            normal = pd.read_sql_query('''SELECT e.stop_id,t.route_id,t.direction_id,COUNT(*) NB_DEPARTS_PROGRAMMES,
                0.0 NB_DEPARTS_ESTIMES_CADENCE FROM events e JOIN trips t USING(trip_id)
                LEFT JOIN freq_ids f USING(trip_id) WHERE f.trip_id IS NULL AND e.pickup='0'
                AND e.dep>=? AND e.dep<? GROUP BY e.stop_id,t.route_id,t.direction_id''',con,
                params=[w['START'],w['END']])
            sub = [normal]
            if not freq.empty:
                # Seules les courses en cadence sont parcourues ici, sans créer d'horaires fictifs.
                fidx = {k:g for k,g in freq.groupby('trip_id')}
                aggregated = {}
                cur = con.execute('''SELECT e.trip_id,e.stop_id,t.route_id,t.direction_id,e.dep-b.base
                    FROM events e JOIN freq_ids f USING(trip_id) JOIN trips t USING(trip_id)
                    JOIN bases b USING(trip_id) WHERE e.pickup='0' AND e.dep IS NOT NULL''')
                for trip,stop,route,direction,offset in cur:
                    key = (stop,route,direction); v = aggregated.setdefault(key,[0.,0.])
                    for r in fidx[trip].itertuples():
                        n = compter_depart_cadence(int(r.START),int(r.END),int(r.HEADWAY),offset,
                                                 w['START'],w['END'],r.EXACT=='1')
                        v[0 if r.EXACT=='1' else 1] += n
                extra = pd.DataFrame([{'stop_id':k[0],'route_id':k[1],'direction_id':k[2],
                    'NB_DEPARTS_PROGRAMMES':int(v[0]),'NB_DEPARTS_ESTIMES_CADENCE':v[1]}
                    for k,v in aggregated.items() if sum(v)>0])
                if not extra.empty: sub.append(extra)
            combined = pd.concat(sub,ignore_index=True)
            if combined.empty: continue
            combined = combined.groupby(['stop_id','route_id','direction_id'],as_index=False)[
                ['NB_DEPARTS_PROGRAMMES','NB_DEPARTS_ESTIMES_CADENCE']].sum()
            combined['CRENEAU'] = w['CRENEAU']; combined['DATE_SERVICE'] = str(jour)
            combined['DUREE_HEURES'] = w['DUREE_HEURES']; parts.append(combined)
        cols = ['stop_id','route_id','direction_id','NB_DEPARTS_PROGRAMMES','NB_DEPARTS_ESTIMES_CADENCE',
                'CRENEAU','DATE_SERVICE','DUREE_HEURES']
        out = pd.concat(parts,ignore_index=True) if parts else pd.DataFrame(columns=cols)
        out = out.merge(routes[['route_id','ID_LINE','MODE','LIBELLE','COULEUR']],on='route_id',validate='many_to_one')
        out['NB_DEPARTS_PROGRAMMES'] = out['NB_DEPARTS_PROGRAMMES'].astype('int64')
        out['DEPARTS_PROGRAMMES_PAR_HEURE'] = out['NB_DEPARTS_PROGRAMMES']/out['DUREE_HEURES']
        return out
    finally:
        con.close()
