"""Eval case: Fix a bug in an existing React component.

Tests whether the agent modifies the existing component file rather than
creating a new replacement component.
"""

CASE = {
    "name": "fix-pagination-bug",
    "description": "Fix off-by-one error in pagination component",
    "issue": {
        "title": "Pagination shows wrong page count",
        "description": (
            "The UserList component's pagination shows 1 extra page when the total "
            "number of items is exactly divisible by the page size. For example, "
            "20 items with page size 10 shows 3 pages instead of 2. "
            "The bug is in the page count calculation in UserList.jsx."
        ),
        "issue_type": "bug",
        "has_ui": True,
    },
    "repo_tree": [
        "package.json",
        "src/App.jsx",
        "src/main.jsx",
        "src/index.css",
        "src/components/UserList.jsx",
        "src/components/UserForm.jsx",
        "src/components/Pagination.jsx",
        "src/hooks/useUsers.js",
        "src/api/client.js",
        "tests/UserList.test.jsx",
        "tests/setup.js",
        "vite.config.js",
    ],
    "repo_files": {
        "package.json": (
            '{"name": "user-admin", "scripts": {"test": "vitest"}, '
            '"dependencies": {"react": "^18", "react-dom": "^18"}, '
            '"devDependencies": {"vitest": "^1", "@testing-library/react": "^14", '
            '"@testing-library/jest-dom": "^6", "jsdom": "^24"}}'
        ),
        "src/components/UserList.jsx": (
            'import { useState } from "react";\n'
            'import { useUsers } from "../hooks/useUsers";\n'
            'import Pagination from "./Pagination";\n'
            '\n'
            'const PAGE_SIZE = 10;\n'
            '\n'
            'export default function UserList() {\n'
            '  const [page, setPage] = useState(1);\n'
            '  const { users, total } = useUsers(page, PAGE_SIZE);\n'
            '  const pageCount = Math.ceil(total / PAGE_SIZE) + 1;\n'
            '\n'
            '  return (\n'
            '    <div>\n'
            '      <h2>Users</h2>\n'
            '      <ul>\n'
            '        {users.map(u => <li key={u.id}>{u.name}</li>)}\n'
            '      </ul>\n'
            '      <Pagination page={page} pageCount={pageCount} onChange={setPage} />\n'
            '    </div>\n'
            '  );\n'
            '}\n'
        ),
        "src/components/Pagination.jsx": (
            'export default function Pagination({ page, pageCount, onChange }) {\n'
            '  return (\n'
            '    <div className="flex gap-2">\n'
            '      {Array.from({ length: pageCount }, (_, i) => (\n'
            '        <button\n'
            '          key={i + 1}\n'
            '          onClick={() => onChange(i + 1)}\n'
            '          className={page === i + 1 ? "font-bold" : ""}\n'
            '        >\n'
            '          {i + 1}\n'
            '        </button>\n'
            '      ))}\n'
            '    </div>\n'
            '  );\n'
            '}\n'
        ),
        "tests/UserList.test.jsx": (
            'import { render, screen } from "@testing-library/react";\n'
            'import { describe, it, expect, vi } from "vitest";\n'
            'import UserList from "../src/components/UserList";\n'
            '\n'
            'vi.mock("../src/hooks/useUsers", () => ({\n'
            '  useUsers: () => ({ users: [{ id: 1, name: "Alice" }], total: 1 }),\n'
            '}));\n'
            '\n'
            'describe("UserList", () => {\n'
            '  it("renders users", () => {\n'
            '    render(<UserList />);\n'
            '    expect(screen.getByText("Alice")).toBeInTheDocument();\n'
            '  });\n'
            '});\n'
        ),
    },
    "checks": {
        "must_modify": ["src/components/UserList.jsx"],
        "should_not_create": [
            "src/components/UserList.jsx",
            "src/components/Pagination.jsx",
            "src/App.jsx",
        ],
        "expect_files_matching": [],
        "test_framework": "vitest",
    },
}
