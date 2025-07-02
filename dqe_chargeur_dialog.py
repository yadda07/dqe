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
from enum import Enum, auto
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
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QStringListModel, QThread, QObject
from PyQt5.QtGui import QFont, QColor

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
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = _validator = None
    DQEProTab = DQEExeTab = DQEPGCTab = None
    MODULES_AVAILABLE = False


class OperationType(Enum):
    DQE_PRO = auto()
    DQE_EXE = auto()
    DQE_PGC = auto()


@dataclass
class DQEResult:
    designation: str
    unite: str = "ml"
    quantite: float = 0.0
    ids: List[int] = field(default_factory=list)
    
    @property
    def ids_string(self) -> str:
        return ",".join(str(id_) for id_ in self.ids)


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
        
        # Barre de progression avec texte de pourcentage
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_bar)
        
        # Bouton d'annulation
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


class SROComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.sro_list = []
        self.load_sro_list()
        
    def load_sro_list(self):
        """Charge la liste des SRO avec autocomplétion"""
        try:
            if _db_manager and _db_manager._connection_pool:
                # Requête exacte demandée par l'utilisateur
                query = "SELECT sro FROM rip_avg_nge.za_sro"
                
                print(f"Chargement SRO avec requête: {query}")
                results = _db_manager.execute_query(query)
                self.sro_list = [row[0] for row in results if row[0] and str(row[0]).strip()]
                
                # Configuration optimisée de l'autocomplétion
                model = QStringListModel(self.sro_list)
                completer = QCompleter()
                completer.setModel(model)
                
                # Configuration pour afficher le popup
                completer.setCaseSensitivity(Qt.CaseInsensitive)
                completer.setFilterMode(Qt.MatchContains)  # Recherche partielle
                completer.setCompletionMode(QCompleter.PopupCompletion)  # Mode popup
                completer.setMaxVisibleItems(10)  # Maximum 10 éléments visibles
                
                # Appliquer le completer au champ éditable
                line_edit = self.lineEdit()
                line_edit.setCompleter(completer)
                
                # Forcer l'affichage du popup dès qu'on tape
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
            
            # En cas d'erreur, utiliser une liste vide
            self.sro_list = []
    
    def _show_completions(self, text: str, completer: QCompleter):
        """Force l'affichage des suggestions quand on tape"""
        if len(text) >= 1:  # Afficher dès 1 caractère
            # Filtrer les SRO qui contiennent le texte
            matching_sros = [sro for sro in self.sro_list if text.upper() in sro.upper()]
            
            if matching_sros:
                print(f" Recherche '{text}': {len(matching_sros)} SRO trouvés")
                print(f"Exemples: {', '.join(matching_sros[:3])}{'...' if len(matching_sros) > 3 else ''}")
                
                # Mettre à jour le modèle avec les résultats filtrés
                new_model = QStringListModel(matching_sros)
                completer.setModel(new_model)
                
                # Forcer l'affichage du popup
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


class DatabaseOperations:
    @staticmethod
    def get_db_connection_params():
        if _db_manager and _db_manager._config:
            return _db_manager._config.to_dict()
        return None
    
    @staticmethod
    def execute_dqe_pro(sro: str, p_type: str) -> List[Dict[str, Any]]:
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            raise RuntimeError("Paramètres DB non disponibles")
        
        conn = psycopg2.connect(
            host=db_params["host"],
            port=db_params["port"],
            database=db_params["database"],
            user=db_params["user"],
            password=db_params["password"]
        )
        
        try:
            cursor = conn.cursor(cursor_factory=DictCursor)
            
            if p_type == 'T':
                cursor.execute("SET statement_timeout TO '90000'")
            
            print(f"Exécution de dqe2('{sro}', '{p_type}')")
            query = "SELECT * FROM rip_avg_nge.dqe2(%s, %s)"
            cursor.execute(query, (sro, p_type))
            results = cursor.fetchall()
            
            print(f"Résultats bruts: {len(results)} lignes reçues de la base")
            
            cleaned_results = []
            for i, row in enumerate(results):
                row_dict = dict(row)
                if i == 0:
                    print(f"Première ligne (exemple): {row_dict}")
                cleaned_results.append(row_dict)
            
            print(f"Résultats nettoyés: {len(cleaned_results)} lignes retournées")
            return cleaned_results
            
        finally:
            conn.close()
    
    @staticmethod
    def execute_dqe_exe(sro: str, p_type: str) -> List[Dict[str, Any]]:
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            raise RuntimeError("Paramètres DB non disponibles")
        
        conn = psycopg2.connect(
            host=db_params["host"],
            port=db_params["port"],
            database=db_params["database"],
            user=db_params["user"],
            password=db_params["password"]
        )
        
        try:
            cursor = conn.cursor(cursor_factory=DictCursor)
            
            print(f"Exécution de dqe_exe('{sro}', '{p_type}')")
            query = "SELECT * FROM rip_avg_nge.dqe_exe(%s, %s)"
            cursor.execute(query, (sro, p_type))
            results = cursor.fetchall()
            
            print(f"Résultats bruts: {len(results)} lignes reçues de la base")
            
            cleaned_results = []
            for i, row in enumerate(results):
                row_dict = dict(row)
                if i == 0:
                    print(f"Première ligne (exemple): {row_dict}")
                cleaned_results.append(row_dict)
            
            print(f"Résultats nettoyés: {len(cleaned_results)} lignes retournées")
            return cleaned_results
            
        finally:
            conn.close()
    
    @staticmethod
    def execute_dqe_pgc(sro: str, troncon: str) -> List[DQEResult]:
        """
        CORRECTION CRITIQUE PGC : 
        - Débogage complet des clés retournées par la fonction
        - Gestion des en-têtes et lignes vides
        - Récupération correcte des IDs
        """
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            raise RuntimeError("Paramètres DB non disponibles")
        
        conn = psycopg2.connect(
            host=db_params["host"],
            port=db_params["port"],
            database=db_params["database"],
            user=db_params["user"],
            password=db_params["password"]
        )
        
        try:
            cursor = conn.cursor(cursor_factory=DictCursor)
            print(f"\n=== DÉBUT DQE PGC DEBUG ===")
            print(f"SRO: {sro}, Tronçon: {troncon}")
            
            query = "SELECT * FROM rip_avg_nge.dqe_pgc(%s, %s)"
            cursor.execute(query, (sro, troncon))
            raw_results = cursor.fetchall()
            
            print(f"Résultats bruts de la fonction: {len(raw_results)} lignes")
            
            # DEBUG: Afficher les premières lignes pour voir la structure
            for i, row in enumerate(raw_results[:10]):
                row_dict = dict(row)
                print(f"Ligne {i+1}: {row_dict}")
            
            results = []
            for i, row in enumerate(raw_results):
                row_dict = dict(row)
                
                # CORRECTION: Essayer plusieurs variantes de clés possibles
                designation = (row_dict.get("Désignation") or 
                              row_dict.get("designation") or 
                              row_dict.get("désignation") or "")
                
                unite = (row_dict.get("Unité") or 
                        row_dict.get("unite") or 
                        row_dict.get("unité") or "u")
                
                quantite = (row_dict.get("Quantité") or 
                           row_dict.get("quantite") or 
                           row_dict.get("quantité") or 0)
                
                ids_str = (row_dict.get("ids") or 
                          row_dict.get("Ids") or 
                          row_dict.get("IDS") or "")
                
                print(f"\nLigne {i+1}:")
                print(f"  Désignation: '{designation}'")
                print(f"  Unité: '{unite}'")
                print(f"  Quantité: {quantite}")
                print(f"  IDs: '{ids_str}'")
                
                # CORRECTION: Ne filtrer QUE les vraies lignes vides/en-têtes
                if not designation or designation.strip() == "":
                    print(f"  -> IGNORÉ (désignation vide)")
                    continue
                
                # Ignorer les en-têtes spécifiques
                if any(x in designation.lower() for x in [
                    "nom gc :", "désignation", "armoire de rue  -", 
                    "gc - tdr", "pose de poteaux", "fourniture des alvéoles"
                ]):
                    print(f"  -> IGNORÉ (en-tête)")
                    continue
                
                # CORRECTION: Ne plus filtrer sur quantité == 0, laisser passer même les 0
                # car certaines peuvent être légitimes
                try:
                    quantite_num = float(quantite) if quantite is not None else 0
                except (ValueError, TypeError):
                    print(f"  -> IGNORÉ (quantité invalide: {quantite})")
                    continue
                
                # CORRECTION: Ne plus exiger des IDs pour toutes les lignes
                # Certaines lignes PGC peuvent être des totaux sans GIDs spécifiques
                ids_list = []
                if ids_str and str(ids_str).strip():
                    try:
                        ids_list = [int(id_str.strip()) for id_str in str(ids_str).split(',') if id_str.strip()]
                        print(f"  -> IDs parsés: {len(ids_list)} éléments")
                    except ValueError as e:
                        print(f"  -> Erreur parsing IDs: {e}")
                        # Ne pas ignorer, juste laisser la liste vide
                
                # CORRECTION: Accepter même sans IDs si quantité > 0
                if quantite_num > 0 or ids_list:
                    result = DQEResult(
                        designation=designation.strip(),
                        unite=unite.strip(),
                        quantite=float(quantite_num),
                        ids=ids_list
                    )
                    results.append(result)
                    print(f"  ->  AJOUTÉ AU RÉSULTAT")
                else:
                    print(f"  -> IGNORÉ (quantité=0 et pas d'IDs)")
            
            print(f"\n=== RÉSULTATS FINAUX PGC ===")
            print(f"Total résultats retenus: {len(results)}")
            for i, result in enumerate(results):
                print(f"{i+1}. {result.designation} | {result.quantite} {result.unite} | {len(result.ids)} IDs")
            
            return results
            
        finally:
            conn.close()


class LayerManager:
    @staticmethod
    def create_layer_group(name: str):
        root = QgsProject.instance().layerTreeRoot()
        return root.addGroup(name)
    
    @staticmethod
    def get_db_connection_string():
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            return None
        
        uri = QgsDataSourceUri()
        uri.setConnection(
            db_params["host"], 
            db_params["port"], 
            db_params["database"],
            db_params["user"], 
            db_params["password"]
        )
        return uri
    
    @staticmethod
    def get_custom_layer_order(layer_name):
        """Classification des couches pour organisation"""
        lower_name = layer_name.lower()
        
        if any(x in lower_name for x in ["prise", "dtr", "rad"]):
            return 900  # Prises en dernier
        elif any(x in lower_name for x in ["bpe", "pbo", "pa"]):
            return 800  # Équipements
        elif any(x in lower_name for x in ["gc", "infra", "cheminement", "lineaire"]):
            return 200  # Génie civil
        elif any(x in lower_name for x in ["cable", "câble", "fibre", "fo "]):
            return 100  # Câbles en premier
        else:
            return 500  # Défaut
    
    @staticmethod
    def get_table_from_designation_pgc(designation):
        """
        CORRECTION PGC: Table spécialisée pour DQE PGC
        Différents éléments PGC utilisent différentes tables
        """
        designation = designation.lower()
        
        print(f"Détection table PGC pour: '{designation}'")
        
        # Chambres
        if any(x in designation for x in ["pose de chambre", "chambre l"]):
            print("  -> Table PGC: gc_exe.infra_pt_chb")
            return "gc_exe.infra_pt_chb"
        
        # Poteaux
        elif any(x in designation for x in ["pose poteau", "poteau rauv"]):
            print("  -> Table PGC: gc_exe.infra_pt_autres")
            return "gc_exe.infra_pt_autres"
        
        # Tranchées et travaux de terrassement (le plus courant)
        elif any(x in designation for x in [
            "tranchée", "micro tranchée", "forage dirigé", "encorbellement",
            "pvc ", "pehd", "alvéole"
        ]):
            print("  -> Table PGC: gc_exe.t_cheminement")
            return "gc_exe.t_cheminement"
        
        # Par défaut pour PGC
        else:
            print("  -> Table PGC par défaut: gc_exe.t_cheminement")
            return "gc_exe.t_cheminement"
    
    @staticmethod
    def get_table_from_designation(designation):
        """Méthode générale pour PRO/EXE"""
        designation = designation.lower()
        
        print(f"Détection de table pour: '{designation}'")
        
        # Tables EXE spécifiques (génie civil)
        if any(x in designation for x in ["tranchée", "micro tranchée", "forage dirigé", "encorbellement"]):
            print("  -> Détecté comme GC EXE (cheminement)")
            return "gc_exe.t_cheminement"
        elif any(x in designation for x in ["pose de chambre", "chambre l"]):
            print("  -> Détecté comme GC EXE (chambres)")
            return "gc_exe.infra_pt_chb"
        elif any(x in designation for x in ["pose poteau", "poteau rauv", "ft à"]):
            print("  -> Détecté comme EXE (poteaux de distribution)")
            return "rip_avg_nge.infra_pt_pot"
        elif any(x in designation for x in ["pvc ", "pehd"]):
            print("  -> Détecté comme GC EXE (alvéoles)")
            return "gc_exe.t_cheminement"
        
        # Tables PRO/EXE - BPE et équipements
        elif any(x in designation for x in ["bpe", "pa ", "pa)", "pbo", "f&p bpe", "f&p pa", "f&p de pbo"]):
            print("  -> Détecté comme BPE/PA/PBO")
            return "rip_avg_nge.bpe"
        elif "sro" in designation:
            print("  -> Détecté comme SRO")
            return "rip_avg_nge.bpe"
        
        # Tables câbles et fibres optiques
        elif any(x in designation for x in ["cable", "câble", "fibre", "fo ", "fourniture et pose de câble"]):
            print("  -> Détecté comme câble")
            return "rip_avg_nge.cables"
        
        # Tables prises et raccordements
        elif any(x in designation for x in ["prise", "dtr", "rad", "nbre de prises"]):
            print("  -> Détecté comme Prise")
            return "rbal.rbal_auvergne"
        
        # Tables génie civil PRO
        elif any(x in designation for x in ["gc", "génie civil", "cheminement", "lineaire", "infra"]):
            print("  -> Détecté comme GC/Cheminement PRO")
            return "rip_avg_nge.t_cheminement"
        
        # Par défaut pour les câbles
        else:
            print("  -> Type non reconnu, utilisation de cables par défaut")
            return "rip_avg_nge.cables"
    
    @staticmethod
    def load_layer_direct(designation, ids_str, table_name, sro="", layer_group=None):
        """Chargement direct basé sur l'ancienne méthode qui fonctionne"""
        if not ids_str or not ids_str.strip():
            print(f"        ÉCHEC: IDs vides pour {designation}")
            return None
        
        try:
            gids_list = [str(gid.strip()) for gid in ids_str.split(',') if gid.strip()]
            if not gids_list:
                print(f"        ÉCHEC: Liste GIDs vide après nettoyage pour {designation}")
                return None
            
            print(f"        GIDs traités: {len(gids_list)} éléments")
            print(f"        Premiers GIDs: {', '.join(gids_list[:5])}{'...' if len(gids_list) > 5 else ''}")
            
            uri = LayerManager.get_db_connection_string()
            if not uri:
                print(f"        ÉCHEC: URI de connexion non disponible")
                return None
            
            schema, table = table_name.split(".", 1) if "." in table_name else ("public", table_name)
            print(f"        Schéma: {schema}, Table: {table}")
            
            # Filtre simple avec gid IN (...)
            ids_joined = ",".join(gids_list)
            sql_filter = f"gid IN ({ids_joined})"
            print(f"        Filtre SQL: {sql_filter[:100]}{'...' if len(sql_filter) > 100 else ''}")
            
            uri.setDataSource(schema, table, "geom", sql_filter, "gid")
            
            layer = QgsVectorLayer(uri.uri(), designation, "postgres")
            
            if layer.isValid():
                feature_count = layer.featureCount()
                print(f"        Couche valide avec {feature_count} entités")
                
                if feature_count > 0:
                    return layer
                else:
                    print(f"        ÉCHEC: Couche vide (0 entités)")
                    return None
            else:
                error = layer.error().message() if layer.error() else "Erreur inconnue"
                print(f"        ÉCHEC: Couche invalide - {error}")
                print(f"        URI complète: {uri.uri()}")
                return None
                
        except Exception as e:
            print(f"        EXCEPTION: {str(e)}")
            import traceback
            print(f"        Traceback: {traceback.format_exc()}")
            if _logger:
                _logger.error(f"Erreur chargement couche {designation}", exception=e)
            return None
    
    @staticmethod
    def load_distribution_cables(sro, layer_group=None, layers_loaded=None):
        """Chargement des câbles découpés pour Distribution"""
        try:
            print(f"Chargement des câbles découpés pour la distribution, SRO: {sro}")
            start_time = time.time()
            
            db_params = DatabaseOperations.get_db_connection_params()
            if not db_params:
                print("Erreur: Paramètres DB non disponibles")
                return []
            
            conn = psycopg2.connect(
                host=db_params["host"],
                port=db_params["port"],
                database=db_params["database"],
                user=db_params["user"],
                password=db_params["password"]
            )
            
            conn.set_session(autocommit=False)
            cursor = conn.cursor()
            
            # Vérifier la présence de câbles découpés
            print(f"Vérification de la présence de câbles découpés pour le SRO '{sro}'...")
            cursor.execute("SELECT COUNT(*) FROM rip_avg_nge.fddcpi2(%s) WHERE cab_type = 'CDI'", (sro,))
            count_cables = cursor.fetchone()[0]
            
            if count_cables == 0:
                print(f" Aucun câble découpé trouvé pour le SRO '{sro}'")
                return []
            
            print(f"{count_cables} segments de câbles découpés trouvés pour le SRO '{sro}'")
            
            # Créer table permanente unique
            sro_safe = sro.replace("/", "_").replace("\\", "_").replace(" ", "_")
            today = datetime.now().strftime("%Y%m%d")
            unique_id = uuid.uuid4().hex[:6]
            permanent_table_name = f"cables_decoupes_{sro_safe}_{today}_{unique_id}"
            
            # Garantir un nom valide
            if len(permanent_table_name) > 50:
                sro_id = sro.split("/")[-1]
                permanent_table_name = f"cables_dec_{sro_id}_{today}_{unique_id}"
            
            qualified_table_name = f"temporaire.{permanent_table_name}"
            
            print(f"Création de la table permanente '{qualified_table_name}'...")
            
            # Supprimer si existe
            cursor.execute(f"DROP TABLE IF EXISTS {qualified_table_name}")
            
            # Créer la table permanente avec normalisation des capacités
            cursor.execute(f"""
                CREATE TABLE {qualified_table_name} AS
                SELECT 
                    c.*,
                    CASE 
                        WHEN cab_capa <= 12 THEN 12
                        WHEN cab_capa <= 24 THEN 24
                        WHEN cab_capa <= 36 THEN 36
                        WHEN cab_capa <= 48 THEN 48
                        WHEN cab_capa <= 72 THEN 72
                        WHEN cab_capa <= 96 THEN 96
                        WHEN cab_capa <= 144 THEN 144
                        WHEN cab_capa <= 288 THEN 288
                        WHEN cab_capa <= 432 THEN 432
                        WHEN cab_capa <= 576 THEN 576
                        ELSE 720
                    END AS normalized_capa,
                    '{sro}' AS sro_source,
                    NOW() AS date_creation
                FROM rip_avg_nge.fddcpi2(%s) c
                WHERE cab_type = 'CDI' AND "DCE" = 'O' AND affectation != '3'
            """, (sro,))
            
            # Créer des index pour optimiser
            cursor.execute(f"""
                CREATE INDEX idx_{permanent_table_name}_posemode 
                ON {qualified_table_name}(posemode, normalized_capa)
            """)
            
            cursor.execute(f"""
                CREATE INDEX idx_{permanent_table_name}_gid_dc2 
                ON {qualified_table_name}(gid_dc2)
            """)
            
            cursor.execute(f"ANALYZE {qualified_table_name}")
            conn.commit()
            
            print(f"Table permanente '{qualified_table_name}' créée avec succès!")
            
            # Récupérer les catégories
            cursor.execute(f"""
                SELECT 
                    posemode,
                    normalized_capa,
                    COUNT(*) as count
                FROM {qualified_table_name}
                GROUP BY posemode, normalized_capa
                ORDER BY posemode, normalized_capa
            """)
            
            categories = cursor.fetchall()
            print(f"Trouvé {len(categories)} catégories de câbles découpés")
            
            created_layers = []
            uri = LayerManager.get_db_connection_string()
            if not uri:
                print("Erreur: Impossible de récupérer l'URI de connexion")
                return []
            
            # Créer les couches par catégorie
            for idx, (posemode, capa, count) in enumerate(categories):
                if count == 0:
                    continue
                
                # Noms selon le format DQE
                if posemode == 0:
                    layer_name = f"Câble de {capa} FO en conduite"
                elif posemode == 1:
                    layer_name = f"Câble optique de {capa} FO en aérien"
                elif posemode == 2:
                    layer_name = f"Câble optique de {capa} FO en façade"
                else:
                    layer_name = f"Câble de {capa} FO (mode pose {posemode})"
                
                # Requête SQL utilisant la table permanente
                sql_query = f"""
                    SELECT * 
                    FROM {qualified_table_name}
                    WHERE posemode = {posemode} AND normalized_capa = {capa}
                """
                
                # Créer la couche QGIS
                uri_copy = QgsDataSourceUri(uri.uri())
                uri_copy.setDataSource("", f"({sql_query})", "geom", "", "gid_dc2")
                
                layer = QgsVectorLayer(uri_copy.uri(False), layer_name, "postgres")
                
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer, False)
                    if layer_group:
                        layer_group.addLayer(layer)
                    if layers_loaded is not None:
                        layers_loaded.append(layer)
                    created_layers.append(layer)
                    print(f"Couche créée: {layer_name} ({layer.featureCount()} entités)")
                else:
                    print(f" Échec du chargement de la couche {layer_name}")
            
            conn.close()
            
            end_time = time.time()
            print(f"Temps total de chargement des câbles découpés: {end_time - start_time:.2f} secondes")
            print(f"Total de {len(created_layers)} couches de câbles découpés chargées avec succès")
            
            return created_layers
                
        except Exception as e:
            import traceback
            print(f"ERREUR dans le chargement des câbles découpés: {str(e)}")
            print(traceback.format_exc())
            try:
                if 'conn' in locals():
                    conn.rollback()
                    conn.close()
            except:
                pass
            return []


class ExcelManager:
    @staticmethod
    def get_template_path(operation_type: str) -> str:
        """Retourne le chemin du template selon le type d'opération"""
        plugin_dir = os.path.dirname(__file__)
        template_files = {
            'PRO': 'template_dqe_pro.xlsx',
            'EXE': 'template_dqe_exe.xlsx', 
            'PGC': 'template_dqe_pgc.xlsx'
        }
        
        template_name = template_files.get(operation_type.upper(), 'template_dqe_pro.xlsx')
        template_path = os.path.join(plugin_dir, 'files', template_name)
        
        print(f"Template recherché pour {operation_type}: {template_path}")
        
        if not os.path.exists(template_path):
            print(f" Template non trouvé: {template_path}")
            # Fallback vers template PRO si le spécifique n'existe pas
            fallback_path = os.path.join(plugin_dir, 'files', 'template_dqe_pro.xlsx')
            if os.path.exists(fallback_path):
                print(f"Utilisation du template fallback: {fallback_path}")
                return fallback_path
            else:
                print(" Aucun template trouvé")
                return None
        
        return template_path
    
    @staticmethod
    def create_excel_report(results: List[Dict], sro: str, operation_type: str, troncon: str = None):
        """Génère le rapport Excel en utilisant le bon template"""
        if not results:
            return None
        
        try:
            print(f"\n=== Génération Excel {operation_type.upper()} ===")
            
            # Récupérer le template approprié
            template_path = ExcelManager.get_template_path(operation_type)
            if not template_path:
                print(" Aucun template disponible, génération basique")
                return ExcelManager._create_basic_excel(results, sro, operation_type, troncon)
            
            # Préparation des données
            df = pd.DataFrame(results)
            
            # IMPORTANT: Préserver les IDs dans results pour le chargement des couches
            # Ne supprimer que du DataFrame Excel, pas de results original
            if 'ids' in df.columns:
                print(f"Conservation des IDs des câbles découpés pour {operation_type}")
                df = df.drop(columns=['ids'])  # Supprimer seulement du DataFrame Excel
            
            if len(df.columns) >= 3:
                df.columns = ["Désignation", "Unité", "Quantité"]
                
                if "Quantité" in df.columns:
                    df["Quantité"] = pd.to_numeric(df["Quantité"], errors='coerce')
                    df["Quantité"] = df["Quantité"].round().fillna(0).astype(int)
            
            # Chemin de sortie
            temp_dir = tempfile.gettempdir()
            sro_safe = sro.replace('/', '_')
            
            if troncon:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_{sro_safe}_{troncon}_{int(time.time())}.xlsx")
            else:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_{sro_safe}_{int(time.time())}.xlsx")
            
            print(f"Fichier de sortie: {excel_path}")
            
            # Copier le template vers le fichier de sortie
            shutil.copy2(template_path, excel_path)
            print(f"Template copié vers: {excel_path}")
            
            # Charger le workbook et remplir les données
            workbook = load_workbook(excel_path)
            
            # Déterminer la feuille à utiliser
            sheet_name = f"DQE {operation_type.upper()}"
            
            # Essayer de trouver la bonne feuille
            target_sheet = None
            for sheet in workbook.sheetnames:
                if operation_type.upper() in sheet.upper():
                    target_sheet = workbook[sheet]
                    print(f"Feuille trouvée: {sheet}")
                    break
            
            if not target_sheet:
                # Prendre la première feuille par défaut
                target_sheet = workbook.active
                print(f"Feuille par défaut utilisée: {target_sheet.title}")
            
            # Remplir les données selon le type
            if operation_type.upper() == 'PGC':
                ExcelManager._fill_pgc_template(target_sheet, df, sro, troncon)
            else:
                ExcelManager._fill_standard_template(target_sheet, df, operation_type)
            
            # Sauvegarder et fermer
            workbook.save(excel_path)
            workbook.close()
            
            print(f" Rapport Excel généré: {excel_path}")
            
            # Ouvrir automatiquement
            ExcelManager._open_excel_file(excel_path)
            
            return excel_path
            
        except Exception as e:
            print(f" Erreur génération Excel: {str(e)}")
            import traceback
            print(traceback.format_exc())
            if _logger:
                _logger.error("Erreur génération Excel", exception=e)
            return None
    
    @staticmethod
    def _fill_pgc_template(sheet, df: pd.DataFrame, sro: str, troncon: str):
        """Remplit spécifiquement le template PGC avec gestion dynamique des alvéoles et du nom GC"""
        print(f"Remplissage template PGC avec {len(df)} lignes")
        print(f"SRO: {sro}, Tronçon: {troncon}")
        
        # 1. GÉRER LA LIGNE "Nom GC :" dynamiquement
        gc_row = None
        for row in range(1, min(20, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Nom GC :" in str(cell_value):
                gc_row = row
                print(f"Ligne 'Nom GC :' trouvée à la ligne {row}")
                break
        
        if gc_row:
            # Remplacer par le bon tronçon
            new_gc_text = f"Nom GC : {troncon}"
            sheet.cell(row=gc_row, column=1, value=new_gc_text)
            print(f" Ligne GC mise à jour: '{new_gc_text}'")
        else:
            print(" Ligne 'Nom GC :' non trouvée dans le template")
        
        # 2. Rechercher la ligne d'en-tête "Désignation"
        header_row = None
        for row in range(1, min(50, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Désignation" in str(cell_value):
                header_row = row
                print(f"En-tête trouvé à la ligne {header_row}")
                break
        
        if not header_row:
            print(" En-tête 'Désignation' non trouvé, utilisation ligne 1")
            header_row = 1
        
        # 3. Trouver la section "Fourniture des Alvéoles" dans le template
        alveoles_section_row = None
        for row in range(header_row, sheet.max_row + 1):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Fourniture des Alvéoles" in str(cell_value):
                alveoles_section_row = row
                break
        
        # 4. Séparer les données en groupes
        alveoles_data = []
        other_data = []
        
        for _, result_row in df.iterrows():
            designation = str(result_row['Désignation']).strip()
            quantite = result_row['Quantité']
            unite = result_row.get('Unité', 'ml')
            
            # Ignorer les en-têtes et lignes spéciales
            if not designation or any(x in designation.lower() for x in [
                "nom gc", "désignation", "armoire de rue  -", "gc - tdr", 
                "pose de poteaux", "fourniture des alvéoles"
            ]):
                continue
            
            # Détecter les éléments d'alvéoles (PVC/PEHD)
            if any(x in designation.lower() for x in ["pvc ", "pehd"]):
                alveoles_data.append({
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite
                })
            else:
                other_data.append({
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite
                })
        
        # 5. Traiter d'abord les éléments standards (non-alvéoles)
        matched_count = 0
        for data in other_data:
            template_row = ExcelManager._find_template_row(sheet, data['designation'], header_row)
            
            if template_row:
                sheet.cell(row=template_row, column=3, value=data['quantite'])
                matched_count += 1
            else:
                # Debug pour les lignes non trouvées (probablement les 6FO)
                if "6 FO" in data['designation'] or "6FO" in data['designation']:
                    print(f"DEBUG: Ligne 6FO NON TROUVÉE dans template: '{data['designation']}'")
                else:
                    print(f"DEBUG: Ligne NON TROUVÉE dans template: '{data['designation']}'")
        
        # 6. Traiter les alvéoles dynamiquement
        if alveoles_data and alveoles_section_row:
            print(f"Ajout de {len(alveoles_data)} alvéoles après la ligne {alveoles_section_row}")
            next_row = alveoles_section_row + 1
            
            for alv_data in alveoles_data:
                # Trouver la prochaine ligne vide après la section alvéoles
                while next_row <= sheet.max_row and sheet.cell(row=next_row, column=1).value:
                    next_row += 1
                
                # Ajouter la ligne alvéole
                sheet.cell(row=next_row, column=1, value=alv_data['designation'])
                sheet.cell(row=next_row, column=2, value=alv_data['unite'])
                sheet.cell(row=next_row, column=3, value=alv_data['quantite'])
                print(f" ALVÉOLE ajoutée: {alv_data['designation']} -> ligne {next_row}")
                next_row += 1
                matched_count += 1
        elif alveoles_data:
            print(f" {len(alveoles_data)} alvéoles trouvées mais section 'Fourniture des Alvéoles' manquante dans template")
        
        # Résumé final
        print(f"\n=== RÉSUMÉ REMPLISSAGE PGC ===")
        print(f"Tronçon: {troncon}")
        print(f"Lignes standards mappées: {matched_count - len(alveoles_data) if alveoles_data else matched_count}")
        print(f"Alvéoles ajoutées: {len(alveoles_data) if alveoles_data else 0}")
        print(f"Total effectif dans le rapport: {matched_count}")
        
        return matched_count
    
    @staticmethod
    def _find_next_section(sheet, current_section_row: int) -> int:
        """Trouve la ligne de fin de la section courante (début de la section suivante)"""
        # Chercher la prochaine ligne qui commence une nouvelle section
        for row in range(current_section_row + 1, min(current_section_row + 50, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and isinstance(cell_value, str):
                # Si la ligne est en gras ou contient des mots-clés de section
                cell = sheet.cell(row=row, column=1)
                if (cell.font and cell.font.bold) or any(keyword in cell_value.lower() for keyword in [
                    "fourniture", "pose de", "armoire", "gc -", "transport", "distribution"
                ]):
                    return row - 1
        
        # Si pas trouvé, retourner une estimation
        return current_section_row + 20
    
    @staticmethod
    def _fill_standard_template(sheet, df, operation_type):
        """Remplit le template standard avec les données"""
        if df.empty:
            return
        
        if operation_type.upper() == 'EXE':
            # LOGIQUE EXE : Correspondance par index + alvéoles dynamiques
            return ExcelManager._fill_exe_template(sheet, df)
        else:
            # LOGIQUE PRO : Écrire nouvelles lignes après en-tête
            return ExcelManager._fill_pro_template(sheet, df)
    
    @staticmethod
    def _fill_exe_template(sheet, df):
        """Remplit le template EXE (correspondance par index + alvéoles dynamiques)"""
        updated_rows = []
        alveoles_data = []
        
        for i, (_, row) in enumerate(df.iterrows()):
            designation = row['Désignation']
            quantite = row['Quantité']
            unite = row.get('Unité', 'ml')
            
            # Vérifier si c'est une alvéole (dynamique)
            if any(keyword in designation.lower() for keyword in ['pvc', 'pehd', 'alvéole', 'alveole']):
                alveoles_data.append({
                    'designation': designation,
                    'unite': unite,
                    'quantite': quantite
                })
            else:
                # Correspondance directe par index pour tous les autres éléments
                target_row = i + 2  # +2 car ligne 1 = en-tête, données à partir de ligne 2
                
                # Mettre à jour seulement la quantité (colonne 3)
                sheet.cell(row=target_row, column=3, value=quantite)
                updated_rows.append(f"{designation} -> ligne {target_row}")
        
        # Traitement dynamique des alvéoles
        if alveoles_data:
            # Trouver la section alvéoles
            alveoles_header_row = None
            for row in range(130, min(sheet.max_row + 10, 150)):
                cell_value = sheet.cell(row=row, column=1).value
                if cell_value and 'fourniture des alvéoles' in str(cell_value).lower():
                    alveoles_header_row = row
                    break
            
            if alveoles_header_row:
                # Ajouter les alvéoles dynamiquement
                next_row = alveoles_header_row + 1
                for alv_data in alveoles_data:
                    # Trouver la prochaine ligne vide
                    while next_row <= sheet.max_row and sheet.cell(row=next_row, column=1).value:
                        next_row += 1
                    
                    sheet.cell(row=next_row, column=1, value=alv_data['designation'])
                    sheet.cell(row=next_row, column=2, value=alv_data['unite'])
                    sheet.cell(row=next_row, column=3, value=alv_data['quantite'])
                    updated_rows.append(f"ALVÉOLE {alv_data['designation']} -> ligne {next_row}")
                    next_row += 1
        
        print(f"Template EXE rempli: {len(updated_rows)} lignes")
        return updated_rows
    
    @staticmethod
    def _fill_pro_template(sheet, df):
        """Remplit le template PRO (écrire nouvelles lignes après en-tête)"""
        # Chercher l'en-tête "Désignation"
        start_row = 2  # Par défaut ligne 2
        for row in range(1, min(20, sheet.max_row + 1)):
            cell_value = sheet.cell(row=row, column=1).value
            if cell_value and "Désignation" in str(cell_value):
                start_row = row + 1
                break
        
        # Nettoyer les données existantes après l'en-tête (simple)
        for row in range(start_row, sheet.max_row + 1):
            sheet.cell(row=row, column=1).value = None
            sheet.cell(row=row, column=2).value = None
            sheet.cell(row=row, column=3).value = None
        
        # Écrire les nouvelles données
        updated_rows = []
        for i, (_, row) in enumerate(df.iterrows()):
            designation = row['Désignation']
            unite = row.get('Unité', '')
            quantite = row['Quantité']
            
            # Ignorer les lignes vides
            if not designation or str(designation).strip() == '':
                continue
            
            current_row = start_row + i
            sheet.cell(row=current_row, column=1, value=designation)
            sheet.cell(row=current_row, column=2, value=unite)
            sheet.cell(row=current_row, column=3, value=quantite)
            updated_rows.append(f"{designation} -> ligne {current_row}")
        
        print(f"Template PRO rempli: {len(updated_rows)} lignes")
        return updated_rows
    
    @staticmethod
    def _find_template_row(sheet, designation: str, start_row: int = 1, end_row: int = None) -> Optional[int]:
        """Trouve la ligne correspondante dans le template"""
        designation_lower = designation.lower().strip()
        
        # Recherche simple et rapide
        for row in range(start_row, min(end_row or sheet.max_row + 1, start_row + 200)):
            cell_value = sheet.cell(row=row, column=1).value
            if not cell_value:
                continue
            
            template_text = str(cell_value).lower().strip()
            
            # Correspondance exacte (pour BPE et autres)
            if template_text == designation_lower:
                return row
            
            # Correspondance partielle simple pour câbles (sans parenthèses)
            if "câble" in designation_lower and "câble" in template_text:
                # Extraire nombre de FO
                import re
                des_fo = re.search(r'(\d+)\s*fo', designation_lower)
                tem_fo = re.search(r'(\d+)\s*fo', template_text)
                
                if des_fo and tem_fo and des_fo.group(1) == tem_fo.group(1):
                    # Vérifier les mots-clés critiques
                    critical_words = ['conduite', 'façade', 'aérien', 'immeuble']
                    for word in critical_words:
                        if (word in designation_lower) != (word in template_text):
                            break
                    else:
                        return row
        
        return None
    
    @staticmethod
    def _create_basic_excel(results: List[Dict], sro: str, operation_type: str, troncon: str = None):
        """Génération Excel basique si pas de template"""
        try:
            df = pd.DataFrame(results)
            
            if 'ids' in df.columns:
                df = df.drop(columns=['ids'])
            
            if len(df.columns) >= 3:
                df.columns = ["Désignation", "Unité", "Quantité"]
                
                if "Quantité" in df.columns:
                    df["Quantité"] = pd.to_numeric(df["Quantité"], errors='coerce')
                    df["Quantité"] = df["Quantité"].round().fillna(0).astype(int)
            
            temp_dir = tempfile.gettempdir()
            sro_safe = sro.replace('/', '_')
            
            if troncon:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_basic_{sro_safe}_{troncon}_{int(time.time())}.xlsx")
            else:
                excel_path = os.path.join(temp_dir, f"dqe_{operation_type}_basic_{sro_safe}_{int(time.time())}.xlsx")
            
            with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name=f'DQE {operation_type.upper()}', index=False)
            
            return excel_path
            
        except Exception as e:
            print(f"Erreur génération Excel basique: {e}")
            return None
    
    @staticmethod
    def _open_excel_file(excel_path: str):
        """Ouvre le fichier Excel avec l'application par défaut"""
        try:
            import subprocess
            import platform
            
            system = platform.system()
            if system == 'Windows':
                os.startfile(excel_path)
            elif system == 'Darwin':
                subprocess.call(['open', excel_path])
            else:
                subprocess.call(['xdg-open', excel_path])
                
        except Exception as e:
            print(f"Impossible d'ouvrir le fichier Excel: {e}")
            if _logger:
                _logger.warning("Impossible d'ouvrir automatiquement le fichier Excel", exception=e)


class DQEChargeur(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("Chargeur DQE")
        self.setMinimumSize(800, 600)
        self.setModal(False)
        
        self.setup_ui()
        
        if _logger:
            _logger.info("Interface DQE Chargeur initialisée")
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()
        
        title_label = QLabel("Chargeur DQE")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        version_label = QLabel("v3.1.0")
        version_label.setStyleSheet("color: #666; font-style: italic;")
        header_layout.addWidget(version_label)
        
        layout.addLayout(header_layout)
        
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)
        
        self.tab_widget = QTabWidget()
        
        self.pro_tab = DQEProTab()
        self.tab_widget.addTab(self.pro_tab, "DQE PRO")
        
        self.exe_tab = DQEExeTab()
        self.tab_widget.addTab(self.exe_tab, "DQE EXE")
        
        self.pgc_tab = DQEPGCTab()
        self.tab_widget.addTab(self.pgc_tab, "DQE PGC")
        
        layout.addWidget(self.tab_widget)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.close)
        
        help_button = QPushButton("Aide")
        help_button.clicked.connect(self.show_help)
        button_box.addButton(help_button, QDialogButtonBox.HelpRole)
        
        layout.addWidget(button_box)
        
        # Style par défaut Qt - pas de personnalisation
        pass
    
    def show_help(self):
        help_text = """
        <h2>Guide d'utilisation - Plugin DQE</h2>
        
        <h3>DQE PRO</h3>
        <ul>
            <li><b>SRO</b> : Code au format XXX/XXX/XXX/XXX</li>
            <li><b>Type</b> : Transport ou Distribution</li>
            <li><b>Usage</b> : Génération des quantitatifs projet</li>
        </ul>
        
        <h3>DQE EXE</h3>
        <ul>
            <li><b>SRO</b> : Code au format XXX/XXX/XXX/XXX</li>
            <li><b>Type</b> : Transport ou Distribution</li>
            <li><b>Usage</b> : Génération des quantitatifs exécution (projet + génie civil)</li>
        </ul>
        
        <h3>DQE PGC</h3>
        <ul>
            <li><b>SRO</b> : Code pour sélectionner les tronçons disponibles</li>
            <li><b>Tronçon</b> : Sélection du tronçon à traiter</li>
            <li><b>Mode gestionnaire</b> : Permet corrections manuelles des attributions</li>
            <li><b>Mode direct</b> : Traitement automatique sans intervention</li>
        </ul>
        
        <h3>Généralités</h3>
        <ul>
            <li><b>Excel</b> : Génération automatique avec templates spécialisés</li>
            <li><b>Couches QGIS</b> : Chargement organisé par catégories</li>
            <li><b>Validation</b> : Sauvegarde des résultats en base</li>
        </ul>
        """
        
        QMessageBox.information(self, "Aide DQE Chargeur", help_text)


def run_dqe_chargeur():
    dialog = DQEChargeur(iface.mainWindow() if iface else None)
    dialog.show()
    return dialog


__all__ = [
    'DQEChargeur', 'LayerManager', 'DatabaseOperations', 'ExcelManager',
    'run_dqe_chargeur'
]