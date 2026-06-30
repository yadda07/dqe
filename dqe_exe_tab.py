"""
DQE EXE Tab Module

Handles the DQE EXE tab interface and functionality for the QGIS plugin.
Extracted from the main dialog file for better modularity.
"""

import json
import time
import uuid

from .compat import (
    QTimer, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QPushButton, QComboBox, QMessageBox, QApplication, QGIS_SUCCESS
)
from .base_tab import BaseDQETab
from qgis.utils import iface
from .ui_components import SROComboBox, ProgressWidget
from .layer_manager import LayerManager
from .database_operations import DatabaseOperations
from .excel_manager import ExcelManager
from .dqe_utils import _db_manager, _logger, _validator
from .designation_classifier import DesignationClassifier
from .workers import DQEWorker, DistCablesWorker
from .compat import QThread
from .telemetry import send_telemetry


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
        """Validation format uniquement sur frappe (pas de DB)."""
        if sro != self.sro_input.lineEdit().text().strip():
            return
        
        if _validator:
            if _validator._validate_sro_format(sro):
                self.execute_button.setEnabled(True)
    
    def execute_dqe_exe(self):
        """Exécution DQE EXE avec interface uniforme"""
        sro = self.sro_input.lineEdit().text().strip()
        p_type = self.type_combo.currentData()
        blocage = self.blocage_combo.currentData()  # E/T/B
        
        if not sro:
            QMessageBox.warning(self, "Erreur", "Veuillez saisir un SRO")
            return
        
        if _validator:
            is_valid, message = _validator.validate_sro_exists(sro)
            if not is_valid:
                QMessageBox.warning(self, "SRO invalide", f"Le SRO saisi n'est pas valide:\n{message}")
                return
        
        self.execute_button.setVisible(False)
        self.validate_button.setVisible(False)
        self.current_blocage = blocage  # Stocker pour nommage Excel
        self._exec_start = time.monotonic()
        
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
                    self._cleanup_orphan_layers()
                    self.progress_widget.complete_operation(False, "Opération annulée")
                    send_telemetry(
                        action="execution", mode="EXE",
                        sro=sro, type=self.type_combo.currentData(),
                        blocage=getattr(self, 'current_blocage', 'E'),
                        mode_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                        projet_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                        verdict="cancelled", cancelled=True,
                        elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
                    )
                    return
                
                # Stocker pour la phase finale
                self._pending_created_layers = created_layers
                self._pending_results = results
                self._pending_sro = sro
                self._pending_mode_code = mode_code
                
                QApplication.processEvents()
                if self.type_combo.currentData() == 'D' and not self._is_cancelled:
                    if _logger:
                        _logger.info("Lancement worker async cables decoupes (Distribution)")
                    self._start_dist_cables_worker(sro)
                    return  # La suite se fait dans _on_dist_cables_finished
                
                self._finalize_dqe_exe()
            else:
                self.progress_widget.complete_operation(False, message)
                QMessageBox.critical(self, "Erreur", message)
                send_telemetry(
                    action="execution", mode="EXE",
                    sro=self.sro_input.lineEdit().text().strip(),
                    type=self.type_combo.currentData(),
                    blocage=getattr(self, 'current_blocage', 'E'),
                    mode_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                    projet_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                    verdict="failure", error_msg=message,
                    elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
                )
                
        except Exception as e:
            error_msg = f"Erreur post-traitement DQE EXE: {str(e)}"
            import traceback
            if _logger:
                _logger.error(error_msg)
                _logger.error(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
            QMessageBox.critical(self, "Erreur", error_msg)
            send_telemetry(
                action="execution", mode="EXE",
                sro=self.sro_input.lineEdit().text().strip(),
                type=self.type_combo.currentData(),
                blocage=getattr(self, 'current_blocage', 'E'),
                mode_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                projet_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                verdict="failure", error_msg=error_msg,
                elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
            )
        finally:
            self._cleanup_thread()
            self.execute_button.setVisible(True)
            self.validate_button.setVisible(True)
            self.execute_button.setEnabled(True)
    
    def _start_dist_cables_worker(self, sro):
        """Lance le worker async pour la phase DB des cables decoupes."""
        self._dist_worker = DistCablesWorker(sro)
        self._dist_thread = QThread()
        self._dist_worker.moveToThread(self._dist_thread)
        self._dist_worker.finished.connect(self._on_dist_cables_finished)
        self.progress_widget.progress_cancelled.connect(self._dist_worker.cancel)
        self._dist_thread.started.connect(self._dist_worker.run)
        self._dist_thread.finished.connect(self._dist_thread.deleteLater)
        self._dist_thread.start()
    
    def _on_dist_cables_finished(self, success, db_result, message):
        """Callback apres phase DB async des cables decoupes."""
        try:
            if self._dist_worker:
                try:
                    self._dist_worker.deleteLater()
                except RuntimeError:
                    pass
                self._dist_worker = None
            if self._dist_thread:
                try:
                    self._dist_thread.quit()
                    self._dist_thread.wait(5000)
                except RuntimeError:
                    pass
                self._dist_thread = None
            
            if self._is_cancelled:
                self._cleanup_orphan_layers()
                self.progress_widget.complete_operation(False, "Operation annulee")
                send_telemetry(
                    action="execution", mode="EXE",
                    sro=self.sro_input.lineEdit().text().strip(),
                    type=self.type_combo.currentData(),
                    blocage=getattr(self, 'current_blocage', 'E'),
                    mode_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                    projet_code=f"{self.type_combo.currentData()}{getattr(self, 'current_blocage', 'E')}",
                    verdict="cancelled", cancelled=True,
                    elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
                )
                self._cleanup_thread()
                self.execute_button.setEnabled(True)
                return
            
            if success and db_result:
                self.smooth_progress_to(95, "Creation couches cables decoupes...")
                QApplication.processEvents()
                dist_layers = LayerManager.create_distribution_layers(
                    db_result, self.layer_group, self.layers_loaded,
                    cancel_check=lambda: self._is_cancelled
                )
                if self._is_cancelled:
                    self._cleanup_orphan_layers()
                    self.progress_widget.complete_operation(False, "Operation annulee")
                    self._cleanup_thread()
                    self.execute_button.setEnabled(True)
                    return
                self._pending_created_layers.extend(dist_layers)
                if _logger:
                    _logger.info(f"Cables decoupes: {len(dist_layers)} couches creees")
            elif not success and message:
                if _logger:
                    _logger.warning(f"Cables decoupes: {message}")
            
            self._finalize_dqe_exe()
            
        except Exception as e:
            error_msg = f"Erreur cables decoupes: {e}"
            if _logger:
                import traceback
                _logger.error(error_msg)
                _logger.error(traceback.format_exc())
            self.progress_widget.complete_operation(False, error_msg)
            self._cleanup_thread()
            self.execute_button.setEnabled(True)
    
    def _finalize_dqe_exe(self):
        """Phase finale commune : Excel, collapse, message."""
        try:
            if self._is_cancelled:
                self._cleanup_orphan_layers()
                self.progress_widget.complete_operation(False, "Operation annulee")
                send_telemetry(
                    action="execution", mode="EXE",
                    sro=self._pending_sro if hasattr(self, '_pending_sro') else "",
                    type=self.type_combo.currentData() if hasattr(self, 'type_combo') else "",
                    blocage=getattr(self, 'current_blocage', 'E'),
                    mode_code=getattr(self, '_pending_mode_code', ''),
                    projet_code=getattr(self, '_pending_mode_code', ''),
                    verdict="cancelled", cancelled=True,
                    elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
                )
                return
            
            sro = self._pending_sro
            results = self._pending_results
            created_layers = self._pending_created_layers
            mode_code = self._pending_mode_code
            
            self.smooth_progress_to(98, "Generation du rapport Excel...")
            QApplication.processEvents()
            excel_type = f"EXE_{mode_code}"
            ExcelManager.create_excel_report(results, sro, excel_type)
            self.smooth_progress_to(100, "Finalisation...")
            QApplication.processEvents()
            
            if self.layer_group:
                LayerManager.collapse_group_recursive(self.layer_group)
            
            final_message = f"DQE EXE termine: {len(created_layers)} couches creees"
            self.progress_widget.complete_operation(True, final_message)
            send_telemetry(
                action="execution", mode="EXE",
                sro=sro, type=self.type_combo.currentData(),
                blocage=getattr(self, 'current_blocage', 'E'),
                mode_code=mode_code, projet_code=mode_code,
                verdict="success",
                n_results=len(results) if results else 0,
                n_layers=len(created_layers) if created_layers else 0,
                excel_generated=True,
                elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
            )
            
            if iface:
                iface.messageBar().pushMessage(
                    "DQE EXE", final_message,
                    level=QGIS_SUCCESS, duration=5
                )
        except Exception as e:
            error_msg = f"Erreur finalisation DQE EXE: {e}"
            if _logger:
                _logger.error(error_msg)
            self.progress_widget.complete_operation(False, error_msg)
            send_telemetry(
                action="execution", mode="EXE",
                sro=self._pending_sro if hasattr(self, '_pending_sro') else "",
                type=self.type_combo.currentData() if hasattr(self, 'type_combo') else "",
                blocage=getattr(self, 'current_blocage', 'E'),
                mode_code=getattr(self, '_pending_mode_code', ''),
                projet_code=getattr(self, '_pending_mode_code', ''),
                verdict="failure", error_msg=error_msg,
                elapsed_ms=int((time.monotonic() - getattr(self, '_exec_start', time.monotonic())) * 1000),
            )
        finally:
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
        validate_start = time.monotonic()
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
            send_telemetry(
                action="validation", mode="EXE",
                sro=sro, type=type_data, blocage=blocage,
                mode_code=projet_code, projet_code=projet_code,
                verdict="success",
                n_dqe_data=len(dqe_data), n_layers_saved=layers_count,
                elapsed_ms=int((time.monotonic() - validate_start) * 1000),
            )
            
        except Exception as e:
            import traceback
            if _logger:
                _logger.error(f"Erreur validation: {str(e)}")
                _logger.error(traceback.format_exc())
            if _logger:
                _logger.error("Erreur validation DQE EXE", exception=e)
            QMessageBox.critical(self, "Erreur", f"Erreur validation DQE EXE: {str(e)}")
            send_telemetry(
                action="validation", mode="EXE",
                sro=self.sro_input.currentText().strip(),
                type=self.type_combo.currentData() if hasattr(self, 'type_combo') else "",
                blocage=getattr(self, 'current_blocage', 'E'),
                projet_code=f"{self.type_combo.currentData() if hasattr(self, 'type_combo') else 'T'}{getattr(self, 'current_blocage', 'E')}",
                verdict="failure", error_msg=str(e),
                elapsed_ms=int((time.monotonic() - validate_start) * 1000),
            )
    
    def _save_all_layers(self, sro, projet_code, user_name):
        """Sauvegarde TOUTES les couches du groupe dans dqejson"""
        return LayerManager.save_layers_to_db(
            self.layer_group, sro, f"DQE_EXE_{sro}",
            projet_code, user_name, _db_manager
        )
