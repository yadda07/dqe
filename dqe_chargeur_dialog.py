"""
DQE Chargeur Dialog
======================================================

"""

import os
import time
import json
import uuid
import tempfile
import shutil
import psycopg2
from psycopg2.extras import DictCursor
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QMessageBox, QLineEdit, QTabWidget, QProgressBar, QTextEdit, 
    QGroupBox, QFormLayout, QCheckBox, QSpinBox, QFrame, QDialog, 
    QDialogButtonBox, QCompleter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QStringListModel, QThread, QObject, QUrl
from PyQt5.QtGui import QFont, QColor, QDesktopServices

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsDataSourceUri, QgsField,
    QgsFeature, Qgis, QgsApplication, QgsTask, QgsTaskManager
)
from qgis.utils import iface
from PyQt5.QtCore import QVariant

try:
    from .dqe_utils import _db_manager, _logger, _validator, FileUtils
    from .dqe_pro_tab import DQEProTab
    from .dqe_exe_tab import DQEExeTab
    from .dqe_pgc_tab import DQEPGCTab
    from .dqe_recover_tab import DQERecoverTab
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = _validator = None
    DQEProTab = DQEExeTab = DQEPGCTab = DQERecoverTab = None
    MODULES_AVAILABLE = False


# OperationType et DQEResult centralises dans models.py
from .models import DQEResult, OperationType


class DQEChargeur(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("Chargeur DQE")
        self.setMinimumSize(380, 280)
        self.resize(400, 320)
        self.setModal(False)
        
        # Police Corbel globale
        self.setStyleSheet("QWidget { font-family: 'Corbel', 'Segoe UI', sans-serif; }")
        
        self.setup_ui()
        
        if _logger:
            _logger.info("Interface DQE Chargeur initialisee")
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        
        header_layout = QHBoxLayout()
        header_layout.setSpacing(5)
        
        title_label = QLabel("Chargeur DQE")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Indicateur connexion DB
        self.db_status_label = QLabel()
        self._update_db_status()
        header_layout.addWidget(self.db_status_label)
        
        version_label = QLabel("v3.5.1")
        version_label.setStyleSheet("color: #666; font-style: italic;")
        header_layout.addWidget(version_label)
        
        layout.addLayout(header_layout)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        self.tab_widget = QTabWidget()
        self.tab_widget.setContentsMargins(0, 0, 0, 0)
        
        self.pro_tab = DQEProTab()
        self.tab_widget.addTab(self.pro_tab, "DQE PRO")
        
        self.exe_tab = DQEExeTab()
        self.tab_widget.addTab(self.exe_tab, "DQE EXE")
        
        self.pgc_tab = DQEPGCTab()
        self.tab_widget.addTab(self.pgc_tab, "DQE PGC")
        
        self.recover_tab = DQERecoverTab()
        self.tab_widget.addTab(self.recover_tab, "DQE Recover")
        
        # Ajuster la taille selon l'onglet
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        layout.addWidget(self.tab_widget)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.close)
        
        help_button = QPushButton("Aide")
        help_button.clicked.connect(self.show_help)
        button_box.addButton(help_button, QDialogButtonBox.HelpRole)
        
        layout.addWidget(button_box)
        pass
    
    def on_tab_changed(self, index):
        """Ajuste la taille du dialogue selon l'onglet actif"""
        tab_name = self.tab_widget.tabText(index)
        if "Recover" in tab_name:
            self.setMinimumSize(600, 500)
            self.resize(650, 600)
        else:
            self.setMinimumSize(380, 280)
            self.resize(400, 320)
    
    def show_help(self):
        """Ouvre la documentation HTML complete"""
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        doc_path = os.path.join(plugin_dir, "docs", "index.html")
        
        if os.path.exists(doc_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(doc_path))
        else:
            QMessageBox.warning(self, "Documentation", 
                f"Fichier documentation introuvable:\n{doc_path}")
    
    def _update_db_status(self):
        """Met a jour l'indicateur de connexion DB"""
        if _db_manager and _db_manager.is_connected:
            self.db_status_label.setText("DB")
            self.db_status_label.setStyleSheet(
                "color: white; background-color: #2E7D32; "
                "padding: 2px 6px; border-radius: 3px; font-size: 10px;"
            )
            self.db_status_label.setToolTip("Connexion base de donnees active")
        else:
            self.db_status_label.setText("DB")
            self.db_status_label.setStyleSheet(
                "color: white; background-color: #C62828; "
                "padding: 2px 6px; border-radius: 3px; font-size: 10px;"
            )
            self.db_status_label.setToolTip("Connexion base de donnees inactive")


def run_dqe_chargeur():
    dialog = DQEChargeur(iface.mainWindow() if iface else None)
    dialog.show()
    return dialog


__all__ = [
    'DQEChargeur', 'DQEResult', 'OperationType',
    'run_dqe_chargeur'
]
