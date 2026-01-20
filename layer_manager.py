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
from qgis.PyQt.QtCore import QVariant

from .database_operations import DatabaseOperations

try:
    from .dqe_utils import _db_manager, _logger
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = None
    MODULES_AVAILABLE = False


class LayerManager:
    @staticmethod
    def create_compatible_field(name: str, field_type, type_name: str = None):
        """
        Crée un QgsField compatible avec différentes versions de QGIS
        """
        try:
            field = QgsField()
            field.setName(name)
            field.setType(field_type)
            if type_name:
                field.setTypeName(type_name)
            return field
        except:
            try:
                from qgis.PyQt.QtCore import QVariant
                if type_name:
                    return QgsField(name, field_type, type_name)
                else:
                    return QgsField(name, field_type)
            except:
                return QgsField(name, field_type)
    
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
            fields.append(LayerManager.create_compatible_field("troncon_gid", QVariant.Int, "integer"))
            fields.append(LayerManager.create_compatible_field("segment_id", QVariant.String, "text"))
            fields.append(LayerManager.create_compatible_field("cm_gest_do", QVariant.String, "text"))
            fields.append(LayerManager.create_compatible_field("cm_compo", QVariant.String, "text"))
            fields.append(LayerManager.create_compatible_field("long", QVariant.Double, "double"))
            fields.append(LayerManager.create_compatible_field("distance_route_m", QVariant.Double, "double"))
            fields.append(LayerManager.create_compatible_field("angle_parallelisme_deg", QVariant.Double, "double"))
            fields.append(LayerManager.create_compatible_field("confiance_niveau", QVariant.String, "text"))
            fields.append(LayerManager.create_compatible_field("methode_attribution", QVariant.String, "text"))
            fields.append(LayerManager.create_compatible_field("nb_pot_ac", QVariant.Int, "integer"))
            
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
            print(f"Vérification de la présence de câbles découpés pour le SRO '{sro}'...")
            cursor.execute("SELECT COUNT(*) FROM rip_avg_nge.fddcpi2(%s) WHERE cab_type = 'CDI'", (sro,))
            count_cables = cursor.fetchone()[0]
            
            if count_cables == 0:
                print(f" Aucun câble découpé trouvé pour le SRO '{sro}'")
                return []
            
            print(f"{count_cables} segments de câbles découpés trouvés pour le SRO '{sro}'")
            sro_safe = re.sub(r'[^a-zA-Z0-9]', '_', sro)
            today = datetime.now().strftime("%Y%m%d")
            unique_id = uuid.uuid4().hex[:6]
            permanent_table_name = f"cables_decoupes_{sro_safe}_{today}_{unique_id}"
            if len(permanent_table_name) > 50:
                sro_id = re.sub(r'[^a-zA-Z0-9]', '_', sro.split("/")[-1])
                permanent_table_name = f"cables_decoupes_{sro_id}_{today}_{unique_id}"
            
            qualified_table_name = f"temporaire.{permanent_table_name}"
            
            print(f"Création de la table permanente '{qualified_table_name}'...")
            cursor.execute(
                sql.SQL("DROP TABLE IF EXISTS {}").format(
                    sql.Identifier('temporaire', permanent_table_name)
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
                """).format(sql.Identifier('temporaire', permanent_table_name)),
                (sro, sro)
            )
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
            for idx, (posemode, capa, count) in enumerate(categories):
                if count == 0:
                    continue
                if posemode == 0:
                    layer_name = f"Câble de {capa} FO en conduite"
                elif posemode == 1:
                    layer_name = f"Câble optique de {capa} FO en aérien"
                elif posemode == 2:
                    layer_name = f"Câble optique de {capa} FO en façade"
                else:
                    layer_name = f"Câble de {capa} FO (mode pose {posemode})"
                sql_query = f"""
                    SELECT * 
                    FROM {qualified_table_name}
                    WHERE posemode = {posemode} AND normalized_capa = {capa}
                """
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
                    print(f"Couche créée: '{layer_name}' ({layer.featureCount()} entités)")
                else:
                    print(f" Échec du chargement de la couche {layer_name}")
            
            conn.close()
            
            end_time = time.time()
            print(f"Temps total de chargement des câbles découpés: {end_time - start_time:.2f} secondes")
            print(f"{len(created_layers)}/{len(categories)} couches SRO créées avec succès")
            
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
