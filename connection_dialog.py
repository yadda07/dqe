"""
Interface de connexion à la base de données
==========================================

Dialog pour saisir les paramètres de connexion PostgreSQL
"""

import os
import json
from typing import Optional, Dict, Any

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, 
    QLineEdit, QPushButton, QLabel, QCheckBox, 
    QMessageBox, QGroupBox, QSpinBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from qgis.core import QgsSettings
from qgis.utils import iface

from .dqe_utils import DatabaseConfig


class ConnectionDialog(QDialog):
    """Dialog pour configurer la connexion à la base de données"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuration de la connexion PostgreSQL")
        self.setModal(True)
        self.resize(450, 350)
        
        # Données de connexion
        self.connection_config = None
        
        # Interface
        self.setup_ui()
        self.load_saved_values()
    
    def setup_ui(self):
        """Configure l'interface utilisateur"""
        layout = QVBoxLayout(self)
        
        # Titre et description
        title_label = QLabel("Configuration de la base de données DQE")
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #2E7D32;")
        layout.addWidget(title_label)
        
        desc_label = QLabel(
            "Aucune connexion PostgreSQL valide n'a été trouvée dans QGIS.\n"
            "Veuillez saisir les paramètres de connexion à votre base de données DQE :"
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #555; margin-bottom: 10px;")
        layout.addWidget(desc_label)
        
        # Groupe de connexion
        conn_group = QGroupBox("Paramètres de connexion")
        conn_layout = QFormLayout(conn_group)
        
        # Champs de saisie
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("localhost ou IP du serveur")
        self.host_edit.setText("localhost")
        conn_layout.addRow("Hôte :", self.host_edit)
        
        self.port_spinbox = QSpinBox()
        self.port_spinbox.setRange(1, 65535)
        self.port_spinbox.setValue(5432)
        conn_layout.addRow("Port :", self.port_spinbox)
        
        self.database_edit = QLineEdit()
        self.database_edit.setPlaceholderText("Nom de la base de données")
        conn_layout.addRow("Base de données :", self.database_edit)
        
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Nom d'utilisateur")
        conn_layout.addRow("Utilisateur :", self.user_edit)
        
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Mot de passe")
        conn_layout.addRow("Mot de passe :", self.password_edit)
        
        layout.addWidget(conn_group)
        
        # Options de sauvegarde
        save_group = QGroupBox("Options de sauvegarde")
        save_layout = QVBoxLayout(save_group)
        
        self.save_qgis_checkbox = QCheckBox("Sauvegarder comme connexion QGIS")
        self.save_qgis_checkbox.setChecked(True)
        self.save_qgis_checkbox.setToolTip("Créer une connexion PostgreSQL dans QGIS")
        save_layout.addWidget(self.save_qgis_checkbox)
        
        self.save_json_checkbox = QCheckBox("Sauvegarder dans un fichier de configuration")
        self.save_json_checkbox.setChecked(False)
        self.save_json_checkbox.setToolTip("Créer un fichier config.json dans le plugin")
        save_layout.addWidget(self.save_json_checkbox)
        
        layout.addWidget(save_group)
        
        # Boutons
        button_layout = QHBoxLayout()
        
        self.test_button = QPushButton("Tester la connexion")
        self.test_button.clicked.connect(self.test_connection)
        button_layout.addWidget(self.test_button)
        
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Annuler")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.ok_button = QPushButton("Connecter")
        self.ok_button.clicked.connect(self.accept_connection)
        self.ok_button.setDefault(True)
        self.ok_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
        
        # Focus sur le premier champ vide
        if not self.host_edit.text():
            self.host_edit.setFocus()
        elif not self.database_edit.text():
            self.database_edit.setFocus()
        elif not self.user_edit.text():
            self.user_edit.setFocus()
        else:
            self.password_edit.setFocus()
    
    def load_saved_values(self):
        """Charge les valeurs sauvegardées précédemment"""
        try:
            # Essayer de charger depuis le fichier JSON du plugin
            config_file = os.path.join(os.path.dirname(__file__), 'config.json')
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                
                db_config = config_data.get('database', {})
                self.host_edit.setText(db_config.get('host', 'localhost'))
                self.port_spinbox.setValue(int(db_config.get('port', 5432)))
                self.database_edit.setText(db_config.get('database', ''))
                self.user_edit.setText(db_config.get('user', ''))
                # Ne pas charger le mot de passe pour des raisons de sécurité
                
        except Exception:
            pass  # Ignorer les erreurs de chargement
    
    def get_connection_data(self) -> Dict[str, str]:
        """Retourne les données de connexion saisies"""
        return {
            'host': self.host_edit.text().strip(),
            'port': str(self.port_spinbox.value()),
            'database': self.database_edit.text().strip(),
            'user': self.user_edit.text().strip(),
            'password': self.password_edit.text()
        }
    
    def validate_form(self) -> bool:
        """Valide les champs du formulaire"""
        data = self.get_connection_data()
        
        if not data['host']:
            QMessageBox.warning(self, "Erreur", "L'hôte est requis")
            self.host_edit.setFocus()
            return False
        
        if not data['database']:
            QMessageBox.warning(self, "Erreur", "Le nom de la base de données est requis")
            self.database_edit.setFocus()
            return False
        
        if not data['user']:
            QMessageBox.warning(self, "Erreur", "Le nom d'utilisateur est requis")
            self.user_edit.setFocus()
            return False
        
        if not data['password']:
            QMessageBox.warning(self, "Erreur", "Le mot de passe est requis")
            self.password_edit.setFocus()
            return False
        
        return True
    
    def test_connection(self):
        """Teste la connexion à la base de données"""
        if not self.validate_form():
            return
        
        try:
            # Tester la connexion
            data = self.get_connection_data()
            config = DatabaseConfig(**data)
            
            # Import ici pour éviter les imports circulaires
            import psycopg2
            
            # Test de connexion simple
            conn = psycopg2.connect(**config.to_dict())
            cursor = conn.cursor()
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            
            QMessageBox.information(
                self, "Succès", 
                f"Connexion réussie !\n\nVersion PostgreSQL :\n{version[:100]}..."
            )
            
        except Exception as e:
            QMessageBox.critical(
                self, "Erreur de connexion", 
                f"Impossible de se connecter à la base de données :\n\n{str(e)}"
            )
    
    def accept_connection(self):
        """Accepte la connexion et sauvegarde si demandé"""
        if not self.validate_form():
            return
        
        try:
            data = self.get_connection_data()
            self.connection_config = DatabaseConfig(**data)
            
            # Sauvegarder si demandé
            if self.save_qgis_checkbox.isChecked():
                self.save_to_qgis(data)
            
            if self.save_json_checkbox.isChecked():
                self.save_to_json(data)
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(
                self, "Erreur", 
                f"Erreur lors de la configuration :\n\n{str(e)}"
            )
    
    def save_to_qgis(self, data: Dict[str, str]):
        """Sauvegarde la connexion dans QGIS"""
        try:
            settings = QgsSettings()
            conn_name = "DQE_Connection"
            
            # Vérifier si la connexion existe déjà
            settings.beginGroup("PostgreSQL/connections")
            connections = settings.childGroups()
            settings.endGroup()
            
            if conn_name in connections:
                reply = QMessageBox.question(
                    self, "Connexion existante",
                    f"Une connexion '{conn_name}' existe déjà dans QGIS.\n"
                    "Voulez-vous la remplacer ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply != QMessageBox.Yes:
                    return
            
            # Sauvegarder la connexion
            settings.beginGroup(f"PostgreSQL/connections/{conn_name}")
            settings.setValue("host", data['host'])
            settings.setValue("port", data['port'])
            settings.setValue("database", data['database'])
            settings.setValue("username", data['user'])
            settings.setValue("password", data['password'])
            settings.setValue("sslmode", "1")  # Préférer SSL
            settings.setValue("saveUsername", "true")
            settings.setValue("savePassword", "true")
            settings.setValue("estimatedMetadata", "false")
            settings.endGroup()
            
            if iface:
                iface.messageBar().pushMessage(
                    "DQE Plugin", 
                    f"Connexion '{conn_name}' sauvegardée dans QGIS",
                    level=1, duration=5  # Success
                )
            
        except Exception as e:
            QMessageBox.warning(
                self, "Avertissement",
                f"Impossible de sauvegarder dans QGIS :\n{str(e)}"
            )
    
    def save_to_json(self, data: Dict[str, str]):
        """Sauvegarde la connexion dans un fichier JSON"""
        try:
            config_file = os.path.join(os.path.dirname(__file__), 'config.json')
            
            # Créer la structure de configuration
            config_data = {
                "database": {
                    "host": data['host'],
                    "port": int(data['port']),
                    "database": data['database'],
                    "user": data['user'],
                    "password": data['password']
                }
            }
            
            # Sauvegarder
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            
            if iface:
                iface.messageBar().pushMessage(
                    "DQE Plugin", 
                    "Configuration sauvegardée dans config.json",
                    level=1, duration=5  # Success
                )
            
        except Exception as e:
            QMessageBox.warning(
                self, "Avertissement",
                f"Impossible de sauvegarder le fichier JSON :\n{str(e)}"
            )
    
    def get_config(self) -> Optional[DatabaseConfig]:
        """Retourne la configuration validée"""
        return self.connection_config
