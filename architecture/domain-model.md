# Domain Model

## Purpose

The Domain Model defines the core business entities of AI Research OS and the relationships between them.

It represents the business view of the platform, independent of implementation details or specific technologies.

The domain model serves as the foundation for the entire architecture and guides the implementation of business logic.

---

# Core Principles

The domain model is built on the following principles:

- Business entities represent real business concepts.
- Project is the central business aggregate.
- Business entities are independent of AI implementation.
- Runtime execution is separated from business state.
- AI agents interact with the domain through controlled interfaces.

---

# Core Business Entities

## Project

The Project is the primary business aggregate of AI Research OS.

A Project represents a long-lived business context and owns all information related to a research initiative.

A Project may contain:

- Workflow Runs
- Knowledge
- Documents
- Artifacts
- Business Decisions
- Execution History

A Project exists independently of workflow execution.

---

## WorkflowTemplate

A WorkflowTemplate defines a reusable business process.

It contains the sequence of TaskDefinitions required to accomplish a business objective.

Workflow templates are immutable.

---

## WorkflowRun

A WorkflowRun is a runtime instance of a WorkflowTemplate.

It represents one execution of a workflow within a specific Project.

A WorkflowRun owns:

- AITasks
- Execution State
- Execution History
- Runtime Metadata

---

## TaskDefinition

A TaskDefinition describes a reusable unit of work.

It specifies:

- objective
- expected inputs
- expected outputs
- execution requirements

TaskDefinitions are immutable and reusable.

---

## AITask

An AITask is the runtime representation of a TaskDefinition.

It exists only during workflow execution.

An AITask stores:

- current status
- runtime context
- produced artifacts
- execution logs

Business logic is never stored inside an AITask.

---

## Knowledge

Knowledge represents reusable business information accumulated across projects.

Examples include:

- methodologies
- research standards
- best practices
- client-specific knowledge
- reusable insights

Knowledge is persistent and independent of workflow execution.

---

## Document

A Document represents any business document managed by the platform.

Examples include:

- Project Brief
- Commercial Proposal
- Questionnaire
- Final Report
- Presentation

Documents belong to a Project.

---

## Artifact

An Artifact is any output produced during workflow execution.

Examples include:

- generated text
- structured JSON
- tables
- summaries
- recommendations
- intermediate analysis

Artifacts may later become Documents or Knowledge.

---

# Entity Relationships

Project
│
├── owns Knowledge
├── owns Documents
├── owns Artifacts
└── owns WorkflowRuns
        │
        ├── created from WorkflowTemplate
        │
        └── contains AITasks
                    │
                    └── instantiated from TaskDefinition

---

# Definition vs Runtime

AI Research OS separates executable definitions from runtime instances.

Definition

- WorkflowTemplate
- TaskDefinition

↓

Runtime

- WorkflowRun
- AITask

This separation enables reusable workflows while preserving execution history.

---

# Design Rules

The following rules apply to the domain model:

- Business entities never depend on AI agents.
- Runtime objects never own business state.
- AI components operate only through runtime objects.
- Business data belongs to the Project.
- Every entity has a single responsibility.

---

# Future Extensions

The domain model is intentionally designed for incremental evolution.

Future entities may include:

- Client
- Research
- Dataset
- Methodology
- Survey
- Respondent Group
- Fieldwork
- Report Version

New entities should follow the same architectural principles defined in ADR-000.

---

# Related Documents

- Architecture Overview
- Architecture Layers
- ADR-000 — Architecture Principles