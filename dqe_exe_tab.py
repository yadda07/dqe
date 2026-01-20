"""
DQE EXE Tab Module

Handles the DQE EXE tab interface and functionality for the QGIS plugin.
Extracted from the main dialog file for better modularity.
"""

import os
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
from .ui_components import SROComboBox, ProgressWidget
from .layer_manager import LayerManager
from .database_operations import DatabaseOperations
from .excel_manager import ExcelManager

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


class DQEExeWorker(QObject):
    """Worker dédié DQE EXE avec support blocage_ran"""
    finished = pyqtSignal(bool, object, str)
    
    def __init__(self, sro, p_type, blocage=None):
        super().__init__()
        self.sro = sro
        self.p_type = p_type
        self.blocage = blocage
        self.is_cancelled = False
        self.results = None
        self.is_running = False
        self.progress_value = 0
    
    def cancel(self):
        self.is_cancelled = True
    
    def run(self):
        self.is_running = True
        self.progress_value = 15
        try:
            if self.is_cancelled:
                self.finished.emit(False, None, "Annulé")
                return
            self.progress_value = 40
            self.results = DatabaseOperations.execute_dqe_exe(self.sro, self.p_type, self.blocage)
            self.progress_value = 85
            if self.is_cancelled:
                self.finished.emit(False, None, "Annulé")
                return
            self.progress_value = 90
            print(f"DQE EXE terminé - {len(self.results) if self.results else 0} résultats")
            self.finished.emit(True, self.results, "DQE EXE terminé")
        except Exception as e:
            print(f"Erreur DQE EXE: {str(e)}")
            import traceback
            print(traceback.format_exc())
            self.finished.emit(False, None, f"Erreur: {str(e)}")
        finally:
            self.is_running = False


class DQEExeTab(QWidget):
    """Interface et logique pour l'onglet DQE EXE"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers_loaded = []
        self.layer_group = None
        self.dqe_results = None  # Stockage resultats SQL
        self.current_type = None  # Type courant (T/D)
        self.current_blocage = 'E'  # Mode blocage: E/T/B
        self.current_mode_code = None  # Code complet: TE/DE/TT/DT/TB/DB
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        config_group = QGroupBox("Configuration DQE EXE")
        config_layout = QFormLayout(config_group)
        
        self.sro_input = SROComboBox()
        config_layout.addRow("SRO:", self.sro_input)
        
        self.type_combo = QComboBox()
        self.type_combo.addItem("Transport", "T")
        self.type_combo.addItem("Distribution", "D")
        config_layout.addRow("Type:", self.type_combo)
        
        # Mode blocage RAN
        self.blocage_combo = QComboBox()
        self.blocage_combo.addItem("Standard (TE/DE)", "E")
        self.blocage_combo.addItem("Travaux - sans blocage (TT/DT)", "T")
        self.blocage_combo.addItem("Blocage RAN uniquement (TB/DB)", "B")
        self.blocage_combo.setToolTip("E=Standard, T=Travaux (exclut blocage_ran=true), B=Blocage uniquement")
        config_layout.addRow("Mode:", self.blocage_combo)
        
        layout.addWidget(config_group)
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)  # Espacement réduit entre boutons
        
        self.execute_button = QPushButton("Exécuter DQE EXE")
        self.execute_button.setToolTip("Génère le DQE Exécution avec génie civil")
        self.execute_button.clicked.connect(self.execute_dqe_exe)
        buttons_layout.addWidget(self.execute_button)
        
        self.validate_button = QPushButton("Valider DQE")
        self.validate_button.setToolTip("Enregistre le DQE dans la base de données")
        self.validate_button.clicked.connect(self.validate_dqe_exe)
        buttons_layout.addWidget(self.validate_button)
        
        layout.addLayout(buttons_layout)
        self.progress_widget = ProgressWidget()
        layout.addWidget(self.progress_widget)
        self.sro_input.lineEdit().textChanged.connect(self.on_sro_changed)
    
    def on_sro_changed(self):
        sro = self.sro_input.lineEdit().text().strip()
        if sro and len(sro) >= 3:
            self.execute_button.setEnabled(False)
            QTimer.singleShot(1000, lambda: self.validate_sro_async(sro))
    
    def validate_sro_async(self, sro: str):
        if sro != self.sro_input.lineEdit().text().strip():
            return
        
        if _validator:
            is_valid, message = _validator.validate_sro_exists(sro)
            if is_valid:
                self.execute_button.setEnabled(True)
    
    def execute_dqe_exe(self):
        """Exécution DQE EXE avec interface uniforme"""
        sro = self.sro_input.lineEdit().text().strip()
        p_type = self.type_combo.currentData()
        blocage = self.blocage_combo.currentData()  # E/T/B
        
        if not sro:
            QMessageBox.warning(self, "Erreur", "Veuillez saisir un SRO")
            return
        self.execute_button.setEnabled(False)
        self.current_blocage = blocage  # Stocker pour nommage Excel
        
        try:
            mode_label = self.blocage_combo.currentText()
            self.progress_widget.start_operation(f"DQE EXE ({mode_label})")
            self.worker = DQEExeWorker(sro, p_type, blocage)
            self.thread = QThread()
            self.progress_timer = QTimer()
            self.current_progress = 10
            self.progress_increment = 1
            
            def update_smooth_progress():
                if hasattr(self, 'worker') and self.worker.is_running:
                    target_progress = getattr(self.worker, 'progress_value', 10)
                    
                    if self.current_progress < target_progress:
                        self.current_progress = min(self.current_progress + self.progress_increment, target_progress)
                    elif self.current_progress < 90:  # Progression continue même sans cible
                        self.current_progress += 0.5
                    
                    status = "Traitement DQE EXE en cours..."
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
            self.worker.moveToThread(self.thread)
            self.worker.finished.connect(self.on_dqe_exe_finished)
            self.progress_widget.progress_cancelled.connect(self.worker.cancel)
            self.thread.started.connect(self.worker.run)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.start()
            
        except Exception as e:
            error_msg = f"Erreur initialisation DQE EXE: {str(e)}"
            print(f"ERREUR DQE EXE: {error_msg}")
            self.progress_widget.complete_operation(False, error_msg)
            self.execute_button.setEnabled(True)
            QMessageBox.critical(self, "Erreur", error_msg)
    
    def on_dqe_exe_finished(self, success: bool, results, message: str):
        """Callback appelé quand le traitement DQE EXE est terminé"""
        try:
            if hasattr(self, 'progress_timer'):
                self.post_processing = True
                
            if success and results:
                self.smooth_progress_to(92, "Création des couches...")
                QApplication.processEvents()
                current_date = time.strftime("%Y-%m-%d_%H%M%S")
                sro = self.sro_input.lineEdit().text().strip()
                sro_safe = sro.replace('/', '_')
                
                # Code mode complet: TE/DE/TT/DT/TB/DB
                p_type = self.type_combo.currentData()  # T ou D
                blocage = getattr(self, 'current_blocage', 'E')  # E/T/B
                mode_code = f"{p_type}{blocage}"  # Ex: TE, DT, TB...
                
                group_name = f"DQE_EXE_{mode_code}_{sro_safe}_{current_date}"
                self.layer_group = LayerManager.create_layer_group(group_name)
                
                # Stockage resultats SQL pour validation
                self.dqe_results = results
                self.current_type = p_type
                self.current_mode_code = mode_code
                print(f"DEBUG: {len(results)} resultats SQL stockes pour validation (mode {mode_code})")
                
                created_layers = self._load_organized_layers(results, sro, self.type_combo.currentData())
                QApplication.processEvents()
                if self.type_combo.currentData() == 'D':
                    print("\n=== CHARGEMENT CÂBLES DÉCOUPÉS (Distribution) ===")
                    self.smooth_progress_to(95, "Chargement câbles découpés...")
                    QApplication.processEvents()
                    
                    dist_layers = LayerManager.load_distribution_cables(
                        sro, self.layer_group, self.layers_loaded
                    )
                    created_layers.extend(dist_layers)
                    print(f"=== CÂBLES DÉCOUPÉS AJOUTÉS: {len(dist_layers)} ===")
                self.smooth_progress_to(98, "Génération du rapport Excel...")
                QApplication.processEvents()
                # Nom fichier avec mode: EXE_TE, EXE_DT, EXE_TB...
                excel_type = f"EXE_{mode_code}"
                ExcelManager.create_excel_report(results, sro, excel_type)
                self.smooth_progress_to(100, "Finalisation...")
                QApplication.processEvents()
                
                final_message = f"DQE EXE terminé: {len(created_layers)} couches créées"
                self.progress_widget.complete_operation(True, final_message)
                
                if iface:
                    iface.messageBar().pushMessage(
                        "DQE EXE", final_message,
                        level=Qgis.Success, duration=5
                    )
            else:
                self.progress_widget.complete_operation(False, message)
                QMessageBox.critical(self, "Erreur", message)
                
        except Exception as e:
            error_msg = f"Erreur post-traitement DQE EXE: {str(e)}"
            print(f"ERREUR: {error_msg}")
            import traceback
            print(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
            QMessageBox.critical(self, "Erreur", error_msg)
        finally:
            if hasattr(self, 'progress_timer'):
                self.progress_timer.stop()
                self.progress_timer.deleteLater()
            self.execute_button.setEnabled(True)
            if hasattr(self, 'thread'):
                self.thread.quit()
                self.thread.wait()
    
    def smooth_progress_to(self, target_value, status):
        """Fait évoluer la progression en douceur vers une valeur cible"""
        if hasattr(self, 'current_progress'):
            steps = max(1, int((target_value - self.current_progress) / 2))
            for i in range(steps):
                remaining = steps - i
                if remaining > 0 and self.current_progress < target_value:
                    self.current_progress += (target_value - self.current_progress) / remaining
                    self.progress_widget.update_progress(int(self.current_progress), status)
                    QApplication.processEvents()
                    time.sleep(0.05)
            self.current_progress = target_value
            self.progress_widget.update_progress(int(self.current_progress), status)
    
    def _load_organized_layers(self, results, sro, p_type):
        """Chargement organisé par catégories - VERSION EXE"""
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
            "Poteaux": [],  # Nouvelle catégorie pour les poteaux
            "Travaux Génie civil": [],
            "SRO": [],
            "Autres": []
        }
        
        print(f"\n=== DÉBUT TRAITEMENT DQE EXE - {len(results)} résultats ===")
        
        for i, result in enumerate(results):
            designation = result.get("designation") or result.get("Désignation") or result.get("désignation") or ""
            
            if not designation:
                print(f"[{i+1}] IGNORÉ - Pas de désignation")
                continue
            
            ids = result.get("ids") or result.get("Ids") or ""
            quantite = result.get("quantite") or result.get("Quantité") or result.get("quantité") or 0
            unite = result.get("unite") or result.get("Unité") or result.get("unité") or ""
            
            print(f"\n[{i+1}] Traitement: {designation}")
            print(f"    Quantité: {quantite}, Unité: {unite}")
            print(f"    IDs: {str(ids)[:100]}{'...' if len(str(ids)) > 100 else ''}")
            
            if not ids or len(str(ids).strip()) == 0:
                print(f"  IGNORÉ - Pas d'IDs (en-tête ou section)")
                continue
            
            try:
                quantite_num = float(quantite) if quantite is not None else 0
                if quantite_num <= 0:
                    print(f"  IGNORÉ - Quantité nulle ou négative ({quantite_num})")
                    continue
            except (ValueError, TypeError):
                print(f"  IGNORÉ - Quantité invalide: {quantite}")
                continue
            
            main_category = None
            designation_lower = designation.lower()
            if any(x in designation_lower for x in ["pose poteau", "poteau rauv", "ft à"]):
                main_category = "Poteaux"
                print(f"    Détecté comme Poteau: {designation}")
            elif any(x in designation_lower for x in ["tranchée", "micro tranchée", "forage dirigé", "encorbellement", "pose de chambre", "pvc ", "pehd"]):
                main_category = "Travaux Génie civil"
            elif any(x in designation_lower for x in ["prise", "dtr", "rad", "nbre de prises"]):
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
                        print(f"  IGNORÉ - Câble remplacé par câbles découpés")
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
                print(f"Catégorie par défaut: Autres")
            
            if not main_category:
                print(f"IGNORÉ - Aucune catégorie déterminée")
                continue
            
            table_name = LayerManager.get_table_from_designation(designation)
            print(f"Table déterminée: {table_name}")
            
            task_data = {
                'layer_name': designation,
                'ids_str': str(ids),
                'table_name': table_name,
                'layer_id': str(uuid.uuid4()),
                'priority': LayerManager.get_custom_layer_order(designation),
                'sro': sro
            }
            
            categories[main_category].append(task_data)
            print(f"Assigné à la catégorie: {main_category}")
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
                        
                        print(f"COUCHE CRÉÉE - {layer.featureCount()} entités")
                        if iface:
                            iface.mainWindow().statusBar().showMessage(f"Chargé {len(created_layers)} couches")
                    else:
                        print(f"ÉCHEC CRÉATION COUCHE")
                        
                except Exception as e:
                    print(f"Erreur lors du chargement de {task_data['layer_name']}: {str(e)}")
        
        print(f"\n=== COUCHES STANDARD CRÉÉES: {len(created_layers)} ===")
        return created_layers
    
    def validate_dqe_exe(self):
        """Valide et sauvegarde le DQE EXE dans la base de données
        Structure simplifiée: 1 ligne avec categorie='dqe_result' et tout le DQE en JSON
        """
        try:
            sro = self.sro_input.currentText().strip()
            if not sro:
                QMessageBox.warning(self, "Validation DQE", "Veuillez sélectionner un SRO")
                return
            
            if not self.dqe_results:
                QMessageBox.warning(self, "Validation DQE", 
                    "Aucun résultat DQE trouvé.\nVeuillez d'abord exécuter le DQE EXE.")
                return
            
            # Code projet avec mode blocage: TE/DE (standard), TT/DT (travaux), TB/DB (blocage)
            type_data = self.type_combo.currentData()  # T ou D
            blocage = getattr(self, 'current_blocage', 'E')  # E/T/B
            projet_code = f"{type_data}{blocage}"  # Ex: TE, DT, TB...
            user_name = _db_manager._config.user if _db_manager and _db_manager._config else "unknown"
            
            # Construire le tableau JSON - TOUTES les lignes dans l'ordre exact
            dqe_data = []
            for result in self.dqe_results:
                designation = result.get("Désignation") or result.get("designation") or ""
                quantite = result.get("Quantité") or result.get("quantite")
                unite = result.get("Unité") or result.get("unite") or ""
                ids = result.get("ids") or result.get("Ids") or ""
                
                try:
                    quantite_num = float(quantite) if quantite is not None else 0
                except (ValueError, TypeError):
                    quantite_num = 0
                
                # Garder TOUTES les lignes (même quantité 0) pour reconstitution exacte
                dqe_data.append({
                    'designation': designation,
                    'quantite': quantite_num,
                    'unite': unite,
                    'ids': str(ids) if ids else None
                })
            
            if not dqe_data:
                QMessageBox.warning(self, "Validation DQE", "Aucune donnée DQE")
                return
            
            print(f"Validation DQE EXE: {len(dqe_data)} lignes à enregistrer")
            
            # Une seule insertion avec tout le DQE
            with _db_manager.get_cursor() as cursor:
                query = """
                    INSERT INTO dqe.dqejson 
                    (sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (
                    sro,
                    f"DQE_EXE_{sro}",
                    projet_code,
                    'dqe_result',  # Catégorie unique
                    json.dumps(dqe_data),  # Tableau JSON complet
                    user_name,
                    None  # Version auto-assignée par trigger
                ))
            
            print(f"Validation: 1 ligne dqe_result avec {len(dqe_data)} elements")
            
            # Sauvegarde de TOUTES les couches avec géométries
            layers_count = 0
            if self.layer_group:
                layers_count = self._save_all_layers(sro, projet_code, user_name)
            
            total_saved = len(dqe_data) + layers_count
            print(f"Validation terminee: {len(dqe_data)} resultats SQL + {layers_count} couches")
            
            QMessageBox.information(
                self, 
                "Validation DQE EXE", 
                f"Validation terminee!\n\n"
                f"- SRO: {sro}\n"
                f"- Type: {projet_code}\n"
                f"- Resultats DQE: {len(dqe_data)}\n"
                f"- Couches archivees: {layers_count}\n"
                f"- Total: {total_saved} elements"
            )
            
        except Exception as e:
            print(f"Erreur validation: {str(e)}")
            import traceback
            print(traceback.format_exc())
            if _logger:
                _logger.error("Erreur validation DQE EXE", exception=e)
            QMessageBox.critical(self, "Erreur", f"Erreur validation DQE EXE: {str(e)}")
    
    def _save_all_layers(self, sro, projet_code, user_name):
        """Sauvegarde TOUTES les couches du groupe dans dqejson
        Chaque couche est stockee comme FeatureCollection avec geometries
        """
        layers_count = 0
        try:
            def collect_all_layers(group):
                """Recherche recursive de toutes les couches"""
                layers = []
                for child in group.children():
                    if hasattr(child, 'layer'):
                        layer = child.layer()
                        if layer and layer.isValid():
                            layers.append(layer)
                    elif hasattr(child, 'children'):
                        layers.extend(collect_all_layers(child))
                return layers
            
            all_layers = collect_all_layers(self.layer_group)
            print(f"Couches a archiver: {len(all_layers)}")
            
            for layer in all_layers:
                try:
                    layer_data = self._extract_layer_data(layer)
                    if layer_data['features']:
                        with _db_manager.get_cursor() as cursor:
                            query = """
                                INSERT INTO dqe.dqejson 
                                (sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """
                            cursor.execute(query, (
                                sro,
                                f"DQE_EXE_{sro}",
                                projet_code,
                                layer.name(),
                                json.dumps(layer_data),
                                user_name,
                                None  # Version auto-assignée par trigger
                            ))
                        layers_count += 1
                        print(f"  Couche archivee: {layer.name()} ({len(layer_data['features'])} features)")
                except Exception as e:
                    print(f"  Erreur archivage {layer.name()}: {str(e)}")
                    
        except Exception as e:
            print(f"Erreur archivage couches: {str(e)}")
        
        return layers_count

    def _extract_layer_data(self, layer):
        """Extrait les donnees d'une couche QGIS pour sauvegarde JSON"""
        features_data = []
        
        try:
            if not layer or not layer.isValid():
                return {'type': 'FeatureCollection', 'features': [], 'crs': None}
            
            for feature in layer.getFeatures():
                feature_dict = {
                    'geometry': feature.geometry().asWkt() if feature.geometry() else None,
                    'attributes': {}
                }
                for field in layer.fields():
                    field_name = field.name()
                    value = feature[field_name]
                    if isinstance(value, (int, float, str, bool)) or value is None:
                        feature_dict['attributes'][field_name] = value
                    else:
                        feature_dict['attributes'][field_name] = str(value)
                
                features_data.append(feature_dict)
            
            crs_authid = layer.crs().authid() if layer.crs() and layer.crs().isValid() else None
            return {
                'type': 'FeatureCollection',
                'features': features_data,
                'crs': crs_authid
            }
        except Exception as e:
            print(f"Erreur extraction donnees couche: {str(e)}")
            return {'type': 'FeatureCollection', 'features': [], 'crs': None}
