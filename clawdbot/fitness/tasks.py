"""Task definitions - Verifiable tasks for evolutionary fitness."""

from __future__ import annotations

import json
import random
import string
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskTier(Enum):
    """Task difficulty tiers."""

    SIMPLE = 1  # Math, JSON extraction, logic
    MEDIUM = 2  # HumanEval, MBPP function completion
    HARD = 3  # Extended tests, algorithm challenges
    EXPERT = 4  # SWE-bench style bug fixes


class TaskType(Enum):
    """Types of tasks."""

    MATH = "math"
    JSON = "json"
    LOGIC = "logic"
    CODE = "code"
    HUMANEVAL = "humaneval"
    MBPP = "mbpp"
    ALGORITHM = "algorithm"
    SWE_LITE = "swe_lite"


@dataclass
class TaskResult:
    """Result of attempting a task."""

    task_id: str
    answer: Any
    raw_response: str
    execution_time_seconds: float
    tokens_used: int = 0
    api_cost: float = 0.0


@dataclass
class Task(ABC):
    """Base class for all tasks."""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    tier: TaskTier = TaskTier.SIMPLE
    task_type: TaskType = TaskType.MATH
    difficulty: float = 0.5  # 0.0-1.0

    @abstractmethod
    def get_prompt(self) -> str:
        """Get the prompt to present to the LLM."""
        pass

    @abstractmethod
    def get_expected_answer(self) -> Any:
        """Get the expected answer for verification."""
        pass

    @abstractmethod
    def get_verification_data(self) -> dict[str, Any]:
        """Get data needed for verification."""
        pass

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to dictionary."""
        return {
            "id": self.id,
            "tier": self.tier.value,
            "task_type": self.task_type.value,
            "difficulty": self.difficulty,
        }


@dataclass
class MathTask(Task):
    """Mathematical problem with exact answer.

    Generates arithmetic, algebra, or word problems based on difficulty.
    """

    tier: TaskTier = TaskTier.SIMPLE
    task_type: TaskType = TaskType.MATH

    expression: str = ""
    answer: float = 0.0
    word_problem: str = ""

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> MathTask:
        """Generate a math task based on difficulty.

        Args:
            difficulty: 0.0-1.0 where higher is harder
        """
        task = cls(difficulty=difficulty)

        if difficulty < 0.3:
            # Simple arithmetic
            task._generate_arithmetic()
        elif difficulty < 0.6:
            # Multi-step arithmetic
            task._generate_multi_step()
        else:
            # Word problem
            task._generate_word_problem()

        return task

    def _generate_arithmetic(self) -> None:
        """Generate simple arithmetic: a op b."""
        a = random.randint(1, 100)
        b = random.randint(1, 100)
        op = random.choice(["+", "-", "*"])

        if op == "+":
            self.answer = a + b
        elif op == "-":
            self.answer = a - b
        else:
            self.answer = a * b

        self.expression = f"{a} {op} {b}"

    def _generate_multi_step(self) -> None:
        """Generate multi-step arithmetic: (a op1 b) op2 c."""
        a = random.randint(1, 50)
        b = random.randint(1, 50)
        c = random.randint(1, 20)
        ops = random.choices(["+", "-", "*"], k=2)

        # Calculate step by step
        if ops[0] == "+":
            step1 = a + b
        elif ops[0] == "-":
            step1 = a - b
        else:
            step1 = a * b

        if ops[1] == "+":
            self.answer = step1 + c
        elif ops[1] == "-":
            self.answer = step1 - c
        else:
            self.answer = step1 * c

        self.expression = f"({a} {ops[0]} {b}) {ops[1]} {c}"

    def _generate_word_problem(self) -> None:
        """Generate a word problem."""
        templates = [
            (
                "A store has {a} apples. They sell {b} apples and then receive a shipment of {c} more. How many apples do they have?",
                lambda a, b, c: a - b + c,
            ),
            (
                "If {a} workers can complete a task in {b} hours, and each worker produces {c} units per hour, how many total units are produced?",
                lambda a, b, c: a * b * c,
            ),
            (
                "A train travels {a} miles in the first hour, {b} miles in the second hour, and {c} miles in the third hour. What is the total distance?",
                lambda a, b, c: a + b + c,
            ),
            (
                "A rectangle has length {a} and width {b}. What is its area?",
                lambda a, b, c: a * b,
            ),
            (
                "You have ${a}. You spend ${b} on food and ${c} on transport. How much do you have left?",
                lambda a, b, c: a - b - c,
            ),
        ]

        template, calc = random.choice(templates)
        a = random.randint(10, 100)
        b = random.randint(1, min(50, a - 1))  # Ensure non-negative results
        c = random.randint(1, 30)

        self.word_problem = template.format(a=a, b=b, c=c)
        self.answer = calc(a, b, c)
        self.expression = f"word_problem({a}, {b}, {c})"

    def get_prompt(self) -> str:
        """Get the prompt for the LLM."""
        if self.word_problem:
            return f"""Solve this math problem. Give ONLY the numerical answer, no explanation.

{self.word_problem}

Answer:"""
        else:
            return f"""Calculate the following expression. Give ONLY the numerical answer, no explanation.

{self.expression}

Answer:"""

    def get_expected_answer(self) -> float:
        """Get the expected numerical answer."""
        return self.answer

    def get_verification_data(self) -> dict[str, Any]:
        """Get verification data."""
        return {
            "expected": self.answer,
            "tolerance": 0.001,  # Allow small floating point errors
        }


@dataclass
class JSONTask(Task):
    """JSON extraction task with schema validation."""

    tier: TaskTier = TaskTier.SIMPLE
    task_type: TaskType = TaskType.JSON

    input_text: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    expected_output: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> JSONTask:
        """Generate a JSON extraction task."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.3:
            task._generate_simple_extraction()
        elif difficulty < 0.6:
            task._generate_nested_extraction()
        else:
            task._generate_transformation()

        return task

    def _generate_simple_extraction(self) -> None:
        """Extract simple fields from text."""
        names = ["Alice", "Bob", "Carol", "David", "Eve"]
        cities = ["New York", "London", "Tokyo", "Paris", "Sydney"]
        jobs = ["engineer", "teacher", "doctor", "artist", "chef"]

        name = random.choice(names)
        age = random.randint(20, 60)
        city = random.choice(cities)

        self.input_text = f"{name} is a {age}-year-old person living in {city}."
        self.schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
                "city": {"type": "string"},
            },
            "required": ["name", "age", "city"],
        }
        self.expected_output = {"name": name, "age": age, "city": city}

    def _generate_nested_extraction(self) -> None:
        """Extract nested structured data."""
        products = ["laptop", "phone", "tablet", "headphones", "camera"]
        product = random.choice(products)
        price = round(random.uniform(99.99, 999.99), 2)
        quantity = random.randint(1, 10)
        customer = random.choice(["John Smith", "Jane Doe", "Bob Wilson"])

        self.input_text = f"""Order confirmation:
Customer: {customer}
Product: {product}
Price: ${price}
Quantity: {quantity}
Total: ${round(price * quantity, 2)}"""

        self.schema = {
            "type": "object",
            "properties": {
                "customer": {"type": "string"},
                "order": {
                    "type": "object",
                    "properties": {
                        "product": {"type": "string"},
                        "price": {"type": "number"},
                        "quantity": {"type": "integer"},
                    },
                },
            },
            "required": ["customer", "order"],
        }
        self.expected_output = {
            "customer": customer,
            "order": {"product": product, "price": price, "quantity": quantity},
        }

    def _generate_transformation(self) -> None:
        """Transform data between formats."""
        items = []
        for _ in range(random.randint(2, 4)):
            items.append(
                {
                    "item": random.choice(["apple", "banana", "orange", "grape"]),
                    "count": random.randint(1, 10),
                }
            )

        lines = [f"- {item['count']}x {item['item']}" for item in items]
        self.input_text = "Shopping list:\n" + "\n".join(lines)

        self.schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "integer"},
                        },
                    },
                }
            },
        }
        self.expected_output = {
            "items": [{"name": item["item"], "quantity": item["count"]} for item in items]
        }

    def get_prompt(self) -> str:
        """Get the prompt for JSON extraction."""
        schema_str = json.dumps(self.schema, indent=2)
        return f"""Extract data from the following text and return it as JSON matching this schema:

Schema:
{schema_str}

Text:
{self.input_text}

Return ONLY valid JSON, no explanation:"""

    def get_expected_answer(self) -> dict[str, Any]:
        """Get the expected JSON output."""
        return self.expected_output

    def get_verification_data(self) -> dict[str, Any]:
        """Get verification data including schema."""
        return {
            "schema": self.schema,
            "expected": self.expected_output,
        }


@dataclass
class LogicTask(Task):
    """Logic puzzle with constraint checking."""

    tier: TaskTier = TaskTier.SIMPLE
    task_type: TaskType = TaskType.LOGIC

    puzzle: str = ""
    constraints: list[str] = field(default_factory=list)
    answer: str = ""

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> LogicTask:
        """Generate a logic puzzle."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.4:
            task._generate_sequence()
        elif difficulty < 0.7:
            task._generate_deduction()
        else:
            task._generate_ordering()

        return task

    def _generate_sequence(self) -> None:
        """Generate a number sequence puzzle."""
        # Arithmetic sequence
        start = random.randint(1, 20)
        step = random.randint(2, 10)
        sequence = [start + i * step for i in range(5)]
        self.answer = str(sequence[-1] + step)

        display = sequence[:-1] + ["?"]
        self.puzzle = f"What comes next in the sequence: {', '.join(map(str, display))}"
        self.constraints = [f"Answer should be {self.answer}"]

    def _generate_deduction(self) -> None:
        """Generate a simple deduction puzzle."""
        items = ["red", "blue", "green"]
        random.shuffle(items)
        positions = ["first", "second", "third"]

        clues = []
        if random.random() < 0.5:
            clues.append(f"The {items[0]} item is {positions[0]}.")
        else:
            clues.append(f"The {items[0]} item is not {positions[1]} or {positions[2]}.")

        clues.append(f"The {items[1]} item comes before the {items[2]} item.")

        self.puzzle = "Three colored items are arranged in order.\n" + "\n".join(clues)
        self.puzzle += f"\nWhat position is the {items[0]} item?"
        self.answer = positions[0]
        self.constraints = [f"Answer should be '{positions[0]}'"]

    def _generate_ordering(self) -> None:
        """Generate an ordering puzzle."""
        people = random.sample(["Alice", "Bob", "Carol", "David"], 3)
        heights = ["tallest", "middle", "shortest"]

        self.puzzle = f"""{people[0]} is taller than {people[1]}.
{people[1]} is taller than {people[2]}.
Who is the tallest?"""
        self.answer = people[0]
        self.constraints = [f"Answer should be '{people[0]}'"]

    def get_prompt(self) -> str:
        """Get the logic puzzle prompt."""
        return f"""{self.puzzle}

Give ONLY the answer, no explanation:"""

    def get_expected_answer(self) -> str:
        """Get the expected answer."""
        return self.answer

    def get_verification_data(self) -> dict[str, Any]:
        """Get verification data."""
        return {
            "expected": self.answer,
            "constraints": self.constraints,
        }


@dataclass
class CodeTask(Task):
    """Code generation task with unit test verification."""

    tier: TaskTier = TaskTier.MEDIUM
    task_type: TaskType = TaskType.CODE

    function_name: str = ""
    description: str = ""
    signature: str = ""
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    solution: str = ""  # Reference solution

    @classmethod
    def generate(cls, difficulty: float = 0.5) -> CodeTask:
        """Generate a code task based on difficulty."""
        task = cls(difficulty=difficulty)

        if difficulty < 0.3:
            task._generate_simple()
        elif difficulty < 0.6:
            task._generate_medium()
        else:
            task._generate_hard()

        return task

    def _generate_simple(self) -> None:
        """Generate a simple function task."""
        problems = [
            {
                "name": "double",
                "desc": "Return twice the input number",
                "sig": "def double(n: int) -> int:",
                "tests": [
                    {"input": [5], "output": 10},
                    {"input": [0], "output": 0},
                    {"input": [-3], "output": -6},
                ],
                "solution": "def double(n: int) -> int:\n    return n * 2",
            },
            {
                "name": "is_even",
                "desc": "Return True if the number is even, False otherwise",
                "sig": "def is_even(n: int) -> bool:",
                "tests": [
                    {"input": [4], "output": True},
                    {"input": [7], "output": False},
                    {"input": [0], "output": True},
                ],
                "solution": "def is_even(n: int) -> bool:\n    return n % 2 == 0",
            },
            {
                "name": "string_length",
                "desc": "Return the length of the input string",
                "sig": "def string_length(s: str) -> int:",
                "tests": [
                    {"input": ["hello"], "output": 5},
                    {"input": [""], "output": 0},
                    {"input": ["abc"], "output": 3},
                ],
                "solution": "def string_length(s: str) -> int:\n    return len(s)",
            },
        ]
        problem = random.choice(problems)
        self._apply_problem(problem)

    def _generate_medium(self) -> None:
        """Generate a medium difficulty function task."""
        problems = [
            {
                "name": "factorial",
                "desc": "Return the factorial of n (n!). For n=0, return 1.",
                "sig": "def factorial(n: int) -> int:",
                "tests": [
                    {"input": [5], "output": 120},
                    {"input": [0], "output": 1},
                    {"input": [3], "output": 6},
                    {"input": [1], "output": 1},
                ],
                "solution": "def factorial(n: int) -> int:\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)",
            },
            {
                "name": "reverse_string",
                "desc": "Return the input string reversed",
                "sig": "def reverse_string(s: str) -> str:",
                "tests": [
                    {"input": ["hello"], "output": "olleh"},
                    {"input": [""], "output": ""},
                    {"input": ["a"], "output": "a"},
                    {"input": ["ab"], "output": "ba"},
                ],
                "solution": "def reverse_string(s: str) -> str:\n    return s[::-1]",
            },
            {
                "name": "sum_list",
                "desc": "Return the sum of all numbers in the list",
                "sig": "def sum_list(nums: list[int]) -> int:",
                "tests": [
                    {"input": [[1, 2, 3]], "output": 6},
                    {"input": [[]], "output": 0},
                    {"input": [[-1, 1]], "output": 0},
                    {"input": [[10]], "output": 10},
                ],
                "solution": "def sum_list(nums: list[int]) -> int:\n    return sum(nums)",
            },
            {
                "name": "find_max",
                "desc": "Return the maximum value in the list. Assume list is non-empty.",
                "sig": "def find_max(nums: list[int]) -> int:",
                "tests": [
                    {"input": [[1, 5, 3]], "output": 5},
                    {"input": [[-1, -5, -3]], "output": -1},
                    {"input": [[42]], "output": 42},
                ],
                "solution": "def find_max(nums: list[int]) -> int:\n    return max(nums)",
            },
        ]
        problem = random.choice(problems)
        self._apply_problem(problem)

    def _generate_hard(self) -> None:
        """Generate a hard function task."""
        problems = [
            {
                "name": "is_palindrome",
                "desc": "Return True if the string is a palindrome (reads same forwards and backwards), ignoring case and spaces",
                "sig": "def is_palindrome(s: str) -> bool:",
                "tests": [
                    {"input": ["racecar"], "output": True},
                    {"input": ["hello"], "output": False},
                    {"input": ["A man a plan a canal Panama"], "output": True},
                    {"input": [""], "output": True},
                ],
                "solution": "def is_palindrome(s: str) -> bool:\n    s = s.lower().replace(' ', '')\n    return s == s[::-1]",
            },
            {
                "name": "fibonacci",
                "desc": "Return the nth Fibonacci number (0-indexed). F(0)=0, F(1)=1",
                "sig": "def fibonacci(n: int) -> int:",
                "tests": [
                    {"input": [0], "output": 0},
                    {"input": [1], "output": 1},
                    {"input": [6], "output": 8},
                    {"input": [10], "output": 55},
                ],
                "solution": "def fibonacci(n: int) -> int:\n    if n <= 1:\n        return n\n    a, b = 0, 1\n    for _ in range(n - 1):\n        a, b = b, a + b\n    return b",
            },
            {
                "name": "two_sum",
                "desc": "Given a list of integers and a target, return indices of two numbers that add up to target. Return as [i, j] where i < j.",
                "sig": "def two_sum(nums: list[int], target: int) -> list[int]:",
                "tests": [
                    {"input": [[2, 7, 11, 15], 9], "output": [0, 1]},
                    {"input": [[3, 2, 4], 6], "output": [1, 2]},
                    {"input": [[3, 3], 6], "output": [0, 1]},
                ],
                "solution": "def two_sum(nums: list[int], target: int) -> list[int]:\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i\n    return []",
            },
            {
                "name": "is_prime",
                "desc": "Return True if n is a prime number, False otherwise. n >= 0.",
                "sig": "def is_prime(n: int) -> bool:",
                "tests": [
                    {"input": [2], "output": True},
                    {"input": [17], "output": True},
                    {"input": [4], "output": False},
                    {"input": [1], "output": False},
                    {"input": [0], "output": False},
                ],
                "solution": "def is_prime(n: int) -> bool:\n    if n < 2:\n        return False\n    for i in range(2, int(n**0.5) + 1):\n        if n % i == 0:\n            return False\n    return True",
            },
        ]
        problem = random.choice(problems)
        self._apply_problem(problem)

    def _apply_problem(self, problem: dict) -> None:
        """Apply a problem definition to this task."""
        self.function_name = problem["name"]
        self.description = problem["desc"]
        self.signature = problem["sig"]
        self.test_cases = problem["tests"]
        self.solution = problem["solution"]

    def get_prompt(self) -> str:
        """Get the code task prompt."""
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

Write ONLY the function definition, no explanation:"""

    def get_expected_answer(self) -> str:
        """Get the reference solution."""
        return self.solution

    def get_verification_data(self) -> dict[str, Any]:
        """Get verification data including test cases."""
        return {
            "function_name": self.function_name,
            "test_cases": self.test_cases,
            "solution": self.solution,
        }
