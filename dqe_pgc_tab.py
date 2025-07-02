"""
DQE PGC Tab Module

Handles the DQE PGC tab interface and functionality for the QGIS plugin.
Extracted from the main dialog file for better modularity.
"""

import json
import time
import uuid
from typing import List, Dict, Any

from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QPushButton, QApplication, QMessageBox
)
from qgis.PyQt.QtCore import QObject
from qgis.core import QgsProject, Qgis
from qgis import utils

# Import des modules du plugin
from .ui_components import SROComboBox, TronconComboBox, ProgressWidget
from .layer_manager import LayerManager
from .database_operations import DatabaseOperations
from .excel_manager import ExcelManager
from .dqe_pro_tab import DQEWorker  # Réutilisation du DQEWorker

# Récupération des singletons depuis le module principal
try:
    iface = utils.iface
    from . import dqe_chargeur_dialog
    _db_manager = getattr(dqe_chargeur_dialog, '_db_manager', None)
    _logger = getattr(dqe_chargeur_dialog, '_logger', None)
    _validator = getattr(dqe_chargeur_dialog, '_validator', None)
except (ImportError, AttributeError):
    iface = None
    _db_manager = None
    _logger = None
    _validator = None


class DQEPGCTab(QWidget):
    """Interface et logique pour l'onglet DQE PGC"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers_loaded = []
        self.layer_group = None
        # Stockage des derniers résultats pour régénération Excel
        self.last_dqe_results = None
        self.last_sro = None
        self.last_troncon = None
        # Mode de calcul redevance
        self.redevance_mode_gestionnaire = False  # False = mode direct, True = mode gestionnaire
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Configuration - INTERFACE UNIFORME COMME PRO
        config_group = QGroupBox("Configuration DQE PGC")
        config_layout = QFormLayout(config_group)
        
        self.sro_input = SROComboBox()
        self.sro_input.setToolTip("Saisir le code SRO pour charger les tronçons disponibles\nFormat attendu : XXX/XXX/XXX/XXX")
        config_layout.addRow("SRO:", self.sro_input)
        
        self.troncon_combo = TronconComboBox()
        self.troncon_combo.setEnabled(False)
        self.troncon_combo.setToolTip("Sélectionner le tronçon à traiter parmi ceux disponibles pour ce SRO")
        config_layout.addRow("Tronçon:", self.troncon_combo)
        
        layout.addWidget(config_group)
        
        # Boutons - INTERFACE UNIFORME COMME PRO  
        buttons_layout = QHBoxLayout()
        
        self.execute_button = QPushButton("Exécuter DQE PGC")
        self.execute_button.setEnabled(False)
        self.execute_button.setToolTip("Lancer le calcul DQE PGC avec attribution gestionnaire\nCharge automatiquement les couches QGIS et génère l'Excel")
        self.execute_button.clicked.connect(self.execute_dqe_pgc)
        buttons_layout.addWidget(self.execute_button)
        
        self.regenerate_excel_button = QPushButton("Régénérer Excel")
        self.regenerate_excel_button.setToolTip("Régénérer l'Excel avec les données modifiées manuellement\nDétecte automatiquement les corrections dans la couche gestionnaire")
        self.regenerate_excel_button.clicked.connect(self.regenerate_excel)
        self.regenerate_excel_button.setEnabled(False)  # Désactivé par défaut
        buttons_layout.addWidget(self.regenerate_excel_button)
        
        self.validate_button = QPushButton("Valider DQE")
        self.validate_button.setToolTip("Sauvegarder les résultats DQE en base de données\nConfirme et finalise le traitement")
        self.validate_button.clicked.connect(self.validate_dqe_pgc)
        buttons_layout.addWidget(self.validate_button)
        
        layout.addLayout(buttons_layout)
        
        # Progression - INTERFACE UNIFORME COMME PRO
        self.progress_widget = ProgressWidget()
        layout.addWidget(self.progress_widget)
        
        layout.addStretch()
        
        # Connexions
        self.sro_input.lineEdit().textChanged.connect(self.on_sro_changed)
        self.troncon_combo.currentTextChanged.connect(self.on_troncon_changed)
        self.connect_gestionnaire_layer_signals()
    
    def on_sro_changed(self):
        # Réinitialiser l'état du plugin quand SRO change
        self._reset_plugin_state()
        
        sro = self.sro_input.lineEdit().text().strip()
        
        self.troncon_combo.clear()
        self.troncon_combo.setEnabled(False)
        self.execute_button.setEnabled(False)
        
        if len(sro) >= 5:
            QTimer.singleShot(1000, lambda: self.validate_sro_async(sro))
    
    def on_troncon_changed(self):
        """Appelé quand le tronçon change - réinitialise l'état du plugin"""
        troncon = self.troncon_combo.currentText().strip()
        
        if troncon:  # Seulement si un tronçon est sélectionné
            print(f"CHANGEMENT: Nouveau tronçon sélectionné: {troncon}")
            self._reset_plugin_state()
    
    def _reset_plugin_state(self):
        """Réinitialise complètement l'état du plugin pour un nouveau SRO/tronçon"""
        print("RÉINITIALISATION: État du plugin réinitialisé")
        
        # 1. Réinitialiser les données stockées
        self.last_dqe_results = None
        self.last_sro = None
        self.last_troncon = None
        self.redevance_mode_gestionnaire = False
        
        # 2. Réinitialiser l'état des boutons
        self.regenerate_excel_button.setEnabled(False)
        self.regenerate_excel_button.setText("Régénérer Excel")
        
        # 3. Nettoyer les couches précédentes
        self._clean_previous_layers()
        
        # 4. Réinitialiser les widgets de progression
        if hasattr(self, 'progress_widget'):
            # Réinitialiser l'état du widget de progression
            self.progress_widget.is_running = False
            self.progress_widget.progress_bar.setVisible(False)
            self.progress_widget.cancel_button.setVisible(False)
            self.progress_widget.status_label.setText("")
        
        print("RÉINITIALISATION: État du plugin réinitialisé")
    
    def _clean_previous_layers(self):
        """Nettoie les couches des traitements précédents"""
        try:
            from qgis.core import QgsProject
            project = QgsProject.instance()
            
            # Supprimer le groupe de couches précédent s'il existe
            if self.layer_group:
                project.layerTreeRoot().removeChildNode(self.layer_group)
                self.layer_group = None
            
            # Vider la liste des couches chargées
            self.layers_loaded.clear()
            
            print("NETTOYAGE: Couches précédentes supprimées")
            
        except Exception as e:
            print(f"ATTENTION: Erreur nettoyage couches: {e}")
    
    def validate_sro_async(self, sro: str):
        if sro != self.sro_input.lineEdit().text().strip():
            return
        
        if _validator:
            is_valid, message = _validator.validate_sro_exists(sro)
            if is_valid:
                self.troncon_combo.set_sro(sro)
                self.troncon_combo.setEnabled(True)
                self.execute_button.setEnabled(True)
    
    def execute_dqe_pgc(self):
        """Exécution DQE PGC avec interface uniforme"""
        sro = self.sro_input.lineEdit().text().strip()
        troncon = self.troncon_combo.currentText().strip()
        
        if not sro or not troncon:
            print("ERREUR: Veuillez remplir le SRO et sélectionner un tronçon")
            return
        
        # Désactiver le bouton pendant le traitement
        self.execute_button.setEnabled(False)
        
        try:
            self.progress_widget.start_operation("DQE PGC")
            
            # Créer le worker et le thread
            self.worker = DQEWorker("PGC", sro, None, troncon)
            self.thread = QThread()
            
            # Timer pour progression fluide dans le thread principal
            self.progress_timer = QTimer()
            self.current_progress = 10
            self.progress_increment = 1
            
            def update_smooth_progress():
                if hasattr(self, 'worker') and self.worker.is_running:
                    # Progression fluide vers la valeur cible du worker
                    target_progress = getattr(self.worker, 'progress_value', 10)
                    
                    if self.current_progress < target_progress:
                        self.current_progress = min(self.current_progress + self.progress_increment, target_progress)
                    elif self.current_progress < 90:  # Progression continue même sans cible
                        self.current_progress += 0.5
                    
                    status = "Traitement DQE PGC en cours..."
                    if self.current_progress < 20:
                        status = "Initialisation..."
                    elif self.current_progress < 40:
                        status = "Connexion à la base..."
                    elif self.current_progress < 85:
                        status = "Exécution de la requête..."
                    else:
                        status = "Finalisation..."
                    
                    self.progress_widget.update_progress(int(self.current_progress), status)
                else:
                    self.progress_timer.stop()
            
            self.progress_timer.timeout.connect(update_smooth_progress)
            self.progress_timer.start(100)  # Mise à jour toutes les 100ms pour fluidité
            
            # Connecter les signaux
            self.worker.moveToThread(self.thread)
            self.worker.finished.connect(self.on_dqe_pgc_finished)
            self.progress_widget.progress_cancelled.connect(self.worker.cancel)
            self.thread.started.connect(self.worker.run)
            self.thread.finished.connect(self.thread.deleteLater)
            
            # Démarrer le thread
            self.thread.start()
            
        except Exception as e:
            error_msg = f"Erreur initialisation DQE PGC: {str(e)}"
            print(f"\n💥 ERREUR DQE PGC: {error_msg}")
            self.progress_widget.complete_operation(False, error_msg)
            self.execute_button.setEnabled(True)
    
    def on_dqe_pgc_finished(self, success: bool, results, message: str):
        """Callback appelé quand le traitement DQE PGC est terminé"""
        try:
            # Continuer la progression fluide au lieu de l'arrêter brutalement
            if hasattr(self, 'progress_timer'):
                # Changer le comportement du timer pour la phase post-traitement
                self.post_processing = True
                
            if success and results:
                # Stocker les résultats pour régénération Excel ultérieure
                sro = self.sro_input.lineEdit().text().strip()
                troncon_safe = self.troncon_combo.currentText().strip().replace('/', '_')
                self.last_dqe_results = results
                self.last_sro = sro  
                self.last_troncon = troncon_safe
                print(f"📋 Résultats DQE PGC stockés pour régénération (SRO: {sro}, Tronçon: {troncon_safe})")
                
                # Traitement post-requête dans le thread principal
                self.smooth_progress_to(92, "Création des couches...")
                
                # Forcer le rafraîchissement de l'interface
                QApplication.processEvents()
                
                # Créer le groupe de couches
                current_date = time.strftime("%Y-%m-%d_%H%M%S")
                sro = self.sro_input.lineEdit().text().strip()
                troncon_safe = self.troncon_combo.currentText().strip().replace('/', '_')
                sro_safe = sro.replace('/', '_')
                group_name = f"DQE_PGC_{sro_safe}_{troncon_safe}_{current_date}"
                self.layer_group = LayerManager.create_layer_group(group_name)
                
                # Charger les couches
                created_layers = self._load_organized_layers(results, sro, troncon_safe)
                
                # === CHOIX DU MODE DE CALCUL REDEVANCE ===
                print(f"\n=== CHOIX MODE CALCUL REDEVANCE ===")
                
                # Boîte de dialogue pour choisir le mode de calcul
                reply = QMessageBox.question(
                    None,  # Parent
                    "Mode de calcul des redevances",
                    "Souhaitez-vous calculer les redevances automatiquement ?\n\n"
                    "• OUI → Mode Gestionnaire (précis)\n"
                    "  - Calcul avec algorithme de proximité\n"
                    "  - Correction manuelle possible\n"
                    "  - Couche éditable dans QGIS\n\n"
                    "• NON → Mode Direct (existant)\n"
                    "  - Utilise les données existantes\n"
                    "  - Plus rapide, pas de correction\n"
                    "  - Excel final généré directement",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes  # Bouton par défaut
                )
                
                self.redevance_mode_gestionnaire = (reply == QMessageBox.Yes)
                
                if self.redevance_mode_gestionnaire:
                    print(f"✅ Mode GESTIONNAIRE sélectionné → Calcul précis avec corrections possibles")
                    
                    # AJOUT: Charger la couche gestionnaire dans son propre sous-groupe
                    print(f"\n=== CHARGEMENT COUCHE GESTIONNAIRE ===")
                    
                    # Créer le sous-groupe "Gestionnaires" seulement en mode gestionnaire
                    gestionnaire_group = LayerManager.create_layer_subgroup(self.layer_group, "Gestionnaires")
                    
                    gestionnaire_layer = LayerManager.load_gestionnaire_layer(sro, troncon_safe, gestionnaire_group)
                    if gestionnaire_layer:
                        created_layers.append(gestionnaire_layer)
                        self.layers_loaded.append(gestionnaire_layer)
                        print(f"✅ Couche gestionnaire chargée: {gestionnaire_layer.featureCount()} segments")
                        print(f"   → Placée dans sous-groupe 'Gestionnaires'")
                        print(f"   → Permet corrections manuelles des attributions cm_gest_do")
                    else:
                        print(f"⚠️ Impossible de charger la couche gestionnaire")
                else:
                    print(f"✅ Mode DIRECT sélectionné → Utilisation données existantes")
                    print(f"   → Aucun sous-groupe 'Gestionnaires' créé")
                
                # Mettre à jour l'état des boutons selon le mode sélectionné
                self.update_buttons_state()
                
                # Connecter les signaux de modification si mode gestionnaire
                if hasattr(self, 'redevance_mode_gestionnaire') and self.redevance_mode_gestionnaire:
                    self.connect_gestionnaire_layer_signals()
                
                # Mode Direct ou Gestionnaire : utiliser ExcelManager.create_excel_report pour unifier
                
                # Sauvegarder les résultats DQE pour la génération Excel
                self.last_dqe_results = results
                
                # Génération Excel
                print(f"\n=== GÉNÉRATION EXCEL PGC ===")
                
                self.smooth_progress_to(98, "Génération du rapport Excel...")
                QApplication.processEvents()
                
                # IMPORTANT: Passer les objets DQEResult originaux qui contiennent les données redevance
                # Ne pas convertir en dictionnaire car cela perd les données redevance !
                excel_path = ExcelManager.create_excel_report(results, sro, "PGC", troncon_safe)
                
                if excel_path:
                    print(f"✅ Rapport Excel généré: {excel_path}")
                    # Optionnel: ouvrir automatiquement le fichier
                    try:
                        import os
                        os.startfile(excel_path)
                        print("📂 Fichier Excel ouvert automatiquement")
                    except Exception as e:
                        print(f"⚠ Impossible d'ouvrir automatiquement le fichier: {e}")
                else:
                    print("❌ Erreur lors de la génération du rapport Excel")
                
                # Finaliser
                self.smooth_progress_to(100, "Finalisation...")
                QApplication.processEvents()
                
                final_message = f"DQE PGC terminé: {len(created_layers)} couches créées"
                self.progress_widget.complete_operation(True, final_message)
                
                if iface:
                    iface.messageBar().pushMessage(
                        "DQE PGC", final_message,
                        level=Qgis.Success, duration=5
                    )
            else:
                self.progress_widget.complete_operation(False, message)
                print(f"❌ Erreur: {message}")
                
        except Exception as e:
            error_msg = f"Erreur post-traitement DQE PGC: {str(e)}"
            print(f"💥 {error_msg}")
            import traceback
            print(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
        finally:
            # Arrêter le timer et nettoyer
            if hasattr(self, 'progress_timer'):
                self.progress_timer.stop()
                self.progress_timer.deleteLater()
            # Réactiver le bouton et nettoyer
            self.execute_button.setEnabled(True)
            if hasattr(self, 'thread'):
                self.thread.quit()
                self.thread.wait()
    
    def smooth_progress_to(self, target_value, status):
        """Fait évoluer la progression en douceur vers une valeur cible"""
        if hasattr(self, 'current_progress'):
            # Mise à jour progressive vers la cible
            steps = max(1, int((target_value - self.current_progress) / 2))
            for i in range(steps):
                if self.current_progress < target_value:
                    self.current_progress = min(self.current_progress + self.progress_increment, target_value)
                elif self.current_progress < 90:  # Progression continue même sans cible
                    self.current_progress += 0.5
                
                status = "Traitement DQE PGC en cours..."
                if self.current_progress < 20:
                    status = "Initialisation..."
                elif self.current_progress < 40:
                    status = "Connexion à la base..."
                elif self.current_progress < 85:
                    status = "Exécution de la requête..."
                else:
                    status = "Finalisation..."
                
                self.progress_widget.update_progress(int(self.current_progress), status)
                QApplication.processEvents()
                time.sleep(0.05)  # Petite pause pour rendre la progression visible
            
            # S'assurer qu'on atteint la valeur cible
            self.current_progress = target_value
            self.progress_widget.update_progress(int(self.current_progress), status)
    
    def validate_dqe_pgc(self):
        """Valide et sauvegarde le DQE PGC dans la base de données"""
        try:
            # Vérifications préliminaires
            sro = self.sro_input.currentText().strip()
            if not sro:
                print("❌ Veuillez sélectionner un SRO")
                return
            
            if not self.layer_group or not self.layers_loaded:
                print("❌ Aucune couche DQE PGC chargée à valider")
                return
            
            # Détermination du code projet selon le type sélectionné
            projet_code = "GC"  # Génie Civil PGC
            
            # Récupération des informations utilisateur
            user_name = _db_manager._config.user if _db_manager._config else "unknown"
            
            success_count = 0
            total_layers = len(self.layers_loaded)
            
            # Sauvegarde de chaque couche dans dqe.dqejson
            for i, layer in enumerate(self.layers_loaded):
                print(f"DEBUG: Couche {i+1}/{total_layers}: {layer.name() if hasattr(layer, 'name') else 'SANS NOM'}")
                
                if not layer.isValid():
                    continue
                
                try:
                    # Transaction séparée pour chaque couche
                    with _db_manager.get_cursor() as cursor:
                        # Extraction des données de la couche
                        layer_data = self._extract_layer_data(layer)
                        
                        # Insertion dans dqe.dqejson
                        query = """
                            INSERT INTO dqe.dqejson 
                            (sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """
                        
                        cursor.execute(query, (
                            sro,
                            f"DQE_PGC_{sro}",
                            projet_code,
                            layer.name(),
                            json.dumps(layer_data),
                            user_name,
                            "dqe"
                        ))
                        
                        success_count += 1
                        
                except Exception as e:
                    if _logger:
                        _logger.error(f"Erreur validation couche {layer.name()}: {str(e)}")
            
            # Message de confirmation
            print(f"Validation terminée avec succès !\n\n"
                  f"- SRO: {sro}\n"
                  f"- Type: {projet_code}\n"
                  f"- Couches sauvegardées: {success_count}/{total_layers}")
            
            if _logger:
                _logger.info(f"DQE PGC validé - SRO: {sro}, Type: {projet_code}, Couches: {success_count}")
                
        except Exception as e:
            error_msg = f"Erreur lors de la validation DQE PGC: {str(e)}"
            print(f"❌ {error_msg}")
            if _logger:
                _logger.error(error_msg, exception=e)
    
    def _extract_layer_data(self, layer):
        """Extrait les données d'une couche QGIS pour sauvegarde JSON"""
        features_data = []
        
        for feature in layer.getFeatures():
            feature_dict = {
                'geometry': feature.geometry().asWkt() if feature.geometry() else None,
                'attributes': {}
            }
            
            # Récupération des attributs
            for field in layer.fields():
                field_name = field.name()
                value = feature[field_name]
                # Conversion des valeurs pour JSON
                if isinstance(value, (int, float, str, bool)) or value is None:
                    feature_dict['attributes'][field_name] = value
                else:
                    feature_dict['attributes'][field_name] = str(value)
            
            features_data.append(feature_dict)
        
        return {
            'type': 'FeatureCollection',
            'features': features_data,
            'crs': layer.crs().authid() if layer.crs().isValid() else None
        }
    
    def regenerate_excel(self):
        """Régénère le fichier Excel avec les données de redevance selon le mode sélectionné"""
        
        # Vérifier que nous sommes en mode gestionnaire
        if not hasattr(self, 'redevance_mode_gestionnaire') or not self.redevance_mode_gestionnaire:
            print("INFORMATION: Régénération Excel non disponible en mode direct")
            return
        
        # Récupérer SRO et tronçon actuels
        sro = self.sro_input.lineEdit().text().strip()
        troncon = self.troncon_combo.currentText().strip()
        
        if not sro or not troncon:
            print("ERREUR: Veuillez remplir le SRO et sélectionner un tronçon")
            return
            
        print(f"\n=== RÉGÉNÉRATION EXCEL (Mode Gestionnaire) ===")
        print(f"SRO: {sro}, Tronçon: {troncon}")
        
        try:
            # Récupérer les données modifiées de la couche gestionnaire
            modified_data = self.get_modified_gestionnaire_data(sro, troncon)
            
            if modified_data is None:
                print("⚠️ Impossible de récupérer les données gestionnaire modifiées")
                return
            
            print(f"✅ Données gestionnaire récupérées: {len(modified_data)} segments")
            
            # Calculer les redevances avec les données modifiées
            from .database_operations import DatabaseOperations
            redevance_data = DatabaseOperations.get_redevance_from_modified_gestionnaire(
                sro, troncon, modified_data
            )
            
            if not redevance_data:
                print("⚠️ Aucune donnée de redevance calculée")
                return
            
            print(f"✅ Redevances calculées avec données modifiées")
            
            # Générer le nouveau fichier Excel
            self._generate_excel_file(sro, troncon, redevance_data, suffix="_gestionnaire_modifié")
            
            print("🎉 Excel régénéré avec succès avec les modifications gestionnaire!")
            
        except Exception as e:
            print(f"❌ Erreur lors de la régénération Excel: {str(e)}")
            import traceback
            traceback.print_exc()
            # Ne pas lancer l'exception pour éviter la fermeture du plugin
    
    def update_buttons_state(self):
        """Met à jour l'état des boutons selon le mode redevance et les modifications"""
        if hasattr(self, 'redevance_mode_gestionnaire') and self.redevance_mode_gestionnaire:
            # Mode gestionnaire - bouton toujours activé mais avec détection intelligente
            self.regenerate_excel_button.setEnabled(True)
            self.regenerate_excel_button.setText("Régénérer Excel (Mode Gestionnaire)")
            print("🔄 Bouton Excel activé - Mode Gestionnaire")
        else:
            # Mode direct - bouton désactivé car Excel généré automatiquement
            self.regenerate_excel_button.setEnabled(False)
            self.regenerate_excel_button.setText("Régénérer Excel (Non disponible en mode direct)")
            print("⚪ Bouton Excel désactivé - Mode Direct")
    
    def connect_gestionnaire_layer_signals(self):
        """Connecte les signaux de modification de la couche gestionnaire"""
        if not hasattr(self, 'redevance_mode_gestionnaire') or not self.redevance_mode_gestionnaire:
            return
            
        # Rechercher la couche gestionnaire active
        project = QgsProject.instance()
        gestionnaire_layer = None
        
        for layer in project.mapLayers().values():
            if hasattr(layer, 'name') and 'gestionnaire' in layer.name().lower():
                gestionnaire_layer = layer
                break
        
        if gestionnaire_layer and hasattr(gestionnaire_layer, 'editingStarted'):
            # Connecter les signaux de modification
            try:
                gestionnaire_layer.editingStarted.connect(self.on_gestionnaire_editing_started)
                gestionnaire_layer.featureAdded.connect(self.on_gestionnaire_modified)
                gestionnaire_layer.featureDeleted.connect(self.on_gestionnaire_modified)
                gestionnaire_layer.attributeValueChanged.connect(self.on_gestionnaire_modified)
                print("CONNEXION: Signaux de modification de la couche gestionnaire connectés")
            except Exception as e:
                print(f"ATTENTION: Erreur connexion signaux: {e}")
    
    def on_gestionnaire_editing_started(self):
        """Appelé quand l'édition de la couche gestionnaire commence"""
        print("ÉDITION: Mode édition activé pour la couche gestionnaire")
        self.regenerate_excel_button.setEnabled(True)
        self.regenerate_excel_button.setText("Régénérer Excel (Modifications détectées)")
    
    def on_gestionnaire_modified(self):
        """Appelé quand la couche gestionnaire est modifiée"""
        print("MODIFICATION: Changements détectés dans la couche gestionnaire")
        self.regenerate_excel_button.setEnabled(True)
        self.regenerate_excel_button.setText("Régénérer Excel (Modifications détectées)")
    
    def get_modified_gestionnaire_data(self, sro, troncon):
        """Récupère les données modifiées de la couche gestionnaire si elle existe et a été modifiée"""
        try:
            # Chercher la couche gestionnaire dans les couches chargées
            gestionnaire_layer = None
            layer_name_pattern = f"Gestionnaire - {sro} - {troncon}"
            
            for layer in self.layers_loaded:
                if layer and layer.isValid() and layer_name_pattern in layer.name():
                    gestionnaire_layer = layer
                    break
            
            if not gestionnaire_layer:
                print("ℹ️ Couche gestionnaire non trouvée - utilisation des données originales")
                return None
            
            print(f"📊 Récupération des données modifiées de la couche gestionnaire")
            print(f"   Couche: {gestionnaire_layer.name()}")
            print(f"   Entités: {gestionnaire_layer.featureCount()}")
            
            # Lire toutes les données de la couche (modifiées ou non)
            modified_data = []
            for feature in gestionnaire_layer.getFeatures():
                row_data = {
                    'troncon_gid': feature.attribute('troncon_gid'),
                    'segment_id': feature.attribute('segment_id'),
                    'cm_gest_do': feature.attribute('cm_gest_do'),
                    'cm_compo': feature.attribute('cm_compo'),
                    'long': feature.attribute('long'),
                    'distance_route_m': feature.attribute('distance_route_m'),
                    'angle_parallelisme_deg': feature.attribute('angle_parallelisme_deg'),
                    'confiance_niveau': feature.attribute('confiance_niveau'),
                    'methode_attribution': feature.attribute('methode_attribution')
                }
                modified_data.append(row_data)
            
            print(f"✅ {len(modified_data)} lignes récupérées de la couche gestionnaire")
            return modified_data
            
        except Exception as e:
            print(f"⚠️ Erreur récupération données gestionnaire: {str(e)}")
            return None
    
    def _auto_generate_excel_direct_mode(self, sro, troncon, results):
        """Génère automatiquement l'Excel en mode direct"""
        try:
            # Calculer les redevances avec les données existantes
            from .database_operations import DatabaseOperations
            redevance_data = DatabaseOperations.get_redevance_from_results(sro, troncon, results)
            
            if not redevance_data:
                print("⚠️ Aucune donnée de redevance calculée")
                return
            
            print(f"✅ Redevances calculées avec données existantes")
            
            # Générer le nouveau fichier Excel
            self._generate_excel_file(sro, troncon, redevance_data, suffix="_direct")
            
            print("🎉 Excel généré automatiquement avec succès en mode direct!")
            
        except Exception as e:
            print(f"❌ Erreur lors de la génération automatique Excel en mode direct: {str(e)}")
            import traceback
            traceback.print_exc()
            # Ne pas lancer l'exception pour éviter la fermeture du plugin
    
    def _generate_excel_file(self, sro, troncon, redevance_data, suffix=""):
        """Génère un fichier Excel avec le template PGC et les données de redevance"""
        try:
            import os
            import tempfile
            import pandas as pd
            from datetime import datetime
            from openpyxl import load_workbook
            import shutil
            
            print(f"🔄 Génération Excel avec template PGC: {len(redevance_data)} entrées de redevance")
            
            # 1. Conversion des données de redevance pour DataFrame
            rows = []
            for entry in redevance_data:
                if isinstance(entry, dict):
                    if 'concessionnaire_voirie' in entry:
                        # Nouveau format avec concessionnaire_voirie
                        row = {'concessionnaire_voirie': entry['concessionnaire_voirie']}
                        total_redevance = 0
                        for key, value in entry.items():
                            if key != 'concessionnaire_voirie':
                                # Conversion Decimal vers float
                                if hasattr(value, '__float__'):
                                    value = float(value)
                                row[key] = value
                                total_redevance += value if isinstance(value, (int, float)) else 0
                        row['total_redevance'] = total_redevance
                        rows.append(row)
                    elif 'redevance_data' in entry:
                        # Ancien format avec redevance_data (rétro-compatibilité)
                        redevance_dict = entry['redevance_data']
                        row = {
                            'concessionnaire_voirie': entry.get('gest_do', ''),
                            'total_redevance': entry.get('total_redevance', 0)
                        }
                        for compo, montant in redevance_dict.items():
                            if hasattr(montant, '__float__'):
                                montant = float(montant)
                            row[compo] = montant
                        rows.append(row)
            
            if not rows:
                print("⚠️ Aucune donnée à exporter")
                return
            
            # 2. Création DataFrame redevance
            df_redevance = pd.DataFrame(rows)
            print(f"✓ DataFrame redevance créé: {len(df_redevance)} lignes, colonnes: {list(df_redevance.columns)}")
            
            # 3. Création DataFrame DQE PGC depuis last_dqe_results
            dqe_pgc_data = []
            if hasattr(self, 'last_dqe_results') and self.last_dqe_results:
                for result in self.last_dqe_results:
                    dqe_pgc_data.append({
                        'Désignation': result.designation,
                        'Unité': getattr(result, 'unite', ''),
                        'Quantité': result.quantite
                    })
            
            df_dqe_pgc = pd.DataFrame(dqe_pgc_data) if dqe_pgc_data else pd.DataFrame([{
                'Désignation': 'Aucune donnée', 'Unité': '', 'Quantité': 0
            }])
            print(f"✓ DataFrame DQE PGC créé: {len(df_dqe_pgc)} lignes")
            
            # 4. Récupération du template PGC
            plugin_dir = os.path.dirname(__file__)
            template_path = os.path.join(plugin_dir, 'files', 'template_dqe_pgc.xlsx')
            
            if not os.path.exists(template_path):
                print(f"❌ Template PGC non trouvé: {template_path}")
                return
            
            print(f"✓ Template PGC trouvé: {template_path}")
            
            # 5. Nettoyage des noms pour fichier
            def clean_filename(name):
                invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
                for char in invalid_chars:
                    name = name.replace(char, '_')
                return name
            
            sro_clean = clean_filename(sro)
            troncon_clean = clean_filename(troncon)
            
            # 6. Génération nom et chemin de fichier
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"redevance_{sro_clean}_{troncon_clean}{suffix}_{timestamp}.xlsx"
            temp_dir = tempfile.gettempdir()
            filepath = os.path.join(temp_dir, filename)
            
            # 7. Copier le template vers le fichier de sortie
            shutil.copy2(template_path, filepath)
            print(f"✓ Template copié vers: {filepath}")
            
            # 8. Charger le workbook et remplir les données avec logique template
            workbook = load_workbook(filepath)
            
            # 9. Remplir la feuille DQE PGC avec le template (comme ExcelManager._fill_pgc_template)
            if 'DQE PGC' in workbook.sheetnames:
                dqe_sheet = workbook['DQE PGC']
                print("✓ Feuille 'DQE PGC' trouvée dans template")
                
                # Appliquer la logique de remplissage comme _fill_pgc_template
                self._fill_template_dqe_pgc(dqe_sheet, df_dqe_pgc, sro, troncon)
            else:
                print("⚠️ Feuille 'DQE PGC' non trouvée dans template")
            
            # 10. Remplir la feuille REDEVANCE
            if 'REDEVANCE' in workbook.sheetnames:
                redevance_sheet = workbook['REDEVANCE']
                print("✓ Feuille 'REDEVANCE' trouvée dans template")
                
                # Remplir avec les données de redevance
                self._fill_template_redevance(redevance_sheet, df_redevance)
            else:
                print("⚠️ Feuille 'REDEVANCE' non trouvée dans template")
                
                # Créer la feuille REDEVANCE manuellement
                redevance_sheet = workbook.create_sheet(title='REDEVANCE')
                print("✓ Feuille 'REDEVANCE' créée")
                
                # Remplir avec les données de redevance
                self._fill_template_redevance(redevance_sheet, df_redevance)
            
            # 11. Sauvegarder et fermer
            workbook.save(filepath)
            workbook.close()
            
            print(f"📄 Fichier Excel généré: {filepath}")
            print(f"📊 Template utilisé avec feuilles DQE PGC ({len(df_dqe_pgc)} lignes) et REDEVANCE ({len(df_redevance)} lignes)")
            
            # 12. Ouverture automatique
            try:
                os.startfile(filepath)
                print("✓ Fichier Excel ouvert automatiquement")
            except Exception as e:
                print(f"⚠ Impossible d'ouvrir automatiquement le fichier: {e}")
            
        except Exception as e:
            print(f"❌ Erreur lors de la génération Excel: {str(e)}")
            import traceback
            print(traceback.format_exc())
    
    def _fill_template_dqe_pgc(self, sheet, df_dqe_pgc, sro, troncon):
        """Remplit la feuille DQE PGC avec la logique du template (comme _fill_pgc_template)"""
        try:
            print(f"🔄 Remplissage template DQE PGC avec {len(df_dqe_pgc)} lignes")
            
            # 1. Gérer la ligne "Nom GC :" dynamiquement
            gc_row = None
            for row in range(1, min(20, sheet.max_row + 1)):
                cell_value = sheet.cell(row=row, column=1).value
                if cell_value and "Nom GC :" in str(cell_value):
                    gc_row = row
                    break
            
            if gc_row:
                new_gc_text = f"Nom GC : {troncon}"
                sheet.cell(row=gc_row, column=1, value=new_gc_text)
                print(f"✓ Ligne GC mise à jour: '{new_gc_text}'")
            
            # 2. Rechercher la ligne d'en-tête "Désignation"
            header_row = None
            for row in range(1, min(50, sheet.max_row + 1)):
                cell_value = sheet.cell(row=row, column=1).value
                if cell_value and "Désignation" in str(cell_value):
                    header_row = row
                    break
            
            if not header_row:
                header_row = 1
            
            # 3. Séparer les données DQE en alvéoles et autres
            alveoles_data = []
            other_data = []
            
            for _, result_row in df_dqe_pgc.iterrows():
                designation = str(result_row['Désignation']).strip()
                quantite = result_row['Quantité']
                unite = result_row.get('Unité', 'ml')
                
                # Ignorer les en-têtes et lignes spéciales
                if not designation or designation == 'Aucune donnée':
                    continue
                
                # Détecter les éléments d'alvéoles (PVC/PEHD)
                if any(x in designation.lower() for x in ["pvc ", "pehd"]):
                    alveoles_data.append({
                        'designation': designation,
                        'unite': unite,
                        'quantite': quantite
                    })
                else:
                    other_data.append({
                        'designation': designation,
                        'unite': unite,
                        'quantite': quantite
                    })
            
            # 4. Traiter les éléments standards avec correspondance intelligente
            matched_count = 0
            for data in other_data:
                template_row = self._find_template_row_simple(sheet, data['designation'], header_row)
                if template_row:
                    sheet.cell(row=template_row, column=3, value=data['quantite'])
                    matched_count += 1
                    print(f"✓ {data['designation']} → ligne {template_row} (quantité: {data['quantite']})")
                else:
                    print(f"⚠️ Pas de correspondance trouvée pour: {data['designation']}")
            
            # 5. Traiter les alvéoles dynamiquement
            if alveoles_data:
                alveoles_section_row = None
                for row in range(header_row, sheet.max_row + 1):
                    cell_value = sheet.cell(row=row, column=1).value
                    if cell_value and "Fourniture des Alvéoles" in str(cell_value):
                        alveoles_section_row = row
                        break
                
                if alveoles_section_row:
                    next_row = alveoles_section_row + 1
                    for alv_data in alveoles_data:
                        # Trouver la prochaine ligne vide
                        while next_row <= sheet.max_row and sheet.cell(row=next_row, column=1).value:
                            next_row += 1
                        
                        sheet.cell(row=next_row, column=1, value=alv_data['designation'])
                        sheet.cell(row=next_row, column=2, value=alv_data['unite'])
                        sheet.cell(row=next_row, column=3, value=alv_data['quantite'])
                        print(f"✓ Alvéole ajoutée: {alv_data['designation']} → ligne {next_row}")
                        next_row += 1
                        matched_count += 1
            
            print(f"✓ Template DQE PGC rempli: {matched_count} éléments traités")
            
        except Exception as e:
            print(f"❌ Erreur remplissage template DQE PGC: {e}")
    
    def _fill_template_redevance(self, sheet, df_redevance):
        """Remplit la feuille REDEVANCE avec les données"""
        try:
            print(f"🔄 Remplissage template REDEVANCE avec {len(df_redevance)} lignes")
            
            # Trouver la ligne de départ (après les en-têtes)
            start_row = 2  # Par défaut ligne 2
            
            # Vider les données existantes mais préserver les en-têtes
            for row in range(start_row, sheet.max_row + 1):
                for col in range(1, sheet.max_column + 1):
                    sheet.cell(row=row, column=col, value=None)
            
            # Écrire les en-têtes (colonnes DataFrame)
            for col_idx, column_name in enumerate(df_redevance.columns, 1):
                sheet.cell(row=1, column=col_idx, value=column_name)
            
            # Écrire les données
            for row_idx, (_, row_data) in enumerate(df_redevance.iterrows(), start_row):
                for col_idx, value in enumerate(row_data, 1):
                    sheet.cell(row=row_idx, column=col_idx, value=value)
            
            print(f"✓ Template REDEVANCE rempli: {len(df_redevance)} lignes de données")
            
        except Exception as e:
            print(f"❌ Erreur remplissage template REDEVANCE: {e}")
    
    def _find_template_row_simple(self, sheet, designation, start_row):
        """Trouve la ligne correspondante dans le template avec correspondance simple"""
        designation_clean = self._smart_match_simple(designation)
        
        for row in range(start_row, min(sheet.max_row + 1, start_row + 200)):
            cell_value = sheet.cell(row=row, column=1).value
            if not cell_value:
                continue
            
            template_clean = self._smart_match_simple(str(cell_value))
            
            # Correspondance exacte après nettoyage
            if template_clean == designation_clean:
                return row
            
            # Correspondance partielle pour les variations mineures
            if len(designation_clean) > 5 and len(template_clean) > 5:
                from difflib import SequenceMatcher
                similarity = SequenceMatcher(None, designation_clean, template_clean).ratio()
                if similarity >= 0.8:  # 80% de similarité
                    return row
        
        return None
    
    def _smart_match_simple(self, text):
        """Nettoie et normalise le texte pour la correspondance"""
        if not text:
            return ""
        
        import re
        
        # Conversion en minuscules
        text = text.lower().strip()
        
        # Normalisation FO (avec/sans espace)
        text = re.sub(r'(\d+)\s*fo\b', r'\1 fo', text)
        
        # Normalisation "câble optique" -> "câble"
        text = re.sub(r'câble\s+optique', 'câble', text)
        
        # Suppression caractères de ponctuation parasites
        text = re.sub(r'[^\w\s\(\)\/\-\.]', '', text)
        
        # Normalisation espaces multiples
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    def _load_organized_layers(self, results, sro, troncon_safe):
        """Chargement organisé par catégories - VERSION PGC"""
        created_layers = []
        
        # Catégories spécifiques pour DQE PGC selon demande utilisateur
        # NOTE: "Gestionnaires" géré séparément selon le mode choisi par l'utilisateur
        categories = {
            "GC - TDR + RAD (hors fourniture tube PEHD ou PVC et chambres)": [],
            "Chambres": [],
            "Poteaux": [],
            "Fourniture des alvéoles": []
        }
        
        print(f"\n=== DÉBUT TRAITEMENT DQE PGC ORGANISÉ - {len(results)} résultats ===")
        
        for i, result in enumerate(results):
            designation = result.designation if hasattr(result, 'designation') else ""
            
            if not designation:
                print(f"[{i+1}] 🚫 IGNORÉ - Pas de désignation")
                continue
            
            ids = result.ids if hasattr(result, 'ids') else []
            quantite = result.quantite if hasattr(result, 'quantite') else 0
            
            print(f"\n[{i+1}] Traitement: {designation}")
            print(f"    Quantité: {quantite}")
            print(f"    IDs: {len(ids) if ids else 0} éléments")
            
            if not ids or len(ids) == 0:
                print(f"    🚫 IGNORÉ - Pas d'IDs (en-tête ou section)")
                continue
            
            try:
                quantite_num = float(quantite) if quantite is not None else 0
                if quantite_num <= 0:
                    print(f"    🚫 IGNORÉ - Quantité nulle ou négative ({quantite_num})")
                    continue
            except (ValueError, TypeError):
                print(f"    🚫 IGNORÉ - Quantité invalide: {quantite}")
                continue
            
            main_category = None
            designation_lower = designation.lower()
            
            # Catégorisation selon les spécifications PGC
            if any(x in designation_lower for x in ["chambre", "ch ", "regard"]):
                main_category = "Chambres"
                print(f"    🏠 Détecté comme Chambre: {designation}")
            elif any(x in designation_lower for x in ["poteau", "pt ", "appui"]):
                main_category = "Poteaux"
                print(f"    🏗️ Détecté comme Poteau: {designation}")
            elif any(x in designation_lower for x in ["alvéole", "alveole", "fourniture alvéole", "fourniture alveole", "tube pehd", "tube pvc", "fourniture tube", "pvc ", "pehd ", " pvc", " pehd"]):
                main_category = "Fourniture des alvéoles"
                print(f"    📦 Détecté comme Fourniture alvéole/tube: {designation}")
            elif any(x in designation_lower for x in ["tdr", "rad", "gc ", "génie civil", "tranchée", "forage", "tirage", "pose", "infrastructure", "encorbellement"]):
                # Catégorie principale: GC - TDR + RAD (hors fournitures et chambres)
                main_category = "GC - TDR + RAD (hors fourniture tube PEHD ou PVC et chambres)"
                print(f"    🚧 Détecté comme GC-TDR+RAD: {designation}")
            
            if not main_category:
                print(f"    🚫 IGNORÉ - Aucune catégorie déterminée")
                continue
            
            table_name = LayerManager.get_table_from_designation_pgc(designation)
            print(f"    📊 Table: {table_name}")
            
            task_data = {
                'designation': designation,
                'ids': ids,
                'table_name': table_name,
                'layer_id': str(uuid.uuid4()),
                'priority': LayerManager.get_custom_layer_order(designation) if hasattr(LayerManager, 'get_custom_layer_order') else 0,
                'sro': sro
            }
            
            categories[main_category].append(task_data)
            print(f"     ✅ Assigné à la catégorie: {main_category}")
        
        # Charger les couches par catégorie
        for category_name, tasks in categories.items():
            if not tasks:
                continue
            
            print(f"\n=== CHARGEMENT CATÉGORIE: {category_name} ===")
            print(f"Éléments à charger: {len(tasks)}")
            
            # Créer un sous-groupe pour chaque catégorie
            category_group = LayerManager.create_layer_subgroup(self.layer_group, category_name)
            
            for task in tasks:
                layer_name = f"{task['designation']}"
                if troncon_safe:
                    layer_name += f" - {troncon_safe}"
                
                print(f"  🔄 Chargement: {layer_name}")
                
                ids_string = ','.join(map(str, task['ids'])) if task['ids'] else ""
                
                layer = LayerManager.load_layer_direct(
                    layer_name,
                    ids_string,
                    task['table_name'],
                    task['sro']
                )
                
                if layer and layer.isValid():
                    QgsProject.instance().addMapLayer(layer, False)
                    category_group.addLayer(layer)
                    created_layers.append(layer)
                    self.layers_loaded.append(layer)
                    
                    print(f"    ✅ COUCHE CRÉÉE ({layer.featureCount()} entités)")
                else:
                    print(f"    ❌ ÉCHEC CRÉATION COUCHE: {layer_name}")
        
        print(f"\n=== RÉSUMÉ CHARGEMENT ORGANISÉ ===")
        for category_name, tasks in categories.items():
            if tasks:
                print(f"📁 {category_name}: {len(tasks)} couches")
        
        print(f"✅ Total: {len(created_layers)} couches créées avec organisation")
        return created_layers
    
    def update_buttons_state(self):
        """Met à jour l'état des boutons selon le mode redevance et les modifications"""
        if hasattr(self, 'redevance_mode_gestionnaire') and self.redevance_mode_gestionnaire:
            # Mode gestionnaire - bouton toujours activé mais avec détection intelligente
            self.regenerate_excel_button.setEnabled(True)
            self.regenerate_excel_button.setText("Régénérer Excel (Mode Gestionnaire)")
            print("🔄 Bouton Excel activé - Mode Gestionnaire")
        else:
            # Mode direct - bouton désactivé car Excel généré automatiquement
            self.regenerate_excel_button.setEnabled(False)
            self.regenerate_excel_button.setText("Régénérer Excel (Non disponible en mode direct)")
            print("⚪ Bouton Excel désactivé - Mode Direct")
