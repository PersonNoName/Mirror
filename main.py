import asyncio

from core.agent_app import AgentApplication, AgentConfig


async def main() -> None:
    app = AgentApplication(AgentConfig())
    await app.initialize()
    print("[AgentApplication] 初始化完成，模拟运行测试...")

    await app.event_bus.emit(
        "dialogue_ended",
        {
            "user_id": "test_user",
            "session_id": "test_session",
            "dialogue": [
                {"role": "user", "content": "请简洁回复"},
                {"role": "assistant", "content": "好的，我会简洁回复。"},
            ],
        },
    )

    await asyncio.sleep(0.5)
    await app.shutdown()
    print("[AgentApplication] 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
