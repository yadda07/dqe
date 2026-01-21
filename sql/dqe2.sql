-- FUNCTION: rip_avg_nge.dqe2(text, text, text)
-- p_blocage: NULL/'E' (standard), 'T' (travaux sans blocage), 'B' (blocage uniquement)

-- Supprimer l'ancienne version 2 params pour éviter conflit de signature
DROP FUNCTION IF EXISTS rip_avg_nge.dqe2(text, text);
-- DROP FUNCTION IF EXISTS rip_avg_nge.dqe2(text, text, text);

CREATE OR REPLACE FUNCTION rip_avg_nge.dqe2(
	p_sro text,
	p_type text DEFAULT NULL::text,
	p_blocage text DEFAULT NULL::text)
    RETURNS TABLE("Désignation" text, "Unité" text, "Quantité" numeric, ids text) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
    v_transport BOOLEAN := FALSE;
    v_distribution BOOLEAN := FALSE;
BEGIN
    IF p_type IS NULL OR p_type = 'T' THEN
        SELECT COUNT(*) > 0 INTO v_transport
        FROM rip_avg_nge.cables 
        WHERE projet_tr = p_sro
        AND (p_blocage IS NULL OR p_blocage = 'E' 
             OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
             OR (p_blocage = 'B' AND blocage_ran = true));
    END IF;
    
    IF p_type IS NULL OR p_type = 'D' THEN
        SELECT COUNT(*) > 0 INTO v_distribution
        FROM rip_avg_nge.cables 
        WHERE cab_type = 'CDI' and sro = p_sro
        AND (p_blocage IS NULL OR p_blocage = 'E' 
             OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
             OR (p_blocage = 'B' AND blocage_ran = true));
    END IF;

    RETURN QUERY
    WITH 
    base_data AS (
        SELECT
            gid, cab_capa,
            ST_Length(geom) AS longueur,
            geom
        FROM rip_avg_nge.cables
        WHERE projet_tr = p_sro AND "DCE" ='O'
        AND (p_blocage IS NULL OR p_blocage = 'E' 
             OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
             OR (p_blocage = 'B' AND blocage_ran = true))
    ),
    transport_cable_gids AS (
        SELECT cab_capa AS cap, string_agg(gid::text, ',') AS gids,
               ROUND(SUM(longueur)::numeric, 2) AS total_length
        FROM base_data
        GROUP BY cab_capa
    ),
    gc_to_create AS (
        WITH filtered_data AS (
            SELECT 
                gid,
                ST_Length(geom) AS length
            FROM rip_avg_nge.t_cheminement
            WHERE (
                (projet_tr = p_sro AND cm_typelog IN ('TD', 'TR') AND cm_avct = 'C' AND (p_type IS NULL OR p_type = 'T'))
                OR
                (sro = p_sro AND cm_typelog = 'DI' AND cm_avct = 'C' AND cm_typ_imp IN ('7','0') 
                 AND dce = 'O' AND affectation != '3'
                 AND (p_type IS NULL OR p_type = 'D'))
            )
            AND (p_blocage IS NULL OR p_blocage = 'E' 
                 OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
                 OR (p_blocage = 'B' AND blocage_ran = true))
        )
        SELECT 
            COALESCE(SUM(length), 0) AS length,
            string_agg(gid::text, ',') AS gids
        FROM filtered_data
    ),
    existing_aerial AS (
        SELECT COALESCE(SUM(ST_Length(geom)), 0) AS length,
               string_agg(gid::text, ',') AS gids
        FROM rip_avg_nge.t_cheminement
        WHERE sro ILIKE '%' || p_sro || '%'
        AND cm_typelog IN ('DI')
        AND cm_avct = 'E'
        AND cm_typ_imp in ('0','1') AND dce = 'O' AND affectation != '3'
        AND (p_type IS NULL OR p_type = 'D')
        AND (p_blocage IS NULL OR p_blocage = 'E' 
             OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
             OR (p_blocage = 'B' AND blocage_ran = true))
    ),
    pep_transport AS (
        SELECT 
            CASE 
                WHEN noe_pose LIKE 'CHB%' THEN 'SOUTERRAIN'
                WHEN noe_pose LIKE 'POT%' THEN 'AERIEN'
                WHEN noe_pose LIKE 'FAC%' THEN 'FACADE'
                WHEN noe_pose LIKE 'IMM%' OR noe_pose = 'IMM' THEN 'IMM' 
                ELSE noe_pose
            END AS pose_type,
            CASE
                WHEN c_tr.max_cap <= 12 THEN 12
                WHEN c_tr.max_cap <= 24 THEN 24
                WHEN c_tr.max_cap <= 36 THEN 36
                WHEN c_tr.max_cap <= 48 THEN 48
                WHEN c_tr.max_cap <= 72 THEN 72
                WHEN c_tr.max_cap <= 96 THEN 96
                WHEN c_tr.max_cap <= 144 THEN 144
                WHEN c_tr.max_cap <= 288 THEN 288
                WHEN c_tr.max_cap <= 432 THEN 432
                WHEN c_tr.max_cap <= 576 THEN 576
                ELSE 720
            END AS capacity,
            COUNT(*) AS quantity,
            string_agg(b.gid::text, ',') AS gids
        FROM 
            rip_avg_nge.bpe b
        LEFT JOIN LATERAL (
            SELECT MAX(c.cab_capa) AS max_cap
            FROM rip_avg_nge.cables c 
            WHERE ST_dwithin(b.geom, c.geom,0.2) AND c.nro IS NOT NULL
        ) c_tr ON true
        WHERE 
    b.projet_tr = p_sro
    AND b.noe_type = 'PEP' AND "DCE" = 'O'
    AND NOT EXISTS (
        SELECT 1 
        FROM rip_avg_nge.cables c 
        WHERE ST_Intersects(b.geom, c.geom) 
            AND c.fon = 'Oui'
    )
    AND (p_blocage IS NULL OR p_blocage = 'E' 
         OR (p_blocage = 'T' AND (b.blocage_ran = false OR b.blocage_ran IS NULL))
         OR (p_blocage = 'B' AND b.blocage_ran = true))
        GROUP BY 
            CASE 
                WHEN noe_pose LIKE 'CHB%' THEN 'SOUTERRAIN'
                WHEN noe_pose LIKE 'POT%' THEN 'AERIEN'
                WHEN noe_pose LIKE 'FAC%' THEN 'FACADE'
                WHEN noe_pose LIKE 'IMM%' OR noe_pose = 'IMM' THEN 'IMM'  -- Ajout de la condition exacte 'IMM'
                ELSE noe_pose
            END,
            CASE
                WHEN c_tr.max_cap <= 12 THEN 12
                WHEN c_tr.max_cap <= 24 THEN 24
                WHEN c_tr.max_cap <= 36 THEN 36
                WHEN c_tr.max_cap <= 48 THEN 48
                WHEN c_tr.max_cap <= 72 THEN 72
                WHEN c_tr.max_cap <= 96 THEN 96
                WHEN c_tr.max_cap <= 144 THEN 144
                WHEN c_tr.max_cap <= 288 THEN 288
                WHEN c_tr.max_cap <= 432 THEN 432
                WHEN c_tr.max_cap <= 576 THEN 576
                ELSE 720
            END
    ),
    equipment_data_d AS (
        SELECT 
            b.noe_type,
            CASE 
                WHEN b.noe_pose LIKE 'CHB%' THEN 'SOUTERRAIN'
                WHEN b.noe_pose LIKE 'POT%' THEN 'AERIEN'
                WHEN b.noe_pose LIKE 'FAC%' THEN 'FACADE'
                WHEN b.noe_pose LIKE 'IMM%' OR b.noe_pose = 'IMM' THEN 'IMM'  -- Ajout de la condition exacte 'IMM'
                ELSE b.noe_pose
            END AS noe_pose,
            CASE
                WHEN c_dist.max_cap <= 12 THEN 12
                WHEN c_dist.max_cap <= 24 THEN 24
                WHEN c_dist.max_cap <= 36 THEN 36
                WHEN c_dist.max_cap <= 48 THEN 48
                WHEN c_dist.max_cap <= 72 THEN 72
                WHEN c_dist.max_cap <= 96 THEN 96
                WHEN c_dist.max_cap <= 144 THEN 144
                WHEN c_dist.max_cap <= 288 THEN 288
                WHEN c_dist.max_cap <= 432 THEN 432
                WHEN c_dist.max_cap <= 576 THEN 576
                ELSE 720
            END AS capacity,
            COUNT(DISTINCT b.gid) AS quantity,
            string_agg(DISTINCT b.gid::text, ',') AS gids
        FROM 
            rip_avg_nge.bpe b
        LEFT JOIN LATERAL (
            SELECT MAX(c.cab_capa) AS max_cap
            FROM rip_avg_nge.cables c 
            WHERE st_dwithin(b.geom, c.geom,0.1) AND c.cab_type = 'CDI'
        ) c_dist ON true
        WHERE 
            b.sro = p_sro
            AND b.noe_usage = 'DI'
            AND b.noe_type != 'SRO' 
            AND "DCE" = 'O'
            AND (p_blocage IS NULL OR p_blocage = 'E' 
                 OR (p_blocage = 'T' AND (b.blocage_ran = false OR b.blocage_ran IS NULL))
                 OR (p_blocage = 'B' AND b.blocage_ran = true))
        GROUP BY 
            b.noe_type,
            CASE 
                WHEN b.noe_pose LIKE 'CHB%' THEN 'SOUTERRAIN'
                WHEN b.noe_pose LIKE 'POT%' THEN 'AERIEN'
                WHEN b.noe_pose LIKE 'FAC%' THEN 'FACADE'
                WHEN b.noe_pose LIKE 'IMM%' OR b.noe_pose = 'IMM' THEN 'IMM'  -- Ajout de la condition exacte 'IMM'
                ELSE b.noe_pose
            END,
            CASE
                WHEN c_dist.max_cap <= 12 THEN 12
                WHEN c_dist.max_cap <= 24 THEN 24
                WHEN c_dist.max_cap <= 36 THEN 36
                WHEN c_dist.max_cap <= 48 THEN 48
                WHEN c_dist.max_cap <= 72 THEN 72
                WHEN c_dist.max_cap <= 96 THEN 96
                WHEN c_dist.max_cap <= 144 THEN 144
                WHEN c_dist.max_cap <= 288 THEN 288
                WHEN c_dist.max_cap <= 432 THEN 432
                WHEN c_dist.max_cap <= 576 THEN 576
                ELSE 720
            END
    ),
    -- Données des câbles pour distribution avec fddcpi2
    cables_data AS (
        SELECT 
            CASE 
                WHEN posemode = 0 THEN 'Fourniture et pose de câble de ' || 
                    CASE 
                        WHEN normalized_capa <= 6 THEN '6'
                        WHEN normalized_capa <= 12 THEN '12'
                        WHEN normalized_capa <= 24 THEN '24'
                        WHEN normalized_capa <= 36 THEN '36'
                        WHEN normalized_capa <= 48 THEN '48'
                        WHEN normalized_capa <= 72 THEN '72'
                        WHEN normalized_capa <= 96 THEN '96'
                        WHEN normalized_capa <= 144 THEN '144'
                        WHEN normalized_capa <= 288 THEN '288'
                        WHEN normalized_capa <= 432 THEN '432'
                        WHEN normalized_capa <= 576 THEN '576'
                        ELSE '720'
                    END || ' FO en conduite'
                
                WHEN posemode = 1 THEN 'Fourniture et pose de câble optique de ' || 
                    CASE 
                        WHEN normalized_capa <= 12 THEN '12'
                        WHEN normalized_capa <= 24 THEN '24'
                        WHEN normalized_capa <= 36 THEN '36'
                        WHEN normalized_capa <= 48 THEN '48'
                        WHEN normalized_capa <= 72 THEN '72'
                        WHEN normalized_capa <= 96 THEN '96'
                        ELSE '144'
                    END || ' FO en aérien'
                
                WHEN posemode = 2 THEN 'Fourniture et pose de câble optique de ' || 
                    CASE 
                        WHEN normalized_capa <= 12 THEN '12'
                        WHEN normalized_capa <= 24 THEN '24'
                        WHEN normalized_capa <= 36 THEN '36'
                        WHEN normalized_capa <= 48 THEN '48'
                        WHEN normalized_capa <= 72 THEN '72'
                        WHEN normalized_capa <= 96 THEN '96'
                        ELSE '144'
                    END || ' FO en façade'
                
                ELSE 'Autre type de câble'
            END AS designation,
            'ml' AS unite,
            ROUND(SUM(longueur)::numeric, 2) AS quantite,
            posemode,
            normalized_capa,
            string_agg(gid_dc2::text, ',') AS gids
        FROM (
            SELECT 
                f.posemode,
                CASE 
                    WHEN f.cab_capa <= 6 THEN 6
                    WHEN f.cab_capa <= 12 THEN 12
                    WHEN f.cab_capa <= 24 THEN 24
                    WHEN f.cab_capa <= 36 THEN 36
                    WHEN f.cab_capa <= 48 THEN 48
                    WHEN f.cab_capa <= 72 THEN 72
                    WHEN f.cab_capa <= 96 THEN 96
                    WHEN f.cab_capa <= 144 THEN 144
                    WHEN f.cab_capa <= 288 THEN 288
                    WHEN f.cab_capa <= 432 THEN 432
                    WHEN f.cab_capa <= 576 THEN 576
                    ELSE 720
                END AS normalized_capa,
                f.length AS longueur,
                f.gid_dc2
            FROM rip_avg_nge.fddcpi2(p_sro) f
            LEFT JOIN LATERAL (
                SELECT c.blocage_ran
                FROM rip_avg_nge.cables c
                WHERE ST_Intersects(f.geom, c.geom) AND c.cab_type = 'CDI'
                LIMIT 1
            ) cab_src ON true
            WHERE f.cab_type = 'CDI' AND f."DCE" ='O' AND f.affectation != '3'
            AND (p_blocage IS NULL OR p_blocage = 'E' 
                 OR (p_blocage = 'T' AND (cab_src.blocage_ran = false OR cab_src.blocage_ran IS NULL))
                 OR (p_blocage = 'B' AND cab_src.blocage_ran = true))
        ) AS normalized_cables
        GROUP BY posemode, normalized_capa
    ),
    all_rows AS (
        -- Prises DTR
        SELECT 1 AS ordre, 'Nbre de Prises DTR' AS designation, 'prise' AS unite, 
            CASE WHEN p_type = 'T' THEN 0 ELSE 
                COALESCE((SELECT SUM(CASE WHEN phase = 'DTR' THEN noe_nblr ELSE 0 END) 
                    FROM rbal.rbal_auvergne WHERE sro ILIKE '%' || p_sro || '%'
                    AND (p_blocage IS NULL OR p_blocage = 'E' 
                         OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
                         OR (p_blocage = 'B' AND blocage_ran = true))), 0) 
            END AS quantite,
            CASE WHEN p_type = 'T' THEN NULL ELSE
                (SELECT string_agg(gid::text, ',') FROM rbal.rbal_auvergne 
                WHERE sro ILIKE '%' || p_sro || '%' AND phase = 'DTR'
                AND (p_blocage IS NULL OR p_blocage = 'E' 
                     OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
                     OR (p_blocage = 'B' AND blocage_ran = true)) LIMIT 1)
            END AS gids
        
        UNION ALL
        
        -- Prises RAD
        SELECT 2 AS ordre, 'Nbre de Prises RAD' AS designation, 'prise' AS unite, 
            CASE WHEN p_type = 'T' THEN 0 ELSE 
                COALESCE((SELECT SUM(CASE WHEN phase IN ('RAD', 'RAD H_DCE') THEN noe_nblr ELSE 0 END) 
                    FROM rbal.rbal_auvergne WHERE sro ILIKE '%' || p_sro || '%'
                    AND (p_blocage IS NULL OR p_blocage = 'E' 
                         OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
                         OR (p_blocage = 'B' AND blocage_ran = true))), 0) 
            END AS quantite,
            CASE WHEN p_type = 'T' THEN NULL ELSE
                (SELECT string_agg(gid::text, ',') FROM rbal.rbal_auvergne 
                WHERE sro ILIKE '%' || p_sro || '%' AND phase IN ('RAD', 'RAD_H_DCE')
                AND (p_blocage IS NULL OR p_blocage = 'E' 
                     OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
                     OR (p_blocage = 'B' AND blocage_ran = true)) LIMIT 1)
            END AS gids
        
        UNION ALL
        -- SRO
        SELECT 3 AS ordre, 'SRO' AS designation, 'U' AS unite, 
            CASE WHEN p_type = 'T' THEN 0 ELSE 
                COALESCE((SELECT COUNT(DISTINCT sro) FROM rbal.rbal_auvergne WHERE sro ILIKE '%' || p_sro || '%'
                AND (p_blocage IS NULL OR p_blocage = 'E' 
                     OR (p_blocage = 'T' AND (blocage_ran = false OR blocage_ran IS NULL))
                     OR (p_blocage = 'B' AND blocage_ran = true))), 0) 
            END AS quantite,
            (SELECT string_agg(gid::text, ',') FROM rip_avg_nge.infra_pt_autres 
             WHERE inf_mat = 'SRO' AND inf_num = p_sro LIMIT 1) AS gids
        
        UNION ALL
        
        -- GC à réaliser
        SELECT 4 AS ordre, 'GC (sou/aérien) à réaliser' AS designation, 'ml' AS unite, 
            ROUND((SELECT length FROM gc_to_create LIMIT 1)::numeric, 2) AS quantite,
            (SELECT gids FROM gc_to_create LIMIT 1) AS gids
        
        UNION ALL
        
        -- Linéaire infra existant aérien
        SELECT 5 AS ordre, 'lineaire infra existant aérien utilisé*' AS designation, 'ml' AS unite, 
            ROUND((SELECT length FROM existing_aerial LIMIT 1)::numeric, 2) AS quantite,
            (SELECT gids FROM existing_aerial LIMIT 1) AS gids
        
        UNION ALL
        
        -- En-tête TRANSPORT
        SELECT 6 AS ordre, 'TRANSPORT - Fourniture du câbe et pose comprises :' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- Câbles transport
        SELECT 
            7 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'Fourniture et pose de câble de ' || r.cap || ' FO en conduite' AS designation,
            'ml' AS unite,
            CASE WHEN p_type IS NULL OR p_type = 'T' THEN 
                COALESCE((SELECT total_length FROM transport_cable_gids WHERE cap = r.cap LIMIT 1), 0) 
            ELSE 0 END AS quantite,
            CASE WHEN p_type IS NULL OR p_type = 'T' THEN 
                COALESCE((SELECT gids FROM transport_cable_gids WHERE cap = r.cap LIMIT 1), NULL) 
            ELSE NULL END AS gids
        FROM (VALUES (12), (24), (36), (48), (72), (96), (144), (288), (432), (576), (720)) AS r(cap)
        UNION ALL
        -- En-tête DISTRIBUTION
        SELECT 18 AS ordre, 'DISTRIBUTION - Fourniture du câble et pose comprises :' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- Câbles façade (distribution) 
        SELECT 
            19 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'Fourniture et pose de câble optique de ' || r.cap || ' FO en façade' AS designation,
            'ml' AS unite,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN 
                COALESCE((SELECT quantite FROM cables_data WHERE posemode = 2 AND normalized_capa = r.cap LIMIT 1), 0) 
            ELSE 0 END AS quantite,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN 
                COALESCE((SELECT gids FROM cables_data WHERE posemode = 2 AND normalized_capa = r.cap LIMIT 1), NULL) 
            ELSE NULL END AS gids
        FROM (VALUES (6), (12), (24), (36), (48), (72), (96), (144)) AS r(cap)
        UNION ALL
        -- En-tête Câble aérien
        SELECT 27 AS ordre, 'Câble aérien' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- Câbles aériens (distribution) 
        SELECT 
            28 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'Fourniture et pose de câble optique de ' || r.cap || (CASE WHEN r.cap IN (6, 24) THEN 'FO' ELSE ' FO' END) || ' en aérien' AS designation,
            'ml' AS unite,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN 
                COALESCE((SELECT quantite FROM cables_data WHERE posemode = 1 AND normalized_capa = r.cap LIMIT 1), 0) 
            ELSE 0 END AS quantite,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN 
                COALESCE((SELECT gids FROM cables_data WHERE posemode = 1 AND normalized_capa = r.cap LIMIT 1), NULL) 
            ELSE NULL END AS gids
        FROM (VALUES (6), (12), (24), (36), (48), (72), (96), (144)) AS r(cap)
        UNION ALL
        -- En-tête Câble souterrain
        SELECT 36 AS ordre, 'Câble sout' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- Câbles souterrains (distribution) 
        SELECT 
            37 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'Fourniture et pose de câble de ' || r.cap || ' FO en conduite' AS designation,
            'ml' AS unite,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN 
                COALESCE((SELECT quantite FROM cables_data WHERE posemode = 0 AND normalized_capa = r.cap LIMIT 1), 0) 
            ELSE 0 END AS quantite,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN 
                COALESCE((SELECT gids FROM cables_data WHERE posemode = 0 AND normalized_capa = r.cap LIMIT 1), NULL) 
            ELSE NULL END AS gids
        FROM (VALUES (6), (12), (24), (36), (48), (72), (96), (144), (288), (432), (576), (720)) AS r(cap)
        UNION ALL
        
        -- En-tête BPE façade
        SELECT 49 AS ordre, 'BPE facade' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- BPE façade
        SELECT 
            50 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'F&P BPE ' || r.cap || ' FO en façade (sans épissures)' AS designation,
            'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'FACADE' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0)
                WHEN p_type = 'D' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'FACADE' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'FACADE' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0) +
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'FACADE' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM pep_transport
                        WHERE pose_type = 'FACADE' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type = 'D' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PEP' AND noe_pose = 'FACADE' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type IS NULL THEN
                    (
                        WITH combined_gids AS (
                            SELECT 
                                CASE 
                                    WHEN t.gids IS NULL THEN d.gids
                                    WHEN d.gids IS NULL THEN t.gids
                                    ELSE t.gids || ',' || d.gids
                                END AS combined
                            FROM 
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM pep_transport
                                    WHERE pose_type = 'FACADE' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) t
                            CROSS JOIN
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM equipment_data_d
                                    WHERE noe_type = 'PEP' AND noe_pose = 'FACADE' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) d
                            LIMIT 1
                        )
                        SELECT combined FROM combined_gids
                    )
                ELSE NULL
            END AS gids
        FROM (VALUES 
            (12, NULL::int),
            (24, 12),
            (36, 24),
            (48, 36),
            (72, 48),
            (96, 72),
            (144, 96)
        ) AS r(cap, prevCap)
        UNION ALL
        -- En-tête BPE aérien
        SELECT 57 AS ordre, 'BPE aérien' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- BPE aérien
        SELECT 
            58 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'F&P BPE ' || r.cap || (CASE WHEN r.cap = 144 THEN 'FO' ELSE ' FO' END) || ' en aérien (sans épissures)' AS designation,
            'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0)
                WHEN p_type = 'D' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0) +
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM pep_transport
                        WHERE pose_type = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type = 'D' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PEP' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type IS NULL THEN
                    (
                        WITH combined_gids AS (
                            SELECT 
                                CASE 
                                    WHEN t.gids IS NULL THEN d.gids
                                    WHEN d.gids IS NULL THEN t.gids
                                    ELSE t.gids || ',' || d.gids
                                END AS combined
                            FROM 
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM pep_transport
                                    WHERE pose_type = 'AERIEN' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) t
                            CROSS JOIN
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM equipment_data_d
                                    WHERE noe_type = 'PEP' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) d
                            LIMIT 1
                        )
                        SELECT combined FROM combined_gids
                    )
                ELSE NULL
            END AS gids
        FROM (VALUES 
            (12, NULL::int),
            (24, 12),
            (36, 24),
            (48, 36),
            (72, 48),
            (96, 72),
            (144, 96)
        ) AS r(cap, prevCap)
        UNION ALL
        -- En-tête BPE Immeuble
        SELECT 65 AS ordre, 'BPE Immeuble' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- BPE Immeuble
        SELECT 
            66 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'F&P BPE ' || r.cap || ' FO en immeuble (sans épissures)' AS designation,
            'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'IMM' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0)
                WHEN p_type = 'D' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'IMM' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'IMM' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0) +
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'IMM' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM pep_transport
                        WHERE pose_type = 'IMM' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type = 'D' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PEP' AND noe_pose = 'IMM' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type IS NULL THEN
                    (
                        WITH combined_gids AS (
                            SELECT 
                                CASE 
                                    WHEN t.gids IS NULL THEN d.gids
                                    WHEN d.gids IS NULL THEN t.gids
                                    ELSE t.gids || ',' || d.gids
                                END AS combined
                            FROM 
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM pep_transport
                                    WHERE pose_type = 'IMM' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) t
                            CROSS JOIN
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM equipment_data_d
                                    WHERE noe_type = 'PEP' AND noe_pose = 'IMM' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) d
                            LIMIT 1
                        )
                        SELECT combined FROM combined_gids
                    )
                ELSE NULL
            END AS gids
        FROM (VALUES 
            (12, NULL::int),
            (24, 12),
            (36, 24),
            (48, 36),
            (72, 48),
            (96, 72),
            (144, 96)
        ) AS r(cap, prevCap)
        UNION ALL
        -- En-tête BPE souterrain
        SELECT 73 AS ordre, 'BPE sout' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- BPE souterrain
        SELECT 
            74 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'F&P BPE ' || r.cap || ' FO en conduite (sans épissures)' AS designation,
            'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0)
                WHEN p_type = 'D' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN pose_type = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM pep_transport
                    ), 0) +
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PEP' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM pep_transport
                        WHERE pose_type = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type = 'D' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PEP' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type IS NULL THEN
                    (
                        WITH combined_gids AS (
                            SELECT 
                                CASE 
                                    WHEN t.gids IS NULL THEN d.gids
                                    WHEN d.gids IS NULL THEN t.gids
                                    ELSE t.gids || ',' || d.gids
                                END AS combined
                            FROM 
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM pep_transport
                                    WHERE pose_type = 'SOUTERRAIN' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) t
                            CROSS JOIN
                                (
                                    SELECT string_agg(gids, ',') AS gids 
                                    FROM equipment_data_d
                                    WHERE noe_type = 'PEP' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                                        AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                                ) d
                            LIMIT 1
                        )
                        SELECT combined FROM combined_gids
                    )
                ELSE NULL
            END AS gids
        FROM (VALUES 
            (12, NULL::int),
            (24, 12),
            (36, 24),
            (48, 36),
            (72, 48),
            (96, 72),
            (144, 96),
            (288, 144),
            (432, 288),
            (576, 432),
            (720, 576)
        ) AS r(cap, prevCap)
        UNION ALL
		
        -- En-tête PA aérien
        SELECT 85 AS ordre, 'PA aérien' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- PA aérien
        SELECT 
            86 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'F&P PA ' || r.cap || ' FO en aérien (sans épissures)' AS designation,
            'u' AS unite,
            CASE 
                WHEN p_type = 'D' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PA' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PA' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'D' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PA' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type IS NULL THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PA' AND noe_pose = 'AERIEN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                ELSE NULL
            END AS gids
        FROM (VALUES 
            (12, NULL::int),
            (24, 12),
            (36, 24),
            (48, 36),
            (72, 48),
            (96, 72),
            (144, 96)
        ) AS r(cap, prevCap)
        UNION ALL
        -- En-tête PA souterrain
        SELECT 93 AS ordre, 'PA souterrain' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- PA souterrain
        SELECT 
            94 + (row_number() OVER (ORDER BY r.cap)) - 1 AS ordre,
            'F&P PA ' || r.cap || ' FO en conduite (sans épissures)' AS designation,
            'u' AS unite,
            CASE 
                WHEN p_type = 'D' THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PA' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((
                        SELECT SUM(CASE WHEN noe_type = 'PA' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0)) THEN quantity ELSE 0 END)
                        FROM equipment_data_d
                    ), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'D' THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PA' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                WHEN p_type IS NULL THEN
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type = 'PA' AND noe_pose = 'SOUTERRAIN' AND capacity <= r.cap 
                            AND (capacity > r.prevCap OR (r.prevCap IS NULL AND capacity > 0))
                        LIMIT 1
                    )
                ELSE NULL
            END AS gids
        FROM (VALUES 
            (12, NULL::int),
            (24, 12),
            (36, 24),
            (48, 36),
            (72, 48),
            (96, 72),
            (144, 96),
            (288, 144),
            (432, 288),
            (576, 432),
            (720, 576)
        ) AS r(cap, prevCap)
        UNION ALL
        -- En-tête PBO
        SELECT 105 AS ordre, 'PBO' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        -- PBO en chambre
        SELECT 106 AS ordre, 'F&P de PBO en chambre (yc prépa câble)' AS designation, 'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN 0  
                WHEN p_type = 'D' THEN
                    COALESCE((SELECT SUM(CASE WHEN noe_type IN ('PBO', 'PBR') AND noe_pose = 'SOUTERRAIN' THEN quantity ELSE 0 END)
                        FROM equipment_data_d), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((SELECT SUM(CASE WHEN noe_type IN ('PBO', 'PBR') AND noe_pose = 'SOUTERRAIN' THEN quantity ELSE 0 END)
                        FROM equipment_data_d), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN NULL
                ELSE
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type IN ('PBO', 'PBR') AND noe_pose = 'SOUTERRAIN'
                        LIMIT 1
                    )
            END AS gids
        UNION ALL
        -- PBO aérien/façade
        SELECT 107 AS ordre, 'F&P de PBO aérien/ façade (yc prépa câble)' AS designation, 'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN 0  
                WHEN p_type = 'D' THEN
                    COALESCE((SELECT SUM(CASE WHEN noe_type IN ('PBO', 'PBR') AND noe_pose IN ('AERIEN', 'FACADE') THEN quantity ELSE 0 END)
                        FROM equipment_data_d), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((SELECT SUM(CASE WHEN noe_type IN ('PBO', 'PBR') AND noe_pose IN ('AERIEN', 'FACADE') THEN quantity ELSE 0 END)
                        FROM equipment_data_d), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN NULL
                ELSE
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type IN ('PBO', 'PBR') AND noe_pose IN ('AERIEN', 'FACADE')
                        LIMIT 1
                    )
            END AS gids
        UNION ALL
        -- PBO immeuble
        SELECT 108 AS ordre, 'F&P de PBO immeuble (yc prépa câble)' AS designation, 'u' AS unite,
            CASE 
                WHEN p_type = 'T' THEN 0  
                WHEN p_type = 'D' THEN
                    COALESCE((SELECT SUM(CASE WHEN noe_type IN ('PBO', 'PBR') AND noe_pose = 'IMM' THEN quantity ELSE 0 END)
                        FROM equipment_data_d), 0)
                WHEN p_type IS NULL THEN
                    COALESCE((SELECT SUM(CASE WHEN noe_type IN ('PBO', 'PBR') AND noe_pose = 'IMM' THEN quantity ELSE 0 END)
                        FROM equipment_data_d), 0)
                ELSE 0
            END AS quantite,
            CASE 
                WHEN p_type = 'T' THEN NULL
                ELSE
                    (
                        SELECT string_agg(gids, ',')
                        FROM equipment_data_d
                        WHERE noe_type IN ('PBO', 'PBR') AND noe_pose = 'IMM'
                        LIMIT 1
                    )
            END AS gids
    )
    SELECT 
        designation, 
        unite, 
        quantite,
        gids 
    FROM all_rows
    WHERE ordre IS NOT NULL -- Assurez-vous que les lignes avec un ordre nul sont exclues
    ORDER BY ordre;
END;
$BODY$;

ALTER FUNCTION rip_avg_nge.dqe2(text, text, text)
    OWNER TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe2(text, text, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe2(text, text, text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe2(text, text, text) TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe2(text, text, text) TO sdupays;

COMMENT ON FUNCTION rip_avg_nge.dqe2(text, text, text)
    IS 'DQE PRO avec filtre blocage_ran. p_blocage: NULL/E=standard, T=travaux (sans blocage), B=blocage uniquement';
