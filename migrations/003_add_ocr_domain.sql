-- ============================================================================
-- NassaQ Server — Schema Migration 003
-- Adds: domain column to Ocr_Results for hierarchical classification
-- ============================================================================
-- Run against the NassaQ SQL Server database.
-- Safe to re-run: uses IF NOT EXISTS guard.
-- ============================================================================

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Ocr_Results') AND name = 'domain'
)
ALTER TABLE Ocr_Results ADD domain VARCHAR(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL;
GO
