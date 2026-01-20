-- FUNCTION: dqe.dqe_recover(text, text, text, text)

-- DROP FUNCTION IF EXISTS dqe.dqe_recover(text, text, text, text);

CREATE OR REPLACE FUNCTION dqe.dqe_recover(
	p_sro text,
	p_projet text,
	p_version_projet text,
	p_schema_name text DEFAULT 'dqe'::text)
    RETURNS void
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    v_id integer;
    v_json jsonb;
    v_categorie text;
    v_features jsonb;
    v_feature jsonb;
    v_first_feature jsonb;
    v_columns text[];
    v_column_names text;
    v_column_defs text;
    v_sql text;
    v_values text;
    v_srid integer := 2154;  -- SRID par défaut (RGF93 / Lambert-93)
    v_geom_type text;
    v_count integer := 0;
    v_categories text[];
    v_audit_timestamp timestamp;
    v_user_name text;
    v_validation_info text;
BEGIN
    -- Vérifier si le schéma existe, sinon le créer
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I;', p_schema_name);
    
    -- Récupérer toutes les catégories uniques pour ce SRO, projet et version
    SELECT array_agg(DISTINCT categorie) INTO v_categories
    FROM dqe.dqejson
    WHERE sro = p_sro 
      AND projet = p_projet 
      AND version_projet = p_version_projet;
    
    IF v_categories IS NULL OR array_length(v_categories, 1) = 0 THEN
        RAISE EXCEPTION 'Aucune donnée trouvée pour SRO=%, Projet=%, Version=%', p_sro, p_projet, p_version_projet;
    END IF;
    
    -- Pour chaque catégorie, créer une table
    FOREACH v_categorie IN ARRAY v_categories
    LOOP
        -- Récupérer l'ID le plus récent pour cette catégorie
        SELECT id, audit_timestamp, user_name INTO v_id, v_audit_timestamp, v_user_name
        FROM dqe.dqejson
        WHERE sro = p_sro 
          AND projet = p_projet 
          AND version_projet = p_version_projet
          AND categorie = v_categorie
        ORDER BY audit_timestamp DESC
        LIMIT 1;
        
        -- Formater les informations de validation
        v_validation_info := format('DQE SRO=%s, Projet=%s, Version=%s Validé par "%s" le %s à %s',
                                   p_sro, p_projet, p_version_projet,
                                   v_user_name,
                                   to_char(v_audit_timestamp, 'DD/MM/YYYY'),
                                   to_char(v_audit_timestamp, 'HH24:MI:SS'));
        
        -- Récupérer les données JSON
        SELECT champs::jsonb INTO v_json 
        FROM dqe.dqejson 
        WHERE id = v_id;
        
        IF v_json IS NULL THEN
            RAISE WARNING 'Données JSON vides pour la catégorie %', v_categorie;
            CONTINUE;
        END IF;
        
        -- Extraire le tableau de features
        v_features := v_json->'features';
        
        -- S'assurer qu'il y a au moins une feature
        IF jsonb_array_length(v_features) = 0 THEN
            RAISE WARNING 'Aucune feature trouvée pour la catégorie %', v_categorie;
            CONTINUE;
        END IF;
        
        -- Récupérer la première feature pour déterminer les colonnes
        v_first_feature := v_features->0;
        
        -- Déterminer le type de géométrie à partir de la première feature
        IF v_first_feature->>'geom' LIKE 'Point%' THEN
            v_geom_type := 'Point';
        ELSIF v_first_feature->>'geom' LIKE 'LineString%' THEN
            v_geom_type := 'LineString';
        ELSIF v_first_feature->>'geom' LIKE 'Polygon%' THEN
            v_geom_type := 'Polygon';
        ELSIF v_first_feature->>'geom' LIKE 'MultiPoint%' THEN
            v_geom_type := 'MultiPoint';
        ELSIF v_first_feature->>'geom' LIKE 'MultiLineString%' THEN
            v_geom_type := 'MultiLineString';
        ELSIF v_first_feature->>'geom' LIKE 'MultiPolygon%' THEN
            v_geom_type := 'MultiPolygon';
        ELSE
            v_geom_type := 'GEOMETRY';
        END IF;
        
        -- Créer la liste des colonnes (sauf geom qui sera traitée séparément)
        SELECT array_agg(key) INTO v_columns
        FROM jsonb_object_keys(v_first_feature) key
        WHERE key != 'geom';
        
        -- Préparer les définitions de colonnes (toutes en TEXT par simplification)
        WITH column_def AS (
            SELECT col, 
                format('%I text', col) AS col_def
            FROM unnest(v_columns) AS col
        )
        SELECT string_agg(col_def, ', ') INTO v_column_defs
        FROM column_def;
        
        -- Préparer la liste des noms de colonnes pour INSERT
        WITH column_name AS (
            SELECT col, 
                format('%I', col) AS col_name
            FROM unnest(v_columns) AS col
        )
        SELECT string_agg(col_name, ', ') INTO v_column_names
        FROM column_name;
        
        -- Créer la table
        v_sql := format('
            DROP TABLE IF EXISTS %I.%I;
            CREATE TABLE %I.%I (
                id serial PRIMARY KEY,
                %s,
                geom geometry(%s, %s)
            );
            COMMENT ON TABLE %I.%I IS ''%s'';
        ', 
        p_schema_name, v_categorie, 
        p_schema_name, v_categorie, 
        v_column_defs, 
        v_geom_type, v_srid,
        p_schema_name, v_categorie,
        v_validation_info);
        
        EXECUTE v_sql;
        
        -- Insérer les données
        FOR i IN 0..jsonb_array_length(v_features)-1 LOOP
            v_feature := v_features->i;
            
            -- Préparer les valeurs pour INSERT
            WITH col_values AS (
                SELECT 
                    col, 
                    CASE 
                        WHEN v_feature->>col = 'NULL' THEN NULL 
                        ELSE v_feature->>col 
                    END AS val
                FROM unnest(v_columns) AS col
            )
            SELECT string_agg(
                CASE WHEN val IS NULL THEN 'NULL' ELSE quote_literal(val) END,
                ', '
            ) INTO v_values
            FROM col_values;
            
            -- Insérer dans la table
            v_sql := format('
                INSERT INTO %I.%I (%s, geom)
                VALUES (%s, ST_GeomFromText(%L, %s));
            ',
            p_schema_name, v_categorie,
            v_column_names, v_values,
            v_feature->>'geom', v_srid);
            
            EXECUTE v_sql;
        END LOOP;
        
        RAISE NOTICE 'Table %I.%I créée avec succès.', p_schema_name, v_categorie;
        v_count := v_count + 1;
    END LOOP;
    
    -- Résumé final
    RAISE NOTICE '% tables ont été créées dans le schéma %:', v_count, p_schema_name;
    FOR i IN 1..array_length(v_categories, 1) LOOP
        RAISE NOTICE '- %I.%I', p_schema_name, v_categories[i];
    END LOOP;
END;
$BODY$;

ALTER FUNCTION dqe.dqe_recover(text, text, text, text)
    OWNER TO yadda;

GRANT EXECUTE ON FUNCTION dqe.dqe_recover(text, text, text, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION dqe.dqe_recover(text, text, text, text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION dqe.dqe_recover(text, text, text, text) TO yadda;

