-- FUNCTION: gc_exe.gestionnaire(character varying, character varying)

-- DROP FUNCTION IF EXISTS gc_exe.gestionnaire(character varying, character varying);

CREATE OR REPLACE FUNCTION gc_exe.gestionnaire(
	p_sro character varying,
	p_gc character varying)
    RETURNS TABLE(troncon_gid integer, segment_id integer, cm_gest_do character varying, cm_compo character varying, cm_typ_imp integer, geom_segment geometry, long numeric, distance_route_m numeric, angle_parallelisme_deg numeric, confiance_niveau character varying, methode_attribution character varying, nb_pot_ac integer) 
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
    ROWS 1000

AS $BODY$
DECLARE
    resolution_analyse numeric := 2.0; -- Résolution pour analyse parallélisme
    buffer_recherche numeric := 50.0; -- Réduit pour éviter routes trop éloignées
    seuil_parallelisme numeric := 20.0; -- Légèrement assoupli
    seuil_decoupage numeric := 0.5; -- Plus strict pour éviter découpage excessif
    distance_max_acceptable numeric := 15.0; -- RÉDUIT: Distance max acceptable
    densite_carrefour numeric := 3.0; -- Seuil détection carrefour (nb routes/50m)
BEGIN
    RETURN QUERY
    WITH 
    -- ÉTAPE 1: Récupération tronçons avec ordre topologique
    troncons_ordonnes AS (
        SELECT 
            t.gid as troncon_gid_orig,
            t.geom as geom_troncon_orig,
            t.cm_compo, 
            t.cm_typ_imp,
            ST_Length(t.geom) as longueur_troncon,
            ROW_NUMBER() OVER (ORDER BY ST_X(ST_Centroid(t.geom)), ST_Y(ST_Centroid(t.geom))) as ordre_topo
        FROM gc_exe.t_cheminement t
        WHERE t.sro = p_sro AND t.gc = p_gc
          AND ST_GeometryType(t.geom) = 'ST_LineString'
          AND ST_Length(t.geom) > 0.5
    ),
    
    -- ÉTAPE 1B: Détection zones carrefour (NOUVEAU)
    detection_carrefour AS (
        SELECT 
            tro.troncon_gid_orig,
            tro.geom_troncon_orig,
            tro.cm_compo,  --  PROPAGATION cm_compo
            tro.cm_typ_imp, --  PROPAGATION cm_typ_imp
            tro.longueur_troncon,
            tro.ordre_topo,
            (SELECT COUNT(DISTINCT rf.gestionnaire) 
             FROM ign.routes_fusionnees rf 
             WHERE ST_DWithin(ST_Centroid(tro.geom_troncon_orig), rf.geom, buffer_recherche)
            ) as nb_routes_proches,
            CASE WHEN (SELECT COUNT(DISTINCT rf.gestionnaire) 
                      FROM ign.routes_fusionnees rf 
                      WHERE ST_DWithin(ST_Centroid(tro.geom_troncon_orig), rf.geom, buffer_recherche)
                     ) >= densite_carrefour 
                 THEN true 
                 ELSE false 
            END as est_carrefour
        FROM troncons_ordonnes tro
    ),
    
    -- ÉTAPE 2: Analyse fine par segmentation
    analyse_segments AS (
        SELECT 
            dc.troncon_gid_orig,
            dc.geom_troncon_orig,
            dc.cm_compo,  -- PROPAGATION cm_compo
            dc.cm_typ_imp, -- PROPAGATION cm_typ_imp
            dc.longueur_troncon,
            dc.ordre_topo,
            dc.est_carrefour,
            dc.nb_routes_proches,
            ST_Segmentize(dc.geom_troncon_orig, 
                         CASE WHEN dc.est_carrefour THEN resolution_analyse * 2 
                              ELSE resolution_analyse END) as geom_analyse
        FROM detection_carrefour dc
    ),
  
    -- ÉTAPE 3: Extraction points d'analyse
    points_analyse AS (
        SELECT 
            anas.troncon_gid_orig,
            anas.geom_troncon_orig,
            anas.cm_compo,  -- PROPAGATION cm_compo
            anas.cm_typ_imp, -- PROPAGATION cm_typ_imp
            anas.ordre_topo,
            anas.est_carrefour,
            generate_series(0, ST_NPoints(anas.geom_analyse) - 1) as point_index,
            ST_PointN(anas.geom_analyse, generate_series(1, ST_NPoints(anas.geom_analyse))) as point_geom,
            ST_LineLocatePoint(anas.geom_troncon_orig, 
                ST_PointN(anas.geom_analyse, generate_series(1, ST_NPoints(anas.geom_analyse)))) as position_relative
        FROM analyse_segments anas
    ),
    
    -- ÉTAPE 4: Attribution gestionnaire AMÉLIORÉE
    attribution_points AS (
        SELECT 
            pa.troncon_gid_orig,
            pa.geom_troncon_orig,
            pa.cm_compo,  -- PROPAGATION cm_compo
            pa.cm_typ_imp, -- PROPAGATION cm_typ_imp
            pa.ordre_topo,
            pa.point_index,
            pa.position_relative,
            pa.est_carrefour,
            
            -- CORRECTION MAJEURE: Distance d'abord, puis parallélisme
            (SELECT 
                rf.gestionnaire
            FROM ign.routes_fusionnees rf
            WHERE ST_DWithin(pa.point_geom, rf.geom, buffer_recherche)
              AND ST_Distance(pa.point_geom, rf.geom) <= 
                  CASE WHEN pa.est_carrefour THEN distance_max_acceptable * 1.5 
                       ELSE distance_max_acceptable END
            ORDER BY 
                -- PRIORITÉ 1: Distance (80% du score)
                ST_Distance(pa.point_geom, rf.geom) * 0.8 +
                -- PRIORITÉ 2: Parallélisme (20% du score)
                CASE WHEN 
                    ABS(
                        degrees(ST_Azimuth(
                            ST_LineInterpolatePoint(pa.geom_troncon_orig, GREATEST(0, pa.position_relative - 0.05)),
                            ST_LineInterpolatePoint(pa.geom_troncon_orig, LEAST(1, pa.position_relative + 0.05))
                        )) -
                        COALESCE(degrees(ST_Azimuth(
                            ST_LineInterpolatePoint(rf.geom, GREATEST(0, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) - 0.01)),
                            ST_LineInterpolatePoint(rf.geom, LEAST(1, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) + 0.01))
                        )), 0)
                    ) <= seuil_parallelisme
                THEN 0.0  -- Bonus si parallèle
                ELSE (distance_max_acceptable * 0.2)  -- Pénalité modérée si pas parallèle
                END
            LIMIT 1
            ) as gestionnaire_point,
            
            -- Métriques pour ce point
            (SELECT 
                ST_Distance(pa.point_geom, rf.geom)
            FROM ign.routes_fusionnees rf
            WHERE ST_DWithin(pa.point_geom, rf.geom, buffer_recherche)
              AND ST_Distance(pa.point_geom, rf.geom) <= 
                  CASE WHEN pa.est_carrefour THEN distance_max_acceptable * 1.5 
                       ELSE distance_max_acceptable END
            ORDER BY 
                ST_Distance(pa.point_geom, rf.geom) * 0.8 +
                CASE WHEN 
                    ABS(
                        degrees(ST_Azimuth(
                            ST_LineInterpolatePoint(pa.geom_troncon_orig, GREATEST(0, pa.position_relative - 0.05)),
                            ST_LineInterpolatePoint(pa.geom_troncon_orig, LEAST(1, pa.position_relative + 0.05))
                        )) -
                        COALESCE(degrees(ST_Azimuth(
                            ST_LineInterpolatePoint(rf.geom, GREATEST(0, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) - 0.01)),
                            ST_LineInterpolatePoint(rf.geom, LEAST(1, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) + 0.01))
                        )), 0)
                    ) <= seuil_parallelisme
                THEN 0.0
                ELSE (distance_max_acceptable * 0.2)
                END
            LIMIT 1
            ) as distance_point,
            
            (SELECT 
                ABS(
                    degrees(ST_Azimuth(
                        ST_LineInterpolatePoint(pa.geom_troncon_orig, GREATEST(0, pa.position_relative - 0.05)),
                        ST_LineInterpolatePoint(pa.geom_troncon_orig, LEAST(1, pa.position_relative + 0.05))
                    )) -
                    COALESCE(degrees(ST_Azimuth(
                        ST_LineInterpolatePoint(rf.geom, GREATEST(0, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) - 0.01)),
                        ST_LineInterpolatePoint(rf.geom, LEAST(1, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) + 0.01))
                    )), 0)
                )
            FROM ign.routes_fusionnees rf
            WHERE ST_DWithin(pa.point_geom, rf.geom, buffer_recherche)
              AND ST_Distance(pa.point_geom, rf.geom) <= 
                  CASE WHEN pa.est_carrefour THEN distance_max_acceptable * 1.5 
                       ELSE distance_max_acceptable END
            ORDER BY 
                ST_Distance(pa.point_geom, rf.geom) * 0.8 +
                CASE WHEN 
                    ABS(
                        degrees(ST_Azimuth(
                            ST_LineInterpolatePoint(pa.geom_troncon_orig, GREATEST(0, pa.position_relative - 0.05)),
                            ST_LineInterpolatePoint(pa.geom_troncon_orig, LEAST(1, pa.position_relative + 0.05))
                        )) -
                        COALESCE(degrees(ST_Azimuth(
                            ST_LineInterpolatePoint(rf.geom, GREATEST(0, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) - 0.01)),
                            ST_LineInterpolatePoint(rf.geom, LEAST(1, ST_LineLocatePoint(rf.geom, ST_ClosestPoint(rf.geom, pa.point_geom)) + 0.01))
                        )), 0)
                    ) <= seuil_parallelisme
                THEN 0.0
                ELSE (distance_max_acceptable * 0.2)
                END
            LIMIT 1
            ) as angle_point
            
        FROM points_analyse pa
    ),
    
    -- ÉTAPE 5: Gestionnaire dominant par tronçon
    gestionnaire_base AS (
        SELECT 
            ap.troncon_gid_orig,
            ap.geom_troncon_orig,
            ap.cm_compo, ap.cm_typ_imp, ap.ordre_topo,
            MAX(ap.est_carrefour::int)::boolean as est_carrefour, -- Propager info carrefour
            
            -- Gestionnaire le plus fréquent sur le tronçon
            mode() WITHIN GROUP (ORDER BY ap.gestionnaire_point) as gestionnaire_maj,
            
            -- Métriques moyennes
            AVG(ap.distance_point) as distance_moyenne,
            AVG(ap.angle_point) as angle_moyen,
            COUNT(*) as total_points
            
        FROM attribution_points ap
        WHERE ap.gestionnaire_point IS NOT NULL
        GROUP BY ap.troncon_gid_orig, ap.geom_troncon_orig, ap.cm_compo, ap.cm_typ_imp, ap.ordre_topo
    ),

    taux_homogeneite AS (
        SELECT 
            gb.troncon_gid_orig,
            gb.gestionnaire_maj,
            gb.total_points,
            gb.est_carrefour,
            (SELECT COUNT(*) FROM attribution_points ap2 
             WHERE ap2.troncon_gid_orig = gb.troncon_gid_orig 
               AND ap2.gestionnaire_point = gb.gestionnaire_maj
               AND ap2.gestionnaire_point IS NOT NULL
            )::numeric / NULLIF(gb.total_points::numeric, 0) as taux_homo
        FROM gestionnaire_base gb
    ),
    analyse_continuite AS (
        SELECT 
            gb.*,
            COALESCE(th.taux_homo, 0) as taux_homogeneite,
            LAG(gb.gestionnaire_maj) OVER (ORDER BY gb.ordre_topo) as gestionnaire_precedent,
            LEAD(gb.gestionnaire_maj) OVER (ORDER BY gb.ordre_topo) as gestionnaire_suivant
            
        FROM gestionnaire_base gb
        LEFT JOIN taux_homogeneite th ON gb.troncon_gid_orig = th.troncon_gid_orig
    ),
    
    -- ÉTAPE 7: Décision finale avec logique carrefour 
    gestionnaire_dominant AS (
        SELECT 
            ac.troncon_gid_orig,
            ac.geom_troncon_orig,
            ac.cm_compo,
            ac.cm_typ_imp,  
            ac.gestionnaire_maj  gestionnaire_majoritaire,
            ac.taux_homogeneite,
            ac.distance_moyenne,
            ac.angle_moyen,
            ac.est_carrefour,
            ac.gestionnaire_precedent,
            ac.gestionnaire_suivant,
            
            -- Correction par continuité SAUF en carrefour
            CASE 
                WHEN ac.est_carrefour THEN ac.gestionnaire_maj -- 🔧 CARREFOUR: garder gestionnaire majoritaire
                WHEN ac.taux_homogeneite < 0.6 
                     AND ac.gestionnaire_precedent = ac.gestionnaire_suivant 
                     AND ac.gestionnaire_precedent IS NOT NULL
                THEN ac.gestionnaire_precedent
                ELSE ac.gestionnaire_maj
            END as gestionnaire_final,
            
            -- Méthode d'attribution finale
            CASE 
                WHEN ac.est_carrefour THEN 'CARREFOUR_DIRECT'
                WHEN ac.taux_homogeneite >= 0.8 THEN 'ANALYSE_DIRECTE'
                WHEN ac.taux_homogeneite < 0.6 
                     AND ac.gestionnaire_precedent = ac.gestionnaire_suivant 
                THEN 'CONTINUITE_TOPO'
                ELSE 'MAJORITE_RELATIVE'
            END as methode_finale
            
        FROM analyse_continuite ac
    ),
    
    -- ÉTAPE 8: Décision découpage
    decision_decoupage AS (
        SELECT 
            gd.*,
            CASE 
                WHEN gd.est_carrefour THEN false -- INTERDIT en carrefour
                WHEN gd.taux_homogeneite < seuil_decoupage 
                     AND gd.methode_finale = 'MAJORITE_RELATIVE'
                     AND ST_Length(gd.geom_troncon_orig) > 15.0 -- Tronçons plus longs seulement
                THEN true
                ELSE false
            END as doit_decouper
        FROM gestionnaire_dominant gd
    ),
    
    -- ÉTAPE 9A: Tronçons à garder entiers (MAJORITÉ DES CAS)
    troncons_entiers AS (
        SELECT 
            dd.troncon_gid_orig as troncon_gid,
            1 as segment_id,
            dd.gestionnaire_final as gestionnaire_attribue,
            dd.cm_compo,
            dd.cm_typ_imp, 
            dd.geom_troncon_orig as geom_segment,
            ST_Length(dd.geom_troncon_orig) as longueur_segment_m,
            dd.distance_moyenne as distance_route_m,
            dd.angle_moyen as angle_parallelisme_deg,
            CASE 
                WHEN dd.est_carrefour THEN 'CARREFOUR'
                WHEN dd.distance_moyenne <= 8 AND dd.angle_moyen <= 15 THEN 'HAUTE'
                WHEN dd.distance_moyenne <= 20 AND dd.angle_moyen <= 25 THEN 'MOYENNE'
                ELSE 'FAIBLE'
            END as confiance_niveau,
            dd.methode_finale as methode_attribution
        FROM decision_decoupage dd
        WHERE dd.doit_decouper = false
    ),
    
    -- ÉTAPE 9B: Découpage exceptionnel (hors carrefour uniquement)
    changements_gestionnaire AS (
        SELECT 
            ap.troncon_gid_orig,
            ap.geom_troncon_orig,
            ap.cm_compo,
            ap.cm_typ_imp, 
            ap.gestionnaire_point,
            ap.position_relative,
            CASE WHEN ap.gestionnaire_point != LAG(ap.gestionnaire_point, 1, ap.gestionnaire_point) 
                      OVER (PARTITION BY ap.troncon_gid_orig ORDER BY ap.position_relative) 
                 THEN 1 ELSE 0 END as changement
        FROM attribution_points ap
        INNER JOIN decision_decoupage dd ON ap.troncon_gid_orig = dd.troncon_gid_orig
        WHERE dd.doit_decouper = true
          AND ap.gestionnaire_point IS NOT NULL
    ),
    
    segments_continus AS (
        SELECT 
            cg.troncon_gid_orig,
            cg.geom_troncon_orig,
            cg.cm_compo,
            cg.cm_typ_imp, 
            cg.gestionnaire_point,
            cg.position_relative,
            SUM(cg.changement) OVER (PARTITION BY cg.troncon_gid_orig ORDER BY cg.position_relative) as groupe_gestionnaire
        FROM changements_gestionnaire cg
    ),
    
    bornes_segments AS (
        SELECT 
            sc.troncon_gid_orig,
            sc.geom_troncon_orig,
            sc.cm_compo,
            sc.cm_typ_imp,
            sc.groupe_gestionnaire,
            sc.gestionnaire_point,
            MIN(sc.position_relative) as pos_debut,
            MAX(sc.position_relative) as pos_fin
        FROM segments_continus sc
        GROUP BY sc.troncon_gid_orig, sc.geom_troncon_orig, sc.cm_compo, sc.cm_typ_imp, sc.groupe_gestionnaire, sc.gestionnaire_point
        HAVING MAX(sc.position_relative) > MIN(sc.position_relative)
    ),
    
    metriques_segments AS (
        SELECT 
            bs.troncon_gid_orig,
            bs.groupe_gestionnaire,
            bs.gestionnaire_point,
            bs.pos_debut,
            bs.pos_fin,
            AVG(ap.distance_point) as distance_moyenne,
            AVG(ap.angle_point) as angle_moyen
        FROM bornes_segments bs
        INNER JOIN attribution_points ap ON ap.troncon_gid_orig = bs.troncon_gid_orig
                                        AND ap.gestionnaire_point = bs.gestionnaire_point
                                        AND ap.position_relative BETWEEN bs.pos_debut AND bs.pos_fin
        GROUP BY bs.troncon_gid_orig, bs.groupe_gestionnaire, bs.gestionnaire_point, bs.pos_debut, bs.pos_fin
    ),
    
    troncons_decoupe AS (
        SELECT 
            bs.troncon_gid_orig as troncon_gid,
            (bs.groupe_gestionnaire + 1) as segment_id,
            bs.gestionnaire_point as gestionnaire_attribue,
            bs.cm_compo,
            bs.cm_typ_imp,  
            ST_LineSubstring(bs.geom_troncon_orig, bs.pos_debut, bs.pos_fin) as geom_segment,
            ST_Length(ST_LineSubstring(bs.geom_troncon_orig, bs.pos_debut, bs.pos_fin)) as longueur_segment_m,
            COALESCE(ms.distance_moyenne, 12.0) as distance_route_m,
            COALESCE(ms.angle_moyen, 30.0) as angle_parallelisme_deg,
            'MOYENNE'::varchar as confiance_niveau,
            'DECOUPAGE_AUTO'::varchar as methode_attribution
        FROM bornes_segments bs
        LEFT JOIN metriques_segments ms ON bs.troncon_gid_orig = ms.troncon_gid_orig
                                       AND bs.groupe_gestionnaire = ms.groupe_gestionnaire
                                       AND bs.gestionnaire_point = ms.gestionnaire_point
    ),
    
    -- ÉTAPE 10: Union des résultats sans comptage poteaux
    segments_finaux AS (
        SELECT 
            te.troncon_gid,
            te.segment_id, 
            te.gestionnaire_attribue,
            te.cm_compo,
            te.cm_typ_imp,
            te.geom_segment,
            te.longueur_segment_m,
            te.distance_route_m,
            te.angle_parallelisme_deg,
            te.confiance_niveau,
            te.methode_attribution
        FROM troncons_entiers te
        
        UNION ALL
        
        SELECT 
            td.troncon_gid,
            td.segment_id,
            td.gestionnaire_attribue,
            td.cm_compo,
            td.cm_typ_imp,
            td.geom_segment,
            td.longueur_segment_m,
            td.distance_route_m,
            td.angle_parallelisme_deg,
            td.confiance_niveau,
            td.methode_attribution
        FROM troncons_decoupe td
    ),
    
    -- ÉTAPE 11: Attribution unique des poteaux au segment le plus proche
    attribution_poteaux AS (
        SELECT 
            p.gid as poteau_id,
            sf.troncon_gid,
            sf.segment_id,
            ST_Distance(sf.geom_segment, p.geom) as distance_segment,
            ROW_NUMBER() OVER (PARTITION BY p.gid ORDER BY ST_Distance(sf.geom_segment, p.geom)) as rang_distance
        FROM gc_exe.infra_pt_pot p
        CROSS JOIN segments_finaux sf
        WHERE p.inf_type = 'POT-AC'
          AND ST_DWithin(sf.geom_segment, p.geom, 0.5)
    ),
    
    -- ÉTAPE 12: Comptage final des poteaux par segment (sans doublons)
    comptage_poteaux AS (
        SELECT 
            ap.troncon_gid,
            ap.segment_id,
            COUNT(ap.poteau_id) as nb_pot_ac
        FROM attribution_poteaux ap
        WHERE ap.rang_distance = 1  -- Seulement le segment le plus proche
        GROUP BY ap.troncon_gid, ap.segment_id
    )
    
    -- ÉTAPE 13: Résultat final avec comptage poteaux
    SELECT 
        sf.troncon_gid::integer,
        sf.segment_id::integer, 
        sf.gestionnaire_attribue::varchar,
        sf.cm_compo::varchar,
        sf.cm_typ_imp::integer,
        sf.geom_segment::geometry,
        ROUND(sf.longueur_segment_m::numeric, 2),
        ROUND(sf.distance_route_m::numeric, 2),
        ROUND(sf.angle_parallelisme_deg::numeric, 2),
        sf.confiance_niveau::varchar(10),
        sf.methode_attribution::varchar(20),
        COALESCE(cp.nb_pot_ac, 0)::integer
    FROM segments_finaux sf
    LEFT JOIN comptage_poteaux cp ON sf.troncon_gid = cp.troncon_gid 
                                  AND sf.segment_id = cp.segment_id
    
    ORDER BY sf.troncon_gid, sf.segment_id;

END;
$BODY$;

ALTER FUNCTION gc_exe.gestionnaire(character varying, character varying)
    OWNER TO yadda;

GRANT EXECUTE ON FUNCTION gc_exe.gestionnaire(character varying, character varying) TO PUBLIC;

GRANT EXECUTE ON FUNCTION gc_exe.gestionnaire(character varying, character varying) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION gc_exe.gestionnaire(character varying, character varying) TO yadda;

