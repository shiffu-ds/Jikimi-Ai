-- PostgreSQL 16 + pgvector (ADR-006). Embeddings use halfvec(768) to halve storage (plan 7.14).
CREATE EXTENSION IF NOT EXISTS vector;
