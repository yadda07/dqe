# DQE Recover - Documentation Technique

**Version:** 3.2.0  
**Module:** `dqe_recover_tab.py`

## Vue d'ensemble

L'onglet **DQE Recover** permet de **récupérer et régénérer** les DQE précédemment validés.  
Il offre la possibilité de :
- Consulter l'historique des validations
- Régénérer les fichiers Excel
- Recréer les couches QGIS
- Aperçu HTML stylisé avec watermark "ARCHIVÉ"

---

## Architecture

### Fichiers principaux
| Fichier | Rôle |
|---------|------|
| `dqe_recover_tab.py` | Interface UI et logique métier |
| `excel_manager.py` | Régénération du rapport Excel |
| `dqe_utils.py` | Connexion base de données |

### Classes principales
- `DQERecoverTab(QWidget)` : Interface utilisateur

---

## Interface Utilisateur

### Filtres disponibles
| Filtre | Description |
|--------|-------------|
| Type | PRO Transport (TP), PRO Distribution (DP), EXE Transport (TE), EXE Distribution (DE), PGC |
| SRO | Recherche partielle (ILIKE) |

### Table des résultats
| Colonne | Description |
|---------|-------------|
| SRO | Code SRO |
| Type | Code projet (TP, DP, TE, DE, PGC) |
| Nom DQE | Identifiant du DQE |
| Lignes | Nombre de lignes archivées |
| Date création | Date/heure de validation |
| Utilisateur | Utilisateur ayant validé |

### Actions disponibles
- **Régénérer Excel** : Recrée le fichier Excel
- **Régénérer couches** : Recrée les couches QGIS
- **Tout régénérer** : Excel + couches

---

## Processus de Récupération

### Étape 1 : Recherche des DQE archivés
```python
# Requête SQL avec GROUP BY date pour séparer les validations
query = """
    SELECT 
        sro, projet, nom_dqe,
        COUNT(*) as nb_lignes,
        MIN(audit_timestamp) as date_creation,
        MAX(user_name) as user_name,
        DATE(MIN(audit_timestamp)) as date_validation
    FROM dqe.dqejson
    {where_clause}
    GROUP BY sro, projet, nom_dqe, DATE(audit_timestamp)
    ORDER BY MIN(audit_timestamp) DESC
    LIMIT 30
"""
```

**Important** : Le GROUP BY inclut `DATE(audit_timestamp)` pour afficher chaque validation séparément (même SRO, dates différentes).

### Étape 2 : Sélection d'un DQE
```python
# Stockage des informations du DQE sélectionné
self.selected_dqe = {
    'sro': row[0],
    'projet': row[1],
    'nom_dqe': row[2],
    'nb_lignes': row[3],
    'date_creation': row[4],
    'user_name': row[5],
    'date_validation': row[6]  # Pour filtrer par date
}
```

### Étape 3 : Récupération des données
```python
def get_dqe_data(self) -> List[Dict]:
    # Filtrer par date_validation pour récupérer uniquement
    # les données de la validation sélectionnée
    
    if date_validation:
        query = """
            SELECT id, categorie, champs, audit_timestamp
            FROM dqe.dqejson
            WHERE sro = %s AND projet = %s AND nom_dqe = %s
              AND DATE(audit_timestamp) = %s
            ORDER BY id
        """
    else:
        # Fallback sans filtre date
        query = """
            SELECT id, categorie, champs, audit_timestamp
            FROM dqe.dqejson
            WHERE sro = %s AND projet = %s AND nom_dqe = %s
            ORDER BY id
        """
```

---

## Régénération Excel

### Processus pour DQE PRO
```python
def _generate_excel_by_designation(self, results, sro, report_type):
    """Génère l'Excel en faisant correspondre chaque désignation 
    à sa ligne dans le template"""
    
    # 1. Obtenir le template
    template_path = ExcelManager.get_template_path(report_type)
    
    # 2. Copier le template
    shutil.copy2(template_path, excel_path)
    
    # 3. Ouvrir le workbook
    workbook = load_workbook(excel_path)
    
    # 4. Déterminer la section (Transport ou Distribution)
    if projet == 'TP':
        start_row = 2
        end_row = distribution_start_row - 1
    elif projet == 'DP':
        start_row = distribution_start_row
        end_row = target_sheet.max_row
    
    # 5. Remplir par correspondance de désignation
    for row_idx in range(start_row, end_row + 1):
        template_designation = sheet.cell(row=row_idx, column=1).value
        if template_designation in results:
            quantite = results[template_designation]['quantite']
            sheet.cell(row=row_idx, column=3).value = quantite
    
    # 6. Sauvegarder et ouvrir
    workbook.save(excel_path)
    ExcelManager._open_excel_file(excel_path)
```

### Distinction Transport / Distribution
```python
# Chercher la ligne "Distribution" qui sépare les sections
for row_idx in range(2, sheet.max_row + 1):
    cell_val = sheet.cell(row=row_idx, column=1).value
    if "distribution" in str(cell_val).lower():
        distribution_start_row = row_idx
        break

# TP (Transport) : lignes 2 à distribution_start_row - 1
# DP (Distribution) : lignes distribution_start_row à max_row
```

---

## Régénération des couches QGIS

### Processus
```python
def recover_layers(self):
    # 1. Récupérer les données archivées
    dqe_data = self.get_dqe_data()
    
    # 2. Filtrer les FeatureCollections (géométries)
    for item in dqe_data:
        champs = item['champs']
        if champs.get('type') == 'FeatureCollection':
            # Créer la couche QGIS
            layer_name = item['categorie']
            features = champs['features']
            crs = champs.get('crs', 'EPSG:2154')
            
            # Créer QgsVectorLayer en mémoire
            layer = QgsVectorLayer(f"LineString?crs={crs}", layer_name, "memory")
            
            # Ajouter les features
            for feat_data in features:
                feat = QgsFeature()
                geom = QgsGeometry.fromWkt(feat_data['geometry'])
                feat.setGeometry(geom)
                feat.setAttributes(feat_data['properties'])
                layer.dataProvider().addFeature(feat)
            
            # Ajouter au projet
            QgsProject.instance().addMapLayer(layer, False)
            layer_group.addLayer(layer)
```

---

## Structure des données archivées

### Types de champs JSONB
```json
// Type sql_result (quantités)
{
    "type": "sql_result",
    "designation": "Fourniture et pose de câble optique de 12 FO en aérien",
    "quantite": 2079.2,
    "unite": "ml",
    "ids": "145,140,147,..."
}

// Type FeatureCollection (géométries)
{
    "type": "FeatureCollection",
    "crs": "EPSG:2154",
    "features": [
        {
            "geometry": "LINESTRING(x1 y1, x2 y2, ...)",
            "properties": {
                "id": 123,
                "cap_fo": 12,
                ...
            }
        }
    ]
}
```

---

## Flux de données

```
┌─────────────────┐
│  Interface UI   │
│ (dqe_recover_tab)│
└────────┬────────┘
         │ Filtres (Type, SRO)
         ▼
┌─────────────────┐
│ refresh_dqe_list│
│ (GROUP BY date) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  dqe.dqejson    │
│  (PostgreSQL)   │
└────────┬────────┘
         │ Liste des validations
         ▼
┌─────────────────┐
│  Table UI       │
│  (sélection)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  get_dqe_data() │
│ (filtre par date)│
└────────┬────────┘
         │
         ├─────────────────┐
         ▼                 ▼
┌─────────────────┐ ┌─────────────────┐
│ recover_excel() │ │ recover_layers()│
└────────┬────────┘ └────────┬────────┘
         │                   │
         ▼                   ▼
┌─────────────────┐ ┌─────────────────┐
│  Fichier Excel  │ │  Couches QGIS   │
│  régénéré       │ │  recréées       │
└─────────────────┘ └─────────────────┘
```

---

## Points d'attention

### Séparation par date
- Le GROUP BY inclut `DATE(audit_timestamp)` pour séparer les validations
- Chaque validation du même SRO à des dates différentes apparaît sur une ligne séparée
- La récupération filtre par `date_validation` pour obtenir uniquement les données de cette validation

### Correspondance par désignation
- La régénération Excel utilise la correspondance par désignation exacte
- Évite les problèmes de décalage d'index

### Sections Transport / Distribution
- Pour DQE PRO, le template a 2 sections identiques
- La régénération remplit uniquement la section correspondant au type (TP ou DP)

---

## Aperçu des données

### Table de prévisualisation
| Colonne | Description |
|---------|-------------|
| Catégorie | Désignation ou nom de couche |
| Type | sql_result ou Géométries |
| Valeur | Quantité ou nombre de features |
| IDs | Liste des IDs (pour sql_result) |

```python
def load_preview(self):
    # Afficher les 50 premières lignes
    for i, item in enumerate(dqe_data[:50]):
        champs = item['champs']
        
        if champs.get('type') == 'sql_result':
            # Afficher désignation, quantité, unité
            ...
        elif champs.get('type') == 'FeatureCollection':
            # Afficher nombre de features
            ...
```

---

## Redimensionnement dynamique

L'onglet DQE Recover nécessite plus d'espace. Le dialogue se redimensionne automatiquement :

```python
# Dans dqe_chargeur_dialog.py
def on_tab_changed(self, index):
    tab_name = self.tab_widget.tabText(index)
    if "Recover" in tab_name:
        self.resize(650, 600)  # Plus grand pour Recover
    else:
        self.resize(620, 450)  # Taille standard
```
