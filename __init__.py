"""
DQE Chargeur Plugin pour QGIS
============================

Plugin professionnel pour la gestion des DQE (Devis Quantitatif Estimatif)
avec support des fonctionnalités PRO, EXE et PGC.

Architecture modulaire conçue pour la maintenabilité et l'extensibilité.

Auteur: DEVTEAM NGE
Version: 2.0.0
Compatibilité: QGIS 3.x
"""

# Métadonnées du plugin
__version__ = "2.0.0"
__author__ = "DEVTEM NGE"
__email__ = "yadda@ext.nge.fr"
__license__ = "GPL v3"

def classFactory(iface):
    """
    Factory function pour l'instanciation du plugin QGIS.
    
    Cette fonction est appelée automatiquement par QGIS lors du chargement du plugin.
    Elle suit le pattern Factory standard pour les plugins QGIS.
    
    Args:
        iface (QgisInterface): Interface principale de QGIS
        
    Returns:
        DqeChargeurPlugin: Instance du plugin principal
        
    Raises:
        ImportError: Si les dépendances requises ne sont pas disponibles
        Exception: Si l'initialisation du plugin échoue
    """
    try:
        # Import paresseux pour éviter les erreurs de dépendances au chargement initial
        from .dqe_chargeur import DqeChargeurPlugin
        
        # Log du chargement pour le débogage
        print(f"[DQE] Initialisation du plugin DQE Chargeur v{__version__}")
        
        return DqeChargeurPlugin(iface)
        
    except ImportError as e:
        # Gestion spécifique des erreurs d'import
        error_msg = f"Erreur d'import lors du chargement du plugin DQE: {str(e)}"
        print(f"[DQE ERROR] {error_msg}")
        
        # Afficher un message à l'utilisateur si possible
        try:
            from qgis.core import Qgis
            from qgis.utils import iface as qgis_iface
            if qgis_iface:
                qgis_iface.messageBar().pushMessage(
                    "Erreur DQE Plugin", 
                    error_msg, 
                    level=Qgis.Critical,
                    duration=10
                )
        except:
            pass  # Si même l'affichage d'erreur échoue, continuer silencieusement
            
        raise
        
    except Exception as e:
        # Gestion des autres erreurs d'initialisation
        error_msg = f"Erreur lors de l'initialisation du plugin DQE: {str(e)}"
        print(f"[DQE ERROR] {error_msg}")
        raise


# Vérification des dépendances critiques au niveau module
def check_dependencies():
    """
    Vérifie que toutes les dépendances critiques sont disponibles.
    
    Returns:
        tuple: (success: bool, missing_deps: list)
    """
    required_modules = [
        'psycopg2',
        'pandas', 
        'openpyxl',
        'PyQt5',
        'qgis.core',
        'qgis.gui'
    ]
    
    missing_deps = []
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_deps.append(module)
    
    return len(missing_deps) == 0, missing_deps


# Vérification automatique des dépendances lors de l'import
_deps_ok, _missing_deps = check_dependencies()

if not _deps_ok:
    warning_msg = f"[DQE WARNING] Dépendances manquantes: {', '.join(_missing_deps)}"
    print(warning_msg)
    print("[DQE WARNING] Le plugin pourrait ne pas fonctionner correctement.")


# Métadonnées additionnelles pour le debugging et la maintenance
DEBUG_MODE = False  # À activer pour plus de logs
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR

# Configuration globale du plugin
PLUGIN_CONFIG = {
    'name': 'DQE Chargeur',
    'version': __version__,
    'min_qgis_version': '3.0',
    'description': 'Plugin pour la gestion des DQE',
    'about': 'Chargement et validation des DQE PRO, EXE et PGC avec interface modulaire',
    'tracker': '',
    'repository': '',
    'category': 'Database',
    'icon': 'icon.png',
    'experimental': False,
    'deprecated': False
}


def get_plugin_info():
    """
    Retourne les informations complètes du plugin.
    
    Utile pour le débogage et les rapports d'erreur.
    
    Returns:
        dict: Dictionnaire contenant toutes les métadonnées du plugin
    """
    return {
        **PLUGIN_CONFIG,
        'author': __author__,
        'email': __email__,
        'license': __license__,
        'dependencies_ok': _deps_ok,
        'missing_dependencies': _missing_deps,
        'debug_mode': DEBUG_MODE,
        'log_level': LOG_LEVEL
    }


# Log d'initialisation du module
if DEBUG_MODE:
    print(f"[DQE DEBUG] Module __init__.py chargé. Config: {get_plugin_info()}")