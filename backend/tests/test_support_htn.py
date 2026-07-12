from services.abbr_service import ABBRService

service = ABBRService()

result = service.expand_verify_with_retry(
    text="The patient has HTN.",
    max_retries=2
)

print(result)