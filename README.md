# NassaQ — Backend Server

The central API gateway for the NassaQ document digitization platform. Handles authentication, file uploads, virtual path management, and OCR job dispatch.

---

## Overview

This repository is the **Backend Server** component of NassaQ — an AI-powered platform that processes uploaded documents through bilingual (Arabic/English) OCR pipelines and makes them searchable.

The server is responsible for the full request lifecycle: authenticating users, accepting file uploads, storing files in Azure Blob Storage, recording metadata in Azure SQL Server, and publishing processing jobs to a RabbitMQ queue for the OCR worker to consume asynchronously.

For platform-wide documentation, see [docs](https://nassaq.github.io/docs).

---

## Platform Architecture

NassaQ is composed of three independently deployable services:

| Component | Repository | Technology |
|---|---|---|
| **Backend Server** | `NassaQ/server` *(this repo)* | Python 3.11, FastAPI, SQLAlchemy 2.0 |
| **OCR Worker** | `NassaQ/ocr-api` | Python 3.11, FastAPI, PaddleOCR, EasyOCR |
| **User Interface** | `NassaQ/User_Interface` | React 18, TypeScript, Vite 5, Tailwind CSS |

Services communicate via REST (frontend → server) and AMQP (server → OCR worker via RabbitMQ). All persistent storage is on Azure managed services for now, we are planning to support local storage setup soon.

---

## Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| **Framework** | FastAPI + Uvicorn | Async web framework and ASGI server |
| **ORM** | SQLAlchemy 2.0 (async, `aioodbc`) | Database access layer |
| **Primary Database** | Azure SQL Server (ODBC 18) | Users, documents, paths, roles, audit logs |
| **File Storage** | Azure Blob Storage | Upload and retrieval of original documents |
| **Message Broker** | RabbitMQ (`aio-pika`) | Async job queue for OCR dispatch |
| **Auth** | `python-jose` + `passlib[bcrypt]` | JWT tokens and password hashing |
| **Validation** | Pydantic v2 + Pydantic Settings | Request/response schemas and config |
| **Package Manager** | `uv` | Dependency management and virtual environments |

---

## Getting Started

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | >= 3.11 | |
| [uv](https://docs.astral.sh/uv/) | Latest | Package manager |
| Docker | 20+ | Required for RabbitMQ and containerized deployment |
| ODBC Driver 18 | Latest | SQL Server connectivity (installed automatically in Docker) |

### Environment Variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Every variable is documented inside `.env.example`. Two connection strings (SQL Server and MongoDB/Cosmos DB) are computed automatically from the individual fields — you do not set them directly.

### Local Development

**1. Install dependencies**

```bash
uv sync
```

**2. Start RabbitMQ** (required — the server connects to the broker on startup)

```bash
docker compose up rabbitmq -d
```

**3. Start the server**

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The server will be available at `http://localhost:8000`. Swagger UI is at `http://localhost:8000/docs` when `ENVIRONMENT="dev"`.

### Docker

```bash
# Build
docker build -t nassaq-server:latest .

# Run
docker run -d \
  --name nassaq-server \
  --env-file .env \
  -p 8000:8000 \
  nassaq-server:latest
```

The image uses a multi-stage build: a builder stage compiles dependencies, and a minimal runtime stage installs Microsoft ODBC Driver 18 and runs the app as a non-root user. Health check is `GET /` (returns `204 No Content`) every 30 seconds.

To run the full platform (server + OCR worker + RabbitMQ) together, see the [Deployment Guide](https://nassaq.github.io/docs/setup/deployment/).

---

## API Overview

All endpoints are versioned under `/api/v1`. Three authorization tiers are enforced:

| Route Group | Base Path | Description |
|---|---|---|
| **Auth** | `/api/v1/auth` | Register, login (OAuth2 password flow), token refresh |
| **Users** | `/api/v1/users` | Profile management (self) and user administration (admin) |
| **Documents** | `/api/v1/docs` | File upload — stores to Blob, creates DB record, dispatches to OCR queue |
| **Virtual Paths** | `/api/v1/paths` | Hierarchical folder management for organizing documents |

Full endpoint reference: [docs/reference/api-endpoints/](https://nassaq.github.io/docs/reference/api-endpoints/)

---

## Testing

```bash
uv sync --extra test
uv run pytest
```

The test suite covers:

- security functions tests.
- schemas function tests.


---

## Note on Contributions

> This project is a graduation project and is currently **not accepting external contributions**. The repository is on hold while the project is under academic review. Feel free to explore the code and documentation, but pull requests will not be reviewed at this time.

---

## Documentation

Full platform documentation is available at [nassaq.github.io/docs](https://nassaq.github.io/docs) covering the full details about the project, from system design to specific components guides.