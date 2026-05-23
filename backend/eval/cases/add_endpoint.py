"""Eval case: Add a new API endpoint to an existing Express app.

Tests whether the agent modifies the existing router/index file to register
the new route, rather than creating a standalone server file.
"""

CASE = {
    "name": "add-endpoint",
    "description": "Add a GET /users endpoint to an existing Express app",
    "issue": {
        "title": "Add GET /users endpoint",
        "description": (
            "Add a new REST endpoint GET /users that returns all users from the database. "
            "It should follow the same pattern as the existing /posts endpoint."
        ),
        "issue_type": "feature",
        "has_ui": False,
    },
    "repo_tree": [
        "package.json",
        "tsconfig.json",
        "src/index.ts",
        "src/db.ts",
        "src/routes/health.ts",
        "src/routes/posts.ts",
        "src/middleware/auth.ts",
        "tests/health.test.ts",
        "tests/posts.test.ts",
    ],
    "repo_files": {
        "package.json": (
            '{"name": "my-api", "scripts": {"test": "jest"}, '
            '"dependencies": {"express": "^4.18", "pg": "^8.11"}, '
            '"devDependencies": {"@types/express": "^4.17", "jest": "^29", '
            '"ts-jest": "^29", "supertest": "^6", "@types/supertest": "^2"}}'
        ),
        "src/index.ts": (
            'import express from "express";\n'
            'import healthRouter from "./routes/health";\n'
            'import postsRouter from "./routes/posts";\n'
            '\n'
            'const app = express();\n'
            'app.use(express.json());\n'
            'app.use("/health", healthRouter);\n'
            'app.use("/posts", postsRouter);\n'
            '\n'
            'export default app;\n'
        ),
        "src/routes/posts.ts": (
            'import { Router } from "express";\n'
            'import { pool } from "../db";\n'
            '\n'
            'const router = Router();\n'
            '\n'
            'router.get("/", async (req, res) => {\n'
            '  const result = await pool.query("SELECT * FROM posts");\n'
            '  res.json(result.rows);\n'
            '});\n'
            '\n'
            'export default router;\n'
        ),
        "src/db.ts": (
            'import { Pool } from "pg";\n'
            '\n'
            'export const pool = new Pool({\n'
            '  connectionString: process.env.DATABASE_URL,\n'
            '});\n'
        ),
        "tests/posts.test.ts": (
            'import request from "supertest";\n'
            'import app from "../src/index";\n'
            '\n'
            'describe("GET /posts", () => {\n'
            '  it("returns 200", async () => {\n'
            '    const res = await request(app).get("/posts");\n'
            '    expect(res.status).toBe(200);\n'
            '  });\n'
            '});\n'
        ),
    },
    "checks": {
        "must_modify": ["src/index.ts"],
        "should_not_create": ["src/index.ts", "src/db.ts"],
        "expect_files_matching": ["src/routes/users"],
        "test_framework": "jest",
    },
}
