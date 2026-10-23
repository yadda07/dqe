-- FUNCTION: dqe.adjust_sequence()

-- DROP FUNCTION IF EXISTS dqe.adjust_sequence();

CREATE OR REPLACE FUNCTION dqe.adjust_sequence()
    RETURNS trigger
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE NOT LEAKPROOF
AS $BODY$
DECLARE
    max_id INTEGER;
BEGIN
    SELECT MAX(id) INTO max_id FROM dqe.dqejson;

    -- Réinitialise la séquence à max_id + 1 si nécessaire
    IF max_id IS NOT NULL THEN
        PERFORM setval('dqe.dqejson_id_seq', max_id + 1, false);
    END IF;

    RETURN NEW;
END;
$BODY$;

GRANT EXECUTE ON FUNCTION dqe.adjust_sequence() TO PUBLIC;

