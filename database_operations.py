"""
DQE Database Operations
======================================================
Opérations base de données pour le plugin DQE Chargeur
"""

from typing import Dict, List, Any
import psycopg2
from psycopg2.extras import DictCursor
from .models import DQEResult
import time

try:
    from .dqe_utils import _db_manager, _logger
    MODULES_AVAILABLE = True
except ImportError:
    _db_manager = _logger = None
    MODULES_AVAILABLE = False


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
        - Récupération données REDEVANCE pour Excel
        - Support des deux modes : gestionnaire avec édition manuelle OU données existantes
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
            print(f"\n=== DÉBUT DQE PGC COMPLET ===")
            print(f"SRO: {sro}, Tronçon: {troncon}")
            
            # ÉTAPE 1: Exécution DQE PGC principal
            print(f"\n1️⃣ ÉTAPE 1: Exécution DQE PGC...")
            query = "SELECT * FROM rip_avg_nge.dqe_pgc(%s, %s)"
            cursor.execute(query, (sro, troncon))
            raw_results = cursor.fetchall()
            
            print(f"Résultats bruts de la fonction: {len(raw_results)} lignes")
            
            # ÉTAPE 2: Récupération données REDEVANCE pour Excel
            print("\n2️⃣ ÉTAPE 2: Récupération données REDEVANCE...")
            redevance_data = []
            try:
                # CORRECTION: gc_exe.redevance_table() retourne une expression SQL, pas des données
                print(f"📊 REDEVANCE: Appel de gc_exe.redevance_table('{sro}', '{troncon}')")
                redevance_query = "SELECT gc_exe.redevance_table(%s, %s)"
                cursor.execute(redevance_query, (sro, troncon))
                redevance_result = cursor.fetchone()
                
                if redevance_result:
                    # La fonction retourne une expression SQL du type "SELECT * FROM redevances_xxx"
                    redevance_sql_expression = redevance_result[0]  # Premier élément du tuple
                    print(f"📊 Expression SQL reçue: {redevance_sql_expression}")
                    
                    if redevance_sql_expression and redevance_sql_expression.strip():
                        # Exécuter l'expression SQL pour récupérer les vraies données
                        print("📊 Exécution de la requête REDEVANCE...")
                        cursor.execute(redevance_sql_expression)
                        redevance_data = cursor.fetchall()
                        print(f"✅ Données REDEVANCE récupérées: {len(redevance_data)} lignes")
                        
                        # Debug: Afficher les premières lignes pour vérifier
                        if redevance_data and len(redevance_data) > 0:
                            print(f"📊 Aperçu colonnes REDEVANCE: {list(dict(redevance_data[0]).keys()) if redevance_data else 'Aucune'}")
                    else:
                        print("⚠️ Expression SQL REDEVANCE vide")
                else:
                    print("⚠️ Aucune expression SQL REDEVANCE retournée")
                    
            except Exception as e:
                print(f"⚠️ Erreur récupération REDEVANCE: {str(e)}")
                # Ne pas faire échouer le DQE PGC si la redevance échoue
            
            # TRAITEMENT DES RÉSULTATS DQE PGC (code existant)
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
                    print(f"  -> ✅ AJOUTÉ AU RÉSULTAT")
                else:
                    print(f"  -> IGNORÉ (quantité=0 et pas d'IDs)")
            
            print(f"\n=== RÉSULTATS FINAUX PGC ===")
            print(f"Total résultats retenus: {len(results)}")
            for i, result in enumerate(results):
                print(f"{i+1}. {result.designation} | {result.quantite} {result.unite} | {len(result.ids)} IDs")
            
            # STOCKAGE DES DONNÉES REDEVANCE DANS LES RÉSULTATS
            # Stocker les données redevance dans un résultat spécial pour les récupérer plus tard
            if redevance_data:
                # Conversion des données redevance en format compatible
                redevance_converted = []
                for row in redevance_data:
                    row_dict = dict(row)
                    redevance_converted.append(row_dict)
                
                # Ajouter les données redevance comme métadonnées au premier résultat
                if results:
                    # Créer un attribut spécial pour stocker les données redevance
                    results[0].redevance_data = redevance_converted
                    print(f"📊 Données REDEVANCE attachées: {len(redevance_converted)} lignes")
            
            return results
            
        finally:
            conn.close()

    @staticmethod
    def get_redevance_data_only(sro: str, troncon: str) -> List[Dict]:
        """
        Récupère seulement les données REDEVANCE sans refaire FUNCTION_UP_GEST
        Utilisé pour régénérer l'Excel après correction manuelle de cm_gest_do
        """
        print(f"📊 RÉCUPÉRATION REDEVANCE SEULE pour {sro} / {troncon}")
        
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            raise RuntimeError("Paramètres DB non disponibles")
        
        redevance_data = []
        
        try:
            # Utiliser exactement la même méthode de connexion que execute_dqe_pgc
            conn = psycopg2.connect(
                host=db_params["host"],
                port=db_params["port"],
                database=db_params["database"],
                user=db_params["user"],
                password=db_params["password"]
            )
            
            # Utiliser DictCursor comme dans execute_dqe_pgc pour obtenir des dictionnaires
            cursor = conn.cursor(cursor_factory=DictCursor)
            print("✅ Connexion database établie pour récupération REDEVANCE")
            
            # Récupération données REDEVANCE SEULEMENT
            print("📊 REDEVANCE: récupération des données actualisées...")
            
            # CORRECTION: gc_exe.redevance_table() retourne une expression SQL, pas des données
            print(f"📊 REDEVANCE: Appel de gc_exe.redevance_table('{sro}', '{troncon}')")
            redevance_query = "SELECT gc_exe.redevance_table(%s, %s)"
            cursor.execute(redevance_query, (sro, troncon))
            redevance_result = cursor.fetchone()
            
            if redevance_result:
                # La fonction retourne une expression SQL du type "SELECT * FROM redevances_xxx"
                redevance_sql_expression = redevance_result[0]  # Premier élément du tuple
                print(f"📊 Expression SQL reçue: {redevance_sql_expression}")
                
                if redevance_sql_expression and redevance_sql_expression.strip():
                    # Exécuter l'expression SQL pour récupérer les vraies données
                    print("📊 Exécution de la requête REDEVANCE...")
                    cursor.execute(redevance_sql_expression)
                    redevance_raw = cursor.fetchall()
                    print(f"✅ Données REDEVANCE récupérées: {len(redevance_raw)} lignes")
                    
                    # Conversion des données redevance en format compatible (dictionnaires)
                    for row in redevance_raw:
                        row_dict = dict(row)  # DictCursor permet cette conversion
                        redevance_data.append(row_dict)
                    
                    # Debug: Afficher les premières lignes pour vérifier
                    if redevance_data and len(redevance_data) > 0:
                        print(f"📊 Aperçu colonnes REDEVANCE: {list(redevance_data[0].keys())}")
                        print(f"📊 Première ligne exemple: {redevance_data[0] if redevance_data else 'Aucune'}")
                else:
                    print("⚠️ Expression SQL REDEVANCE vide")
            else:
                print("⚠️ Aucune expression SQL REDEVANCE retournée")
                
        except Exception as e:
            print(f"💥 Erreur récupération REDEVANCE seule: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
            
        finally:
            try:
                if 'conn' in locals():
                    conn.close()
                    print("✅ Connexion database fermée")
            except:
                pass
                
        print(f"📊 REDEVANCE finale récupérée: {len(redevance_data)} lignes")
        return redevance_data

    @staticmethod
    def get_redevance_from_modified_gestionnaire(sro: str, troncon: str, modified_gestionnaire_data: List[Dict]) -> List[Dict]:
        """
        Calcule les redevances en utilisant les données modifiées de la couche gestionnaire
        """
        print(f"📊 CALCUL REDEVANCE avec données gestionnaire modifiées pour {sro} / {troncon}")
        print(f"📊 Données gestionnaire modifiées: {len(modified_gestionnaire_data)} lignes")
        
        db_params = DatabaseOperations.get_db_connection_params()
        if not db_params:
            raise RuntimeError("Paramètres DB non disponibles")
        
        redevance_data = []
        
        try:
            conn = psycopg2.connect(
                host=db_params["host"],
                port=db_params["port"],
                database=db_params["database"],
                user=db_params["user"],
                password=db_params["password"]
            )
            
            cursor = conn.cursor(cursor_factory=DictCursor)
            print("✅ Connexion database établie pour calcul redevance avec données modifiées")
            
            # Créer une table temporaire avec les données modifiées
            temp_table_name = f"temp_gestionnaire_modified_{int(time.time())}"
            print(f"📊 Création table temporaire: {temp_table_name}")
            
            # Créer la table temporaire
            create_temp_sql = f"""
            CREATE TEMP TABLE {temp_table_name} (
                troncon_gid integer,
                segment_id integer,
                cm_gest_do varchar,
                cm_compo varchar,
                long numeric(10,2),
                distance_route_m numeric(10,2),
                angle_parallelisme_deg numeric(10,2),
                confiance_niveau varchar,
                methode_attribution varchar
            )
            """
            cursor.execute(create_temp_sql)
            print(f"✅ Table temporaire {temp_table_name} créée")
            
            # Insérer les données modifiées
            insert_sql = f"""
            INSERT INTO {temp_table_name} 
            (troncon_gid, segment_id, cm_gest_do, cm_compo, long, distance_route_m, 
             angle_parallelisme_deg, confiance_niveau, methode_attribution)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            for row in modified_gestionnaire_data:
                cursor.execute(insert_sql, (
                    row.get('troncon_gid'),
                    row.get('segment_id'),
                    row.get('cm_gest_do'),
                    row.get('cm_compo'),
                    row.get('long'),
                    row.get('distance_route_m'),
                    row.get('angle_parallelisme_deg'),
                    row.get('confiance_niveau'),
                    row.get('methode_attribution')
                ))
            
            print(f"✅ {len(modified_gestionnaire_data)} lignes insérées dans {temp_table_name}")
            
            # D'abord obtenir toutes les compositions uniques pour créer les colonnes dynamiques
            compositions_sql = f"""
            SELECT DISTINCT cm_compo 
            FROM {temp_table_name}
            WHERE cm_compo IS NOT NULL
            ORDER BY cm_compo
            """
            
            cursor.execute(compositions_sql)
            compositions = [row[0] for row in cursor.fetchall()]
            print(f"📊 Compositions trouvées: {compositions}")
            
            # Générer les colonnes SQL dynamiquement
            colonnes_sql = ', '.join([
                f'SUM(CASE WHEN cm_compo = \'{compo}\' THEN quantite ELSE 0 END) as "{compo}"' 
                for compo in compositions
            ])
            
            # Maintenant calculer les redevances en format tabulaire
            # Adaptation de la logique de gc_exe.redevance_table() mais avec les données modifiées
            redevance_sql = f"""
            WITH extraction_alveoles AS (
                SELECT 
                    cm_gest_do as concessionnaire_voirie,
                    cm_compo,
                    CASE 
                        WHEN cm_compo LIKE '%+%' THEN 
                            CAST(split_part(cm_compo, '+', 1) AS INTEGER) + 
                            CAST(regexp_replace(split_part(split_part(cm_compo, '+', 2), ' ', 1), '[^0-9]', '', 'g') AS INTEGER)
                        ELSE 
                            CAST(regexp_replace(split_part(cm_compo, ' ', 1), '[^0-9]', '', 'g') AS INTEGER)
                    END as nb_alveoles,
                    long as long_plan
                FROM {temp_table_name}
                WHERE cm_compo IS NOT NULL AND cm_gest_do IS NOT NULL
            ),
            totaux_par_type AS (
                SELECT 
                    concessionnaire_voirie,
                    cm_compo,
                    ROUND(SUM(nb_alveoles * long_plan)::NUMERIC, 2) as quantite
                FROM extraction_alveoles
                GROUP BY concessionnaire_voirie, cm_compo
            )
            SELECT concessionnaire_voirie, {colonnes_sql}
            FROM totaux_par_type
            GROUP BY concessionnaire_voirie
            ORDER BY concessionnaire_voirie
            """
            
            cursor.execute(redevance_sql)
            redevance_raw = cursor.fetchall()
            print(f"✅ Redevances calculées avec données modifiées: {len(redevance_raw)} lignes")
            
            # Convertir en format compatible
            for row in redevance_raw:
                row_dict = dict(row)
                redevance_data.append(row_dict)
            
            # Debug
            if redevance_data:
                print(f"📊 Aperçu colonnes REDEVANCE modifiées: {list(redevance_data[0].keys())}")
                print(f"📊 Première ligne exemple: {redevance_data[0] if redevance_data else 'Aucune'}")
                
        except Exception as e:
            print(f"💥 Erreur calcul redevance avec données modifiées: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
            
        finally:
            try:
                if 'conn' in locals():
                    conn.close()
                    print("✅ Connexion database fermée")
            except:
                pass
                
        print(f"📊 REDEVANCE finale (modifiée) calculée: {len(redevance_data)} lignes")
        return redevance_data

    @staticmethod
    def get_redevance_from_results(sro, troncon, results):
        """Récupère les données de redevance depuis les résultats DQE PGC existants"""
        try:
            print(f"📊 Récupération redevances en mode direct pour SRO {sro}, tronçon {troncon}")
            
            # Chercher le premier résultat contenant des données de redevance
            redevance_data = []
            
            for result in results:
                if hasattr(result, 'redevance_data') and result.redevance_data:
                    redevance_data = result.redevance_data
                    print(f"✅ Données redevance trouvées dans résultat '{result.designation}': {len(redevance_data)} lignes")
                    break
            
            if not redevance_data:
                # Si pas de données redevance dans les résultats, calculer depuis la base
                print("⚠️ Aucune donnée redevance trouvée dans les résultats, calcul depuis base...")
                redevance_data = DatabaseOperations.get_redevance_data_only(sro, troncon)
            
            return redevance_data
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des données redevance: {str(e)}")
            import traceback
            traceback.print_exc()
            return []
