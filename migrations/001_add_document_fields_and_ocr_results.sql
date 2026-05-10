-- ============================================================================
-- NassaQ Server — Schema Migration
-- Adds: file_size, content_type, file_type, updated_at to Documents
-- Adds: Ocr_Results table
-- ============================================================================
-- Run against the NassaQ SQL Server database.
-- Safe to re-run: uses IF (NOT) EXISTS guards where possible.
-- ============================================================================

-- 1. Add new nullable columns to Documents
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Documents') AND name = 'file_size'
)
ALTER TABLE Documents ADD file_size BIGINT NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Documents') AND name = 'content_type'
)
ALTER TABLE Documents ADD content_type VARCHAR(100) COLLATE SQL_Latin1_General_CP1_CI_AS NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Documents') AND name = 'file_type'
)
ALTER TABLE Documents ADD file_type VARCHAR(10) COLLATE SQL_Latin1_General_CP1_CI_AS NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Documents') AND name = 'updated_at'
)
ALTER TABLE Documents ADD updated_at DATETIME NULL;
GO

-- 2. Create Ocr_Results table
IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'Ocr_Results')
CREATE TABLE Ocr_Results (
    result_id               BIGINT IDENTITY(1,1) NOT NULL,
    doc_id                  BIGINT NOT NULL,
    page_count              INT NOT NULL,
    word_count              INT NOT NULL,
    avg_confidence          FLOAT NOT NULL,
    primary_language        VARCHAR(10) COLLATE SQL_Latin1_General_CP1_CI_AS NOT NULL,
    category                VARCHAR(50) COLLATE SQL_Latin1_General_CP1_CI_AS NULL,
    classification_confidence FLOAT NULL,
    cost_usd_ocr            FLOAT NOT NULL,
    cost_usd_classification FLOAT NULL,
    processed_at            DATETIME NOT NULL DEFAULT (getutcdate()),

    CONSTRAINT PK_OcrResults PRIMARY KEY (result_id),
    CONSTRAINT FK_OcrResults_Doc FOREIGN KEY (doc_id)
        REFERENCES Documents(doc_id)
);
GO

-- 3. Create index on Ocr_Results.doc_id for fast lookup
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Ocr_Results') AND name = 'IX_OcrResults_DocId'
)
CREATE INDEX IX_OcrResults_DocId ON Ocr_Results (doc_id);
GO
