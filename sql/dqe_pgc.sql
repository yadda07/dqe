-- FUNCTION: rip_avg_nge.dqe_pgc(text, text)

-- DROP FUNCTION IF EXISTS rip_avg_nge.dqe_pgc(text, text);

CREATE OR REPLACE FUNCTION rip_avg_nge.dqe_pgc(
	p_sro text,
	p_troncon text DEFAULT NULL::text)
    RETURNS TABLE("Désignation" text, "Unité" text, "Quantité" numeric, ids text) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
    v_gc_name text;
    v_typ_imp text;
    v_is_aerien boolean := false;
    v_is_mixte boolean := false;
    v_has_aerien boolean := false;
    v_has_souterrain boolean := false;
BEGIN
    -- Détection des types d'infrastructure présents (aérien ET/OU souterrain)
    SELECT 
        bool_or(cm_typ_imp = '0') AS has_aerien,
        bool_or(cm_typ_imp = '7') AS has_souterrain
    INTO v_has_aerien, v_has_souterrain
    FROM gc_exe.t_cheminement 
    WHERE sro = p_sro
    AND (p_troncon IS NULL OR gc = p_troncon)
    AND cm_avct = 'C' 
    AND cm_typ_imp IN ('0', '7');
    
    -- Détermination du type de parcours
    v_is_mixte := (v_has_aerien AND v_has_souterrain);
    
    -- Si parcours mixte, on traite comme souterrain avec ajout des poteaux
    -- Si pas mixte, on garde la logique actuelle selon le type majoritaire
    IF v_is_mixte THEN
        v_typ_imp := '7'; -- Base souterraine pour parcours mixte
        v_is_aerien := false;
    ELSE
        -- Parcours pur : prendre le type existant
        IF v_has_aerien THEN
            v_typ_imp := '0';
            v_is_aerien := true;
        ELSE
            v_typ_imp := '7'; -- Par défaut souterrain
            v_is_aerien := false;
        END IF;
    END IF;
    
    -- Récupération du nom GC pour le tronçon donné
    IF p_troncon IS NULL THEN
        -- Si aucun tronçon spécifié, prendre tous les tronçons du SRO
        -- Pour parcours mixte, inclure TOUS les types, sinon seulement le type détecté
        SELECT string_agg(DISTINCT gc, ';' ORDER BY gc) INTO v_gc_name
        FROM gc_exe.t_cheminement 
        WHERE sro = p_sro
        AND cm_avct = 'C' 
        AND (
            CASE 
                WHEN v_is_mixte THEN cm_typ_imp IN ('0', '7')
                ELSE cm_typ_imp = v_typ_imp
            END
        );
    ELSE
        -- Utiliser le tronçon spécifié
        v_gc_name := p_troncon;
    END IF;

    RETURN QUERY
    WITH 
    -- Données des cheminements par type de coup
    cheminement_data AS (
        SELECT
            type_coup,
            CASE 
                WHEN type_coup = 'Dk' THEN 'Tranchée traditionnelle sous chaussée'
                WHEN type_coup = 'Fc' THEN 'Tranchée traditionnelle sous trottoir'
                WHEN type_coup = 'Dm' THEN 'Tranchée traditionnelle sous accotement'
                WHEN type_coup = 'Dn' THEN 'Tranchée traditionnelle sous Espace Vert ou chemin empierré'
                WHEN type_coup = 'Bd' THEN 'Micro tranchée sous chaussée'
                WHEN type_coup = 'Ba' THEN 'Micro tranchée sous rive'
                WHEN type_coup IN ('Ma', 'Sa') THEN 'Tranchée mécanisée ou SOC sous accotement'
                WHEN type_coup = 'Mc' THEN 'Tranchée mécanisée sous Espace Vert ou chemin empierré'
                WHEN type_coup IN ('Ga', 'Gb') THEN 'Forage dirigé ou fonçage'
                WHEN type_coup = 'ENC' THEN 'Encorbellement'
                ELSE type_coup
            END AS designation,
            SUM(long_plan) AS total_length,
            string_agg(gid::text, ',') AS gids
        FROM gc_exe.t_cheminement
        WHERE sro = p_sro
        AND (p_troncon IS NULL OR gc = p_troncon)
        AND cm_avct = 'C' 
        AND (
            CASE 
                WHEN v_is_mixte THEN cm_typ_imp = '7'  -- Pour mixte : seulement souterrain pour les tranchées
                ELSE cm_typ_imp = v_typ_imp
            END
        )
        AND type_coup IS NOT NULL
        GROUP BY type_coup, 
                CASE 
                    WHEN type_coup = 'Dk' THEN 'Tranchée traditionnelle sous chaussée'
                    WHEN type_coup = 'Fc' THEN 'Tranchée traditionnelle sous trottoir'
                    WHEN type_coup = 'Dm' THEN 'Tranchée traditionnelle sous accotement'
                    WHEN type_coup = 'Dn' THEN 'Tranchée traditionnelle sous Espace Vert ou chemin empierré'
                    WHEN type_coup = 'Bd' THEN 'Micro tranchée sous chaussée'
                    WHEN type_coup = 'Ba' THEN 'Micro tranchée sous rive'
                    WHEN type_coup IN ('Ma', 'Sa') THEN 'Tranchée mécanisée ou SOC sous accotement'
                    WHEN type_coup = 'Mc' THEN 'Tranchée mécanisée sous Espace Vert ou chemin empierré'
                    WHEN type_coup IN ('Ga', 'Gb') THEN 'Forage dirigé ou fonçage'
                    WHEN type_coup = 'ENC' THEN 'Encorbellement'
                    ELSE type_coup
                END
    ),
    
    -- Regroupement des types de coup similaires (Ma+Sa, Ga+Gb)
    cheminement_grouped AS (
        SELECT 
            designation,
            SUM(total_length) AS total_length,
            string_agg(gids, ',') AS gids
        FROM cheminement_data
        GROUP BY designation
    ),
    
    -- Données des chambres
    chambres_data AS (
        SELECT
            c.inf_mat,
            COUNT(*) AS quantity,
            string_agg(c.gid::text, ',') AS gids
        FROM gc_exe.infra_pt_chb c
        WHERE c.inf_type = 'CHB-AC'
        AND EXISTS (
            SELECT 1 FROM gc_exe.t_cheminement t 
            WHERE ST_DWithin(c.geom, t.geom, 0.5)
            AND t.sro = p_sro
            AND (p_troncon IS NULL OR t.gc = p_troncon)
            AND t.cm_avct = 'C' 
            AND (
                CASE 
                    WHEN v_is_mixte THEN t.cm_typ_imp = '7'  -- Pour mixte : seulement souterrain pour les chambres
                    ELSE t.cm_typ_imp = v_typ_imp
                END
            )
        )
        GROUP BY c.inf_mat
    ),
    
    -- Données des poteaux (uniquement pour l'aérien, optionnel pour souterrain)
    poteaux_data AS (
        SELECT
            'pose poteau RAUV' AS designation,
            COUNT(*) AS quantity,
            string_agg(p.gid::text, ',') AS gids
        FROM gc_exe.infra_pt_pot p
        WHERE p.inf_type = 'POT-AC'
        AND EXISTS (
            SELECT 1 FROM gc_exe.t_cheminement t 
            WHERE ST_DWithin(p.geom, t.geom, 0.5)
            AND t.sro = p_sro
            AND (p_troncon IS NULL OR t.gc = p_troncon)
            AND t.cm_avct = 'C' 
            AND (
                CASE 
                    WHEN v_is_mixte THEN t.cm_typ_imp IN ('0', '7')  -- Pour mixte : aérien ET souterrain pour les poteaux
                    ELSE t.cm_typ_imp = v_typ_imp
                END
            )
        )
    ),
    
    -- Données PVC (x fois les longueurs par tranchée)
    pvc_data AS (
        SELECT
            CASE 
                WHEN cm_compo ILIKE '%45' THEN 'PVC 45 (' || CAST(LEFT(cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN cm_compo ILIKE '%60' THEN 'PVC 60 (' || CAST(LEFT(cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN cm_compo ILIKE '%80' THEN 'PVC 80 (' || CAST(LEFT(cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
            END AS designation,
            CASE 
                WHEN cm_compo ILIKE '%45' THEN 'PVC 45'
                WHEN cm_compo ILIKE '%60' THEN 'PVC 60'
                WHEN cm_compo ILIKE '%80' THEN 'PVC 80'
            END AS pvc_type,
            cm_compo,
            CAST(LEFT(cm_compo,1) AS INTEGER) * SUM(long_plan) AS total_length,
            string_agg(gid::text, ',') AS gids
        FROM gc_exe.t_cheminement
        WHERE sro = p_sro
        AND (p_troncon IS NULL OR gc = p_troncon)
        AND cm_avct = 'C' 
        AND (
            CASE 
                WHEN v_is_mixte THEN cm_typ_imp = '7'  -- Pour mixte : seulement souterrain pour le PVC
                ELSE cm_typ_imp = v_typ_imp
            END
        )
        AND cm_compo ILIKE '%pvc%' 
        AND (cm_compo ILIKE '%45' OR cm_compo ILIKE '%60' OR cm_compo ILIKE '%80')
        GROUP BY 
            CASE 
                WHEN cm_compo ILIKE '%45' THEN 'PVC 45 (' || CAST(LEFT(cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN cm_compo ILIKE '%60' THEN 'PVC 60 (' || CAST(LEFT(cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
                WHEN cm_compo ILIKE '%80' THEN 'PVC 80 (' || CAST(LEFT(cm_compo,1) AS TEXT) || ' fois les longueur par tranchée)'
            END,
            CASE 
                WHEN cm_compo ILIKE '%45' THEN 'PVC 45'
                WHEN cm_compo ILIKE '%60' THEN 'PVC 60'
                WHEN cm_compo ILIKE '%80' THEN 'PVC 80'
            END,
            cm_compo
    ),
    
    -- Données PEHD (une fois la longueur au ml de tranchée)
    pehd_data AS (
        SELECT
            cm_compo AS designation,
            SUM(long_plan) AS total_length,
            string_agg(gid::text, ',') AS gids
        FROM gc_exe.t_cheminement
        WHERE sro = p_sro
        AND (p_troncon IS NULL OR gc = p_troncon)
        AND cm_avct = 'C' 
        AND (
            CASE 
                WHEN v_is_mixte THEN cm_typ_imp = '7'  -- Pour mixte : seulement souterrain pour le PEHD
                ELSE cm_typ_imp = v_typ_imp
            END
        )
        AND cm_compo ILIKE '%PEHD%'
        GROUP BY cm_compo
    ),
    
    all_rows AS (
        -- 1. Nom GC avec tronçon spécifique ou liste des tronçons
        SELECT 1 AS ordre, 'Nom GC : ' || COALESCE(v_gc_name, '') AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 2-3. Lignes vides
        SELECT 2 AS ordre, '' AS designation, '' AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        SELECT 3 AS ordre, '' AS designation, '' AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 4. En-tête Description/Unité/Quantité  
        SELECT 4 AS ordre, 'Désignation' AS designation, 'Unité' AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 5. Armoire de rue HEADER
        SELECT 5 AS ordre, 'Armoire de rue  - (hors fourniture)' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 6. Armoire de rue détail
        SELECT 6 AS ordre, 'Terrassement, Pose d''un socle préfa en Béton, bétonnage et Pose d''une armoire de rue (y-compris transport, mise à la terre, réfection a l''identique)' AS designation, 'U' AS unite, 0::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 7. GC HEADER
        SELECT 7 AS ordre, 'GC - TDR + RAD (hors fourniture tube PEHD ou PVC et chambres)' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 8. Tranchée traditionnelle sous chaussée
        SELECT 8 AS ordre, 'Tranchée traditionnelle sous chaussée' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Tranchée traditionnelle sous chaussée'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Tranchée traditionnelle sous chaussée' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 9. Tranchée traditionnelle sous trottoir
        SELECT 9 AS ordre, 'Tranchée traditionnelle sous trottoir' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Tranchée traditionnelle sous trottoir'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Tranchée traditionnelle sous trottoir' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 10. Tranchée traditionnelle sous accotement
        SELECT 10 AS ordre, 'Tranchée traditionnelle sous accotement' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Tranchée traditionnelle sous accotement'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Tranchée traditionnelle sous accotement' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 11. Tranchée traditionnelle sous Espace Vert
        SELECT 11 AS ordre, 'Tranchée traditionnelle sous Espace Vert ou chemin empierré' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Tranchée traditionnelle sous Espace Vert ou chemin empierré'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Tranchée traditionnelle sous Espace Vert ou chemin empierré' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 12. Micro tranchée sous chaussée
        SELECT 12 AS ordre, 'Micro tranchée sous chaussée' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Micro tranchée sous chaussée'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Micro tranchée sous chaussée' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 13. Micro tranchée sous rive
        SELECT 13 AS ordre, 'Micro tranchée sous rive' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Micro tranchée sous rive'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Micro tranchée sous rive' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 14. Tranchée mécanisée sous accotement
        SELECT 14 AS ordre, 'Tranchée mécanisée ou SOC sous accotement' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Tranchée mécanisée ou SOC sous accotement'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Tranchée mécanisée ou SOC sous accotement' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 15. Tranchée mécanisée sous Espace Vert
        SELECT 15 AS ordre, 'Tranchée mécanisée sous Espace Vert ou chemin empierré' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Tranchée mécanisée sous Espace Vert ou chemin empierré'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Tranchée mécanisée sous Espace Vert ou chemin empierré' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 16. Forage dirigé
        SELECT 16 AS ordre, 'Forage dirigé ou fonçage' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Forage dirigé ou fonçage'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Forage dirigé ou fonçage' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 17. Encorbellement
        SELECT 17 AS ordre, 'Encorbellement' AS designation, 'ml' AS unite,
            COALESCE((SELECT SUM(total_length) FROM cheminement_grouped 
                     WHERE designation = 'Encorbellement'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM cheminement_grouped 
             WHERE designation = 'Encorbellement' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 18-25. CHAMBRES
        SELECT 18 AS ordre, 'Pose de chambre L1T' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L1T'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L1T' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 19 AS ordre, 'Pose de chambre L2T' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L2T'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L2T' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 20 AS ordre, 'pose de chambre L3T' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L3T'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L3T' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 21 AS ordre, 'pose de chambre L4T' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L4T'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L4T' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 22 AS ordre, 'pose de chambre L5T' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L5T'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L5T' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 23 AS ordre, 'pose de chambre L2C' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L2C'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L2C' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 24 AS ordre, 'pose de chambre L3C' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'L3C'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'L3C' LIMIT 1) AS gids
        
        UNION ALL
        
        SELECT 25 AS ordre, 'pose de chambre K2C' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM chambres_data WHERE inf_mat = 'K2C'), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM chambres_data WHERE inf_mat = 'K2C' LIMIT 1) AS gids
        
        UNION ALL
        
        -- 26. POSE DE POTEAUX HEADER
        SELECT 26 AS ordre, 'Pose de poteaux' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 27. Poteau RAUV
        SELECT 27 AS ordre, 'pose poteau RAUV' AS designation, 'U' AS unite,
            COALESCE((SELECT SUM(quantity) FROM poteaux_data), 0) AS quantite,
            (SELECT string_agg(gids, ',') FROM poteaux_data LIMIT 1) AS gids
        
        UNION ALL
        
        -- 28-29. Lignes vides
        SELECT 28 AS ordre, '' AS designation, '' AS unite, NULL::numeric AS quantite, NULL AS gids
        UNION ALL
        SELECT 29 AS ordre, '' AS designation, '' AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 30. FOURNITURE DES ALVÉOLES HEADER
        SELECT 30 AS ordre, 'Fourniture des Alvéoles' AS designation, NULL AS unite, NULL::numeric AS quantite, NULL AS gids
        
        UNION ALL
        
        -- 31-33. PVC DYNAMIQUE (selon les types trouvés)
        SELECT 
            30 + (row_number() OVER (ORDER BY 
                CASE 
                    WHEN p.pvc_type = 'PVC 45' THEN 1
                    WHEN p.pvc_type = 'PVC 60' THEN 2
                    WHEN p.pvc_type = 'PVC 80' THEN 3
                    ELSE 4
                END, 
                p.cm_compo
            )) AS ordre,
            p.designation AS designation,
            'ml' AS unite,
            COALESCE(p.total_length, 0) AS quantite,
            p.gids AS gids
        FROM pvc_data p
        
        UNION ALL
        
        -- PEHD DYNAMIQUE (après les PVC)
        SELECT 
            35 + (row_number() OVER (ORDER BY p.designation)) AS ordre,
            p.designation AS designation,
            'ml' AS unite,
            COALESCE(p.total_length, 0) AS quantite,
            p.gids AS gids
        FROM pehd_data p
    )
    SELECT 
        designation, 
        unite, 
        quantite,
        gids 
    FROM all_rows
    WHERE ordre IS NOT NULL
    ORDER BY ordre;
END;
$BODY$;

ALTER FUNCTION rip_avg_nge.dqe_pgc(text, text)
    OWNER TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_pgc(text, text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_pgc(text, text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_pgc(text, text) TO ownergrp_auvergne;

GRANT EXECUTE ON FUNCTION rip_avg_nge.dqe_pgc(text, text) TO sdupays;

COMMENT ON FUNCTION rip_avg_nge.dqe_pgc(text, text)
    IS 'Fonction DQE PGC (Plan de Génie Civil) ';
