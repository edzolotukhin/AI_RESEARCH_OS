# RESEARCH BRIEF

Title:
{title}

Business Question:
{business_question}

Objectives:
{objectives}

Geography:
{geography}

Market:
{market}

Target Entities:
{target_entities}

Timeframe:
{timeframe}

Constraints:
{constraints}

Deliverables:
{deliverables}

Language:
{language}

Context:
{context}

Known Information:
{known_information}

Exclusions:
{exclusions}

---

# YOUR TASK

Design the semantic research plan for this desk research project.

Define research questions, information needs, source strategy, analysis approach, and deliverable structure.

Do not assign executors or define runtime workflow tasks.

---

# REQUIREMENTS

- Cover every brief objective with at least one research question.
- Link questions to objectives using exact objective text in `objective_refs`.
- Consolidate related objectives instead of creating one question per objective.
- Define concrete information needs for each major question within the configured limits.
- For every information need, define an `evidence_expectation` that states what evidence must establish before the need can be considered answered.
- Align deliverable_plan with brief deliverables where provided.
- Use the brief language unless otherwise specified.
- Return compact JSON only; no prose outside the JSON object.

Return only the ResearchDesign JSON object described in the system prompt.
