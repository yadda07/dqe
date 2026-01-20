-- FUNCTION: rip_avg_nge.dqe_exe(text, text)

-- DROP FUNCTION IF EXISTS rip_avg_nge.dqe_exe(text, text);

CREATE OR REPLACE FUNCTION rip_avg_nge.dqe_exe(
	p_sro text,
	p_type text DEFAULT NULL::text)
    RETURNS TABLE("Désignation" text, "Unité" text, "Quantité" numeric, ids text) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
    v_gc_ids text; -- IDs du GC à réaliser
BEGIN
    -- Récupération des IDs du GC à réaliser depuis la ligne 4 du DQE
    WITH dqe_numbered AS (
        SELECT d.ids as gc_ids, ROW_NUMBER() OVER (ORDER BY 1) as rn
        FROM rip_avg_nge.dqe2(p_sro, p_type) d
    )
    SELECT dqe_numbered.gc_ids INTO v_gc_ids
    FROM dqe_numbered 
    WHERE rn = 4; -- Ligne 4 = GC (sou/aérien) à réaliser

    -- Si pas d'IDs trouvés, on met une chaîne vide
    IF v_gc_ids IS NULL THEN
        v_gc_ids := '';
    END IF;

    RETURN QUERY
    WITH 
    -- =========================================================================
    -- RÉCUPÉRATION DES DONNÉES PRO (via dqe2) - Les 108 premières lignes
    -- =========================================================================
    pro_data AS (
        SELECT ROW_NUMBER() OVER (ORDER BY 1) AS ordre_pro,
               d."Désignation" AS des_pro, 
               d."Unité" AS uni_pro, 
               d."Quantité" AS qte_pro, 
               d.ids AS ids_pro
        FROM rip_avg_nge.dqe2(p_sro, p_type) d
    ),
    
    -- =========================================================================
    -- GC À RÉALISER (depuis la ligne 4)
    -- =========================================================================
    gc_a_realiser AS (
        SELECT 
            t.gid,
            t.geom, 
            ST_Length(t.geom) as longueur
        FROM rip_avg_nge.t_cheminement t
        WHERE v_gc_ids != '' AND t.gid::text = ANY(string_to_array(v_gc_ids, ','))
    ),
    
    -- =========================================================================
    -- DONNÉES EXE - CHEMINEMENTS
    -- =========================================================================
    cheminement_data AS (
        SELECT
            exe.type_coup,
            CASE 
                WHEN exe.type_coup = 'Dk' THEN 'Tranchée traditionnelle sous chaussée'
                WHEN exe.type_coup = 'Fc' THEN 'Tranchée traditionnelle sous trottoir'
                WHEN exe.type_coup = 'Dm' THEN 'Tranchée traditionnelle sous accotement'
                WHEN exe.type_coup = 'Dn' THEN 'Tranchée traditionnelle sous Espace Vert ou chemin empierré'
                WHEN exe.type_coup = 'Bd' THEN 'Micro tranchée sous chaussée'
                WHEN exe.type_coup = 'Ba' THEN 'Micro tranchée sous rive'
                WHEN exe.type_coup IN ('Ma', 'Sa') THEN 'Tranchée mécanisée ou SOC sous accotement'
                WHEN exe.type_coup = 'Mc' THEN 'Tranchée mécanisée sous Espace Vert ou chemin empierré'
                WHEN exe.type_coup IN ('Ga', 'Gb') THEN 'Forage dirigé ou fonçage'
                WHEN exe.type_coup = 'ENC' THEN 'Encorbellement'
                ELSE exe.type_coup
            END AS designation_exec,
            SUM(exe.long_plan)::numeric AS total_length,
            string_agg(exe.gid::text, ',') AS gids_exec
        FROM gc_exe.t_cheminement exe
       INNER JOIN gc_a_realiser gar ON 
    st_dwithin(exe.geom, gar.geom, 0.2)
    --AND st_hausdorffdistance(exe.geom, gar.geom) < 2 
    AND (st_length(st_intersection(st_buffer(gar.geom, 0.2), exe.geom)) / st_length(exe.geom)) > 0.80  or st_within(exe.geom,gar.geom)
		
        WHERE exe.sro = p_sro 
        AND exe.cm_avct = 'C' 
        AND exe.cm_typ_imp = '7'
        AND exe.type_coup IS NOT NULL
        GROUP BY exe.type_coup, 
                CASE 
                    WHEN exe.type_coup = 'Dk' THEN 'Tranchée traditionnelle sous chaussée'
                    WHEN exe.type_coup = 'Fc' THEN 'Tranchée traditionnelle sous trottoir'
                    WHEN exe.type_coup = 'Dm' THEN 'Tranchée traditionnelle sous accotement'
                    WHEN exe.type_coup = 'Dn' THEN 'Tranchée traditionnelle sous Espace Vert ou chemin empierré'
                    WHEN exe.type_coup = 'Bd' THEN 'Micro tranchée sous chaussée'
                    WHEN exe.type_coup = 'Ba' THEN 'Micro tranchée sous rive'
                    WHEN exe.type_coup IN ('Ma', 'Sa') THEN 'Tranchée mécanisée ou SOC sous accotement'
                    WHEN exe.type_coup = 'Mc' THEN 'Tranchée mécanisée sous Espace Vert ou chemin empierré'
                    WHEN exe.type_coup IN ('Ga', 'Gb') THEN 'Forage dirigé ou fonçage'
                    WHEN exe.type_coup = 'ENC' THEN 'Encorbellement'
                    ELSE exe.type_coup
                END
    ),
    
    -- Regroupement des types de coup similaires
    cheminement_grouped AS (
        SELECT 
            designation_exec,
            SUM(total_length)::numeric AS total_length,
            string_agg(gids_exec, ',') AS gids_exec
        FROM cheminement_data
        GROUP BY designation_exec
    ),
    
    -- =========================================================================
    -- DONNÉES EXE - CHAMBRES
    -- =========================================================================
    chambre_distinct AS (
	SELECT 
		  c.gid ,
			c.inf_mat
	FROM gc_exe.infra_pt_chb c
        INNER JOIN gc_a_realiser gar ON ST_DWithin(c.geom, gar.geom, 0.1)
        WHERE c.inf_type = 'CHB-AC'
        GROUP BY c.inf_mat , c.gid
	)
	,chambres_data AS (
        SELECT
            inf_mat,
            COUNT(*)::numeric AS quantity,
            string_agg(gid::text, ',') AS gids_chb
        FROM chambre_distinct 
        GROUP BY inf_mat
    ),
    
    -- =========================================================================
    -- DONNÉES EXE - POTEAUX
    -- =========================================================================
    poteaux_distribution_data AS (
        SELECT
            CASE 
                WHEN inf_type = 'POT-AC' THEN 'pose poteau RAUV'
                WHEN inf_type = 'POT-FT' AND etat = 'A RENFORCER' THEN 'FT à renforcer'
                WHEN inf_type = 'POT-FT' AND etat = 'A RECALER' THEN 'FT à recaler'
                WHEN inf_type = 'POT-FT' AND etat = 'A REMPLACER' THEN 'FT à remplacer'
            END AS designation_poteau,
            COUNT(*)::numeric AS quantity,
            string_agg(p.gid::text, ',') AS gids_pot_dist
        FROM rip_avg_nge.infra_pt_pot p
        WHERE p.sro = p_sro
        AND (
            (p.inf_type = 'POT-AC') OR
            (p.inf_type = 'POT-FT' AND p.etat IN ('A RENFORCER', 'A RECALER', 'A REMPLACER'))
        )
        GROUP BY 
            CASE 
                WHEN inf_type = 'POT-AC' THEN 'pose poteau RAUV'
                WHEN inf_type = 'POT-FT' AND etat = 'A RENFORCER' THEN 'FT à renforcer'
                WHEN inf_type = 'POT-FT' AND etat = 'A RECALER' THEN 'FT à recaler'
                WHEN inf_type = 'POT-FT' AND etat = 'A REMPLACER' THEN 'FT à remplacer'
            END
    ),
    
    -- =========================================================================
    -- DONNÉES EXE - PVC
    -- =========================================================================
    pvc_data AS (
        SELECT
            CASE 
                WHEN exe.cm_compo ILIKE '%45' THEN 'PVC 45 (' || CAST(LEFT(exe.cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN exe.cm_compo ILIKE '%60' THEN 'PVC 60 (' || CAST(LEFT(exe.cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN exe.cm_compo ILIKE '%80' THEN 'PVC 80 (' || CAST(LEFT(exe.cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
            END AS designation_pvc,
            (CAST(LEFT(exe.cm_compo,1) AS INTEGER) * SUM(exe.long_plan))::numeric AS total_length,
            string_agg(exe.gid::text, ',') AS gids_pvc
        FROM gc_exe.t_cheminement exe
       INNER JOIN gc_a_realiser gar ON 
    st_dwithin(exe.geom, gar.geom, 0.2)
    --AND st_hausdorffdistance(exe.geom, gar.geom) < 2 
    AND (st_length(st_intersection(st_buffer(gar.geom, 0.2), exe.geom)) / st_length(exe.geom)) > 0.80  or st_within(exe.geom,gar.geom)
        WHERE exe.sro = p_sro 
        AND exe.cm_compo ILIKE '%pvc%' 
        AND (exe.cm_compo ILIKE '%45' OR exe.cm_compo ILIKE '%60' OR exe.cm_compo ILIKE '%80')
        GROUP BY 
            CASE 
                WHEN exe.cm_compo ILIKE '%45' THEN 'PVC 45 (' || CAST(LEFT(exe.cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN exe.cm_compo ILIKE '%60' THEN 'PVC 60 (' || CAST(LEFT(exe.cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN exe.cm_compo ILIKE '%80' THEN 'PVC 80 (' || CAST(LEFT(exe.cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
            END,
            exe.cm_compo
    ),
    
    -- =========================================================================
    -- DONNÉES EXE - PEHD
    -- =========================================================================
    pehd_data AS (
        SELECT
            exe.cm_compo AS designation_pehd,
            SUM(exe.long_plan)::numeric AS total_length,
            string_agg(exe.gid::text, ',') AS gids_pehd
        FROM gc_exe.t_cheminement exe
       INNER JOIN gc_a_realiser gar ON 
    st_dwithin(gar.geom, exe.geom, 0.2)
   -- AND st_hausdorffdistance(exe.geom, gar.geom) < 2 
    AND (st_length(st_intersection(st_buffer(gar.geom, 0.2), exe.geom)) / st_length(exe.geom)) > 0.80  or st_within(exe.geom,gar.geom)
       WHERE exe.sro = p_sro 
        AND exe.cm_compo ILIKE '%PEHD%'
        GROUP BY exe.cm_compo
    )

    -- =========================================================================
    -- ASSEMBLAGE FINAL SELON L'ORDRE EXACT DU TEMPLATE EXCEL
    -- =========================================================================
    SELECT 
        r.des_pro as "Désignation", 
        r.uni_pro as "Unité", 
        r.qte_pro as "Quantité",
        r.ids_pro as ids
    FROM (
        -- BLOC 1: Données PRO (lignes 1 à 108) - utilisation directe de dqe2
        SELECT p.ordre_pro AS ordre, 
               p.des_pro, 
               p.uni_pro, 
               p.qte_pro, 
               p.ids_pro
        FROM pro_data p
        WHERE p.ordre_pro <= 108
        
        UNION ALL
        
        -- BLOC 2: Section Travaux Génie civil (ligne 109)
        SELECT 109 AS ordre, 'Travaux Génie civil', NULL, NULL::numeric, NULL
        
        UNION ALL
        
        -- BLOC 3: Armoire de rue - HEADER (ligne 110)
        SELECT 110 AS ordre, ' Armoire de rue  - (hors fourniture)', NULL, NULL::numeric, NULL
        
        UNION ALL
        
        -- BLOC 4: Armoire de rue - Pose (ligne 111)
        SELECT 111 AS ordre, 'Terrassement, Pose d''un socle préfa en Béton, bétonnage et Pose d''une armoire de rue (y-compris transport, mise à la terre, réfection a l''identique)', 'U', 0::numeric, NULL
        
        UNION ALL
        
        -- BLOC 5: GC HEADER (ligne 112)
        SELECT 112 AS ordre, ' GC - TDR + RAD (hors fourniture tube PEHD ou PVC et chambres)', NULL, NULL::numeric, NULL
        
        UNION ALL
        
        -- BLOC 6: TRANCHÉES (lignes 113-122)
        SELECT 113 AS ordre, 'Tranchée traditionnelle sous chaussée', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Tranchée traditionnelle sous chaussée'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Tranchée traditionnelle sous chaussée')
        
        UNION ALL
        
        SELECT 114 AS ordre, 'Tranchée traditionnelle sous trottoir', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Tranchée traditionnelle sous trottoir'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Tranchée traditionnelle sous trottoir')
        
        UNION ALL
        
        SELECT 115 AS ordre, 'Tranchée traditionnelle sous accotement', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Tranchée traditionnelle sous accotement'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Tranchée traditionnelle sous accotement')
        
        UNION ALL
        
        SELECT 116 AS ordre, 'Tranchée traditionnelle sous Espace Vert ou chemin empierré', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Tranchée traditionnelle sous Espace Vert ou chemin empierré'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Tranchée traditionnelle sous Espace Vert ou chemin empierré')
        
        UNION ALL
        
        SELECT 117 AS ordre, 'Micro tranchée sous chaussée', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Micro tranchée sous chaussée'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Micro tranchée sous chaussée')
        
        UNION ALL
        
        SELECT 118 AS ordre, 'Micro tranchée sous rive', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Micro tranchée sous rive'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Micro tranchée sous rive')
        
        UNION ALL
        
        SELECT 119 AS ordre, 'Tranchée mécanisée ou SOC sous accotement', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Tranchée mécanisée ou SOC sous accotement'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Tranchée mécanisée ou SOC sous accotement')
        
        UNION ALL
        
        SELECT 120 AS ordre, 'Tranchée mécanisée sous Espace Vert ou chemin empierré', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Tranchée mécanisée sous Espace Vert ou chemin empierré'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Tranchée mécanisée sous Espace Vert ou chemin empierré')
        
        UNION ALL
        
        SELECT 121 AS ordre, 'Forage dirigé ou fonçage', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Forage dirigé ou fonçage'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Forage dirigé ou fonçage')
        
        UNION ALL
        
        SELECT 122 AS ordre, 'Encorbellement', 'ml',
            COALESCE((SELECT total_length FROM cheminement_grouped 
                     WHERE designation_exec = 'Encorbellement'), 0),
            (SELECT gids_exec FROM cheminement_grouped 
             WHERE designation_exec = 'Encorbellement')
        
        UNION ALL
        
        -- BLOC 7: CHAMBRES (lignes 123-130)
        SELECT 123 AS ordre, 'Pose de chambre L1T', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L1T'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L1T')
        
        UNION ALL
        
        SELECT 124 AS ordre, 'Pose de chambre L2T', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L2T'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L2T')
        
        UNION ALL
        
        SELECT 125 AS ordre, 'pose de chambre L3T', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L3T'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L3T')
        
        UNION ALL
        
        SELECT 126 AS ordre, 'pose de chambre L4T', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L4T'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L4T')
        
        UNION ALL
        
        SELECT 127 AS ordre, 'pose de chambre L5T', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L5T'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L5T')
        
        UNION ALL
        
        SELECT 128 AS ordre, 'pose de chambre L2C', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L2C'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L2C')
        
        UNION ALL
        
        SELECT 129 AS ordre, 'pose de chambre L3C', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'L3C'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'L3C')
        
        UNION ALL
        
        SELECT 130 AS ordre, 'pose de chambre K2C', 'U',
            COALESCE((SELECT quantity FROM chambres_data WHERE inf_mat = 'K2C'), 0),
            (SELECT gids_chb FROM chambres_data WHERE inf_mat = 'K2C')
        
        UNION ALL
        
        -- BLOC 8: POSE DE POTEAUX HEADER (ligne 131)
        SELECT 131 AS ordre, ' Pose de poteaux', NULL, NULL::numeric, NULL
        
        UNION ALL
        
        -- BLOC 9: POTEAUX (lignes 132-135) - UNIQUEMENT POUR DISTRIBUTION
        SELECT 132 AS ordre, 'pose poteau RAUV', 'U',
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                COALESCE((SELECT quantity FROM poteaux_distribution_data 
                         WHERE designation_poteau = 'pose poteau RAUV'), 0)
            ELSE 0 END,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                (SELECT gids_pot_dist FROM poteaux_distribution_data 
                 WHERE designation_poteau = 'pose poteau RAUV')
            ELSE NULL END
        
        UNION ALL
        
        SELECT 133 AS ordre, 'FT à recaler', 'U',
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                COALESCE((SELECT quantity FROM poteaux_distribution_data 
                         WHERE designation_poteau = 'FT à recaler'), 0)
            ELSE 0 END,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                (SELECT gids_pot_dist FROM poteaux_distribution_data 
                 WHERE designation_poteau = 'FT à recaler')
            ELSE NULL END
            
        UNION ALL
        
        SELECT 134 AS ordre, 'FT à remplacer', 'U',
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                COALESCE((SELECT quantity FROM poteaux_distribution_data 
                         WHERE designation_poteau = 'FT à remplacer'), 0)
            ELSE 0 END,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                (SELECT gids_pot_dist FROM poteaux_distribution_data 
                 WHERE designation_poteau = 'FT à remplacer')
            ELSE NULL END
            
        UNION ALL
        
        SELECT 135 AS ordre, 'FT à renforcer', 'U',
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                COALESCE((SELECT quantity FROM poteaux_distribution_data 
                         WHERE designation_poteau = 'FT à renforcer'), 0)
            ELSE 0 END,
            CASE WHEN p_type IS NULL OR p_type = 'D' THEN
                (SELECT gids_pot_dist FROM poteaux_distribution_data 
                 WHERE designation_poteau = 'FT à renforcer')
            ELSE NULL END
        
        UNION ALL
        
        -- BLOC 10: LIGNE VIDE (ligne 136)
        SELECT 136 AS ordre, '', NULL, NULL::numeric, NULL
        
        UNION ALL
        
        -- BLOC 11: FOURNITURE DES ALVÉOLES HEADER (ligne 137)
        SELECT 137 AS ordre, ' Fourniture des Alvéoles', NULL, NULL::numeric, NULL
        
        UNION ALL
        
        -- BLOC 12: PVC DYNAMIQUES (lignes 138+)
        SELECT 
            137 + (row_number() OVER (ORDER BY p.designation_pvc)) AS ordre,
            p.designation_pvc,
            'ml',
            COALESCE(p.total_length, 0),
            p.gids_pvc
        FROM pvc_data p
        
        UNION ALL
        
        -- BLOC 13: PEHD DYNAMIQUES (lignes suivantes)
        SELECT 
            150 + (row_number() OVER (ORDER BY p.designation_pehd)) AS ordre,
            p.designation_pehd,
            'ml',
            COALESCE(p.total_length, 0),
            p.gids_pehd
        FROM pehd_data p
        
    ) r
    WHERE r.ordre IS NOT NULL
    ORDER BY r.ordre;
END;
$BODY$;

ALTER FUNCTION rip_avg_nge.dqe_exe(text, text)
    OWNER TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_exe(text, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_exe(text, text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_exe(text, text) TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_exe(text, text) TO sdupays;

COMMENT ON FUNCTION rip_avg_nge.dqe_exe(text, text)
    IS 'Fonction complète pour générer le template DQE EXE selon l''ordre exact du template Excel';
