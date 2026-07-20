# Architecture Layers

## Purpose

This document defines the architectural layers of AI Research OS, their responsibilities, and the rules governing interactions between them.

The goal is to ensure a clear separation of concerns, maintainability, and scalability as the platform evolves.

---

# Layered Architecture

AI Research OS is organized into four architectural layers.
                    AI Research OS
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
 Business Layer   Execution Definition   Execution Runtime
                        Layer                 Layer
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
                           ▼
                   Execution Engine
                           │
                           ▼
                    External Services

Each layer has a single responsibility and communicates only through well-defined interfaces.

---

# 1. Business Layer

## Purpose

Represents the business domain of the platform.

This layer contains persistent business entities, business rules, and business state.

## Typical Entities

- Project
- Knowledge
- Document
- Artifact

## Responsibilities

- Store business data
- Represent business concepts
- Maintain business rules
- Preserve long-term state

## Must Not

- Execute AI tasks
- Call LLMs
- Generate prompts
- Manage workflow execution

---

# 2. Execution Definition Layer

## Purpose

Defines reusable business processes.

This layer describes what should happen, but never performs execution.

## Typical Entities

- WorkflowTemplate
- TaskDefinition

## Responsibilities

- Describe workflows
- Define task sequences
- Specify execution requirements
- Provide reusable process definitions

## Must Not

- Store runtime state
- Execute workflows
- Store business data

---

# 3. Execution Runtime Layer

## Purpose

Represents active workflow execution.

This layer contains runtime objects created from execution definitions.

## Typical Entities

- WorkflowRun
- AITask

## Responsibilities

- Track execution state
- Store runtime context
- Manage task lifecycle
- Record execution history

## Must Not

- Own business entities
- Replace business state
- Contain business rules

---

# 4. Execution Engine

## Purpose

Coordinates execution of workflows and AI agents.

The engine orchestrates execution but never owns business data.

## Core Components

- Supervisor
- Planner
- TaskExecutor
- Agent
- PromptBuilder

## Responsibilities

- Create execution plans
- Execute tasks
- Coordinate AI agents
- Invoke external services
- Produce execution artifacts

## Must Not

- Store persistent business data
- Replace business entities
- Own business decisions

---

# Layer Interaction Rules

## Allowed

Business Layer

↓

Execution Definition Layer

↓

Execution Runtime Layer

↓

Execution Engine

The Execution Engine may update the Business Layer only through controlled business interfaces.

---

# Forbidden Dependencies

The following dependencies are prohibited:

- Business Layer → Execution Engine
- Business Layer → AI Agent
- Project → LLM
- Project → PromptBuilder
- WorkflowTemplate → WorkflowRun
- TaskDefinition → AITask
- AI Agent → Project

---

# Dependency Direction
Business Layer
       ▲
       │
Execution Runtime Layer
       ▲
       │
Execution Definition Layer

Execution Engine
       │
       ▼
External Services

Business entities never depend on execution components.

Execution components depend on business abstractions but never own them.

---

# Layer Responsibilities Summary

| Layer | Responsibility |
|--------|----------------|
| Business Layer | Business state and business rules |
| Execution Definition Layer | Reusable process definitions |
| Execution Runtime Layer | Runtime execution state |
| Execution Engine | Workflow orchestration and AI execution |

---

# Design Principles

The layered architecture follows these principles:
- Single Responsibility
- Separation of Concerns
- Explicit Dependencies
- Business Before AI
- Definition vs Runtime Separation
- Incremental Evolution

---

# Related Documents

- Architecture Overview
- Domain Model
- ADR-000 — Architecture Principles