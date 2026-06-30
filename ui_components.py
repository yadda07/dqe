"""
DQE UI Components
======================================================
Composants d'interface utilisateur pour le plugin DQE Chargeur
"""

from typing import List
from .compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QProgressBar, QCompleter, Qt, QTimer, pyqtSignal, QStringListModel,
    QColor, QApplication, QThread, QObject,
    QT_CASE_INSENSITIVE, QT_MATCH_CONTAINS, COMPLETER_POPUP
)

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


class _SROListWorker(QObject):
    """Worker pour chargement async de la liste SRO hors main thread."""
    finished = pyqtSignal(list, bool)
    error = pyqtSignal(str)

    def run(self):
        try:
            if _db_manager and _db_manager.is_connected:
                query = "SELECT sro FROM rip_avg_nge.za_sro ORDER BY sro LIMIT 1000"
                results = _db_manager.execute_query(query)
                sro_list = [row[0] for row in results if row[0] and str(row[0]).strip()]
                truncated = len(results) >= 1000
                self.finished.emit(sro_list, truncated)
            else:
                self.finished.emit([], False)
        except Exception as e:
            self.error.emit(str(e))


class _SROListLoader(QObject):
    """Singleton partagé: charge la liste SRO une seule fois pour toutes les SROComboBox.

    Évite l'épuisement du pool de connexions quand plusieurs onglets (PRO, EXE, PGC)
    créent chacun une SROComboBox simultanément. Une seule requête, un seul thread,
    un seul connexion - le résultat est diffusé à tous les abonnés.
    """
    _instance = None

    def __init__(self):
        super().__init__()
        self._thread = None
        self._worker = None
        self._sro_list = []
        self._truncated = False
        self._loaded = False
        self._loading = False
        self._subscribers = []

    @classmethod
    def instance(cls) -> '_SROListLoader':
        if cls._instance is None:
            cls._instance = _SROListLoader()
        return cls._instance

    def subscribe(self, on_loaded, on_error):
        """Abonne un callback. Sert le cache si déjà chargé, déclenche le chargement sinon."""
        self._subscribers.append((on_loaded, on_error))
        if self._loaded:
            on_loaded(self._sro_list, self._truncated)
        elif not self._loading:
            self._start_loading()

    def unsubscribe(self, on_loaded, on_error):
        """Désabonne un callback (appelé à la destruction du widget)."""
        try:
            self._subscribers.remove((on_loaded, on_error))
        except ValueError:
            pass

    def _start_loading(self):
        self._loading = True
        self._worker = _SROListWorker()
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._worker.finished.connect(self._on_loaded)
        self._worker.error.connect(self._on_error)
        self._thread.started.connect(self._worker.run)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_loaded(self, sro_list, truncated):
        self._sro_list = sro_list
        self._truncated = truncated
        self._loaded = True
        self._loading = False
        if _logger:
            _logger.info(f"Liste SRO chargée: n_items={len(sro_list)} truncated={truncated}")
        if truncated and _logger:
            _logger.warning("Liste SRO tronquée à 1000 entrées - utiliser la recherche pour les SRO au-delà")
        for on_loaded, _ in self._subscribers:
            on_loaded(sro_list, truncated)
        self._cleanup()

    def _on_error(self, error_msg):
        self._loading = False
        if _logger:
            _logger.error("Erreur chargement SRO", exception=Exception(error_msg))
        for _, on_error in self._subscribers:
            on_error(error_msg)
        self._cleanup()

    def _cleanup(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait(5000)
            self._thread = None
        if self._worker:
            self._worker.deleteLater()
            self._worker = None

    def refresh(self):
        """Force un rechargement de la liste (efface le cache)."""
        self._loaded = False
        self._sro_list = []
        self._truncated = False
        if not self._loading:
            self._start_loading()


class SROComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.sro_list = []
        self._is_destroyed = False
        self._loader = _SROListLoader.instance()
        self._loader.subscribe(self._on_sro_list_loaded, self._on_sro_list_error)

    def _on_sro_list_loaded(self, sro_list, truncated):
        """Callback appelé quand la liste SRO est chargée (main thread)."""
        if self._is_destroyed:
            return
        self.sro_list = sro_list
        self._setup_completer()

    def _on_sro_list_error(self, error_msg):
        """Callback appelé en cas d'erreur de chargement (main thread)."""
        if self._is_destroyed:
            return
        self.sro_list = []

    def closeEvent(self, event):
        """Sécurise la fermeture: marque détruit et se désabonne."""
        self._is_destroyed = True
        self._loader.unsubscribe(self._on_sro_list_loaded, self._on_sro_list_error)
        super().closeEvent(event) if hasattr(super(), 'closeEvent') else None

    def deleteLater(self):
        """Marque le widget comme détruit avant la suppression Qt."""
        self._is_destroyed = True
        self._loader.unsubscribe(self._on_sro_list_loaded, self._on_sro_list_error)
        super().deleteLater()

    def _setup_completer(self):
        """Configure le QCompleter avec la liste SRO courante."""
        model = QStringListModel(self.sro_list)
        completer = QCompleter()
        completer.setModel(model)
        completer.setCaseSensitivity(QT_CASE_INSENSITIVE)
        completer.setFilterMode(QT_MATCH_CONTAINS)
        completer.setCompletionMode(COMPLETER_POPUP)
        completer.setMaxVisibleItems(10)
        line_edit = self.lineEdit()
        line_edit.setCompleter(completer)
        line_edit.textChanged.connect(lambda text: self._show_completions(text, completer))
    
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
        self._loader.refresh()
    
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
                LIMIT 500
            """
            results = _db_manager.execute_query(query, (self.current_sro,))
            troncons = [row[0] for row in results if row[0] and row[0].strip()]
            
            if len(results) >= 500 and _logger:
                _logger.warning(f"Tronçons tronqués à 500 pour SRO={self.current_sro}")
            
            self.clear()
            self.addItems(troncons)
            
        except Exception as e:
            if _logger:
                _logger.error("Erreur chargement tronçons", exception=e)
