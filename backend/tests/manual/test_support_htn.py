from services.abbr_service import ABBRService


def main():
    """手动验证 HTN 的完整链路；不在 pytest 收集阶段初始化真实服务。"""
    service = ABBRService()
    result = service.expand_verify_with_retry(
        text="The patient has HTN.",
        max_retries=2,
    )
    print(result)


if __name__ == "__main__":
    main()
