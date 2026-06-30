"""
DQE Chargeur - Couche de compatibilite Qt5 (QGIS 3.x) / Qt6 (QGIS 4.x)
=========================================================================

Point unique d'import Qt pour tout le plugin.
Aucun autre fichier du plugin ne doit importer directement depuis PyQt5 ou PyQt6.

Utilise le shim qgis.PyQt qui redirige vers la bonne version automatiquement.
"""

import sys

# ---------------------------------------------------------------------------
# Detection de version
# ---------------------------------------------------------------------------
_QT_VERSION = 6 if "PyQt6" in sys.modules else 5

try:
    from qgis.core import Qgis
    _QGIS_VERSION = Qgis.QGIS_VERSION if hasattr(Qgis, "QGIS_VERSION") else "inconnue"
except Exception:
    _QGIS_VERSION = "inconnue"

# ---------------------------------------------------------------------------
# QtCore
# ---------------------------------------------------------------------------
from qgis.PyQt.QtCore import (
    Qt,
    QObject,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
    QStringListModel,
)

# QVariant : present dans PyQt5, absent dans PyQt6 pur.
# qgis.PyQt le re-exporte sur les deux versions.
try:
    from qgis.PyQt.QtCore import QVariant
except ImportError:
    # Fallback : fournir un stub minimal pour QgsField
    class _QVariantStub:
        Int = int
        String = str
        Double = float
        Bool = bool
        LongLong = int
        Invalid = type(None)
    QVariant = _QVariantStub  # type: ignore[misc,assignment]

# ---------------------------------------------------------------------------
# QtWidgets
# ---------------------------------------------------------------------------
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# QtGui
# ---------------------------------------------------------------------------
from qgis.PyQt.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
)

# ---------------------------------------------------------------------------
# Qgis message levels (scope change entre 3.x et 4.x)
# ---------------------------------------------------------------------------
try:
    QGIS_INFO = Qgis.MessageLevel.Info
    QGIS_WARNING = Qgis.MessageLevel.Warning
    QGIS_CRITICAL = Qgis.MessageLevel.Critical
    QGIS_SUCCESS = Qgis.MessageLevel.Success
except AttributeError:
    QGIS_INFO = Qgis.Info
    QGIS_WARNING = Qgis.Warning
    QGIS_CRITICAL = Qgis.Critical
    QGIS_SUCCESS = Qgis.Success


# ---------------------------------------------------------------------------
# Constantes enum compatibles Qt5 (plat) / Qt6 (scope)
# Chaque constante est resolue dynamiquement avec fallback.
# ---------------------------------------------------------------------------

def _enum(obj, *names):
    """Resout un enum Qt en essayant plusieurs chemins d'acces.
    
    Chaque nom est tente dans l'ordre. Un nom peut contenir des points
    pour les enums imbriques (ex: 'Shape.HLine'). Le dernier argument
    peut etre un int comme fallback ultime (valeur numerique brute).
    """
    for name in names:
        if isinstance(name, int):
            return name
        try:
            result = obj
            for part in name.split("."):
                result = getattr(result, part)
            return result
        except AttributeError:
            continue
    raise AttributeError(f"Aucun attribut trouve sur {obj}: {names}")

# QFrame : HLine=4, Sunken=0x0030
FRAME_HLINE = _enum(QFrame, "Shape.HLine", "HLine", 4)
FRAME_SUNKEN = _enum(QFrame, "Shadow.Sunken", "Sunken", 0x0030)

# QLineEdit : Password=2
LINEEDIT_PASSWORD = _enum(QLineEdit, "EchoMode.Password", "Password", 2)

# QCompleter : PopupCompletion=0
COMPLETER_POPUP = _enum(QCompleter, "CompletionMode.PopupCompletion", "PopupCompletion", 0)

# QHeaderView : Stretch=1
HEADERVIEW_STRETCH = _enum(QHeaderView, "ResizeMode.Stretch", "Stretch", 1)

# QTableWidget / QAbstractItemView : SelectRows=1, SingleSelection=1
try:
    from qgis.PyQt.QtWidgets import QAbstractItemView
    TABLE_SELECT_ROWS = _enum(QAbstractItemView, "SelectionBehavior.SelectRows", "SelectRows", 1)
    TABLE_SINGLE_SELECTION = _enum(QAbstractItemView, "SelectionMode.SingleSelection", "SingleSelection", 1)
except ImportError:
    TABLE_SELECT_ROWS = 1
    TABLE_SINGLE_SELECTION = 1

# QDialogButtonBox : Close=0x00200000, HelpRole=4
BUTTONBOX_CLOSE = _enum(QDialogButtonBox, "StandardButton.Close", "Close", 0x00200000)
BUTTONBOX_HELPROLE = _enum(QDialogButtonBox, "ButtonRole.HelpRole", "HelpRole", 4)

# QMessageBox roles : AcceptRole=0, RejectRole=1
MSGBOX_ACCEPTROLE = _enum(QMessageBox, "ButtonRole.AcceptRole", "AcceptRole", 0)
MSGBOX_REJECTROLE = _enum(QMessageBox, "ButtonRole.RejectRole", "RejectRole", 1)

# QMessageBox standard buttons : Yes=0x00004000, No=0x00010000
MSGBOX_YES = _enum(QMessageBox, "StandardButton.Yes", "Yes", 0x00004000)
MSGBOX_NO = _enum(QMessageBox, "StandardButton.No", "No", 0x00010000)

# QDialog codes : Accepted=1, Rejected=0
DIALOG_ACCEPTED = _enum(QDialog, "DialogCode.Accepted", "Accepted", 1)
DIALOG_REJECTED = _enum(QDialog, "DialogCode.Rejected", "Rejected", 0)


# ---------------------------------------------------------------------------
# Types de champ QgsField : QMetaType.Type (QGIS >= 3.38) sinon QVariant.Type
# ---------------------------------------------------------------------------
# QgsField(name, QVariant.Type) est deprecated depuis QGIS 3.38.
# QgsField(name, QMetaType.Type) n'existe QUE depuis QGIS 3.38.
# Basculer naivement vers QMetaType casserait 3.28 -> 3.36.
# On choisit donc dynamiquement selon la version pour couvrir 3.28 -> 4.99.
# Source : https://api.qgis.org/api/classQgsField.html (deprecated 3.38)
def _qgis_version_int():
    """Version QGIS sous forme entiere (ex: 3.38.0 -> 33800), 0 si inconnue."""
    try:
        return int(Qgis.QGIS_VERSION_INT)
    except Exception:
        try:
            return int(Qgis.versionInt())
        except Exception:
            return 0


_USE_QMETATYPE = _qgis_version_int() >= 33800
_QMETATYPE = None
if _USE_QMETATYPE:
    try:
        from qgis.PyQt.QtCore import QMetaType as _QMETATYPE
    except ImportError:
        _QMETATYPE = None
        _USE_QMETATYPE = False

# semantique -> (chemins QMetaType.Type, attributs QVariant.Type)
_FIELD_TYPE_SPECS = {
    "int":      (("Type.Int", "Int"),           ("Int",)),
    "integer":  (("Type.Int", "Int"),           ("Int",)),
    "string":   (("Type.QString", "QString"),   ("String",)),
    "text":     (("Type.QString", "QString"),   ("String",)),
    "double":   (("Type.Double", "Double"),     ("Double",)),
    "bool":     (("Type.Bool", "Bool"),         ("Bool",)),
    "longlong": (("Type.LongLong", "LongLong"), ("LongLong",)),
}


def field_type(semantic):
    """Retourne le type a passer a QgsField(name, type) pour la version courante.

    semantic : 'int' | 'string' | 'double' | 'bool' | 'longlong' (insensible casse).
    QGIS >= 3.38 : QMetaType.Type.X (constructeur non deprecated).
    QGIS <  3.38 : QVariant.X (seul constructeur disponible).
    """
    spec = _FIELD_TYPE_SPECS.get(str(semantic).lower())
    if spec is None:
        raise ValueError(f"Type de champ inconnu: {semantic}")
    qmeta_names, qvar_names = spec
    if _USE_QMETATYPE and _QMETATYPE is not None:
        return _enum(_QMETATYPE, *qmeta_names)
    return _enum(QVariant, *qvar_names)

# Qt namespace
QT_CASE_INSENSITIVE = _enum(Qt, "CaseSensitivity.CaseInsensitive", "CaseInsensitive", 0)
QT_MATCH_CONTAINS = _enum(Qt, "MatchFlag.MatchContains", "MatchContains", 1)
QT_RICHTEXT = _enum(Qt, "TextFormat.RichText", "RichText", 1)
QT_WAIT_CURSOR = _enum(Qt, "CursorShape.WaitCursor", "WaitCursor", 3)
QT_VERTICAL = _enum(Qt, "Orientation.Vertical", "Vertical", 2)


# ---------------------------------------------------------------------------
# exec_dialog : compatibilite exec_() (Qt5) / exec() (Qt6)
# ---------------------------------------------------------------------------
def exec_dialog(dialog):
    """Execute un QDialog de maniere compatible Qt5 et Qt6.

    PyQt5 utilise exec_() (exec est un mot-cle Python 2).
    PyQt6 supprime exec_() et utilise exec().
    """
    if hasattr(dialog, "exec"):
        return dialog.exec()
    return dialog.exec_()


# ---------------------------------------------------------------------------
# Log de demarrage
# ---------------------------------------------------------------------------
print(f"[DQE] Qt{_QT_VERSION}, QGIS {_QGIS_VERSION}")
