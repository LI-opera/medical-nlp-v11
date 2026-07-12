#测试std_service.py

from services.std_service import StdService

def main():
    service = StdService()
    query = "chest pain"
    results = service.search_similar_terms(query,limit=3)
    print("查询:",query)
    for result in results:
        print(result)

if __name__ == "__main__":
    main()