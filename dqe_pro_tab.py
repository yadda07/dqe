"""
DQE PRO Tab Module

Handles the DQE PRO tab interface and functionality for the QGIS plugin.
Extracted from the main dialog file for better modularity.
"""

import os
import csv
import json
import time
import uuid
from typing import List, Dict, Any

from PyQt5.QtCore import QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QPushButton, QComboBox, QMessageBox, QApplication
)
from qgis.PyQt.QtCore import QObject
from qgis.core import QgsProject, Qgis, QgsApplication
from qgis import utils

# Import des modules du plugin
from .ui_components import SROComboBox, ProgressWidget
from .layer_manager import LayerManager
from .database_operations import DatabaseOperations
from .excel_manager import ExcelManager

# Récupération des singletons depuis le module principal
try:
    iface = utils.iface
    from . import dqe_chargeur_dialog
    _db_manager = getattr(dqe_chargeur_dialog, '_db_manager', None)
    _logger = getattr(dqe_chargeur_dialog, '_logger', None)
except (ImportError, AttributeError):
    iface = None
    _db_manager = None
    _logger = None


class DQEWorker(QObject):
    """Worker pour traiter les DQE en arrière-plan avec mise à jour de progression"""
    progress_updated = pyqtSignal(int, str)  # (progress, status)
    finished = pyqtSignal(bool, object, str)  # (success, results, message)
    
    def __init__(self, operation_type, sro, p_type=None, troncon=None):
        super().__init__()
        self.operation_type = operation_type
        self.sro = sro
        self.p_type = p_type
        self.troncon = troncon
        self.is_cancelled = False
        self.results = None
        self.error_message = None
        self.is_running = False
        self.progress_value = 0
    
    def cancel(self):
        """Méthode pour annuler le traitement"""
        self.is_cancelled = True
        print(f" Annulation demandée pour DQE {self.operation_type}")
    
    def run(self):
        """Exécute le traitement DQE avec gestion d'erreur"""
        self.is_running = True
        self.progress_value = 15
        
        try:
            print(f" Début traitement DQE {self.operation_type}")
            
            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annulé")
                return
            
            # Préparation
            self.progress_value = 25
            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annulé")
                return
                
            # Préparation de la requête
            self.progress_value = 35
            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annulé")
                return
            
            # Exécution de la requête principale
            self.progress_value = 40
            
            if self.operation_type == "PRO":
                self.results = DatabaseOperations.execute_dqe_pro(self.sro, self.p_type)
            elif self.operation_type == "EXE":
                self.results = DatabaseOperations.execute_dqe_exe(self.sro, self.p_type)
            elif self.operation_type == "PGC":
                self.results = DatabaseOperations.execute_dqe_pgc(self.sro, self.troncon)
            else:
                self.results = []
            
            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annulé")
                return
            
            # Traitement des résultats
            self.progress_value = 85
            
            # Filtrage si nécessaire
            if self.operation_type == "PRO" and self.results:
                self.results = DQEProTab.filter_results_by_template(self.results)
            
            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annulé")
                return
                
            # Finalisation
            self.progress_value = 90
            
            success_message = f"DQE {self.operation_type} terminé avec succès"
            print(f" {success_message} - {len(self.results) if self.results else 0} résultats")
            self.finished.emit(True, self.results, success_message)
            
        except Exception as e:
            self.error_message = f"Erreur DQE {self.operation_type}: {str(e)}"
            print(f" {self.error_message}")
            import traceback
            print(traceback.format_exc())
            self.finished.emit(False, None, self.error_message)
        finally:
            self.is_running = False


class DQEProTab(QWidget):
    """Interface et logique pour l'onglet DQE PRO"""
    
    @staticmethod
    def filter_results_by_template(results):
        """Filtre les résultats DQE Pro pour ne garder que les lignes présentes dans le template CSV"""
        try:
            # Chemin vers le template CSV
            plugin_dir = os.path.dirname(__file__)
            template_path = os.path.join(plugin_dir, 'files', 'template_dqe_pro.csv')
            
            if not os.path.exists(template_path):
                print(f" Template CSV non trouvé: {template_path}")
                return results  # Retourner tous les résultats si pas de template
            
            # Charger les désignations du template
            template_designations = set()
            with open(template_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter=';')
                for row in reader:
                    designation = row.get('Désignation', '').strip()
                    if designation:
                        template_designations.add(designation)
            
            print(f"📋 Template chargé: {len(template_designations)} désignations")
            
            # Filtrer les résultats
            filtered_results = []
            excluded_count = 0
            
            for result in results:
                designation = result.get("designation") or result.get("Désignation") or result.get("désignation") or ""
                
                if designation in template_designations:
                    filtered_results.append(result)
                else:
                    excluded_count += 1
                    print(f" EXCLU (non dans template): {designation}")
            
            print(f" Filtrage terminé: {len(filtered_results)} lignes conservées, {excluded_count} exclues")
            return filtered_results
            
        except Exception as e:
            print(f" Erreur lors du filtrage: {str(e)}")
            return results  # En cas d'erreur, retourner tous les résultats

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers_loaded = []
        self.layer_group = None
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        config_group = QGroupBox("Configuration DQE PRO")
        config_layout = QFormLayout(config_group)
        
        self.sro_input = SROComboBox()
        config_layout.addRow("SRO:", self.sro_input)
        
        self.type_combo = QComboBox()
        self.type_combo.addItem("Transport", "T")
        self.type_combo.addItem("Distribution", "D")
        config_layout.addRow("Type:", self.type_combo)
        
        layout.addWidget(config_group)
        
        buttons_layout = QHBoxLayout()
        
        self.execute_button = QPushButton("Exécuter DQE PRO")
        self.execute_button.clicked.connect(self.execute_dqe_pro)
        buttons_layout.addWidget(self.execute_button)
        
        self.validate_button = QPushButton("Valider DQE")
        self.validate_button.clicked.connect(self.validate_dqe_pro)
        buttons_layout.addWidget(self.validate_button)
        
        layout.addLayout(buttons_layout)
        
        self.progress_widget = ProgressWidget()
        layout.addWidget(self.progress_widget)
        
        layout.addStretch()
    
    def execute_dqe_pro(self):
        sro = self.sro_input.lineEdit().text().strip()
        p_type = self.type_combo.currentData()
        
        if not sro:
            QMessageBox.warning(self, "Erreur", "Veuillez saisir un SRO")
            return
        
        # Désactiver le bouton pendant le traitement
        self.execute_button.setEnabled(False)
        
        try:
            self.progress_widget.start_operation("DQE PRO")
            
            # Créer le worker et le thread
            self.worker = DQEWorker("PRO", sro, p_type)
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
                    
                    status = "Traitement DQE PRO en cours..."
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
            self.worker.finished.connect(self.on_dqe_pro_finished)
            self.progress_widget.progress_cancelled.connect(self.worker.cancel)
            self.thread.started.connect(self.worker.run)
            self.thread.finished.connect(self.thread.deleteLater)
            
            # Démarrer le thread
            self.thread.start()
            
        except Exception as e:
            error_msg = f"Erreur initialisation DQE PRO: {str(e)}"
            print(f"\n ERREUR DQE PRO: {error_msg}")
            self.progress_widget.complete_operation(False, error_msg)
            self.execute_button.setEnabled(True)
            QMessageBox.critical(self, "Erreur", error_msg)
    
    def on_dqe_pro_finished(self, success: bool, results, message: str):
        """Callback appelé quand le traitement DQE PRO est terminé"""
        try:
            # Continuer la progression fluide au lieu de l'arrêter brutalement
            if hasattr(self, 'progress_timer'):
                # Changer le comportement du timer pour la phase post-traitement
                self.post_processing = True
                
            if success and results:
                # Traitement post-requête dans le thread principal
                self.smooth_progress_to(92, "Création des couches...")
                
                # Forcer le rafraîchissement de l'interface
                QApplication.processEvents()
                
                # Créer le groupe de couches
                current_date = time.strftime("%Y-%m-%d_%H%M%S")
                sro = self.sro_input.lineEdit().text().strip()
                sro_safe = sro.replace('/', '_')
                group_name = f"DQE_PRO_{sro_safe}_{current_date}"
                self.layer_group = LayerManager.create_layer_group(group_name)
                
                # Charger les couches
                created_layers = self._load_organized_layers(results, sro, self.type_combo.currentData())
                
                # Forcer le rafraîchissement
                QApplication.processEvents()
                
                # Chargement des câbles découpés pour Distribution
                if self.type_combo.currentData() == 'D':
                    print("\n=== CHARGEMENT CÂBLES DÉCOUPÉS (Distribution) ===")
                    self.smooth_progress_to(95, "Chargement câbles découpés...")
                    QApplication.processEvents()
                    
                    dist_layers = LayerManager.load_distribution_cables(
                        sro, self.layer_group, self.layers_loaded
                    )
                    created_layers.extend(dist_layers)
                    print(f"=== CÂBLES DÉCOUPÉS AJOUTÉS: {len(dist_layers)} ===")
                
                # Créer le rapport Excel
                self.smooth_progress_to(98, "Génération du rapport Excel...")
                QApplication.processEvents()
                ExcelManager.create_excel_report(results, sro, "PRO")
                
                # Finaliser
                self.smooth_progress_to(100, "Finalisation...")
                QApplication.processEvents()
                
                final_message = f"DQE PRO terminé: {len(created_layers)} couches créées"
                self.progress_widget.complete_operation(True, final_message)
                
                if iface:
                    iface.messageBar().pushMessage(
                        "DQE PRO", final_message,
                        level=Qgis.Success, duration=5
                    )
            else:
                self.progress_widget.complete_operation(False, message)
                QMessageBox.critical(self, "Erreur", message)
                
        except Exception as e:
            error_msg = f"Erreur post-traitement DQE PRO: {str(e)}"
            print(f" {error_msg}")
            import traceback
            print(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
            QMessageBox.critical(self, "Erreur", error_msg)
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
                    self.current_progress += (target_value - self.current_progress) / (steps - i)
                    self.progress_widget.update_progress(int(self.current_progress), status)
                    QApplication.processEvents()
                    time.sleep(0.05)  # Petite pause pour rendre la progression visible
            
            # S'assurer qu'on atteint la valeur cible
            self.current_progress = target_value
            self.progress_widget.update_progress(int(self.current_progress), status)
    
    def _load_organized_layers(self, results, sro, p_type):
        """Chargement organisé par catégories"""
        created_layers = []
        
        categories = {
            "Prises": [],
            "GC/Infrastructures": [],
            "Câble aérien": [],
            "Câble sout": [],
            "BPE facade": [],
            "BPE aérien": [],
            "BPE sout": [],
            "PA aérien": [],
            "PA souterrain": [],
            "PBO": [],
            "SRO": [],
            "Autres": []
        }
        
        print(f"\n=== DÉBUT TRAITEMENT DQE PRO - {len(results)} résultats ===")
        
        for i, result in enumerate(results):
            designation = result.get("designation") or result.get("Désignation") or result.get("désignation") or ""
            
            if not designation:
                print(f"[{i+1}]  IGNORÉ - Pas de désignation")
                continue
            
            ids = result.get("ids") or result.get("Ids") or ""
            quantite = result.get("quantite") or result.get("Quantité") or result.get("quantité") or 0
            unite = result.get("unite") or result.get("Unité") or result.get("unité") or ""
            
            print(f"\n[{i+1}] Traitement: {designation}")
            print(f"    Quantité: {quantite}, Unité: {unite}")
            print(f"    IDs: {str(ids)[:100]}{'...' if len(str(ids)) > 100 else ''}")
            
            if not ids or len(str(ids).strip()) == 0:
                print(f"     IGNORÉ - Pas d'IDs (en-tête ou section)")
                continue
            
            try:
                quantite_num = float(quantite) if quantite is not None else 0
                if quantite_num <= 0:
                    print(f"     IGNORÉ - Quantité nulle ou négative ({quantite_num})")
                    continue
            except (ValueError, TypeError):
                print(f"     IGNORÉ - Quantité invalide: {quantite}")
                continue
            
            main_category = None
            designation_lower = designation.lower()
            
            if any(x in designation_lower for x in ["prise", "dtr", "rad", "nbre de prises"]):
                main_category = "Prises"
            elif "sro" in designation_lower:
                main_category = "SRO"
            elif "bpe" in designation_lower or "f&p bpe" in designation_lower:
                if "façade" in designation_lower:
                    main_category = "BPE facade"
                elif "aérien" in designation_lower:
                    main_category = "BPE aérien"
                elif "conduite" in designation_lower or "sout" in designation_lower:
                    main_category = "BPE sout"
                else:
                    main_category = "BPE facade"
            elif ("pa " in designation_lower or "f&p pa" in designation_lower) and "pbo" not in designation_lower:
                if "aérien" in designation_lower:
                    main_category = "PA aérien"
                elif "conduite" in designation_lower or "souterrain" in designation_lower:
                    main_category = "PA souterrain"
                else:
                    main_category = "PA aérien"
            elif "pbo" in designation_lower or "f&p de pbo" in designation_lower:
                main_category = "PBO"
            elif any(x in designation_lower for x in ["câble", "cable", "fibre", "fo ", "fourniture et pose de câble"]):
                if p_type == 'D':
                    if any(x in designation_lower for x in ["câble optique", "câble de"]) and \
                       any(x in designation_lower for x in ["aérien", "façade", "conduite"]) and \
                       any(x in designation_lower for x in ["fo en", "fo "]):
                        print(f"     IGNORÉ - Câble remplacé par câbles découpés")
                        continue
                
                if "aérien" in designation_lower:
                    main_category = "Câble aérien"
                elif "conduite" in designation_lower or "sout" in designation_lower:
                    main_category = "Câble sout"
                else:
                    main_category = "Câble sout"
            elif any(x in designation_lower for x in ["gc", "génie civil", "cheminement", "lineaire", "infra"]):
                main_category = "GC/Infrastructures"
            else:
                main_category = "Autres"
                print(f"     Catégorie par défaut: Autres")
            
            if not main_category:
                print(f"     IGNORÉ - Aucune catégorie déterminée")
                continue
            
            table_name = LayerManager.get_table_from_designation(designation)
            print(f"    Table déterminée: {table_name}")
            
            task_data = {
                'layer_name': designation,
                'ids_str': str(ids),
                'table_name': table_name,
                'layer_id': str(uuid.uuid4()),
                'priority': LayerManager.get_custom_layer_order(designation),
                'sro': sro
            }
            
            categories[main_category].append(task_data)
            print(f"     Assigné à la catégorie: {main_category}")
        
        # Charger les couches par catégorie
        for category_name, tasks in categories.items():
            if not tasks:
                continue
            
            print(f"\n--- Traitement catégorie: {category_name} ({len(tasks)} couches) ---")
            category_group = self.layer_group.addGroup(category_name)
            
            for i, task_data in enumerate(tasks):
                try:
                    print(f"[{time.strftime('%H:%M:%S')}] Chargement de {task_data['layer_name']} ({i+1}/{len(tasks)})")
                    
                    QgsApplication.processEvents()
                    
                    layer = LayerManager.load_layer_direct(
                        task_data['layer_name'], 
                        task_data['ids_str'], 
                        task_data['table_name'], 
                        sro
                    )
                    
                    if layer and layer.isValid():
                        QgsProject.instance().addMapLayer(layer, False)
                        category_group.addLayer(layer)
                        created_layers.append(layer)
                        self.layers_loaded.append(layer)
                        
                        print(f"     COUCHE CRÉÉE - {layer.featureCount()} entités")
                        if iface:
                            iface.mainWindow().statusBar().showMessage(f"Chargé {len(created_layers)} couches")
                    else:
                        print(f"     ÉCHEC CRÉATION COUCHE")
                        
                except Exception as e:
                    print(f"     Erreur lors du chargement de {task_data['layer_name']}: {str(e)}")
        
        print(f"\n=== COUCHES STANDARD CRÉÉES: {len(created_layers)} ===")
        return created_layers
    
    def validate_dqe_pro(self):
        """Valide et sauvegarde le DQE PRO dans la base de données"""
        try:
            # Vérifications préliminaires
            sro = self.sro_input.currentText().strip()
            if not sro:
                QMessageBox.warning(self, "Validation DQE", "Veuillez sélectionner un SRO")
                return
            
            if not self.layer_group or not self.layers_loaded:
                QMessageBox.warning(self, "Validation DQE", "Aucune couche DQE PRO chargée à valider")
                return
            
            print(f"DEBUG: Validation DQE PRO - {len(self.layers_loaded)} couches à traiter")
            
            # Détermination du code projet selon le type sélectionné
            type_data = self.type_combo.currentData()
            if type_data == "T":
                projet_code = "TP"  # Transport PRO
            else:
                projet_code = "DP"  # Distribution PRO
            
            # Récupération des informations utilisateur
            user_name = _db_manager._config.user if _db_manager._config else "unknown"
            
            success_count = 0
            total_layers = len(self.layers_loaded)
            
            # Sauvegarde de chaque couche dans dqe.dqejson
            for i, layer in enumerate(self.layers_loaded):
                print(f"DEBUG: Couche {i+1}/{total_layers}: {layer.name() if hasattr(layer, 'name') else 'SANS NOM'}")
                
                if not layer.isValid():
                    print(f"DEBUG: - Couche INVALIDE, ignorée")
                    continue
                
                print(f"DEBUG: - Couche valide, {layer.featureCount()} features")
                
                try:
                    # Transaction séparée pour chaque couche
                    with _db_manager.get_cursor() as cursor:
                        # Extraction des données de la couche
                        layer_data = self._extract_layer_data(layer)
                        print(f"DEBUG: - Données extraites: {len(layer_data.get('features', []))} features")
                        
                        # Insertion dans dqe.dqejson
                        query = """
                            INSERT INTO dqe.dqejson 
                            (sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """
                        
                        print(f"DEBUG: - Insertion SQL pour {layer.name()}")
                        cursor.execute(query, (
                            sro,
                            f"DQE_PRO_{sro}",
                            projet_code,
                            layer.name(),
                            json.dumps(layer_data),
                            user_name,
                            "dqe"
                        ))
                        
                        success_count += 1
                        print(f"DEBUG: - Couche {layer.name()} sauvegardée avec succès")
                        
                except Exception as e:
                    print(f"DEBUG: - ERREUR pour {layer.name()}: {str(e)}")
                    import traceback
                    print(f"DEBUG: - Traceback: {traceback.format_exc()}")
                    if _logger:
                        _logger.error(f"Erreur validation couche {layer.name()}: {str(e)}")
            
            print(f"DEBUG: Validation terminée: {success_count}/{total_layers} couches sauvegardées")
            
            # Message de confirmation
            QMessageBox.information(
                self, 
                "Validation DQE PRO", 
                f"Validation terminée avec succès !\n\n"
                f"- SRO: {sro}\n"
                f"- Type: {projet_code}\n"
                f"- Couches sauvegardées: {success_count}/{total_layers}"
            )
            
        except Exception as e:
            print(f"DEBUG: Erreur générale validation: {str(e)}")
            import traceback
            print(f"DEBUG: Traceback général: {traceback.format_exc()}")
            if _logger:
                _logger.error("Erreur lors de la validation DQE PRO", exception=e)
            QMessageBox.critical(self, "Erreur", f"Erreur lors de la validation DQE PRO: {str(e)}")
    
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
