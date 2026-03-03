"""
DQE PRO Tab Module

Handles the DQE PRO tab interface and functionality for the QGIS plugin.
Extracted from the main dialog file for better modularity.
"""

import os
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


class DQEProTab(BaseDQETab):
    TAB_LABEL = "PRO"
    """Interface et logique pour l'onglet DQE PRO"""
    
    @staticmethod
    def filter_results_by_template(results):
        """Filtre les résultats DQE Pro pour ne garder que les lignes présentes dans le template Excel"""
        try:
            plugin_dir = os.path.dirname(__file__)
            template_path = os.path.join(plugin_dir, 'files', 'template_dqe_pro.xlsx')
            
            if not os.path.exists(template_path):
                if _logger:
                    _logger.warning(f"Template Excel non trouve: {template_path}")
                return results  # Retourner tous les résultats si pas de template
            
            # Lecture du template Excel
            try:
                import openpyxl
                wb = openpyxl.load_workbook(template_path, read_only=True)
                sheet = wb.active
                
                template_designations = set()
                for row in range(1, sheet.max_row + 1):
                    cell_value = sheet.cell(row=row, column=1).value
                    if cell_value and isinstance(cell_value, str):
                        designation = cell_value.strip()
                        if designation and designation != "Désignation":
                            template_designations.add(designation)
                
                wb.close()
                if _logger:
                    _logger.debug(f"Template Excel charge: {len(template_designations)} designations")
                
            except ImportError:
                if _logger:
                    _logger.warning("openpyxl non disponible, pas de filtrage")
                return results
            
            filtered_results = []
            excluded_count = 0
            
            for result in results:
                designation = result.get("designation") or result.get("Désignation") or result.get("désignation") or ""
                
                if designation in template_designations:
                    filtered_results.append(result)
                else:
                    excluded_count += 1
                    pass
            
            if _logger:
                _logger.info(f"Filtrage termine: {len(filtered_results)} conservees, {excluded_count} exclues")
            return filtered_results
            
        except Exception as e:
            if _logger:
                _logger.error(f"Erreur lors du filtrage: {str(e)}")
            return results  # En cas d'erreur, retourner tous les résultats

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dqe_results = []
        self.current_sro = None
        self.current_type = None
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        
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
        buttons_layout.setSpacing(8)  # Espacement réduit entre boutons
        
        self.execute_button = QPushButton("Exécuter DQE PRO")
        self.execute_button.setToolTip("Génère le DQE et charge les couches QGIS")
        self.execute_button.clicked.connect(self.execute_dqe_pro)
        buttons_layout.addWidget(self.execute_button)
        
        self.validate_button = QPushButton("Valider DQE")
        self.validate_button.setToolTip("Enregistre le DQE dans la base de données")
        self.validate_button.clicked.connect(self.validate_dqe_pro)
        buttons_layout.addWidget(self.validate_button)
        
        layout.addLayout(buttons_layout)
        
        self.progress_widget = ProgressWidget()
        layout.addWidget(self.progress_widget)
        
        self.execute_button.setEnabled(False)
        self.sro_input.lineEdit().textChanged.connect(self.on_sro_changed)
    
    def on_sro_changed(self):
        """Valide le SRO de maniere asynchrone apres un delai de saisie"""
        sro = self.sro_input.lineEdit().text().strip()
        self.execute_button.setEnabled(False)
        if sro and len(sro) >= 3:
            QTimer.singleShot(1000, lambda: self.validate_sro_async(sro))
    
    def validate_sro_async(self, sro: str):
        """Verifie que le SRO existe en base avant d'activer le bouton"""
        if sro != self.sro_input.lineEdit().text().strip():
            return
        if _validator:
            is_valid, message = _validator.validate_sro_exists(sro)
            if is_valid:
                self.execute_button.setEnabled(True)
    
    def execute_dqe_pro(self):
        sro = self.sro_input.lineEdit().text().strip()
        p_type = self.type_combo.currentData()
        
        if not sro:
            QMessageBox.warning(self, "Erreur", "Veuillez saisir un SRO")
            return
        
        if _validator:
            is_valid, message = _validator.validate_sro_exists(sro)
            if not is_valid:
                QMessageBox.warning(self, "SRO invalide", f"Le SRO saisi n'est pas valide:\n{message}")
                return
        
        self.execute_button.setEnabled(False)
        
        try:
            worker = DQEWorker("PRO", sro, p_type)
            self._setup_worker_thread(worker, self.on_dqe_pro_finished)
            
        except Exception as e:
            error_msg = f"Erreur initialisation DQE PRO: {str(e)}"
            if _logger:
                _logger.error(error_msg)
            self.progress_widget.complete_operation(False, error_msg)
            self.execute_button.setEnabled(True)
            QMessageBox.critical(self, "Erreur", error_msg)
    
    def on_dqe_pro_finished(self, success: bool, results, message: str):
        """Callback appelé quand le traitement DQE PRO est terminé"""
        try:
            if hasattr(self, 'progress_timer'):
                self.post_processing = True
                
            if success and results:
                self.smooth_progress_to(92, "Création des couches...")
                QApplication.processEvents()
                current_date = time.strftime("%Y-%m-%d_%H%M%S")
                sro = self.sro_input.lineEdit().text().strip()
                sro_safe = sro.replace('/', '_')
                group_name = f"DQE_PRO_{sro_safe}_{current_date}"
                self.layer_group = LayerManager.create_layer_group(group_name)
                
                # Stockage des résultats SQL pour validation ultérieure
                self.dqe_results = results
                self.current_sro = sro
                self.current_type = self.type_combo.currentData()
                if _logger:
                    _logger.debug(f"{len(results)} resultats SQL stockes pour validation")
                
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
                ExcelManager.create_excel_report(results, sro, "PRO")
                self.smooth_progress_to(100, "Finalisation...")
                QApplication.processEvents()
                
                # Collapse tous les groupes pour une vue compacte
                if self.layer_group:
                    LayerManager.collapse_group_recursive(self.layer_group)
                
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
            import traceback
            if _logger:
                _logger.error(error_msg)
                _logger.error(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
            QMessageBox.critical(self, "Erreur", error_msg)
        finally:
            self._cleanup_thread()
            self.execute_button.setEnabled(True)
    
    def _load_organized_layers(self, results, sro, p_type):
        """Chargement organisé par catégories"""
        created_layers = []
        categories = DesignationClassifier.get_categories("PRO")
        
        if _logger:
            _logger.info(f"Debut traitement DQE PRO - {len(results)} resultats")
        
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
            
            main_category = DesignationClassifier.classify(designation, "PRO", p_type)
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
    
    def validate_dqe_pro(self):
        """Valide et sauvegarde le DQE PRO dans la base de données
        Structure simplifiée: 1 ligne avec categorie='dqe_result' et tout le DQE en JSON
        """
        try:
            sro = self.sro_input.currentText().strip()
            if not sro:
                QMessageBox.warning(self, "Validation DQE", "Veuillez sélectionner un SRO")
                return
            
            if not self.dqe_results:
                QMessageBox.warning(self, "Validation DQE", 
                    "Aucun résultat DQE trouvé.\nVeuillez d'abord exécuter le DQE PRO.")
                return
            
            type_data = self.type_combo.currentData()
            projet_code = "TP" if type_data == "T" else "DP"
            user_name = _db_manager.config.user if _db_manager and _db_manager.config else "unknown"
            
            dqe_data = self._build_dqe_data(self.dqe_results)
            
            if not dqe_data:
                QMessageBox.warning(self, "Validation DQE", "Aucune donnée DQE")
                return
            
            if _logger:
                _logger.info(f"Validation DQE PRO: {len(dqe_data)} lignes a enregistrer")
            
            # Une seule insertion avec tout le DQE
            with _db_manager.get_cursor() as cursor:
                query = """
                    INSERT INTO dqe.dqejson 
                    (sro, nom_dqe, projet, categorie, champs, user_name, version_projet) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (
                    sro,
                    f"DQE_PRO_{sro}",
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
                "Validation DQE PRO", 
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
                _logger.error("Erreur validation DQE PRO", exception=e)
            QMessageBox.critical(self, "Erreur", f"Erreur validation DQE PRO: {str(e)}")
    
    def _save_all_layers(self, sro, projet_code, user_name):
        """Sauvegarde TOUTES les couches du groupe dans dqejson"""
        return LayerManager.save_layers_to_db(
            self.layer_group, sro, f"DQE_PRO_{sro}",
            projet_code, user_name, _db_manager
        )
