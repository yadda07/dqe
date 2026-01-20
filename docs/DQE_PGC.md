# DQE PGC - Documentation Technique

## Vue d'ensemble

L'onglet **DQE PGC** permet de générer le Devis Quantitatif Estimatif pour les projets de type **PGC** (Plan de Gestion de Configuration).  
Cet onglet gère également les données de **redevance**.

---

## Architecture

### Fichiers principaux
| Fichier | Rôle |
|---------|------|
| `dqe_pgc_tab.py` | Interface UI et logique métier |
| `database_operations.py` | Exécution des requêtes SQL |
| `excel_manager.py` | Génération du rapport Excel |
| `layer_manager.py` | Création des couches QGIS |

### Classes principales
- `DQEPGCTab(QWidget)` : Interface utilisateur
- `DQEWorker(QObject)` : Traitement asynchrone

---

## Processus de Génération

### Étape 1 : Sélection des paramètres
```
Utilisateur → Sélectionne SRO + Tronçon (optionnel)
           → Clique "Générer DQE PGC"
```

### Étape 2 : Exécution SQL (DQEWorker)
```python
# Appel fonction PostgreSQL
DatabaseOperations.execute_dqe_pgc(sro, troncon)

# Requête SQL exécutée :
SELECT * FROM dqe_pgc('{sro}', '{troncon}')
```

**Retour SQL** : Lignes structurées avec :
- Désignations et quantités
- Données de redevance (si disponibles)

### Étape 3 : Génération Excel
```python
# Fichier : excel_manager.py
ExcelManager.create_excel_report(results, sro, "PGC", troncon)

# Processus :
1. Copie du template : files/template_dqe_pgc.xlsx
2. Remplissage via _fill_pgc_template()
3. Ajout des données redevance (si disponibles)
4. Sauvegarde dans %TEMP%/dqe_PGC_{sro}_{troncon}_{timestamp}.xlsx
5. Ouverture automatique
```

### Étape 4 : Chargement des couches QGIS
```python
# Création des couches PGC
LayerManager.create_pgc_layers(results, sro, troncon, layer_group)
```

---

## Processus de Validation

### Déclenchement
```
Utilisateur → Clique "Valider DQE PGC"
```

### Étape 1 : Récupération des couches actives
```python
# Récupération directe depuis QgsProject
layers = QgsProject.instance().mapLayers().values()

# Filtrage des couches appartenant au groupe DQE PGC
for layer in layers:
    if layer.isValid() and is_in_dqe_pgc_group(layer):
        # Traitement
```

### Etape 2 : Enregistrement dans dqejson
```python
# Table cible : dqe.dqejson
# Code projet : GC (Genie Civil PGC)

# 1. Sauvegarde de chaque couche QGIS
for layer in layers_loaded:
    layer_data = _extract_layer_data(layer)  # FeatureCollection avec geometries WKT
    INSERT INTO dqe.dqejson 
    (sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
    VALUES (%s, 'DQE_PGC_sro', 'GC', layer.name(), layer_data, user, troncon)

# 2. Sauvegarde des resultats SQL (categorie='dqe_result')
# Support dict et object pour extraction des donnees
if hasattr(result, 'designation'):
    designation = result.designation
else:
    designation = result.get('designation') or result.get('Designation')
```

### Resultat validation
```
Message : "Validation terminee!"
- SRO: [code_sro]
- Type: GC
- Couches sauvegardees: 12/12
- Resultats DQE: 28 lignes
```

---

## Données de Redevance

### Structure
```python
# Données redevance attachées aux résultats
result.redevance_data = [
    {"designation": "...", "quantite": 123, "unite": "ml"},
    ...
]
```

### Remplissage Excel
```python
# Dans _fill_pgc_template()
if redevance_data:
    # Remplir la section REDEVANCE du template
    for i, row in enumerate(redevance_data):
        sheet.cell(row=redevance_start + i, column=1).value = row['designation']
        sheet.cell(row=redevance_start + i, column=3).value = row['quantite']
```

---

## Structure des données

### Code projet
| Code | Description |
|------|-------------|
| PGC | Plan de Gestion de Configuration |

### Champs JSONB
```json
{
    "type": "sql_result",
    "designation": "...",
    "quantite": 123.45,
    "unite": "ml",
    "troncon": "T01"
}
```

---

## Flux de données

```
┌─────────────────┐
│  Interface UI   │
│  (dqe_pgc_tab)  │
└────────┬────────┘
         │ SRO + Tronçon
         ▼
┌─────────────────┐
│   DQEWorker     │
│   (Thread)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ DatabaseOps     │
│ execute_dqe_pgc │
└────────┬────────┘
         │ SQL: dqe_pgc(sro, troncon)
         ▼
┌─────────────────┐
│   PostgreSQL    │
└────────┬────────┘
         │
         ├── Données DQE
         └── Données Redevance
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  ExcelManager   │     │  LayerManager   │
│  _fill_pgc_     │     │  (Couches QGIS) │
│  template()     │     │                 │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  Fichier Excel  │     │  Groupe couches │
│  + Redevance    │     │  DQE PGC        │
└─────────────────┘     └─────────────────┘
         │
         │ [Validation]
         ▼
┌─────────────────┐
│  dqe.dqejson    │
└─────────────────┘
```

---

## Template Excel

### template_dqe_pgc.xlsx
- **Localisation** : `files/template_dqe_pgc.xlsx`
- **Sections** :
  - DQE principal
  - Section REDEVANCE (si données disponibles)

---

## Points d'attention

### Tronçon
- Le paramètre tronçon est optionnel
- S'il est fourni, les données sont filtrées par tronçon

### Redevance
- Les données de redevance sont extraites séparément
- Elles sont remplies dans une section dédiée du template

### Recuperation des couches
- Utiliser `QgsProject.instance().mapLayers()` au lieu de references stockees
- Evite l'erreur "wrapped C/C++ object has been deleted"

### Validation
- **Couches QGIS** : Chaque couche est sauvegardee avec ses geometries WKT
- **Resultats SQL** : Support dict et object pour extraction flexible des donnees
- **Categories** : GC - TDR + RAD, Chambres, Poteaux, Fourniture des alveoles
- **Modes** : Direct (rapide) ou Gestionnaire (corrections manuelles possibles)
