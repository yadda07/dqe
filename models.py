"""
DQE Models
======================================================
Classes de données et énumérations pour le plugin DQE Chargeur
"""

from typing import List, Dict
from dataclasses import dataclass, field
from enum import Enum, auto


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
    redevance_data: List[Dict] = field(default_factory=list)  # Données redevance pour PGC
    
    @property
    def ids_string(self) -> str:
        return ",".join(str(id_) for id_ in self.ids)
