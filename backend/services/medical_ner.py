from transformers import pipeline


NER_LABEL_TO_DOMAIN = {
    "DISEASE_DISORDER": "Condition",
    "SIGN_SYMPTOM": "Condition",
    "BIOLOGICAL_STRUCTURE": "Spec Anatomic Site",
    "MEDICATION": "Drug",
    "DIAGNOSTIC_PROCEDURE": "Procedure",
    "THERAPEUTIC_PROCEDURE": "Procedure",
    "LAB_VALUE": "Measurement",
    "DETAILED_DESCRIPTION": "Observation",
}


class MedicalNER:
    """Medical NER helper used by the active abbreviation pipeline.

    V11 only needs NER on the hot path to infer a candidate expansion's medical
    domain after fallback retrieval. Sentence-level standardization is no
    longer part of the active service layer.
    """

    def __init__(self):
        self.ner_pipeline = pipeline(
            task="token-classification",
            model="Clinical-AI-Apollo/Medical-NER",
            aggregation_strategy="simple",
        )

    def extract_entities(self, text: str):
        raw_entities = self.ner_pipeline(text)
        entities = []
        for item in raw_entities:
            entities.append({
                "text": item["word"],
                "label": item["entity_group"],
                "score": round(float(item["score"]), 4),
                "start": item["start"],
                "end": item["end"],
            })
        return self._merge_adjacent_entities(text, entities)

    def is_medical(self, text: str):
        """Return (is_medical, top_label, top_score) for an isolated phrase."""
        if not text:
            return False, None, 0.0
        ents = self.extract_entities(text)
        if not ents:
            return False, None, 0.0
        top = max(ents, key=lambda e: e["score"])
        return True, top["label"], top["score"]

    def infer_domain(self, text: str):
        """Infer the retrieval domain used for source routing and rerank boosts."""
        _, label, score = self.is_medical(text)
        return NER_LABEL_TO_DOMAIN.get(label), label, score

    def _merge_adjacent_entities(self, text: str, entities: list[dict]):
        if not entities:
            return []

        merged = []
        current = entities[0]
        for next_entity in entities[1:]:
            gap_text = text[current["end"]:next_entity["start"]]
            should_merge = gap_text.strip() == "" and self._can_merge(current, next_entity)
            if should_merge:
                current = {
                    "text": text[current["start"]:next_entity["end"]].strip(),
                    "label": f"{current['label']}+{next_entity['label']}",
                    "score": round((current["score"] + next_entity["score"]) / 2, 4),
                    "start": current["start"],
                    "end": next_entity["end"],
                }
            else:
                merged.append(current)
                current = next_entity

        merged.append(current)
        return merged

    def _can_merge(self, left: dict, right: dict):
        merge_label_pairs = {
            ("BIOLOGICAL_STRUCTURE", "SIGN_SYMPTOM"),
            ("BIOLOGICAL_STRUCTURE", "DISEASE_DISORDER"),
            ("SIGN_SYMPTOM", "SIGN_SYMPTOM"),
        }
        return (left["label"], right["label"]) in merge_label_pairs
