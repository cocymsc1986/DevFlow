import os
import logging
from github import Github, GithubException

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self):
        token = os.getenv("GITHUB_TOKEN", "")
        self.owner = os.getenv("GITHUB_OWNER", "")
        self._github = Github(token) if token else None
        self.is_configured = bool(token and self.owner)

    def list_repos(self) -> list[dict]:
        if not self._github:
            return []
        try:
            user = self._github.get_user()
            repos = []
            for repo in user.get_repos():
                repos.append({
                    "full_name": repo.full_name,
                    "name": repo.name,
                    "owner": repo.owner.login,
                    "private": repo.private,
                    "default_branch": repo.default_branch,
                    "url": repo.html_url,
                })
            return repos
        except GithubException as e:
            logger.error("Failed to list repos: %s", e)
            return []

    def _get_repo(self, repo: str):
        return self._github.get_repo(repo)

    def create_branch(self, repo: str, name: str, from_branch: str = "main") -> dict:
        gh_repo = self._get_repo(repo)
        source = gh_repo.get_branch(from_branch)
        gh_repo.create_git_ref(ref=f"refs/heads/{name}", sha=source.commit.sha)
        return {"branch": name, "sha": source.commit.sha}

    def push_files(self, repo: str, branch: str, files: list[dict], commit_message: str) -> dict:
        gh_repo = self._get_repo(repo)
        results = []
        for f in files:
            path = f["path"]
            content = f["content"]
            try:
                existing = gh_repo.get_contents(path, ref=branch)
                result = gh_repo.update_file(path, commit_message, content, existing.sha, branch=branch)
                results.append({"path": path, "action": "updated"})
            except GithubException:
                result = gh_repo.create_file(path, commit_message, content, branch=branch)
                results.append({"path": path, "action": "created"})
        return {"files": results}

    def create_pr(self, repo: str, branch: str, title: str, body: str, base: str = "main") -> dict:
        gh_repo = self._get_repo(repo)
        pr = gh_repo.create_pull(title=title, body=body, head=branch, base=base)
        return {"number": pr.number, "url": pr.html_url, "title": pr.title}

    def add_pr_comment(self, repo: str, pr_number: int, comment: str) -> dict:
        gh_repo = self._get_repo(repo)
        pr = gh_repo.get_pull(pr_number)
        issue_comment = pr.create_issue_comment(comment)
        return {"comment_id": issue_comment.id}

    def get_repo_info(self, repo: str = None) -> dict:
        if not self._github:
            return {"configured": False}
        try:
            target = repo or f"{self.owner}/{os.getenv('GITHUB_REPO', '')}"
            gh_repo = self._get_repo(target)
            return {
                "configured": True,
                "name": gh_repo.full_name,
                "default_branch": gh_repo.default_branch,
                "url": gh_repo.html_url,
            }
        except GithubException as e:
            logger.error("Failed to get repo info: %s", e)
            return {"configured": False, "error": str(e)}
