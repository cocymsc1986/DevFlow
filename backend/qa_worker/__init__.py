"""QA worker package — runs inside a GitHub Actions runner, not on the control plane.

The control plane (EC2) triggers `.github/workflows/qa.yml`, which checks out
the PR branch and executes `python -m qa_worker` against it. Findings, tool
calls, and screenshots are POSTed back to DevFlow's callback endpoint with
an HMAC-signed signature.
"""
