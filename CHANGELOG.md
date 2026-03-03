# Change Log

All notable changes to this project will be documented in this file. This change log follows the conventions of [keepachangelog.com](https://keepachangelog.com/).

## [Unreleased]

### Added

- New Azure Bus service as a cloud choice for message broker. Set as default in the production environment.

---

## [0.1.0] - 2026-02-26

> Initial release. Establishes the full backend foundation: authentication, user management,
> document upload with async OCR dispatch, and Azure cloud integrations.

### Added

- FastAPI application foundation — project structure, Pydantic settings, and environment-based behaviour (`dev` vs `production`)
- SQL Server database session with async SQLAlchemy 2.0, connection pooling (`pool_pre_ping`, `pool_recycle`), and exponential backoff retry to handle Azure SQL cold starts
- SQLAlchemy ORM models for the full database schema: Users, Roles, Role Actions, Actions, Individual Permissions, Documents, Virtual Paths, Processing Status, and Logs
- User registration endpoint with bcrypt password hashing and auto-generated username derived from email
- JWT authentication — login via OAuth2 password flow, dual-token issuance (short-lived access token + long-lived refresh token), and a dedicated token refresh endpoint
- Current user profile endpoint (`GET /users/me`) and self-service profile update
- Admin user management endpoints — list all users, list pending (inactive) users, update any user, activate a user, and delete a user
- Virtual path management endpoints — list (with depth and prefix filters), create, update, and delete paths
- Document upload endpoint — multipart file upload (up to 50 MB), Azure Blob Storage integration, SQL document record creation, and processing status initialisation (`Queued`)
- Abstract blob storage interface (`StorageBase`) with a full Azure Blob Storage implementation
- RabbitMQ message broker integration — abstract broker interface (`BaseBroker`), async connection lifecycle tied to FastAPI lifespan, and persistent message publish to `ocr_queue` on every upload
- Role-based access control enforced via three dependency tiers: `CurrentUser`, `ActiveUser`, and `AdminUser`
- Multi-stage Dockerfile — builder stage compiles dependencies with `uv`; runtime stage installs Microsoft ODBC Driver 18, runs as a non-root user, and exposes a health check on `GET /`
- Unit tests for security functions (bcrypt hashing, JWT creation, decoding, and tamper detection) and Pydantic schema validation (user creation, login, update, and password strength rules)

### Fixed

- Orphaned files in blob storage caused by a failure after upload but before the database record was committed
- Database engine connection timeout and pre-ping verification to prevent stale connections
- OpenAPI schema (`/openapi.json`), Swagger UI (`/docs`), and ReDoc (`/redoc`) are now disabled in production mode
