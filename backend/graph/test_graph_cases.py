import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from graph.abbr_graph import build_abbr_graph


GRAPH_TEST_CASES = [
    "The patient has HTN.",
    "The patient has DM.",
    "The patient developed AKI after dehydration.",
    "The patient has COPD and SOB.",
    "The patient denies CP but reports SOB.",
    "The patient has MS with optic neuritis and limb weakness.",
]


def main():
    graph = build_abbr_graph()

    for index, text in enumerate(GRAPH_TEST_CASES, start=1):
        initial_state = {
            "original_text": text,
            "attempt": 1,
            "max_retries": 2,
            "success": False,
            "attempts": []
        }

        result = graph.invoke(initial_state)

        print("=" * 80)
        print(f"Case {index}")
        print("Input:")
        print(text)

        print("\nExpanded:")
        print(result.get("current_expanded_text"))

        print("\nMappings:")
        print(result.get("current_mappings"))

        print("\nSuccess:")
        print(result.get("success"))

        print("\nAttempts Count:")
        print(len(result.get("attempts", [])))


if __name__ == "__main__":
    main()