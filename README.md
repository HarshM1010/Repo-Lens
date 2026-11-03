# 🔍 Repolens

**Repolens** is a static code analysis and repository intelligence platform that analyzes remote Git repositories and transforms raw codebases into actionable insights about **code complexity, security vulnerabilities, dependencies, architecture, and module relationships**.

It combines asynchronous background processing, distributed task execution, real-time WebSocket updates, and AI-generated architectural documentation into a unified developer dashboard.

---

## ✨ Features

### 📊 Code Complexity Analysis

Analyzes Python code using **Radon** to evaluate code complexity and provide measurable insights into code quality.

### 🛡️ Security Analysis

Runs **Bandit** to identify potential security vulnerabilities and risky coding patterns.

### 📦 Dependency Analysis

Parses dependency manifests across multiple programming languages to identify project dependencies and package information.

### 🕸️ Import & Module Graph

Builds a directed dependency graph by analyzing import relationships within the repository.

The graph is generated using **NetworkX** and serialized into **Vis.js-compatible JSON** for interactive visualization.

### ⚡ Concurrent Repository Analysis

Analysis tasks are distributed across Celery workers and parallelized using **Celery Chords** with Redis as the message broker/backend.

This allows independent analysis operations to execute concurrently rather than processing the repository sequentially.

### 🔄 Real-Time Analysis Dashboard

Uses **Django Channels, ASGI, and WebSockets** to provide persistent full-duplex communication between workers and the frontend.

Users can see:

* Analysis progress from **0% → 100%**
* Background task status
* Updated repository metrics
* Analysis completion events

without manually refreshing the dashboard.

### 🧠 AI-Generated Documentation

The **Gemini API** analyzes generated repository metrics and produces structured architectural documentation describing the analyzed codebase.

### 🚀 Smart Analysis Caching

Repositories are shallow-cloned using **GitPython** and analyzed using the repository's **SHA-1 commit hash**.

If the same commit has already been analyzed, Repolens can skip redundant analysis work and reuse the existing results.

### 🗄️ Object Storage

Parsed repositories are compressed and archived using **Boto3** and stored in a self-hosted **MinIO** S3-compatible object storage bucket.

---

## 🏗️ Architecture

```text
                         ┌──────────────────┐
                         │   User / Browser │
                         └────────┬─────────┘
                                  │
                           HTTP / WebSocket
                                  │
                         ┌────────▼─────────┐
                         │      Nginx       │
                         └────────┬─────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │          Django           │
                    │      REST / WebSocket     │
                    └──────┬──────────┬─────────┘
                           │          │
                      WebSocket      Tasks
                           │          │
                           │    ┌─────▼─────┐
                           │    │   Redis   │
                           │    └─────┬─────┘
                           │          │
                           │    ┌─────▼────────────┐
                           │    │ Celery Workers   │
                           │    └─────┬────────────┘
                           │          │
                ┌──────────┼──────────┼─────────────┐
                │          │          │             │
           ┌────▼────┐ ┌───▼────┐ ┌──▼────────┐ ┌──▼──────────┐
           │  Radon  │ │ Bandit │ │ Dependency│ │ Import Graph│
           │ Analysis│ │        │ │  Parsing   │ │  NetworkX   │
           └─────────┘ └────────┘ └───────────┘ └─────────────┘
                                  │
                         ┌────────▼────────┐
                         │   PostgreSQL    │
                         └─────────────────┘
                                  │
                         ┌────────▼────────┐
                         │     MinIO       │
                         │  Object Storage │
                         └─────────────────┘

                         ┌─────────────────┐
                         │   Gemini API    │
                         │ AI Documentation│
                         └─────────────────┘
```

---

## 🔄 Analysis Workflow

```text
Remote Git Repository
          │
          ▼
     Shallow Clone
       (GitPython)
          │
          ▼
    Get Commit SHA-1
          │
          ▼
    ┌───────────────┐
    │ Cache Exists? │
    └───────┬───────┘
        Yes │   │ No
            │   │
            │   ▼
            │  Create Analysis Tasks
            │       │
            │       ▼
            │  Celery + Redis
            │       │
            │       ├──► Complexity → Radon
            │       ├──► Security → Bandit
            │       ├──► Dependencies
            │       └──► Import Graph → NetworkX
            │
            ▼
      Store Results
            │
            ▼
     Gemini API
            │
            ▼
 Architectural Documentation
            │
            ▼
       Live Dashboard
```

---

## 🧰 Tech Stack

| Category                   | Technology                   |
| -------------------------- | ---------------------------- |
| Backend                    | Django                       |
| Database                   | PostgreSQL                   |
| Task Queue                 | Celery                       |
| Message Broker             | Redis                        |
| Real-Time Communication    | Django Channels / WebSockets |
| Code Complexity            | Radon                        |
| Security Analysis          | Bandit                       |
| Graph Analysis             | NetworkX                     |
| Git Operations             | GitPython                    |
| AI                         | Gemini API                   |
| Object Storage             | MinIO                        |
| Object Storage SDK         | Boto3                        |
| Web Server / Reverse Proxy | Nginx                        |
| Containerization           | Docker                       |
| Async Server               | ASGI                         |

---

## 📁 Core Analysis Components

### Complexity Analyzer

Uses **Radon** to inspect source code and calculate complexity-related metrics.

### Security Analyzer

Uses **Bandit** to statically inspect Python code for common security issues.

### Dependency Parser

Identifies dependency manifests and extracts package/dependency information across supported languages.

### Import Analyzer

Uses syntax-pattern matching to identify module relationships and constructs a directed graph:

```text
module_a
   │
   ├──────► module_b
   │          │
   │          └──────► module_d
   │
   └──────► module_c
```

The resulting graph is converted into JSON suitable for interactive visualization.

---

## ⚙️ Concurrency Model

Repolens uses **Celery** to distribute repository analysis across workers.

Independent analysis operations are executed concurrently:

```text
                 Repository
                     │
              Analysis Pipeline
                     │
              Celery Chord
          ┌──────────┼──────────┐
          ▼          ▼          ▼
      Complexity   Security   Dependency
        Worker      Worker      Worker
          │          │          │
          └──────────┼──────────┘
                     ▼
              Aggregate Results
                     │
                     ▼
              Generate Report
```

This architecture prevents expensive analysis operations from blocking one another and allows the platform to scale analysis workers independently.

---

## 🔌 Real-Time Updates

Django Channels provides WebSocket-based communication between the analysis backend and dashboard.

Example event flow:

```text
Celery Worker
     │
     │ Analysis Started
     ▼
Redis / Channel Layer
     │
     ▼
Django Channels
     │
     ▼
WebSocket
     │
     ▼
Browser Dashboard
```

Progress updates can be streamed continuously while the repository is being analyzed.

---

## 🧠 AI Documentation

After analysis completes, Repolens sends structured repository metrics to the **Gemini API**.

The generated output can be used to document aspects of the codebase such as:

* Architectural structure
* Module relationships
* Code quality observations
* Dependency information
* Security findings
* Complexity characteristics

This turns static analysis results into human-readable architectural documentation.

---

## 🗃️ Data & Storage

### PostgreSQL

Stores structured application data and analysis metadata.

### Redis

Used for asynchronous task coordination and Celery infrastructure.

### MinIO

Provides S3-compatible object storage for compressed repository archives and parsed repository data.

### Commit-Based Caching

Analysis results are associated with the repository's **SHA-1 commit hash**.

```text
Repository
    │
    ▼
Commit SHA-1
    │
    ▼
Check Cache
 ┌──┴──┐
 │     │
Hit   Miss
 │     │
 ▼     ▼
Reuse  Analyze
       │
       ▼
     Cache
```

This prevents repeated analysis when the repository has not changed.

---

## 🐳 Deployment

The application is designed to run as a containerized backend infrastructure using Docker.

A typical deployment consists of:

```text
Nginx
  │
  ├── Django / ASGI
  │
  ├── Celery Workers
  │
  ├── Redis
  │
  ├── PostgreSQL
  │
  └── MinIO
```

---

## 🚀 Getting Started

### Prerequisites

Make sure the following are installed:

* Python 3.x
* Docker
* Docker Compose
* PostgreSQL
* Redis

You will also need credentials/configuration for the Gemini API if AI-generated documentation is enabled.

### Clone the Repository

```bash
git clone <repository-url>
cd repolens
```

### Configure Environment Variables

Create a `.env` file containing the required application configuration:

```env
DJANGO_SECRET_KEY=
DEBUG=

DATABASE_URL=

REDIS_URL=

GEMINI_API_KEY=

MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
MINIO_BUCKET=
```

### Start the Services

```bash
docker compose up --build
```

### Run Celery Workers

```bash
celery -A <project_name> worker --loglevel=info
```

### Access the Application

Open the configured application URL in your browser.


---

## 📌 Project Highlights

Repolens demonstrates several backend and distributed-systems concepts:

* **Asynchronous task processing**
* **Concurrent workload execution**
* **Distributed workers**
* **Commit-based caching**
* **Real-time WebSocket communication**
* **Static code analysis**
* **Dependency graph construction**
* **AI-assisted documentation**
* **S3-compatible object storage**
* **Containerized deployment**

---

## 👨‍💻 Author

**Harsh Mane**

B.Tech — Electronics and Telecommunication Engineering
IIIT Bhubaneswar
---

