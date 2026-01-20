# DQE EXE - Documentation Technique

## Vue d'ensemble

L'onglet **DQE EXE** permet de générer le Devis Quantitatif Estimatif pour les projets de type **EXE** (Exécution).  
Il gère deux sous-types :
- **Transport (TE)** : Infrastructure de transport optique
- **Distribution (DE)** : Infrastructure de distribution optique

---

## Architecture

### Fichiers principaux
| Fichier | Rôle |
|---------|------|
| `dqe_exe_tab.py` | Interface UI et logique métier |
| `database_operations.py` | Exécution des requêtes SQL |
| `excel_manager.py` | Génération du rapport Excel |
| `layer_manager.py` | Création des couches QGIS |

### Classes principales
- `DQEExeTab(QWidget)` : Interface utilisateur
- `DQEWorker(QObject)` : Traitement asynchrone (partagé avec PRO)

---

## Processus de Génération

### Étape 1 : Sélection des paramètres
```
Utilisateur → Sélectionne SRO + Type (Transport/Distribution)
           → Clique "Générer DQE EXE"
```

### Étape 2 : Exécution SQL (DQEWorker)
```python
# Appel fonction PostgreSQL
DatabaseOperations.execute_dqe_exe(sro, p_type)

# Requête SQL exécutée :
SELECT * FROM dqe_exe('{sro}', '{p_type}')
```

**Retour SQL** : Lignes structurées avec désignations et quantités

### Étape 3 : Génération Excel
```python
# Fichier : excel_manager.py
ExcelManager.create_excel_report(results, sro, "EXE")

# Processus :
1. Copie du template : files/template_dqe_exe.xlsx
2. Remplissage via _fill_exe_template()
3. Sauvegarde dans %TEMP%/dqe_EXE_{sro}_{timestamp}.xlsx
4. Ouverture automatique
```

### Étape 4 : Chargement des couches QGIS
```python
# Création des couches selon les résultats
LayerManager.create_exe_layers(results, sro, layer_group)
```

---

## Processus de Validation

### Déclenchement
```
Utilisateur → Clique "Valider DQE EXE"
```

### Étape 1 : Récupération des couches actives
```python
# Récupération directe depuis QgsProject (pas de cache)
layers = QgsProject.instance().mapLayers().values()

# Filtrage des couches appartenant au groupe DQE EXE
for layer in layers:
    if layer.isValid() and is_in_dqe_exe_group(layer):
        # Traitement
```

### Etape 2 : Enregistrement dans dqejson
```python
# Table cible : dqe.dqejson
# Codes projet : TE (Transport EXE) ou DE (Distribution EXE)

# 1. Sauvegarde des resultats SQL (une seule ligne categorie='dqe_result')
INSERT INTO dqe.dqejson 
(sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
VALUES (%s, %s, %s, 'dqe_result', %s, %s, %s)

# 2. Sauvegarde des cables decoupes (Distribution uniquement)
# Methode _save_cut_cables() - recherche recursive dans le groupe
for cable_layer in collect_cable_layers(layer_group):
    layer_data = _extract_layer_data(layer)  # FeatureCollection avec geometries WKT
    INSERT INTO dqe.dqejson ... VALUES (sro, layer.name(), layer_data)
```

### Resultat validation
```
Message : "Validation terminee!"
- SRO: [code_sro]
- Type: DE
- Resultats DQE: 25
- Cables decoupes: 7
- Total: 32 elements
```

---

## Différences avec DQE PRO

| Aspect | DQE PRO | DQE EXE |
|--------|---------|---------|
| Fonction SQL | `dqe2()` | `dqe_exe()` |
| Template | `template_dqe_pro.xlsx` | `template_dqe_exe.xlsx` |
| Remplissage | `_fill_standard_template()` | `_fill_exe_template()` |
| Codes projet | TP, DP | TE, DE |

---

## Structure des données

### Codes projet EXE
| Code | Description |
|------|-------------|
| TE | EXE Transport |
| DE | EXE Distribution |

### Champs JSONB (identique à PRO)
```json
{
    "type": "sql_result",
    "designation": "...",
    "quantite": 123.45,
    "unite": "ml",
    "ids": "1,2,3,..."
}
```

---

## Flux de données

```
┌─────────────────┐
│  Interface UI   │
│  (dqe_exe_tab)  │
└────────┬────────┘
         │ SRO + Type
         ▼
┌─────────────────┐
│   DQEWorker     │
│   (Thread)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ DatabaseOps     │
│ execute_dqe_exe │
└────────┬────────┘
         │ SQL: dqe_exe(sro, type)
         ▼
┌─────────────────┐
│   PostgreSQL    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐
│  ExcelManager   │     │  LayerManager   │
│  _fill_exe_     │     │  (Couches QGIS) │
│  template()     │     │                 │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  Fichier Excel  │     │  Groupe couches │
└─────────────────┘     └─────────────────┘
         │
         │ [Validation]
         ▼
┌─────────────────┐
│  dqe.dqejson    │
└─────────────────┘
```

---

## Points d'attention

### Récupération des couches
- Utiliser `QgsProject.instance().mapLayers()` au lieu de références stockées
- Évite l'erreur "wrapped C/C++ object has been deleted"

### Validation
- **Resultats SQL** : Toutes les lignes enregistrees dans une seule entree `dqe_result`
- **Cables decoupes** : Sauvegardes avec geometries WKT (Distribution uniquement)
- **Recherche recursive** : `_save_cut_cables()` parcourt tous les sous-groupes
- **Elements sauvegardes** : Poteaux, chambres, tranchees, BPE, PA, PBO, cables FO
