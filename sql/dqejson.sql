-- Table: dqe.dqejson

-- DROP TABLE IF EXISTS dqe.dqejson;

CREATE TABLE IF NOT EXISTS dqe.dqejson
(
    id integer NOT NULL DEFAULT nextval('dqe.dqejson_id_seq'::regclass),
    sro character varying(255) COLLATE pg_catalog."default",
    nom_dqe character varying(255) COLLATE pg_catalog."default",
    projet character varying(2) COLLATE pg_catalog."default",
    categorie character varying(255) COLLATE pg_catalog."default",
    champs jsonb,
    user_name character varying(255) COLLATE pg_catalog."default" DEFAULT CURRENT_USER,
    audit_timestamp timestamp without time zone DEFAULT now(),
    version_projet character varying(10) COLLATE pg_catalog."default",
    CONSTRAINT dqejson_pkey PRIMARY KEY (id)
)

TABLESPACE pg_default;

-- Trigger: tr_ajust_sequence

-- DROP TRIGGER IF EXISTS tr_ajust_sequence ON dqe.dqejson;

CREATE OR REPLACE TRIGGER tr_ajust_sequence
    BEFORE INSERT
    ON dqe.dqejson
    FOR EACH STATEMENT
    EXECUTE FUNCTION dqe.adjust_sequence();

-- Trigger: tr_assign_version

-- DROP TRIGGER IF EXISTS tr_assign_version ON dqe.dqejson;

CREATE OR REPLACE TRIGGER tr_assign_version
    BEFORE INSERT
    ON dqe.dqejson
    FOR EACH ROW
    EXECUTE FUNCTION dqe.assign_version();