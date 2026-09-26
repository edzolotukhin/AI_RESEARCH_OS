"""Explicit one-action PRF-08L UI driver; no automatic retry or live rerun."""
import argparse
import json
import sys

if __package__:
    from .acceptance_http import post_form
else:
    from acceptance_http import post_form


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "generate", "approve", "activate"))
    parser.add_argument("--project")
    parser.add_argument("--design")
    parser.add_argument("--diagnostics", default="artifacts/acceptance/prf08l_http_errors.log")
    args = parser.parse_args()
    base = "http://127.0.0.1:18086/ui/projects"

    def post(url, values):
        status, final_url = post_form(url, values, stage=args.action, diagnostic_path=args.diagnostics)
        print(json.dumps({"status": status, "url": final_url}))
        return final_url

    if args.action == "prepare":
        brief = json.load(sys.stdin)
        url = post(base, {"name": "PRF-08L — Controlled Live Targeted Continuation", "selected_methods": "desk"})
        project = url.rstrip("/").split("/")[-1]
        fields = {key: brief.get(key, "") for key in ("title", "business_question", "objectives", "geography", "timeframe", "market", "language")}
        for key in ("objectives", "geography"):
            if isinstance(fields[key], list):
                fields[key] = "\n".join(fields[key])
        post(f"{base}/{project}/brief", fields)
        print(json.dumps({"project_id": project}))
    else:
        if not args.project:
            raise SystemExit("Explicit project ID required")
        path = {"generate": "design/generate", "approve": "design/approve", "activate": "methods/DESK/activate"}[args.action]
        if args.action == "approve" and not args.design:
            raise SystemExit("Explicit design ID required")
        post(f"{base}/{args.project}/{path}", {"design_id": args.design} if args.design else {})


if __name__ == "__main__":
    main()
