"""
DQE Workers
===========
Unified background workers for DQE PRO, EXE, and PGC operations.
"""

from qgis.PyQt.QtCore import QObject
from PyQt5.QtCore import pyqtSignal
from .database_operations import DatabaseOperations
from .dqe_utils import _logger


class DQEWorker(QObject):
    """Background worker for all DQE operations (PRO, EXE, PGC)."""
    progress_updated = pyqtSignal(int, str)
    finished = pyqtSignal(bool, object, str)

    def __init__(self, operation_type, sro, p_type=None, troncon=None, blocage=None):
        super().__init__()
        self.operation_type = operation_type
        self.sro = sro
        self.p_type = p_type
        self.troncon = troncon
        self.blocage = blocage
        self.is_cancelled = False
        self.results = None
        self.error_message = None
        self.is_running = False
        self.progress_value = 0

    def cancel(self):
        """Request cooperative cancellation."""
        self.is_cancelled = True
        if _logger:
            _logger.info(f"Annulation demandee pour DQE {self.operation_type}")

    def run(self):
        """Execute the DQE operation in the worker thread."""
        self.is_running = True
        self.progress_value = 15
        try:
            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annule")
                return
            self.progress_value = 25

            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annule")
                return
            self.progress_value = 40

            self.results = self._execute_operation()

            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annule")
                return
            self.progress_value = 85

            if self.is_cancelled:
                self.finished.emit(False, None, "Traitement annule")
                return
            self.progress_value = 90

            count = len(self.results) if self.results else 0
            msg = f"DQE {self.operation_type} termine - {count} resultats"
            if _logger:
                _logger.info(msg)
            self.finished.emit(True, self.results, msg)

        except Exception as e:
            self.error_message = f"Erreur DQE {self.operation_type}: {str(e)}"
            import traceback
            if _logger:
                _logger.error(self.error_message)
                _logger.error(traceback.format_exc())
            self.finished.emit(False, None, self.error_message)
        finally:
            self.is_running = False

    def _execute_operation(self):
        """Dispatch to the correct DatabaseOperations method."""
        if self.operation_type == "PRO":
            return DatabaseOperations.execute_dqe_pro(self.sro, self.p_type)
        elif self.operation_type == "EXE":
            return DatabaseOperations.execute_dqe_exe(self.sro, self.p_type, self.blocage)
        elif self.operation_type == "PGC":
            return DatabaseOperations.execute_dqe_pgc(self.sro, self.troncon)
        return []
