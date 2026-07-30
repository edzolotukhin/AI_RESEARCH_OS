# Examples

Run the deterministic offline demo from the repository root:

```bash
pip install -r requirements.txt
python examples/deterministic_research_demo.py
```

`deterministic_research_demo.py` exercises the current runtime path
(`WorkflowTemplate` → `WorkflowRun` → `WorkflowEngine`) with demo-only executors.
It does not call a live LLM and does not require `OPENAI_API_KEY`.

A full `Agency` / `PlannerAgent` example with live OpenAI will be added in a later sprint.
