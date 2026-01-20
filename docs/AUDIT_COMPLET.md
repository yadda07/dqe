# Audit Complet DQE Chargeur

**Date:** 2026-01-16  
**Version analysée:** 3.2.0  
**Auditeurs:** Lead Tech, Performance Specialist, Duplication Expert, QA Expert

---

# PARTIE 1 - LEAD TECH : Architecture & Dépendances

## 1.1 Cartographie DAG des Modules

```
__init__.py
    └── dqe_chargeur.py (DqeChargeurPlugin)
            ├── dqe_utils.py (singletons: _db_manager, _logger, _validator)
            └── dqe_chargeur_dialog.py (DQEChargeur)
                    ├── dqe_pro_tab.py (DQEProTab, DQEWorker)
                    ├── dqe_exe_tab.py (DQEExeTab)
                    ├── dqe_pgc_tab.py (DQEPGCTab)
                    ├── dqe_recover_tab.py (DQERecoverTab)
                    ├── ui_components.py (SROComboBox, TronconComboBox, ProgressWidget)
                    ├── layer_manager.py (LayerManager)
                    ├── database_operations.py (DatabaseOperations)
                    ├── excel_manager.py (ExcelManager)
                    └── models.py (DQEResult, OperationType)
```

## 1.2 Analyse des Dépendances par Module

### `__init__.py` (Point d'entrée)
| Import | Type | Critique |
|--------|------|----------|
| `dqe_chargeur.DqeChargeurPlugin` | Lazy | Oui |

**Verdict:** OK - Import paresseux correct

### `dqe_utils.py` (Singletons)
| Singleton | Portée | Problème |
|-----------|--------|----------|
| `_db_manager` | Module-level | **GLOBAL** |
| `_config_manager` | Module-level | **GLOBAL** |
| `_validator` | Module-level | **GLOBAL** |
| `_logger` | Module-level | **GLOBAL** |

**VIOLATION ARCH-001:** Variables globales au niveau module. Risque de fuite mémoire si le plugin n'est pas correctement déchargé.

### `dqe_chargeur.py` (Plugin principal)
| Responsabilité | Conforme |
|----------------|----------|
| Lifecycle QGIS (initGui/unload) | Oui |
| Création action/menu | Oui |
| Initialisation système | Oui |
| Nettoyage ressources | **Partiel** |

**VIOLATION ARCH-002:** `cleanup_dqe_system()` ne ferme pas le pool de connexions.

### Tabs (pro, exe, pgc, recover)
| Aspect | PRO | EXE | PGC | RECOVER |
|--------|-----|-----|-----|---------|
| Séparation UI/Logic | Non | Non | Non | Non |
| Threading | QThread | QThread | QThread | QThread |
| Signaux Qt | OK | OK | OK | OK |
| État interne | layers_loaded | layers_loaded | layers_loaded | dqe_data |

**VIOLATION ARCH-003:** Logique métier mélangée avec UI dans tous les tabs.

## 1.3 Dépendances Circulaires Détectées

```
dqe_pro_tab.py → dqe_chargeur_dialog.py (getattr _db_manager)
dqe_exe_tab.py → dqe_chargeur_dialog.py (getattr _db_manager)
dqe_pgc_tab.py → dqe_chargeur_dialog.py (getattr _db_manager)
dqe_recover_tab.py → dqe_chargeur_dialog.py (getattr _db_manager)
ui_components.py → dqe_utils.py (_db_manager)
```

**VIOLATION ARCH-004:** Pattern d'import circulaire via `getattr(dqe_chargeur_dialog, '_db_manager')` dans tous les tabs.

## 1.4 Gestion de l'État Global

| Variable | Fichier | Problème |
|----------|---------|----------|
| `self.layers_loaded` | Tous tabs | Références couches C++ potentiellement invalides |
| `self.layer_group` | Tous tabs | Référence groupe potentiellement supprimé |
| `self.last_dqe_results` | dqe_pgc_tab | État persistant entre exécutions |
| `self.dqe_results` | dqe_pro_tab, dqe_exe_tab | État persistant |

**VIOLATION ARCH-005:** Références à objets QGIS stockées comme attributs d'instance.

## 1.5 Threading et Signaux Qt

| Classe | Thread | Signal | Problème |
|--------|--------|--------|----------|
| DQEWorker | QThread | finished, progress_updated | OK |
| PreviewWorker | QThread | finished, error | OK |
| Tabs | Main | progress_cancelled | OK |

**Conformité Threading:** OK

## 1.6 Cycle de Vie QGIS (unload)

```python
# dqe_chargeur.py:227-265
def unload(self):
    # ✓ Fermeture dialog
    # ✓ Suppression menu
    # ✓ Appel cleanup_dqe_system()
    # ✗ Pool connexions NON fermé explicitement
    # ✗ Threads en cours NON arrêtés
```

**VIOLATION ARCH-006:** Threads worker potentiellement actifs lors de unload.

---

# PARTIE 2 - PERFORMANCE SPECIALIST

## 2.1 Requêtes SQL Lourdes

| Fonction | Fichier:Ligne | Temps estimé | Problème |
|----------|---------------|--------------|----------|
| `dqe2(sro, 'T')` | database_operations.py:89 | 90s timeout | OK avec timeout |
| `dqe_exe(sro, type)` | database_operations.py:127 | Variable | Pas de timeout |
| `dqe_pgc(sro, troncon)` | database_operations.py:166 | Variable | Pas de timeout |
| `redevance_table(sro, troncon)` | database_operations.py:174 | Variable | Expression SQL dynamique exécutée |
| `gestionnaire(sro, troncon)` | layer_manager.py:247 | Variable | Pas de timeout |
| `fddcpi2(sro)` | layer_manager.py:403 | Variable | Compte puis CREATE TABLE |

**PERF-001:** Seul `dqe2` avec type='T' a un timeout configuré (90s).

**PERF-002:** `redevance_table` retourne une expression SQL qui est ensuite exécutée - double requête.

## 2.2 Pool Connexions DB

```python
# dqe_utils.py:111-121
def initialize(self, config: DatabaseConfig, pool_size: int = 3):
    self._connection_pool = SimpleConnectionPool(1, pool_size, **config.to_dict())
```

| Aspect | Valeur | Problème |
|--------|--------|----------|
| Pool min | 1 | OK |
| Pool max | 3 (ou 2 selon appel) | Trop petit pour parallélisme |
| Connexions hors pool | Multiples | `psycopg2.connect()` direct dans plusieurs fonctions |

**PERF-003:** Connexions créées hors pool :
- `database_operations.py:74` - execute_dqe_pro
- `database_operations.py:114` - execute_dqe_exe  
- `database_operations.py:152` - execute_dqe_pgc
- `layer_manager.py:226` - load_gestionnaire_layer
- `layer_manager.py:392` - load_distribution_cables

## 2.3 Chargement Couches QGIS

| Fonction | Méthode | Entités/appel | Problème |
|----------|---------|---------------|----------|
| `load_layer_direct` | URI + filtre SQL | Variable | OK |
| `load_gestionnaire_layer` | Memory layer | Toutes | Création feature par feature |
| `load_distribution_cables` | CREATE TABLE temp | Toutes | Table créée à chaque appel |

**PERF-004:** `load_gestionnaire_layer` crée les features une par une dans une boucle (ligne 316-347).

**PERF-005:** `load_distribution_cables` crée une table physique `temporaire.cables_decoupes_*` à chaque exécution sans nettoyage.

## 2.4 Génération Excel

| Opération | Fichier:Ligne | Problème |
|-----------|---------------|----------|
| `shutil.copy2(template_path, excel_path)` | excel_manager.py:94 | OK |
| Parcours template | excel_manager.py:378-382 | Boucle sur toutes les lignes pour chaque désignation |
| `workbook.save()` | excel_manager.py:113 | Sauvegarde synchrone |

**PERF-006:** Correspondance par désignation = O(n*m) où n=résultats, m=lignes template.

## 2.5 Boucles et Itérations Critiques

| Boucle | Fichier:Ligne | Complexité |
|--------|---------------|------------|
| `_load_organized_layers` | dqe_pro_tab.py:371-461 | O(n) + UI updates |
| `_fill_pgc_template` | excel_manager.py:364-422 | O(n*m) |
| `get_modified_gestionnaire_data` | dqe_pgc_tab.py:640-653 | O(n) features |
| `_generate_html_report` | dqe_recover_tab.py:472-493 | O(n) + string concat |

**PERF-007:** String concatenation pour HTML dans `_generate_html_report` (utiliser liste + join).

## 2.6 Goulots d'Étranglement Identifiés

| Rang | Opération | Impact |
|------|-----------|--------|
| 1 | Requête `dqe_pgc` + `redevance_table` | Critique - 2 requêtes séquentielles |
| 2 | `load_distribution_cables` CREATE TABLE | Élevé - I/O disque |
| 3 | Correspondance Excel O(n*m) | Moyen - CPU |
| 4 | Feature creation 1 par 1 | Moyen - CPU |

---

# PARTIE 3 - DUPLICATION EXPERT

## 3.1 Pattern: Validation SRO

**Localisation:** 
- `dqe_pro_tab.py:218` - `if not sro: QMessageBox.warning`
- `dqe_exe_tab.py:103-104` - `if not sro: QMessageBox.warning`
- `dqe_pgc_tab.py:166-168` - `if not sro or not troncon: print`
- `dqe_recover_tab.py:559-561` - `if not self.selected_dqe: QMessageBox.warning`

**Duplication:** 4 instances, logique similaire

**Consolidation proposée:**
```python
# Dans dqe_utils.py
def validate_input_required(value, field_name, parent_widget=None):
    if not value or not str(value).strip():
        if parent_widget:
            QMessageBox.warning(parent_widget, "Erreur", f"Veuillez remplir {field_name}")
        return False
    return True
```

## 3.2 Pattern: execute_dqe_* (PRO, EXE, PGC)

**Localisation:**
- `database_operations.py:69-106` - execute_dqe_pro
- `database_operations.py:108-143` - execute_dqe_exe
- `database_operations.py:145-275` - execute_dqe_pgc

**Code dupliqué (95% identique):**
```python
db_params = DatabaseOperations.get_db_connection_params()
if not db_params:
    raise RuntimeError("Paramètres DB non disponibles")

conn = psycopg2.connect(
    host=db_params["host"],
    port=db_params["port"],
    database=db_params["database"],
    user=db_params["user"],
    password=db_params["password"]
)
try:
    cursor = conn.cursor(cursor_factory=DictCursor)
    # ... requête différente
finally:
    conn.close()
```

**Consolidation proposée:**
```python
@staticmethod
def _execute_with_connection(query, params, processor_fn=None):
    db_params = DatabaseOperations.get_db_connection_params()
    if not db_params:
        raise RuntimeError("Paramètres DB non disponibles")
    
    with psycopg2.connect(**db_params) as conn:
        with conn.cursor(cursor_factory=DictCursor) as cursor:
            cursor.execute(query, params)
            results = cursor.fetchall()
            return processor_fn(results) if processor_fn else results
```

## 3.3 Pattern: _load_organized_layers

**Localisation:**
- `dqe_pro_tab.py:350-498` - 148 lignes
- `dqe_exe_tab.py:234-388` - 154 lignes

**Différences:** Catégories légèrement différentes (EXE a "Poteaux", "Travaux Génie civil")

**Taux de duplication:** ~85%

**Consolidation proposée:** Classe abstraite ou fonction paramétrable dans `layer_manager.py`

## 3.4 Pattern: _extract_layer_data

**Localisation:**
- `dqe_pro_tab.py:644-710` - Version avec try/except RuntimeError
- `dqe_exe_tab.py:534-565` - Version simplifiée
- `dqe_pgc_tab.py:486-509` - Version minimale

**Taux de duplication:** ~70%

**Consolidation proposée:** Fonction unique dans `layer_manager.py`

## 3.5 Pattern: validate_dqe_*

**Localisation:**
- `dqe_pro_tab.py:500-590`
- `dqe_exe_tab.py:390-480`
- `dqe_pgc_tab.py:376-484`

**Structure commune:**
1. Récupérer SRO
2. Vérifier résultats existent
3. Construire dqe_data
4. INSERT INTO dqe.dqejson
5. Sauvegarder câbles découpés si Distribution
6. Afficher message

**Taux de duplication:** ~75%

## 3.6 Pattern: smooth_progress_to

**Localisation:**
- `dqe_pro_tab.py:337-348`
- `dqe_exe_tab.py:221-232`
- `dqe_pgc_tab.py:350-374`

**Duplication:** 100% identique (sauf PGC légèrement différent)

**Consolidation proposée:** Méthode dans `ProgressWidget` ou mixin

## 3.7 Pattern: Messages d'erreur répétés

| Message | Occurrences |
|---------|-------------|
| "Paramètres DB non disponibles" | 5 |
| "Erreur chargement" | 8 |
| "Veuillez sélectionner un SRO" | 4 |
| "Aucun résultat DQE trouvé" | 3 |

**Consolidation proposée:** Constantes dans `dqe_utils.py`

## 3.8 Carte de Duplication Synthétique

| Pattern | Fichiers | Lignes dupliquées | Priorité |
|---------|----------|-------------------|----------|
| execute_dqe_* connexion | database_operations | ~45 | P1 |
| _load_organized_layers | pro_tab, exe_tab | ~280 | P1 |
| smooth_progress_to | 3 tabs | ~36 | P2 |
| _extract_layer_data | 3 tabs | ~90 | P2 |
| validate_dqe_* | 3 tabs | ~180 | P1 |
| Messages erreur | Multiple | N/A | P3 |

**Total lignes dupliquées estimé:** ~630 lignes

---

# PARTIE 4 - QA EXPERT (Résumé)

## Issues Critiques (P0)

| ID | Issue | Fichier:Ligne |
|----|-------|---------------|
| QA-003 | Injection SQL sro/troncon | layer_manager.py:247 |
| QA-004 | Injection SQL nom table | layer_manager.py:422 |
| QA-005 | Référence couche C++ supprimée | dqe_pgc_tab.py:392 |

## Issues Majeures (P1)

| ID | Issue | Fichier:Ligne |
|----|-------|---------------|
| QA-001 | `_db_manager._config` sans null check | Multiples |
| QA-002 | Division par zéro smooth_progress | dqe_pro_tab.py:343 |
| QA-010 | CRS null avant .isValid() | dqe_pgc_tab.py:508 |

## Issues Mineures (P2-P3)

| ID | Issue | Impact |
|----|-------|--------|
| QA-007 | deleteLater() timing | Crash rare |
| QA-009 | Géométrie non validée | Données corrompues |
| QA-011 | except: bare | Mauvaise pratique |
| QA-012 | iface.mainWindow() null | Crash rare |

---

# PARTIE 5 - DOCUMENTATION

## 5.1 État Actuel

| Document | Existe | À jour |
|----------|--------|--------|
| README.md | Oui | Partiel |
| DQE_PRO.md | Oui | À vérifier |
| DQE_EXE.md | Oui | À vérifier |
| DQE_PGC.md | Oui | À vérifier |
| DQE_RECOVER.md | Oui | À vérifier |

## 5.2 Mises à Jour Requises

### README.md
- [ ] Ajouter section DQE RECOVER
- [ ] Mettre à jour version (3.2.0)
- [ ] Ajouter diagramme d'architecture
- [ ] Documenter les singletons et leur cycle de vie

### DQE_*.md
- [ ] Synchroniser avec code actuel
- [ ] Ajouter exemples d'utilisation
- [ ] Documenter les modes (gestionnaire/direct)

---

# PARTIE 6 - PLAN D'ACTION DÉTAILLÉ (35 étapes)

## Phase 1: Lead Tech - Architecture (11 étapes)
1. Cartographier DAG modules complet
2. Analyser dépendances `__init__.py`
3. Analyser singletons `dqe_utils.py`
4. Analyser `database_operations.py`
5. Analyser `layer_manager.py`
6. Analyser `excel_manager.py`
7. Analyser tous les tabs
8. Vérifier séparation UI/logique métier
9. Vérifier gestion état global
10. Vérifier threading et signaux Qt
11. Vérifier cycle de vie QGIS (unload)

## Phase 2: Performance (6 étapes)
12. Analyser requêtes SQL lourdes
13. Analyser pool connexions DB
14. Analyser chargement couches QGIS
15. Analyser génération Excel
16. Analyser boucles et itérations
17. Identifier goulots d'étranglement

## Phase 3: Duplication (8 étapes)
18. Scan patterns validation SRO
19. Scan patterns execute_dqe_*
20. Scan patterns _load_organized_layers
21. Scan patterns _extract_layer_data
22. Scan patterns validate_dqe_*
23. Scan patterns smooth_progress_to
24. Scan messages erreur répétés
25. Proposer stratégie consolidation

## Phase 4: QA (4 étapes)
26. Réviser issues P0 (injection SQL)
27. Réviser issues P1 (null checks)
28. Réviser issues P2 (géométrie/CRS)
29. Vérifier conformité API QGIS 3.28

## Phase 5: Documentation (5 étapes)
30. Créer/MAJ README.md
31. Créer/MAJ DQE_PRO.md
32. Créer/MAJ DQE_EXE.md
33. Créer/MAJ DQE_PGC.md
34. Créer/MAJ DQE_RECOVER.md

## Phase 6: Synthèse (1 étape)
35. Consolider rapport final

---

# ANNEXE: Fonctionnement de l'Outil

## Flux DQE PRO
```
1. Utilisateur saisit SRO + Type (T/D)
2. execute_dqe_pro() → dqe2(sro, type) SQL
3. DQEWorker thread exécute en background
4. Résultats parsés → categories
5. _load_organized_layers() crée couches QGIS
6. Si Distribution: load_distribution_cables()
7. ExcelManager génère rapport
8. validate_dqe_pro() sauvegarde en base
```

## Flux DQE EXE
```
1. Utilisateur saisit SRO + Type (T/D)
2. execute_dqe_exe() → dqe_exe(sro, type) SQL
3. Même flux que PRO avec catégories différentes
4. Inclut poteaux et travaux GC
```

## Flux DQE PGC
```
1. Utilisateur saisit SRO + Tronçon
2. execute_dqe_pgc() → dqe_pgc() + redevance_table()
3. Choix mode: Gestionnaire ou Direct
4. Mode Gestionnaire: load_gestionnaire_layer()
   - Couche éditable
   - Régénération Excel possible
5. Mode Direct: Excel immédiat
6. validate_dqe_pgc() sauvegarde
```

## Flux DQE RECOVER
```
1. Recherche archives dans dqe.dqejson
2. Sélection DQE archivé
3. Aperçu HTML avec watermark
4. Régénération Excel et/ou couches QGIS
```

---

**Fin de l'audit**
