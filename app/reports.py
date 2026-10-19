"""Fiches PDF vectorielles : données sourcées, aucun rendu Chrome/Kaleido."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import math
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle,getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Flowable,KeepTogether

NAVY=colors.HexColor('#132b3a');TEAL=colors.HexColor('#087f8c')
GREY=colors.HexColor('#526575');LIGHT=colors.HexColor('#eef4f6')


def fonts():
    directory=Path(__file__).parent/'assets/fonts'
    if 'GeoSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('GeoSans',str(directory/'DejaVuSans.ttf')))
        pdfmetrics.registerFont(TTFont('GeoSansBold',str(directory/'DejaVuSans-Bold.ttf')))
        pdfmetrics.registerFontFamily('GeoSans',normal='GeoSans',bold='GeoSansBold',italic='GeoSans',boldItalic='GeoSansBold')


def text(value):
    if value is None or pd.isna(value): return 'Non renseigné'
    return str(value).replace('\u2011','-').replace('\u2013','-').replace('\u2014','-')


def rings(geometry):
    if geometry['type']=='Polygon': return geometry['coordinates']
    if geometry['type']=='MultiPolygon': return [r for polygon in geometry['coordinates'] for r in polygon]
    return []


class TerritoryMap(Flowable):
    def __init__(self,bundle,commune,iris=None,width=490,height=235):
        Flowable.__init__(self)
        self.bundle=bundle;self.commune=commune;self.iris=iris;self.width=width;self.height=height

    def draw(self):
        c=self.canv;bundle=self.bundle
        outer=bundle['_communes_geo'][self.commune]['geometry']
        points=[p for ring in rings(outer) for p in ring]
        west=min(p[0] for p in points);east=max(p[0] for p in points)
        south=min(p[1] for p in points);north=max(p[1] for p in points)
        coslat=math.cos(math.radians((south+north)/2))
        dx=max((east-west)*coslat,.00001);dy=max(north-south,.00001)
        scale=min((self.width-36)/dx,(self.height-64)/dy)
        offx=(self.width-dx*scale)/2;offy=30+(self.height-58-dy*scale)/2
        c.setFillColor(colors.HexColor('#f5f8fa'));c.roundRect(0,0,self.width,self.height,9,stroke=0,fill=1)
        def shape(geometry,fill,stroke,width):
            path=c.beginPath()
            for ring in rings(geometry):
                if not ring: continue
                path.moveTo(offx+(ring[0][0]-west)*coslat*scale,offy+(ring[0][1]-south)*scale)
                for x,y,*_ in ring[1:]:path.lineTo(offx+(x-west)*coslat*scale,offy+(y-south)*scale)
                path.close()
            c.setStrokeColor(stroke);c.setLineWidth(width)
            if fill is not None:c.setFillColor(fill)
            c.drawPath(path,stroke=1,fill=int(fill is not None),fillMode=0)
        for ident in bundle['_iris_par_commune'][self.commune]:
            shape(bundle['_iris_geo'][ident]['geometry'],colors.HexColor('#f6d998') if ident==self.iris else colors.HexColor('#d5e8ec'),colors.white,.7)
        shape(outer,None,NAVY,1.8)
        c.setFillColor(GREY);c.setFont('GeoSans',7)
        c.drawString(12,10,'Contours simplifiés - affichage descriptif - sans fond externe')
        c.setFont('GeoSansBold',8);c.drawRightString(self.width-12,self.height-18,'N ↑')


def generate_report(bundle,commune,iris=None,details=(),theme='Synthèse territoriale',draft=False):
    fonts()
    from app.core import fmt,MODES
    meta=bundle['manifest']
    row=(bundle['profil_iris'].set_index('IRIS').loc[iris] if iris else bundle['profil_communes'].set_index('CODGEO').loc[commune])
    commune_name=bundle['profil_communes'].set_index('CODGEO').loc[commune,'NOM_COMMUNE']
    title=str(row['NOM_IRIS']) if iris else str(commune_name)
    scope=f"IRIS {iris} | {commune_name} ({commune})" if iris else f'Commune {commune}'
    styles=getSampleStyleSheet()
    body=ParagraphStyle('GeoBody',fontName='GeoSans',fontSize=8.6,leading=13,textColor=NAVY,spaceAfter=6)
    small=ParagraphStyle('GeoSmall',parent=body,fontSize=7.1,leading=10,textColor=GREY)
    h1=ParagraphStyle('GeoTitle',parent=body,fontName='GeoSansBold',fontSize=24,leading=29,spaceAfter=8)
    h2=ParagraphStyle('GeoSection',parent=body,fontName='GeoSansBold',fontSize=12,leading=16,textColor=TEAL,spaceBefore=14,spaceAfter=8,keepWithNext=True)
    def p(value,style=body):return Paragraph(escape(text(value)).replace('\n','<br/>'),style)
    def table(rows,widths):
        header=ParagraphStyle('GeoHead',parent=small,textColor=colors.white,fontName='GeoSansBold')
        out=Table([[p(v,header if i==0 else small) for v in r] for i,r in enumerate(rows)],colWidths=widths,repeatRows=1,hAlign='LEFT')
        out.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),NAVY),('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,LIGHT]),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LINEBELOW',(0,0),(-1,0),1,TEAL)]))
        return out
    stream=BytesIO();doc=SimpleDocTemplate(stream,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=49,bottomMargin=45,
        title='Diagnostic territorial - '+title,author='GeoMarketing IDF')
    width=A4[0]-84
    story=[p('G E O M A R K E T I N G   /   Î L E - D E - F R A N C E',small),Spacer(1,12),p(title,h1),p(scope,body),
           p(f"Population RP {meta['annee_rp']} | Géographie IRIS {meta['geographie_iris']} | Diagnostic descriptif",small)]
    if draft:story.append(p('DOCUMENT DE TRAVAIL - certaines métadonnées restent à valider.',small))
    if meta.get('donnees_controle'):story.append(p('DONNÉES DE CONTRÔLE - exemple de présentation, sans valeur d’étude réelle.',small))
    story+=[Spacer(1,10),TerritoryMap(bundle,commune,iris,width=width),p('Repères du territoire',h2)]
    basics=[['Indicateur','Valeur'],['Population',fmt(row.get('POPULATION'))],['Restaurants observés',fmt(row.get('RESTAURANTS'))],
            ['Restaurants pour 10 000 habitants',fmt(row.get('DENSITE_RESTAURANTS'),decimals=1)]]
    if iris:
        basics+=[['Niveau de vie médian annuel par UC',fmt(row.get('MEDIANE_UC'),' €')],['Taux de pauvreté',fmt(row.get('PAUVRETE_PCT'),' %',1)]]
    else:basics.append(['Actifs venant travailler dans la commune',fmt(row.get('MOBPRO_ENTRANTS'))])
    story.append(table(basics,[width*.69,width*.31]))
    if details:
        story.append(p(theme,h2))
        rows=[['Indicateur et définition','Valeur','Référence']]
        for d in details:
            desc=str(d.get('LIBELLE',''))
            if d.get('DEFINITION'):desc+='\n'+str(d['DEFINITION'])
            if d.get('STATUT_GEOGRAPHIE'):desc+='\n'+str(d['STATUT_GEOGRAPHIE'])
            provenance=' | '.join(str(d.get(k,'')) for k in ['SOURCE','ANNEE','GEOGRAPHIE'] if d.get(k)) or 'Métadonnées à compléter'
            value=d.get('VALEUR')
            value=fmt(value,decimals=1) if d.get('TYPE')=='NUMERIQUE' else text(value)
            rows.append([desc,value+' '+str(d.get('UNITE','')),provenance])
        story.append(table(rows,[width*.48,width*.18,width*.34]))
    transport=[['Mode','Lignes proches des points IRIS','Surface proche des arrêts (%)']]
    for mode,label in MODES.items():
        transport.append([label,fmt(row.get('LIGNES_'+mode)),fmt(row.get('SURFACE_'+mode+'_PCT'),decimals=1)])
    story.extend([p('Transports observés',h2),table(transport,[width*.25,width*.37,width*.38]),p('Sources et limites de lecture',h2),
        p('Les contours sont simplifiés pour l’affichage. Les données manquantes restent indisponibles. Les médianes de revenus ne sont pas additionnées ; les flux professionnels restent communaux.',small),
        p('La proximité des arrêts mesure une distance directe ou une part de surface. Elle ne mesure ni temps de marche, ni population desservie, ni fréquence ou fréquentation. Une densité de restaurants ne démontre ni saturation ni demande non satisfaite.',small),
        p('J15b : aucun commentaire généré par LLM. Les données ne constituent pas une prévision de ventes ou de rentabilité.',small)])
    seen=set()
    for d in details:
        key=tuple(str(d.get(k,'')) for k in ['SOURCE','ANNEE','GEOGRAPHIE'])
        if key in seen:continue
        seen.add(key)
        if any(key):story.append(p(' | '.join(k for k in key if k),small))
    for s in bundle['sources'].fillna('').to_dict('records'):
        line=' | '.join(str(s.get(k,'')) for k in ['source','annee_donnees','annee_geographie','url'] if s.get(k))
        if line:story.append(p(line,small))
    def footer(canvas,doc):
        canvas.saveState();canvas.setStrokeColor(TEAL);canvas.setLineWidth(.7);canvas.line(42,32,A4[0]-42,32)
        canvas.setFillColor(GREY);canvas.setFont('GeoSans',7)
        canvas.drawString(42,21,'GeoMarketing IDF | '+('Document de travail' if draft else 'Fiche descriptive'))
        canvas.drawRightString(A4[0]-42,21,f'Page {doc.page}')
        canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()
