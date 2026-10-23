# J16 — Contrôler les données et rédiger un bilan simple

## Utilisation

Extraire le ZIP J16 à la racine de GeoMarketing_IDF puis ouvrir
notebooks/16_controler_donnees_application.ipynb. Exécuter les cellules dans l’ordre.
Le notebook réutilise pandas et NumPy, déjà employés dans le projet.
Les imports corrigent les variables de threads de l’environnement Anaconda.

## Dossiers d’entrée

Par défaut : data/app/j15 et data/app/j15b.
Pour contrôler l’organisation du dépôt déployé : app/data/app/j15 et app/data/app/j15b.
Les chemins peuvent être précisés dans le bloc 2. Les dossiers réellement utilisés sont affichés.
Le contrôle ne modifie pas les fichiers de l’application ni les exports de données.

## Résultats

OK : la règle testée est respectée.
À vérifier : relire, documenter ou expliquer.
À corriger : incohérence à traiter avant de présenter les résultats concernés.
Non testé : partie non exécutée ou vérification humaine nécessaire.

Les rapports détaillent les règles appliquées. Les évolutions, écarts, indices et soldes
ne reçoivent pas les bornes 0–100 d’une part. Les effectifs pondérés ne sont pas arrondis.
Les valeurs manquantes restent manquantes. Aucune médiane ni part n’est agrégée.

## Sorties

data/interim/j16 : inventaire, bilan, documentation, couverture, anomalies, calculs,
compatibilité des géographies, aperçu Cergy/Pontoise et tests manuels.
outputs/rapports/j16 : bilan_j16.html, synthese_j16.txt et bilan_j16.json.
Les CSV de contrôle utilisent le séparateur point-virgule et l’encodage UTF-8 avec BOM.

Les tests manuels se complètent dans controles_manuels_application_j16.csv.
États acceptés : A_FAIRE, OK, A_CORRIGER, NON_APPLICABLE. Ajouter une observation.
Relancer le notebook pour intégrer les réponses dans le bilan.

## Limites

Le contrôle ne constitue pas une validation statistique automatique de toutes les variables.
Il vérifie la structure GeoJSON et les codes ; la topologie complète et l’affichage réel
nécessitent les contrôles géométriques de préparation et les tests manuels.
Les origines, années et unités sont vérifiées pour leur présence, pas certifiées depuis Internet.
Les fréquences, validations de transport et zones accessibles seront traitées aux étapes suivantes.

## GitHub

Ajouter le notebook, scripts/controle_j16.py et ce README. Les rapports sont facultatifs après relecture.
Commit : feat: ajouter les contrôles J16 et un bilan qualité compréhensible

## Suite

J17 : commerces, cinémas, pôles d’attractivité ; J18 : GTFS ; J19 : fréquentation ;
J20–J21 : zones accessibles ; J22 : étude locale ; J23 : intégration ; J24 : partage LinkedIn.
