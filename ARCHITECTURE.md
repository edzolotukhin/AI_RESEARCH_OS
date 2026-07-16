# AI Research OS

# Architecture

Version: 1.0

---

# Architecture Overview

AI Research OS is designed as a business operating system for professional marketing research agencies.

The system is organized around a single business entity:

Project

Everything else exists to create, enrich, validate or complete a Project.

---

# High-Level Architecture

Client
↓
Client Request
↓
Project
↓
Workflow Engine
↓
AI Roles
↓
Project
↓
Artifacts
↓
Client

---

# Core Components

## Project

Project is the central business entity.

It contains the complete state of the research project throughout its lifecycle.

Examples:

- Client Request
- Qualification
- Project Brief
- Research Design
- Commercial Proposal
- Questionnaire
- Fieldwork
- Analysis
- Report

Project is the Single Source of Truth.

---

## Workflow Engine

Workflow Engine orchestrates the project.

Responsibilities:

- execute AI roles
- control execution order
- validate readiness
- stop workflow when human input is required
- move Project through its lifecycle

Workflow Engine contains no AI.

---

## AI Roles

Each AI role performs one professional responsibility.

Examples:

- Client Manager
- Research Designer
- Proposal Generator
- Analyst

Every role follows the same contract.
execute(project: Project) -> Project

Roles never communicate directly with each other.

Workflow Engine coordinates all interactions.

---

## Domain

Domain contains business entities.

Examples:

- Project
- ClientRequest
- ClientQualification
- ProjectBrief
- ResearchDesign

Domain never depends on:

- OpenAI
- Prompts
- Knowledge
- Infrastructure

---

## Core

Core contains business rules.

Examples:

- Readiness Rules
- Validation Rules
- State Transitions
- Business Policies

Core contains no AI logic.

---

## Knowledge

Knowledge stores corporate expertise.

Examples:

- Best Practices
- Research Methodology
- Internal Standards
- Playbooks
- Templates
- Project Examples

Knowledge does not contain business rules.

---

## Prompts

Prompts define AI behaviour.

Prompts do not contain corporate knowledge.

Knowledge and Prompts are intentionally separated.

---

## Services

Services provide infrastructure.

Examples:

- OpenAI
- Prompt Repository
- Knowledge Manager
- JSON Parser

Services contain no business logic.

---

# Dependency Rules

Dependencies always point downward.

main.py
↓

Workflow Engine
↓

Roles
↓

Services
↓

Infrastructure

Domain is independent from every other layer.

---

# Project Lifecycle

Lead

↓

Qualification

↓

Project Brief

↓

Research Design

↓

Commercial Proposal

↓

Client Approval

↓

Questionnaire

↓

Fieldwork

↓

Analysis

↓

Presentation

↓

Closed

---

# Design Principles

1. Project is the central business entity.
2. Project is the Single Source of Truth.
3. Workflow orchestrates execution.
4. Roles modify Project.
5. Domain owns business entities.
6. Core owns business rules.
7. Knowledge owns expertise.
8. Prompts define behaviour.
9. Services provide infrastructure.
10. AI is an implementation detail.

---

# Architecture Goals

The architecture should remain:

- simple
- modular
- scalable
- testable
- maintainable

New functionality should be added by extending existing components rather than introducing unnecessary new abstractions.

---

# Evolution Strategy

Architecture changes are exceptional.

Whenever possible:

- extend Domain
- enrich Knowledge
- improve Prompts
- enhance Workflow

before introducing new components.