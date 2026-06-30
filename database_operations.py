"""
DQE Database Operations
======================================================
Opérations base de données pour le plugin DQE Chargeur
"""

from typing import Dict, List, Any
from contextlib import contextmanager
import psycopg2
from psycopg2 import sql as psql
from psycopg2.extras import DictCursor
from .models import DQEResult
import time

try:
    from .dqe_utils import _db_manager, _logger, _crash_log
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = _crash_log = None
    MODULES_AVAILABLE = False


class DatabaseOperations:
    def __init__(self, connection_params):
        self.connection_params = connection_params
        
    @staticmethod
    def _reorganize_redevance_columns(redevance_data):
        """Réorganise les colonnes de redevance pour mettre les poteaux à la fin (cohérence première génération / régénération)"""
        if not redevance_data:
            return redevance_data
        reorganized_data = []
        
        for raw_row in redevance_data:
            row_dict = dict(raw_row)
            new_row = {}
            if 'concessionnaire_voirie' in row_dict:
                new_row['concessionnaire_voirie'] = row_dict['concessionnaire_voirie']
            alveoles_keys = [k for k in row_dict.keys() 
                           if k != 'concessionnaire_voirie' and 'poteau' not in k.lower()]
            for key in sorted(alveoles_keys):  # Tri alphabétique pour cohérence
                new_row[key] = row_dict[key]
            total_redevance = 0
            for key in alveoles_keys:
                value = row_dict[key]
                if isinstance(value, (int, float)) or (hasattr(value, '__float__')):
                    try:
                        total_redevance += float(value)
                    except (ValueError, TypeError):
                        pass
            new_row['total_redevance'] = total_redevance
            poteaux_keys = [k for k in row_dict.keys() if 'poteau' in k.lower()]
            for key in poteaux_keys:
                if key.lower() in ['poteaux', 'nb_poteaux']:
                    new_row['Poteaux_nb_unites'] = row_dict[key]  
                else:
                    new_row[key] = row_dict[key]
            
            reorganized_data.append(new_row)
        
        print(f" Réorganisation colonnes: poteaux déplacés à la fin")
        return reorganized_data

    @staticmethod
    def get_db_connection_params():
        if _db_manager and _db_manager.config:
            return _db_manager.config.to_dict()
        return None
    
    @staticmethod
    @contextmanager
    def get_connection():
        """Context manager pour connexion DB via le pool de _db_manager"""
        if _db_manager and _db_manager.is_connected:
            with _db_manager.get_connection() as conn:
                yield conn
        else:
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
                yield conn
            finally:
                conn.close()
    
    @staticmethod
    def execute_dqe_pro(sro: str, p_type: str) -> List[Dict[str, Any]]:
        _t0 = time.monotonic()
        with DatabaseOperations.get_connection() as conn:
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
            elapsed_ms = int((time.monotonic() - _t0) * 1000)
            if _crash_log:
                _crash_log.step("execute_dqe_pro END", f"n_items={len(cleaned_results)} elapsed_ms={elapsed_ms}")
            return cleaned_results

    @staticmethod
    def execute_dqe_exe(sro: str, p_type: str, blocage: str = None) -> List[Dict[str, Any]]:
        _t0 = time.monotonic()
        with DatabaseOperations.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=DictCursor)
            
            print(f"Exécution de dqe_exe('{sro}', '{p_type}', '{blocage}')")
            query = "SELECT * FROM rip_avg_nge.dqe_exe(%s, %s, %s)"
            cursor.execute(query, (sro, p_type, blocage))
            results = cursor.fetchall()
            
            print(f"Résultats bruts: {len(results)} lignes reçues de la base")
            
            cleaned_results = []
            for i, row in enumerate(results):
                row_dict = dict(row)
                if i == 0:
                    print(f"Première ligne (exemple): {row_dict}")
                cleaned_results.append(row_dict)
            
            print(f"Résultats nettoyés: {len(cleaned_results)} lignes retournées")
            elapsed_ms = int((time.monotonic() - _t0) * 1000)
            if _crash_log:
                _crash_log.step("execute_dqe_exe END", f"n_items={len(cleaned_results)} elapsed_ms={elapsed_ms}")
            return cleaned_results

    @staticmethod
    def execute_dqe_pgc(sro: str, troncon: str) -> List[DQEResult]:
        _t0 = time.monotonic()
        with DatabaseOperations.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=DictCursor)
            print(f"\n=== DÉBUT DQE PGC COMPLET ===")
            print(f"SRO: {sro}, Tronçon: {troncon}")
            print("\nÉTAPE 1: Exécution DQE PGC...")
            query = "SELECT * FROM rip_avg_nge.dqe_pgc(%s, %s)"
            cursor.execute(query, (sro, troncon))
            raw_results = cursor.fetchall()
            
            print(f"Résultats bruts de la fonction: {len(raw_results)} lignes")
            print("\nÉTAPE 2: Récupération données REDEVANCE...")
            redevance_data = []
            try:
                print(f" REDEVANCE: Appel de gc_exe.redevance_table('{sro}', '{troncon}')")
                redevance_query = "SELECT gc_exe.redevance_table(%s, %s)"
                cursor.execute(redevance_query, (sro, troncon))
                redevance_result = cursor.fetchone()
                
                if redevance_result:
                    redevance_sql_expression = redevance_result[0]  # Premier élément du tuple
                    print(f" Expression SQL reçue: {redevance_sql_expression}")
                    
                    if redevance_sql_expression and redevance_sql_expression.strip():
                        print(" Exécution de la requête REDEVANCE...")
                        cursor.execute(redevance_sql_expression)
                        redevance_data = cursor.fetchall()
                        print(f" Données REDEVANCE récupérées: {len(redevance_data)} lignes")
                        if redevance_data and len(redevance_data) > 0:
                            print(f" Aperçu colonnes REDEVANCE (original): {list(dict(redevance_data[0]).keys()) if redevance_data else 'Aucune'}")
                            redevance_data = DatabaseOperations._reorganize_redevance_columns(redevance_data)
                            print(f" Aperçu colonnes REDEVANCE (réorganisé): {list(dict(redevance_data[0]).keys()) if redevance_data else 'Aucune'}")
                    else:
                        print(" Expression SQL REDEVANCE vide")
                else:
                    print(" Aucune expression SQL REDEVANCE retournée")
                    
            except Exception as e:
                print(f" Erreur récupération REDEVANCE: {str(e)}")
            for i, row in enumerate(raw_results[:10]):
                row_dict = dict(row)
                print(f"Ligne {i+1}: {row_dict}")
            
            results = []
            for i, row in enumerate(raw_results):
                row_dict = dict(row)
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
                if not designation or designation.strip() == "":
                    print(f"  -> IGNORÉ (désignation vide)")
                    continue
                if any(x in designation.lower() for x in [
                    "nom gc :", "désignation", "armoire de rue  -", 
                    "gc - tdr", "pose de poteaux", "fourniture des alvéoles"
                ]):
                    print(f"  -> IGNORÉ (en-tête)")
                    continue
                try:
                    quantite_num = float(quantite) if quantite is not None else 0
                except (ValueError, TypeError):
                    print(f"  -> IGNORÉ (quantité invalide: {quantite})")
                    continue
                ids_list = []
                if ids_str and str(ids_str).strip():
                    try:
                        ids_list = [int(id_str.strip()) for id_str in str(ids_str).split(',') if id_str.strip()]
                        print(f"  -> IDs parsés: {len(ids_list)} éléments")
                    except ValueError as e:
                        print(f"  -> Erreur parsing IDs: {e}")
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
            if redevance_data:
                redevance_converted = []
                for row in redevance_data:
                    row_dict = dict(row)
                    redevance_converted.append(row_dict)
                if results:
                    results[0].redevance_data = redevance_converted
                    print(f" Données REDEVANCE attachées: {len(redevance_converted)} lignes")
            
            elapsed_ms = int((time.monotonic() - _t0) * 1000)
            if _crash_log:
                _crash_log.step("execute_dqe_pgc END", f"n_items={len(results)} elapsed_ms={elapsed_ms}")
            return results

    @staticmethod
    def get_redevance_data_only(sro: str, troncon: str) -> List[Dict]:
        """
        Récupère seulement les données REDEVANCE sans refaire FUNCTION_UP_GEST
        Utilisé pour régénérer l'Excel après correction manuelle de cm_gest_do
        """
        print(f" RÉCUPÉRATION REDEVANCE SEULE pour {sro} / {troncon}")
        
        redevance_data = []
        
        try:
            with DatabaseOperations.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=DictCursor)
                redevance_query = "SELECT gc_exe.redevance_table(%s, %s)"
                cursor.execute(redevance_query, (sro, troncon))
                redevance_result = cursor.fetchone()
                
                if redevance_result:
                    redevance_sql_expression = redevance_result[0]
                    
                    if redevance_sql_expression and redevance_sql_expression.strip():
                        cursor.execute(redevance_sql_expression)
                        redevance_raw = cursor.fetchall()
                        print(f" Données REDEVANCE récupérées: {len(redevance_raw)} lignes")
                        for row in redevance_raw:
                            redevance_data.append(dict(row))
                    else:
                        print(" Expression SQL REDEVANCE vide")
                else:
                    print(" Aucune expression SQL REDEVANCE retournée")
                
                conn.commit()
                
        except Exception as e:
            print(f" Erreur récupération REDEVANCE seule: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
                
        print(f" REDEVANCE finale récupérée: {len(redevance_data)} lignes")
        return redevance_data

    @staticmethod
    def get_redevance_from_modified_gestionnaire(sro: str, troncon: str, modified_gestionnaire_data: List[Dict]) -> List[Dict]:
        """
        Calcule les redevances en utilisant les données modifiées de la couche gestionnaire
        """
        print(f" CALCUL REDEVANCE avec données gestionnaire modifiées pour {sro} / {troncon}")
        print(f" Données gestionnaire modifiées: {len(modified_gestionnaire_data)} lignes")
        
        redevance_data = []
        
        try:
            with DatabaseOperations.get_connection() as conn:
                cursor = conn.cursor(cursor_factory=DictCursor)
                temp_table_name = f"temp_gestionnaire_modified_{int(time.time())}"
                print(f" Création table temporaire: {temp_table_name}")
                tbl_id = psql.Identifier(temp_table_name)
                create_temp_sql = psql.SQL("""
                CREATE TEMP TABLE {} (
                    troncon_gid integer,
                    segment_id integer,
                    cm_gest_do varchar,
                    cm_compo varchar,
                    long numeric(10,2),
                    distance_route_m numeric(10,2),
                    angle_parallelisme_deg numeric(10,2),
                    confiance_niveau varchar,
                    methode_attribution varchar,
                    nb_pot_ac integer
                )
                """).format(tbl_id)
                cursor.execute(create_temp_sql)
                print(f" Table temporaire {temp_table_name} créée")
                insert_sql = psql.SQL("""
                INSERT INTO {} 
                (troncon_gid, segment_id, cm_gest_do, cm_compo, long, distance_route_m, 
                 angle_parallelisme_deg, confiance_niveau, methode_attribution, nb_pot_ac)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """).format(tbl_id)
                for row in modified_gestionnaire_data:
                    troncon_gid = row.get('troncon_gid')
                    if troncon_gid == '' or troncon_gid is None:
                        troncon_gid = None
                    else:
                        try:
                            troncon_gid = int(troncon_gid)
                        except (ValueError, TypeError):
                            troncon_gid = None
                
                    segment_id = row.get('segment_id')
                    if segment_id == '' or segment_id is None:
                        segment_id = None
                    else:
                        try:
                            segment_id = int(segment_id)
                        except (ValueError, TypeError):
                            segment_id = None
                    long_val = row.get('long')
                    if long_val == '' or long_val is None:
                        long_val = None
                    else:
                        try:
                            long_val = float(long_val)
                        except (ValueError, TypeError):
                            long_val = None
                
                    distance_route_m = row.get('distance_route_m')
                    if distance_route_m == '' or distance_route_m is None:
                        distance_route_m = None
                    else:
                        try:
                            distance_route_m = float(distance_route_m)
                        except (ValueError, TypeError):
                            distance_route_m = None
                
                    angle_parallelisme_deg = row.get('angle_parallelisme_deg')
                    if angle_parallelisme_deg == '' or angle_parallelisme_deg is None:
                        angle_parallelisme_deg = None
                    else:
                        try:
                            angle_parallelisme_deg = float(angle_parallelisme_deg)
                        except (ValueError, TypeError):
                            angle_parallelisme_deg = None
                
                    nb_pot_ac = row.get('nb_pot_ac')
                    if nb_pot_ac == '' or nb_pot_ac is None:
                        nb_pot_ac = None
                    else:
                        try:
                            nb_pot_ac = int(nb_pot_ac)
                        except (ValueError, TypeError):
                            nb_pot_ac = None
                
                    cursor.execute(insert_sql, (
                        troncon_gid,
                        segment_id,
                        row.get('cm_gest_do'),
                        row.get('cm_compo'),
                        long_val,
                        distance_route_m,
                        angle_parallelisme_deg,
                        row.get('confiance_niveau'),
                        row.get('methode_attribution'),
                        nb_pot_ac
                    ))
            
                print(f" {len(modified_gestionnaire_data)} lignes insérées dans {temp_table_name}")
                compositions_sql = psql.SQL("""
                SELECT DISTINCT cm_compo 
                FROM {}
                WHERE cm_compo IS NOT NULL
                ORDER BY cm_compo
                """).format(tbl_id)
            
                cursor.execute(compositions_sql)
                compositions = [row[0] for row in cursor.fetchall()]
                print(f" Compositions trouvées: {compositions}")
                cursor.execute(psql.SQL("SELECT COUNT(*) FROM {} WHERE nb_pot_ac > 0").format(tbl_id))
                has_poteaux = cursor.fetchone()[0] > 0
                colonnes_finales = []
                if compositions:
                    for compo in compositions:
                        col = psql.SQL(
                            "SUM(CASE WHEN type_equipement = {val} THEN quantite ELSE 0 END) AS {name}"
                        ).format(val=psql.Literal(compo), name=psql.Identifier(compo))
                        colonnes_finales.append(col)
                if has_poteaux:
                    colonnes_finales.append(psql.SQL(
                        "SUM(CASE WHEN type_equipement = 'Poteaux' THEN quantite ELSE 0 END) AS {}"
                    ).format(psql.Identifier('Poteaux_nb_unites')))
            
                colonnes_finales_sql = psql.SQL(', ').join(colonnes_finales)
                infra_type = 'Mixte' if has_poteaux and compositions else 'Aérienne' if has_poteaux else 'Souterraine'
                col_names = list(compositions) + (['Poteaux_nb_unites'] if has_poteaux else [])
                print(f" Infrastructure: {infra_type}")
                print(f" Colonnes générées: {col_names}")
            
                redevance_sql = psql.SQL("""
                WITH extraction_alveoles AS (
                    SELECT 
                        cm_gest_do as concessionnaire_voirie,
                        cm_compo as type_equipement,
                        CASE 
                            WHEN cm_compo LIKE '%+%' THEN 
                                COALESCE(NULLIF(split_part(cm_compo, '+', 1), '')::INTEGER, 0) + 
                                COALESCE(NULLIF(regexp_replace(split_part(split_part(cm_compo, '+', 2), ' ', 1), '[^0-9]', '', 'g'), '')::INTEGER, 0)
                            ELSE 
                                COALESCE(NULLIF(regexp_replace(split_part(cm_compo, ' ', 1), '[^0-9]', '', 'g'), '')::INTEGER, 1)
                        END as nb_alveoles,
                        long as long_plan
                    FROM {tbl}
                    WHERE cm_compo IS NOT NULL AND cm_gest_do IS NOT NULL
                    AND long IS NOT NULL AND long > 0
                ),
                extraction_poteaux AS (
                    SELECT 
                        cm_gest_do as concessionnaire_voirie,
                        'Poteaux' as type_equipement,
                        1 as nb_equipements,
                        nb_pot_ac::NUMERIC as quantite_totale
                    FROM {tbl}
                    WHERE cm_gest_do IS NOT NULL AND nb_pot_ac IS NOT NULL AND nb_pot_ac > 0
                ),
                totaux_alveoles AS (
                    SELECT 
                        concessionnaire_voirie,
                        type_equipement,
                        ROUND(SUM(nb_alveoles * long_plan)::NUMERIC, 2) as quantite
                    FROM extraction_alveoles
                    GROUP BY concessionnaire_voirie, type_equipement
                ),
                totaux_poteaux AS (
                    SELECT 
                        concessionnaire_voirie,
                        type_equipement,
                        SUM(quantite_totale) as quantite
                    FROM extraction_poteaux
                    GROUP BY concessionnaire_voirie, type_equipement
                ),
                totaux_combines AS (
                    SELECT * FROM totaux_alveoles
                    UNION ALL
                    SELECT * FROM totaux_poteaux
                )
                SELECT concessionnaire_voirie, {cols}
                FROM totaux_combines
                GROUP BY concessionnaire_voirie
                ORDER BY concessionnaire_voirie
                """).format(tbl=tbl_id, cols=colonnes_finales_sql)
            
                cursor.execute(redevance_sql)
                redevance_raw = cursor.fetchall()
                print(f" Redevances calculées avec données modifiées: {len(redevance_raw)} lignes")
                for row in redevance_raw:
                    row_dict = dict(row)
                    redevance_data.append(row_dict)
                if redevance_data:
                    print(f" Aperçu colonnes REDEVANCE modifiées: {list(redevance_data[0].keys())}")
                    print(f" Première ligne exemple: {redevance_data[0]}")
                
        except Exception as e:
            print(f" Erreur calcul redevance avec données modifiées: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
            
        print(f" REDEVANCE finale (modifiée) calculée: {len(redevance_data)} lignes")
        return redevance_data

    @staticmethod
    def get_redevance_from_results(sro, troncon, results):
        """Récupère les données de redevance depuis les résultats DQE PGC existants"""
        try:
            print(f" Récupération redevances en mode direct pour SRO {sro}, tronçon {troncon}")
            redevance_data = []
            
            for result in results:
                if hasattr(result, 'redevance_data') and result.redevance_data:
                    redevance_data = result.redevance_data
                    print(f" Données redevance trouvées dans résultat '{result.designation}': {len(redevance_data)} lignes")
                    break
            
            if not redevance_data:
                print(" Aucune donnée redevance trouvée dans les résultats, calcul depuis base...")
                redevance_data = DatabaseOperations.get_redevance_data_only(sro, troncon)
            
            return redevance_data
            
        except Exception as e:
            print(f" Erreur lors de la récupération des données redevance: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
