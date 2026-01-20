# DQE PRO - Documentation Technique

## Vue d'ensemble

L'onglet **DQE PRO** permet de générer le Devis Quantitatif Estimatif pour les projets de type **PRO** (Projet).  
Il gère deux sous-types :
- **Transport (TP)** : Infrastructure de transport optique
- **Distribution (DP)** : Infrastructure de distribution optique

---

## Architecture

### Fichiers principaux
| Fichier | Rôle |
|---------|------|
| `dqe_pro_tab.py` | Interface UI et logique métier |
| `database_operations.py` | Exécution des requêtes SQL (`dqe2`) |
| `excel_manager.py` | Génération du rapport Excel |
| `layer_manager.py` | Création des couches QGIS |

### Classes principales
- `DQEProTab(QWidget)` : Interface utilisateur
- `DQEWorker(QObject)` : Traitement asynchrone en thread séparé

---

## Processus de Génération

### Étape 1 : Sélection des paramètres
```
Utilisateur → Sélectionne SRO + Type (Transport/Distribution)
           → Clique "Générer DQE PRO"
```

### Étape 2 : Exécution SQL (DQEWorker)
```python
# Appel fonction PostgreSQL dqe2
DatabaseOperations.execute_dqe_pro(sro, p_type)

# Requête SQL exécutée :
SELECT * FROM dqe2('{sro}', '{p_type}')
```

**Retour SQL** : 109 lignes structurées identiques au template Excel
- Désignations avec quantités
- En-têtes de section (Câble aérien, BPE facade, etc.)
- IDs des objets concernés

### Étape 3 : Génération Excel
```python
# Fichier : excel_manager.py
ExcelManager.create_excel_report(results, sro, "PRO")

# Processus :
1. Copie du template : files/template_dqe_pro.xlsx
2. Remplissage par index direct (ligne i → row i+2)
3. Sauvegarde dans %TEMP%/dqe_PRO_{sro}_{timestamp}.xlsx
4. Ouverture automatique
```

**Important** : L'ordre des données SQL doit correspondre exactement à l'ordre du template.

### Étape 4 : Chargement des couches QGIS
```python
# Pour Distribution uniquement
LayerManager.create_cable_layers(results, sro, layer_group)

# Couches créées :
- Câble optique de 6 FO en aérien
- Câble optique de 12 FO en aérien
- Câble de 48 FO en conduite
- etc.
```

---

## Processus de Validation

### Déclenchement
```
Utilisateur → Clique "Valider DQE PRO"
```

### Étape 1 : Vérification des prérequis
```python
# Vérifications :
- SRO sélectionné
- Résultats DQE disponibles (self.dqe_results)
```

### Étape 2 : Enregistrement des résultats SQL
```python
# Table cible : dqe.dqejson
# Pour chaque ligne avec quantité > 0 et IDs non null :

INSERT INTO dqe.dqejson 
(sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
VALUES (%s, %s, %s, %s, %s, %s, %s)

# Structure champs (JSONB) :
{
    "type": "sql_result",
    "designation": "Fourniture et pose de câble optique de 12 FO en aérien",
    "quantite": 2079.2,
    "unite": "ml",
    "ids": "145,140,147,..."
}
```

### Etape 3 : Enregistrement des cables decoupes (Distribution)
```python
# Methode _save_cut_cables() - Recherche recursive
def collect_cable_layers(group):
    # Parcourt tous les sous-groupes
    # Detecte les couches avec 'cable', 'fo ' dans le nom
    # Retourne liste des couches valides
    
# Pour chaque couche cable :
{
    "type": "FeatureCollection",
    "crs": "EPSG:2154",
    "features": [
        {"geometry": "LINESTRING(...)", "attributes": {...}},
        ...
    ]
}
```

### Resultat validation
```
Message : "Validation terminee!"
- SRO: [code_sro]
- Type: DP
- Resultats DQE: 22
- Cables decoupes: 7 (FO 6, FO 12, FO 24, etc.)
- Total: 29 elements
```

---

## Structure des données

### Table dqe.dqejson
| Colonne | Type | Description |
|---------|------|-------------|
| id | SERIAL | Clé primaire |
| sro | VARCHAR | Code SRO (ex: 63007/QRD/PMZ/50801) |
| nom_dqe | VARCHAR | Nom du DQE (ex: DQE_PRO_63007/QRD/PMZ/50801) |
| projet | VARCHAR | Code projet (TP, DP, TE, DE, PGC) |
| categorie | VARCHAR | Désignation ou nom de couche |
| champs | JSONB | Données structurées |
| user_name | VARCHAR | Utilisateur |
| audit_timestamp | TIMESTAMP | Date/heure d'enregistrement |
| version_projet | VARCHAR | Version (dqe) |

### Types de champs JSONB
```json
// Type sql_result (quantités)
{
    "type": "sql_result",
    "designation": "...",
    "quantite": 123.45,
    "unite": "ml",
    "ids": "1,2,3,..."
}

// Type FeatureCollection (géométries)
{
    "type": "FeatureCollection",
    "crs": "EPSG:2154",
    "features": [...]
}
```

---

## Fichiers template

### template_dqe_pro.xlsx
- **Localisation** : `files/template_dqe_pro.xlsx`
- **Structure** : 109 lignes de désignations
- **Sections** :
  - Lignes 2-6 : Prises, SRO, GC
  - Lignes 7-18 : TRANSPORT (câbles conduite)
  - Lignes 19-49 : DISTRIBUTION (câbles façade/aérien/sout)
  - Lignes 50-85 : BPE (facade/aérien/immeuble/sout)
  - Lignes 86-105 : PA (aérien/souterrain)
  - Lignes 106-109 : PBO

---

## Flux de données complet

```
┌─────────────────┐
│  Interface UI   │
│  (dqe_pro_tab)  │
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
│ execute_dqe_pro │
└────────┬────────┘
         │ SQL: dqe2(sro, type)
         ▼
┌─────────────────┐
│   PostgreSQL    │
│   Fonction dqe2 │
└────────┬────────┘
         │ 109 lignes
         ▼
┌─────────────────┐     ┌─────────────────┐
│  ExcelManager   │     │  LayerManager   │
│  (Rapport .xlsx)│     │  (Couches QGIS) │
└────────┬────────┘     └────────┬────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐
│  Fichier Excel  │     │  Groupe couches │
│  (ouvert auto)  │     │  dans QGIS      │
└─────────────────┘     └─────────────────┘
         │
         │ [Validation]
         ▼
┌─────────────────┐
│  dqe.dqejson    │
│  (PostgreSQL)   │
└─────────────────┘
```

---

## Points d'attention

### Performance
- L'exécution SQL est asynchrone (QThread) pour ne pas bloquer l'UI
- Le chargement des couches est optimisé par batch

### Intégrité des données
- L'ordre des lignes SQL doit correspondre exactement au template
- Le filtrage par template a été désactivé pour éviter les décalages

### Validation
- **Resultats SQL** : Toutes les lignes sont enregistrees dans une seule entree `dqe_result`
- **Cables decoupes** : Sauvegardes separement avec geometries WKT (Distribution uniquement)
- **Recherche recursive** : `_save_cut_cables()` parcourt tous les sous-groupes
- **Elements sauvegardes** : RBAL, RAD, DTR, BPE, PA, PBO, cables FO 6/12/24/48/72/144/288

---

## Codes projet
| Code | Description |
|------|-------------|
| TP | PRO Transport |
| DP | PRO Distribution |
| TE | EXE Transport |
| DE | EXE Distribution |
| PGC | Plan de Gestion de Configuration |
