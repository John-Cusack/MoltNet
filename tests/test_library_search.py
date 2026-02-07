"""Tests for the library search & consumption feature.

Tests cover:
- MoltGit enriched search (database + API)
- Library usage tracking (record, update, reviews)
- MoltGit client enriched methods
- Sandbox PYTHONPATH injection
- Bot library search phase logic
- Bot import detection
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from clawdbot.fitness.sandbox import Sandbox

# ==================== Sandbox PYTHONPATH Tests ====================


class TestSandboxPythonPath:
    """Test that Sandbox properly sets PYTHONPATH."""

    async def test_sandbox_default_empty_pythonpath(self):
        """Default sandbox has empty PYTHONPATH."""
        sandbox = Sandbox(timeout_seconds=5.0)
        assert sandbox.extra_python_paths == []

    async def test_sandbox_with_extra_paths(self):
        """Sandbox accepts extra_python_paths."""
        paths = ["/tmp/libs/foo", "/tmp/libs/bar"]
        sandbox = Sandbox(timeout_seconds=5.0, extra_python_paths=paths)
        assert sandbox.extra_python_paths == paths

    async def test_sandbox_executes_with_extra_paths(self):
        """Code in sandbox can import from extra python paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a module in a temp directory
            lib_dir = Path(tmpdir) / "mylib"
            lib_dir.mkdir()
            (lib_dir / "helper.py").write_text(
                "def greet(name):\n    return f'Hello, {name}!'\n"
            )

            sandbox = Sandbox(
                timeout_seconds=5.0,
                extra_python_paths=[str(lib_dir)],
            )

            result = await sandbox.execute(
                "from helper import greet\n"
                "print(greet('world'))"
            )

            assert result.success
            assert "Hello, world!" in result.output

    async def test_sandbox_without_extra_paths_cannot_import(self):
        """Without extra paths, imports from custom dirs fail."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lib_dir = Path(tmpdir) / "mylib"
            lib_dir.mkdir()
            (lib_dir / "helper.py").write_text("def greet(): return 'hi'\n")

            sandbox = Sandbox(timeout_seconds=5.0)

            result = await sandbox.execute(
                "from helper import greet\nprint(greet())"
            )

            assert not result.success


# ==================== MoltGit Database Tests ====================


class TestMoltGitDatabaseEnhancements:
    """Test MoltGit database library_usage and enriched search."""

    async def test_record_and_update_library_usage(self):
        """Test recording and updating library usage."""
        from moltgit.database import MoltGitDatabase

        with tempfile.TemporaryDirectory() as tmpdir:
            db = MoltGitDatabase(db_path=Path(tmpdir) / "test.db")
            await db.connect()

            try:
                # Create a repo first
                repo_id = await db.create_repo({
                    "name": "test_lib",
                    "owner_bot": "bot-001",
                    "description": "A test library",
                })

                # Record usage
                usage_id = await db.record_library_usage(
                    repo_id=repo_id,
                    bot_name="bot-002",
                    task_type="code_generation",
                )
                assert usage_id

                # Update with outcome
                updated = await db.update_library_usage(
                    usage_id=usage_id,
                    task_success=True,
                    feedback="Great library, very useful!",
                )
                assert updated

                # Check stats
                stats = await db.get_repo_usage_stats(repo_id)
                assert stats["download_count"] == 1
                assert stats["success_count"] == 1
                assert stats["success_rate"] == 1.0

                # Check reviews
                reviews = await db.get_library_reviews(repo_id)
                assert len(reviews) == 1
                assert reviews[0]["bot_name"] == "bot-002"
                assert reviews[0]["feedback"] == "Great library, very useful!"
                assert reviews[0]["task_success"] is True

            finally:
                await db.close()

    async def test_usage_stats_multiple_bots(self):
        """Test usage stats with multiple bots, mixed outcomes."""
        from moltgit.database import MoltGitDatabase

        with tempfile.TemporaryDirectory() as tmpdir:
            db = MoltGitDatabase(db_path=Path(tmpdir) / "test.db")
            await db.connect()

            try:
                repo_id = await db.create_repo({
                    "name": "utils",
                    "owner_bot": "bot-001",
                })

                # Bot A: success
                uid1 = await db.record_library_usage(repo_id, "bot-a", "code_generation")
                await db.update_library_usage(uid1, True, "Good")

                # Bot B: failure
                uid2 = await db.record_library_usage(repo_id, "bot-b", "bug_fix")
                await db.update_library_usage(uid2, False, "Didn't help")

                # Bot C: success
                uid3 = await db.record_library_usage(repo_id, "bot-c", "script_creation")
                await db.update_library_usage(uid3, True, "")

                stats = await db.get_repo_usage_stats(repo_id)
                assert stats["download_count"] == 3
                assert stats["success_count"] == 2
                assert abs(stats["success_rate"] - 2 / 3) < 0.01

                # Only reviews with non-empty feedback
                reviews = await db.get_library_reviews(repo_id)
                assert len(reviews) == 2  # Bot C had empty feedback

            finally:
                await db.close()

    async def test_analyze_repo_extracts_exports(self):
        """Test that analyze_repo extracts function and class names."""
        from moltgit.database import MoltGitDatabase

        with tempfile.TemporaryDirectory() as tmpdir:
            db = MoltGitDatabase(db_path=Path(tmpdir) / "test.db")
            await db.connect()

            try:
                repo_id = await db.create_repo({
                    "name": "string_utils",
                    "owner_bot": "bot-001",
                })

                # Push a Python file
                await db.create_or_update_file(
                    repo_id=repo_id,
                    path="string_utils.py",
                    content=(
                        'def slugify(text):\n'
                        '    """Convert text to slug."""\n'
                        '    return text.lower().replace(" ", "-")\n\n'
                        'def _private_helper():\n'
                        '    pass\n\n'
                        'class TextProcessor:\n'
                        '    """Process text."""\n'
                        '    def transform(self, s):\n'
                        '        return s.upper()\n'
                    ),
                    bot_name="bot-001",
                )

                analysis = await db.analyze_repo(repo_id)

                assert analysis["function_count"] >= 2  # slugify + _private + transform
                assert analysis["class_count"] == 1
                assert "exports" in analysis
                exports = analysis["exports"]

                # Should include public functions/classes, not private
                export_names = [e["name"] for e in exports]
                assert "slugify" in export_names
                assert "TextProcessor" in export_names
                assert "_private_helper" not in export_names

                # Check signature format
                slugify_export = next(e for e in exports if e["name"] == "slugify")
                assert slugify_export["signature"] == "slugify(text)"
                assert slugify_export["type"] == "function"

            finally:
                await db.close()

    async def test_enriched_search_results(self):
        """Test enriched search includes exports and usage stats."""
        from moltgit.database import MoltGitDatabase

        with tempfile.TemporaryDirectory() as tmpdir:
            db = MoltGitDatabase(db_path=Path(tmpdir) / "test.db")
            await db.connect()

            try:
                repo_id = await db.create_repo({
                    "name": "data_utils",
                    "owner_bot": "bot-001",
                    "description": "Data manipulation utilities",
                })

                await db.create_or_update_file(
                    repo_id=repo_id,
                    path="data_utils.py",
                    content=(
                        "def flatten(nested_list):\n"
                        '    """Flatten a list."""\n'
                        "    return [x for sub in nested_list for x in sub]\n"
                    ),
                    bot_name="bot-001",
                )

                # Analyze to populate exports
                await db.analyze_repo(repo_id)

                # Record some usage
                uid = await db.record_library_usage(repo_id, "bot-002", "code_generation")
                await db.update_library_usage(uid, True, "Useful flatten function")

                # Search enriched
                results, total = await db.get_enriched_search_results("data")
                assert total >= 1
                assert len(results) >= 1

                result = results[0]
                assert result["name"] == "data_utils"
                assert result["download_count"] == 1
                assert result["success_count"] == 1
                assert result["success_rate"] == 1.0
                assert len(result["exports"]) >= 1
                assert result["exports"][0]["name"] == "flatten"

            finally:
                await db.close()


# ==================== MoltGit Client Tests ====================


class TestMoltGitClientEnhancements:
    """Test MoltGit client enriched search and usage reporting."""

    async def test_search_repos_enriched(self):
        """Test enriched search returns EnrichedRepo objects."""
        from clawdbot.moltgit_client import EnrichedRepo, MoltGitClient

        client = MoltGitClient(base_url="http://test:9103", bot_name="bot-test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "items": [
                {
                    "id": "abc123",
                    "name": "string_utils",
                    "owner_bot": "bot-001",
                    "description": "String utilities",
                    "stars": 3,
                    "file_count": 1,
                    "exports": [
                        {
                            "type": "function",
                            "name": "slugify",
                            "signature": "slugify(text)",
                            "docstring": "Convert to slug",
                        }
                    ],
                    "download_count": 5,
                    "success_count": 4,
                    "success_rate": 0.8,
                }
            ],
            "total": 1,
            "offset": 0,
            "limit": 5,
            "has_more": False,
        }

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_response)
        client._client = mock_http

        results = await client.search_repos_enriched("string", limit=5)

        assert len(results) == 1
        repo = results[0]
        assert isinstance(repo, EnrichedRepo)
        assert repo.name == "string_utils"
        assert repo.stars == 3
        assert len(repo.exports) == 1
        assert repo.exports[0]["name"] == "slugify"
        assert repo.download_count == 5
        assert repo.success_rate == 0.8

        await client.close()

    async def test_report_usage(self):
        """Test usage reporting."""
        from clawdbot.moltgit_client import MoltGitClient

        client = MoltGitClient(base_url="http://test:9103", bot_name="bot-test")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "usage_id": "uid-123"}

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_response)
        client._client = mock_http

        success = await client.report_usage(
            owner="bot-001",
            repo="string_utils",
            task_type="code_generation",
            task_success=True,
            feedback="Very helpful library",
        )

        assert success
        mock_http.post.assert_called_once()

        await client.close()

    async def test_search_repos_enriched_disabled(self):
        """Disabled client returns empty list."""
        from clawdbot.moltgit_client import MoltGitClient

        client = MoltGitClient(base_url="", bot_name="bot-test")
        assert not client.is_enabled

        results = await client.search_repos_enriched("test")
        assert results == []

        await client.close()


# ==================== Bot Integration Tests ====================


class TestBotImportDetection:
    """Test the static import detection method."""

    def test_detect_import_statement(self):
        """Detect 'import module' pattern."""
        from clawdbot.openclaw_bot import OpenClawBot

        code = "import string_utils\nresult = string_utils.slugify('hello')"
        assert OpenClawBot._detect_import(code, ["string_utils"]) is True

    def test_detect_from_import(self):
        """Detect 'from module import ...' pattern."""
        from clawdbot.openclaw_bot import OpenClawBot

        code = "from data_utils import flatten\nresult = flatten([[1,2],[3]])"
        assert OpenClawBot._detect_import(code, ["data_utils"]) is True

    def test_no_import_detected(self):
        """No import found."""
        from clawdbot.openclaw_bot import OpenClawBot

        code = "def solve():\n    return 42"
        assert OpenClawBot._detect_import(code, ["string_utils"]) is False

    def test_empty_inputs(self):
        """Empty code or module names."""
        from clawdbot.openclaw_bot import OpenClawBot

        assert OpenClawBot._detect_import("", ["foo"]) is False
        assert OpenClawBot._detect_import("import foo", []) is False
        assert OpenClawBot._detect_import("", []) is False


# ==================== Verifier PYTHONPATH Threading ====================


class TestVerifierPythonPath:
    """Test that extra_python_paths threads through verifiers."""

    async def test_verify_openclaw_task_passes_paths(self):
        """verify_openclaw_task passes extra_python_paths to CodeTestVerifier."""
        from clawdbot.fitness.openclaw_tasks import (
            OpenClawTaskType,
            VerificationType,
        )
        from clawdbot.fitness.openclaw_verifiers import CodeTestVerifier, get_openclaw_verifier

        # Create a mock task that uses TEST_CASES verification
        task = MagicMock()
        task.verification_type = VerificationType.TEST_CASES
        task.task_type = OpenClawTaskType.CODE_GENERATION

        verifier = get_openclaw_verifier(
            task,
            workspace="/tmp/test",
            extra_python_paths=["/tmp/libs/a", "/tmp/libs/b"],
        )

        assert isinstance(verifier, CodeTestVerifier)
        assert verifier.sandbox.extra_python_paths == ["/tmp/libs/a", "/tmp/libs/b"]

    async def test_verify_without_extra_paths(self):
        """Without extra paths, sandbox has empty PYTHONPATH."""
        from clawdbot.fitness.openclaw_tasks import VerificationType
        from clawdbot.fitness.openclaw_verifiers import CodeTestVerifier, get_openclaw_verifier

        task = MagicMock()
        task.verification_type = VerificationType.TEST_CASES

        verifier = get_openclaw_verifier(task, workspace="/tmp/test")

        assert isinstance(verifier, CodeTestVerifier)
        assert verifier.sandbox.extra_python_paths == []


# ==================== MoltGit API Endpoint Tests ====================


class TestMoltGitEndpoints:
    """Test MoltGit API endpoints for usage and reviews."""

    @pytest.fixture
    async def app_client(self):
        """Create a test client for MoltGit app."""
        from httpx import ASGITransport, AsyncClient

        from moltgit.database import db
        from moltgit.main import app

        # Connect DB with temp path
        with tempfile.TemporaryDirectory() as tmpdir:
            db.db_path = Path(tmpdir) / "test.db"
            await db.connect()

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                yield client

            await db.close()

    async def test_enriched_search(self, app_client):
        """Test /search/repos?enriched=true returns exports."""
        client = app_client

        # Create a repo with a Python file
        resp = await client.post("/repos", json={
            "name": "str_utils",
            "owner_bot": "bot-001",
            "description": "String utilities",
        })
        assert resp.status_code == 201

        # Push a file (triggers auto-analysis)
        resp = await client.put(
            "/repos/bot-001/str_utils/files/str_utils.py",
            json={
                "content": 'def slugify(text):\n    return text.lower().replace(" ", "-")\n',
                "bot_name": "bot-001",
            },
        )
        assert resp.status_code == 200

        # Search enriched
        resp = await client.get("/search/repos", params={"q": "str", "enriched": "true"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        item = data["items"][0]
        assert "exports" in item
        assert "download_count" in item
        assert "success_rate" in item

    async def test_report_usage_endpoint(self, app_client):
        """Test POST /repos/{owner}/{name}/usage."""
        client = app_client

        # Create a repo
        await client.post("/repos", json={
            "name": "test_lib",
            "owner_bot": "bot-001",
        })

        # Report usage
        resp = await client.post(
            "/repos/bot-001/test_lib/usage",
            json={
                "bot_name": "bot-002",
                "task_type": "code_generation",
                "task_success": True,
                "feedback": "Useful library",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "usage_id" in data

    async def test_reviews_endpoint(self, app_client):
        """Test GET /repos/{owner}/{name}/reviews."""
        client = app_client

        # Create repo and report usage with feedback
        await client.post("/repos", json={
            "name": "reviewed_lib",
            "owner_bot": "bot-001",
        })

        await client.post(
            "/repos/bot-001/reviewed_lib/usage",
            json={
                "bot_name": "bot-002",
                "task_type": "code_generation",
                "task_success": True,
                "feedback": "Great slugify function",
            },
        )

        # Get reviews
        resp = await client.get("/repos/bot-001/reviewed_lib/reviews")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["reviews"][0]["feedback"] == "Great slugify function"
        assert data["reviews"][0]["task_success"] is True

    async def test_usage_for_nonexistent_repo(self, app_client):
        """Test usage report for missing repo returns 404."""
        client = app_client
        resp = await client.post(
            "/repos/nobody/nothing/usage",
            json={
                "bot_name": "bot-002",
                "task_type": "test",
                "task_success": False,
            },
        )
        assert resp.status_code == 404

    async def test_auto_analyze_on_push(self, app_client):
        """Test that pushing a .py file triggers auto-analysis."""
        client = app_client

        await client.post("/repos", json={
            "name": "auto_analyzed",
            "owner_bot": "bot-001",
        })

        # Push Python file
        await client.put(
            "/repos/bot-001/auto_analyzed/files/utils.py",
            json={
                "content": "def helper(x):\n    return x * 2\n",
                "bot_name": "bot-001",
            },
        )

        # Analysis should now exist
        resp = await client.get("/repos/bot-001/auto_analyzed/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["function_count"] >= 1
        assert len(data.get("exports", [])) >= 1

    async def test_enhanced_usage_stats(self, app_client):
        """Test /analysis/usage includes success_count and success_rate."""
        client = app_client

        # Create repo with a star so it appears in trending
        resp = await client.post("/repos", json={
            "name": "popular_lib",
            "owner_bot": "bot-001",
        })

        await client.post(
            "/repos/bot-001/popular_lib/star",
            json={"bot_name": "bot-002"},
        )

        # Report usage
        await client.post(
            "/repos/bot-001/popular_lib/usage",
            json={
                "bot_name": "bot-003",
                "task_type": "code_generation",
                "task_success": True,
                "feedback": "",
            },
        )

        resp = await client.get("/analysis/usage")
        assert resp.status_code == 200
        data = resp.json()
        usage = data["usage"]
        assert len(usage) >= 1
        # Find our repo
        our_repo = next((u for u in usage if u["repo_name"] == "popular_lib"), None)
        assert our_repo is not None
        assert "success_count" in our_repo
        assert "success_rate" in our_repo
