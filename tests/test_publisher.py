"""
tests/test_publisher.py

Unit tests for GitHub Pages automated publishing via PyGithub.
"""

from unittest.mock import MagicMock, patch
import pytest
from github import GithubException

from rss.publisher import publish_to_github


def test_publish_missing_token():
    success, url, err = publish_to_github("<xml/>", "user/repo", token="")
    assert not success
    assert "token" in err.lower()


def test_publish_missing_repo():
    success, url, err = publish_to_github("<xml/>", "", token="ghp_fake")
    assert not success
    assert "repository" in err.lower()


@patch("rss.publisher.Github")
def test_publish_create_new_file(mock_github_cls):
    mock_gh = MagicMock()
    mock_github_cls.return_value = mock_gh

    mock_user = MagicMock()
    mock_user.login = "tanvish619"
    mock_gh.get_user.return_value = mock_user

    mock_repo = MagicMock()
    mock_repo.full_name = "tanvish619/rss_feedd"
    mock_gh.get_repo.return_value = mock_repo

    # Simulate file not existing (404)
    mock_repo.get_contents.side_effect = GithubException(404, {"message": "Not Found"}, headers={})

    success, pages_url, err = publish_to_github(
        xml_content="<rss><channel><title>Test</title></channel></rss>",
        repo_name="tanvish619/rss_feedd",
        file_path="feed.xml",
        token="ghp_mock_token_123",
        branch="main",
    )

    assert success
    assert err is None
    assert pages_url == "https://tanvish619.github.io/rss_feedd/feed.xml"
    mock_repo.create_file.assert_called_once()


@patch("rss.publisher.Github")
def test_publish_update_existing_file(mock_github_cls):
    mock_gh = MagicMock()
    mock_github_cls.return_value = mock_gh

    mock_user = MagicMock()
    mock_user.login = "tanvish619"
    mock_gh.get_user.return_value = mock_user

    mock_repo = MagicMock()
    mock_repo.full_name = "tanvish619/rss_feedd"
    mock_gh.get_repo.return_value = mock_repo

    mock_contents = MagicMock()
    mock_contents.path = "feed.xml"
    mock_contents.sha = "abcdef123456"
    mock_repo.get_contents.return_value = mock_contents

    success, pages_url, err = publish_to_github(
        xml_content="<rss><channel><title>Updated</title></channel></rss>",
        repo_name="tanvish619/rss_feedd",
        file_path="feed.xml",
        token="ghp_mock_token_123",
        branch="main",
    )

    assert success
    assert err is None
    assert pages_url == "https://tanvish619.github.io/rss_feedd/feed.xml"
    mock_repo.update_file.assert_called_once_with(
        path="feed.xml",
        message="Update feed.xml via RSS Feed Builder",
        content="<rss><channel><title>Updated</title></channel></rss>",
        sha="abcdef123456",
        branch="main",
    )
