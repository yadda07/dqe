"""
DQE UI Components
======================================================
Composants d'interface utilisateur pour le plugin DQE Chargeur
"""

from typing import List
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QProgressBar, QCompleter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QStringListModel
from PyQt5.QtGui import QColor

try:
    from .dqe_utils import _db_manager, _logger
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = None
    MODULES_AVAILABLE = False


class AnimatedLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.success_color = QColor(34, 139, 34)
        self.error_color = QColor(220, 20, 60)
        self.warning_color = QColor(255, 140, 0)
    
    def show_success(self, message: str, duration: int = 3000):
        self.setText(message)
        self.setStyleSheet(f"color: {self.success_color.name()}; font-weight: bold;")
        if duration > 0:
            QTimer.singleShot(duration, self.clear_message)
    
    def show_error(self, message: str, duration: int = 5000):
        self.setText(message)
        self.setStyleSheet(f"color: {self.error_color.name()}; font-weight: bold;")
        if duration > 0:
            QTimer.singleShot(duration, self.clear_message)
    
    def show_warning(self, message: str, duration: int = 4000):
        self.setText(message)
        self.setStyleSheet(f"color: {self.warning_color.name()}; font-weight: bold;")
        if duration > 0:
            QTimer.singleShot(duration, self.clear_message)
    
    def clear_message(self):
        self.setText("")
        self.setStyleSheet("")


class ProgressWidget(QWidget):
    progress_cancelled = pyqtSignal()  # Signal émis quand l'utilisateur annule
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.is_running = False
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(4)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.cancel_button.setMaximumWidth(80)
        progress_layout.addWidget(self.cancel_button)
        
        layout.addLayout(progress_layout)
        
        self.status_label = AnimatedLabel()
        layout.addWidget(self.status_label)
    
    def start_operation(self, operation_name: str):
        self.is_running = True
        self.progress_bar.setVisible(True)
        self.cancel_button.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"{operation_name} en cours...")
    
    def update_progress(self, progress: int, status: str):
        if self.is_running:
            self.progress_bar.setValue(max(0, min(100, progress)))
            self.status_label.setText(status)
    
    def complete_operation(self, success: bool, message: str):
        self.is_running = False
        self.progress_bar.setVisible(False)
        self.cancel_button.setVisible(False)
        if success:
            self.status_label.show_success(message)
        else:
            self.status_label.show_error(message)
    
    def cancel_operation(self):
        if self.is_running:
            self.progress_cancelled.emit()
            self.status_label.show_warning("Annulation en cours...")
            self.cancel_button.setEnabled(False)
    
    def smooth_progress_to(self, current_progress: float, target_value: int, status: str) -> float:
        """Fait évoluer la progression en douceur vers une valeur cible
        Retourne la nouvelle valeur de current_progress
        """
        import time
        from qgis.PyQt.QtWidgets import QApplication
        
        steps = max(1, int((target_value - current_progress) / 2))
        for i in range(steps):
            remaining = steps - i
            if remaining > 0 and current_progress < target_value:
                current_progress += (target_value - current_progress) / remaining
                self.update_progress(int(current_progress), status)
                QApplication.processEvents()
                time.sleep(0.05)
        current_progress = target_value
        self.update_progress(int(current_progress), status)
        return current_progress


class SROComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.sro_list = []
        self.load_sro_list()
        
    def load_sro_list(self):
        """Charge la liste des SRO avec autocomplétion"""
        try:
            if _db_manager and _db_manager.is_connected:
                query = "SELECT sro FROM rip_avg_nge.za_sro"
                
                print(f"Chargement SRO avec requête: {query}")
                results = _db_manager.execute_query(query)
                self.sro_list = [row[0] for row in results if row[0] and str(row[0]).strip()]
                model = QStringListModel(self.sro_list)
                completer = QCompleter()
                completer.setModel(model)
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                completer.setFilterMode(Qt.MatchContains)  # Recherche partielle
                completer.setCompletionMode(QCompleter.PopupCompletion)  # Mode popup
                completer.setMaxVisibleItems(10)  # Maximum 10 éléments visibles
                line_edit = self.lineEdit()
                line_edit.setCompleter(completer)
                line_edit.textChanged.connect(lambda text: self._show_completions(text, completer))
                
                print(f" Liste SRO chargée: {len(self.sro_list)} éléments")
                if len(self.sro_list) > 0:
                    print(f"Premiers SRO: {', '.join(self.sro_list[:5])}{'...' if len(self.sro_list) > 5 else ''}")
                
                if _logger:
                    _logger.info(f"Liste SRO chargée: {len(self.sro_list)} éléments")
                    
        except Exception as e:
            error_msg = f"Erreur chargement liste SRO: {str(e)}"
            print(f" {error_msg}")
            
            if _logger:
                _logger.error("Erreur chargement SRO", exception=e)
            self.sro_list = []
    
    def _show_completions(self, text: str, completer: QCompleter):
        """Force l'affichage des suggestions quand on tape"""
        if len(text) >= 1:  # Afficher dès 1 caractère
            matching_sros = [sro for sro in self.sro_list if text.upper() in sro.upper()]
            
            if matching_sros:
                print(f" Recherche '{text}': {len(matching_sros)} SRO trouvés")
                print(f"Exemples: {', '.join(matching_sros[:3])}{'...' if len(matching_sros) > 3 else ''}")
                new_model = QStringListModel(matching_sros)
                completer.setModel(new_model)
                if not completer.popup().isVisible():
                    completer.complete()
            else:
                print(f" Aucun SRO trouvé pour '{text}'")
    
    def refresh_sro_list(self):
        """Méthode pour rafraîchir la liste SRO à la demande"""
        print(" Rafraîchissement de la liste SRO...")
        self.load_sro_list()
    
    def get_sro_count(self) -> int:
        """Retourne le nombre de SRO chargés"""
        return len(self.sro_list)
    
    def search_sro(self, pattern: str) -> List[str]:
        """Recherche les SRO contenant le pattern"""
        if not pattern:
            return self.sro_list
        
        pattern_lower = pattern.lower()
        matching_sros = [sro for sro in self.sro_list if pattern_lower in sro.lower()]
        return matching_sros


class TronconComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.current_sro = ""
    
    def set_sro(self, sro: str):
        self.current_sro = sro
        self.clear()
        if sro:
            self.load_items()
    
    def load_items(self):
        if not self.current_sro or not _db_manager:
            return
        
        try:
            query = """
                SELECT DISTINCT gc 
                FROM gc_exe.t_cheminement 
                WHERE sro = %s AND gc IS NOT NULL AND gc != ''
                ORDER BY gc
            """
            results = _db_manager.execute_query(query, (self.current_sro,))
            troncons = [row[0] for row in results if row[0] and row[0].strip()]
            
            self.clear()
            self.addItems(troncons)
            
        except Exception as e:
            if _logger:
                _logger.error("Erreur chargement tronçons", exception=e)
