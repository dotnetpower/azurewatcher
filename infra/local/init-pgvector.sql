-- Enable pgvector so T1 similarity search (Phase 2) has the right runtime
-- available from day zero of the local stack.
CREATE EXTENSION IF NOT EXISTS vector;
