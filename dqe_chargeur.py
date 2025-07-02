"""
DQE Chargeur Plugin - VERSION CORRIGÉE
======================================

Plugin QGIS corrigé pour charger les DQE PRO, EXE et PGC.
Principe : Filtrage simple avec gid IN (ids) pour chaque catégorie.

Auteur: DEVTEAM NGE
"""

import os
from typing import Optional

from PyQt5.QtWidgets import QAction, QMessageBox
from PyQt5.QtGui import QIcon

from qgis.core import QgsApplication, QgsProject, Qgis
from qgis.gui import QgsMessageBar
from qgis.utils import iface

# Import des modules avec gestion d'erreurs
try:
    from .dqe_utils import initialize_dqe_system, cleanup_dqe_system, _logger
    from .dqe_chargeur_dialog import DQEChargeur
    MODULES_LOADED = True
except ImportError as e:
    print(f"[DQE] Erreur import: {e}")
    MODULES_LOADED = False
    _logger = None


class DqeChargeurPlugin:
    """
    Plugin DQE Chargeur CORRIGÉ
    
    Fonctionnalités :
    - Initialisation robuste du système DQE
    - Interface unique pour DQE PRO/EXE/PGC
    - Chargement des couches avec filtrage gid IN (ids)
    """
    
    def __init__(self, iface):
        """Initialise le plugin"""
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        
        # Composants UI
        self.action = None
        self.dialog = None
        
        # État
        self.initialized = False
        
        if _logger:
            _logger.info("Plugin DQE Chargeur créé")
    
    def initGui(self):
        """Initialise l'interface graphique"""
        try:
            # Création de l'action principale
            self._create_action()
            
            # Ajout au menu
            self._add_to_menu()
            
            # Initialisation du système DQE
            self._initialize_system()
            
            if _logger:
                _logger.info("Interface plugin initialisée")
                
        except Exception as e:
            error_msg = f"Erreur initialisation GUI: {str(e)}"
            print(f"[DQE ERROR] {error_msg}")
            
            if self.iface:
                self.iface.messageBar().pushMessage(
                    "Erreur DQE Plugin", error_msg,
                    level=Qgis.Critical, duration=10
                )
    
    def _create_action(self):
        """Crée l'action principale"""
        # Icône
        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        
        # Action
        self.action = QAction(icon, "Chargeur DQE", self.iface.mainWindow())
        self.action.triggered.connect(self.run_dialog)
        
        # Tooltip
        self.action.setToolTip(
            "Chargeur DQE - Gestion des Devis Quantitatifs Estimatifs\n"
            "DQE PRO, EXE et PGC avec chargement optimisé"
        )
        
        if _logger:
            _logger.info("Action principale créée")
    
    def _add_to_menu(self):
        """Ajoute au menu QGIS"""
        try:
            # Menu Vector
            self.iface.addPluginToVectorMenu("&DQE Chargeur", self.action)
            
            # Barre d'outils
            self.iface.addVectorToolBarIcon(self.action)
            
            if _logger:
                _logger.info("Plugin ajouté au menu")
                
        except Exception as e:
            if _logger:
                _logger.error(f"Erreur ajout menu: {e}")
            raise
    
    def _initialize_system(self):
        """Initialise le système DQE de manière robuste"""
        # TOUJOURS activer l'action d'abord
        self.action.setEnabled(True)
        
        if not MODULES_LOADED:
            if _logger:
                _logger.warning("Modules non chargés - mode dégradé")
            else:
                print("[DQE] Modules non chargés - mode dégradé")
            
            # Notification
            if self.iface:
                self.iface.messageBar().pushMessage(
                    "DQE Plugin", "Modules non chargés - veuillez redémarrer QGIS",
                    level=Qgis.Warning, duration=8
                )
            return
        
        try:
            # Tentative d'initialisation avec pool réduit
            success = initialize_dqe_system(pool_size=2)
            
            if success:
                self.initialized = True
                
                if _logger:
                    _logger.info("Système DQE initialisé avec succès")
                else:
                    print("[DQE] Système DQE initialisé avec succès")
                
                # Notification discrète de succès
                if self.iface:
                    self.iface.messageBar().pushMessage(
                        "DQE Plugin", "Initialisé avec succès",
                        level=Qgis.Success, duration=3
                    )
            else:
                # Échec mais on laisse l'action active en mode dégradé
                if _logger:
                    _logger.warning("Échec initialisation - mode dégradé disponible")
                else:
                    print("[DQE] Échec initialisation - mode dégradé disponible")
                
                if self.iface:
                    self.iface.messageBar().pushMessage(
                        "DQE Plugin", "Mode dégradé - vérifiez la configuration DB",
                        level=Qgis.Warning, duration=6
                    )
                
        except Exception as e:
            # Erreur mais on laisse l'action active
            error_msg = f"Erreur initialisation: {str(e)}"
            
            if _logger:
                _logger.error(error_msg)
            else:
                print(f"[DQE ERROR] {error_msg}")
            
            if self.iface:
                self.iface.messageBar().pushMessage(
                    "DQE Plugin", f"Erreur init: {str(e)[:50]}...",
                    level=Qgis.Critical, duration=8
                )
    
    def run_dialog(self):
        """Lance l'interface DQE"""
        try:
            # Vérifications de base
            if not MODULES_LOADED:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Erreur DQE Plugin",
                    "Les modules DQE ne sont pas chargés.\n\n"
                    "Veuillez redémarrer QGIS et vérifier l'installation du plugin."
                )
                return
            
            if not self.initialized:
                # Permettre l'utilisation même si pas initialisé (mode dégradé)
                reply = QMessageBox.question(
                    self.iface.mainWindow(),
                    "DQE Plugin",
                    "Le système DQE n'est pas complètement initialisé.\n\n"
                    "Voulez-vous continuer en mode dégradé ?\n"
                    "(Certaines fonctions peuvent ne pas être disponibles)",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                
                if reply == QMessageBox.No:
                    return
            
            # Création ou réactivation du dialogue
            if self.dialog is None:
                self.dialog = DQEChargeur(self.iface.mainWindow())
                
                # Connexion du signal de fermeture
                if hasattr(self.dialog, 'finished'):
                    self.dialog.finished.connect(self._on_dialog_closed)
            
            # Affichage
            self._show_dialog()
            
            if _logger:
                _logger.info("Interface DQE ouverte")
                
        except Exception as e:
            error_msg = f"Erreur ouverture interface: {str(e)}"
            
            if _logger:
                _logger.error(error_msg)
            
            QMessageBox.critical(
                self.iface.mainWindow() if self.iface else None,
                "Erreur DQE Plugin", 
                error_msg
            )
    
    def _show_dialog(self):
        """Affiche le dialogue"""
        if self.dialog:
            # Réinitialiser la position si nécessaire
            if not self.dialog.isVisible():
                # Centrer sur QGIS
                if self.iface and self.iface.mainWindow():
                    main_window = self.iface.mainWindow()
                    dialog_width = self.dialog.width()
                    dialog_height = self.dialog.height()
                    
                    x = main_window.x() + (main_window.width() - dialog_width) // 2
                    y = main_window.y() + (main_window.height() - dialog_height) // 2
                    
                    self.dialog.move(x, y)
            
            # Affichage et mise au premier plan
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
            
            # Forcer le focus
            if hasattr(self.dialog, 'setFocus'):
                self.dialog.setFocus()
    
    def _on_dialog_closed(self):
        """Gestionnaire de fermeture du dialogue"""
        if _logger:
            _logger.debug("Interface DQE fermée")
        
        # Optionnel: nettoyer les ressources du dialogue
        # self.dialog = None  # On garde en mémoire pour performance
    
    def unload(self):
        """Décharge le plugin"""
        try:
            if _logger:
                _logger.info("Déchargement plugin DQE")
            
            # Fermer le dialogue
            if self.dialog:
                try:
                    if self.dialog.isVisible():
                        self.dialog.close()
                except RuntimeError:
                    # L'objet a été supprimé
                    pass
                except Exception as e:
                    if _logger:
                        _logger.warning(f"Erreur fermeture dialogue: {e}")
                finally:
                    self.dialog = None
            
            # Supprimer du menu
            if self.iface and self.action:
                try:
                    self.iface.removePluginVectorMenu("&DQE Chargeur", self.action)
                    self.iface.removeVectorToolBarIcon(self.action)
                except Exception as e:
                    if _logger:
                        _logger.warning(f"Erreur suppression menu: {e}")
            
            # Nettoyage système DQE
            if MODULES_LOADED:
                try:
                    cleanup_dqe_system()
                except Exception as e:
                    if _logger:
                        _logger.warning(f"Erreur nettoyage système: {e}")
            
            if _logger:
                _logger.info("Plugin DQE déchargé avec succès")
                
        except Exception as e:
            error_msg = f"Erreur déchargement: {str(e)}"
            print(f"[DQE ERROR] {error_msg}")
            
            if _logger:
                _logger.error(error_msg)
    
    def reload_plugin(self):
        """Recharge le plugin (utile pour le développement)"""
        try:
            if _logger:
                _logger.info("Rechargement du plugin demandé")
            
            self.unload()
            
            # Rechargement des modules Python
            if MODULES_LOADED:
                import importlib
                from . import dqe_utils, dqe_chargeur_dialog
                
                importlib.reload(dqe_utils)
                importlib.reload(dqe_chargeur_dialog)
            
            self.initGui()
            
        except Exception as e:
            error_msg = f"Erreur lors du rechargement: {str(e)}"
            if _logger:
                _logger.error(error_msg)
            
            QMessageBox.critical(
                self.iface.mainWindow() if self.iface else None,
                "Erreur rechargement",
                error_msg
            )
    
    def get_plugin_info(self) -> dict:
        """Retourne les infos du plugin"""
        return {
            'name': 'DQE Chargeur',
            'version': '3.1.1',
            'initialized': self.initialized,
            'modules_loaded': MODULES_LOADED,
            'action_enabled': self.action.isEnabled() if self.action else False,
            'dialog_open': self.dialog.isVisible() if self.dialog else False,
            'description': 'Plugin QGIS pour DQE PRO/EXE/PGC avec chargement optimisé'
        }


# Fonctions utilitaires pour debug et test
def get_plugin_instance():
    """Retourne l'instance du plugin (pour debug)"""
    return None


def create_standalone_dialog():
    """Crée un dialogue standalone (pour tests)"""
    if not MODULES_LOADED:
        raise ImportError("Modules DQE non chargés")
    
    from PyQt5.QtWidgets import QApplication
    import sys
    
    if not QApplication.instance():
        app = QApplication(sys.argv)
    
    dialog = DQEChargeur()
    return dialog


# Export des classes principales
__all__ = [
    'DqeChargeurPlugin', 
    'get_plugin_instance', 
    'create_standalone_dialog'
]