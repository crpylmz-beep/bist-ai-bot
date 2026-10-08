CREATE TABLE bist_v6.document_projections(dataset text NOT NULL,collection text NOT NULL,ids jsonb NOT NULL,checksum text NOT NULL,PRIMARY KEY(dataset,collection));
ALTER TABLE bist_v6.import_proofs ADD COLUMN ordinal bigint NOT NULL DEFAULT 0;
