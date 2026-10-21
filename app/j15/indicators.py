"""Catalogue J15b : conserver les variables, documenter, exporter par thème."""
from pathlib import Path
import csv
import hashlib
import io
import json
import math
import re
import unicodedata
import pandas as pd

THEMES = {
    'POPULATION': 'Population, âge et sexe', 'MENAGES': 'Ménages et familles',
    'REVENUS': 'Revenus et pauvreté', 'EMPLOI': 'Activité, emploi et PCS',
    'DIPLOMES': 'Diplômes et scolarisation', 'LOGEMENTS': 'Logements',
    'RESTAURATION': 'Restauration', 'EQUIPEMENTS': 'Commerces et équipements',
    'TRANSPORTS': 'Transports et mobilités', 'AUTRES': 'Autres indicateurs',
    'PRESELECTION': 'Présélection exploratoire J12',
    'TECHNIQUE': 'Codes, statuts et métadonnées',
}
FIELDS = ['ID','NIVEAU','COLONNE','LIBELLE','THEME','TYPE','UNITE','ANNEE','GEOGRAPHIE',
          'SOURCE','DEFINITION','AGREGATION','NUMERATEUR','DENOMINATEUR','FACTEUR',
          'VALIDE','METADONNEES','FICHIER_SOURCE','NB_PRESENTES','NB_LIGNES','COUVERTURE_PCT']
EDITABLE = ['LIBELLE','THEME','TYPE','UNITE','ANNEE','GEOGRAPHIE','SOURCE','DEFINITION',
            'AGREGATION','NUMERATEUR','DENOMINATEUR','FACTEUR','VALIDE']
MISSING = {'','s','ss','nd','n.d.','n.d','nan','na','n/a','null','none','-','--','///','...','…'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1048576), b''): h.update(part)
    return h.hexdigest()


def name(value):
    s = unicodedata.normalize('NFKD', str(value)).encode('ascii','ignore').decode().upper()
    return re.sub(r'[^A-Z0-9]+','_',s).strip('_')


def read_table(path, sep=None):
    path = Path(path)
    with path.open(encoding='utf-8-sig', newline='') as f:
        first = f.readline()
    if sep is None:
        scores = [(len(next(csv.reader([first],delimiter=d))),d) for d in [',',';','\t']]
        sep = max(scores)[1]
    table = pd.read_csv(path,sep=sep,dtype='string',encoding='utf-8-sig',keep_default_na=False)
    table.columns = table.columns.str.strip()
    if not table.columns.is_unique or any(c.endswith(('.1','.2')) for c in table.columns):
        raise ValueError(f'{path} : colonnes ambiguës/dupliquées ; vérifier les en-têtes.')
    return table.replace('',pd.NA)


def numbers(values):
    s = values.astype('string').str.strip()
    missing = s.str.lower().isin(MISSING) | s.isna()
    clean = s.str.replace('\u202f','',regex=False).str.replace('\u00a0','',regex=False).str.replace(' ','',regex=False).str.replace(',','.',regex=False)
    n = pd.to_numeric(clean.where(~missing),errors='coerce').astype(float)
    invalid = ~missing & (n.isna() | ~n.map(math.isfinite))
    return n.where(~invalid),invalid


def theme_for(column):
    c = re.sub(r'__SOURCE_J(?:12|13E)$','',column)
    c = name(c)
    if c in {'DEP','REG','NOM_COMMUNE','NOM_IRIS','NOM_COMMUNE_CONTOUR'}: return 'TECHNIQUE'
    if c.startswith('J12_') and any(x in c for x in ['INDICE','RANG','CRITERE','PRESELECTION','SCENARIO']):return 'PRESELECTION'
    if re.search(r'(^|_)(STATUT|SOURCE|ANNEE|GEOGRAPHIE|CODE|CODGEO|CHARGE|DISPONIBLE|DANS_FOCUS|ORIGINE|CLE)(_|$)',c): return 'TECHNIQUE'
    if any(x in c for x in ['MOBPRO','MOBSCO','TRANSPORT','ARRET','LIGNES','METRO','TRANSILIEN','RER','TRAM','BUS','MARCHE','VELO','VOITURE','DEUX_ROUES']): return 'TRANSPORTS'
    if any(x in c for x in ['MEDIAN','PAUV','REVENU','FISCAL','FILOSOFI']): return 'REVENUS'
    if any(x in c for x in ['RESTAUR','RAPIDE','CAFETER']): return 'RESTAURATION'
    if any(x in c for x in ['DIPLO','SCOLAR','SCOL_','NON_SCOL','ETUDIANT','BEPC','CAP_BEP','BAC']): return 'DIPLOMES'
    if any(x in c for x in ['MENAGE','FAMIL','COUPLE','MONOPAR','ENFANT']): return 'MENAGES'
    if any(x in c for x in ['LOGEMENT','RESID','LOCATAIRE','PROPRIET','MAISON','APPART','HLM']): return 'LOGEMENTS'
    if any(x in c for x in ['ACTIF','ACTOCC','CHOMEUR','EMPLO','OUVRIER','CADRE','PCS','PROFESSION','ACTIVITE','INACTIF']): return 'EMPLOI'
    if any(x in c for x in ['POP','AGE','HOMME','FEMME','1529','0014','3044','4559','6074','75P']): return 'POPULATION'
    if any(x in c for x in ['COMMERCE','EQUIPEMENT','SANTE','SPORT','LOISIR','CINEMA','HOTEL','TOURIS','EDUCATION','SERVICE','ALIMENT']) or c.startswith(('NB_OBS_','DENSITE_OBS_','PART_OBS_')): return 'EQUIPEMENTS'
    return 'AUTRES'


def metadata(paths):
    """Conserver les collisions au lieu de choisir une définition arbitraire."""
    rows = {}
    for path in paths:
        table = read_table(path)
        table.columns = [name(c) for c in table]
        if 'COLONNE' not in table: continue
        for raw in table.fillna('').to_dict('records'):
            c = str(raw['COLONNE']).strip()
            entry = {k:str(raw.get(k,'')) for k in ['LIBELLE','UNITE','SOURCE','DEFINITION','AGREGATION','NUMERATEUR','DENOMINATEUR','FACTEUR','ANNEE','GEOGRAPHIE','NIVEAU']}
            if not entry['DEFINITION']: entry['DEFINITION'] = str(raw.get('METHODE',''))
            if not entry['GEOGRAPHIE']: entry['GEOGRAPHIE'] = str(raw.get('GEOGRAPHIE_IRIS',''))
            entry['_DICTIONNAIRE'] = str(path)
            rows.setdefault(c,[]).append(entry)
    return rows


def build_catalogue(tables, provenance, dictionaries=(), hints=None):
    met = metadata(dictionaries)
    result = []
    for level,table in tables.items():
        for column in table:
            if column.startswith('__'): continue
            raw = table[column]
            n,bad = numbers(raw)
            kind = 'NUMERIQUE' if not bad.any() and n.notna().any() else 'TEXTE'
            entries = [e for e in met.get(column,[]) if not e['NIVEAU'] or e['NIVEAU'].upper()==level]
            signatures = {json.dumps({k:v for k,v in e.items() if not k.startswith('_')},sort_keys=True) for e in entries}
            md = entries[0] if len(signatures)==1 else {}
            proposed=(hints or {}).get(level,{}).get(column,{})
            state = 'DICTIONNAIRE' if md else ('CONFLIT_DICTIONNAIRES' if entries else ('PROPOSITION_SOURCE_ET_NOM' if proposed else 'A_DOCUMENTER'))
            def field(key):return md.get(key) or proposed.get(key,'')
            nonmissing = raw.notna() & ~raw.astype('string').str.strip().str.lower().isin(MISSING)
            result.append({
                'ID':level+'_'+hashlib.sha256(column.encode()).hexdigest()[:16],
                'NIVEAU':level,'COLONNE':column,
                'LIBELLE':field('LIBELLE') or column.replace('_',' ').capitalize(),
                'THEME':theme_for(column),'TYPE':kind,
                'UNITE':field('UNITE'),'ANNEE':field('ANNEE'),'GEOGRAPHIE':field('GEOGRAPHIE'),
                'SOURCE':field('SOURCE'),'DEFINITION':field('DEFINITION'),
                # Aucune somme ni moyenne automatique dans J15b.
                'AGREGATION':md.get('AGREGATION') or 'NON_AUTORISEE',
                'NUMERATEUR':md.get('NUMERATEUR',''),'DENOMINATEUR':md.get('DENOMINATEUR',''),'FACTEUR':md.get('FACTEUR',''),
                'VALIDE':'NON','METADONNEES':state,'FICHIER_SOURCE':provenance[level].get(column,''),
                'NB_PRESENTES':int(nonmissing.sum()),'NB_LIGNES':len(table),
                'COUVERTURE_PCT':float(nonmissing.mean()*100),
            })
    cat = pd.DataFrame(result,columns=FIELDS)
    if not cat['ID'].is_unique: raise ValueError('Identifiant de variable dupliqué.')
    return cat


def apply_overrides(catalogue, path):
    cat = catalogue.copy()
    if not Path(path).is_file(): return cat
    edits = read_table(path).fillna('')
    if 'ID' not in edits or not edits['ID'].is_unique: raise ValueError('Corrections : ID absent/dupliqué.')
    if not edits['ID'].isin(cat['ID']).all(): raise ValueError('Corrections : ID inconnus ; comparer au nouveau catalogue.')
    index = cat.set_index('ID')
    for row in edits.to_dict('records'):
        for field in EDITABLE:
            if field in row and str(row[field]).strip(): index.at[row['ID'],field] = str(row[field]).strip()
    cat = index.reset_index()
    if not cat['THEME'].isin(THEMES).all(): raise ValueError('Thème inconnu dans les corrections.')
    if not cat['TYPE'].isin(['NUMERIQUE','TEXTE']).all(): raise ValueError('TYPE attendu : NUMERIQUE ou TEXTE.')
    if not cat['VALIDE'].isin(['OUI','NON']).all(): raise ValueError('VALIDE attendu : OUI ou NON.')
    incomplete = cat['VALIDE'].eq('OUI') & cat[['LIBELLE','UNITE','ANNEE','GEOGRAPHIE','SOURCE','DEFINITION']].fillna('').eq('').any(axis=1)
    if incomplete.any(): raise ValueError('Indicateurs validés sans métadonnées complètes : '+', '.join(cat.loc[incomplete,'COLONNE'].head(8)))
    return cat


def export_themes(tables, catalogue, directory, base_directory, inputs, commune_alignment=None):
    directory = Path(directory);directory.mkdir(parents=True,exist_ok=True)
    outputs = []
    cp = directory/'catalogue.csv';catalogue.to_csv(cp,index=False,encoding='utf-8-sig');outputs.append(cp)
    if commune_alignment is not None and not commune_alignment.empty:
        path=directory/'compatibilite_sources_communes.csv'
        commune_alignment.to_csv(path,index=False,encoding='utf-8-sig');outputs.append(path)
    index = []
    for (level,theme),rows in catalogue.groupby(['NIVEAU','THEME'],sort=True):
        filename=f'{level.lower()}_{theme.lower()}.csv'
        selected=['__CODE','__CODGEO','__NOM']+rows['COLONNE'].tolist()
        path=directory/filename
        tables[level][selected].to_csv(path,index=False,encoding='utf-8-sig');outputs.append(path)
        index.append({'niveau':level,'theme':theme,'fichier':filename,'nb_variables':len(rows)})
    for p in outputs:
        if p.stat().st_size > 20_000_000: raise ValueError(p.name+' dépasse le seuil de travail de 20 Mo. Répartir ce thème avant publication ; ne pas supprimer de territoires.')
    from datetime import datetime,timezone
    manifest={'schema_version':1,'etape':'J15B_INDICATEURS_PDF','generation_utc':datetime.now(timezone.utc).isoformat(),
              'base_manifest_sha256':digest(Path(base_directory)/'manifest.json'),
              'nb_variables':len(catalogue),'nb_par_niveau':catalogue.groupby('NIVEAU').size().to_dict(),
              'nb_territoires':{k:len(v) for k,v in tables.items()},'themes':index,
              'sources':[{'fichier':Path(p).name,'sha256':digest(p)} for p in inputs],
              'fichiers':[{'nom':p.name,'sha256':digest(p),'octets':p.stat().st_size} for p in outputs],
              'llm':{'actif':False,'etape_prevue':'J20','commentaires':'REGLES_DESCRIPTIVES'},
              'agregations_regionales':'NON_CALCULEES_J15B'}
    if commune_alignment is not None:
        incompatible=commune_alignment.loc[commune_alignment['STATUT'].isin(['CODE_ABSENT_SOURCE','PERIMETRE_INCOMPATIBLE_MEME_CODE'])]
        manifest['incompatibilites_sources_communes']=incompatible[['SOURCE','FICHIER','CODGEO','STATUT','MOTIF']].to_dict('records')
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


def load_catalogue(directory, base_directory):
    directory=Path(directory)
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version')!=1 or manifest.get('etape')!='J15B_INDICATEURS_PDF': raise ValueError('Manifeste J15b non reconnu.')
    if digest(Path(base_directory)/'manifest.json')!=manifest['base_manifest_sha256']: raise ValueError('J15a a été régénéré : réexécuter J15b pour synchroniser les exports.')
    names=[r['nom'] for r in manifest['fichiers']]
    if len(names)!=len(set(names)): raise ValueError('Fichiers J15b dupliqués.')
    for n in names:
        if Path(n).name!=n or '/' in n or '\\' in n: raise ValueError('Chemin J15b invalide.')
    row=next((r for r in manifest['fichiers'] if r['nom']=='catalogue.csv'),None)
    if row is None or digest(directory/'catalogue.csv')!=row['sha256']: raise ValueError('Catalogue absent ou différent du manifeste.')
    cat=read_table(directory/'catalogue.csv').fillna('')
    if not set(FIELDS).issubset(cat) or not cat['ID'].is_unique or len(cat)!=manifest['nb_variables']: raise ValueError('Catalogue J15b incohérent.')
    if not cat['THEME'].isin(THEMES).all(): raise ValueError('Thème J15b inconnu.')
    return cat,manifest


def load_theme(directory, manifest, level, theme):
    entry=next((e for e in manifest['themes'] if e['niveau']==level and e['theme']==theme),None)
    if entry is None: raise ValueError('Thème absent à ce niveau.')
    filename=entry['fichier']
    if Path(filename).name!=filename: raise ValueError('Nom de fichier J15b invalide.')
    row=next((r for r in manifest['fichiers'] if r['nom']==filename),None)
    path=Path(directory)/filename
    if row is None or digest(path)!=row['sha256']: raise ValueError(filename+' absent ou différent du manifeste.')
    table=read_table(path)
    pattern=r'\d{9}' if level=='IRIS' else r'\d{5}'
    if not table['__CODE'].is_unique or not table['__CODE'].str.fullmatch(pattern,na=False).all(): raise ValueError('Codes du thème invalides/dupliqués.')
    if len(table)!=manifest['nb_territoires'][level]: raise ValueError('Couverture du thème différente du manifeste.')
    return table


def descriptive_comment(label,value,unit='',reference=None,scope=''):
    """Texte déterministe ; aucun appel LLM, causalité ou prévision commerciale."""
    from app.core import fmt
    if pd.isna(value): return f'{label} : valeur indisponible pour ce territoire.'
    text=f'{label} : {fmt(value,decimals=1)} {unit}.'.strip()
    if reference is not None and pd.notna(reference):
        text+=f' Médiane descriptive des territoires comparés ({scope}) : {fmt(reference,decimals=1)} {unit}.'
        text+=' Cette médiane de comparaison n’est pas un indicateur publié pour le département ou la région.'
    return text+' Cette observation ne permet pas, seule, de conclure sur le potentiel commercial.'


def source_geography_note(manifest,metadata,code):
    files=str(metadata.get('FICHIER_SOURCE',''))
    entries=[r for r in manifest.get('incompatibilites_sources_communes',[])
        if r['CODGEO']==code and r['FICHIER'] in files]
    if not entries:return ''
    return ' '.join((r['SOURCE']+' : '+('code absent du fichier source.' if r['STATUT']=='CODE_ABSENT_SOURCE'
        else 'périmètre différent pour le même code communal ; valeur laissée indisponible.')) for r in entries)
