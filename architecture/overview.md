# Architecture Overview

## Purpose

AI Research OS is an AI-native operating system for professional marketing research agencies.

It is designed to manage the complete lifecycle of research projects by combining business workflows, structured knowledge, reusable processes, and AI-powered execution into a single platform.

AI Research OS is not a collection of AI agents. It is an operating system where AI acts as an execution component within a well-defined business architecture.

The platform follows a Business First philosophy: business entities, business rules, and business decisions always remain the foundation of the system.

---

# Architectural Statement

> AI Research OS is an operating system for marketing research. AI agents are execution components of the platform, not the platform itself.

This principle guides every architectural decision within the project.

---

# High-Level Architecture

    AI Research OS
           │
    ┌──────┼──────┐
    │      │      │
    ▼      ▼      ▼
Business   Execution Definition   Execution Runtime
 Layer             Layer                  Layer
    │              │                      │
    └──────────────┼──────────────────────┘
                   │
                   ▼
           Execution Engine
                   │
                   ▼
          External Services

Each layer has a clearly defined responsibility and communicates through explicit interfaces.

---

# Architecture Layers

## 1. Business Layer

Represents the business domain of the platform.

Typical entities include:

- Project
- Knowledge
- Documents
- Artifacts

This layer owns the persistent business state and business rules.

It is completely independent of AI implementation details.

---

## 2. Execution Definition Layer

Defines what should happen.

Typical entities:

- WorkflowTemplate
- TaskDefinition

These objects describe reusable business processes and remain immutable during execution.

---

## 3. Execution Runtime Layer

Represents what is happening now.

Typical entities:

- WorkflowRun
- AITask

Runtime objects are instantiated from execution definitions and exist only while a workflow is being executed.

---

## 4. Execution Engine

Responsible for workflow orchestration and task execution.

Core components include:

- Supervisor
- Planner
- TaskExecutor
- Agent
- PromptBuilder

The Execution Engine coordinates execution but never owns business state.

---

# Core Design Principles

The architecture is built around the following principles:

- Business before AI.
- Project is the central business aggregate.
- Process definitions are separated from runtime execution.
- AI executes work but never owns business logic.
- Every major architectural decision is documented through ADRs.
- Simplicity is preferred over premature abstraction.
- The architecture evolves incrementally through well-defined iterations.

---

# Execution Flow

A typical execution lifecycle is illustrated below.

    Project
        │
        ▼
WorkflowTemplate
        │
 Instantiate
        ▼
 WorkflowRun
        │
    Creates
        ▼
    AITasks
        │
 Executed by
        ▼
 TaskExecutor
        │
      Uses
        ▼
    AI Agent
        │
    Produces
        ▼
Artifacts / Knowledge / Documents

Business information is always stored in business entities owned by the Project.

---

# Related Documentation

Further architectural details are available in the following documents:

- domain-model.md — Core business entities and relationships.
- layers.md — Responsibilities and boundaries of architectural layers.
- docs/adr/ — Architecture Decision Records.
- docs/roadmap/ — Development roadmap and sprint planning.

---

# Evolution

AI Research OS follows an Architecture First development process.

Every significant architectural change follows the same lifecycle:

    Idea
      │
      ▼
Architecture Discussion
      │
      ▼
Architecture Decision Record (ADR)
      │
      ▼
Implementation
      │
      ▼
Review
      │
      ▼
Release
This approach ensures that the architecture remains consistent, maintainable, and aligned with the long-term vision of the platform.