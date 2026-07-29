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
- Assign every task a non-empty suggested_agent.
- Use dependencies to express task ordering.

---

# OUTPUT FORMAT

Return only valid JSON.

Do not include markdown fences or explanations.

Each task must contain:

- id
- title
- description
- suggested_agent
- dependencies

Return only the JSON object.
