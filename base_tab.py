"""
Base class for DQE tabs
=======================
Shared logic for DQE PRO, EXE, and PGC tabs.
"""

import time

from .compat import QThread, QTimer, QWidget, QApplication
from .dqe_utils import _crash_log


class BaseDQETab(QWidget):
    """Base class factoring out common DQE tab behaviour."""

    # Subclasses must set this for log messages (e.g. "PRO", "EXE", "PGC")
    TAB_LABEL = "DQE"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layers_loaded = []
        self.layer_group = None
        self._is_cancelled = False
        self.worker = None
        self.thread = None
        self.progress_timer = None
        self.current_progress = 0
        self.progress_increment = 1

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    def _cancel_post_processing(self):
        """Signale l'annulation pendant le post-traitement (chargement couches)"""
        self._is_cancelled = True

    def _cleanup_orphan_layers(self):
        """Supprime les couches QGIS chargees pendant l'operation en cours.

        Evite la boucle infinie de requetes QGIS sur des tables temporaires
        supprimees apres annulation.
        """
        from qgis.core import QgsProject
        from .dqe_utils import _logger

        _crash_log.step("cleanup_orphan_layers START", f"count={len(self.layers_loaded)}")
        project = QgsProject.instance()
        removed = 0
        for layer in list(self.layers_loaded):
            try:
                if layer is not None and project.mapLayer(layer.id()):
                    _crash_log.step("cleanup_orphan_layers", f"removing layer {layer.id()}")
                    project.removeMapLayer(layer.id())
                    removed += 1
            except RuntimeError:
                pass
        self.layers_loaded.clear()

        if self.layer_group is not None:
            try:
                _crash_log.step("cleanup_orphan_layers", "removing layer_group")
                root = project.layerTreeRoot()
                root.removeChildNode(self.layer_group)
            except RuntimeError:
                pass
            self.layer_group = None

        _crash_log.step("cleanup_orphan_layers END", f"removed={removed}")
        if removed and _logger:
            _logger.info(f"Nettoyage annulation: {removed} couches orphelines supprimees")

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------
    def _cleanup_thread(self):
        """Nettoie proprement le thread et le worker pour eviter les fuites memoire"""
        if hasattr(self, 'progress_timer') and self.progress_timer:
            self.progress_timer.stop()
            self.progress_timer.deleteLater()
            self.progress_timer = None
        if hasattr(self, 'thread') and self.thread:
            try:
                if hasattr(self, 'worker') and self.worker:
                    self.worker.cancel()
                self.thread.quit()
                if not self.thread.wait(10000):
                    from .dqe_utils import _logger
                    if _logger:
                        _logger.warning(f"Thread DQE {self.TAB_LABEL} ne repond pas apres 10s")
            except RuntimeError:
                pass  # Objet C++ deja supprime par deleteLater()
            self.thread = None
        if hasattr(self, 'worker') and self.worker:
            try:
                self.worker.deleteLater()
            except RuntimeError:
                pass
            self.worker = None

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------
    def smooth_progress_to(self, target_value, status):
        """Met a jour la progression vers une valeur cible sans bloquer l'UI"""
        if hasattr(self, 'current_progress'):
            self.current_progress = target_value
            self.progress_widget.update_progress(int(self.current_progress), status)
            QApplication.processEvents()

    def _setup_worker_thread(self, worker, on_finished_callback, operation_label=None):
        """Configure et demarre le worker/thread/timer de progression.

        Parameters
        ----------
        worker : QObject
            Worker instance (must have ``is_running``, ``progress_value``, ``cancel``, ``run``).
        on_finished_callback : callable
            Slot connected to the worker's ``finished`` signal.
        operation_label : str, optional
            Label shown in the progress bar. Defaults to ``TAB_LABEL``.
        """
        _crash_log.step(f"setup_worker_thread START", f"tab={self.TAB_LABEL} layers_loaded={len(self.layers_loaded)}")
        if self.layers_loaded:
            _crash_log.step("setup_worker_thread", "pre-cleanup orphan layers")
            self._cleanup_orphan_layers()
            _crash_log.step("setup_worker_thread", "post-cleanup orphan layers")

        label = operation_label or f"DQE {self.TAB_LABEL}"
        self.progress_widget.start_operation(label)
        self.worker = worker
        self.thread = QThread()
        self.progress_timer = QTimer()
        self.current_progress = 10
        self.progress_increment = 1

        tab_label = self.TAB_LABEL

        def update_smooth_progress():
            if hasattr(self, 'worker') and self.worker is not None and self.worker.is_running:
                target_progress = getattr(self.worker, 'progress_value', 10)

                if self.current_progress < target_progress:
                    self.current_progress = min(self.current_progress + self.progress_increment, target_progress)
                elif self.current_progress < 90:
                    self.current_progress += 0.5

                status = f"Traitement DQE {tab_label} en cours..."
                if self.current_progress < 20:
                    status = "Initialisation..."
                elif self.current_progress < 40:
                    status = "Connexion à la base..."
                elif self.current_progress < 85:
                    status = "Exécution de la requête..."
                else:
                    status = "Finalisation..."

                self.progress_widget.update_progress(int(self.current_progress), status)
            else:
                self.progress_timer.stop()

        self.progress_timer.timeout.connect(update_smooth_progress)
        self.progress_timer.start(100)
        _crash_log.step("setup_worker_thread", "moveToThread")
        self.worker.moveToThread(self.thread)
        self.worker.finished.connect(on_finished_callback)
        self._is_cancelled = False
        self.progress_widget.progress_cancelled.connect(self.worker.cancel)
        self.progress_widget.progress_cancelled.connect(self._cancel_post_processing)
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.thread.deleteLater)
        _crash_log.step("setup_worker_thread", "thread.start()")
        self.thread.start()
        _crash_log.step("setup_worker_thread END")

    # ------------------------------------------------------------------
    # Shared layer loading
    # ------------------------------------------------------------------
    def _load_categories_to_layers(self, categories, sro):
        """Load categorized task data into QGIS layers under self.layer_group.

        Parameters
        ----------
        categories : OrderedDict
            {category_name: [task_data, ...]} as built by _load_organized_layers.
        sro : str
            Current SRO identifier.

        Returns
        -------
        list
            List of created QgsVectorLayer instances.
        """
        from qgis.core import QgsProject, QgsApplication
        from qgis.utils import iface
        from .layer_manager import LayerManager
        from .dqe_utils import _logger

        _t0 = time.monotonic()
        created_layers = []
        for category_name, tasks in categories.items():
            if not tasks:
                continue
            if _logger:
                _logger.debug(f"Categorie: {category_name} ({len(tasks)} couches)")
            category_group = self.layer_group.addGroup(category_name)

            for i, task_data in enumerate(tasks):
                if self._is_cancelled:
                    if _logger:
                        _logger.info("Annulation detectee pendant le chargement des couches")
                    return created_layers
                try:
                    if _logger:
                        _logger.debug(f"Chargement de {task_data['layer_name']} ({i+1}/{len(tasks)})")
                    QgsApplication.processEvents()

                    layer = LayerManager.load_layer_direct(
                        task_data['layer_name'],
                        task_data['ids_str'],
                        task_data['table_name'],
                        sro
                    )

                    if layer and layer.isValid():
                        QgsProject.instance().addMapLayer(layer, False)
                        category_group.addLayer(layer)
                        created_layers.append(layer)
                        self.layers_loaded.append(layer)
                        if iface:
                            iface.mainWindow().statusBar().showMessage(f"Charge {len(created_layers)} couches")
                    else:
                        if _logger:
                            _logger.warning(f"Echec creation couche: {task_data['layer_name']}")

                except Exception as e:
                    if _logger:
                        _logger.error(f"Erreur chargement {task_data['layer_name']}: {str(e)}")

        elapsed_ms = int((time.monotonic() - _t0) * 1000)
        _crash_log.step("_load_categories_to_layers END", f"n_items={len(created_layers)} elapsed_ms={elapsed_ms}")
        if _logger:
            _logger.info(f"Couches standard creees: {len(created_layers)} elapsed_ms={elapsed_ms}")
        return created_layers

    # ------------------------------------------------------------------
    # Shared validation data builder
    # ------------------------------------------------------------------
    @staticmethod
    def _build_dqe_data(results):
        """Build the JSON-serializable list from raw DQE results.

        Returns
        -------
        list[dict]
            Each dict has keys: designation, quantite, unite, ids.
        """
        dqe_data = []
        for result in results:
            designation = result.get("Désignation") or result.get("designation") or ""
            quantite = result.get("Quantité") or result.get("quantite")
            unite = result.get("Unité") or result.get("unite") or ""
            ids = result.get("ids") or result.get("Ids") or ""

            try:
                quantite_num = float(quantite) if quantite is not None else 0
            except (ValueError, TypeError):
                quantite_num = 0

            dqe_data.append({
                'designation': designation,
                'quantite': quantite_num,
                'unite': unite,
                'ids': str(ids) if ids else None
            })
        return dqe_data
