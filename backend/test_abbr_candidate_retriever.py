from services.abbr_candidate_retriever import ABBRCandidateRetriever

def main():
    retriever = ABBRCandidateRetriever()

    for abbr in ["SOB", "DM", "CP", "XYZ"]:
        print("缩写:",abbr)
        print("候选扩展:")
        print(retriever.retrieve(abbr))
        print("-"*50)

if __name__ == "__main__":
    main()