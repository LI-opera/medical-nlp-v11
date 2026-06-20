import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from graph.abbr_graph import build_abbr_graph


def main():
    graph = build_abbr_graph()

    initial_state = {
        "original_text": "The patient denies CP but reports SOB.",
        "attempt": 1,
        "max_retries": 2,
        "success": False,
        "attempts": []
    }

    result = graph.invoke(initial_state)

    print("=" * 80)
    print("Original Text:")
    print(result.get("original_text"))

    print("\nFinal Expanded Text:")
    print(result.get("current_expanded_text"))

    print("\nMappings:")
    print(result.get("current_mappings"))

    print("\nSuccess:")
    print(result.get("success"))

    print("\nAttempts:")
    for attempt in result.get("attempts", []):
        print(attempt)


if __name__ == "__main__":
    main()