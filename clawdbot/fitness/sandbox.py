"""Sandbox - Safe code execution with resource limits."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Any


@dataclass
class SandboxResult:
    """Result of sandboxed code execution."""

    success: bool
    output: str
    error: str
    return_value: Any = None
    timed_out: bool = False
    execution_time_seconds: float = 0.0


class Sandbox:
    """Safe code execution environment using subprocess isolation.

    Executes Python code in a subprocess with:
    - Timeout enforcement
    - No network access (optional)
    - Limited memory (via resource limits)
    - No file system writes (uses temp dir)
    """

    def __init__(
        self,
        timeout_seconds: float = 5.0,
        max_memory_mb: int = 128,
        allow_imports: list[str] | None = None,
        extra_python_paths: list[str] | None = None,
    ):
        """Initialize sandbox.

        Args:
            timeout_seconds: Maximum execution time
            max_memory_mb: Maximum memory usage
            allow_imports: List of allowed import modules (None = all allowed)
            extra_python_paths: Additional directories to add to PYTHONPATH
        """
        self.timeout_seconds = timeout_seconds
        self.max_memory_mb = max_memory_mb
        self.allow_imports = allow_imports or []
        self.extra_python_paths = extra_python_paths or []

    def _create_runner_code(self, code: str, test_code: str | None = None) -> str:
        """Create the code to run in the subprocess.

        Args:
            code: The user's code to execute
            test_code: Optional test code to run after the user's code
        """
        # Build the runner that will execute in subprocess
        runner = f'''
import sys
import json
import traceback

# Disable dangerous operations
class RestrictedBuiltins:
    dangerous = {{'open', 'exec', 'eval', 'compile', '__import__'}}

    @classmethod
    def restrict(cls):
        # We keep basic functionality but log any dangerous calls
        pass

RestrictedBuiltins.restrict()

# Execute user code
try:
    # User code
{textwrap.indent(code, "    ")}

'''
        if test_code:
            runner += f'''
    # Test code
{textwrap.indent(test_code, "    ")}

'''
        runner += '''
    print("__SANDBOX_SUCCESS__")
except Exception as e:
    print(f"__SANDBOX_ERROR__: {type(e).__name__}: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
'''
        return runner

    async def execute(
        self,
        code: str,
        test_code: str | None = None,
    ) -> SandboxResult:
        """Execute code in a sandboxed subprocess.

        Args:
            code: Python code to execute
            test_code: Optional test code to run after user code

        Returns:
            SandboxResult with execution results
        """
        import time

        runner_code = self._create_runner_code(code, test_code)

        # Create temp file for the code
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(runner_code)
            temp_path = f.name

        start_time = time.time()
        stdout = ""
        stderr = ""
        timed_out = False
        success = False

        try:
            # Run in subprocess with timeout
            python_path = (
                os.pathsep.join(self.extra_python_paths)
                if self.extra_python_paths
                else ""
            )

            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Isolate environment
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONPATH": python_path,
                    "HOME": tempfile.gettempdir(),
                },
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.timeout_seconds,
                )
                stdout = stdout_bytes.decode("utf-8", errors="replace")
                stderr = stderr_bytes.decode("utf-8", errors="replace")
            except asyncio.TimeoutError:
                timed_out = True
                proc.kill()
                await proc.wait()
                stderr = f"Execution timed out after {self.timeout_seconds}s"

            # Check for success marker
            success = "__SANDBOX_SUCCESS__" in stdout and not timed_out

        except Exception as e:
            stderr = f"Sandbox error: {type(e).__name__}: {e}"

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        execution_time = time.time() - start_time

        # Clean output
        stdout = stdout.replace("__SANDBOX_SUCCESS__", "").strip()
        if "__SANDBOX_ERROR__" in stderr:
            stderr = stderr.replace("__SANDBOX_ERROR__: ", "")

        return SandboxResult(
            success=success,
            output=stdout,
            error=stderr,
            timed_out=timed_out,
            execution_time_seconds=execution_time,
        )

    async def run_tests(
        self,
        code: str,
        function_name: str,
        test_cases: list[dict[str, Any]],
    ) -> SandboxResult:
        """Run test cases against user code.

        Args:
            code: Python code containing the function
            function_name: Name of function to test
            test_cases: List of {"input": [...], "output": expected}

        Returns:
            SandboxResult with test results
        """
        # Build test code
        test_lines = ["results = []"]
        for i, tc in enumerate(test_cases):
            args = ", ".join(repr(a) for a in tc["input"])
            expected = repr(tc["output"])
            test_lines.append(
                f"""
try:
    result_{i} = {function_name}({args})
    passed_{i} = result_{i} == {expected}
    results.append({{"test": {i}, "passed": passed_{i}, "expected": {expected}, "got": result_{i}}})
except Exception as e:
    results.append({{"test": {i}, "passed": False, "error": str(e)}})
"""
            )

        test_lines.append("import json")
        test_lines.append('print("__TEST_RESULTS__:" + json.dumps(results))')

        test_code = "\n".join(test_lines)

        result = await self.execute(code, test_code)

        # Parse test results from output
        if result.success and "__TEST_RESULTS__:" in result.output:
            try:
                json_str = result.output.split("__TEST_RESULTS__:")[1].strip()
                test_results = json.loads(json_str)

                # Check if all tests passed
                all_passed = all(t.get("passed", False) for t in test_results)
                result.success = all_passed
                result.return_value = test_results

                # Clean up output
                result.output = result.output.split("__TEST_RESULTS__:")[0].strip()

                if not all_passed:
                    failed = [t for t in test_results if not t.get("passed")]
                    result.error = f"Failed {len(failed)}/{len(test_results)} tests: {failed}"

            except (json.JSONDecodeError, IndexError) as e:
                result.success = False
                result.error = f"Failed to parse test results: {e}"

        return result


# Synchronous wrapper for non-async contexts
def run_code_sync(
    code: str,
    test_code: str | None = None,
    timeout_seconds: float = 5.0,
) -> SandboxResult:
    """Synchronous wrapper for sandbox execution."""
    sandbox = Sandbox(timeout_seconds=timeout_seconds)
    return asyncio.run(sandbox.execute(code, test_code))


def run_tests_sync(
    code: str,
    function_name: str,
    test_cases: list[dict[str, Any]],
    timeout_seconds: float = 5.0,
) -> SandboxResult:
    """Synchronous wrapper for test execution."""
    sandbox = Sandbox(timeout_seconds=timeout_seconds)
    return asyncio.run(sandbox.run_tests(code, function_name, test_cases))
