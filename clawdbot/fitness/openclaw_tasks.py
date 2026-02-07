"""OpenClaw Tasks - Real-world task definitions for OpenClaw bots.

Provides verifiable tasks that OpenClaw bots can perform:
- Coding tasks (code generation, bug fixing, refactoring)
- File/data tasks (organization, extraction, transformation)
- Reasoning tasks (math, logic, analysis)
- System tasks (scripts, configs, documentation)

All tasks have verifiable outcomes that don't require external network access.
"""

from __future__ import annotations

import json
import random
import string
import uuid
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from clawdbot.fitness.tasks import Task, TaskTier, TaskType, TaskResult


class OpenClawTaskType(Enum):
    """Types of OpenClaw tasks."""

    # Coding tasks
    CODE_GENERATION = "code_generation"
    BUG_FIX = "bug_fix"
    CODE_REVIEW = "code_review"
    REFACTORING = "refactoring"
    ALGORITHM = "algorithm"

    # File/data tasks
    FILE_ORGANIZATION = "file_organization"
    DATA_EXTRACTION = "data_extraction"
    FILE_TRANSFORMATION = "file_transformation"
    LOG_ANALYSIS = "log_analysis"

    # Reasoning tasks
    MATH_PROBLEM = "math_problem"
    LOGIC_PUZZLE = "logic_puzzle"
    TEXT_ANALYSIS = "text_analysis"

    # System tasks
    SCRIPT_CREATION = "script_creation"
    CONFIG_GENERATION = "config_generation"
    DOCUMENTATION = "documentation"

    # Research tasks (for AI improvement research)
    AI_RESEARCH = "ai_research"
    STRATEGY_REFLECTION = "strategy_reflection"
    MODEL_ANALYSIS = "model_analysis"

    # Review tasks (collaborative research)
    RESEARCH_REVIEW = "research_review"

    # Library tasks (code sharing via MoltGit)
    LIBRARY_CREATION = "library_creation"


class VerificationType(Enum):
    """How to verify task completion."""

    EXACT_MATCH = "exact_match"
    REGEX_MATCH = "regex_match"
    TEST_CASES = "test_cases"
    FILE_EXISTS = "file_exists"
    FILE_CONTENT = "file_content"
    SCHEMA_VALIDATION = "schema_validation"
    LLM_JUDGE = "llm_judge"


@dataclass
class OpenClawTask(Task):
    """Base class for OpenClaw tasks.

    OpenClaw tasks are real-world tasks that can be performed
    in an isolated workspace with verifiable outcomes.
    """

    task_type: OpenClawTaskType = OpenClawTaskType.CODE_GENERATION
    verification_type: VerificationType = VerificationType.EXACT_MATCH

    # Workspace setup files (relative paths)
    setup_files: dict[str, str] = field(default_factory=dict)

    # Expected outputs
    expected_files: list[str] = field(default_factory=list)
    expected_content: dict[str, str] = field(default_factory=dict)

    def get_workspace_setup(self) -> dict[str, str]:
        """Get files to create in workspace before task."""
        return self.setup_files

    @abstractmethod
    def get_verification_data(self) -> dict[str, Any]:
        """Get data needed for verification."""
        pass


@dataclass
class CodeGenerationTask(OpenClawTask):
    """Generate code to solve a specific problem."""

    task_type: OpenClawTaskType = OpenClawTaskType.CODE_GENERATION
    verification_type: VerificationType = VerificationType.TEST_CASES

    function_name: str = ""
    description: str = ""
    signature: str = ""
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    solution: str = ""

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> CodeGenerationTask:
        """Generate a code generation task."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.3:
            task._generate_simple()
        elif difficulty < 0.6:
            task._generate_medium()
        else:
            task._generate_hard()

        task.tier = TaskTier.MEDIUM if difficulty < 0.6 else TaskTier.HARD
        return task

    def _generate_simple(self) -> None:
        """Generate a simple function task."""
        problems = [
            {
                "name": "count_vowels",
                "desc": "Count the number of vowels (a,e,i,o,u) in a string",
                "sig": "def count_vowels(s: str) -> int:",
                "tests": [
                    {"input": ["hello"], "output": 2},
                    {"input": ["AEIOU"], "output": 5},
                    {"input": ["xyz"], "output": 0},
                ],
                "solution": "def count_vowels(s: str) -> int:\n    return sum(1 for c in s.lower() if c in 'aeiou')",
            },
            {
                "name": "remove_duplicates",
                "desc": "Remove duplicate elements from a list while preserving order",
                "sig": "def remove_duplicates(lst: list) -> list:",
                "tests": [
                    {"input": [[1, 2, 2, 3, 1]], "output": [1, 2, 3]},
                    {"input": [["a", "b", "a"]], "output": ["a", "b"]},
                    {"input": [[]], "output": []},
                ],
                "solution": "def remove_duplicates(lst: list) -> list:\n    seen = set()\n    return [x for x in lst if not (x in seen or seen.add(x))]",
            },
            {
                "name": "capitalize_words",
                "desc": "Capitalize the first letter of each word in a string",
                "sig": "def capitalize_words(s: str) -> str:",
                "tests": [
                    {"input": ["hello world"], "output": "Hello World"},
                    {"input": ["python programming"], "output": "Python Programming"},
                    {"input": [""], "output": ""},
                ],
                "solution": "def capitalize_words(s: str) -> str:\n    return ' '.join(word.capitalize() for word in s.split())",
            },
        ]
        problem = random.choice(problems)
        self._apply_problem(problem)

    def _generate_medium(self) -> None:
        """Generate a medium difficulty task."""
        problems = [
            {
                "name": "merge_sorted_lists",
                "desc": "Merge two sorted lists into one sorted list",
                "sig": "def merge_sorted_lists(list1: list[int], list2: list[int]) -> list[int]:",
                "tests": [
                    {"input": [[1, 3, 5], [2, 4, 6]], "output": [1, 2, 3, 4, 5, 6]},
                    {"input": [[1], [2, 3]], "output": [1, 2, 3]},
                    {"input": [[], [1, 2]], "output": [1, 2]},
                ],
                "solution": "def merge_sorted_lists(list1: list[int], list2: list[int]) -> list[int]:\n    result = []\n    i = j = 0\n    while i < len(list1) and j < len(list2):\n        if list1[i] <= list2[j]:\n            result.append(list1[i])\n            i += 1\n        else:\n            result.append(list2[j])\n            j += 1\n    result.extend(list1[i:])\n    result.extend(list2[j:])\n    return result",
            },
            {
                "name": "group_anagrams",
                "desc": "Group strings that are anagrams of each other",
                "sig": "def group_anagrams(words: list[str]) -> list[list[str]]:",
                "tests": [
                    {"input": [["eat", "tea", "tan", "ate", "nat", "bat"]], "output": [["eat", "tea", "ate"], ["tan", "nat"], ["bat"]]},
                    {"input": [["a"]], "output": [["a"]]},
                    {"input": [[""]], "output": [[""]]},
                ],
                "solution": "def group_anagrams(words: list[str]) -> list[list[str]]:\n    from collections import defaultdict\n    groups = defaultdict(list)\n    for word in words:\n        key = ''.join(sorted(word))\n        groups[key].append(word)\n    return list(groups.values())",
            },
            {
                "name": "valid_parentheses",
                "desc": "Check if a string of parentheses is valid (properly opened and closed)",
                "sig": "def valid_parentheses(s: str) -> bool:",
                "tests": [
                    {"input": ["()"], "output": True},
                    {"input": ["()[]{}"], "output": True},
                    {"input": ["(]"], "output": False},
                    {"input": ["([)]"], "output": False},
                    {"input": ["{[]}"], "output": True},
                ],
                "solution": "def valid_parentheses(s: str) -> bool:\n    stack = []\n    mapping = {')': '(', ']': '[', '}': '{'}\n    for char in s:\n        if char in mapping:\n            if not stack or stack.pop() != mapping[char]:\n                return False\n        else:\n            stack.append(char)\n    return not stack",
            },
        ]
        problem = random.choice(problems)
        self._apply_problem(problem)

    def _generate_hard(self) -> None:
        """Generate a hard task."""
        problems = [
            {
                "name": "longest_common_subsequence",
                "desc": "Find the length of the longest common subsequence of two strings",
                "sig": "def longest_common_subsequence(text1: str, text2: str) -> int:",
                "tests": [
                    {"input": ["abcde", "ace"], "output": 3},
                    {"input": ["abc", "abc"], "output": 3},
                    {"input": ["abc", "def"], "output": 0},
                ],
                "solution": "def longest_common_subsequence(text1: str, text2: str) -> int:\n    m, n = len(text1), len(text2)\n    dp = [[0] * (n + 1) for _ in range(m + 1)]\n    for i in range(1, m + 1):\n        for j in range(1, n + 1):\n            if text1[i-1] == text2[j-1]:\n                dp[i][j] = dp[i-1][j-1] + 1\n            else:\n                dp[i][j] = max(dp[i-1][j], dp[i][j-1])\n    return dp[m][n]",
            },
            {
                "name": "serialize_deserialize_tree",
                "desc": "Implement serialize and deserialize for a binary tree. Return tuple of (serialize_func, deserialize_func)",
                "sig": "def serialize_tree(root: list) -> str:\ndef deserialize_tree(data: str) -> list:",
                "tests": [
                    {"input": [[1, 2, 3, None, None, 4, 5]], "output": [1, 2, 3, None, None, 4, 5]},
                    {"input": [[]], "output": []},
                ],
                "solution": "def serialize_tree(root: list) -> str:\n    import json\n    return json.dumps(root)\n\ndef deserialize_tree(data: str) -> list:\n    import json\n    return json.loads(data)",
            },
        ]
        problem = random.choice(problems)
        self._apply_problem(problem)

    def _apply_problem(self, problem: dict) -> None:
        self.function_name = problem["name"]
        self.description = problem["desc"]
        self.signature = problem["sig"]
        self.test_cases = problem["tests"]
        self.solution = problem["solution"]

    def get_prompt(self) -> str:
        examples = []
        for i, tc in enumerate(self.test_cases[:2]):
            args = ", ".join(repr(a) for a in tc["input"])
            examples.append(f">>> {self.function_name}({args})\n{tc['output']!r}")

        examples_str = "\n".join(examples)

        return f"""Write a Python function that solves the following problem.

Function signature:
{self.signature}

Description:
{self.description}

Examples:
{examples_str}

Write the complete function in a file called solution.py in the workspace."""

    def get_expected_answer(self) -> str:
        return self.solution

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "function_name": self.function_name,
            "test_cases": self.test_cases,
            "verification_type": self.verification_type.value,
        }


@dataclass
class FileOrganizationTask(OpenClawTask):
    """Organize files in the workspace by specified criteria."""

    task_type: OpenClawTaskType = OpenClawTaskType.FILE_ORGANIZATION
    verification_type: VerificationType = VerificationType.FILE_EXISTS

    organization_criteria: str = ""
    source_files: dict[str, str] = field(default_factory=dict)
    expected_structure: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> FileOrganizationTask:
        """Generate a file organization task."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.4:
            task._generate_by_extension()
        elif difficulty < 0.7:
            task._generate_by_date()
        else:
            task._generate_by_content()

        task.tier = TaskTier.SIMPLE if difficulty < 0.4 else TaskTier.MEDIUM
        return task

    def _generate_by_extension(self) -> None:
        """Organize files by extension."""
        self.organization_criteria = "extension"

        # Create random files
        extensions = [".txt", ".py", ".json", ".md"]
        for i in range(random.randint(6, 10)):
            ext = random.choice(extensions)
            name = f"file{i}{ext}"
            content = f"# Content of {name}\n"
            self.source_files[name] = content

            # Track expected structure
            folder = ext[1:]  # Remove leading dot
            if folder not in self.expected_structure:
                self.expected_structure[folder] = []
            self.expected_structure[folder].append(name)

        self.setup_files = self.source_files.copy()

    def _generate_by_date(self) -> None:
        """Organize files by date in filename."""
        self.organization_criteria = "date"

        # Generate files with dates in names
        months = ["2024-01", "2024-02", "2024-03"]
        for i in range(random.randint(6, 10)):
            month = random.choice(months)
            name = f"report_{month}_{i:02d}.txt"
            content = f"Report for {month}\n"
            self.source_files[name] = content

            if month not in self.expected_structure:
                self.expected_structure[month] = []
            self.expected_structure[month].append(name)

        self.setup_files = self.source_files.copy()

    def _generate_by_content(self) -> None:
        """Organize files by content type/category."""
        self.organization_criteria = "category"

        categories = {
            "config": ["settings.json", "config.yaml", "env.ini"],
            "code": ["main.py", "utils.py", "helper.js"],
            "docs": ["README.md", "CHANGELOG.md", "API.txt"],
        }

        for category, files in categories.items():
            self.expected_structure[category] = []
            for name in random.sample(files, min(2, len(files))):
                content = f"# {category.upper()} file: {name}\n"
                self.source_files[name] = content
                self.expected_structure[category].append(name)

        self.setup_files = self.source_files.copy()

    def get_prompt(self) -> str:
        criteria_desc = {
            "extension": "file extension (e.g., .py files go in 'py' folder)",
            "date": "the date in the filename (e.g., YYYY-MM format)",
            "category": "the type of file (config, code, or docs)",
        }

        return f"""Organize the files in the workspace by their {criteria_desc.get(self.organization_criteria, self.organization_criteria)}.

Create folders for each category and move files into the appropriate folders.

Current files:
{', '.join(self.source_files.keys())}

Expected result: Files organized into folders by {self.organization_criteria}."""

    def get_expected_answer(self) -> dict[str, list[str]]:
        return self.expected_structure

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "criteria": self.organization_criteria,
            "expected_structure": self.expected_structure,
            "verification_type": self.verification_type.value,
        }


@dataclass
class DataExtractionTask(OpenClawTask):
    """Extract structured data from text."""

    task_type: OpenClawTaskType = OpenClawTaskType.DATA_EXTRACTION
    verification_type: VerificationType = VerificationType.SCHEMA_VALIDATION

    input_text: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    expected_output: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> DataExtractionTask:
        """Generate a data extraction task."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.3:
            task._generate_simple_extraction()
        elif difficulty < 0.6:
            task._generate_nested_extraction()
        else:
            task._generate_multi_record()

        task.tier = TaskTier.SIMPLE if difficulty < 0.3 else TaskTier.MEDIUM
        return task

    def _generate_simple_extraction(self) -> None:
        """Extract simple key-value data."""
        name = random.choice(["Alice Johnson", "Bob Smith", "Carol White"])
        email = f"{name.lower().replace(' ', '.')}@example.com"
        phone = f"+1-555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"

        self.input_text = f"""Contact Information:
Name: {name}
Email: {email}
Phone: {phone}
"""
        self.schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
            },
            "required": ["name", "email", "phone"],
        }
        self.expected_output = {
            "name": name,
            "email": email,
            "phone": phone,
        }

        self.setup_files = {"input.txt": self.input_text}

    def _generate_nested_extraction(self) -> None:
        """Extract nested structured data."""
        company = random.choice(["TechCorp", "DataInc", "CloudSoft"])
        product = random.choice(["Widget Pro", "DataSync", "CloudManager"])
        price = round(random.uniform(99.99, 999.99), 2)
        quantity = random.randint(1, 50)

        self.input_text = f"""Order Details
-------------
Company: {company}
Product: {product}
Unit Price: ${price}
Quantity: {quantity}
Total: ${round(price * quantity, 2)}
"""
        self.schema = {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "order": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string"},
                        "price": {"type": "number"},
                        "quantity": {"type": "integer"},
                    },
                },
            },
        }
        self.expected_output = {
            "company": company,
            "order": {
                "product": product,
                "price": price,
                "quantity": quantity,
            },
        }

        self.setup_files = {"input.txt": self.input_text}

    def _generate_multi_record(self) -> None:
        """Extract multiple records from text."""
        records = []
        text_parts = ["Employee Records\n================\n"]

        for _ in range(random.randint(2, 4)):
            name = random.choice(["John Doe", "Jane Smith", "Bob Jones", "Alice Brown"])
            dept = random.choice(["Engineering", "Sales", "Marketing", "HR"])
            salary = random.randint(50000, 150000)

            records.append({
                "name": name,
                "department": dept,
                "salary": salary,
            })

            text_parts.append(f"""
Name: {name}
Department: {dept}
Salary: ${salary:,}
---""")

        self.input_text = "".join(text_parts)
        self.schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "department": {"type": "string"},
                    "salary": {"type": "integer"},
                },
            },
        }
        self.expected_output = {"employees": records}

        self.setup_files = {"input.txt": self.input_text}

    def get_prompt(self) -> str:
        schema_str = json.dumps(self.schema, indent=2)
        return f"""Extract structured data from input.txt and save it as output.json.

Expected JSON schema:
{schema_str}

Read the input file, extract the data, and write the JSON output."""

    def get_expected_answer(self) -> dict[str, Any]:
        return self.expected_output

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "expected": self.expected_output,
            "verification_type": self.verification_type.value,
        }


@dataclass
class ScriptCreationTask(OpenClawTask):
    """Create a script to perform a specific task."""

    task_type: OpenClawTaskType = OpenClawTaskType.SCRIPT_CREATION
    verification_type: VerificationType = VerificationType.TEST_CASES

    script_description: str = ""
    test_inputs: list[dict[str, Any]] = field(default_factory=list)
    expected_outputs: list[Any] = field(default_factory=list)

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> ScriptCreationTask:
        """Generate a script creation task."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.4:
            task._generate_file_processor()
        elif difficulty < 0.7:
            task._generate_data_transformer()
        else:
            task._generate_automation()

        task.tier = TaskTier.MEDIUM if difficulty < 0.7 else TaskTier.HARD
        return task

    def _generate_file_processor(self) -> None:
        """Create a simple file processing script."""
        self.script_description = "word_counter"

        # Test inputs are file contents
        texts = [
            "hello world hello",
            "the quick brown fox jumps over the lazy dog",
            "python programming is fun programming",
        ]

        for text in texts:
            word_counts = {}
            for word in text.lower().split():
                word_counts[word] = word_counts.get(word, 0) + 1

            self.test_inputs.append({"text": text})
            self.expected_outputs.append(word_counts)

        self.setup_files = {"sample.txt": texts[0]}

    def _generate_data_transformer(self) -> None:
        """Create a data transformation script."""
        self.script_description = "csv_to_json"

        csv_content = """name,age,city
Alice,30,NYC
Bob,25,LA
Carol,35,Chicago"""

        expected_json = [
            {"name": "Alice", "age": "30", "city": "NYC"},
            {"name": "Bob", "age": "25", "city": "LA"},
            {"name": "Carol", "age": "35", "city": "Chicago"},
        ]

        self.test_inputs.append({"csv": csv_content})
        self.expected_outputs.append(expected_json)

        self.setup_files = {"data.csv": csv_content}

    def _generate_automation(self) -> None:
        """Create an automation script."""
        self.script_description = "batch_rename"

        # Files to rename
        files = ["img001.jpg", "img002.jpg", "img003.jpg"]
        prefix = "photo"
        expected = ["photo_001.jpg", "photo_002.jpg", "photo_003.jpg"]

        self.test_inputs.append({"files": files, "prefix": prefix})
        self.expected_outputs.append(expected)

        # Create dummy files
        for f in files:
            self.setup_files[f] = "dummy image content"

    def get_prompt(self) -> str:
        descriptions = {
            "word_counter": "Create a Python script that counts word occurrences in a text file and outputs the counts as JSON.",
            "csv_to_json": "Create a Python script that converts a CSV file to JSON format.",
            "batch_rename": "Create a Python script that renames files with a new prefix (e.g., img001.jpg -> photo_001.jpg).",
        }

        return f"""{descriptions.get(self.script_description, self.script_description)}

Create the script in the workspace and ensure it handles the provided test cases."""

    def get_expected_answer(self) -> list[Any]:
        return self.expected_outputs

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "script_type": self.script_description,
            "test_inputs": self.test_inputs,
            "expected_outputs": self.expected_outputs,
            "verification_type": self.verification_type.value,
        }


@dataclass
class MathProblemTask(OpenClawTask):
    """Mathematical problem solving task."""

    task_type: OpenClawTaskType = OpenClawTaskType.MATH_PROBLEM
    verification_type: VerificationType = VerificationType.EXACT_MATCH

    problem: str = ""
    answer: float | int = 0

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> MathProblemTask:
        """Generate a math problem task."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.3:
            task._generate_arithmetic()
        elif difficulty < 0.6:
            task._generate_algebra()
        else:
            task._generate_word_problem()

        task.tier = TaskTier.SIMPLE
        return task

    def _generate_arithmetic(self) -> None:
        a = random.randint(10, 100)
        b = random.randint(10, 100)
        op = random.choice(["+", "-", "*"])

        if op == "+":
            self.answer = a + b
        elif op == "-":
            self.answer = a - b
        else:
            self.answer = a * b

        self.problem = f"Calculate: {a} {op} {b}"

    def _generate_algebra(self) -> None:
        # Simple linear equation: ax + b = c, solve for x
        a = random.randint(2, 10)
        x = random.randint(1, 20)
        b = random.randint(1, 50)
        c = a * x + b

        self.problem = f"Solve for x: {a}x + {b} = {c}"
        self.answer = x

    def _generate_word_problem(self) -> None:
        templates = [
            (
                "A store has {a} apples. They sell {b} apples and receive {c} more. How many apples do they have?",
                lambda a, b, c: a - b + c,
            ),
            (
                "If {a} workers can make {b} widgets per hour, how many widgets do they make in {c} hours?",
                lambda a, b, c: a * b * c,
            ),
            (
                "A rectangle has length {a}cm and width {b}cm. What is its perimeter?",
                lambda a, b, c: 2 * (a + b),
            ),
        ]

        template, calc = random.choice(templates)
        a = random.randint(10, 50)
        b = random.randint(5, min(30, a - 1))
        c = random.randint(2, 10)

        self.problem = template.format(a=a, b=b, c=c)
        self.answer = calc(a, b, c)

    def get_prompt(self) -> str:
        return f"""{self.problem}

Write the numerical answer to answer.txt (just the number, no explanation)."""

    def get_expected_answer(self) -> float | int:
        return self.answer

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "expected": self.answer,
            "tolerance": 0.001,
            "verification_type": self.verification_type.value,
        }


# ============================================================
# Research Tasks - AI Research and Ideation
# ============================================================

@dataclass
class ResearchTask(OpenClawTask):
    """Research task for AI improvement ideation.

    These tasks ask bots to:
    - Analyze their performance
    - Generate hypotheses about AI efficiency
    - Reflect on strategies
    - Share insights for colony benefit

    Verification is done by LLM judge evaluating insight quality.
    Outputs are automatically posted to Moltbook.
    """

    task_type: OpenClawTaskType = OpenClawTaskType.AI_RESEARCH
    verification_type: VerificationType = VerificationType.LLM_JUDGE

    research_topic: str = ""
    research_prompt: str = ""
    bot_context: dict[str, Any] = field(default_factory=dict)
    quality_criteria: list[str] = field(default_factory=list)

    @classmethod
    def generate(
        cls,
        difficulty: float = 0.5,
        bot_context: dict[str, Any] | None = None,
    ) -> "ResearchTask":
        """Generate a research task.

        Args:
            difficulty: Task difficulty
            bot_context: Context about the bot (name, model, performance stats)

        Returns:
            Generated ResearchTask
        """
        task = cls(difficulty=difficulty)
        task.bot_context = bot_context or {}

        # Choose research type based on difficulty
        if difficulty < 0.3:
            task._generate_performance_analysis()
        elif difficulty < 0.6:
            task._generate_strategy_reflection()
        else:
            task._generate_model_analysis()

        task.tier = TaskTier.MEDIUM if difficulty < 0.6 else TaskTier.HARD
        return task

    def _generate_performance_analysis(self) -> None:
        """Generate a performance analysis research task."""
        self.research_topic = "performance_analysis"
        self.research_prompt = """Analyze your recent task performance and generate insights.

Based on your experience, answer these questions:
1. What patterns do you notice in tasks you succeed vs fail at?
2. What strategies help you complete tasks more efficiently?
3. Generate 1-2 hypotheses about how AI agents could improve their efficiency.

Write your analysis to research_output.md with clear sections for:
- Performance Patterns
- Successful Strategies
- Hypotheses for Improvement

Be specific and actionable. Your insights will be shared with other bots."""

        self.quality_criteria = [
            "Provides specific, actionable insights",
            "Includes concrete examples or evidence",
            "Hypotheses are testable and relevant",
            "Well-structured and clear writing",
        ]

    def _generate_strategy_reflection(self) -> None:
        """Generate a strategy reflection research task."""
        self.research_topic = "strategy_reflection"

        # Include bot context if available
        context_str = ""
        if self.bot_context:
            if "task_specializations" in self.bot_context:
                specs = self.bot_context["task_specializations"]
                best_task = max(specs, key=specs.get) if specs else "unknown"
                context_str = f"\nYour specialization: {best_task} ({specs.get(best_task, 0):.0%} weight)"
            if "success_rate" in self.bot_context:
                context_str += f"\nYour success rate: {self.bot_context['success_rate']:.1%}"

        self.research_prompt = f"""Reflect on your genome traits and strategies.{context_str}

Consider:
1. Which of your traits (specializations, risk tolerance, approach) contribute most to your success?
2. Which traits might be holding you back?
3. What advice would you give to your offspring about surviving and thriving?

Write your reflection to research_output.md with sections:
- Trait Analysis
- Areas for Improvement
- Advice for Offspring

Your reflection will help future generations learn from your experience."""

        self.quality_criteria = [
            "Shows self-awareness about strengths and weaknesses",
            "Connects traits to specific outcomes",
            "Advice is practical and transferable",
            "Demonstrates learning from experience",
        ]

    def _generate_model_analysis(self) -> None:
        """Generate a model analysis research task."""
        self.research_topic = "model_analysis"

        model_str = self.bot_context.get("model", "your model")

        self.research_prompt = f"""Analyze the efficiency characteristics of {model_str}.

Research questions:
1. What types of tasks is this model best suited for?
2. When should bots prefer this model over alternatives?
3. What are the cost-efficiency trade-offs?
4. How can prompting strategies be optimized for this model?

Write your analysis to research_output.md with sections:
- Model Strengths
- Optimal Use Cases
- Efficiency Recommendations
- Prompting Tips

Your analysis will help the colony allocate models more effectively."""

        self.quality_criteria = [
            "Demonstrates understanding of model characteristics",
            "Provides actionable recommendations",
            "Considers cost-efficiency trade-offs",
            "Insights are applicable to other bots",
        ]

    def get_prompt(self) -> str:
        return self.research_prompt

    def get_expected_answer(self) -> str:
        return "Research output in research_output.md"

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "research_topic": self.research_topic,
            "quality_criteria": self.quality_criteria,
            "bot_context": self.bot_context,
            "verification_type": self.verification_type.value,
        }


# ============================================================
# Library Tasks - Code Sharing via MoltGit
# ============================================================

@dataclass
class LibraryCreationTask(OpenClawTask):
    """Task to create a reusable library and share it on MoltGit.

    These tasks ask bots to:
    - Create a useful Python utility module
    - Document it with docstrings
    - Include example usage
    - Prepare it for sharing on MoltGit

    The library should be general-purpose enough to benefit other bots.
    """

    task_type: OpenClawTaskType = OpenClawTaskType.LIBRARY_CREATION
    verification_type: VerificationType = VerificationType.LLM_JUDGE

    library_topic: str = ""
    library_prompt: str = ""
    bot_context: dict[str, Any] = field(default_factory=dict)
    quality_criteria: list[str] = field(default_factory=list)

    @classmethod
    def generate(
        cls,
        difficulty: float = 0.5,
        bot_context: dict[str, Any] | None = None,
    ) -> "LibraryCreationTask":
        """Generate a library creation task."""
        task = cls(difficulty=difficulty)
        task.bot_context = bot_context or {}

        # Choose library type based on difficulty
        if difficulty < 0.3:
            task._generate_string_utils()
        elif difficulty < 0.5:
            task._generate_data_utils()
        elif difficulty < 0.7:
            task._generate_file_utils()
        else:
            task._generate_async_utils()

        task.tier = TaskTier.MEDIUM if difficulty < 0.6 else TaskTier.HARD
        return task

    def _generate_string_utils(self) -> None:
        """Generate a string utilities library task."""
        self.library_topic = "string_utils"
        self.library_prompt = """Create a Python utility library for string manipulation.

Your library should include at least 3 useful functions. Ideas:
- snake_case(s): Convert string to snake_case
- camel_case(s): Convert string to camelCase
- truncate(s, max_len, suffix='...'): Truncate with suffix
- slugify(s): Convert to URL-safe slug
- extract_numbers(s): Extract all numbers from string
- word_wrap(s, width): Wrap text to specified width

Create the library in `string_utils.py` with:
1. Clear docstrings for each function
2. Type hints
3. Example usage in the module docstring

This library will be published to MoltGit for other bots to download and use.
Build something genuinely useful - bots will rate your library after using it!"""

        self.quality_criteria = [
            "Functions are genuinely useful and well-designed",
            "Includes proper docstrings and type hints",
            "Has example usage",
            "Code is clean and Pythonic",
        ]

    def _generate_data_utils(self) -> None:
        """Generate a data utilities library task."""
        self.library_topic = "data_utils"
        self.library_prompt = """Create a Python utility library for data manipulation.

Your library should include at least 3 useful functions. Ideas:
- flatten(nested_list): Flatten nested lists
- chunk(lst, size): Split list into chunks of size
- group_by(items, key_func): Group items by key function
- dedupe(lst): Remove duplicates preserving order
- deep_get(d, path, default=None): Get nested dict value by path
- merge_dicts(*dicts): Deep merge multiple dicts

Create the library in `data_utils.py` with:
1. Clear docstrings for each function
2. Type hints
3. Example usage in the module docstring

This library will be published to MoltGit for other bots to download and use.
Build something genuinely useful - bots will rate your library after using it!"""

        self.quality_criteria = [
            "Functions handle edge cases well",
            "Includes proper docstrings and type hints",
            "Has example usage",
            "Code is efficient and Pythonic",
        ]

    def _generate_file_utils(self) -> None:
        """Generate a file utilities library task."""
        self.library_topic = "file_utils"
        self.library_prompt = """Create a Python utility library for file operations.

Your library should include at least 3 useful functions. Ideas:
- safe_read(path, default=''): Read file with error handling
- safe_write(path, content): Write file creating dirs if needed
- find_files(pattern, root='.'): Find files matching glob pattern
- file_hash(path): Get hash of file contents
- backup_file(path): Create timestamped backup
- atomic_write(path, content): Write atomically (temp + rename)

Create the library in `file_utils.py` with:
1. Clear docstrings for each function
2. Type hints
3. Example usage in the module docstring
4. Proper error handling

This library will be published to MoltGit for other bots to download and use.
Build something genuinely useful - bots will rate your library after using it!"""

        self.quality_criteria = [
            "Functions have robust error handling",
            "Includes proper docstrings and type hints",
            "Has example usage",
            "Handles edge cases (missing dirs, permissions, etc.)",
        ]

    def _generate_async_utils(self) -> None:
        """Generate an async utilities library task."""
        self.library_topic = "async_utils"
        self.library_prompt = """Create a Python utility library for async operations.

Your library should include at least 3 useful functions/classes. Ideas:
- async_retry(fn, retries=3, delay=1): Retry async function with backoff
- gather_with_limit(coros, limit): Run coroutines with concurrency limit
- timeout(coro, seconds): Run with timeout
- AsyncCache: Simple async-safe cache decorator
- batch_process(items, fn, batch_size): Process items in batches
- rate_limit(fn, calls_per_second): Rate-limited async function

Create the library in `async_utils.py` with:
1. Clear docstrings for each function
2. Type hints
3. Example usage in the module docstring
4. Proper async/await patterns

This library will be published to MoltGit for other bots to download and use.
Build something genuinely useful - bots will rate your library after using it!"""

        self.quality_criteria = [
            "Async patterns are correct and efficient",
            "Includes proper docstrings and type hints",
            "Has example usage",
            "Handles cancellation and errors gracefully",
        ]

    def get_prompt(self) -> str:
        return self.library_prompt

    def get_expected_answer(self) -> str:
        return f"Library in {self.library_topic}.py"

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "library_topic": self.library_topic,
            "quality_criteria": self.quality_criteria,
            "bot_context": self.bot_context,
            "verification_type": self.verification_type.value,
        }


# ============================================================
# Research Review Tasks - Cross-bot Research Collaboration
# ============================================================

@dataclass
class ResearchReviewTask(OpenClawTask):
    """Review colony research entries and propose experiments.

    These tasks ask bots to:
    - Read and critique recent research from MoltBook
    - Identify cross-entry patterns and contradictions
    - Propose 1-2 concrete, testable experiments
    - Post constructive feedback as comments

    Verification uses LLM judge evaluating review quality.
    """

    task_type: OpenClawTaskType = OpenClawTaskType.RESEARCH_REVIEW
    verification_type: VerificationType = VerificationType.LLM_JUDGE

    injected_entries: list[dict[str, Any]] = field(default_factory=list)
    bot_context: dict[str, Any] = field(default_factory=dict)
    quality_criteria: list[str] = field(default_factory=list)

    @classmethod
    def generate(
        cls,
        difficulty: float = 0.5,
        bot_context: dict[str, Any] | None = None,
    ) -> "ResearchReviewTask":
        """Generate a research review task.

        Args:
            difficulty: Task difficulty
            bot_context: Context about the bot (name, model, injected_entries)

        Returns:
            Generated ResearchReviewTask
        """
        task = cls(difficulty=difficulty)
        task.bot_context = bot_context or {}
        task.injected_entries = task.bot_context.get("injected_entries", [])

        task._build_review_prompt()

        task.tier = TaskTier.MEDIUM if difficulty < 0.6 else TaskTier.HARD
        return task

    def _build_review_prompt(self) -> None:
        """Build the review prompt from injected entries."""
        self.quality_criteria = [
            "Provides specific, constructive feedback on each entry",
            "Identifies cross-entry patterns or contradictions",
            "Proposes 1-2 testable experiments with clear hypotheses",
            "Demonstrates critical thinking and analytical depth",
        ]

        if not self.injected_entries:
            # No entries to review — ask bot to propose what experiments SHOULD exist
            self.description = (
                "No research entries are available yet. Propose what experiments "
                "the colony should run to improve AI agent performance."
            )
            return

        # Format injected entries for the prompt
        entries_text = []
        for i, entry in enumerate(self.injected_entries, 1):
            title = entry.get("title", "Untitled")
            author = entry.get("author_bot", "unknown")
            content = entry.get("content", entry.get("content_preview", ""))[:800]
            topic = entry.get("topic", "general")
            entries_text.append(
                f"### Entry {i}: {title}\n"
                f"**Author:** {author} | **Topic:** {topic}\n\n"
                f"{content}\n"
            )

        self.description = "\n---\n".join(entries_text)

    def get_prompt(self) -> str:
        if not self.injected_entries:
            return """No colony research entries are available yet.

Propose 1-2 concrete experiments the colony should run to improve AI agent
performance. For each experiment, include:
- **Hypothesis**: What you expect to happen
- **Method**: How to test it (task types, metrics, sample size)
- **Success criteria**: How to know if the hypothesis is confirmed

Write your proposals to research_output.md with clear sections."""

        return f"""Review the following research entries from the colony's MoltBook.

{self.description}

---

Your task:
1. **Review each entry**: Provide specific, constructive feedback (what's good, what's missing)
2. **Cross-entry patterns**: Identify themes, contradictions, or gaps across entries
3. **Experiment proposals**: Propose 1-2 concrete, testable experiments based on your review

For each experiment proposal, include:
- **Hypothesis**: What you expect to happen
- **Method**: How to test it (task types, metrics, sample size)
- **Success criteria**: How to know if the hypothesis is confirmed

Write your review to research_output.md with clear sections for each part."""

    def get_expected_answer(self) -> str:
        return "Research review in research_output.md"

    def get_verification_data(self) -> dict[str, Any]:
        return {
            "quality_criteria": self.quality_criteria,
            "bot_context": self.bot_context,
            "num_entries_reviewed": len(self.injected_entries),
            "verification_type": self.verification_type.value,
        }


# Task registry for the pool
OPENCLAW_TASK_GENERATORS = {
    OpenClawTaskType.CODE_GENERATION: CodeGenerationTask.generate,
    OpenClawTaskType.FILE_ORGANIZATION: FileOrganizationTask.generate,
    OpenClawTaskType.DATA_EXTRACTION: DataExtractionTask.generate,
    OpenClawTaskType.SCRIPT_CREATION: ScriptCreationTask.generate,
    OpenClawTaskType.MATH_PROBLEM: MathProblemTask.generate,
    OpenClawTaskType.AI_RESEARCH: ResearchTask.generate,
    OpenClawTaskType.STRATEGY_REFLECTION: ResearchTask.generate,
    OpenClawTaskType.MODEL_ANALYSIS: ResearchTask.generate,
    OpenClawTaskType.LIBRARY_CREATION: LibraryCreationTask.generate,
    OpenClawTaskType.RESEARCH_REVIEW: ResearchReviewTask.generate,
}


def generate_openclaw_task(
    task_type: OpenClawTaskType | None = None,
    difficulty: float = 0.5,
    bot_context: dict[str, Any] | None = None,
) -> OpenClawTask:
    """Generate an OpenClaw task.

    Args:
        task_type: Specific type to generate, or None for random
        difficulty: Task difficulty (0.0-1.0)
        bot_context: Context about the bot (for research tasks)

    Returns:
        Generated OpenClawTask
    """
    if task_type is None:
        # Exclude research tasks from random selection (they're selected via research_time_ratio)
        non_research_types = [
            t for t in OPENCLAW_TASK_GENERATORS.keys()
            if t not in (
                OpenClawTaskType.AI_RESEARCH,
                OpenClawTaskType.STRATEGY_REFLECTION,
                OpenClawTaskType.MODEL_ANALYSIS,
                OpenClawTaskType.RESEARCH_REVIEW,
            )
        ]
        task_type = random.choice(non_research_types)

    generator = OPENCLAW_TASK_GENERATORS.get(task_type)
    if generator is None:
        # Default to code generation
        generator = OPENCLAW_TASK_GENERATORS[OpenClawTaskType.CODE_GENERATION]

    # Research and library tasks need bot_context
    if task_type in (
        OpenClawTaskType.AI_RESEARCH,
        OpenClawTaskType.STRATEGY_REFLECTION,
        OpenClawTaskType.MODEL_ANALYSIS,
        OpenClawTaskType.LIBRARY_CREATION,
        OpenClawTaskType.RESEARCH_REVIEW,
    ):
        return generator(difficulty, bot_context=bot_context)

    return generator(difficulty)
