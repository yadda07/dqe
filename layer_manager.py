"""
DQE Layer Manager
======================================================
Gestion des couches QGIS pour le plugin DQE Chargeur
"""

import time
import uuid
from datetime import datetime
from typing import List, Optional

import re
import psycopg2
from psycopg2 import sql
from qgis.core import (
    QgsDataSourceUri, QgsProject, QgsVectorLayer, QgsField, QgsFields, QgsFeature, QgsGeometry
)

from .database_operations import DatabaseOperations

try:
    from .dqe_utils import _db_manager, _logger, _crash_log
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = None
    MODULES_AVAILABLE = False
    from .dqe_utils import _crash_log


class LayerManager:
    _temp_tables_created = []

    @classmethod
    def cleanup_temp_tables(cls):
        """Supprime toutes les tables temporaires creees pendant la session.

        Retire d'abord les couches QGIS referencant chaque table pour eviter
        la boucle infinie de requetes QGIS sur des tables supprimees.
        """
        if not cls._temp_tables_created:
            return
        try:
            from qgis.core import QgsProject
            from .database_operations import DatabaseOperations

            project = QgsProject.instance()
            removed_layers = 0
            for table_name in cls._temp_tables_created:
                qualified = f"temporaire.{table_name}"
                for layer in list(project.mapLayers().values()):
                    try:
                        if qualified in layer.source():
                            project.removeMapLayer(layer.id())
                            removed_layers += 1
                    except RuntimeError:
                        pass
            if removed_layers:
                from .dqe_utils import _logger
                if _logger:
                    _logger.info(
                        f"cleanup_temp_tables: {removed_layers} couches QGIS "
                        f"retirees avant DROP, tables={len(cls._temp_tables_created)}"
                    )

            with DatabaseOperations.get_connection() as conn:
                cursor = conn.cursor()
                for table_name in cls._temp_tables_created:
                    try:
                        cursor.execute(
                            sql.SQL("DROP TABLE IF EXISTS {}").format(
                                sql.Identifier('temporaire', table_name)
                            )
                        )
                    except Exception as e:
                        from .dqe_utils import _logger
                        if _logger:
                            _logger.warning(f"DROP temporaire.{table_name} echoue: {e}")
                conn.commit()
                cursor.close()
            cls._temp_tables_created.clear()
        except Exception as e:
            from .dqe_utils import _logger
            if _logger:
                _logger.warning(f"Erreur nettoyage tables temporaires: {e}")

    @staticmethod
    def create_compatible_field(name: str, semantic_type, type_name: str = None):
        """Crée un QgsField compatible QGIS 3.28 -> 4.99.

        semantic_type : 'int' | 'string' | 'double' | 'bool' | 'longlong'.
        Le type Qt (QMetaType.Type >= 3.38, sinon QVariant.Type) est résolu via
        compat.field_type pour éviter le constructeur QVariant deprecated sur 3.38+
        tout en restant compatible avec le plancher 3.28.
        Un type Qt déjà résolu reste accepté (rétro-compatibilité défensive).
        """
        from .compat import field_type as _field_type
        qt_type = _field_type(semantic_type) if isinstance(semantic_type, str) else semantic_type
        if type_name:
            return QgsField(name, qt_type, type_name)
        return QgsField(name, qt_type)
    
    @staticmethod
    def create_layer_group(name: str):
        root = QgsProject.instance().layerTreeRoot()
        return root.addGroup(name)
    
    @staticmethod
    def create_layer_subgroup(parent_group, subgroup_name: str):
        """Crée un sous-groupe de couches dans un groupe parent"""
        if parent_group:
            return parent_group.addGroup(subgroup_name)
        else:
            root = QgsProject.instance().layerTreeRoot()
            return root.addGroup(subgroup_name)
    
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
        uri.setUseEstimatedMetadata(True)
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
        if any(x in designation for x in ["pose de chambre", "chambre l"]):
            print("  -> Table PGC: gc_exe.infra_pt_chb")
            return "gc_exe.infra_pt_chb"
        elif any(x in designation for x in ["pose poteau", "poteau rauv"]):
            print("  -> Table PGC: gc_exe.infra_pt_pot")
            return "gc_exe.infra_pt_pot"
        elif any(x in designation for x in [
            "tranchée", "micro tranchée", "forage dirigé", "encorbellement",
            "pvc ", "pehd", "alvéole"
        ]):
            print("  -> Table PGC: gc_exe.t_cheminement")
            return "gc_exe.t_cheminement"
        else:
            print("  -> Table PGC par défaut: gc_exe.t_cheminement")
            return "gc_exe.t_cheminement"
    
    @staticmethod
    def get_table_from_designation(designation):
        """Méthode générale pour PRO/EXE"""
        designation = designation.lower()
        
        print(f"Détection de table pour: '{designation}'")
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
        elif any(x in designation for x in ["bpe", "pa ", "pa)", "pbo", "f&p bpe", "f&p pa", "f&p de pbo"]):
            print("  -> Détecté comme BPE/PA/PBO")
            return "rip_avg_nge.bpe"
        elif "sro" in designation:
            print("  -> Détecté comme SRO")
            return "rip_avg_nge.bpe"
        elif any(x in designation for x in ["cable", "câble", "fibre", "fo ", "fourniture et pose de câble"]):
            print("  -> Détecté comme câble")
            return "rip_avg_nge.cables"
        elif any(x in designation for x in ["prise", "dtr", "rad", "nbre de prises"]):
            print("  -> Détecté comme Prise")
            return "rbal.rbal_auvergne"
        elif any(x in designation for x in ["gc", "génie civil", "cheminement", "lineaire", "infra"]):
            print("  -> Détecté comme GC/Cheminement PRO")
            return "rip_avg_nge.t_cheminement"
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
            ids_joined = ",".join(gids_list)
            sql_filter = f"gid IN ({ids_joined})"
            print(f"        Filtre SQL: {sql_filter[:100]}{'...' if len(sql_filter) > 100 else ''}")
            
            uri.setDataSource(schema, table, "geom", sql_filter, "gid")
            
            layer = QgsVectorLayer(uri.uri(), designation, "postgres")
            
            if layer.isValid():
                feature_count = layer.featureCount()
                if feature_count > 0:
                    if _logger:
                        _logger.debug(f"Couche valide: {designation} n_items={feature_count}")
                    return layer
                else:
                    if _logger:
                        _logger.info(f"Couche vide rejetée: {designation} (0 entité)")
                    return None
            else:
                error = layer.error().message() if layer.error() else "Erreur inconnue"
                print(f"        ÉCHEC: Couche invalide - {error}")
                return None
                
        except Exception as e:
            print(f"        EXCEPTION: {str(e)}")
            import traceback
            print(f"        Traceback: {traceback.format_exc()}")
            if _logger:
                _logger.error(f"Erreur chargement couche {designation}", exception=e)
            return None
    
    @staticmethod
    def load_gestionnaire_layer(sro, troncon, layer_group=None):
        """Charge la table gestionnaire en tant que couche QGIS pour permettre les corrections manuelles"""
        try:
            print(f"Chargement couche gestionnaire pour SRO: {sro}, Tronçon: {troncon}")
            uri = LayerManager.get_db_connection_string()
            if not uri:
                print("ÉCHEC: URI de connexion non disponible")
                return None
            
            print(f"Récupération données gestionnaire depuis PostgreSQL...")
            conn = None
            try:
                conn = psycopg2.connect(
                    host=uri.host(),
                    port=uri.port(),
                    database=uri.database(),
                    user=uri.username(),
                    password=uri.password()
                )
                cursor = conn.cursor()
                sql_query = """
                SELECT 
                    troncon_gid,
                    segment_id,
                    cm_gest_do,
                    cm_compo,
                    ST_AsText(ST_SetSRID(geom_segment, 2154)) as geom_wkt,
                    long,
                    distance_route_m,
                    angle_parallelisme_deg,
                    confiance_niveau,
                    methode_attribution,
                    nb_pot_ac
                FROM gc_exe.gestionnaire(%s, %s)
                WHERE geom_segment IS NOT NULL
                """
                
                cursor.execute(sql_query, (sro, troncon))
                data_rows = cursor.fetchall()
                column_names = [desc[0] for desc in cursor.description]
                
                print(f"Données récupérées: {len(data_rows)} enregistrements")
                print(f"Colonnes: {column_names}")
                if data_rows:
                    print(f"Premier enregistrement: {data_rows[0]}")
                    print(f"Géométrie WKT sample: {data_rows[0][4][:100] if data_rows[0][4] else 'NULL'}...")
                else:
                    print("Aucune donnée retournée par la requête SQL")
                
                cursor.close()
                
                if not data_rows:
                    print("Aucune donnée trouvée dans gestionnaire()")
                    return None
                    
            except Exception as e:
                print(f"ERREUR création couche gestionnaire: {str(e)}")
                if conn:
                    conn.rollback()
                return None
            finally:
                if conn:
                    conn.close()
            base_layer_name = f"Gestionnaire - {sro} - {troncon}"
            layer_name = base_layer_name
            project = QgsProject.instance()
            existing_layers = [layer.name() for layer in project.mapLayers().values() if layer.isValid()]
            counter = 2
            while layer_name in existing_layers:
                layer_name = f"{base_layer_name} ({counter})"
                counter += 1
            
            print(f"Nom de couche sélectionné: '{layer_name}'")
            if layer_name != base_layer_name:
                print(f"   (nom modifié pour éviter les doublons)")
            
            memory_layer = QgsVectorLayer(
                "LineString?crs=EPSG:2154", 
                layer_name, 
                "memory"
            )
            
            if not memory_layer.isValid():
                print("❌ ÉCHEC: Impossible de créer la couche mémoire")
                return None
            provider = memory_layer.dataProvider()
            fields = QgsFields()
            fields.append(LayerManager.create_compatible_field("troncon_gid", "int", "integer"))
            fields.append(LayerManager.create_compatible_field("segment_id", "string", "text"))
            fields.append(LayerManager.create_compatible_field("cm_gest_do", "string", "text"))
            fields.append(LayerManager.create_compatible_field("cm_compo", "string", "text"))
            fields.append(LayerManager.create_compatible_field("long", "double", "double"))
            fields.append(LayerManager.create_compatible_field("distance_route_m", "double", "double"))
            fields.append(LayerManager.create_compatible_field("angle_parallelisme_deg", "double", "double"))
            fields.append(LayerManager.create_compatible_field("confiance_niveau", "string", "text"))
            fields.append(LayerManager.create_compatible_field("methode_attribution", "string", "text"))
            fields.append(LayerManager.create_compatible_field("nb_pot_ac", "int", "integer"))
            
            provider.addAttributes(fields)
            memory_layer.updateFields()
            features = []
            successful_features = 0
            for i, row in enumerate(data_rows):
                try:
                    feature = QgsFeature()
                    geom_wkt = row[4]  # geom_wkt est à l'index 4
                    if geom_wkt:
                        geom = QgsGeometry.fromWkt(geom_wkt)
                        if geom.isNull():
                            print(f"Géométrie invalide pour ligne {i}: {geom_wkt[:50]}...")
                            continue
                        feature.setGeometry(geom)
                    else:
                        print(f"Géométrie NULL pour ligne {i}")
                        continue
                    attributes = [
                        row[0],  # troncon_gid
                        row[1],  # segment_id
                        row[2],  # cm_gest_do
                        row[3],  # cm_compo
                        float(row[5]) if row[5] else 0.0,  # long
                        float(row[6]) if row[6] else 0.0,  # distance_route_m
                        float(row[7]) if row[7] else 0.0,  # angle_parallelisme_deg
                        row[8],  # confiance_niveau
                        row[9],  # methode_attribution
                        int(row[10]) if row[10] else 0  # nb_pot_ac
                    ]
                    feature.setAttributes(attributes)
                    features.append(feature)
                    successful_features += 1
                    
                except Exception as e:
                    print(f"Erreur création feature {i}: {str(e)}")
                    continue
            
            print(f"Features créées avec succès: {successful_features}/{len(data_rows)}")
            if features:
                memory_layer.startEditing()
                result = provider.addFeatures(features)
                if result[0]:
                    memory_layer.commitChanges()
                    print(f"{len(result[1])} entités ajoutées avec succès")
                else:
                    memory_layer.rollBack()
                    print(f"Échec ajout des entités")
                    return None
            else:
                print(f"Aucune entité valide à ajouter")
                return None
                
            memory_layer.updateExtents()
            final_count = memory_layer.featureCount()
            print(f"Couche gestionnaire créée avec succès: {final_count} entités dans la couche")
            if layer_group:
                QgsProject.instance().addMapLayer(memory_layer, False)
                layer_group.addLayer(memory_layer)
                print(f"Couche ajoutée au groupe: {layer_group.name()}")
            
            return memory_layer
                
        except Exception as e:
            print(f"EXCEPTION lors du chargement gestionnaire: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def prepare_distribution_cables_db(sro, worker=None):
        """Phase DB des cables decoupes (peut s'executer dans un thread).
        
        Retourne un dict {table_name, qualified_table_name, categories}
        ou None si aucun cable trouve.
        """
        _crash_log.step("prepare_distribution_cables_db START", f"sro={sro}")
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            raise RuntimeError("Parametres DB non disponibles")
        
        _crash_log.step("prepare_distribution_cables_db", "connecting")
        conn = psycopg2.connect(
            host=db_params["host"],
            port=db_params["port"],
            database=db_params["database"],
            user=db_params["user"],
            password=db_params["password"]
        )
        _crash_log.step("prepare_distribution_cables_db", "connected")
        try:
            conn.set_session(autocommit=False)
            cursor = conn.cursor()
            
            if worker and worker.is_cancelled:
                return None
            if worker:
                worker.progress_value = 20
            
            _crash_log.step("prepare_distribution_cables_db", "counting cables")
            cursor.execute(
                "SELECT COUNT(*) FROM rip_avg_nge.fddcpi2(%s) WHERE cab_type = 'CDI'",
                (sro,)
            )
            count_cables = cursor.fetchone()[0]
            _crash_log.step("prepare_distribution_cables_db", f"count={count_cables}")
            if count_cables == 0:
                print(f"Aucun cable decoupe pour SRO '{sro}'")
                return None
            
            print(f"{count_cables} segments cables decoupes pour SRO '{sro}'")
            if worker and worker.is_cancelled:
                return None
            if worker:
                worker.progress_value = 40
            
            sro_safe = re.sub(r'[^a-zA-Z0-9]', '_', sro)
            today = datetime.now().strftime("%Y%m%d")
            unique_id = uuid.uuid4().hex[:6]
            table_name = f"cables_decoupes_{sro_safe}_{today}_{unique_id}"
            if len(table_name) > 50:
                sro_id = re.sub(r'[^a-zA-Z0-9]', '_', sro.split("/")[-1])
                table_name = f"cables_decoupes_{sro_id}_{today}_{unique_id}"
            
            qualified = f"temporaire.{table_name}"
            
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(
                    sql.Identifier('temporaire', table_name)
                )
            )
            cursor.execute(
                sql.SQL("""
                CREATE TABLE {} AS
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
                    %s AS sro_source,
                    NOW() AS date_creation
                FROM rip_avg_nge.fddcpi2(%s) c
                WHERE cab_type = 'CDI' AND "DCE" = 'O' AND affectation != '3'
                """).format(sql.Identifier('temporaire', table_name)),
                (sro, sro)
            )
            
            if worker and worker.is_cancelled:
                conn.rollback()
                return None
            if worker:
                worker.progress_value = 70
            
            tbl = sql.Identifier('temporaire', table_name)
            idx_pm = sql.Identifier(f"idx_{table_name}_posemode")
            idx_gid = sql.Identifier(f"idx_{table_name}_gid_dc2")
            cursor.execute(sql.SQL("CREATE INDEX {} ON {} (posemode, normalized_capa)").format(idx_pm, tbl))
            cursor.execute(sql.SQL("CREATE INDEX {} ON {} (gid_dc2)").format(idx_gid, tbl))
            cursor.execute(sql.SQL("ANALYZE {}").format(tbl))
            comment_text = f"DQE cables decoupes - SRO: {sro} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            cursor.execute(
                sql.SQL("COMMENT ON TABLE {} IS %s").format(tbl),
                (comment_text,)
            )
            conn.commit()
            _crash_log.step("prepare_distribution_cables_db", f"table created: {qualified}")
            
            LayerManager._temp_tables_created.append(table_name)
            
            if worker:
                worker.progress_value = 80
            
            cursor.execute(sql.SQL("""
                SELECT posemode, normalized_capa, COUNT(*) as count
                FROM {}
                GROUP BY posemode, normalized_capa
                ORDER BY posemode, normalized_capa
            """).format(tbl))
            categories = cursor.fetchall()
            
            conn.close()
            _crash_log.step("prepare_distribution_cables_db END", f"{len(categories)} categories")
            print(f"Preparation DB terminee: {len(categories)} categories")
            return {
                'table_name': table_name,
                'qualified_table_name': qualified,
                'categories': categories
            }
        except Exception:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
            raise
    
    @staticmethod
    def create_distribution_layers(db_result, layer_group=None, layers_loaded=None, cancel_check=None):
        """Phase UI des cables decoupes (DOIT s'executer dans le main thread).
        
        Cree les couches QGIS a partir du resultat de prepare_distribution_cables_db.
        Appelle processEvents() entre chaque couche pour garder l'UI responsive.
        
        cancel_check : callable retournant True si annulation demandee.
        """
        from qgis.core import QgsProject, QgsVectorLayer
        _crash_log.step("create_distribution_layers START")
        _t0 = time.monotonic()
        
        if not db_result:
            return []
        
        qualified = db_result['qualified_table_name']
        categories = db_result['categories']
        _crash_log.step("create_distribution_layers", f"qualified={qualified} categories={len(categories)}")
        
        uri = LayerManager.get_db_connection_string()
        if not uri:
            print("Erreur: URI de connexion non disponible")
            return []
        
        cables_group = None
        if layer_group:
            cables_group = layer_group.addGroup("Cables decoupes")
        
        created_layers = []
        from qgis.core import QgsApplication
        
        for idx, (posemode, capa, count) in enumerate(categories):
            if cancel_check and cancel_check():
                _crash_log.step("create_distribution_layers", f"cancelled at {idx}/{len(categories)}")
                break
            if count == 0:
                continue
            _crash_log.step("create_distribution_layers", f"layer {idx+1}/{len(categories)} posemode={posemode} capa={capa}")
            
            if posemode == 0:
                layer_name = f"Cable de {capa} FO en conduite"
            elif posemode == 1:
                layer_name = f"Cable optique de {capa} FO en aerien"
            elif posemode == 2:
                layer_name = f"Cable optique de {capa} FO en facade"
            else:
                layer_name = f"Cable de {capa} FO (mode pose {posemode})"
            
            safe_posemode = int(posemode)
            safe_capa = int(capa)
            sql_query = f"""
                SELECT * FROM {qualified}
                WHERE posemode = {safe_posemode} AND normalized_capa = {safe_capa}
            """
            uri_copy = QgsDataSourceUri(uri.uri())
            uri_copy.setDataSource("", f"({sql_query})", "geom", "", "gid_dc2")
            
            layer = QgsVectorLayer(uri_copy.uri(False), layer_name, "postgres")
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer, False)
                if cables_group:
                    cables_group.addLayer(layer)
                elif layer_group:
                    layer_group.addLayer(layer)
                if layers_loaded is not None:
                    layers_loaded.append(layer)
                created_layers.append(layer)
            else:
                print(f"Echec couche: {layer_name}")
            
            QgsApplication.processEvents()
        
        elapsed_ms = int((time.monotonic() - _t0) * 1000)
        _crash_log.step("create_distribution_layers END", f"{len(created_layers)}/{len(categories)} couches elapsed_ms={elapsed_ms}")
        print(f"{len(created_layers)}/{len(categories)} couches cables creees")
        return created_layers
    
    @staticmethod
    def load_distribution_cables(sro, layer_group=None, layers_loaded=None):
        """Chargement synchrone des cables decoupes (wrapper retro-compatible)."""
        try:
            start_time = time.time()
            db_result = LayerManager.prepare_distribution_cables_db(sro)
            if not db_result:
                return []
            layers = LayerManager.create_distribution_layers(
                db_result, layer_group, layers_loaded
            )
            print(f"Temps total cables decoupes: {time.time() - start_time:.2f}s")
            return layers
        except Exception as e:
            import traceback
            print(f"ERREUR cables decoupes: {e}")
            print(traceback.format_exc())
            return []

    @staticmethod
    def extract_layer_data(layer):
        """Extrait les donnees d'une couche QGIS pour sauvegarde JSON.
        Version robuste avec gestion des couches C++ supprimees.
        """
        empty_result = {'type': 'FeatureCollection', 'features': [], 'crs': None}
        try:
            if not layer or not layer.isValid():
                return empty_result

            _ = layer.name()
            layer_fields = layer.fields()

            features_data = []
            for feature in layer.getFeatures():
                try:
                    feature_dict = {
                        'geometry': feature.geometry().asWkt() if feature.geometry() else None,
                        'attributes': {}
                    }
                    for field in layer_fields:
                        field_name = field.name()
                        try:
                            value = feature[field_name]
                            if isinstance(value, (int, float, str, bool)) or value is None:
                                feature_dict['attributes'][field_name] = value
                            else:
                                feature_dict['attributes'][field_name] = str(value)
                        except Exception:
                            feature_dict['attributes'][field_name] = None
                    features_data.append(feature_dict)
                except Exception:
                    continue

            crs_authid = None
            try:
                if layer.crs() and layer.crs().isValid():
                    crs_authid = layer.crs().authid()
            except Exception:
                pass

            return {
                'type': 'FeatureCollection',
                'features': features_data,
                'crs': crs_authid
            }
        except RuntimeError:
            return empty_result
        except Exception:
            return empty_result

    @staticmethod
    def collapse_group_recursive(group):
        """Reduit (collapse) recursivement un groupe et tous ses enfants dans le layer tree.
        Permet d'avoir une vue compacte sans afficher les styles."""
        if not group:
            return
        try:
            group.setExpanded(False)
            for child in group.children():
                if hasattr(child, 'setExpanded'):
                    child.setExpanded(False)
                if hasattr(child, 'children') and child.children():
                    LayerManager.collapse_group_recursive(child)
        except Exception as e:
            print(f"Erreur collapse groupe: {e}")

    @staticmethod
    def collect_group_layers(group):
        """Recherche recursive de toutes les couches valides dans un groupe."""
        layers = []
        if not group:
            return layers
        for child in group.children():
            if hasattr(child, 'layer'):
                layer = child.layer()
                if layer and layer.isValid():
                    layers.append(layer)
            elif hasattr(child, 'children'):
                layers.extend(LayerManager.collect_group_layers(child))
        return layers

    @staticmethod
    def save_layers_to_db(layer_group, sro, nom_dqe, projet_code, user_name, db_manager):
        """Sauvegarde toutes les couches d'un groupe dans dqe.dqejson.
        Retourne le nombre de couches archivees.
        """
        import json as _json
        layers_count = 0
        try:
            all_layers = LayerManager.collect_group_layers(layer_group)
            for layer in all_layers:
                try:
                    layer_data = LayerManager.extract_layer_data(layer)
                    if layer_data['features']:
                        with db_manager.get_cursor() as cursor:
                            query = """
                                INSERT INTO dqe.dqejson
                                (sro, nom_dqe, projet, categorie, champs, user_name, version_projet)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """
                            cursor.execute(query, (
                                sro, nom_dqe, projet_code,
                                layer.name(),
                                _json.dumps(layer_data),
                                user_name, None
                            ))
                        layers_count += 1
                except Exception as e:
                    print(f"Erreur archivage {layer.name()}: {str(e)}")
        except Exception as e:
            print(f"Erreur archivage couches: {str(e)}")
        return layers_count
