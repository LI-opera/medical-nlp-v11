from services.medical_standardizer import MedicalStandardizer

def main():
    standardizer = MedicalStandardizer()

    text =  "The patient has chest pain, shortness of breath, and diabetes."

    result = standardizer.standardize(text)

    print(result)

if __name__ == "__main__":
    main()