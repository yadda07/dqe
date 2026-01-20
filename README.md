# DQE Chargeur - Plugin QGIS

Plugin de génération automatique de DQE (Détail Quantitatif Estimatif) pour le projet Auvergne Numérique.

**Version:** 3.4.0  
**Compatibilité:** QGIS 3.28+  
**Auteur:** DEVTEAM NGE

## Architecture

```
DQE Chargeur/
├── __init__.py              # Point d'entrée QGIS
├── dqe_chargeur.py          # Plugin principal (lifecycle)
├── dqe_chargeur_dialog.py   # Dialog principal avec onglets
├── dqe_pro_tab.py           # Onglet DQE PRO
├── dqe_exe_tab.py           # Onglet DQE EXE
├── dqe_pgc_tab.py           # Onglet DQE PGC
├── dqe_recover_tab.py       # Onglet récupération archives
├── dqe_utils.py             # Utilitaires (DB, Logger, Validation)
├── database_operations.py   # Opérations SQL
├── layer_manager.py         # Gestion couches QGIS
├── excel_manager.py         # Génération rapports Excel
├── ui_components.py         # Composants UI réutilisables
├── models.py                # Classes de données
└── files/                   # Templates Excel
```

## Fonctionnalités

### DQE PRO
- Génération des quantitatifs projet
- Support Transport et Distribution
- Export Excel avec template spécialisé
- Câbles découpés automatiques (Distribution)

### DQE EXE
- Quantitatifs exécution (projet + génie civil)
- Intégration tranchées, chambres, poteaux, alvéoles
- Template Excel dédié
- Catégorisation automatique des couches
- **Modes calcul blocage_ran :**
  - Standard (TE/DE) : calcul normal
  - Travaux (TT/DT) : exclut blocage_ran=true
  - Blocage (TB/DB) : uniquement blocage_ran=true

### DQE PGC
- Attribution gestionnaire avec algorithme de proximité
- Mode gestionnaire : corrections manuelles possibles avec régénération Excel
- Mode direct : traitement automatique
- Gestion intelligente des infrastructures mixtes (aérien + souterrain)
- Calcul des redevances avec poteaux et alvéoles séparés
- Support complet infrastructure aérienne (poteaux RAUV)
- Support infrastructure souterraine (alvéoles PVC/PEHD)
- Totaux Excel automatiques sans mélange d'unités

### DQE RECOVER
- Récupération DQE archivés depuis `dqe.dqejson`
- Aperçu HTML avec watermark "ARCHIVÉ"
- Recherche par SRO/code projet avec filtres
- Régénération Excel à partir des données sauvegardées
- Recréation des couches QGIS avec géométries WKT
- Support codes projet : GC, TP, DP, TE, DE, TT, DT, TB, DB

## Utilisation

### Prérequis

- QGIS 3.1.0 ou supérieur
- Accès à la base de données de télécommunications
- Templates Excel disponibles dans le dossier `files/`

### Workflow type

1. **Saisir le code SRO** (format XXX/XXX/XXX/XXX)
2. **Sélectionner le type** (Transport/Distribution)
3. **Choisir le tronçon** (pour DQE PGC)
4. **Exécuter** le traitement
5. **Modifier manuellement** si nécessaire (mode gestionnaire)
   - Corriger les attributions `cm_gest_do` dans la couche QGIS
   - Transférer des segments entre concessionnaires
6. **Régénérer l'Excel** avec les modifications (bouton "Régénérer Excel")
7. **Excel final** avec redevances recalculées automatiquement

## Configuration

### Base de données

Le plugin se connecte automatiquement à la base configurée et utilise un ensemble complet de fonctions PostgreSQL spécialisées :

#### Schéma `rip_avg_nge`

- **`dqe2(sro, type)`** - Génération DQE PRO (quantitatifs projet)
- **`dqe_exe(sro, type)`** - Génération DQE EXE (quantitatifs exécution)
- **`dqe_pgc(sro, troncon)`** - Génération DQE PGC (attribution gestionnaire)
- **`fddcpi2(sro)`** - Distribution des câbles par SRO
- **`za_sro`** - Table de référence des codes SRO

#### Schéma `gc_exe`

- **`gestionnaire(sro, troncon)`** - Attribution gestionnaire avec algorithme de proximité/parallélisme
  - Retourne `nb_pot_ac` (nombre poteaux) pour infrastructures aériennes
  - Support `cm_typ_imp` (0=aérien, 7=souterrain) pour infrastructures mixtes
- **`redevance_table(sro, troncon)`** - Calcul des redevances par gestionnaire
  - **Aérien** : Colonnes `Poteaux` (unités) + `Longueur` (ml)
  - **Souterrain** : Colonnes dynamiques par types d'alvéoles (ml)
  - **Mixte** : Poteaux + Alvéoles avec unités séparées
- **`t_cheminement`** - Table principale du cheminement
- **`infra_pt_chb`** - Infrastructures ponctuelles (chambres)
- **`infra_pt_pot`** - Infrastructures ponctuelles (poteaux RAUV)
- **`infra_pt_autres`** - Autres infrastructures ponctuelles

#### Workflow des fonctions

**DQE PRO :**

- `rip_avg_nge.dqe2()` → Quantitatifs projet

**DQE EXE :**

- `rip_avg_nge.dqe_exe()` → Quantitatifs exécution + génie civil

**DQE PGC :**

1. `rip_avg_nge.dqe_pgc()` → Données PGC brutes
2. `gc_exe.gestionnaire()` → Attribution gestionnaire intelligente
3. `gc_exe.redevance_table()` → Calcul des redevances finales
   - **Infrastructure aérienne** : Seuls poteaux RAUV comptés
   - **Infrastructure souterraine** : Alvéoles par types (PVC/PEHD)
   - **Infrastructure mixte** : Poteaux + Alvéoles combinés
4. **Mode gestionnaire** : Régénération Excel avec données modifiées de couche QGIS

### Templates Excel

- `template_dqe_pro.xlsx` : Quantitatifs projet
- `template_dqe_exe.xlsx` : Quantitatifs exécution
- `template_dqe_pgc.xlsx` : Attribution gestionnaire avec feuille REDEVANCE automatique

## Fonctionnalités Avancées

### Calcul des Redevances Intelligentes

Le plugin gère automatiquement les différents types d'infrastructures :

#### **Infrastructure Aérienne Pure**
- **Données** : Poteaux RAUV uniquement (`nb_pot_ac`)
- **Excel** : Colonnes `Poteaux` (unités) + `Longueur` (ml)
- **Totaux** : Poteaux séparés des longueurs (unités différentes)

#### **Infrastructure Souterraine Pure**
- **Données** : Alvéoles par types (`2 PVC 42/45`, `4 PEHD 33/40`, etc.)
- **Excel** : Colonnes dynamiques par composition
- **Calcul** : `nb_alvéoles × longueur_segment`

#### **Infrastructure Mixte (Aérien + Souterrain)**
- **Parties aériennes** → Poteaux RAUV + longueurs aériennes
- **Parties souterraines** → Alvéoles par types
- **Excel** : Colonnes alvéoles + colonne "Aérien" (ml) + colonne "Poteaux_nb_unités"
- **Totaux séparés** : Évite le mélange mètres linéaires / unités

### Mode Gestionnaire Avancé

1. **Chargement couche** : Tous les segments avec `nb_pot_ac` inclus
2. **Modification manuelle** : Changement `cm_gest_do` dans QGIS
3. **Régénération Excel** : Recalcul complet avec nouvelles attributions
4. **Évite les doublons** : Noms de couches uniques automatiques
5. **Sélection intelligente** : Prend toujours la couche la plus récente

## Documentation Technique

Voir le dossier `docs/` pour la documentation détaillée :
- `DQE_PRO.md` - Documentation DQE PRO
- `DQE_EXE.md` - Documentation DQE EXE
- `DQE_PGC.md` - Documentation DQE PGC
- `BLOCAGE_RAN_ARCHITECTURE.md` - Architecture modes travaux RAN
- `AUDIT_COMPLET.md` - Rapport d'audit technique

## Dépendances

| Package | Version | Usage |
|---------|---------|-------|
| psycopg2 | >= 2.8 | Connexion PostgreSQL |
| pandas | >= 1.0 | Manipulation données |
| openpyxl | >= 3.0 | Génération Excel |
| PyQt5 | >= 5.12 | Interface graphique |

## Support

Développé par DEVTEAM NGE pour le projet Auvergne Numérique.

**Version :** 3.4.0  
**Contact :** yadda@ext.nge.fr 
