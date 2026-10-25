"""Insertion contrôlée J18 ; sauvegarde et préservation des ajouts J15b/J17."""
from pathlib import Path
from datetime import datetime, timezone
import ast
import shutil


def inserer_apres(source, node, texte):
    lines = source.splitlines(keepends=True)
    indent = lines[node.lineno-1][:len(lines[node.lineno-1])-len(lines[node.lineno-1].lstrip())]
    lines.insert(node.end_lineno,''.join(indent+x+'\n' for x in texte.splitlines()))
    return ''.join(lines)


def comparaison_vue(node,value,operator):
    if not isinstance(node,ast.Compare) or len(node.ops)!=1 or not isinstance(node.ops[0],operator): return False
    return isinstance(node.left,ast.Name) and node.left.id=='view' and len(node.comparators)==1 and (
        isinstance(node.comparators[0],ast.Constant) and node.comparators[0].value==value)


def installer(root):
    root = Path(root); main = root/'app/streamlit_app.py'; core = root/'app/core.py'
    src = main.read_text(encoding='utf-8-sig'); cs = core.read_text(encoding='utf-8-sig')
    if '# J18_INTEGRATION_GTFS' in src and '# J18_GEOMETRIES_A_LA_DEMANDE' in cs:
        return {'modifie':False,'message':'J18 est déjà installé.'}
    if '# J18_INTEGRATION_GTFS' in src or '# J18_GEOMETRIES_A_LA_DEMANDE' in cs:
        raise ValueError('Installation J18 partielle : restaurer les deux fichiers de la même sauvegarde, puis réinstaller.')
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
    if not {'ROOT','DATA','data','code','ident','view'}.issubset(names):
        raise ValueError('Structure différente de l’application : utiliser l’intégration manuelle du guide, sans écraser streamlit_app.py.')
    calls = [n for n in ast.walk(tree) if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='data' for t in n.targets)
        and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='charger']
    if len(calls)!=1: raise ValueError('Chargement du socle non identifié de façon univoque.')
    src = inserer_apres(src,calls[0],'# J18_INTEGRATION_GTFS\nfrom app.transports_j18 import activer_couches_j18, afficher_transports_j18\ndata = activer_couches_j18(ROOT, DATA, data)')
    tree = ast.parse(src)
    targets = [n for n in ast.walk(tree) if isinstance(n,ast.If)
        and isinstance(n.test,ast.Compare) and isinstance(n.test.left,ast.Name) and n.test.left.id=='view'
        and len(n.test.ops)==1 and isinstance(n.test.ops[0],ast.NotIn)
        and isinstance(n.test.comparators[0],(ast.List,ast.Tuple))
        and {'Sources et méthode','Indicateurs détaillés'}.issubset({x.value for x in n.test.comparators[0].elts if isinstance(x,ast.Constant)})]
    if len(targets)!=1: raise ValueError('Bloc de carte générale non reconnu. Voir l’intégration manuelle du guide.')
    segment = ast.get_source_segment(src,targets[0].test)
    src = src.replace(segment,'('+segment+") and not (view == 'Transports' and data.get('_j18_directory'))",1)
    tree = ast.parse(src)
    branches = [n for n in ast.walk(tree) if isinstance(n,ast.If) and comparaison_vue(n.test,'Transports',ast.Eq)]
    if len(branches)!=1: raise ValueError('Branche Transports non identifiée.')
    branch = branches[0]
    src = inserer_apres(src,branch.body[-1],"if data.get('_j18_directory'):\n    afficher_transports_j18(ROOT, DATA, data, code, ident or None)")
    ct = ast.parse(cs)
    fs = [n for n in ct.body if isinstance(n,ast.FunctionDef) and n.name=='build_territory_map']
    if len(fs)!=1 or not {'bundle','commune_code','regional'}.issubset({x.arg for x in fs[0].args.args}):
        raise ValueError('Signature du constructeur de carte différente : voir le guide.')
    f = fs[0]; lines = cs.splitlines(keepends=True)
    position = f.body[0].lineno-1
    if isinstance(f.body[0],ast.Expr) and isinstance(f.body[0].value,ast.Constant) and isinstance(f.body[0].value.value,str):
        position = f.body[0].end_lineno
    indent = ' ' * f.body[0].col_offset
    lines.insert(position,indent+'# J18_GEOMETRIES_A_LA_DEMANDE\n'+indent+'from app.transports_j18 import enrichir_carte_j18\n'+indent+'bundle = enrichir_carte_j18(bundle, commune_code, regional)\n')
    cs = ''.join(lines)
    ast.parse(src); ast.parse(cs)
    backup = root/'data/interim/j18/sauvegardes_code'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    backup.mkdir(parents=True,exist_ok=True)
    shutil.copy2(main,backup/'streamlit_app.py'); shutil.copy2(core,backup/'core.py')
    main.write_text(src,encoding='utf-8'); core.write_text(cs,encoding='utf-8')
    for req in [root/'requirements.txt',root/'app/requirements.txt']:
        if req.is_file():
            text = req.read_text(encoding='utf-8')
            if not any(x.strip().lower().startswith('pyarrow') for x in text.splitlines()):
                shutil.copy2(req,backup/(req.parent.name+'_requirements.txt'))
                req.write_text(text.rstrip()+'\npyarrow\n',encoding='utf-8')
    return {'modifie':True,'sauvegarde':str(backup),'message':'J18 installé. Redémarrer Streamlit pour recharger les modules Python.'}
