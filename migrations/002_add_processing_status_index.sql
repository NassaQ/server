-- ============================================================================
-- NassaQ Server — Schema Migration 002
-- Adds: composite index on Processing_Status (doc_id, stage_name)
-- ============================================================================
-- Run against the NassaQ SQL Server database.
-- Safe to re-run: uses IF NOT EXISTS guard.
-- ============================================================================

-- 1. Create index on Processing_Status (doc_id, stage_name)
--    Speeds up:
--      - Retrieving processing status for a specific document + stage
--      - Dashboard queries that filter by status per document
--      - Correlated subquery in Documents list (status_filter + stage_name)
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Processing_Status') AND name = 'IX_ProcessingStatus_DocId_Stage'
)
CREATE INDEX IX_ProcessingStatus_DocId_Stage
    ON Processing_Status (doc_id, stage_name)
    INCLUDE (status, error_message, start_time, end_time);
GO
