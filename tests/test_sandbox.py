"""Tests for sandbox code execution."""

import pytest
from clawdbot.fitness.sandbox import Sandbox, SandboxResult, run_code_sync, run_tests_sync


class TestSandboxResult:
    """Tests for SandboxResult dataclass."""

    def test_success_result(self):
        """Test successful result structure."""
        result = SandboxResult(
            success=True,
            output="Hello",
            error="",
            return_value=42,
            timed_out=False,
            execution_time_seconds=0.5,
        )

        assert result.success is True
        assert result.output == "Hello"
        assert result.return_value == 42
        assert result.timed_out is False

    def test_failure_result(self):
        """Test failure result structure."""
        result = SandboxResult(
            success=False,
            output="",
            error="NameError: name 'x' is not defined",
            timed_out=False,
            execution_time_seconds=0.1,
        )

        assert result.success is False
        assert "NameError" in result.error


class TestSandbox:
    """Tests for Sandbox class."""

    @pytest.fixture
    def sandbox(self):
        return Sandbox(timeout_seconds=5.0)

    @pytest.mark.asyncio
    async def test_simple_execution(self, sandbox):
        """Test simple code execution."""
        code = "x = 1 + 1\nprint(x)"

        result = await sandbox.execute(code)

        assert result.success is True
        assert "2" in result.output
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_function_definition(self, sandbox):
        """Test function definition and call."""
        code = """
def greet(name):
    return f"Hello, {name}!"

result = greet("World")
print(result)
"""
        result = await sandbox.execute(code)

        assert result.success is True
        assert "Hello, World!" in result.output

    @pytest.mark.asyncio
    async def test_syntax_error(self, sandbox):
        """Test handling of syntax errors."""
        code = "def broken("  # Syntax error

        result = await sandbox.execute(code)

        assert result.success is False
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_runtime_error(self, sandbox):
        """Test handling of runtime errors."""
        code = """
def divide(a, b):
    return a / b

result = divide(1, 0)  # ZeroDivisionError
"""
        result = await sandbox.execute(code)

        assert result.success is False
        assert "ZeroDivisionError" in result.error or "division" in result.error.lower()

    @pytest.mark.asyncio
    async def test_timeout_handling(self, sandbox):
        """Test that infinite loops are terminated."""
        sandbox = Sandbox(timeout_seconds=1.0)  # Short timeout
        code = "while True: pass"

        result = await sandbox.execute(code)

        assert result.success is False
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_with_test_code(self, sandbox):
        """Test execution with separate test code."""
        user_code = """
def add(a, b):
    return a + b
"""
        test_code = """
result = add(2, 3)
print(f"Result: {result}")
assert result == 5, f"Expected 5, got {result}"
"""
        result = await sandbox.execute(user_code, test_code)

        assert result.success is True
        assert "Result: 5" in result.output

    @pytest.mark.asyncio
    async def test_run_tests_all_pass(self, sandbox):
        """Test running test cases that all pass."""
        code = """
def double(n):
    return n * 2
"""
        test_cases = [
            {"input": [5], "output": 10},
            {"input": [0], "output": 0},
            {"input": [-3], "output": -6},
        ]

        result = await sandbox.run_tests(code, "double", test_cases)

        assert result.success is True
        assert result.return_value is not None
        assert len(result.return_value) == 3
        assert all(t["passed"] for t in result.return_value)

    @pytest.mark.asyncio
    async def test_run_tests_partial_pass(self, sandbox):
        """Test running test cases with some failures."""
        code = """
def broken_double(n):
    return n * 2 if n != 0 else 999  # Wrong for n=0
"""
        test_cases = [
            {"input": [5], "output": 10},
            {"input": [0], "output": 0},  # Will fail
            {"input": [-3], "output": -6},
        ]

        result = await sandbox.run_tests(code, "broken_double", test_cases)

        assert result.success is False
        assert result.return_value is not None
        passed_count = sum(1 for t in result.return_value if t["passed"])
        assert passed_count == 2  # 2/3 pass

    @pytest.mark.asyncio
    async def test_run_tests_all_fail(self, sandbox):
        """Test running test cases that all fail."""
        code = """
def wrong(n):
    return 999
"""
        test_cases = [
            {"input": [1], "output": 2},
            {"input": [2], "output": 4},
        ]

        result = await sandbox.run_tests(code, "wrong", test_cases)

        assert result.success is False
        assert result.return_value is not None
        assert all(not t["passed"] for t in result.return_value)

    @pytest.mark.asyncio
    async def test_run_tests_with_exception(self, sandbox):
        """Test handling exceptions during test execution."""
        code = """
def divide(a, b):
    return a / b
"""
        test_cases = [
            {"input": [10, 2], "output": 5},
            {"input": [10, 0], "output": "error"},  # Will raise
        ]

        result = await sandbox.run_tests(code, "divide", test_cases)

        assert result.success is False
        # First test should pass, second should have error
        assert result.return_value[0]["passed"] is True
        assert "error" in result.return_value[1]

    @pytest.mark.asyncio
    async def test_run_tests_timeout(self, sandbox):
        """Test timeout during test execution."""
        sandbox = Sandbox(timeout_seconds=1.0)
        code = """
def infinite(n):
    while True: pass
"""
        test_cases = [{"input": [1], "output": 1}]

        result = await sandbox.run_tests(code, "infinite", test_cases)

        assert result.success is False
        assert result.timed_out is True

    @pytest.mark.asyncio
    async def test_multiple_arguments(self, sandbox):
        """Test functions with multiple arguments."""
        code = """
def add_three(a, b, c):
    return a + b + c
"""
        test_cases = [
            {"input": [1, 2, 3], "output": 6},
            {"input": [0, 0, 0], "output": 0},
            {"input": [-1, 0, 1], "output": 0},
        ]

        result = await sandbox.run_tests(code, "add_three", test_cases)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_list_return_value(self, sandbox):
        """Test functions returning lists."""
        code = """
def double_all(nums):
    return [n * 2 for n in nums]
"""
        test_cases = [
            {"input": [[1, 2, 3]], "output": [2, 4, 6]},
            {"input": [[]], "output": []},
        ]

        result = await sandbox.run_tests(code, "double_all", test_cases)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_string_return_value(self, sandbox):
        """Test functions returning strings."""
        code = """
def greet(name):
    return f"Hello, {name}!"
"""
        test_cases = [
            {"input": ["Alice"], "output": "Hello, Alice!"},
            {"input": [""], "output": "Hello, !"},
        ]

        result = await sandbox.run_tests(code, "greet", test_cases)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_bool_return_value(self, sandbox):
        """Test functions returning booleans."""
        code = """
def is_positive(n):
    return n > 0
"""
        test_cases = [
            {"input": [5], "output": True},
            {"input": [-5], "output": False},
            {"input": [0], "output": False},
        ]

        result = await sandbox.run_tests(code, "is_positive", test_cases)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execution_time_tracking(self, sandbox):
        """Test that execution time is tracked."""
        code = "import time; time.sleep(0.1)"

        result = await sandbox.execute(code)

        assert result.execution_time_seconds >= 0.1


class TestSyncWrappers:
    """Tests for synchronous wrapper functions."""

    def test_run_code_sync(self):
        """Test synchronous code execution."""
        result = run_code_sync("print('hello')")

        assert result.success is True
        assert "hello" in result.output

    def test_run_code_sync_error(self):
        """Test synchronous code execution with error."""
        result = run_code_sync("raise ValueError('test')")

        assert result.success is False
        assert "ValueError" in result.error

    def test_run_tests_sync(self):
        """Test synchronous test execution."""
        code = "def add(a, b): return a + b"
        test_cases = [{"input": [1, 2], "output": 3}]

        result = run_tests_sync(code, "add", test_cases)

        assert result.success is True

    def test_run_tests_sync_timeout(self):
        """Test synchronous test execution with timeout."""
        code = """
def infinite():
    while True:
        pass
"""
        test_cases = [{"input": [], "output": 1}]

        result = run_tests_sync(code, "infinite", test_cases, timeout_seconds=1.0)

        assert result.success is False
        # Either timed out or had syntax/execution error
        assert result.timed_out is True or result.error != ""


class TestSandboxSecurity:
    """Tests for sandbox security features."""

    @pytest.fixture
    def sandbox(self):
        return Sandbox(timeout_seconds=5.0)

    @pytest.mark.asyncio
    async def test_import_allowed(self, sandbox):
        """Test that basic imports work."""
        code = """
import math
result = math.sqrt(16)
print(result)
"""
        result = await sandbox.execute(code)

        assert result.success is True
        assert "4" in result.output

    @pytest.mark.asyncio
    async def test_no_network_implicit(self, sandbox):
        """Test that network operations might fail or be slow."""
        # Note: We don't explicitly block network, but subprocess isolation
        # and timeouts provide some protection
        code = """
try:
    import urllib.request
    # This should work but external URLs might timeout
    print("urllib imported")
except Exception as e:
    print(f"Error: {e}")
"""
        result = await sandbox.execute(code)

        # Should at least complete (even if network fails)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_isolated_environment(self, sandbox):
        """Test that environment is isolated."""
        code = """
import os
# Should have minimal environment
env_keys = list(os.environ.keys())
print(f"Env keys: {len(env_keys)}")
"""
        result = await sandbox.execute(code)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_recursion_limit(self, sandbox):
        """Test that recursion is limited."""
        code = """
def recurse(n):
    return recurse(n + 1)

try:
    recurse(0)
except RecursionError:
    print("RecursionError caught")
"""
        result = await sandbox.execute(code)

        assert result.success is True
        assert "RecursionError" in result.output

    @pytest.mark.asyncio
    async def test_memory_intensive_operation(self, sandbox):
        """Test handling of memory-intensive operations."""
        # Note: Memory limits aren't strictly enforced, but this tests
        # that the sandbox handles large allocations gracefully
        code = """
try:
    # Try to allocate a lot of memory
    big_list = [0] * (10 ** 6)  # 1 million integers
    print(f"Allocated {len(big_list)} elements")
except MemoryError:
    print("MemoryError caught")
"""
        result = await sandbox.execute(code)

        # Should complete one way or another
        assert result.output != "" or result.error != ""
