# AI Research OS

> AI-powered Operating System for Marketing Research Agencies

AI Research OS is a modular platform designed to automate and support the complete lifecycle of professional marketing research projects.

Unlike standalone AI agents, AI Research OS is built as a business operating system where AI, workflow automation, knowledge management and human expertise work together.
---

# Vision

Build the most practical AI Operating System for marketing research agencies.

The system is based on real agency workflows and is designed to improve speed, quality, consistency and knowledge reuse while keeping humans in control of business decisions.

---

# Mission

Transform every stage of a marketing research project into an intelligent, reusable and scalable workflow.
---

# Current Status

Current version:

Architecture Review v1.0

## Implemented

- Project-centric architecture
- Client Manager
- Workflow Engine
- Project Domain Model
- Knowledge Manager
- Prompt Repository
- JSON Parser
- OpenAI Integration
- Documentation structure
- Development Roadmap

## In Progress

- Research Designer
- Business Consultant
- Planner
---

# Architecture
                Client
                   │
                   ▼
          Client Manager
                   │
                   ▼
              Project
                   │
    ┌──────────────┼──────────────┐
    │              │              │
Qualification   Project Brief   Research Design
    │              │              │
    └──────────────┼──────────────┘
                   │
        Commercial Proposal
                   │
             Client Approval
                   │
               Fieldwork
                   │
                Analysis
                   │
                 Reporting

The Project is the central business entity of the entire system.

AI agents never work independently.

Each agent enriches the Project with new business knowledge, documents and decisions.
---

# Project Structure
AI_RESEARCH_OS/
│
├── core/
├── constants/
├── domain/
├── roles/
├── services/
├── workflow/
├── knowledge/
├── prompts/
├── docs/
├── memory/
│
├── main.py
├── config.py
├── requirements.txt
│
├── ARCHITECTURE.md
├── PROJECT_VISION.md
├── ROADMAP.md
└── CHANGELOG.md

## Main Directories

| Directory | Purpose |
|-----------|---------|
| domain | Business entities |
| roles | AI agents |
| services | Business services |
| workflow | Workflow orchestration |
| knowledge | Knowledge Base |
| prompts | LLM prompts |
| docs | Project documentation |
| core | Business rules |
| constants | Shared constants |
| memory | Long-term memory |