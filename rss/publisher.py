"""
rss/publisher.py

Automated Static Hosting via GitHub API using PyGithub.
Publishes generated RSS feeds directly to a GitHub repository to be served
publicly via GitHub Pages.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from github import Auth, Github, GithubException

logger = logging.getLogger(__name__)


def publish_to_github(
    xml_content: str,
    repo_name: str,
    file_path: str = "feed.xml",
    token: Optional[str] = None,
    branch: str = "main",
) -> Tuple[bool, str, Optional[str]]:
    """
    Publish or update *xml_content* in a GitHub repository using the GitHub API.

    Parameters:
        xml_content: The raw XML string to publish.
        repo_name: Target repository in 'owner/repo' format or 'repo' name.
        file_path: Relative path in the repository (default 'feed.xml').
        token: GitHub Personal Access Token (PAT).
        branch: Target branch (default 'main').

    Returns:
        (success, pages_url_or_message, error_message)
    """
    if not token or not token.strip():
        return False, "", "GitHub Personal Access Token (GITHUB_TOKEN) is required."

    if not repo_name or not repo_name.strip():
        return False, "", "GitHub repository name is required."

    repo_name = repo_name.strip()
    file_path = file_path.strip().lstrip("/")
    token = token.strip()

    try:
        # 1. Authenticate with PyGithub
        auth = Auth.Token(token)
        gh = Github(auth=auth)

        # 2. Connect to the repository
        user = gh.get_user()
        owner_name = user.login

        if "/" in repo_name:
            repo = gh.get_repo(repo_name)
            parts = repo_name.split("/")
            owner_name = parts[0]
            clean_repo = parts[1]
        else:
            clean_repo = repo_name
            repo = user.get_repo(clean_repo)

        # Ensure default branch exists or fallback
        target_branch = branch
        try:
            repo.get_branch(target_branch)
        except GithubException:
            # Fallback to repo's default branch if specified branch doesn't exist
            target_branch = repo.default_branch or "main"

        # 3. Check if file already exists in repository
        commit_message = f"Update {file_path} via RSS Feed Builder"
        try:
            contents = repo.get_contents(file_path, ref=target_branch)
            # Update existing file
            repo.update_file(
                path=contents.path,
                message=commit_message,
                content=xml_content,
                sha=contents.sha,
                branch=target_branch,
            )
            logger.info("Updated %s on branch %s in %s", file_path, target_branch, repo.full_name)
        except GithubException as exc:
            if exc.status == 404:
                # File does not exist: create initial file
                create_msg = f"Create {file_path} via RSS Feed Builder"
                repo.create_file(
                    path=file_path,
                    message=create_msg,
                    content=xml_content,
                    branch=target_branch,
                )
                logger.info("Created %s on branch %s in %s", file_path, target_branch, repo.full_name)
            else:
                raise

        # 4. Construct Public GitHub Pages URL
        # Format: https://[username].github.io/[repo_name]/[file_path]
        pages_url = f"https://{owner_name.lower()}.github.io/{clean_repo}/{file_path}"
        return True, pages_url, None

    except GithubException as exc:
        err_msg = f"GitHub API error ({exc.status}): {exc.data.get('message', str(exc)) if isinstance(exc.data, dict) else str(exc)}"
        logger.error("Publishing to GitHub failed: %s", err_msg)
        return False, "", err_msg
    except Exception as exc:
        err_msg = f"Unexpected error during GitHub publishing: {exc}"
        logger.error(err_msg)
        return False, "", err_msg
