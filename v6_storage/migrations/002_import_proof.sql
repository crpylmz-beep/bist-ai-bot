CREATE TABLE bist_v6.import_conflicts(source_id text NOT NULL,collection text NOT NULL,record_id text NOT NULL,incoming_hash text NOT NULL,PRIMARY KEY(source_id,collection,record_id,incoming_hash));
CREATE TABLE bist_v6.import_proofs(source_id text NOT NULL,collection text NOT NULL,record_id text NOT NULL,checksum text NOT NULL,PRIMARY KEY(source_id,collection,record_id));
