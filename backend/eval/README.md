# DevFlow Offline Evaluation Framework

Measures how accurately the coding agent and PR reviewer perform across
a suite of test cases, without needing GitHub integration or a running server.

## Quick Start

```bash
cd backend
# Run all eval cases (requires ANTHROPIC_API_KEY)
python -m eval.run

# Run a specific case
python -m eval.run --case add-endpoint

# Run with a specific coding model
python -m eval.run --coding-model claude-sonnet-4-6

# List available test cases
python -m eval.run --list
```

## How It Works

1. **Test cases** in `eval/cases/` define an issue, a mock repo tree, mock repo
   file contents, and scoring criteria.
2. The eval runner feeds each case through the assessment → coding → PR review
   pipeline (skipping intake/sizing/router/escalation for speed).
3. A deterministic **scorer** checks the coding output against the case's
   expected outcomes:
   - Did it modify the right files? (integration score)
   - Did it avoid creating files that already exist? (no-duplicate score)
   - Do tests use the correct framework? (test quality score)
   - Does the output parse as valid JSON? (format score)
4. Results are written to `eval/results/` as JSON with timestamps, so you can
   track score changes over time as you iterate on prompts.

## Writing Test Cases

Create a Python file in `eval/cases/` that defines a `CASE` dict:

```python
CASE = {
    "name": "add-endpoint",
    "description": "Add a GET /users endpoint to an Express app",
    "issue": {
        "title": "Add GET /users endpoint",
        "description": "Add a new endpoint that returns all users from the database",
        "issue_type": "feature",
        "has_ui": False,
    },
    "repo_tree": [
        "package.json",
        "src/index.ts",
        "src/routes/health.ts",
        "src/routes/posts.ts",
        "src/db.ts",
        "tests/health.test.ts",
        "tests/posts.test.ts",
        "tsconfig.json",
    ],
    "repo_files": {
        "package.json": '{"dependencies": {"express": "^4"}, "devDependencies": {"jest": "^29", "ts-jest": "^29"}}',
        "src/routes/posts.ts": 'import { Router } from "express";\nimport { db } from "../db";\n\nconst router = Router();\nrouter.get("/", async (req, res) => {\n  const posts = await db.query("SELECT * FROM posts");\n  res.json(posts);\n});\n\nexport default router;\n',
        "tests/posts.test.ts": 'import request from "supertest";\nimport app from "../src/index";\n\ndescribe("GET /posts", () => {\n  it("returns posts", async () => {\n    const res = await request(app).get("/posts");\n    expect(res.status).toBe(200);\n  });\n});\n',
    },
    "checks": {
        "must_modify": ["src/index.ts"],
        "should_not_create": ["src/routes/posts.ts"],
        "expect_files_matching": ["src/routes/users.ts"],
        "test_framework": "jest",
    },
}
```

## Scoring Dimensions

| Dimension        | What it measures                                         |
|-----------------|----------------------------------------------------------|
| integration     | Modified files from `must_modify` list                   |
| no_duplicate    | Avoided creating files that already exist                |
| file_coverage   | Produced files matching `expect_files_matching` patterns |
| test_framework  | Tests use the correct test framework                     |
| format          | Output is valid JSON with required fields                |
| action_accuracy | Used correct action (create vs modify) per file          |
