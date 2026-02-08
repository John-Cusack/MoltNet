"""Benchmark dataset loaders for Task Shop.

Loads tasks from HumanEval, MBPP, GSM8K, MATH, QASPER, and SciQ benchmarks
using the HuggingFace datasets library.
"""

from __future__ import annotations

import random
import re
from typing import Any


def load_humaneval(dataset: Any) -> list[dict[str, Any]]:
    """Load HumanEval coding benchmark.

    HumanEval: 164 hand-written Python problems.
    Each has a function signature + docstring prompt and a check() test function.
    """
    tasks = []
    for item in dataset:
        task_id = item["task_id"]  # e.g., "HumanEval/0"
        prompt = item["prompt"]  # Function signature + docstring
        canonical = item["canonical_solution"]
        test_code = item["test"]  # check(candidate) function
        entry_point = item["entry_point"]  # Function name

        # Build test code that calls check(candidate)
        # The test expects the function to be named the same as entry_point
        full_test = f"""
# Run the test
check({entry_point})
"""

        tasks.append({
            "benchmark": "humaneval",
            "benchmark_id": task_id,
            "category": "coding",
            "difficulty": _estimate_humaneval_difficulty(prompt),
            "title": f"HumanEval: {entry_point}",
            "prompt": f"Write a Python function to solve the following problem:\n\n{prompt}",
            "setup_code": None,
            "test_code": test_code + full_test,
            "ground_truth": canonical,
            "metadata": {"entry_point": entry_point},
        })

    return tasks


def load_mbpp(dataset: Any) -> list[dict[str, Any]]:
    """Load MBPP coding benchmark.

    MBPP: ~974 crowd-sourced Python problems.
    Each has a text description and assert-based tests.
    """
    tasks = []
    for item in dataset:
        task_id = str(item["task_id"])
        text = item["text"]  # Problem description
        code = item["code"]  # Reference solution
        test_list = item.get("test_list", [])  # List of assert statements

        # Build test code from assert list
        test_code = "\n".join(test_list) if test_list else ""

        tasks.append({
            "benchmark": "mbpp",
            "benchmark_id": f"mbpp/{task_id}",
            "category": "coding",
            "difficulty": _estimate_mbpp_difficulty(text, code),
            "title": f"MBPP {task_id}: {text[:60]}",
            "prompt": f"Write a Python function to solve the following problem:\n\n{text}",
            "setup_code": None,
            "test_code": test_code,
            "ground_truth": code,
            "metadata": {"test_count": len(test_list)},
        })

    return tasks


def load_gsm8k(dataset: Any) -> list[dict[str, Any]]:
    """Load GSM8K math benchmark.

    GSM8K: ~8.5K grade school math word problems.
    Answer is after #### in the answer field.
    """
    tasks = []
    for i, item in enumerate(dataset):
        question = item["question"]
        answer_text = item["answer"]

        # Extract numeric answer after ####
        ground_truth = _extract_gsm8k_answer(answer_text)

        tasks.append({
            "benchmark": "gsm8k",
            "benchmark_id": f"gsm8k/{i}",
            "category": "math",
            "difficulty": _estimate_gsm8k_difficulty(question),
            "title": f"GSM8K: {question[:60]}",
            "prompt": (
                f"Solve the following math problem. Show your work, then "
                f"provide your final answer as 'ANSWER: <number>'.\n\n{question}"
            ),
            "setup_code": None,
            "test_code": None,
            "ground_truth": ground_truth,
            "metadata": {"full_solution": answer_text},
        })

    return tasks


def load_math(dataset: Any) -> list[dict[str, Any]]:
    r"""Load MATH competition benchmark.

    MATH: ~12.5K competition math problems with 5 difficulty levels.
    Answer in \boxed{}.
    """
    tasks = []
    for i, item in enumerate(dataset):
        problem = item["problem"]
        solution = item["solution"]
        level = item.get("level", "Level 3")
        subject = item.get("type", "unknown")

        # Extract answer from \boxed{}
        ground_truth = _extract_math_answer(solution)
        difficulty = _math_level_to_difficulty(level)

        tasks.append({
            "benchmark": "math",
            "benchmark_id": f"math/{i}",
            "category": "math",
            "difficulty": difficulty,
            "title": f"MATH ({subject}): {problem[:60]}",
            "prompt": (
                f"Solve the following math problem. Show your work, then "
                f"provide your final answer as 'ANSWER: <value>'.\n\n{problem}"
            ),
            "setup_code": None,
            "test_code": None,
            "ground_truth": ground_truth,
            "metadata": {
                "level": level,
                "subject": subject,
                "full_solution": solution,
            },
        })

    return tasks


def load_qasper(dataset: Any) -> list[dict[str, Any]]:
    """Load QASPER AI paper reading comprehension benchmark.

    QASPER: ~5K questions over ~1K NLP/ML papers from allenai/qasper.
    Each paper has questions with extractive, abstractive, boolean, or
    unanswerable answers.
    """
    tasks = []
    for item in dataset:
        title = item.get("title", "Untitled Paper")
        abstract = item.get("abstract", "")

        # Build paper text from abstract + available full text
        full_text_sections = item.get("full_text", {})
        section_texts = []
        if isinstance(full_text_sections, dict):
            paragraphs = full_text_sections.get("paragraphs", [])
            section_names = full_text_sections.get("section_name", [])
            for sec_name, sec_paragraphs in zip(section_names, paragraphs):
                if sec_name:
                    section_texts.append(f"\n## {sec_name}")
                if isinstance(sec_paragraphs, list):
                    section_texts.extend(sec_paragraphs)
                elif isinstance(sec_paragraphs, str):
                    section_texts.append(sec_paragraphs)

        paper_body = "\n".join(section_texts)
        paper_text = f"Abstract: {abstract}\n{paper_body}" if abstract else paper_body
        # Truncate to ~3000 chars to keep prompts manageable
        if len(paper_text) > 3000:
            paper_text = paper_text[:3000] + "\n... (truncated)"

        # Extract questions and answers
        qas = item.get("qas", {})
        questions = qas.get("question", [])
        answers_list = qas.get("answers", [])
        question_ids = qas.get("question_id", [])

        for q_idx, question in enumerate(questions):
            if q_idx >= len(answers_list):
                break

            answers_data = answers_list[q_idx]
            answer_info = answers_data.get("answer", [])
            if not answer_info:
                continue

            # Use the first annotator's answer
            first_answer = answer_info[0]
            unanswerable = first_answer.get("unanswerable", False)
            extractive_spans = first_answer.get("extractive_spans", [])
            free_form = first_answer.get("free_form_answer", "")
            yes_no = first_answer.get("yes_no")

            # Determine answer type and ground truth
            if unanswerable:
                answer_type = "unanswerable"
                ground_truth = "unanswerable"
            elif yes_no is not None:
                answer_type = "boolean"
                ground_truth = "yes" if yes_no else "no"
            elif extractive_spans:
                answer_type = "extractive"
                ground_truth = " ".join(
                    s for s in extractive_spans if isinstance(s, str)
                )
            elif free_form:
                answer_type = "abstractive"
                ground_truth = free_form
            else:
                continue

            q_id = question_ids[q_idx] if q_idx < len(question_ids) else f"q{q_idx}"
            task_id = f"qasper/{q_id}"

            prompt = (
                "Read the following AI research paper excerpt and answer the question.\n\n"
                f"PAPER: {title}\n"
                f"{paper_text}\n\n"
                f"QUESTION: {question}\n\n"
                "Provide your answer as 'ANSWER: <your answer>'. "
                "For yes/no questions, answer 'ANSWER: yes' or 'ANSWER: no'."
            )

            tasks.append({
                "benchmark": "qasper",
                "benchmark_id": task_id,
                "category": "reading",
                "difficulty": _estimate_qasper_difficulty(answer_type),
                "title": f"QASPER: {question[:60]}",
                "prompt": prompt,
                "setup_code": None,
                "test_code": None,
                "ground_truth": ground_truth,
                "metadata": {"answer_type": answer_type, "paper_title": title},
            })

    return tasks


def load_sciq(dataset: Any) -> list[dict[str, Any]]:
    """Load SciQ science reading comprehension benchmark.

    SciQ: ~13K multiple-choice science questions with supporting passages
    from allenai/sciq.
    """
    tasks = []
    for i, item in enumerate(dataset):
        question = item["question"]
        correct = item["correct_answer"]
        support = item.get("support", "")
        distractors = [
            item.get("distractor1", ""),
            item.get("distractor2", ""),
            item.get("distractor3", ""),
        ]

        # Shuffle options and track correct letter
        options = [correct] + distractors
        random.seed(hash(question))  # deterministic shuffle per question
        random.shuffle(options)
        correct_idx = options.index(correct)
        correct_letter = chr(ord("A") + correct_idx)

        letters = ["A", "B", "C", "D"]
        option_lines = "\n".join(
            f"{letters[j]}) {opt}" for j, opt in enumerate(options)
        )

        prompt = (
            "Read the passage and answer the question.\n\n"
            f"PASSAGE: {support}\n\n"
            f"QUESTION: {question}\n\n"
            f"{option_lines}\n\n"
            "Provide your answer as 'ANSWER: <letter>' (e.g., 'ANSWER: B')."
        )

        tasks.append({
            "benchmark": "sciq",
            "benchmark_id": f"sciq/{i}",
            "category": "reading",
            "difficulty": _estimate_sciq_difficulty(support),
            "title": f"SciQ: {question[:60]}",
            "prompt": prompt,
            "setup_code": None,
            "test_code": None,
            "ground_truth": correct_letter,
            "metadata": {
                "answer_type": "multiple_choice",
                "correct_answer": correct,
                "correct_letter": correct_letter,
            },
        })

    return tasks


# ==================== Difficulty Estimation ====================


def _estimate_humaneval_difficulty(prompt: str) -> float:
    """Estimate HumanEval problem difficulty from prompt length and complexity."""
    length = len(prompt)
    if length < 200:
        return 0.2
    elif length < 400:
        return 0.4
    elif length < 600:
        return 0.6
    elif length < 800:
        return 0.8
    return 0.9


def _estimate_mbpp_difficulty(text: str, code: str) -> float:
    """Estimate MBPP problem difficulty from description and solution."""
    code_lines = len(code.strip().split("\n"))
    if code_lines <= 3:
        return 0.2
    elif code_lines <= 6:
        return 0.4
    elif code_lines <= 12:
        return 0.6
    elif code_lines <= 20:
        return 0.8
    return 0.9


def _estimate_gsm8k_difficulty(question: str) -> float:
    """Estimate GSM8K difficulty from question complexity."""
    # Count number of sentences/steps
    sentences = question.count(".")
    if sentences <= 2:
        return 0.2
    elif sentences <= 3:
        return 0.3
    elif sentences <= 4:
        return 0.5
    elif sentences <= 6:
        return 0.7
    return 0.8


def _math_level_to_difficulty(level: str) -> float:
    """Convert MATH benchmark level to difficulty 0-1."""
    level_map = {
        "Level 1": 0.2,
        "Level 2": 0.4,
        "Level 3": 0.6,
        "Level 4": 0.8,
        "Level 5": 0.95,
    }
    return level_map.get(level, 0.5)


def _estimate_qasper_difficulty(answer_type: str) -> float:
    """Map QASPER answer type to difficulty."""
    return {
        "boolean": 0.2,
        "extractive": 0.5,
        "abstractive": 0.7,
        "unanswerable": 0.8,
    }.get(answer_type, 0.5)


def _estimate_sciq_difficulty(support: str) -> float:
    """Estimate SciQ difficulty from passage length."""
    length = len(support)
    if length < 200:
        return 0.2
    elif length < 400:
        return 0.4
    elif length < 600:
        return 0.6
    return 0.8


def _extract_gsm8k_answer(answer_text: str) -> str:
    """Extract numeric answer from GSM8K answer string (after ####)."""
    if "####" in answer_text:
        return answer_text.split("####")[-1].strip().replace(",", "")
    # Fallback: try last number in text
    numbers = re.findall(r"[-+]?\d+\.?\d*", answer_text)
    return numbers[-1] if numbers else "0"


def _extract_math_answer(solution: str) -> str:
    r"""Extract answer from MATH solution (from \boxed{})."""
    # Handle nested braces in \boxed{}
    match = re.search(r"\\boxed\{", solution)
    if match:
        start = match.end()
        depth = 1
        i = start
        while i < len(solution) and depth > 0:
            if solution[i] == "{":
                depth += 1
            elif solution[i] == "}":
                depth -= 1
            i += 1
        return solution[start : i - 1].strip()

    # Fallback
    numbers = re.findall(r"[-+]?\d+\.?\d*", solution)
    return numbers[-1] if numbers else "0"


# ==================== Loader Registry ====================


BENCHMARK_LOADERS = {
    "humaneval": {
        "dataset_name": "openai/openai_humaneval",
        "split": "test",
        "loader": load_humaneval,
    },
    "mbpp": {
        "dataset_name": "google-research-datasets/mbpp",
        "split": "test",
        "loader": load_mbpp,
    },
    "gsm8k": {
        "dataset_name": "openai/gsm8k",
        "split": "main:test",
        "loader": load_gsm8k,
    },
    "math": {
        "dataset_name": "lighteval/MATH",
        "split": "test",
        "loader": load_math,
    },
    "qasper": {
        "dataset_name": "allenai/qasper",
        "split": "test",
        "loader": load_qasper,
    },
    "sciq": {
        "dataset_name": "allenai/sciq",
        "split": "test",
        "loader": load_sciq,
    },
}
