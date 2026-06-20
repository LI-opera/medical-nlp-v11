from services.ner_service import NERService

def main():
    service = NERService()

    text = "The patient has chest pain, shortness of breath, and diabetes."

    entities = service.extract_entities(text)

    print("原始文本:")
    print(text)
    print("="*50)

    for entity in entities:
        print(entity)

if __name__ == "__main__":
    main()