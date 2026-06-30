"""
Designation Classifier
======================
Classifies DQE result designations into layer categories.
Shared logic between PRO and EXE tabs.
"""

from collections import OrderedDict


# Category definitions per operation type
_BASE_CATEGORIES = [
    "Prises", "GC/Infrastructures", "Câble aérien", "Câble sout",
    "BPE facade", "BPE aérien", "BPE sout",
    "PA aérien", "PA souterrain", "PBO", "SRO", "Autres"
]

_EXE_CATEGORIES = [
    "Prises", "GC/Infrastructures", "Câble aérien", "Câble sout",
    "BPE facade", "BPE aérien", "BPE sout",
    "PA aérien", "PA souterrain", "PBO",
    "Poteaux", "Travaux Génie civil", "SRO", "Autres"
]


class DesignationClassifier:
    """Classifies a designation string into a layer category."""

    @staticmethod
    def get_categories(operation_type: str) -> OrderedDict:
        """Returns an empty OrderedDict of categories for the given type."""
        cats = _EXE_CATEGORIES if operation_type == "EXE" else _BASE_CATEGORIES
        return OrderedDict((c, []) for c in cats)

    @staticmethod
    def classify(designation: str, operation_type: str, p_type: str = None) -> str:
        """Return the category name for *designation*, or None to skip it.

        Parameters
        ----------
        designation : str
            The raw designation string from the SQL result.
        operation_type : str
            "PRO" or "EXE".
        p_type : str, optional
            "T" (Transport) or "D" (Distribution).

        Returns
        -------
        str or None
            Category name, or ``None`` if the designation should be skipped.
        """
        dl = designation.lower()

        # EXE-specific categories (checked first for priority)
        if operation_type == "EXE":
            if any(x in dl for x in ["pose poteau", "poteau rauv", "ft à"]):
                return "Poteaux"
            if any(x in dl for x in [
                "tranchée", "micro tranchée", "forage dirigé",
                "encorbellement", "pose de chambre", "pvc ", "pehd"
            ]):
                return "Travaux Génie civil"

        # Common classification rules
        if any(x in dl for x in ["prise", "dtr", "rad", "nbre de prises"]):
            return "Prises"
        if "sro" in dl:
            return "SRO"
        if "bpe" in dl or "f&p bpe" in dl:
            if "façade" in dl:
                return "BPE facade"
            if "aérien" in dl:
                return "BPE aérien"
            if "conduite" in dl or "sout" in dl:
                return "BPE sout"
            return "BPE facade"
        if ("pa " in dl or "f&p pa" in dl) and "pbo" not in dl:
            if "aérien" in dl:
                return "PA aérien"
            if "conduite" in dl or "souterrain" in dl:
                return "PA souterrain"
            return "PA aérien"
        if "pbo" in dl or "f&p de pbo" in dl:
            return "PBO"
        if any(x in dl for x in ["câble", "cable", "fibre", "fo ", "fourniture et pose de câble"]):
            # Distribution cables replaced by cut cables
            if p_type == 'D':
                if (any(x in dl for x in ["câble optique", "câble de"]) and
                        any(x in dl for x in ["aérien", "façade", "conduite"]) and
                        any(x in dl for x in ["fo en", "fo "])):
                    return None  # Skip - replaced by cut cables
            if "aérien" in dl:
                return "Câble aérien"
            if "conduite" in dl or "sout" in dl:
                return "Câble sout"
            return "Câble sout"
        if any(x in dl for x in ["gc", "génie civil", "cheminement", "lineaire", "infra"]):
            return "GC/Infrastructures"

        return "Autres"
