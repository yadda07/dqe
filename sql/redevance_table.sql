-- FUNCTION: gc_exe.redevance_table(text, text)

-- DROP FUNCTION IF EXISTS gc_exe.redevance_table(text, text);

CREATE OR REPLACE FUNCTION gc_exe.redevance_table(
	p_sro text,
	p_gc text)
    RETURNS text
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    colonnes_sql TEXT;
    colonnes_def TEXT;
    sql_create TEXT;
    sql_insert TEXT;
    table_name TEXT;
    v_has_aerien BOOLEAN;
    v_has_souterrain BOOLEAN;
    v_is_mixte BOOLEAN;
BEGIN
    -- Nom de table temporaire unique (sans caractères spéciaux)
    table_name := 'redevances_' || to_char(now(), 'YYYY_MM_DD_HH24_MI_SS') || '_' || extract(microseconds from now())::bigint;
    
    -- Détecter la présence d'infrastructure aérienne (cm_typ_imp = 0)
    SELECT EXISTS(
        SELECT 1 
        FROM gc_exe.gestionnaire(p_sro, p_gc) g 
        WHERE g.cm_typ_imp = 0
    ) INTO v_has_aerien;
    
    -- Détecter la présence d'infrastructure souterraine (cm_typ_imp != 0)
    SELECT EXISTS(
        SELECT 1 
        FROM gc_exe.gestionnaire(p_sro, p_gc) g 
        WHERE g.cm_typ_imp != 0 AND g.cm_compo IS NOT NULL
    ) INTO v_has_souterrain;
    
    -- Infrastructure mixte si on a les deux types
    v_is_mixte := v_has_aerien AND v_has_souterrain;
    
    IF v_is_mixte THEN
        -- Infrastructure mixte : colonnes poteaux + alvéoles dynamiques
        SELECT 
            'SUM(nb_poteaux) as "Poteaux", SUM(longueur) as "Aérien", ' || string_agg('SUM(CASE WHEN cm_compo = ''' || cm_compo || ''' THEN quantite ELSE 0 END) as "' || cm_compo || '"', ', ' ORDER BY cm_compo),
            'concessionnaire_voirie TEXT, "Poteaux" NUMERIC, "Aérien" NUMERIC, ' || string_agg('"' || cm_compo || '" NUMERIC', ', ' ORDER BY cm_compo)
        INTO colonnes_sql, colonnes_def
        FROM (
            SELECT DISTINCT g.cm_compo 
            FROM gc_exe.gestionnaire(p_sro, p_gc) g
            WHERE g.cm_compo IS NOT NULL 
            AND g.cm_compo ~ '[0-9]'
            AND g.cm_compo != 'Aérien'
        ) t;
    ELSIF v_has_aerien AND NOT v_has_souterrain THEN
        -- Infrastructure purement aérienne : colonnes "Poteaux" et "Aérien"
        colonnes_sql := 'SUM(nb_poteaux) as "Poteaux", SUM(longueur) as "Aérien"';
        colonnes_def := 'concessionnaire_voirie TEXT, "Poteaux" NUMERIC, "Aérien" NUMERIC';
    ELSE
        -- Infrastructure purement souterraine : colonnes dynamiques basées sur cm_compo
        SELECT 
            string_agg('SUM(CASE WHEN cm_compo = ''' || cm_compo || ''' THEN quantite ELSE 0 END) as "' || cm_compo || '"', ', ' ORDER BY cm_compo),
            'concessionnaire_voirie TEXT, ' || string_agg('"' || cm_compo || '" NUMERIC', ', ' ORDER BY cm_compo)
        INTO colonnes_sql, colonnes_def
        FROM (
            SELECT DISTINCT g.cm_compo 
            FROM gc_exe.gestionnaire(p_sro, p_gc) g
            WHERE g.cm_compo IS NOT NULL 
            AND g.cm_compo ~ '[0-9]'
            AND g.cm_compo != 'Aérien'
        ) t;
    END IF;
    
    -- Créer la table temporaire
    sql_create := 'CREATE TEMP TABLE ' || table_name || ' (' || colonnes_def || ')';
    EXECUTE sql_create;
    
    -- Insérer les données en utilisant gestionnaire()
    IF v_is_mixte THEN
        -- Infrastructure mixte : poteaux + alvéoles
        sql_insert := 'INSERT INTO ' || table_name || '
        WITH totaux_aeriens AS (
            SELECT 
                g.cm_gest_do as concessionnaire_voirie,
                SUM(g.nb_pot_ac) as nb_poteaux,
                ROUND(SUM(g.long)::NUMERIC, 2) as longueur
            FROM gc_exe.gestionnaire(''' || p_sro || ''', ''' || p_gc || ''') g
            WHERE g.cm_gest_do IS NOT NULL AND g.cm_typ_imp = 0
            GROUP BY g.cm_gest_do
        ),
        extraction_alveoles AS (
            SELECT 
                g.cm_gest_do as concessionnaire_voirie,
                g.cm_compo,
                CASE 
                    WHEN g.cm_compo LIKE ''%+%'' THEN 
                        CAST(split_part(g.cm_compo, ''+'', 1) AS INTEGER) + 
                        CAST(regexp_replace(split_part(split_part(g.cm_compo, ''+'', 2), '' '', 1), ''[^0-9]'', '''', ''g'') AS INTEGER)
                    ELSE 
                        CAST(regexp_replace(split_part(g.cm_compo, '' '', 1), ''[^0-9]'', '''', ''g'') AS INTEGER)
                END as nb_alveoles,
                g.long as long_plan
            FROM gc_exe.gestionnaire(''' || p_sro || ''', ''' || p_gc || ''') g
            WHERE g.cm_compo IS NOT NULL 
            AND g.cm_gest_do IS NOT NULL
            AND g.cm_compo ~ ''[0-9]''
        ),
        totaux_souterrains AS (
            SELECT 
                concessionnaire_voirie,
                cm_compo,
                ROUND(SUM(nb_alveoles * long_plan)::NUMERIC, 2) as quantite
            FROM extraction_alveoles
            GROUP BY concessionnaire_voirie, cm_compo
        ),
        totaux_combines AS (
            SELECT 
                COALESCE(a.concessionnaire_voirie, s.concessionnaire_voirie) as concessionnaire_voirie,
                COALESCE(a.nb_poteaux, 0) as nb_poteaux,
                COALESCE(a.longueur, 0) as longueur,
                s.cm_compo,
                COALESCE(s.quantite, 0) as quantite
            FROM totaux_aeriens a
            FULL OUTER JOIN totaux_souterrains s ON a.concessionnaire_voirie = s.concessionnaire_voirie
        )
        SELECT concessionnaire_voirie, ' || colonnes_sql || '
        FROM totaux_combines
        GROUP BY concessionnaire_voirie
        ORDER BY concessionnaire_voirie';
    ELSIF v_has_aerien AND NOT v_has_souterrain THEN
        -- Infrastructure purement aérienne : compter les poteaux et longueurs par concessionnaire
        sql_insert := 'INSERT INTO ' || table_name || '
        WITH totaux_aeriens AS (
            SELECT 
                g.cm_gest_do as concessionnaire_voirie,
                SUM(g.nb_pot_ac) as nb_poteaux,
                ROUND(SUM(g.long)::NUMERIC, 2) as longueur
            FROM gc_exe.gestionnaire(''' || p_sro || ''', ''' || p_gc || ''') g
            WHERE g.cm_gest_do IS NOT NULL AND g.cm_typ_imp = 0
            GROUP BY g.cm_gest_do
        )
        SELECT concessionnaire_voirie, nb_poteaux, longueur
        FROM totaux_aeriens
        ORDER BY concessionnaire_voirie';
    ELSE
        -- Infrastructure purement souterraine : logique actuelle avec cm_compo
        sql_insert := 'INSERT INTO ' || table_name || '
        WITH extraction_alveoles AS (
            SELECT 
                g.cm_gest_do as concessionnaire_voirie,
                g.cm_compo,
                CASE 
                    WHEN g.cm_compo LIKE ''%+%'' THEN 
                        CAST(split_part(g.cm_compo, ''+'', 1) AS INTEGER) + 
                        CAST(regexp_replace(split_part(split_part(g.cm_compo, ''+'', 2), '' '', 1), ''[^0-9]'', '''', ''g'') AS INTEGER)
                    ELSE 
                        CAST(regexp_replace(split_part(g.cm_compo, '' '', 1), ''[^0-9]'', '''', ''g'') AS INTEGER)
                END as nb_alveoles,
                g.long as long_plan
            FROM gc_exe.gestionnaire(''' || p_sro || ''', ''' || p_gc || ''') g
            WHERE g.cm_compo IS NOT NULL 
            AND g.cm_gest_do IS NOT NULL
            AND g.cm_compo ~ ''[0-9]''
        ),
        totaux_par_type AS (
            SELECT 
                concessionnaire_voirie,
                cm_compo,
                ROUND(SUM(nb_alveoles * long_plan)::NUMERIC, 2) as quantite
            FROM extraction_alveoles
            GROUP BY concessionnaire_voirie, cm_compo
        )
        SELECT concessionnaire_voirie, ' || colonnes_sql || '
        FROM totaux_par_type
        GROUP BY concessionnaire_voirie
        ORDER BY concessionnaire_voirie';
    END IF;
    
    EXECUTE sql_insert;
    
    RETURN 'SELECT * FROM ' || table_name;
END 
$BODY$;

ALTER FUNCTION gc_exe.redevance_table(text, text)
    OWNER TO yadda;

GRANT EXECUTE ON FUNCTION gc_exe.redevance_table(text, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION gc_exe.redevance_table(text, text) TO auvergne_sch_etudes;
ès 
GRANT EXECUTE ON FUNCTION gc_exe.redevance_table(text, text) TO yadda;

