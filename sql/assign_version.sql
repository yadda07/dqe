-- FUNCTION: dqe.assign_version()

-- DROP FUNCTION IF EXISTS dqe.assign_version();

CREATE OR REPLACE FUNCTION dqe.assign_version()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$
DECLARE
    last_version TEXT;
BEGIN
    -- Récupérer la dernière version pour le même sro et projet
    SELECT version_projet INTO last_version
    FROM dqe.dqejson
    WHERE sro = NEW.sro AND projet = NEW.projet and categorie = NEW.categorie  
    ORDER BY audit_timestamp DESC
    LIMIT 1;

    IF last_version IS NULL THEN
        NEW.version_projet := 'A';
    ELSE
        NEW.version_projet := dqe.nextval_alpha(last_version);
    END IF;

    RETURN NEW;
END;
$BODY$;

GRANT EXECUTE ON FUNCTION dqe.assign_version() TO PUBLIC;

