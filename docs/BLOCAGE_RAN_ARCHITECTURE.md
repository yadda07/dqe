# Architecture Blocage RAN - DQE EXE

## Vue d'ensemble

La fonctionnalité **Blocage RAN** permet de filtrer les éléments du DQE EXE selon leur statut de blocage réseau. Elle génère deux DQE distincts :
- **Travaux** : Éléments sans blocage RAN (peuvent être réalisés)
- **Réserves/Blocage** : Éléments avec blocage RAN (en attente)

---

## 1. Paramètre `p_blocage`

### Valeurs possibles

| Valeur | Mode | Description | Code Projet |
|--------|------|-------------|-------------|
| `NULL` | Standard | Pas de filtre, tous les éléments | TE / DE |
| `'E'` | Standard | Identique à NULL | TE / DE |
| `'T'` | Travaux | Exclut `blocage_ran = true` | TT / DT |
| `'B'` | Blocage | Uniquement `blocage_ran = true` | TB / DB |

### Logique de filtrage SQL

```sql
AND (p_blocage IS NULL OR p_blocage = 'E' 
     OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
     OR (p_blocage = 'B' AND blocage_ran = true))
```

---

## 2. Fonctions SQL Modifiées

### 2.1 `rip_avg_nge.dqe2(text, text, text)`

**Signature :**
```sql
CREATE OR REPLACE FUNCTION rip_avg_nge.dqe2(
    p_sro text,
    p_type text DEFAULT NULL::text,
    p_blocage text DEFAULT NULL::text
) RETURNS TABLE("Désignation" text, "Unité" text, "Quantité" numeric, ids text)
```

**Tables filtrées :**

| Table | Schéma | Colonne blocage_ran |
|-------|--------|---------------------|
| `cables` | `rip_avg_nge` | Direct |
| `t_cheminement` | `rip_avg_nge` | Direct |
| `bpe` | `rip_avg_nge` | Direct |
| `rbal_auvergne` | `rbal` | Direct |
| `fddcpi2()` | `rip_avg_nge` | JOIN LATERAL → cables |

**CTEs impactées :**
- `base_data` (cables)
- `gc_to_create` (t_cheminement)
- `existing_aerial` (t_cheminement)
- `pep_transport` (bpe)
- `equipment_data_d` (bpe)
- `cables_data` (fddcpi2 + JOIN cables)
- `all_rows` lignes 1-3 (rbal_auvergne)

---

### 2.2 `rip_avg_nge.dqe_exe(text, text, text)`

**Signature :**
```sql
CREATE OR REPLACE FUNCTION rip_avg_nge.dqe_exe(
    p_sro text,
    p_type text DEFAULT NULL::text,
    p_blocage text DEFAULT NULL::text
) RETURNS TABLE("Désignation" text, "Unité" text, "Quantité" numeric, ids text)
```

**Appels à dqe2 :**
```sql
-- Récupération IDs GC
FROM rip_avg_nge.dqe2(p_sro, p_type, p_blocage) d

-- Données PRO (108 premières lignes)
FROM rip_avg_nge.dqe2(p_sro, p_type, p_blocage) d
```

**Tables EXE filtrées via jointure spatiale LATERAL :**

| Table EXE | Table PRO (source blocage_ran) | Critère jointure |
|-----------|-------------------------------|------------------|
| `gc_exe.t_cheminement` | `rip_avg_nge.t_cheminement` | 95% overlap |
| `gc_exe.infra_pt_chb` | `rip_avg_nge.infra_pt_chb` | ST_DWithin 0.1m |
| `rip_avg_nge.infra_pt_pot` | (même table) | Direct |

**CTEs impactées :**
- `cheminement_data` (tranchées)
- `chambre_distinct` (chambres)
- `poteaux_distribution_data` (poteaux)
- `pvc_data` (PVC)
- `pehd_data` (PEHD)

---

## 3. Jointure Spatiale LATERAL

### Principe

Les tables `gc_exe.*` n'ont **pas** de colonne `blocage_ran`. On récupère cette valeur depuis `rip_avg_nge.*` via jointure spatiale.

### Pattern utilisé

```sql
-- Pour t_cheminement (95% overlap)
LEFT JOIN LATERAL (
    SELECT pro.blocage_ran
    FROM rip_avg_nge.t_cheminement pro
    WHERE st_dwithin(exe.geom, pro.geom, 0.5)
      AND (st_length(st_intersection(exe.geom, st_buffer(pro.geom, 0.2))) 
           / NULLIF(st_length(exe.geom), 0)) >= 0.95
    LIMIT 1
) blocage_src ON true

-- Pour infra_pt_chb (0.1m)
LEFT JOIN LATERAL (
    SELECT pro.blocage_ran
    FROM rip_avg_nge.infra_pt_chb pro
    WHERE ST_DWithin(c.geom, pro.geom, 0.1)
    LIMIT 1
) blocage_src ON true
```

### Filtre appliqué

```sql
AND (p_blocage IS NULL OR p_blocage = 'E' 
     OR (p_blocage = 'T' AND (blocage_src.blocage_ran = false OR blocage_src.blocage_ran IS NULL))
     OR (p_blocage = 'B' AND blocage_src.blocage_ran = true))
```

---

## 4. Schéma de Données

### Tables avec `blocage_ran`

```
rip_avg_nge
├── t_cheminement.blocage_ran     (boolean)
├── infra_pt_chb.blocage_ran      (boolean)
├── infra_pt_pot.blocage_ran      (boolean)
├── bpe.blocage_ran               (boolean)
└── cables.blocage_ran            (boolean)

rbal
└── rbal_auvergne.blocage_ran     (boolean)
```

### Tables SANS `blocage_ran` (jointure spatiale requise)

```
gc_exe
├── t_cheminement      → jointure vers rip_avg_nge.t_cheminement
└── infra_pt_chb       → jointure vers rip_avg_nge.infra_pt_chb
```

---

## 5. Interface Plugin QGIS

### Fichiers modifiés

| Fichier | Modification |
|---------|--------------|
| `dqe_exe_tab.py` | ComboBox mode + DQEExeWorker + nommage |
| `database_operations.py` | `execute_dqe_exe(sro, p_type, blocage)` |
| `dqe_chargeur_dialog.py` | `execute_dqe_exe(sro, p_type, blocage)` |

### ComboBox Mode Blocage

```python
self.blocage_combo = QComboBox()
self.blocage_combo.addItem("Standard (TE/DE)", None)
self.blocage_combo.addItem("Travaux (TT/DT)", "T")
self.blocage_combo.addItem("Blocage RAN (TB/DB)", "B")
```

### DQEExeWorker

```python
class DQEExeWorker(QObject):
    def __init__(self, sro, p_type, blocage=None):
        self.sro = sro
        self.p_type = p_type
        self.blocage = blocage
    
    def run(self):
        self.results = DatabaseOperations.execute_dqe_exe(
            self.sro, self.p_type, self.blocage
        )
```

### Nommage Fichiers Excel

| Mode | Type | Nom Groupe | Nom Fichier |
|------|------|------------|-------------|
| Standard | Transport | `EXE_TE_SRO` | `DQE_EXE_TE_SRO.xlsx` |
| Standard | Distribution | `EXE_DE_SRO` | `DQE_EXE_DE_SRO.xlsx` |
| Travaux | Transport | `EXE_TT_SRO` | `DQE_EXE_TT_SRO.xlsx` |
| Travaux | Distribution | `EXE_DT_SRO` | `DQE_EXE_DT_SRO.xlsx` |
| Blocage | Transport | `EXE_TB_SRO` | `DQE_EXE_TB_SRO.xlsx` |
| Blocage | Distribution | `EXE_DB_SRO` | `DQE_EXE_DB_SRO.xlsx` |

---

## 6. Codes Projet `dqe.dqejson`

### Tous les codes

| Code | Type DQE | Description |
|------|----------|-------------|
| `GC` | PGC | Génie Civil |
| `TP` | PRO | Transport PRO |
| `DP` | PRO | Distribution PRO |
| `TE` | EXE | Transport Standard |
| `DE` | EXE | Distribution Standard |
| `TT` | EXE | Transport Travaux (sans blocage_ran) |
| `DT` | EXE | Distribution Travaux (sans blocage_ran) |
| `TB` | EXE | Transport Blocage (blocage_ran uniquement) |
| `DB` | EXE | Distribution Blocage (blocage_ran uniquement) |

### Logique de génération

```python
def get_projet_code(p_type, p_blocage):
    """Retourne le code projet pour dqejson"""
    type_char = p_type if p_type else 'T'  # T ou D
    if p_blocage == 'T':
        return f"{type_char}T"  # TT ou DT
    elif p_blocage == 'B':
        return f"{type_char}B"  # TB ou DB
    else:
        return f"{type_char}E"  # TE ou DE (standard)
```

---

## 6. Déploiement

### Ordre d'exécution SQL

```sql
-- 1. Déployer dqe2 d'abord (dépendance de dqe_exe)
\i sql/dqe2.sql

-- 2. Déployer dqe_exe ensuite
\i sql/dqe_exe.sql
```

### Vérification colonnes

```sql
SELECT table_schema, table_name, column_name 
FROM information_schema.columns 
WHERE column_name = 'blocage_ran'
ORDER BY table_schema, table_name;
```

### Test fonctionnel

```sql
-- Test mode Standard
SELECT COUNT(*) FROM rip_avg_nge.dqe_exe('MON_SRO', 'D', NULL);

-- Test mode Travaux
SELECT COUNT(*) FROM rip_avg_nge.dqe_exe('MON_SRO', 'D', 'T');

-- Test mode Blocage
SELECT COUNT(*) FROM rip_avg_nge.dqe_exe('MON_SRO', 'D', 'B');
```

---

## 7. Rétrocompatibilité

### Appels existants

Les appels existants sans le paramètre `p_blocage` fonctionnent grâce au `DEFAULT NULL` :

```sql
-- Ancien appel (fonctionne toujours)
SELECT * FROM rip_avg_nge.dqe_exe('SRO', 'D');

-- Équivalent à
SELECT * FROM rip_avg_nge.dqe_exe('SRO', 'D', NULL);
```

### Impact DQE PRO

**Aucun impact** sur DQE PRO. La fonction `dqe2` appelée par `dqe_pro_tab.py` continue de fonctionner normalement car `p_blocage` n'est pas passé (= `NULL` = mode Standard).

---

## 8. Diagramme de Flux

```
┌─────────────────────────────────────────────────────────────┐
│                    PLUGIN QGIS                              │
├─────────────────────────────────────────────────────────────┤
│  dqe_exe_tab.py                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ SRO ComboBox│  │Type ComboBox│  │Mode ComboBox│         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          ▼                                  │
│              ┌───────────────────────┐                      │
│              │    DQEExeWorker       │                      │
│              │ (sro, p_type, blocage)│                      │
│              └───────────┬───────────┘                      │
└──────────────────────────┼──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  DATABASE OPERATIONS                        │
├─────────────────────────────────────────────────────────────┤
│  execute_dqe_exe(sro, p_type, blocage)                      │
│                          │                                  │
│                          ▼                                  │
│  SELECT * FROM rip_avg_nge.dqe_exe(sro, p_type, blocage)    │
└──────────────────────────┼──────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    POSTGRESQL                               │
├─────────────────────────────────────────────────────────────┤
│  dqe_exe(p_sro, p_type, p_blocage)                          │
│         │                                                   │
│         ├──► dqe2(p_sro, p_type, p_blocage)                 │
│         │         │                                         │
│         │         ├──► cables (filtre blocage_ran)          │
│         │         ├──► t_cheminement (filtre blocage_ran)   │
│         │         ├──► bpe (filtre blocage_ran)             │
│         │         └──► rbal_auvergne (filtre blocage_ran)   │
│         │                                                   │
│         ├──► gc_exe.t_cheminement                           │
│         │         └──► JOIN LATERAL rip_avg_nge.t_cheminement│
│         │                                                   │
│         ├──► gc_exe.infra_pt_chb                            │
│         │         └──► JOIN LATERAL rip_avg_nge.infra_pt_chb│
│         │                                                   │
│         └──► rip_avg_nge.infra_pt_pot (direct)              │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Fichiers Concernés

### SQL
- `sql/dqe2.sql` - Fonction DQE PRO avec filtre blocage
- `sql/dqe_exe.sql` - Fonction DQE EXE avec jointures LATERAL

### Python
- `dqe_exe_tab.py` - Interface et worker DQE EXE
- `database_operations.py` - Appel SQL execute_dqe_exe
- `dqe_chargeur_dialog.py` - Méthode execute_dqe_exe

### Non modifiés
- `dqe_pro_tab.py` - Pas de modification (mode Standard uniquement)

---

*Document généré le 19/01/2026*
