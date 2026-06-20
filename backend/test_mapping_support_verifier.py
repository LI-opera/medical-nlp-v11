import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from services.mapping_support_verifier import MappingSupportVerifier


def main():
    verifier = MappingSupportVerifier()

    test_cases = [
        {
            "text": "The patient was evaluated for LMN.",
            "abbreviation": "LMN",
            "expansion": "Lower Motor Neuron"
        },
        {
            "text": "The patient shows LMN signs with weakness and reduced reflexes.",
            "abbreviation": "LMN",
            "expansion": "Lower Motor Neuron"
        },
        {
            "text": "The patient has DM and QRS.",
            "abbreviation": "QRS",
            "expansion": "QRS complex"
        },
        {
            "text": "The ECG showed a widened QRS complex.",
            "abbreviation": "QRS",
            "expansion": "QRS complex"
        },
        {
            "text": "The patient has MS with a diastolic murmur.",
            "abbreviation": "MS",
            "expansion": "mitral stenosis"
        },
        {
            "text": "The patient has MS with diastolic murmur, mitral valve disease, and left atrial enlargement.",
            "abbreviation": "MS",
            "expansion": "mitral stenosis"
        }
    ]

    for case in test_cases:
        result = verifier.verify(
            text=case["text"],
            abbreviation=case["abbreviation"],
            expansion=case["expansion"]
        )

        print("=" * 80)
        print("Text:", case["text"])
        print("Mapping:", case["abbreviation"], "->", case["expansion"])
        print("Supported:", result.supported)
        print("Confidence:", result.confidence)
        print("Reason:", result.reason)


if __name__ == "__main__":
    main()