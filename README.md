# DQE Chargeur - Plugin QGIS

Plugin de génération automatique de DQE (Détail Quantitatif Estimatif) pour le projet Auvergne Numérique.

## Fonctionnalités

### DQE PRO

- Génération des quantitatifs projet
- Support Transport et Distribution
- Export Excel avec template spécialisé

### DQE EXE

- Quantitatifs exécution (projet + génie civil)
- Intégration tranchées, chambres, poteaux, alvéoles
- Template Excel dédié

### DQE PGC

- Attribution gestionnaire avec algorithme de proximité
- Mode gestionnaire : corrections manuelles possibles
- Mode direct : traitement automatique
- Gestion des redevances avec calculs précis

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
6. **Générer l'Excel** final

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
- **`redevance_table(sro, troncon)`** - Calcul des redevances par gestionnaire
- **`t_cheminement`** - Table principale du cheminement
- **`infra_pt_chb`** - Infrastructures ponctuelles (chambres)
- **`infra_pt_pot`** - Infrastructures ponctuelles (poteaux)
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

### Templates Excel

- `template_dqe_pro.xlsx` : Quantitatifs projet
- `template_dqe_exe.xlsx` : Quantitatifs exécution
- `template_dqe_pgc.xlsx` : Attribution gestionnaire

## Support

Développé par DEVTEM NGE pour le projet de Auvergne.

**Version :** 3.1.0
**Contact :** yadda@ext.nge.com
"# dqe" 
