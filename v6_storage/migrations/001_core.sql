CREATE TABLE IF NOT EXISTS bist_v6.symbols(symbol text PRIMARY KEY, metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS bist_v6.data_sources(source_id text PRIMARY KEY, metadata jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS bist_v6.documents(dataset text PRIMARY KEY, metadata jsonb NOT NULL, collections jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), source_hash text);
CREATE TABLE IF NOT EXISTS bist_v6.records(
 dataset text NOT NULL, record_id text NOT NULL, record_kind text NOT NULL,
 symbol text, predicted_at timestamptz, model_version text,
 frozen jsonb NOT NULL, frozen_hash text NOT NULL, current_hash text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(dataset,record_id));
CREATE INDEX IF NOT EXISTS records_symbol_time ON bist_v6.records(symbol,predicted_at);
CREATE INDEX IF NOT EXISTS records_kind_time ON bist_v6.records(record_kind,predicted_at);
CREATE TABLE IF NOT EXISTS bist_v6.record_extensions(dataset text NOT NULL, record_id text NOT NULL, field text NOT NULL, payload jsonb NOT NULL, checksum text NOT NULL, PRIMARY KEY(dataset,record_id,field), FOREIGN KEY(dataset,record_id) REFERENCES bist_v6.records);
CREATE TABLE IF NOT EXISTS bist_v6.row_states(dataset text NOT NULL, record_id text NOT NULL, payload jsonb NOT NULL, PRIMARY KEY(dataset,record_id), FOREIGN KEY(dataset,record_id) REFERENCES bist_v6.records);
CREATE TABLE IF NOT EXISTS bist_v6.outcomes(dataset text NOT NULL, record_id text NOT NULL, horizon text NOT NULL, horizon_sessions smallint, payload jsonb NOT NULL, checksum text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(dataset,record_id,horizon), FOREIGN KEY(dataset,record_id) REFERENCES bist_v6.records);
CREATE INDEX IF NOT EXISTS outcomes_horizon ON bist_v6.outcomes(horizon_sessions);
CREATE TABLE IF NOT EXISTS bist_v6.conflicts(dataset text NOT NULL, record_id text NOT NULL, incoming_hash text NOT NULL, incoming jsonb NOT NULL, reason text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(dataset,record_id,incoming_hash));
CREATE TABLE IF NOT EXISTS bist_v6.import_sources(source_id text PRIMARY KEY, dataset text, fingerprint jsonb NOT NULL, raw_sha256 text, records_verified bigint NOT NULL DEFAULT 0, cursor jsonb, status text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS bist_v6.import_receipts(source_id text NOT NULL, record_id text NOT NULL, checksum text NOT NULL, PRIMARY KEY(source_id,record_id));
CREATE TABLE IF NOT EXISTS bist_v6.outbox_receipts(journal_id text NOT NULL, sequence bigint NOT NULL, checksum text NOT NULL, PRIMARY KEY(journal_id,sequence));
CREATE TABLE IF NOT EXISTS bist_v6.job_states(job_id text PRIMARY KEY, payload jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS bist_v6.task_errors(job_id text NOT NULL, day date NOT NULL, error_code text NOT NULL, error_hash text NOT NULL, safe_payload jsonb NOT NULL, occurrences bigint NOT NULL DEFAULT 1, PRIMARY KEY(job_id,day,error_hash));
CREATE TABLE IF NOT EXISTS bist_v6.archives(archive_id text PRIMARY KEY, raw_sha256 text NOT NULL, compressed_sha256 text NOT NULL, raw_bytes bigint NOT NULL, compressed_bytes bigint NOT NULL, manifest jsonb NOT NULL, verified_at timestamptz NOT NULL);
CREATE TABLE IF NOT EXISTS bist_v6.storage_usage(day date NOT NULL, backend text NOT NULL, sample jsonb NOT NULL, measured_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(day,backend));
CREATE OR REPLACE FUNCTION bist_v6.immutable_row() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN RAISE EXCEPTION 'V6_IMMUTABLE_RECORD'; END$$;
CREATE OR REPLACE FUNCTION bist_v6.freeze_record() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN
 IF TG_OP='DELETE' OR (NEW.frozen IS DISTINCT FROM OLD.frozen OR NEW.frozen_hash IS DISTINCT FROM OLD.frozen_hash OR NEW.record_id IS DISTINCT FROM OLD.record_id OR NEW.dataset IS DISTINCT FROM OLD.dataset OR NEW.predicted_at IS DISTINCT FROM OLD.predicted_at OR NEW.model_version IS DISTINCT FROM OLD.model_version OR NEW.symbol IS DISTINCT FROM OLD.symbol OR NEW.record_kind IS DISTINCT FROM OLD.record_kind OR NEW.created_at IS DISTINCT FROM OLD.created_at) THEN RAISE EXCEPTION 'V6_IMMUTABLE_RECORD'; END IF; RETURN NEW; END$$;
CREATE TRIGGER records_frozen BEFORE UPDATE OR DELETE ON bist_v6.records FOR EACH ROW EXECUTE FUNCTION bist_v6.freeze_record();
CREATE TRIGGER outcomes_frozen BEFORE UPDATE OR DELETE ON bist_v6.outcomes FOR EACH ROW EXECUTE FUNCTION bist_v6.immutable_row();
CREATE TRIGGER extensions_frozen BEFORE UPDATE OR DELETE ON bist_v6.record_extensions FOR EACH ROW EXECUTE FUNCTION bist_v6.immutable_row();
ALTER TABLE bist_v6.records ADD COLUMN ordinal bigint NOT NULL DEFAULT 0;
CREATE INDEX records_order ON bist_v6.records(dataset,ordinal,record_id);
CREATE TABLE bist_v6.record_quality(dataset text NOT NULL, record_id text NOT NULL, flags jsonb NOT NULL, PRIMARY KEY(dataset,record_id), FOREIGN KEY(dataset,record_id) REFERENCES bist_v6.records);
