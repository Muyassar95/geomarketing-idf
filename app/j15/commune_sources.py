"""Importer les profils J12/J13e sur la géographie active, sans perdre les sources."""
from pathlib import Path
import re
import numpy as np
import pandas as pd
from app.indicators import numbers,read_table

FUSION_CODES={'93059','93066'}
FUSION_REFERENCE='https://www.insee.fr/fr/metadonnees/geographie/commune/93066-saint-denis'


def unique_value(table,column):
    if column not in table:return ''
    vals=table[column].dropna().astype(str).str.strip().unique()
    return str(vals[0]) if len(vals)==1 else ''


def label_for(column):
    """Proposition éditoriale explicite : ne valide pas la définition statistique."""
    c=re.sub(r'__SOURCE_J(?:12|13E)$','',column)
    c=re.sub(r'^J(?:12|13D|13E)_','',c)
    c=c.replace('_PCT',' (%)').replace('_EUROS',' (€)')
    words={
        'NB':'nombre','OBS':'observations','POP':'population','RP2023':'RP 2023',
        'HAB':'habitants','PCS':'PCS','IRIS':'IRIS','KM2':'km²','H':'hommes','F':'femmes',
        'MENAGES':'ménages','AGE':'âge','SCOLARISES':'scolarisés','SCOLARISEE':'scolarisée',
        'DIPLOMES':'diplômes','DIPLOME':'diplôme','EMPLOYES':'employés','SALARIES':'salariés',
        'RETRAITES':'retraités','RESIDENTS':'résidents','RESIDENCE':'résidence',
        'DENSITE':'densité','MEDIAN':'médian','MEDIANE':'médiane','PAUVRETE':'pauvreté',
        'ACTIVITE':'activité','INTERMEDIAIRES':'intermédiaires','ETUDIANTS':'étudiants',
        'RESTAURATION':'restauration','TRADITIONNELLE':'traditionnelle','EQUIPEMENTS':'équipements',
        'SANTE':'santé','COUPLE':'couple','ENFANTS':'enfants','ALIMENTAIRES':'alimentaires',
    }
    tokens=c.split('_');out=[];i=0
    while i<len(tokens):
        if i+1<len(tokens) and re.fullmatch(r'\d{1,2}',tokens[i]) and re.fullmatch(r'\d{1,2}',tokens[i+1]):
            out.append(tokens[i]+' à '+tokens[i+1]+' ans');i+=2;continue
        out.append(words.get(tokens[i],tokens[i].lower()));i+=1
    label=' '.join(out)
    return label[0].upper()+label[1:] if label else column


def hints_for(column,table,source):
    c=column.upper();unit='';year='';geo='';origin=source
    years=re.findall(r'(?<!\d)(?:19|20)\d{2}(?!\d)',c)
    if years:year=' - '.join(dict.fromkeys(years))
    if c.endswith('_PCT'):unit='%'
    elif '10000_HAB' in c:unit='pour 10 000 habitants'
    elif '1000_EMPLOIS' in c:unit='pour 1 000 emplois'
    elif '1000_HAB' in c:unit='pour 1 000 habitants'
    elif '100_HAB' in c:unit='pour 100 habitants'
    elif c.endswith('_KM2'):unit='km²' if 'SURFACE' in c or 'SUPERFICIE' in c else 'par km²'
    elif 'EUROS' in c or 'NIVEAU_VIE_MEDIAN' in c:unit='euros'
    elif c.startswith('NB_') or c.startswith(('J13D_NB_','J13E_NB_')):unit='observations (unité à confirmer)'
    if source=='J12':
        geo='Périmètre du fichier J12 ; Saint-Denis fusionné avec Pierrefitte'
        fiscal=any(x in c for x in ['REVENU','NIVEAU_VIE','PAUVRETE'])
        if fiscal:
            year=year or unique_value(table,'MILLESIME_REVENUS')
            geo=unique_value(table,'GEOGRAPHIE_REVENUS') or geo
            origin=unique_value(table,'SOURCE_REVENUS') or origin
    else:
        geo=unique_value(table,'J13D_GEOGRAPHIE') or 'Périmètre du fichier J13e'
        if c.startswith('J13D_') or c in {'J13E_POPULATION','J13E_POP_1529','J13E_PART_1529_PCT'}:
            year=year or unique_value(table,'J13D_ANNEE_RP')
    return {'LIBELLE':label_for(column),'UNITE':unit,'ANNEE':year,'GEOGRAPHIE':geo,
            'SOURCE':origin+' - '+('profil_communes_idf_j12.csv' if source=='J12' else 'profil_communes_idf_j13e.csv')}


def same_values(left,right):
    l=left.astype('string').str.strip();r=right.astype('string').str.strip()
    same=l.eq(r).fillna(False)
    ln,lb=numbers(l);rn,rb=numbers(r)
    numeric=ln.notna()&rn.notna()&~lb&~rb
    if numeric.any():same.loc[numeric]=np.isclose(ln.loc[numeric],rn.loc[numeric],rtol=1e-11,atol=1e-8)
    return same


def merge_sources(target,provenance,sources,geography_target=None):
    """Jointure gauche par code, colonnes en conflit conservées sous un alias explicite.

    La présence de 93059 identifie les tables avant fusion. Si 93066 est présent
    seul, la géographie déclarée et le périmètre des fichiers fournis sont contrôlés.
    Aucun taux, médiane ou flux n'est désagrégé depuis une commune fusionnée.
    """
    out=target.copy();origin=dict(provenance);hints={};reports=[];conflicts=[];summary=[]
    codes=set(out['__CODE']);positions=out.set_index('__CODE').index
    if not out['__CODE'].is_unique:raise ValueError('Clés cibles communales dupliquées.')
    prepared=[]
    for cfg in sources:
        raw=read_table(cfg['fichier'])
        if 'CODGEO' not in raw or not raw['CODGEO'].is_unique or not raw['CODGEO'].str.fullmatch(r'\d{5}',na=False).all():
            raise ValueError(Path(cfg['fichier']).name+' : CODGEO absent, invalide ou dupliqué.')
        prepared.append((cfg,raw))
    exact_modes={'93059' in set(raw['CODGEO']) for _,raw in prepared if set(raw['CODGEO'])==codes and '93066' in codes}
    if len(exact_modes)==1:target_old=exact_modes.pop()
    elif '93059' in codes:target_old=True
    elif '93066' in codes:
        try:year=int(str(geography_target)[:4])
        except (TypeError,ValueError):raise ValueError('Géographie cible de Saint-Denis à préciser avant jointure.')
        target_old=year<2025
        if target_old:raise ValueError('Géographie cible avant 2025 mais Pierrefitte absente. Vérifier les profils/contours avant import.')
    else:target_old=None
    for cfg,raw in prepared:
        source=cfg['source'];path=Path(cfg['fichier'])
        source_codes=set(raw['CODGEO']);source_old='93059' in source_codes
        blocked=set()
        if target_old is not None and source_old!=target_old and '93066' in codes and '93066' in source_codes:
            blocked.add('93066')
        active=raw.set_index('CODGEO').reindex(positions)
        active.index=out.index
        if blocked:active.loc[out['__CODE'].isin(blocked),:]=pd.NA
        new_columns={};n_new=0;n_shared=0;n_conflict=0
        for col in raw:
            if col=='CODGEO':continue
            values=active[col]
            if col not in out:
                new_columns[col]=values;origin[col]=path.name;hints[col]=hints_for(col,raw,source);n_new+=1;continue
            both=out[col].notna()&values.notna()
            disagreement=both&~same_values(out[col],values)
            if disagreement.any():
                alias=col+'__SOURCE_'+source
                if alias in out or alias in new_columns:raise ValueError('Alias source déjà présent : '+alias)
                new_columns[alias]=values;origin[alias]=path.name
                hints[alias]=hints_for(col,raw,source)
                hints[alias]['LIBELLE']+=' - source '+source
                for i in out.index[disagreement]:
                    conflicts.append({'SOURCE':source,'COLONNE':col,'COLONNE_CONSERVEE':alias,
                        'CODGEO':out.at[i,'__CODE'],'VALEUR_CIBLE':out.at[i,col],'VALEUR_SOURCE':values.loc[i]})
                n_conflict+=1
            else:
                # Le complément ne remplace aucune valeur déjà présente.
                fill=out[col].isna()&values.notna()
                if fill.any():
                    out.loc[fill,col]=values.loc[fill]
                    origin[col]=origin.get(col,'')+' | '+path.name
                n_shared+=1
        if new_columns:out=pd.concat([out,pd.DataFrame(new_columns,index=out.index)],axis=1)
        for code in sorted(codes|source_codes):
            if code not in codes:status='HORS_GEOGRAPHIE_CIBLE'
            elif code not in source_codes:status='CODE_ABSENT_SOURCE'
            elif code in blocked:status='PERIMETRE_INCOMPATIBLE_MEME_CODE'
            else:status='APPARIE'
            reports.append({'SOURCE':source,'FICHIER':path.name,'CODGEO':code,'STATUT':status,
                'MOTIF':('Fusion Saint-Denis/Pierrefitte : données non réparties entre anciens contours' if code in blocked else ''),
                'REFERENCE':FUSION_REFERENCE if code in FUSION_CODES else ''})
        summary.append({'SOURCE':source,'FICHIER':path.name,'NB_COMMUNES_SOURCE':len(raw),
            'NB_COLONNES_SOURCE':len(raw.columns),'NB_VARIABLES_AJOUTEES':n_new,'NB_COLONNES_COMMUNES_COMPATIBLES':n_shared,
            'NB_COLONNES_CONFLIT_CONSERVEES':n_conflict,'NB_CODES_ABSENTS_SOURCE':len(codes-source_codes),
            'NB_CODES_BLOQUES_GEOGRAPHIE':len(blocked),'NB_CODES_SOURCE_HORS_CIBLE':len(source_codes-codes)})
    if set(out['__CODE'])!=codes or len(out)!=len(target):raise ValueError('La jointure a modifié la couverture cible.')
    return out,origin,hints,pd.DataFrame(reports),pd.DataFrame(conflicts,columns=['SOURCE','COLONNE','COLONNE_CONSERVEE','CODGEO','VALEUR_CIBLE','VALEUR_SOURCE']),pd.DataFrame(summary)
