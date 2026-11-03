# 🛡️ ContexA — Pre-Publication Brand Governance OS

<div align="center">

![ContexA Governance Engine](https://img.shields.io/badge/ContexA-Enterprise%20OS-0f172a?style=for-the-badge&logo=shield)
![Python 3.11+](https://img.shields.io/badge/Backend-FastAPI%20%7C%20Python%203.11+-3776AB?style=for-the-badge&logo=python)
![React 18+](https://img.shields.io/badge/Frontend-React%2018%20%7C%20TypeScript-61DAFB?style=for-the-badge&logo=react)
![Tailwind CSS](https://img.shields.io/badge/Styling-Tailwind%20%7C%2016%20Themes-38B2AC?style=for-the-badge&logo=tailwindcss)
![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL%20%7C%20Supabase-336791?style=for-the-badge&logo=postgresql)
![Docker Ready](https://img.shields.io/badge/Deployment-Docker%20%7C%20Render%20%7C%20Cloudflare-2496ED?style=for-the-badge&logo=docker)

**An Automated Pre-Publication Governance & Compliance Gateway**
*Catch brand breaches, off-tone copy, visual accessibility failures, and ungrounded claims before content hits the public.*

[Quick Start](#-quick-start--hackathon-judge-runbook) • [System Architecture](#-system-architecture) • [Workflows & Diagrams](#-workflows--system-diagrams) • [UI & Theme System](#-uiux-architecture--theme-engine) • [API Reference](#-api-specification) • [Deployment](#-deployment--cloud-infrastructure)

</div>

---

## 📖 Executive Summary & Core Value Proposition

Modern organizations generate content across dozens of distributed teams, agencies, and generative AI tools. However, brand guidelines, regulatory rules, and pricing sheets remain buried in static PDFs, slide decks, and spreadsheets. 

**ContexA** bridges this gap by acting as a **Pre-Publication Safety Gate**. It parses multi-format content assets (PDF, DOCX, PPTX, Images via OCR) and evaluates them against an active, isolated workspace rulebook using a **Hybrid Deterministic & Local AI Multi-Engine**.

```
    [ CONTENT CREATION ]                [ CONTEXA SAFETY GATE ]                [ PUBLIC DISTRIBUTION ]
+---------------------------+        +---------------------------+        +---------------------------+
| • Marketing Copy (Text)   |        |  01. Multi-Format Parsing |        |                           |
| • Campaign Slides (PPTX)  | -----> |  02. Deterministic Engine | -----> |  APPROVED: Publish Live   |
| • Press Releases (DOCX)   |        |  03. Local LLM Context    |        |                           |
| • Brand Assets (PDF/Img)  |        |  04. Critical Gate Policy |        |  BLOCKED: Audit & Fix     |
+---------------------------+        +---------------------------+        +---------------------------+
```

### Key Differentiators
1. **Hybrid Inspection Engine:** Ultra-fast, zero-token deterministic Python checks for exact terminology/banned words paired with local Ollama LLM execution for deep tone/positioning analysis.
2. **Grounding & Quote Verification Guardrails:** Every AI finding is verified verbatim against the uploaded document and active brand guideline quote. Unmatched claims are explicitly flagged as `Unverifiable`.
3. **Dynamic 16-Palette Visual Engine:** Built-in design token switcher supporting Corporate Slate, Glassmorphism, Dark High-Contrast, and full **Neubrutalism** UI with an interactive 3D WebGL Canvas scene.
4. **Hard Publication Gate:** Open `CRITICAL` or `HIGH` severity findings automatically block approval until resolved or explicitly overridden with an audit log reason.

---

## 🛠️ Workflows & System Diagrams

### 1. End-to-End Content Processing Pipeline

```
+---------------------------------------------------------------------------------------------------+
|                                     CONTENT INGESTION & PARSING                                   |
|                                                                                                   |
|  +--------------+     +-------------------+     +--------------------+     +-------------------+  |
|  |  PDF Upload  |     |   DOCX Document   |     |   PPTX Deck File   |     |   Raw Image/OCR   |  |
|  +------+-------+     +---------+---------+     +---------+----------+     +---------+---------+  |
|         |                       |                         |                      |                |
|         v                       v                         v                      v                |
|  [ PyMuPDF Stream ]   [ python-docx XML ]       [ python-pptx Frames ]   [ Tesseract Engine ] |
+---------+-----------------------+-------------------------+----------------------+----------------+
          |                       |                         |                      |
          +-----------------------+------------+------------+----------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                                     HYBRID INSPECTION ENGINE                                      |
|                                                                                                   |
|                      +-------------------------------------------------+                          |
|                      |             Extracted Plain Text &              |                          |
|                      |               Visual Spatial Map                |                          |
|                      +-----------------------+-------------------------+                          |
|                                              |                                                    |
|                      +-----------------------+-------------------------+                          |
|                      |                                                 |                          |
|                      v                                                 v                          |
|       +-----------------------------+           +-----------------------------+                   |
|       |    DETERMINISTIC ENGINE     |           |     LOCAL OLLAMA ENGINE     |                   |
|       |  (Zero Token / Memory Fast) |           |  (Contextual Brand Rules)   |                   |
|       +--------------+--------------+           +--------------+--------------+                   |
|                      |                                         |                                  |
|                      | • Forbidden Term Regex                  | • Off-Tone Language              |
|                      | • Price Register Match                  | • Brand Positioning Match        |
|                      | • Image Alt-Text Presence               | • Subtle Claim Verification      |
|                      | • WCAG Luminance Contrast               |                                  |
|                      |                                         |                                  |
|                      +-----------------------+-----------------+                                  |
|                                              |                                                    |
+----------------------------------------------+----------------------------------------------------+
                                               |
                                               v
+---------------------------------------------------------------------------------------------------+
|                                 VALIDATION & GOVERNANCE GATEWAY                                   |
|                                                                                                   |
|                     +---------------------------------------------------+                         |
|                     |             VERBATIM QUOTE VALIDATION             |                         |
|                     | Does finding match exact document & source text?  |                         |
|                     +------------------------+--------------------------+                         |
|                                              |                                                    |
|                            +-----------------+-----------------+                                  |
|                            | YES                               | NO                               |
|                            v                                   v                                  |
|               +-------------------------+         +-------------------------+                     |
|               |  VERIFIED CITATION FIND |         |    UNVERIFIABLE CLAIM   |                     |
|               |  (Assigned Severity)    |         | (Requires Human Review) |                     |
|               +------------+------------+         +------------+------------+                     |
|                            |                                   |                                  |
|                            +-----------------+-----------------+                                  |
|                                              |                                                    |
|                                              v                                                    |
|                     +---------------------------------------------------+                         |
|                     |            PUBLICATION GATE ASSESSMENT            |                         |
|                     |    Any unresolved CRITICAL / HIGH Findings?       |                         |
|                     +------------------------+--------------------------+                         |
|                                              |                                                    |
|                            +-----------------+-----------------+                                  |
|                            | YES                               | NO                               |
|                            v                                   v                                  |
|               +-------------------------+         +-------------------------+                     |
|               |    PUBLICATION BLOCKED  |         |   APPROVED FOR RELEASE  |                     |
|               | (Requires Override Note)|         | (Audit Log Generated)   |                     |
|               +-------------------------+         +-------------------------+                     |
+---------------------------------------------------------------------------------------------------+
```

---

### 2. Guideline Candidate Ingestion Lifecycle

To prevent unverified guidelines from automatically destabilizing active governance policies, imported brand documents are parsed into distinct clause candidates. An admin must review and activate each candidate clause before it is added to active workspace evaluation.

```
 [ Brand Guideline PDF / Doc ]
              |
              v
 [ Rule Parsing & Extraction ]
              |
              v
+-----------------------------------+
|     CANDIDATE CLAUSE STAGING      |
|  • Status: PAUSED / CANDIDATE     |  <--- Isolated from active evaluation
|  • Workspace ID Attached          |
+-------------+---------------------+
              |
              v
     [ Admin Review Queue ]
              |
     +--------+--------+
     |                 |
     v                 v
[ REJECT ]        [ APPROVE ]
     |                 |
     v                 v
 (Archived)     +-----------------------------------+
                |      ACTIVE WORKSPACE RULEBOOK    |
                |  • Status: ACTIVE                 |
                |  • Enforces Real-Time Pipeline    |
                +-----------------------------------+
```

---

## 🚀 Quick Start — Hackathon Judge Runbook

You can run ContexA in **Submission Mode**, which requires zero cloud API keys, zero paid external services, and runs 100% locally with deterministic safety checks.

### Prerequisites
* **Node.js**: v18.0.0 or higher
* **Python**: v3.11 or higher
* **Pip & Virtualenv**

### 1-Click Local Execution (Windows)
```cmd
run-dev.bat
```

### 1-Click Local Execution (macOS / Linux)
```bash
chmod +x run-dev.sh
./run-dev.sh
```

---

### Manual Step-by-Step Setup

#### Step 1: Clone & Configure Environment
```bash
git clone https://github.com/your-org/ContexA.git
cd ContexA

# Copy example environment files
cp .env.example .env
cp frontend/.env.example frontend/.env
```

#### Step 2: Backend Setup
```bash
# Navigate to backend directory
cd backend

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI development server
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### Step 3: Frontend Setup (New Terminal)
```bash
# Navigate to frontend directory
cd frontend

# Install Node dependencies
npm install

# Start Vite development server
npm run dev
```

* Access Application UI: `http://localhost:5173`
* Access API OpenAPI Docs: `http://localhost:8000/docs`

---

## 🎨 UI/UX Architecture & Theme Engine

ContexA features a fully dynamic visual architecture allowing instant switching across **16 color palettes** with granular CSS Design Tokens.

### Palette Highlights

```
+------------------------------------------------------------------------------------+
| 🎨 PALETTE STYLE    | ACCENT COLOR  | BACKGROUND    | PRIMARY SURFACES / BORDERS   |
+---------------------+---------------+---------------+------------------------------+
| Neubrutalism       | #FFE600 (Yel) | #FAF8F5 (Raw) | #000000 (Stark 3px Borders)  |
| Corporate Slate     | #0F172A (Navy)| #F8FAFC (Slte)| #E2E8F0 (Subtle Borders)     |
| Glassmorphism Dark  | #38BDF8 (Sky) | #0F172A (Dark)| rgba(255,255,255,0.05) Blur  |
| High Contrast Light | #000000 (Blk) | #FFFFFF (Wht)| #000000 (Pure Black Line)    |
+------------------------------------------------------------------------------------+
```

### Key UI Features
* **Interactive 3D WebGL Canvas (`GovernanceScene3D.tsx`):** Displays real-time rendering of active workspace compliance nodes.
* **Palette Motion Lab (`palette-motion-lab.html`):** Test dynamic visual state changes and reduced-motion accessibility overrides.
* **WCAG Contrast Verifier:** Automatic theme luminance calculation ensuring readability across viewports.

---

## 📦 Project Structure

```
ContexA/
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI Application Entrypoint
│   │   ├── capabilities.py           # Engine & Rule Check Core Logic
│   │   ├── models.py                 # SQLAlchemy Database Schemas
│   │   ├── database.py               # SQLite / Postgres Connection Managers
│   │   ├── parsing.py                # PyMuPDF, DOCX, PPTX, OCR Parsers
│   │   ├── upload_security.py        # ClamAV & Extension Validation
│   │   └── collaboration.py         # Audit Trails & Real-Time Stream
│   ├── tests/                        # Comprehensive PyTest Suite
│   └── requirements.txt              # Backend Dependencies
├── frontend/
│   ├── src/
│   │   ├── App.tsx                   # Root UI Routing & Workspace Controller
│   │   ├── TrustOSPage.tsx           # Main Compliance Dashboard
│   │   ├── GovernanceScene3D.tsx     # 3D Canvas Visualizer
│   │   ├── Collaboration.tsx         # Audit Trail & Review Feed
│   │   ├── styles.css                # Base Design Tokens
│   │   ├── neubrutalism.css          # Neubrutalism Theme Overrides
│   │   └── professional.css        # Corporate Slate Theme
│   ├── palette-motion-lab.html       # Theme Previewer & Motion Testing
│   └── package.json                  # Node Dependencies
├── ops/                              # Verification & DB Migration Scripts
│   ├── schema_postgres.sql           # Production PostgreSQL Schema
│   ├── verify_postgres_rls.py        # Row-Level Security Verification
│   └── check_object_storage.py       # S3 / Storage Health Verification
├── docker-compose.yml                # Single-Service Docker Stack
├── HACKATHON_JUDGE_RUNBOOK.md        # Judge Testing Guide
└── README.md                         # Product Documentation
```

---

## ⚡ API Specification

ContexA exposes a REST API generated by FastAPI.

### Core Endpoints Summary

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/review` | Submits text or file for rule inspection | Yes |
| `GET` | `/api/v1/rules` | Lists all active rules for workspace | Yes |
| `POST` | `/api/v1/rules/import` | Uploads guideline doc to candidate rules | Yes |
| `POST` | `/api/v1/rules/{id}/approve`| Promotes candidate rule to active status | Yes (Admin) |
| `GET` | `/api/v1/audit/export` | Downloads CSV audit log of workspace decisions| Yes |
| `GET` | `/health` | System diagnostics & engine status check | No |

#### Example Request: Content Review (`POST /api/v1/review`)
```json
{
  "workspace_id": "ws_enterprise_01",
  "content_type": "text",
  "raw_text": "Buy our flagship product today for $49. Guaranteed 100% returns with zero risk!",
  "mode": "hybrid"
}
```

#### Example Response
```json
{
  "status": "BLOCKED",
  "publication_gate": {
    "can_publish": false,
    "critical_count": 1,
    "high_count": 1
  },
  "findings": [
    {
      "id": "f_9823",
      "rule_id": "rule_banned_claim_04",
      "severity": "CRITICAL",
      "category": "Legal Compliance",
      "quote": "Guaranteed 100% returns with zero risk!",
      "explanation": "Unsubstantiated financial guarantees violate Enterprise Policy Rule LEGAL-04.",
      "suggested_fix": "Remove risk-free guarantees or cite approved disclaimer #802.",
      "citation_status": "VERIFIED"
    }
  ]
}
```

---

## 🔒 Reliability, Security & Fallback Capabilities

1. **Offline Fallback (Submission Mode):** If local Ollama or cloud models become unreachable, ContexA automatically degrades to **Submission Mode**, executing 100% of deterministic rules without failing requests.
2. **Multi-Tenant Row-Level Security (RLS):** Built on PostgreSQL RLS schemas to ensure strict workspace isolation.
3. **Quote Verification Guardrails:** All AI findings undergo string-matching validation against source text to eliminate hallucinated findings.

---

## 🗺️ Roadmap & Engineering Priorities

```
[ PHASE 1: CURRENT prototype ]       [ PHASE 2: ROUND 3 ENHANCEMENTS ]      [ PHASE 3: ENTERPRISE READY ]
• Multi-format parsing (PDF/DOCX/PPTX) • Production SSO / OIDC Auth          • Cross-workspace analytics
• Hybrid Deterministic Engine        • Versioned Approved Fact Register     • Custom LLM fine-tuning adapter
• 16 Visual Themes + Neubrutalism     • 50-Asset Benchmarking Suite         • Adobe Creative Cloud Plugin
• Publication Gate & CSV Audit       • Hybrid Keyword/Vector Search        • Automated CMS Webhooks
```

---

## 📄 License & Acknowledgments

Built for high-performance enterprise brand governance. Designed for security, speed, and accuracy.
```

An enterprise-grade `README.md` file has been generated with system diagrams, workflows, setup runbooks, API specifications, and visual theme details.
