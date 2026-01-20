-- FUNCTION: dqe.nextval_alpha(text)

-- DROP FUNCTION IF EXISTS dqe.nextval_alpha(text);

CREATE OR REPLACE FUNCTION dqe.nextval_alpha(
	text)
    RETURNS text
    LANGUAGE 'plpgsql'
    COST 100
    VOLATILE PARALLEL UNSAFE
AS $BODY$
DECLARE
    input ALIAS FOR $1;
    i INTEGER;
    carry BOOLEAN := TRUE;
    result TEXT := '';
    c CHAR;
BEGIN
    FOR i IN REVERSE LENGTH(input)..1 LOOP
        c := SUBSTRING(input, i, 1);
        IF carry THEN
            IF c = 'Z' THEN
                result := 'A' || result;
                carry := TRUE;
            ELSE
                result := CHR(ASCII(c) + 1) || result;
                carry := FALSE;
            END IF;
        ELSE
            result := c || result;
        END IF;
    END LOOP;

    IF carry THEN
        result := 'A' || result;
    END IF;

    RETURN result;
END;
$BODY$;

ALTER FUNCTION dqe.nextval_alpha(text)
    OWNER TO yadda;

GRANT EXECUTE ON FUNCTION dqe.nextval_alpha(text) TO PUBLIC;

GRANT EXECUTE ON FUNCTION dqe.nextval_alpha(text) TO auvergne_sch_etudes;

GRANT EXECUTE ON FUNCTION dqe.nextval_alpha(text) TO yadda;

