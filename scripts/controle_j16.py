"""Contrôles J16 : lecture des exports, explications en français et rapports.

Ce module ne réécrit aucun fichier J15a/J15b et ne valide aucun indicateur.
"""
from pathlib import Path
import csv
import hashlib
import html
import json
import math
import re
import unicodedata
from datetime import datetime, timezone

import numpy as np
import pandas as pd

VERSION = '2026-10-22-v1'
DEPARTEMENTS = {'75','77','78','91','92','93','94','95'}
MANQUANTS = {'','s','ss','nd','n.d.','n.d','nan','na','n/a','null','none','-','--','///','...','…'}
MODES = {'METRO','RER','TRANSILIEN','TRAM','BUS'}
REQUIS_A = {'profil_communes.csv','profil_iris.csv','arrets.csv','lignes.csv','relations.csv',
            'restaurants.csv','sources.csv','communes_idf.geojson','iris_idf.geojson',
            'traces_idf.geojson','iris_focus.geojson','traces_focus.geojson'}
CHAMPS_CATALOGUE = {'ID','NIVEAU','COLONNE','LIBELLE','THEME','TYPE','UNITE','ANNEE',
    'GEOGRAPHIE','SOURCE','DEFINITION','AGREGATION','NUMERATEUR','DENOMINATEUR','FACTEUR',
    'VALIDE','METADONNEES','FICHIER_SOURCE','NB_PRESENTES','NB_LIGNES','COUVERTURE_PCT'}
RESULTATS = {'OK':'OK', 'A_VERIFIER':'À vérifier', 'BLOQUANT':'À corriger', 'NON_TESTE':'Non testé'}
CHAMPS_BILAN = ['BLOC','CONTROLE','STATUT','RESULTAT','NB_CONCERNES','EXPLICATION','ACTION']


def empreinte(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):
            h.update(part)
    return h.hexdigest()


def lire_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        first = f.readline()
        sep = max((len(next(csv.reader([first],delimiter=d))),d) for d in [',',';','\t'])[1]
        f.seek(0)
        reader = csv.reader(f,delimiter=sep,strict=True)
        cols = next(reader)
        if not cols or len(set(cols)) != len(cols) or any(not x.strip() for x in cols):
            raise ValueError('En-tête vide ou colonnes dupliquées.')
        for row in reader:
            if row and len(row) != len(cols):
                raise ValueError(f'Ligne {reader.line_num} : nombre de champs différent de l’en-tête.')
    return pd.read_csv(path,sep=sep,dtype='string',encoding='utf-8-sig',keep_default_na=False)


def nombre(serie):
    s = serie.astype('string').str.strip()
    absent = s.isna() | s.str.lower().isin(MANQUANTS)
    text = s.str.replace('\u202f','',regex=False).str.replace('\u00a0','',regex=False)
    text = text.str.replace(' ','',regex=False).str.replace(',','.',regex=False)
    n = pd.to_numeric(text.where(~absent),errors='coerce').astype(float)
    mauvais = ~absent & (n.isna() | ~np.isfinite(n))
    return n.where(~mauvais), mauvais, absent


def texte_simple(value):
    return unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().lower()


def regle_prudente(colonne, theme=''):
    """Les évolutions, écarts et indices ne sont pas bornés à 100 %."""
    c = re.sub(r'^J\d{1,2}[A-Z]{0,2}_','',str(colonne).upper())
    if theme == 'TECHNIQUE' or re.search(r'(^|_)(CODE|CODGEO|IRIS|ANNEE|MILLESIME|SOURCE)(_|$)',c):
        return 'LECTURE_NUMERIQUE'
    if any(x in c for x in ['EVOL','ECART','VARIATION','CROISS','SOLDE','INDICE','RANG','POSITION','SCORE']):
        return 'LECTURE_NUMERIQUE'
    if (re.search(r'(^|_)PART_',c) and c.endswith('_PCT')) or c in {'PAUVRETE_PCT','PART_1529_PCT'} or c.startswith('SURFACE_') and c.endswith('_PCT'):
        return 'PART_0_100'
    if c.startswith(('TAUX_PAUVRETE','TAUX_CHOMAGE','TAUX_ACTIVITE','TAUX_EMPLOI','TAUX_SCOLARISATION')) and c.endswith('_PCT'):
        return 'PART_0_100'
    if c.startswith(('NB_','POP_','POPULATION','DENSITE_','DIST_','ARRETS_','LIGNES_','OBS_')) or c in {'RESTAURANTS','RAPIDES','MEDIANE_UC','MOBPRO_ENTRANTS','MOBPRO_SORTANTS'}:
        return 'VALEUR_POSITIVE'
    return 'LECTURE_NUMERIQUE'


def choisir_dossiers(racine, j15a='', j15b=''):
    racine = Path(racine).resolve()
    def chemin(v):
        p = Path(v)
        return (p if p.is_absolute() else racine/p).resolve()
    candidats_b = [chemin(j15b)] if j15b else [racine/'data/app/j15b',racine/'app/data/app/j15b']
    detail = next((p for p in candidats_b if (p/'manifest.json').is_file()),candidats_b[0])
    base = chemin(j15a) if j15a else detail.parent/'j15'
    return base, detail


class ControleJ16:
    def __init__(self,racine,j15a,j15b,focus=('95127','95500')):
        self.racine = Path(racine).resolve()
        self.base, self.detail = Path(j15a).resolve(), Path(j15b).resolve()
        self.focus = list(map(str,focus))
        self.interim = self.racine/'data/interim/j16'
        self.rapports = self.racine/'outputs/rapports/j16'
        self.controles, self.inventaire, self.anomalies = [], [], []
        self.documentation, self.couverture, self.calculs = [], [], []
        self.fiables, self.instantane = set(), {}
        self.manifestes, self.tables, self.catalogue = {}, {}, None
        self.compatibilite = pd.DataFrame()
        self.selection, self.manuels = pd.DataFrame(), pd.DataFrame()
        self.etapes = set()

    def noter(self,bloc,controle,statut,explication,action='',nb=0):
        self.controles.append(dict(BLOC=bloc,CONTROLE=controle,STATUT=statut,
            RESULTAT=RESULTATS[statut],NB_CONCERNES=int(nb),EXPLICATION=explication,ACTION=action))

    def bilan(self,bloc=None):
        t = pd.DataFrame(self.controles,columns=CHAMPS_BILAN)
        return t if bloc is None else t.loc[t['BLOC'].eq(bloc)].copy()

    def afficher(self,bloc=None):
        return self.bilan(bloc)[['CONTROLE','RESULTAT','NB_CONCERNES','EXPLICATION','ACTION']].rename(columns={
            'CONTROLE':'Contrôle','RESULTAT':'Résultat','NB_CONCERNES':'Nombre concerné',
            'EXPLICATION':'Ce que cela signifie','ACTION':'Action à faire'})

    def _lire(self,dossier,nom):
        p = Path(dossier)/nom
        if p not in self.fiables:
            self.noter('LECTURE',nom,'NON_TESTE','Ce fichier n’a pas passé le contrôle de présence et d’empreinte.','Corriger le lot d’exports avant de l’analyser.')
            return None
        try:
            return lire_csv(p)
        except (OSError,ValueError,csv.Error,pd.errors.ParserError) as e:
            self.noter('LECTURE',nom,'BLOQUANT',str(e),'Réexporter ce fichier depuis son notebook de préparation.',1)
            return None

    def verifier_fichiers(self):
        self.etapes.add('fichiers')
        for cle,dossier,version,etape in [('J15A',self.base,2,'J15A_APPLICATION'),('J15B',self.detail,1,'J15B_INDICATEURS_PDF')]:
            p = dossier/'manifest.json'
            try:
                m = json.loads(p.read_text(encoding='utf-8-sig'))
                if m.get('schema_version') != version or m.get('etape') != etape:
                    raise ValueError(f'{cle} : version attendue {version}, étape attendue {etape}.')
                entries = m.get('fichiers',[])
                noms = [r['nom'] for r in entries]
                requis = REQUIS_A if cle == 'J15A' else {'catalogue.csv'}
                if len(set(noms)) != len(noms) or not requis <= set(noms):
                    raise ValueError('Liste des fichiers incomplète ou dupliquée : '+str(sorted(requis-set(noms))))
                self.manifestes[cle] = m
                self.instantane[p] = empreinte(p)
                self.noter('FICHIERS',cle+' : manifeste','OK',f'Le manifeste décrit {len(entries)} fichiers. Les versions J15a et J15b sont volontairement différentes.')
                erreurs = 0
                for r in entries:
                    nom = r['nom']
                    if not nom or Path(nom).name != nom or '/' in nom or '\\' in nom:
                        raise ValueError('Nom de fichier non local dans le manifeste.')
                    q = dossier/nom
                    conforme = q.is_file() and q.resolve().parent == dossier and empreinte(q) == r['sha256']
                    if conforme and 'octets' in r:
                        conforme = q.stat().st_size == r['octets']
                    if conforme:
                        self.fiables.add(q)
                        self.instantane[q] = r['sha256']
                    else:
                        erreurs += 1
                    self.inventaire.append({'LOT':cle,'FICHIER':nom,'EXISTE':q.is_file(),
                        'TAILLE_MO':round(q.stat().st_size/1_000_000,3) if q.is_file() else None,
                        'EMPREINTE_CONFORME':conforme})
                self.noter('FICHIERS',cle+' : fichiers du lot','BLOQUANT' if erreurs else 'OK',
                    f'{erreurs} fichier(s) absent(s) ou différent(s) du manifeste.' if erreurs else 'Chaque fichier correspond exactement à la version décrite par son manifeste.',
                    'Republier le lot cohérent complet ; ne pas changer les empreintes pour masquer l’erreur.' if erreurs else '',erreurs)
            except (OSError,ValueError,KeyError,TypeError) as e:
                self.noter('FICHIERS',cle+' : accès aux exports','BLOQUANT',str(e),'Vérifier le chemin affiché et régénérer les exports concernés.',1)
        if {'J15A','J15B'} <= self.manifestes.keys():
            ok = self.manifestes['J15B'].get('base_manifest_sha256') == empreinte(self.base/'manifest.json')
            self.noter('FICHIERS','Synchronisation J15a et J15b','OK' if ok else 'BLOQUANT',
                'Les indicateurs détaillés utilisent bien la base cartographique choisie.' if ok else 'J15b a été généré avec un autre manifeste J15a.',
                '' if ok else 'Régénérer J15b avec ce J15a puis réappliquer les correctifs de libellés.',0 if ok else 1)
        return self.afficher('FICHIERS')

    def _codes(self,t,col,longueur,libelle):
        if col not in t:
            self.noter('TERRITOIRES',libelle,'BLOQUANT',f'La colonne {col} manque.','Reprendre l’export.',1)
            return False
        mauvais = ~t[col].str.fullmatch(r'\d{'+str(longueur)+'}',na=False) | ~t[col].str[:2].isin(DEPARTEMENTS)
        doublons = t[col].duplicated(keep=False)
        n = int((mauvais|doublons).sum())
        self.noter('TERRITOIRES',libelle,'BLOQUANT' if n else 'OK',
            f'{len(t)} lignes ; {n} codes invalides, hors IDF ou répétés.',
            'Vérifier la clé géographique et conserver les codes comme du texte.' if n else '',n)
        return n == 0

    def verifier_territoires(self):
        self.etapes.add('territoires')
        for key in ['profil_communes','profil_iris','arrets','lignes','relations','restaurants','sources']:
            t = self._lire(self.base,key+'.csv')
            if t is not None:
                self.tables[key] = t
        for key,col,longueur,nombre_lignes in [('profil_communes','CODGEO',5,'nb_communes'),('profil_iris','IRIS',9,'nb_iris')]:
            t = self.tables.get(key)
            if t is None:
                continue
            self._codes(t,col,longueur,key+' : codes')
            attendu = self.manifestes.get('J15A',{}).get(nombre_lignes)
            ok = len(t) == attendu
            self.noter('TERRITOIRES',key+' : nombre de territoires','OK' if ok else 'BLOQUANT',
                f'{len(t)} lignes lues ; {attendu} annoncées par le manifeste.','Vérifier le lot utilisé.' if not ok else '',0 if ok else 1)
        c,i = self.tables.get('profil_communes'),self.tables.get('profil_iris')
        if c is not None and i is not None and 'CODGEO' in c and 'CODGEO' in i:
            n = int((~i['CODGEO'].isin(c['CODGEO'])).sum())
            self.noter('TERRITOIRES','Rattachement des IRIS aux communes','BLOQUANT' if n else 'OK',
                f'{n} IRIS rattaché(s) à une commune absente du profil.',
                'Vérifier les communes de contexte, notamment Paris et les fusions.' if n else '',n)
        if c is not None and 'CODGEO' in c:
            absent = sorted(set(self.focus)-set(c['CODGEO']))
            self.noter('TERRITOIRES','Communes de démonstration','A_VERIFIER' if absent else 'OK',
                'Communes absentes : '+', '.join(absent) if absent else 'Cergy et Pontoise sont présentes dans le profil.',
                'Adapter FOCUS ou reprendre la couverture géographique.' if absent else '',len(absent))
        return self.afficher('TERRITOIRES')

    def verifier_catalogue(self):
        self.etapes.add('catalogue')
        cat = self._lire(self.detail,'catalogue.csv')
        if cat is None:
            return self.afficher('CATALOGUE')
        manque = CHAMPS_CATALOGUE-set(cat)
        if manque:
            self.noter('CATALOGUE','Structure du catalogue','BLOQUANT','Champs absents : '+', '.join(sorted(manque)),'Reprendre la génération J15b.',len(manque))
            return self.afficher('CATALOGUE')
        self.catalogue = cat
        n = int((cat['ID'].duplicated(keep=False)|cat[['NIVEAU','COLONNE']].duplicated(keep=False)).sum())
        n += int((~cat['NIVEAU'].isin(['COMMUNE','IRIS'])|~cat['TYPE'].isin(['NUMERIQUE','TEXTE'])|~cat['VALIDE'].isin(['OUI','NON'])).sum())
        self.noter('CATALOGUE','Identifiants et structure','BLOQUANT' if n else 'OK',
            f'{len(cat)} variables ; {n} ligne(s) avec identifiant répété ou valeur de structure invalide.',
            'Vérifier les ID, niveaux, types et statuts.' if n else '',n)
        nb = self.manifestes.get('J15B',{}).get('nb_variables')
        self.noter('CATALOGUE','Nombre de variables','OK' if len(cat)==nb else 'BLOQUANT',
            f'{len(cat)} variables dans le catalogue ; {nb} dans le manifeste.','Régénérer J15b.' if len(cat)!=nb else '',int(len(cat)!=nb))
        problemes_label, incomplets, valides_incomplets = 0,0,0
        for row in cat.to_dict('records'):
            obligatoire = ['LIBELLE','ANNEE','GEOGRAPHIE','SOURCE','DEFINITION']
            numerique_metier = row['TYPE']=='NUMERIQUE' and row['THEME']!='TECHNIQUE'
            if numerique_metier:
                obligatoire.append('UNITE')
            absents = [k for k in obligatoire if not row[k].strip() or row[k].strip().lower() in MANQUANTS
                       or texte_simple(row[k]).strip() in {'non precise','non renseigne','a documenter','a verifier'}]
            vague = numerique_metier and any(x in texte_simple(row['UNITE']) for x in ['a preciser','a verifier','a confirmer','non renseigne'])
            if vague:
                absents.append('UNITE_A_PRECISER')
            lib = row['LIBELLE']
            motifs = []
            if re.search(r'(?<![A-Za-z0-9])J\d{1,2}[A-Za-z]{0,2}(?![A-Za-z0-9])',lib):
                motifs.append('Préfixe d’étape encore visible')
            if re.search(r'\bans\s+ans\b',lib,re.I):
                motifs.append('Mot « ans » répété')
            compact = re.search(r'\b(0014|1524|1529|1564|1824|2549|3044|4559|6074|7589)\b',lib)
            if compact and compact.group() in row['COLONNE']:
                motifs.append('Âge encore écrit sous forme compacte')
            if '_' in lib or texte_simple(lib).replace(' ','') == texte_simple(row['COLONNE']).replace('_',''):
                motifs.append('Libellé proche du code technique : relire')
            if motifs:
                problemes_label += 1
            if absents:
                incomplets += 1
                if row['VALIDE']=='OUI':
                    valides_incomplets += 1
            self.documentation.append({'ID':row['ID'],'NIVEAU':row['NIVEAU'],'COLONNE':row['COLONNE'],
                'LIBELLE':lib,'THEME':row['THEME'],'VALIDE':row['VALIDE'],
                'CHAMPS_A_COMPLETER':' ; '.join(absents),'LIBELLE_A_RELIRE':' ; '.join(motifs),
                'DOCUMENTATION_COMPLETE':not absents})
        self.noter('CATALOGUE','Libellés compréhensibles','A_VERIFIER' if problemes_label else 'OK',
            f'{problemes_label} libellé(s) à relire selon les règles de présentation.',
            'Consulter documentation_indicateurs_j16.csv ; appliquer le correctif J15b puis relire les libellés concernés.' if problemes_label else 'Relire également les indicateurs choisis pour la démonstration.',problemes_label)
        self.noter('CATALOGUE','Sources, années, définitions et unités','A_VERIFIER' if incomplets else 'OK',
            f'{incomplets} variable(s) avec documentation incomplète ou unité à préciser.',
            'Compléter en priorité les indicateurs qui seront présentés publiquement.' if incomplets else '',incomplets)
        self.noter('CATALOGUE','Indicateurs marqués validés','BLOQUANT' if valides_incomplets else 'OK',
            f'{valides_incomplets} indicateur(s) marqué(s) OUI avec une documentation incomplète.',
            'Compléter la documentation ou réviser le statut de validation dans les corrections J15b.' if valides_incomplets else '',valides_incomplets)
        return self.afficher('CATALOGUE')

    def _valeurs(self,t,col,codes,bloc,level='',theme=''):
        n,bad,absent = nombre(t[col])
        regle = regle_prudente(col,theme)
        hors = n.notna() & ((n < -1e-8)|(n > 100+1e-8)) if regle=='PART_0_100' else (n < -1e-8 if regle=='VALEUR_POSITIVE' else pd.Series(False,index=t.index))
        for motif,mask in [('Valeur non numérique ou infinie',bad),('Valeur hors des bornes attendues',hors)]:
            if mask.any():
                self.anomalies.append({'BLOC':bloc,'NIVEAU':level,'COLONNE':col,'REGLE':regle,
                    'PROBLEME':motif,'NB_LIGNES':int(mask.sum()),
                    'EXEMPLES_CODES':', '.join(codes.loc[mask].astype(str).head(10))})
        return n,bad,absent,regle,int(bad.sum()+hors.sum())

    def verifier_valeurs_detaillees(self):
        self.etapes.add('indicateurs')
        if self.catalogue is None or 'J15B' not in self.manifestes:
            self.noter('INDICATEURS','Lecture des thèmes','NON_TESTE','Catalogue indisponible.','Corriger d’abord le catalogue.')
            return self.afficher('INDICATEURS')
        cat = self.catalogue
        m = self.manifestes['J15B']
        index = m.get('themes',[])
        paires = [(e['niveau'],e['theme']) for e in index]
        attendus = set(map(tuple,cat[['NIVEAU','THEME']].itertuples(index=False,name=None)))
        if len(set(paires)) != len(paires) or set(paires) != attendus:
            self.noter('INDICATEURS','Liste des thèmes','BLOQUANT','Les thèmes du manifeste et du catalogue diffèrent.','Régénérer J15b.',1)
        for e in index:
            level,theme = e['niveau'],e['theme']
            rows = cat.loc[cat['NIVEAU'].eq(level)&cat['THEME'].eq(theme)]
            t = self._lire(self.detail,e['fichier'])
            if t is None:
                continue
            titre = f'{level} — {theme}'
            required = {'__CODE','__CODGEO','__NOM'} | set(rows['COLONNE'])
            manque = required-set(t)
            surplus = set(t)-required
            if manque or surplus or len(rows)!=e.get('nb_variables'):
                self.noter('INDICATEURS',titre+' : colonnes','BLOQUANT',
                    'Colonnes absentes : '+str(sorted(manque)[:8])+' ; supplémentaires : '+str(sorted(surplus)[:8]),'Régénérer ce thème.',max(1,len(manque)+len(surplus)))
                if manque:
                    continue
            base = self.tables.get('profil_communes' if level=='COMMUNE' else 'profil_iris')
            cle = 'CODGEO' if level=='COMMUNE' else 'IRIS'
            ok_codes = self._codes(t,'__CODE',5 if level=='COMMUNE' else 9,titre+' : codes')
            if base is not None and cle in base:
                difference = set(t['__CODE']) ^ set(base[cle])
                n = len(difference)
                self.noter('INDICATEURS',titre+' : couverture géographique','BLOQUANT' if n else 'OK',
                    f'{len(t)} territoires ; {n} code(s) différent(s) du socle J15a.',
                    'Utiliser les mêmes territoires et la même géographie dans les deux exports.' if n else '',n)
                if level=='IRIS' and 'CODGEO' in base and ok_codes and base[cle].is_unique:
                    attendu = t['__CODE'].map(base.set_index(cle)['CODGEO'])
                    n = int(t['__CODGEO'].ne(attendu).fillna(True).sum())
                    self.noter('INDICATEURS',titre+' : commune de contexte','BLOQUANT' if n else 'OK',
                        f'{n} rattachement(s) communal(aux) différent(s) du socle.','Vérifier la jointure des IRIS.' if n else '',n)
            if len(t) != m.get('nb_territoires',{}).get(level):
                self.noter('INDICATEURS',titre+' : effectif du manifeste','BLOQUANT','Le nombre de territoires diffère du manifeste.','Régénérer J15b.',1)
            erreurs, decalages, vides, partielles = 0,0,0,0
            for row in rows.to_dict('records'):
                col = row['COLONNE']
                present = ~t[col].str.strip().str.lower().isin(MANQUANTS) & t[col].notna()
                taux = float(present.mean()*100) if len(t) else 0.0
                vides += int(not present.any())
                partielles += int(present.any() and not present.all())
                minimum,maximum,regle = None,None,'TEXTE'
                if row['TYPE']=='NUMERIQUE':
                    v,bad,_,regle,n = self._valeurs(t,col,t['__CODE'],'INDICATEURS',level,theme)
                    erreurs += n
                    if v.notna().any():
                        minimum,maximum = float(v.min()),float(v.max())
                declaration = []
                for key,value in [('NB_PRESENTES',int(present.sum())),('NB_LIGNES',len(t)),('COUVERTURE_PCT',taux)]:
                    try:
                        if not math.isclose(float(row[key]),value,abs_tol=.0001,rel_tol=1e-8):
                            declaration.append(key)
                    except (ValueError,TypeError):
                        declaration.append(key)
                if declaration:
                    decalages += 1
                self.couverture.append({'ID':row['ID'],'NIVEAU':level,'THEME':theme,'COLONNE':col,
                    'LIBELLE':row['LIBELLE'],'NB_TERRITOIRES':len(t),'NB_PRESENTES':int(present.sum()),
                    'COUVERTURE_PCT':round(taux,2),'MINIMUM':minimum,'MAXIMUM':maximum,
                    'REGLE_APPLIQUEE':regle,'METADONNEES_COUVERTURE_A_VERIFIER':' ; '.join(declaration)})
                # Vérification limitée aux colonnes attribuées explicitement à une seule source.
                if not self.compatibilite.empty and row['TYPE']=='NUMERIQUE' and '|' not in row['FICHIER_SOURCE']:
                    source = Path(row['FICHIER_SOURCE']).name
                    bad_geo = self.compatibilite.loc[self.compatibilite['FICHIER'].eq(source)&self.compatibilite['STATUT'].eq('PERIMETRE_INCOMPATIBLE_MEME_CODE'),'CODGEO']
                    mask = t['__CODGEO'].isin(bad_geo)&present
                    if mask.any():
                        erreurs += int(mask.sum())
                        self.anomalies.append({'BLOC':'GEOGRAPHIE_SOURCE','NIVEAU':level,'COLONNE':col,
                            'REGLE':'VALEUR_INDISPONIBLE_SI_PERIMETRE_INCOMPATIBLE','PROBLEME':'Une valeur est présente malgré une incompatibilité géographique déclarée.',
                            'NB_LIGNES':int(mask.sum()),'EXEMPLES_CODES':', '.join(t.loc[mask,'__CODE'].head(10))})
            self.noter('INDICATEURS',titre+' : valeurs numériques','BLOQUANT' if erreurs else 'OK',
                f'{len(rows)} variables examinées ; {erreurs} valeur(s) à corriger selon les règles appliquées.',
                'Lire anomalies_valeurs_j16.csv et vérifier le calcul source.' if erreurs else 'Les variables sans règle métier reçoivent uniquement un contrôle de lecture numérique.',erreurs)
            self.noter('INDICATEURS',titre+' : couverture annoncée','A_VERIFIER' if decalages else 'OK',
                f'{decalages} variable(s) dont la couverture annoncée diffère des données lues.',
                'Comparer le catalogue au fichier thématique.' if decalages else '',decalages)
            self.noter('INDICATEURS',titre+' : disponibilité des données','A_VERIFIER' if vides else 'OK',
                f'{vides} variable(s) sans aucune valeur ; {partielles} avec une couverture partielle. Une absence peut être légitime.',
                'Consulter couverture_indicateurs_j16.csv et expliquer les absences pour les indicateurs présentés.' if vides or partielles else '',vides)
        return self.afficher('INDICATEURS')

    def verifier_geographies_sources(self):
        self.etapes.add('geographies_sources')
        nom = 'compatibilite_sources_communes.csv'
        if self.detail/nom not in self.fiables:
            self.noter('SOURCES','Compatibilité des géographies sources','NON_TESTE','Le rapport de compatibilité n’est pas disponible.','Documenter manuellement les sources de géographies différentes.')
            return self.afficher('SOURCES')
        t = self._lire(self.detail,nom)
        if t is None:
            return self.afficher('SOURCES')
        if not {'FICHIER','CODGEO','STATUT'} <= set(t):
            self.noter('SOURCES','Compatibilité des géographies sources','BLOQUANT','Le rapport n’a pas les champs attendus.','Reprendre l’export de compatibilité.',1)
            return self.afficher('SOURCES')
        self.compatibilite = t
        n = int(t['STATUT'].isin(['PERIMETRE_INCOMPATIBLE_MEME_CODE','CODE_ABSENT_SOURCE']).sum())
        self.noter('SOURCES','Sources de géographies différentes','A_VERIFIER' if n else 'OK',
            f'{n} ligne(s) signalent un code absent ou un périmètre incompatible. Ces cas peuvent être correctement gérés par des valeurs indisponibles.',
            'Consulter compatibilite_geographies_j16.csv ; ne pas remplacer les données indisponibles par zéro.' if n else '',n)
        return self.afficher('SOURCES')

    def verifier_calculs_simples(self):
        self.etapes.add('calculs')
        erreurs = 0
        for key,level,cle in [('profil_communes','COMMUNE','CODGEO'),('profil_iris','IRIS','IRIS')]:
            t = self.tables.get(key)
            if t is None or cle not in t:
                self.noter('CALCULS',level+' : contrôle du socle','NON_TESTE','Profil indisponible.','Corriger sa lecture.')
                continue
            for col in t:
                if regle_prudente(col) != 'LECTURE_NUMERIQUE':
                    self._valeurs(t,col,t[cle],'SOCLE',level)
            required = {'POPULATION','RESTAURANTS','DENSITE_RESTAURANTS'}
            if required <= set(t):
                p,_,_ = nombre(t['POPULATION']);r,_,_ = nombre(t['RESTAURANTS']);d,_,_ = nombre(t['DENSITE_RESTAURANTS'])
                possible = p.gt(0)&r.notna()
                attendu = r/p.where(p.gt(0))*10000
                mauvais = possible&d.notna()&~pd.Series(np.isclose(d,attendu,atol=.051,rtol=1e-6),index=t.index)
                incoherent = p.le(0)&d.notna()
                absent = possible&d.isna()
                for mask,motif in [(mauvais,'Densité différente du calcul restaurants / population × 10 000'),(incoherent,'Densité publiée avec une population nulle ou négative'),(absent,'Densité absente alors que les données permettent le calcul')]:
                    for idx in t.index[mask]:
                        self.calculs.append({'NIVEAU':level,'CODE':t.at[idx,cle],'PROBLEME':motif,
                            'RESTAURANTS':r.loc[idx],'POPULATION':p.loc[idx],'DENSITE_PUBLIEE':d.loc[idx],
                            'DENSITE_RECALCULEE':attendu.loc[idx]})
                n = int(mauvais.sum()+incoherent.sum());erreurs += n
                self.noter('CALCULS',level+' : densité de restaurants','BLOQUANT' if n else ('A_VERIFIER' if absent.any() else 'OK'),
                    f'{int(possible.sum())} calculs possibles ; {n} valeur(s) incohérente(s) ; {int(absent.sum())} densité(s) absente(s).',
                    'Lire controles_calculs_j16.csv. Une tolérance de 0,051 permet un affichage arrondi à une décimale.' if n or absent.any() else '',n+int(absent.sum()))
            if {'RESTAURANTS','RAPIDES'} <= set(t):
                total,_,_ = nombre(t['RESTAURANTS']);rapide,_,_ = nombre(t['RAPIDES'])
                n = int((rapide>total+1e-8).sum());erreurs += n
                self.noter('CALCULS',level+' : restauration rapide et total','BLOQUANT' if n else 'OK',
                    f'{n} territoire(s) où la restauration rapide dépasse le total.',
                    'Vérifier les périmètres et catégories retenues.' if n else '',n)
        anomalies_socle = sum(r['NB_LIGNES'] for r in self.anomalies if r['BLOC']=='SOCLE')
        self.noter('CALCULS','Lecture et bornes des indicateurs du socle','BLOQUANT' if anomalies_socle else 'OK',
            f'{anomalies_socle} valeur(s) hors des règles de lecture ou de bornes connues.',
            'Lire anomalies_valeurs_j16.csv.' if anomalies_socle else '',anomalies_socle)
        return self.afficher('CALCULS')

    def verifier_cartographie(self):
        self.etapes.add('cartographie')
        a,l,rel = self.tables.get('arrets'),self.tables.get('lignes'),self.tables.get('relations')
        for t,key,nom in [(a,'ID_ARRET','Arrêts'),(l,'ID_LINE','Lignes')]:
            if t is None:
                continue
            if key not in t:
                self.noter('CARTE',nom+' : identifiants','BLOQUANT',key+' absent.','Reprendre la préparation du réseau.',1)
                continue
            n = int((t[key].eq('')|t[key].duplicated(keep=False)).sum())
            self.noter('CARTE',nom+' : identifiants','BLOQUANT' if n else 'OK',f'{n} identifiant(s) vide(s) ou répété(s).','Vérifier la clé des objets.' if n else '',n)
        if a is not None and l is not None and rel is not None and {'ID_ARRET','ID_LINE'} <= set(rel) and 'ID_ARRET' in a and 'ID_LINE' in l:
            n = int((~rel['ID_ARRET'].isin(a['ID_ARRET'])|~rel['ID_LINE'].isin(l['ID_LINE'])|rel[['ID_ARRET','ID_LINE']].duplicated(keep=False)).sum())
            self.noter('CARTE','Relations arrêt–ligne','BLOQUANT' if n else 'OK',f'{n} relation(s) répétée(s) ou sans arrêt/ligne correspondant(e).','Vérifier les relations, sans confondre leur nombre avec le nombre d’arrêts physiques.' if n else '',n)
        if l is not None and 'MODE' in l:
            n = int((~l['MODE'].isin(MODES)).sum())
            self.noter('CARTE','Modes de transport','BLOQUANT' if n else 'OK',
                f'Modes présents : {", ".join(sorted(l["MODE"].unique()))}. {n} valeur(s) non reconnue(s).',
                'Harmoniser les modes avec ceux acceptés par l’application.' if n else '',n)
        if l is not None and 'COULEUR_WEB' in l:
            n = int((~l['COULEUR_WEB'].str.fullmatch(r'#[0-9a-fA-F]{6}',na=False)).sum())
            self.noter('CARTE','Couleurs des lignes','BLOQUANT' if n else 'OK',f'{n} couleur(s) au format non reconnu.','Reprendre les couleurs du référentiel de lignes.' if n else '',n)
        for key in ['arrets','restaurants']:
            t = self.tables.get(key)
            if t is None:
                continue
            if not {'LONGITUDE','LATITUDE'} <= set(t):
                self.noter('CARTE',key+' : coordonnées','BLOQUANT','Latitude ou longitude absente.','Reprendre l’export géolocalisé.',1)
                continue
            x,bx,_ = nombre(t['LONGITUDE']);y,by,_ = nombre(t['LATITUDE'])
            n = int((bx|by|x.isna()|y.isna()|~x.between(-180,180)|~y.between(-90,90)).sum())
            self.noter('CARTE',key+' : coordonnées','BLOQUANT' if n else 'OK',f'{n} paire(s) de coordonnées invalide(s).','Vérifier le système de coordonnées et les points.' if n else '',n)
        for nom,key,profil,cle in [('communes_idf.geojson','CODGEO','profil_communes','CODGEO'),('iris_idf.geojson','IRIS','profil_iris','IRIS')]:
            p = self.base/nom
            if p not in self.fiables or profil not in self.tables:
                continue
            try:
                g = json.loads(p.read_text(encoding='utf-8-sig'))
                features = g.get('features',[])
                codes = [f['properties'][key] for f in features]
                attendu = set(self.tables[profil][cle])
                mauvais = sum(not isinstance(c,str) for c in codes) + sum(not f.get('geometry') or f['geometry'].get('type') not in {'Polygon','MultiPolygon'} or not f['geometry'].get('coordinates') for f in features)
                n = len(set(codes)^attendu)+len(codes)-len(set(codes))+mauvais
                if g.get('type') != 'FeatureCollection':
                    n += 1
                self.noter('CARTE',nom+' : contours et codes','BLOQUANT' if n else 'OK',
                    f'{len(features)} contours ; {n} différence(s) de codes ou de structure.','Reprendre les contours du même millésime.' if n else '',n)
                if key=='IRIS' and 'CODGEO' in self.tables[profil]:
                    contextes = self.tables[profil].set_index('IRIS')['CODGEO'].to_dict()
                    n = sum(f['properties'].get('CODGEO') != contextes.get(f['properties']['IRIS']) for f in features)
                    self.noter('CARTE','Contours IRIS : communes de contexte','BLOQUANT' if n else 'OK',f'{n} rattachement(s) différent(s) du profil.','Vérifier Paris et les changements de communes.' if n else '',n)
            except (OSError,ValueError,KeyError,TypeError) as e:
                self.noter('CARTE',nom,'BLOQUANT',str(e),'Reprendre le fichier géographique.',1)
        if l is not None and 'ID_LINE' in l:
            lignes = set(l['ID_LINE'])
            for nom in ['traces_idf.geojson','traces_focus.geojson']:
                p = self.base/nom
                if p not in self.fiables:
                    continue
                try:
                    g = json.loads(p.read_text(encoding='utf-8-sig'))
                    fs = g.get('features',[])
                    n = int(g.get('type') != 'FeatureCollection')
                    n += sum(f.get('properties',{}).get('ID_LINE') not in lignes or not f.get('geometry')
                             or f['geometry'].get('type') not in {'LineString','MultiLineString'} for f in fs)
                    self.noter('CARTE',nom+' : références des lignes','BLOQUANT' if n else 'OK',
                        f'{len(fs)} tracés ; {n} référence(s) ou structure(s) incorrecte(s).',
                        'Harmoniser les identifiants des tracés et du référentiel.' if n else '',n)
                except (OSError,ValueError,TypeError) as e:
                    self.noter('CARTE',nom,'BLOQUANT',str(e),'Reprendre le fichier de tracés.',1)
        self.noter('CARTE','Validité topologique des polygones','NON_TESTE','Le contrôle porte sur les codes et la structure GeoJSON. Les auto-intersections et la qualité topologique ne sont pas recalculées ici.','Conserver les contrôles géométriques des notebooks de préparation ; vérifier les cartes à l’écran.')
        return self.afficher('CARTE')

    def verifier_sources(self):
        self.etapes.add('sources')
        t = self.tables.get('sources')
        required = {'fichier','source','annee_donnees','annee_geographie','date_telechargement','url'}
        if t is None:
            self.noter('SOURCES','Registre des sources','NON_TESTE','Le registre n’a pas pu être lu.','Vérifier sources.csv.')
        elif not required <= set(t):
            self.noter('SOURCES','Registre des sources','BLOQUANT','Champs absents : '+', '.join(sorted(required-set(t))),'Reprendre le registre.',len(required-set(t)))
        else:
            n = int(t[list(required)].eq('').any(axis=1).sum())
            self.noter('SOURCES','Informations du registre','A_VERIFIER' if n else 'OK',f'{n} ligne(s) avec au moins un champ non renseigné.','Compléter les dates et millésimes réellement connus ; écrire explicitement « non précisé » si nécessaire.' if n else '',n)
        return self.afficher('SOURCES')

    def preparer_tests_manuels(self):
        self.etapes.add('manuels')
        self.interim.mkdir(parents=True,exist_ok=True)
        path = self.interim/'controles_manuels_application_j16.csv'
        if path.is_file():
            self.manuels = lire_csv(path)
            if not {'TEST','ETAT','OBSERVATION'} <= set(self.manuels):
                raise ValueError('Le fichier des tests manuels doit garder TEST, ETAT et OBSERVATION.')
        else:
            tests = ['Ouvrir l’application déployée dans une nouvelle session',
                'Afficher Cergy, Pontoise et une autre commune',
                'Cliquer sur un IRIS et retrouver le bon territoire',
                'Lire les libellés et unités des indicateurs présentés',
                'Afficher les transports et vérifier la présence du tramway',
                'Vérifier les légendes et les infobulles de la carte',
                'Télécharger puis ouvrir un PDF',
                'Vérifier la lisibilité sur une petite fenêtre ou un téléphone']
            self.manuels = pd.DataFrame({'TEST':tests,'ETAT':'A_FAIRE','OBSERVATION':''})
            self.manuels.to_csv(path,sep=';',index=False,encoding='utf-8-sig')
        for row in self.manuels.fillna('').to_dict('records'):
            etat = row['ETAT'].strip().upper()
            statut = {'OK':'OK','A_CORRIGER':'BLOQUANT','NON_APPLICABLE':'NON_TESTE','A_FAIRE':'NON_TESTE'}.get(etat,'A_VERIFIER')
            self.noter('APPLICATION',row['TEST'],statut,
                row['OBSERVATION'] or ('Test réalisé, aucune observation renseignée.' if etat=='OK' else 'Ce test nécessite une vérification humaine dans l’application.'),
                'Renseigner ETAT et OBSERVATION dans controles_manuels_application_j16.csv, puis relancer ce notebook.' if etat not in {'OK','NON_APPLICABLE'} else '',int(etat not in {'OK','NON_APPLICABLE'}))
        return self.manuels.copy()

    def verifier_fichiers_application(self):
        self.etapes.add('fichiers_application')
        noms = ['app/streamlit_app.py','app/core.py','app/indicators.py','app/territory_map.py',
                'app/territory_component/index.html','app/territory_component/plotly.min.js',
                'app/territory_component/world_110m.json']
        problemes = []
        for nom in noms:
            p = self.racine/nom
            if not p.is_file() or not p.stat().st_size:
                problemes.append(nom+' absent ou vide')
            elif p.name == 'plotly.min.js':
                with p.open('rb') as f:
                    debut = f.read(256)
                if b'version https://git-lfs.github.com/spec' in debut or debut.lstrip().lower().startswith((b'<!doctype html',b'<html')):
                    problemes.append(nom+' contient un pointeur Git LFS ou une page HTML')
        self.noter('APPLICATION','Fichiers nécessaires à la carte','BLOQUANT' if problemes else 'OK',
            ' ; '.join(problemes) if problemes else 'Les fichiers contrôlés existent et le JavaScript ne ressemble pas à un pointeur LFS ou à une page HTML.',
            'Rétablir les fichiers complets dans le dépôt puis redéployer.' if problemes else 'Tester la carte dans le navigateur : la présence des fichiers ne vérifie pas leur exécution.',len(problemes))
        return self.afficher('APPLICATION')

    def apercu_focus(self):
        t = self.tables.get('profil_communes')
        if t is None or 'CODGEO' not in t:
            return pd.DataFrame()
        cols = [c for c in ['CODGEO','NOM_COMMUNE','POPULATION','RESTAURANTS','RAPIDES','DENSITE_RESTAURANTS'] if c in t]
        return t.loc[t['CODGEO'].isin(self.focus),cols].rename(columns={
            'CODGEO':'Code commune','NOM_COMMUNE':'Commune','POPULATION':'Population (habitants)',
            'RESTAURANTS':'Restaurants recensés','RAPIDES':'Restauration rapide recensée',
            'DENSITE_RESTAURANTS':'Restaurants pour 10 000 habitants'})

    def verifier_lecture_seule(self):
        n = sum(not p.is_file() or empreinte(p)!=sha for p,sha in self.instantane.items())
        self.noter('INTEGRITE','Conservation des exports de départ','BLOQUANT' if n else 'OK',
            f'{n} fichier(s) d’entrée différent(s) de leur version au début du contrôle.',
            'Identifier la modification et relancer le contrôle sur un lot stable.' if n else 'Les rapports J16 sont écrits dans leurs propres dossiers.',n)

    def exporter(self,commentaire=''):
        self.interim.mkdir(parents=True,exist_ok=True)
        self.rapports.mkdir(parents=True,exist_ok=True)
        attendues = {'fichiers','territoires','catalogue','indicateurs','geographies_sources',
                     'calculs','cartographie','sources','manuels','fichiers_application'}
        for etape in sorted(attendues-self.etapes):
            self.noter('EXECUTION','Étape '+etape,'NON_TESTE','Cette partie du notebook n’a pas été exécutée.','Exécuter le notebook du début à la fin.')
        self.verifier_lecture_seule()
        tables = {'bilan_controles_j16':self.bilan(), 'inventaire_fichiers_j16':pd.DataFrame(self.inventaire),
            'documentation_indicateurs_j16':pd.DataFrame(self.documentation),
            'couverture_indicateurs_j16':pd.DataFrame(self.couverture),
            'anomalies_valeurs_j16':pd.DataFrame(self.anomalies,columns=['BLOC','NIVEAU','COLONNE','REGLE','PROBLEME','NB_LIGNES','EXEMPLES_CODES']),
            'controles_calculs_j16':pd.DataFrame(self.calculs,columns=['NIVEAU','CODE','PROBLEME','RESTAURANTS','POPULATION','DENSITE_PUBLIEE','DENSITE_RECALCULEE']),
            'compatibilite_geographies_j16':self.compatibilite,
            'apercu_cergy_pontoise_j16':self.apercu_focus()}
        for nom,t in tables.items():
            if len(t.columns):
                t.to_csv(self.interim/(nom+'.csv'),sep=';',index=False,encoding='utf-8-sig')
        counts = self.bilan()['STATUT'].value_counts().to_dict()
        blocages = int(counts.get('BLOQUANT',0));avertissements = int(counts.get('A_VERIFIER',0))
        non_testes = int(counts.get('NON_TESTE',0))
        t_bilan = self.bilan()
        hors_perimetre = t_bilan['CONTROLE'].eq('Validité topologique des polygones') | (
            t_bilan['BLOC'].eq('APPLICATION') & t_bilan['STATUT'].eq('NON_TESTE') & t_bilan['NB_CONCERNES'].eq(0))
        non_testes_a_traiter = int((t_bilan['STATUT'].eq('NON_TESTE') & ~hors_perimetre).sum())
        statut = 'A_CORRIGER' if blocages else ('A_COMPLETER' if avertissements or non_testes_a_traiter else 'CONTROLES_REALISES_DANS_LE_PERIMETRE')
        nb_vars = len(self.catalogue) if self.catalogue is not None else 0
        c,i = self.tables.get('profil_communes'),self.tables.get('profil_iris')
        texte = (f'Bilan J16 — Contrôle des données et de l’application\n\n'
            f'Le contrôle porte sur {len(c) if c is not None else "un nombre non vérifié de"} communes, '
            f'{len(i) if i is not None else "un nombre non vérifié d’"} IRIS et {nb_vars} variables du catalogue.\n'
            f'Les vérifications concernent les fichiers, les codes géographiques, la documentation, '
            f'la lecture des valeurs, quelques calculs simples et la structure des cartes.\n\n'
            f'Résultats : {counts.get("OK",0)} contrôles OK ; {avertissements} à vérifier ; '
            f'{blocages} à corriger ; {non_testes} non testés.\n'
            f'Parmi les non testés, {non_testes_a_traiter} demandent encore une action dans ce bilan. '
            f'La topologie complète et les tests déclarés non applicables restent hors du périmètre exécuté.\n'
            f'État du bilan : {statut}.\n\n')
        if blocages:
            texte += 'Les points « À corriger » doivent être traités avant de présenter les résultats concernés.\n'
        else:
            texte += 'Les contrôles exécutés n’ont pas détecté de point bloquant selon leurs règles.\n'
        texte += ('Les points « À vérifier » demandent une relecture ou une documentation supplémentaire. '
            'Les tests manuels de l’application restent à réaliser s’ils sont marqués A_FAIRE.\n\n'
            'Ce contrôle technique ne valide pas automatiquement les définitions statistiques. '
            'Les valeurs manquantes restent manquantes. Les médianes et pourcentages ne sont pas additionnés. '
            'Les évolutions, écarts et indices peuvent dépasser les bornes d’une part de population.\n\n')
        if commentaire.strip():
            texte += 'Mon commentaire :\n'+commentaire.strip()+'\n\n'
        priorites = self.bilan().loc[self.bilan()['STATUT'].isin(['BLOQUANT','A_VERIFIER'])]
        texte += 'Actions à suivre :\n'
        if priorites.empty:
            texte += '- Terminer les tests non réalisés et conserver ce bilan.\n'
        else:
            for row in priorites.to_dict('records'):
                texte += f'- {row["CONTROLE"]} : {row["ACTION"] or row["EXPLICATION"]}\n'
        (self.rapports/'synthese_j16.txt').write_text(texte,encoding='utf-8')
        tableau = self.afficher().to_html(index=False,escape=True,border=0)
        page = ('<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Bilan J16</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#173047;background:#f3f6fa;margin:0}'
            'main{max-width:1280px;margin:auto;padding:32px}h1{font-size:30px}section{background:white;padding:24px;border-radius:12px;margin-bottom:20px}'
            'pre{font:inherit;white-space:pre-wrap}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:12px;text-align:left;border-bottom:1px solid #d9e2eb;vertical-align:top}'
            'th{background:#eaf0f6}.table{overflow-x:auto}footer{color:#4c6375}</style><main>'
            '<h1>Bilan J16 — Des contrôles expliqués simplement</h1><section><pre>'+html.escape(texte)+'</pre></section>'
            '<section><h2>Lire les résultats</h2><p><strong>OK</strong> : la règle testée est respectée. '
            '<strong>À vérifier</strong> : une relecture est nécessaire. <strong>À corriger</strong> : une incohérence a été détectée. '
            '<strong>Non testé</strong> : le contrôle n’a pas été réalisé ou nécessite une vérification humaine.</p></section>'
            '<section class="table"><h2>Détail des contrôles</h2>'+tableau+'</section>'
            '<footer>Rapport produit par le notebook J16. Les fichiers J15a et J15b sont conservés.</footer></main></html>')
        (self.rapports/'bilan_j16.html').write_text(page,encoding='utf-8')
        resultat = {'version':VERSION,'date_utc':datetime.now(timezone.utc).isoformat(),'statut':statut,
            'nb_variables':nb_vars,'controles_par_statut':counts,
            'nb_non_testes_a_traiter':non_testes_a_traiter,
            'j15a':str(self.base),'j15b':str(self.detail),
            'nb_fichiers_entree_controles':len(self.instantane),
            'rapports':str(self.rapports),'validation_statistique_automatique':False}
        (self.rapports/'bilan_j16.json').write_text(json.dumps(resultat,ensure_ascii=False,indent=2),encoding='utf-8')
        return resultat,texte
