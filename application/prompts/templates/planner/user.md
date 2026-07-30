# PROJECT

Client:
{client}

Project:
{project_title}

---

# BUSINESS CONTEXT

Business Problem:
{business_problem}

Research Goal:
{research_goal}

---

# YOUR TASK

Design the optimal research workflow for this project.

The workflow should solve the client's business problem in the most effective and efficient way.

---

# REQUIREMENTS

When designing the workflow:

- Understand the business problem before selecting research methods.
- Propose only necessary work.
- Break complex work into logical tasks.
- Avoid duplicate activities.
- Prefer practical and executable solutions.
- Use professional marketing research terminology.
- Include at least one stage.
- Include at least two tasks.
- Assign every task a registered executor_id from the available executors list.
- Use dependencies to express task ordering.

---

# AVAILABLE EXECUTORS

{executor_catalog}

---

# OUTPUT FORMAT

Return only valid JSON.

Do not include markdown fences or explanations.

Each task must contain:

- id
- title
- description
- executor_id
- dependencies

Return only the JSON object.

Use only executor_id values from the available executors list.
Do not create new executor IDs.
Do not use job titles or display labels instead of executor_id.
