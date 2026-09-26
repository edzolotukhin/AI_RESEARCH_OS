"""Explicit one-action PRF-08J UI driver; no automatic retry or live rerun."""
import argparse
import json
import sys
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "generate", "approve", "activate"))
    parser.add_argument("--project")
    parser.add_argument("--design")
    args = parser.parse_args()
    base = "http://127.0.0.1:18085/ui/projects"

    def post(url, values):
        request = urllib.request.Request(url, data=urllib.parse.urlencode(values).encode())
        with urllib.request.urlopen(request, timeout=240) as response:
            print(json.dumps({"status": response.status, "url": response.url}))
            return response.url

    if args.action == "prepare":
        brief = json.load(sys.stdin)
        url = post(base, {"name": "PRF-08J — Controlled Live Evidence-Aware Continuation", "selected_methods": "desk"})
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
