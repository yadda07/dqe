"""
DQE Utils - Version CORRIGÉE
==========================================

Auteur: DEVTEAM NGE
"""

import os
import json
import logging
import functools
import re
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import DictCursor
from psycopg2.pool import SimpleConnectionPool

from qgis.core import QgsSettings, QgsDataSourceUri, QgsMessageLog, Qgis, QgsApplication, QgsAuthMethodConfig
from qgis.utils import iface


# Constantes messages d'erreur centralisés
class ErrorMessages:
    DB_PARAMS_UNAVAILABLE = "Paramètres DB non disponibles"
    NO_SRO_SELECTED = "Veuillez sélectionner un SRO"
    NO_DQE_RESULTS = "Aucun résultat DQE trouvé"
    LAYER_LOAD_ERROR = "Erreur chargement couche"
    NO_LAYERS_TO_VALIDATE = "Aucune couche à valider"
    VALIDATION_ERROR = "Erreur lors de la validation"
    EXCEL_GENERATION_ERROR = "Erreur génération Excel"


@dataclass
class DatabaseConfig:
    """Configuration de base de données simple et efficace"""
    host: str
    port: str
    database: str
    user: str
    password: str
    
    def __post_init__(self):
        if not all([self.host, self.port, self.database, self.user]):
            raise ValueError("Tous les champs DB sont requis")
        
        try:
            port_int = int(self.port)
            if not (1 <= port_int <= 65535):
                raise ValueError("Port invalide")
        except ValueError:
            raise ValueError("Port doit être un entier valide")
    
    @property
    def connection_string(self) -> str:
        return (f"host={self.host} port={self.port} dbname={self.database} "
                f"user={self.user} password={self.password}")
    
    def to_dict(self) -> Dict[str, str]:
        return {
            'host': self.host, 'port': self.port, 'database': self.database,
            'user': self.user, 'password': self.password
        }


class SimpleLogger:
    """Logger ULTRA SIMPLE - évite tous les problèmes de stream"""
    
    def __init__(self):
        self.use_qgis = True
        
    def _log(self, level: str, message: str):
        """Log simple et sécurisé"""
        try:
            clean_msg = str(message).replace("/", "-").replace("\\", "-")
            
            if self.use_qgis and hasattr(QgsMessageLog, 'logMessage'):
                qgis_level = Qgis.Info
                if level == 'error':
                    qgis_level = Qgis.Critical
                elif level == 'warning':
                    qgis_level = Qgis.Warning
                
                QgsMessageLog.logMessage(f"[DQE] {clean_msg}", 'DQE Plugin', qgis_level)
            else:
                print(f"[DQE {level.upper()}] {clean_msg}")
        except:
            print(f"[DQE {level.upper()}] {message}")
    
    def debug(self, message: str, **kwargs):
        self._log('debug', message)
    
    def info(self, message: str, **kwargs):
        self._log('info', message)
    
    def warning(self, message: str, **kwargs):
        self._log('warning', message)
    
    def error(self, message: str, exception: Optional[Exception] = None, **kwargs):
        msg = f"{message}"
        if exception:
            msg += f" - Exception: {str(exception)}"
        self._log('error', msg)
    
    def critical(self, message: str, exception: Optional[Exception] = None, **kwargs):
        msg = f"{message}"
        if exception:
            msg += f" - Exception: {str(exception)}"
        self._log('error', msg)


class DatabaseManager:
    """Gestionnaire DB SIMPLE et EFFICACE"""
    
    def __init__(self):
        self.logger = SimpleLogger()
        self._config = None
        self._connection_pool = None
    
    def initialize(self, config: DatabaseConfig, pool_size: int = 3):
        """Initialise avec pool réduit"""
        self._config = config
        try:
            conn_params = config.to_dict()
            conn_params['connect_timeout'] = 10
            self._connection_pool = SimpleConnectionPool(
                1, pool_size, **conn_params
            )
            self.logger.info(f"Pool DB initialisé ({pool_size} connexions)")
        except Exception as e:
            self.logger.error("Erreur init pool DB", exception=e)
            raise
    
    @contextmanager
    def get_connection(self):
        """Context manager simple pour connexions"""
        if not self._connection_pool:
            raise RuntimeError("Pool non initialisé")
        
        connection = None
        try:
            connection = self._connection_pool.getconn()
            yield connection
        except Exception as e:
            if connection:
                connection.rollback()
            self.logger.error("Erreur connexion", exception=e)
            raise
        finally:
            if connection:
                self._connection_pool.putconn(connection)
    
    @contextmanager
    def get_cursor(self):
        """Context manager simple pour curseurs"""
        with self.get_connection() as conn:
            try:
                with conn.cursor(cursor_factory=DictCursor) as cursor:
                    yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise
    
    def execute_query(self, query: str, params: tuple = None) -> Any:
        """Exécute une requête simple"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(f"Erreur requête: {query[:100]}...", exception=e)
            raise
    
    def get_qgis_uri(self) -> QgsDataSourceUri:
        """URI QGIS simple"""
        if not self._config:
            raise RuntimeError("Config DB manquante")
        
        uri = QgsDataSourceUri()
        uri.setConnection(
            self._config.host, self._config.port, self._config.database,
            self._config.user, self._config.password
        )
        return uri

    @property
    def is_connected(self) -> bool:
        """Indique si le pool de connexions est actif"""
        return self._connection_pool is not None

    @property
    def config(self):
        """Retourne la configuration DB courante"""
        return self._config


class ConfigurationManager:
    """Gestionnaire config SIMPLIFIÉ"""
    
    def __init__(self):
        self.logger = SimpleLogger()
    
    # Criteres de recherche pour la connexion cible
    TARGET_HOST = "10.241.228.107"
    TARGET_DATABASE = "AUVERGNE"
    TARGET_CONNECTION_NAME = "AUVERGNE"
    
    def get_db_config(self) -> DatabaseConfig:
        """Recupere config DB avec recherche ciblee AUVERGNE"""
        
        self.logger.info("=== DEBUT RECHERCHE CONFIGURATION DB ===")
        
        # Etape 1: Chercher connexion QGIS avec DB=AUVERGNE + host cible
        self.logger.info("Etape 1: Recherche connexion QGIS (DB=AUVERGNE, host=10.241.228.107)")
        try:
            config = self._find_target_qgis_connection()
            if config:
                self.logger.info("Config trouvee depuis connexion QGIS ciblee")
                return config
        except Exception as e:
            self.logger.warning(f"Echec recherche QGIS ciblee: {e}")
        
        # Etape 2: Fichier JSON local
        self.logger.info("Etape 2: Recherche fichier JSON")
        try:
            config = self._get_json_config()
            if config:
                self.logger.info("Config depuis JSON")
                return config
        except Exception as e:
            self.logger.warning(f"Echec config JSON: {e}")
        
        # Etape 3: Variables d'environnement
        self.logger.info("Etape 3: Recherche variables ENV")
        try:
            config = self._get_env_config()
            if config:
                self.logger.info("Config depuis ENV")
                return config
        except Exception as e:
            self.logger.warning(f"Echec config ENV: {e}")
        
        # Etape 4: Dialog de connexion manuelle
        self.logger.info("Etape 4: Affichage interface utilisateur")
        try:
            config = self._get_user_connection()
            if config:
                self.logger.info("Config depuis interface utilisateur")
                return config
        except Exception as e:
            self.logger.error(f"Erreur lors de l'affichage de l'interface de connexion: {e}")
        
        self.logger.error("=== AUCUNE CONFIGURATION TROUVEE ===")
        raise RuntimeError("Aucune config DB trouvee")
    
    def _read_qgis_connection(self, conn_name: str) -> Optional[dict]:
        """Lit les parametres d'une connexion QGIS PostgreSQL par son nom.
        Gere le stockage direct (username/password) et le systeme authcfg."""
        try:
            settings = QgsSettings()
            settings.beginGroup(f"PostgreSQL/connections/{conn_name}")
            config_data = {
                'host': settings.value("host", ""),
                'port': settings.value("port", "5432"),
                'database': settings.value("database", ""),
                'user': settings.value("username", ""),
                'password': settings.value("password", "")
            }
            authcfg = settings.value("authcfg", "")
            settings.endGroup()
            
            has_user = bool(config_data['user'])
            has_pass = bool(config_data['password'])
            has_auth = bool(authcfg)
            self.logger.info(
                f"Connexion '{conn_name}': host={config_data['host']}, "
                f"db={config_data['database']}, "
                f"user={'oui' if has_user else 'non'}, "
                f"pass={'oui' if has_pass else 'non'}, "
                f"authcfg={'oui' if has_auth else 'non'}"
            )
            
            # Si credentials manquants et authcfg present, decoder via auth manager
            if authcfg and (not has_user or not has_pass):
                try:
                    auth_mgr = QgsApplication.authManager()
                    auth_cfg_obj = QgsAuthMethodConfig()
                    if auth_mgr.loadAuthenticationConfig(authcfg, auth_cfg_obj, True):
                        config_map = auth_cfg_obj.configMap()
                        if not config_data['user']:
                            config_data['user'] = config_map.get('username', '')
                        if not config_data['password']:
                            config_data['password'] = config_map.get('password', '')
                        self.logger.info(f"Credentials recuperes via authcfg pour '{conn_name}'")
                    else:
                        self.logger.warning(f"Echec chargement authcfg '{authcfg}' pour '{conn_name}'")
                except Exception as e:
                    self.logger.warning(f"Erreur lecture authcfg pour '{conn_name}': {e}")
            
            return config_data
        except Exception as e:
            self.logger.warning(f"Erreur lecture connexion '{conn_name}': {e}")
            return None
    
    def _test_connection(self, config_data: dict) -> Optional[DatabaseConfig]:
        """Teste une connexion et retourne un DatabaseConfig si valide."""
        if not config_data:
            self.logger.warning("Test connexion: config_data vide")
            return None
        missing = [k for k in ('host', 'database', 'user', 'password') if not config_data.get(k)]
        if missing:
            self.logger.warning(f"Test connexion: champs manquants: {missing}")
            return None
        try:
            test_config = DatabaseConfig(**config_data)
            conn_params = test_config.to_dict()
            conn_params['connect_timeout'] = 5
            conn_test = psycopg2.connect(**conn_params)
            conn_test.close()
            return test_config
        except Exception as e:
            self.logger.warning(f"Test connexion echec ({config_data.get('host')}/{config_data.get('database')}): {e}")
            return None
    
    def _find_target_qgis_connection(self) -> Optional[DatabaseConfig]:
        """Recherche ciblee: DB=AUVERGNE + host cible, puis nom connexion AUVERGNE + host cible."""
        try:
            settings = QgsSettings()
            settings.beginGroup("PostgreSQL/connections")
            connections = settings.childGroups()
            settings.endGroup()
            
            self.logger.info(f"Connexions QGIS disponibles: {connections}")
            
            # Passe 1: Chercher par DB=AUVERGNE ET host=10.241.228.107
            for conn_name in connections:
                config_data = self._read_qgis_connection(conn_name)
                if not config_data:
                    continue
                db_match = config_data.get('database', '').upper() == self.TARGET_DATABASE
                host_match = config_data.get('host', '') == self.TARGET_HOST
                if db_match and host_match:
                    self.logger.info(f"Connexion ciblee trouvee: '{conn_name}' (DB={self.TARGET_DATABASE}, host={self.TARGET_HOST})")
                    result = self._test_connection(config_data)
                    if result:
                        return result
            
            # Passe 2: Chercher par nom AUVERGNE (insensible casse) ET host cible
            for conn_name in connections:
                if conn_name.upper() != self.TARGET_CONNECTION_NAME:
                    continue
                config_data = self._read_qgis_connection(conn_name)
                if not config_data:
                    continue
                host_match = config_data.get('host', '') == self.TARGET_HOST
                if host_match:
                    self.logger.info(f"Connexion AUVERGNE trouvee: '{conn_name}' (host={self.TARGET_HOST})")
                    result = self._test_connection(config_data)
                    if result:
                        return result
            
            self.logger.info("Aucune connexion QGIS ciblee trouvee")
            return None
            
        except Exception as e:
            self.logger.error(f"Erreur recherche connexions QGIS: {e}")
            return None
    
    def _get_json_config(self) -> Optional[DatabaseConfig]:
        """Config depuis JSON"""
        config_file = os.path.join(os.path.dirname(__file__), 'db_config.json')
        if not os.path.exists(config_file):
            return None
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            return DatabaseConfig(**config_data)
        except Exception:
            return None
    
    def _get_env_config(self) -> Optional[DatabaseConfig]:
        """Config depuis ENV"""
        env_vars = {
            'host': os.getenv('DQE_DB_HOST'),
            'port': os.getenv('DQE_DB_PORT', '5432'),
            'database': os.getenv('DQE_DB_NAME'),
            'user': os.getenv('DQE_DB_USER'),
            'password': os.getenv('DQE_DB_PASSWORD')
        }
        
        if all([env_vars['host'], env_vars['database'], env_vars['user'], env_vars['password']]):
            return DatabaseConfig(**env_vars)
        return None
    
    def _get_user_connection(self):
        """Interface utilisateur pour configurer une connexion manuelle"""
        try:
            from .connection_dialog import ConnectionDialog
            from qgis.utils import iface
            dialog = ConnectionDialog(parent=iface.mainWindow() if iface else None)
            
            if dialog.exec_() == dialog.Accepted:
                config = dialog.get_config()
                if config:
                    self.logger.info("Configuration de connexion obtenue via interface utilisateur")
                    return config
                else:
                    self.logger.error("Aucune configuration valide obtenue du dialog")
            else:
                self.logger.info("Dialog de connexion annulé par l'utilisateur")
            
            return None
            
        except Exception as e:
            self.logger.error(f"Erreur lors de l'affichage de l'interface de connexion: {e}")
            raise RuntimeError(f"Erreur interface utilisateur: {e}")


class ValidationUtils:
    """Validateur ROBUSTE"""
    
    def __init__(self, db_manager=None):
        self.logger = SimpleLogger()
        self._db_manager_ref = db_manager
    
    @property
    def db_manager(self):
        """Retourne le db_manager injecte ou le singleton global"""
        if self._db_manager_ref is not None:
            return self._db_manager_ref
        return _db_manager
    
    def validate_sro_exists(self, sro: str) -> Tuple[bool, str]:
        """Valide SRO de manière robuste"""
        if not sro or not sro.strip():
            return False, "SRO vide"
        
        sro = sro.strip()
        if not self.db_manager or not self.db_manager._connection_pool:
            if self._validate_sro_format(sro):
                return True, "SRO accepté (format valide - base non connectée)"
            else:
                return False, f"Format SRO invalide: {sro}"
        
        try:
            query = "SELECT COUNT(*) FROM rip_avg_nge.za_sro WHERE sro = %s"
            result = self.db_manager.execute_query(query, (sro,))
            count = result[0][0] if result else 0
            
            if count == 0:
                return False, f"SRO '{sro}' non trouvé en base"
            
            return True, "SRO validé en base"
            
        except Exception as e:
            error_msg = str(e)
            if any(x in error_msg.lower() for x in ["pool", "connection", "timeout", "connexion"]):
                if self._validate_sro_format(sro):
                    return True, f"SRO accepté (format valide - erreur DB: {error_msg[:30]}...)"
                else:
                    return False, f"Format SRO invalide: {sro}"
            else:
                return False, f"Erreur validation: {error_msg[:50]}..."
    
    def _validate_sro_format(self, sro: str) -> bool:
        """Valide le format SRO sans base de données"""
        patterns = [
            r'^\d+/[A-Za-z0-9]+/[A-Za-z0-9]+/\d+$',  # 63437/G2B/PMZ/74316
            r'^\d+/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+$',  # Format alternatif
            r'^[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+/[A-Za-z0-9]+$'  # Format général
        ]
        
        for pattern in patterns:
            if re.match(pattern, sro):
                return True
        
        return False
    
    def get_sro_list(self, pattern: str = "") -> List[str]:
        """Retourne liste des SRO avec pattern optionnel"""
        try:
            if pattern:
                query = "SELECT DISTINCT sro FROM rip_avg_nge.za_sro WHERE sro ILIKE %s ORDER BY sro LIMIT 50"
                result = self.db_manager.execute_query(query, (f"%{pattern}%",))
            else:
                query = "SELECT DISTINCT sro FROM rip_avg_nge.za_sro ORDER BY sro LIMIT 100"
                result = self.db_manager.execute_query(query)
            
            return [row[0] for row in result if row[0]]
        except Exception as e:
            self.logger.error("Erreur récupération SRO", exception=e)
            return []


class FileUtils:
    """Utilitaires pour fichiers"""
    
    @staticmethod
    def format_filename_safe(filename: str) -> str:
        """Formate un nom de fichier en sécurisant les caractères"""
        return filename.replace('/', '_').replace('\\', '_').replace(' ', '_')
    
    TEMPLATE_FILES = {
        'PRO': 'template_dqe_pro.xlsx',
        'EXE': 'template_dqe_exe.xlsx',
        'PGC': 'template_dqe_pgc.xlsx'
    }
    
    @staticmethod
    def get_template_path(operation_type: str = 'PRO') -> str:
        """Retourne le chemin du template Excel selon le type d'operation (PRO, EXE, PGC)"""
        base_type = operation_type.upper().split('_')[0]
        template_name = FileUtils.TEMPLATE_FILES.get(base_type, 'template_dqe_pro.xlsx')
        return os.path.join(os.path.dirname(__file__), 'files', template_name)


def initialize_dqe_system(pool_size: int = 3) -> bool:
    """Initialise système DQE SIMPLE"""
    logger = SimpleLogger()
    
    try:
        config_manager = ConfigurationManager()
        db_config = config_manager.get_db_config()
        
        global _db_manager, _config_manager, _validator
        _db_manager.initialize(db_config, pool_size)
        
        logger.info("Système DQE initialisé")
        return True
        
    except Exception as e:
        logger.error("Erreur init système DQE", exception=e)
        return False


def cleanup_dqe_system():
    """Nettoie système DQE"""
    logger = SimpleLogger()
    try:
        global _db_manager
        if _db_manager and _db_manager._connection_pool:
            _db_manager._connection_pool.closeall()
            _db_manager._connection_pool = None
            logger.info("Pool de connexions DB fermé")
        logger.info("Système DQE nettoyé")
    except Exception as e:
        logger.error("Erreur nettoyage", exception=e)


def retry_on_db_error(max_retries: int = 2):
    """Retry simple pour DB"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (psycopg2.OperationalError, psycopg2.InterfaceError):
                    if attempt < max_retries - 1:
                        continue
                    raise
                except Exception:
                    raise
        return wrapper
    return decorator


def log_execution_time(func):
    """Log temps d'exécution simple"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import time
        start = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start
            SimpleLogger().debug(f"{func.__name__} - {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            SimpleLogger().error(f"{func.__name__} échec après {duration:.2f}s", exception=e)
            raise
    return wrapper
class QtCompatibility:
    """Utilitaires pour assurer la compatibilité entre toutes les versions de Qt/PyQt5"""
    
    @staticmethod
    def set_rich_text_format(message_box):
        """Définit le format RichText de manière compatible avec toutes les versions Qt"""
        try:
            from PyQt5.QtCore import Qt
            message_box.setTextFormat(Qt.RichText)
            return True
        except (AttributeError, ImportError):
            try:
                from qgis.PyQt.QtCore import Qt
                message_box.setTextFormat(Qt.RichText)
                return True
            except (AttributeError, ImportError):
                try:
                    message_box.setTextFormat(1)  # RichText = 1 dans Qt
                    return True
                except:
                    return False
    
    @staticmethod
    def get_message_box_accepted():
        """Retourne la constante QMessageBox.Accepted de manière compatible"""
        try:
            from PyQt5.QtWidgets import QMessageBox
            return QMessageBox.Accepted
        except (AttributeError, ImportError):
            try:
                from qgis.PyQt.QtWidgets import QMessageBox
                return QMessageBox.Accepted
            except (AttributeError, ImportError):
                return 1  # QMessageBox.Accepted = 1
_db_manager = DatabaseManager()
_config_manager = ConfigurationManager()
_validator = ValidationUtils()
_logger = SimpleLogger()
__all__ = [
    'DatabaseManager', 'ConfigurationManager', 'ValidationUtils', 'SimpleLogger',
    'DatabaseConfig', 'FileUtils', 'QtCompatibility', 'initialize_dqe_system', 'cleanup_dqe_system',
    'retry_on_db_error', 'log_execution_time',
    '_db_manager', '_config_manager', '_validator', '_logger'
]