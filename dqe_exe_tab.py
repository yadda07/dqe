"""
DQE EXE Tab Module

Handles the DQE EXE tab interface and functionality for the QGIS plugin.
Extracted from the main dialog file for better modularity.
"""

import json
import time
import uuid

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QPushButton, QComboBox, QMessageBox, QApplication
)
from .base_tab import BaseDQETab
from qgis.core import Qgis
from qgis.utils import iface
from .ui_components import SROComboBox, ProgressWidget
from .layer_manager import LayerManager
from .database_operations import DatabaseOperations
from .excel_manager import ExcelManager
from .dqe_utils import _db_manager, _logger, _validator
from .designation_classifier import DesignationClassifier
from .workers import DQEWorker


class DQEExeTab(BaseDQETab):
    """Interface et logique pour l'onglet DQE EXE"""
    TAB_LABEL = "EXE"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dqe_results = None
        self.current_type = None
        self.current_blocage = 'E'
        self.current_mode_code = None
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
        self.execute_button.setVisible(False)
        self.validate_button.setVisible(False)
        self.current_blocage = blocage  # Stocker pour nommage Excel
        
        try:
            mode_label = self.blocage_combo.currentText()
            worker = DQEWorker("EXE", sro, p_type, blocage=blocage)
            self._setup_worker_thread(worker, self.on_dqe_exe_finished, f"DQE EXE ({mode_label})")
            
        except Exception as e:
            error_msg = f"Erreur initialisation DQE EXE: {str(e)}"
            if _logger:
                _logger.error(error_msg)
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
                if _logger:
                    _logger.debug(f"{len(results)} resultats SQL stockes pour validation (mode {mode_code})")
                
                created_layers = self._load_organized_layers(results, sro, self.type_combo.currentData())
                
                if self._is_cancelled:
                    self.progress_widget.complete_operation(False, "Opération annulée")
                    return
                
                QApplication.processEvents()
                if self.type_combo.currentData() == 'D' and not self._is_cancelled:
                    if _logger:
                        _logger.info("Chargement cables decoupes (Distribution)")
                    self.smooth_progress_to(95, "Chargement câbles découpés...")
                    QApplication.processEvents()
                    
                    dist_layers = LayerManager.load_distribution_cables(
                        sro, self.layer_group, self.layers_loaded
                    )
                    created_layers.extend(dist_layers)
                    if _logger:
                        _logger.info(f"Cables decoupes ajoutes: {len(dist_layers)}")
                
                if self._is_cancelled:
                    self.progress_widget.complete_operation(False, "Opération annulée")
                    return
                
                self.smooth_progress_to(98, "Génération du rapport Excel...")
                QApplication.processEvents()
                # Nom fichier avec mode: EXE_TE, EXE_DT, EXE_TB...
                excel_type = f"EXE_{mode_code}"
                ExcelManager.create_excel_report(results, sro, excel_type)
                self.smooth_progress_to(100, "Finalisation...")
                QApplication.processEvents()
                
                # Collapse tous les groupes pour une vue compacte
                if self.layer_group:
                    LayerManager.collapse_group_recursive(self.layer_group)
                
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
            import traceback
            if _logger:
                _logger.error(error_msg)
                _logger.error(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
            QMessageBox.critical(self, "Erreur", error_msg)
        finally:
            self._cleanup_thread()
            self.execute_button.setVisible(True)
            self.validate_button.setVisible(True)
            self.execute_button.setEnabled(True)
    
    def _load_organized_layers(self, results, sro, p_type):
        """Chargement organisé par catégories - VERSION EXE"""
        created_layers = []
        categories = DesignationClassifier.get_categories("EXE")
        
        if _logger:
            _logger.info(f"Debut traitement DQE EXE - {len(results)} resultats")
        
        for i, result in enumerate(results):
            designation = result.get("designation") or result.get("Désignation") or result.get("désignation") or ""
            if not designation:
                continue
            
            ids = result.get("ids") or result.get("Ids") or ""
            quantite = result.get("quantite") or result.get("Quantité") or result.get("quantité") or 0
            
            if not ids or len(str(ids).strip()) == 0:
                continue
            
            try:
                quantite_num = float(quantite) if quantite is not None else 0
                if quantite_num <= 0:
                    continue
            except (ValueError, TypeError):
                continue
            
            main_category = DesignationClassifier.classify(designation, "EXE", p_type)
            if main_category is None:
                if _logger:
                    _logger.debug(f"Ignore - cable remplace par cables decoupes: {designation}")
                continue
            
            table_name = LayerManager.get_table_from_designation(designation)
            task_data = {
                'layer_name': designation,
                'ids_str': str(ids),
                'table_name': table_name,
                'layer_id': str(uuid.uuid4()),
                'priority': LayerManager.get_custom_layer_order(designation),
                'sro': sro
            }
            categories[main_category].append(task_data)
            if _logger:
                _logger.debug(f"[{i+1}] {designation} -> {main_category}")

        created_layers = self._load_categories_to_layers(categories, sro)
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
            user_name = _db_manager.config.user if _db_manager and _db_manager.config else "unknown"
            
            dqe_data = self._build_dqe_data(self.dqe_results)
            
            if not dqe_data:
                QMessageBox.warning(self, "Validation DQE", "Aucune donnée DQE")
                return
            
            if _logger:
                _logger.info(f"Validation DQE EXE: {len(dqe_data)} lignes a enregistrer")
            
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
            
            if _logger:
                _logger.info(f"Validation: 1 ligne dqe_result avec {len(dqe_data)} elements")
            
            # Sauvegarde de TOUTES les couches avec géométries
            layers_count = 0
            if self.layer_group:
                layers_count = self._save_all_layers(sro, projet_code, user_name)
            
            total_saved = len(dqe_data) + layers_count
            if _logger:
                _logger.info(f"Validation terminee: {len(dqe_data)} resultats SQL + {layers_count} couches")
            
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
            import traceback
            if _logger:
                _logger.error(f"Erreur validation: {str(e)}")
                _logger.error(traceback.format_exc())
            if _logger:
                _logger.error("Erreur validation DQE EXE", exception=e)
            QMessageBox.critical(self, "Erreur", f"Erreur validation DQE EXE: {str(e)}")
    
    def _save_all_layers(self, sro, projet_code, user_name):
        """Sauvegarde TOUTES les couches du groupe dans dqejson"""
        return LayerManager.save_layers_to_db(
            self.layer_group, sro, f"DQE_EXE_{sro}",
            projet_code, user_name, _db_manager
        )
