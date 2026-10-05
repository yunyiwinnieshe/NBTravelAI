"""Generate local Postman v3 and importable v2.1 files from conversation cases."""

import argparse
import json
from pathlib import Path


def generate(root: Path) -> None:
    checks = (root / "evals/conversations/assertions.js").read_text()
    dataset = json.loads((root / "evals/conversations/cases.v1.json").read_text())
    collection = root / "postman/collections/Planning conversations"
    definition = collection / ".resources/definition.yaml"
    definition.parent.mkdir(parents=True, exist_ok=True)
    variables = [
        {"key": "base_url", "value": "http://127.0.0.1:8012"},
        {"key": "session_id", "value": ""},
        {"key": "previous_draft", "value": ""},
    ]
    definition.write_text(
        json.dumps(
            {
                "$kind": "collection",
                "name": "Planning conversations",
                "description": (
                    "12 synthetic cases. Run with a DeepSeek-configured local server. "
                    "Model calls incur usage. Each folder creates a fresh session. "
                    "No credentials are needed in Postman."
                ),
                "variables": variables,
            },
            indent=2,
        )
        + "\n"
    )
    export = {
        "info": {
            "name": "Planning conversations",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
            "description": (
                "Generated from evals/conversations/cases.v1.json. "
                "Each folder is independent; run its requests in order. "
                "Requires DeepSeek configured on the backend."
            ),
        },
        "variable": variables,
        "item": [],
    }
    for number, case in enumerate(dataset["cases"], 1):
        folder = collection / case["id"]
        (folder / ".resources").mkdir(parents=True, exist_ok=True)
        (folder / ".resources/definition.yaml").write_text(
            json.dumps(
                {
                    "$kind": "collection",
                    "name": case["id"],
                    "description": case["description"],
                    "order": number * 1000,
                },
                indent=2,
            )
            + "\n"
        )
        exported_folder = {
            "name": case["id"],
            "description": case["description"],
            "item": [],
        }
        for index, step in enumerate(case["steps"]):
            path = (
                "/trip-sessions"
                if index == 0
                else "/trip-sessions/{{session_id}}/messages"
            )
            url = "{{base_url}}" + path
            code = "const expected = " + json.dumps(step["expected"]) + ";\n" + checks
            pre = (
                (
                    'pm.collectionVariables.unset("session_id"); '
                    'pm.collectionVariables.unset("previous_draft");'
                )
                if index == 0
                else ""
            )
            scripts = [
                {"type": "afterResponse", "language": "text/javascript", "code": code}
            ]
            events = [
                {
                    "listen": "test",
                    "script": {"type": "text/javascript", "exec": code.splitlines()},
                }
            ]
            if pre:
                scripts.insert(
                    0,
                    {
                        "type": "beforeRequest",
                        "language": "text/javascript",
                        "code": pre,
                    },
                )
                events.insert(
                    0,
                    {
                        "listen": "prerequest",
                        "script": {"type": "text/javascript", "exec": [pre]},
                    },
                )
            body = json.dumps(step["body"], indent=2)
            headers = [{"key": "Content-Type", "value": "application/json"}]
            (folder / f"{index + 1:02d}.request.yaml").write_text(
                json.dumps(
                    {
                        "$kind": "http-request",
                        "name": step["name"],
                        "order": (index + 1) * 1000,
                        "method": "POST",
                        "url": url,
                        "headers": headers,
                        "body": {"type": "json", "content": body},
                        "scripts": scripts,
                    },
                    indent=2,
                )
                + "\n"
            )
            exported_folder["item"].append(
                {
                    "name": step["name"],
                    "event": events,
                    "request": {
                        "method": "POST",
                        "header": headers,
                        "url": url,
                        "body": {
                            "mode": "raw",
                            "raw": body,
                            "options": {"raw": {"language": "json"}},
                        },
                    },
                }
            )
        export["item"].append(exported_folder)
    (root / "postman/planning-conversations.postman_collection.json").write_text(
        json.dumps(export, indent=2) + "\n"
    )
    environment = {
        "name": "Travel AI local",
        "values": [
            {
                "key": "base_url",
                "value": "http://127.0.0.1:8012",
                "enabled": True,
                "type": "default",
            }
        ],
    }
    env_dir = root / "postman/environments"
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / "Travel AI local.environment.yaml").write_text(
        json.dumps(environment, indent=2) + "\n"
    )
    (root / "postman/travel-ai-local.postman_environment.json").write_text(
        json.dumps(
            {
                **environment,
                "_postman_variable_scope": "environment",
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    generate(args.root)


if __name__ == "__main__":
    main()
