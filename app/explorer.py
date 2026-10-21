"""Exploration à la demande des données J14 à leur maille de publication."""
import html
import json
from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from app.core import build_territory_map,territory_event,fmt
from app.indicators import load_catalogue,load_theme,numbers,THEMES,digest,descriptive_comment,source_geography_note
from app.reports import generate_report
from app.territory_map import territory_map


@st.cache_data(max_entries=4,show_spinner='Chargement du catalogue des indicateurs…')
def catalogue_cached(directory,base,signature):
    return load_catalogue(directory,base)


@st.cache_data(max_entries=6,show_spinner='Chargement du thème sélectionné…')
def theme_cached(directory,manifest_json,level,theme):
    return load_theme(directory,json.loads(manifest_json),level,theme)


def show_explorer(bundle,base_directory,directory,commune,iris,assets,outline=True):
    directory=Path(directory)
    st.subheader('Explorer les indicateurs détaillés')
    if not (directory/'manifest.json').is_file():
        st.info('Exécuter le notebook J15b puis déposer ses exports dans data/app/j15b pour ouvrir le catalogue détaillé.')
        return
    try:
        cat,meta=catalogue_cached(str(directory),str(base_directory),digest(directory/'manifest.json'))
    except (ValueError,OSError,KeyError) as e:
        st.error('Exports J15b à vérifier : '+str(e));return
    st.caption(f"{len(cat):,} variables inventoriées · Fichiers chargés par thème · Aucun calcul automatique de total départemental ou régional".replace(',',' '))
    levels=[x for x in ['COMMUNE','IRIS'] if x in set(cat['NIVEAU'])]
    level=st.selectbox('Échelle des données',levels,index=levels.index('IRIS') if iris and 'IRIS' in levels else 0,key='detail_niveau')
    show_technical=st.checkbox('Inclure les codes, statuts et métadonnées',False,key='detail_technique')
    show_drafts=st.checkbox('Inclure les indicateurs dont les métadonnées restent à valider',True,key='detail_brouillons')
    filtered=cat.loc[cat['NIVEAU'].eq(level)].copy()
    if not show_technical:filtered=filtered.loc[~filtered['THEME'].eq('TECHNIQUE')]
    if not show_drafts:filtered=filtered.loc[filtered['VALIDE'].eq('OUI')]
    search=st.text_input('Rechercher un indicateur',placeholder='Âge, ménages, cadres, logements…',key='detail_recherche').strip()
    if search:
        filtered=filtered.loc[(filtered['LIBELLE']+' '+filtered['COLONNE']+' '+filtered['DEFINITION']).str.contains(search,case=False,regex=False,na=False)]
    if filtered.empty:
        st.info('Aucun indicateur dans cette sélection. Modifier la recherche ou les filtres de validation.');return
    themes=[x for x in THEMES if x in set(filtered['THEME'])]
    if st.session_state.get('detail_theme') not in themes:st.session_state['detail_theme']=themes[0]
    theme=st.selectbox('Thème',themes,index=themes.index(st.session_state['detail_theme']),format_func=lambda x:THEMES[x],key='detail_theme')
    rows=filtered.loc[filtered['THEME'].eq(theme)]
    ids=rows['ID'].tolist();labels=rows.set_index('ID')['LIBELLE'].to_dict()
    if st.session_state.get('detail_variable') not in ids:st.session_state['detail_variable']=ids[0]
    selected=st.selectbox('Indicateur',ids,index=ids.index(st.session_state['detail_variable']),format_func=lambda x:labels[x],key='detail_variable')
    metadata=rows.set_index('ID').loc[selected].to_dict();column=metadata['COLONNE']
    if metadata['VALIDE']!='OUI':
        st.warning('Indicateur en cours de documentation : vérifier son libellé, son unité, son millésime et sa géographie avant diffusion à un client.')
    if theme=='PRESELECTION':st.caption('Les classements J12 sont exploratoires : ils ne constituent pas une prévision de ventes ou de rentabilité.')
    try:
        table=theme_cached(str(directory),json.dumps(meta,sort_keys=True),level,theme)
    except (ValueError,OSError,KeyError) as e:
        st.error('Thème à vérifier : '+str(e));return
    expected=set(bundle['profil_iris']['IRIS'] if level=='IRIS' else bundle['profil_communes']['CODGEO'])
    if set(table['__CODE'])!=expected:
        st.error('Les territoires détaillés ne correspondent pas aux contours J15a. Réexécuter J15b.');return
    focus=table.loc[table['__CODGEO'].eq(commune)] if level=='IRIS' else table
    current=iris if level=='IRIS' else commune
    if not current and level=='IRIS':
        st.info('La carte présente tous les IRIS de la commune. Choisir un IRIS dans le menu latéral ou cliquer sur la carte pour sa valeur et son PDF.')
    value=(table.set_index('__CODE').loc[current,column] if current else pd.NA)
    if level=='COMMUNE' and pd.isna(value):
        geo_note=source_geography_note(meta,metadata,commune)
        if geo_note:st.warning(geo_note)
    numeric=metadata['TYPE']=='NUMERIQUE'
    if numeric:
        vals,bad=numbers(table[column])
        if bad.any():
            st.error('La colonne est déclarée numérique mais contient des valeurs non interprétables. Vérifier les sources/corrections.');return
        table=table.assign(__VALUE=vals)
        value=table.set_index('__CODE').loc[current,'__VALUE'] if current else float('nan')
        st.metric(metadata['LIBELLE'],fmt(value,unit=' '+metadata['UNITE'],decimals=1))
        mapped=bundle.copy()
        key='IRIS' if level=='IRIS' else 'CODGEO';profile='profil_iris' if level=='IRIS' else 'profil_communes'
        mapped[profile]=bundle[profile].copy()
        mapped[profile]['J15B_SELECTION']=mapped[profile][key].map(table.set_index('__CODE')['__VALUE'])
        dep=st.session_state.get('departement','Tous')
        fig,_=build_territory_map(mapped,commune,iris or None if level=='IRIS' else None,
            regional=level=='COMMUNE',department=dep,indicator='J15B_SELECTION',show_commune_outline=outline)
        label=html.escape(metadata['LIBELLE'])
        for trace in fig.data:
            if hasattr(trace,'colorbar') and trace.showscale:trace.colorbar.title.text=label[:65]+'<br>'+html.escape(metadata['UNITE'])
            if getattr(trace,'text',None):trace.text=[str(t).replace('J15B_SELECTION',label) for t in trace.text]
        event=territory_map(fig,bundle,assets,key='carte_indicateurs_j15b')
        action=territory_event(event,bundle)
        if action and action['event_id']!=st.session_state.get('_last_territory_event'):
            st.session_state['_last_territory_event']=action['event_id']
            action['detail_niveau']='IRIS'
            st.session_state['_territoire_action']=action
            st.rerun()
        st.caption('Limite communale : trait sombre. Limites IRIS : traits fins. Gris : valeur indisponible. Aucun fond externe ni clé API.')
        compare=table.loc[table['__CODGEO'].eq(commune)] if level=='IRIS' else table.loc[table['__CODGEO'].str[:2].eq(commune[:2])]
        options=compare['__CODE'].tolist();names=compare.set_index('__CODE')['__NOM'].to_dict()
        context=level+'_'+commune
        if st.session_state.get('_comparison_context')!=context:
            st.session_state['detail_pairs']=([current] if current in options else [])+[x for x in options if x!=current][:5]
            st.session_state['_comparison_context']=context
        peers=st.multiselect('Territoires à comparer (12 maximum)',options,format_func=lambda x:str(names[x])+' ('+x+')',max_selections=12,key='detail_pairs')
        chart=compare.loc[compare['__CODE'].isin(peers)].copy()
        chart['Territoire']=chart['__NOM'].fillna(chart['__CODE'])+' ('+chart['__CODE']+')'
        if not chart['__VALUE'].dropna().empty:
            chart=chart.sort_values('__VALUE')
            f=px.bar(chart,x='__VALUE',y='Territoire',orientation='h',color_discrete_sequence=['#087f8c'],
                labels={'__VALUE':metadata['LIBELLE']+' ('+metadata['UNITE']+')'},title='Comparaison du même indicateur à la même maille')
            f.update_layout(template='plotly_white',height=max(300,len(chart)*36+90),margin=dict(l=5,r=15,t=60,b=10))
            st.plotly_chart(f,use_container_width=True,config={'displaylogo':False})
        if current:st.write(descriptive_comment(metadata['LIBELLE'],value,metadata['UNITE']))
    else:
        st.write(metadata['LIBELLE']+' : '+('Non disponible' if pd.isna(value) else str(value)))
        st.caption('Variable textuelle : consultation en tableau, sans échelle numérique ni moyenne.')
    with st.expander('Définition, source et méthode',expanded=False):
        st.dataframe(pd.DataFrame([{'Champ':k,'Information':metadata.get(k,'')} for k in ['COLONNE','UNITE','ANNEE','GEOGRAPHIE','SOURCE','DEFINITION','AGREGATION','METADONNEES','COUVERTURE_PCT']]),hide_index=True,width='stretch')
        st.caption('J15b conserve la maille publiée. Les rapprochements et agrégations région/département devront être explicitement documentés dans J15c.')
    subset=table.loc[table['__CODGEO'].eq(commune)] if level=='IRIS' else table
    shown=subset[['__CODE','__NOM',column]].rename(columns={'__CODE':'Code','__NOM':'Territoire',column:metadata['LIBELLE']})
    st.dataframe(shown,hide_index=True,width='stretch')
    st.download_button('Télécharger les valeurs sélectionnées (CSV)',shown.to_csv(index=False,sep=';').encode('utf-8-sig'),file_name='indicateur_'+selected+'.csv',mime='text/csv',key='detail_csv')
    if current:
        report_rows=cat.loc[cat['NIVEAU'].eq(level)&cat['THEME'].eq(theme)]
        choices=report_rows['ID'].tolist();report_labels=report_rows.set_index('ID')['LIBELLE'].to_dict()
        context=level+'_'+theme
        if st.session_state.get('_report_context')!=context:
            st.session_state['detail_pdf_variables']=[selected];st.session_state['_report_context']=context
        picked=st.multiselect('Indicateurs à inclure dans la fiche PDF (12 maximum)',choices,format_func=lambda x:report_labels[x],max_selections=12,key='detail_pdf_variables')
        details=[]
        for d in report_rows.loc[report_rows['ID'].isin(picked)].to_dict('records'):
            raw=table.set_index('__CODE').loc[current,d['COLONNE']]
            if d['TYPE']=='NUMERIQUE':
                numeric_value,invalid=numbers(pd.Series([raw],dtype='string'))
                if invalid.any():st.error('Une valeur PDF numérique doit être corrigée.');return
                raw=numeric_value.iloc[0]
            details.append({**d,'VALEUR':raw,'STATUT_GEOGRAPHIE':source_geography_note(meta,d,current) if level=='COMMUNE' and pd.isna(raw) else ''})
        draft=any(d['VALIDE']!='OUI' for d in details)
        pdf=generate_report(bundle,commune,current if level=='IRIS' else None,details,THEMES[theme],draft=draft)
        st.download_button('Télécharger la fiche territoriale (PDF)',pdf,file_name='fiche_'+current+'.pdf',mime='application/pdf',key='detail_pdf')
        if draft:st.caption('La fiche porte la mention « Document de travail » tant que les métadonnées sélectionnées ne sont pas validées.')
