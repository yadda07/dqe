-- FUNCTION: rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text)

-- DROP FUNCTION IF EXISTS rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text);

CREATE OR REPLACE FUNCTION rip_avg_nge.recover(
	p_schema_name text,
	p_table_name text,
	p_operation character varying,
	p_start_time timestamp without time zone,
	p_end_time timestamp without time zone,
	p_limit integer DEFAULT NULL::integer,
	p_user_filter text DEFAULT NULL::text)
    RETURNS void
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    query TEXT;
    audit_table TEXT;
    temp_table_name TEXT;
    limit_clause TEXT := '';
BEGIN
    CASE p_schema_name
        WHEN 'rip_avg_nge' THEN audit_table := 'rip_avg_json';
        WHEN 'rbal' THEN audit_table := 'rbal_json';
        WHEN 'geofibre' THEN audit_table := 'geofibre_json';
        WHEN 'aerien' THEN audit_table := 'aerien_json';
        WHEN 'gc_exe' THEN audit_table := 'gc_exe_json';
        WHEN 'gc' THEN audit_table := 'gc_json';
        WHEN 'aiguillage et POT' THEN audit_table := 'aig_pot_json';
        ELSE
            RAISE EXCEPTION 'Aucune table d''audit définie pour le schéma %.', p_schema_name;
    END CASE;
    -- Validation optimisée de l'existence de la table d'audit
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'suppresions' AND c.relname = audit_table AND c.relkind = 'r'
    ) THEN
        RAISE EXCEPTION 'La table d''audit % n''existe pas dans suppresions.', audit_table;
    END IF;
    temp_table_name := format('temp_%s_%s', p_schema_name, p_table_name);
    EXECUTE format('DROP TABLE IF EXISTS %I', temp_table_name);
    IF p_limit IS NOT NULL THEN
        limit_clause := format(' LIMIT %s', p_limit);
    END IF;
    EXECUTE format(
        'CREATE TEMP TABLE %I (LIKE %I.%I)',
        temp_table_name, p_schema_name, p_table_name
    );
    
    -- Ajouter les colonnes d'audit
    EXECUTE format(
        'ALTER TABLE %I ADD COLUMN user_name VARCHAR(255), ADD COLUMN audit_timestamp TIMESTAMP',
        temp_table_name
    );
    
    -- Insertion directe sans table temporaire intermédiaire pour optimiser les performances
    EXECUTE format(
        'INSERT INTO %I 
         SELECT (jsonb_populate_record(NULL::%I.%I, a.old_values)).*, a.user_name, a.audit_timestamp
         FROM suppresions.%I a
         WHERE a.table_name = %L 
         AND a.operation_type = %L 
         AND a.audit_timestamp BETWEEN %L AND %L
         AND (%L IS NULL OR a.user_name = %L)
         ORDER BY a.audit_timestamp DESC%s',
        temp_table_name, p_schema_name, p_table_name,
        audit_table,
        p_table_name, p_operation,
        p_start_time, p_end_time,
        p_user_filter, p_user_filter,
        limit_clause
    );
    
    RAISE NOTICE 'Données récupérées avec succès dans %', temp_table_name;
END;
$BODY$;

ALTER FUNCTION rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text)
    OWNER TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text) TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.recover(text, text, character varying, timestamp without time zone, timestamp without time zone, integer, text) TO sdupays;

