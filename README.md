# DQE Chargeur

Génère les DQE (Détail Quantitatif Estimatif) pour Auvergne Numérique.  
Fait le boulot : requêtes SQL, couches QGIS, exports Excel.

**v4.0.0** | QGIS 3.28+ | NGE

## Structure

```
DQE Chargeur/
├── __init__.py              # entry point
├── dqe_chargeur.py          # lifecycle plugin
├── dqe_chargeur_dialog.py   # dialog principal
├── dqe_pro_tab.py           # onglet PRO
├── dqe_exe_tab.py           # onglet EXE  
├── dqe_pgc_tab.py           # onglet PGC
├── dqe_recover_tab.py       # onglet archives
├── dqe_utils.py             # helpers divers
├── database_operations.py   # SQL mgmt
├── layer_manager.py         # couches QGIS
├── excel_manager.py         # export xlsx
├── ui_components.py         # widgets UI
├── models.py                # dataclasses
└── files/                   # templates xlsx
```

## Ce que ca fait

### PRO
Quantitatifs projet, Transport ou Distribution.  
Decoupe auto des cables en Distrib. Export xlsx.

### EXE
Quantitatifs execution : projet + GC (tranchees, chambres, poteaux, alveoles).  
Gere le blocage_ran :
- **TE/DE** : standard
- **TT/DT** : exclut blocage
- **TB/DB** : seulement blocage

### PGC
Attribution gestionnaire via algo proximite.  
Deux modes :
- **Gestionnaire** : modif manuelle QGIS puis regen Excel
- **Direct** : full auto

Gere infra mixte (aerien + souterrain), redevances separees poteaux/alveoles.

### RECOVER
Recupere les DQE archives depuis `dqe.dqejson`.  
Preview HTML, regen Excel, recree couches QGIS.  
Codes : GC, TP, DP, TE, DE, TT, DT, TB, DB

## Usage

### Prereqs
- QGIS 3.28+
- Acces base telecom
- Templates dans `files/`

### Workflow
1. Saisir SRO (format XXX/XXX/XXX/XXX)
2. Choisir type (Transport/Distribution)
3. Troncon si PGC
4. Executer
5. Modif manuelle si besoin (mode gestionnaire)
   - Corriger `cm_gest_do` dans la couche
   - Transferer segments entre concessionnaires
6. Regen Excel
7. Done, redevances recalculees

## Config

### Base de donnees

Connexion auto. Fonctions PostgreSQL utilisees :

#### `rip_avg_nge`
| Fonction | Role |
|----------|------|
| `dqe2(sro, type)` | quantitatifs PRO |
| `dqe_exe(sro, type)` | quantitatifs EXE |
| `dqe_pgc(sro, troncon)` | attribution PGC |
| `fddcpi2(sro)` | distrib cables |
| `za_sro` | ref codes SRO |

#### `gc_exe`
| Fonction | Role |
|----------|------|
| `gestionnaire(sro, troncon)` | algo proximite, retourne `nb_pot_ac` |
| `redevance_table(sro, troncon)` | calcul redevances |
| `t_cheminement` | table principale |
| `infra_pt_chb` | chambres |
| `infra_pt_pot` | poteaux RAUV |

`cm_typ_imp` : 0=aerien, 7=souterrain

#### Flux SQL

**PRO** : `dqe2()` et c'est tout

**EXE** : `dqe_exe()` inclut GC

**PGC** :
1. `dqe_pgc()` - donnees brutes
2. `gestionnaire()` - attribution
3. `redevance_table()` - redevances
4. Mode gestionnaire : regen avec modifs couche QGIS

### Templates
| Fichier | Usage |
|---------|-------|
| `template_dqe_pro.xlsx` | quantitatifs projet |
| `template_dqe_exe.xlsx` | quantitatifs exec |
| `template_dqe_pgc.xlsx` | gestionnaire + feuille REDEVANCE |

## Details techniques

### Redevances

Gestion auto selon type infra :

**Aerien** : poteaux RAUV (`nb_pot_ac`), colonnes Poteaux + Longueur

**Souterrain** : alveoles par types (PVC/PEHD), colonnes dynamiques, calcul `nb_alv * long`

**Mixte** : les deux combines, totaux separes (pas de melange ml/unites)

### Mode gestionnaire

1. Charge couche avec `nb_pot_ac`
2. Modif `cm_gest_do` dans QGIS
3. Regen Excel recalcule tout
4. Noms couches uniques auto
5. Prend toujours la couche la plus recente

## Changelog

### 3.5.0
- Correction SyntaxError EOL (guillemets dans f-strings) empêchant le chargement
- Sauvegarde complète des données DQE PRO dans dqejson (SQL + câbles découpés)
- Correspondance exacte par désignation pour template PGC
- Gestion dynamique des alvéoles dans template PGC
- Unification du remplissage template via ExcelManager
- Correction "wrapped C/C++ object deleted" sur onglets PRO et EXE
- Correction régénération Excel après modification gestionnaire
- Correction fallback template EXE vers PRO
- Documentation HTML : toggle dark/light mode, schéma architecture
- Nettoyage global : style professionnel, suppression émojis

### 3.4.0
- Onglet DQE Recover (archives dqe.dqejson)
- Modes blocage_ran : Standard (TE/DE), Travaux (TT/DT), Blocage (TB/DB)
- Compatibilité Qt (classe QtCompatibility)
- Sauvegarde Excel robuste (openpyxl deprecated)
- Correction comptage chambres L3C/L3T

### 3.2.0
- Infrastructures mixtes (aérien + souterrain)
- Redevances poteaux RAUV / alvéoles séparées
- Corrections gc_exe.gestionnaire() et redevance_table()

### 3.0.0
- Version initiale PRO, EXE, PGC

## Docs

Dans `docs/` :
- `DQE_PRO.md` / `DQE_EXE.md` / `DQE_PGC.md`
- `BLOCAGE_RAN_ARCHITECTURE.md` - modes RAN
- `AUDIT_COMPLET.md` - audit technique

## Deps

| Package | Min | |
|---------|-----|---|
| psycopg2 | 2.8 | PostgreSQL |
| pandas | 1.0 | data |
| openpyxl | 3.0 | xlsx |
| PyQt5 | 5.12 | UI |

---

NGE - Auvergne Numerique  
v3.5.0 | yadda@ext.nge.fr
