-- FUNCTION: dqe.dqe_recover(text, text, text, text)
-- Reconstruit les tables depuis les données archivées dans dqejson.champs
-- Inspiré de rip_avg_nge.recover() - utilise le JSON stocké directement
-- Formats gérés:
--   1. dqe_result: [{designation, quantite, unite, ids}, ...] → table sans géométrie
--   2. FeatureCollection: {features: [{geometry, attributes}]} → table avec géométrie

-- DROP FUNCTION IF EXISTS dqe.dqe_recover(text, text, text, text);

CREATE OR REPLACE FUNCTION dqe.dqe_recover(
    p_sro text,
    p_projet text,
    p_version_projet text DEFAULT NULL,
    p_schema_name text DEFAULT 'dqe_recover')
RETURNS TABLE (
    table_name text,
    table_type text,
    geom_type text,
    row_count integer,
    message text
)
LANGUAGE 'plpgsql'
COST 100
VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_rec RECORD;
    v_json jsonb;
    v_json_type text;
    v_features jsonb;
    v_feature jsonb;
    v_first_feature jsonb;
    v_table_name text;
    v_row_count integer;
    v_validation_info text;
    v_result_item jsonb;
    v_sql text;
    v_srid integer := 2154;
    v_crs text;
    v_geom_type text;
    v_columns text[];
    v_column_names text;
    v_column_defs text;
    v_values text;
    i integer;
BEGIN
    -- Init schema
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I;', p_schema_name);
    
    -- Boucle sur toutes les entrées dqejson pour ce SRO/projet
    FOR v_rec IN 
        SELECT id, categorie, champs, audit_timestamp, user_name, nom_dqe
        FROM dqe.dqejson
        WHERE sro = p_sro 
          AND projet = p_projet 
          AND (p_version_projet IS NULL OR version_projet = p_version_projet)
        ORDER BY audit_timestamp DESC
    LOOP
        v_json := v_rec.champs::jsonb;
        
        IF v_json IS NULL THEN
            CONTINUE;
        END IF;
        
        v_validation_info := format('Récupéré depuis DQE %s validé par %s le %s',
            v_rec.nom_dqe, v_rec.user_name, 
            to_char(v_rec.audit_timestamp, 'DD/MM/YYYY HH24:MI'));
        
        -- Détecter le type de données
        v_json_type := jsonb_typeof(v_json);
        
        -- FORMAT 1: Liste JSON (dqe_result) - Créer table de résultats sans géométrie
        -- Les géométries sont dans les FeatureCollection séparées (categorie = nom_couche)
        IF v_json_type = 'array' THEN
            
            v_table_name := 'dqe_' || regexp_replace(lower(v_rec.categorie), '[^a-z0-9_]', '_', 'g');
            v_table_name := substring(v_table_name from 1 for 60);
            
            -- Créer table de résultats DQE (sans géométrie)
            v_sql := format('
                DROP TABLE IF EXISTS %I.%I CASCADE;
                CREATE TABLE %I.%I (
                    id serial PRIMARY KEY,
                    designation text,
                    quantite numeric,
                    unite text,
                    ids text
                );
                COMMENT ON TABLE %I.%I IS %L;
            ', p_schema_name, v_table_name,
               p_schema_name, v_table_name,
               p_schema_name, v_table_name, v_validation_info);
            
            EXECUTE v_sql;
            
            -- Insérer les données
            v_row_count := 0;
            FOR v_result_item IN SELECT * FROM jsonb_array_elements(v_json)
            LOOP
                EXECUTE format('
                    INSERT INTO %I.%I (designation, quantite, unite, ids)
                    VALUES ($1, $2, $3, $4);
                ', p_schema_name, v_table_name)
                USING COALESCE(v_result_item->>'designation', v_result_item->>'Désignation'),
                      COALESCE(
                          (v_result_item->>'quantite')::numeric,
                          (v_result_item->>'Quantité')::numeric,
                          0
                      ),
                      COALESCE(v_result_item->>'unite', v_result_item->>'Unité'),
                      v_result_item->>'ids';
                
                v_row_count := v_row_count + 1;
            END LOOP;
            
            table_name := v_table_name;
            table_type := 'dqe_result';
            geom_type := NULL;  -- Pas de géométrie
            row_count := v_row_count;
            message := format('Table résultats %I.%I créée (%s lignes)', p_schema_name, v_table_name, v_row_count);
            RETURN NEXT;
            
        -- FORMAT 2: FeatureCollection (câbles découpés avec géométries)
        ELSIF v_json_type = 'object' AND v_json->>'type' = 'FeatureCollection' THEN
            v_features := v_json->'features';
            v_crs := COALESCE(v_json->>'crs', 'EPSG:2154');
            
            -- Extraire SRID du CRS
            IF v_crs ~ 'EPSG:([0-9]+)' THEN
                v_srid := (regexp_match(v_crs, 'EPSG:([0-9]+)'))[1]::integer;
            ELSE
                v_srid := 2154;
            END IF;
            
            IF v_features IS NULL OR jsonb_array_length(v_features) = 0 THEN
                table_name := v_rec.categorie;
                table_type := 'FeatureCollection';
                geom_type := NULL;
                row_count := 0;
                message := 'Aucune feature';
                RETURN NEXT;
                CONTINUE;
            END IF;
            
            -- Nettoyer nom de table
            v_table_name := regexp_replace(lower(v_rec.categorie), '[^a-z0-9_]', '_', 'g');
            v_table_name := regexp_replace(v_table_name, '^[0-9]', 'n', 'g');
            
            -- Première feature pour structure
            v_first_feature := v_features->0;
            
            -- Détecter type géométrie
            IF v_first_feature->>'geometry' LIKE 'POINT%' OR v_first_feature->>'geometry' LIKE 'Point%' THEN
                v_geom_type := 'Point';
            ELSIF v_first_feature->>'geometry' LIKE 'LINE%' OR v_first_feature->>'geometry' LIKE 'Line%' THEN
                v_geom_type := 'LineString';
            ELSIF v_first_feature->>'geometry' LIKE 'MULTI%LINE%' THEN
                v_geom_type := 'MultiLineString';
            ELSIF v_first_feature->>'geometry' LIKE 'POLYGON%' OR v_first_feature->>'geometry' LIKE 'Polygon%' THEN
                v_geom_type := 'Polygon';
            ELSE
                v_geom_type := 'Geometry';
            END IF;
            
            -- Extraire colonnes depuis attributes
            SELECT array_agg(key) INTO v_columns
            FROM jsonb_object_keys(COALESCE(v_first_feature->'attributes', '{}'::jsonb)) key;
            
            IF v_columns IS NULL OR array_length(v_columns, 1) IS NULL THEN
                v_columns := ARRAY['fid'];
                v_column_defs := 'fid integer';
            ELSE
                SELECT string_agg(format('%I text', col), ', ') INTO v_column_defs
                FROM unnest(v_columns) AS col;
            END IF;
            
            SELECT string_agg(format('%I', col), ', ') INTO v_column_names
            FROM unnest(v_columns) AS col;
            
            -- Créer table
            v_sql := format('
                DROP TABLE IF EXISTS %I.%I CASCADE;
                CREATE TABLE %I.%I (
                    id serial PRIMARY KEY,
                    %s,
                    geom geometry(%s, %s)
                );
                COMMENT ON TABLE %I.%I IS %L;
            ', p_schema_name, v_table_name,
               p_schema_name, v_table_name,
               v_column_defs, v_geom_type, v_srid,
               p_schema_name, v_table_name, v_validation_info);
            
            EXECUTE v_sql;
            
            -- Insérer features
            v_row_count := 0;
            FOR i IN 0..jsonb_array_length(v_features)-1 LOOP
                v_feature := v_features->i;
                
                -- Préparer valeurs
                WITH col_vals AS (
                    SELECT col,
                        COALESCE(v_feature->'attributes'->>col, '') AS val
                    FROM unnest(v_columns) AS col
                )
                SELECT string_agg(quote_literal(val), ', ') INTO v_values
                FROM col_vals;
                
                -- Insert avec géométrie
                v_sql := format('
                    INSERT INTO %I.%I (%s, geom)
                    VALUES (%s, ST_GeomFromText(%L, %s));
                ', p_schema_name, v_table_name,
                   v_column_names, v_values,
                   v_feature->>'geometry', v_srid);
                
                BEGIN
                    EXECUTE v_sql;
                    v_row_count := v_row_count + 1;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'Erreur insertion feature %: %', i, SQLERRM;
                END;
            END LOOP;
            
            -- Index spatial
            EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I USING GIST (geom);',
                v_table_name || '_geom_idx', p_schema_name, v_table_name);
            
            table_name := v_table_name;
            table_type := 'FeatureCollection';
            geom_type := v_geom_type;  -- Type détecté depuis WKT
            row_count := v_row_count;
            message := format('Table %I.%I créée avec %s features (%s)', p_schema_name, v_table_name, v_row_count, v_geom_type);
            RETURN NEXT;
            
        -- FORMAT 3: Ancien format sql_result (dict avec type='sql_result')
        ELSIF v_json_type = 'object' AND v_json->>'type' = 'sql_result' THEN
            -- Ignorer - format déprécié, juste log
            table_name := v_rec.categorie;
            table_type := 'sql_result_legacy';
            geom_type := NULL;
            row_count := 0;
            message := 'Format ancien (ignoré)';
            RETURN NEXT;
            
        ELSE
            table_name := v_rec.categorie;
            table_type := 'unknown';
            geom_type := NULL;
            row_count := 0;
            message := format('Format non reconnu: %s', v_json_type);
            RETURN NEXT;
        END IF;
        
    END LOOP;
    
    RETURN;
END;
$BODY$;

ALTER FUNCTION dqe.dqe_recover(text, text, text, text)
    OWNER TO yadda;

GRANT EXECUTE ON FUNCTION dqe.dqe_recover(text, text, text, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION dqe.dqe_recover(text, text, text, text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION dqe.dqe_recover(text, text, text, text) TO yadda;
