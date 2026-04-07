from typing import Optional, Literal, Any, Callable, Awaitable
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class CircuitBreakerState(BaseModel):
    name: str
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: Literal["closed", "open", "half_open"] = "closed"
    opened_at: Optional[datetime] = None
    half_open_probe_count: int = 0


class SnapshotRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    block_type: str
    version: int
    content: dict
    reason: Optional[str] = None


CIRCUIT_BREAKER_CONFIG = {
    "failure_threshold": 5,
    "success_threshold": 2,
    "half_open_max_calls": 3,
    "open_timeout_seconds": 60,
}


class CircuitBreaker:
    """
    熔断器：保护外部服务调用（LLM、GraphDB、VectorDB 等）。

    状态转换：
    - CLOSED（正常）: 失败计数 < failure_threshold，正常执行
    - OPEN（熔断）: 失败计数 >= failure_threshold，立即拒绝，60秒后半开
    - HALF_OPEN（半开）: 允许试探请求，成功计数 >= success_threshold 则关闭
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        open_timeout_seconds: int = 60,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.open_timeout_seconds = open_timeout_seconds
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitBreakerState(name=name)
        self._last_state_change = datetime.utcnow()

    @property
    def state(self) -> CircuitBreakerState:
        self._check_transition()
        return self._state

    def _check_transition(self) -> None:
        if self._state.state == "open":
            elapsed = (datetime.utcnow() - self._last_state_change).total_seconds()
            if elapsed >= self.open_timeout_seconds:
                self._transition_to("half_open")

    def _transition_to(self, new_state: Literal["closed", "open", "half_open"]) -> None:
        if self._state.state == new_state:
            return
        print(f"[CircuitBreaker:{self.name}] {self._state.state} -> {new_state}")
        self._state.state = new_state
        self._last_state_change = datetime.utcnow()

        if new_state == "closed":
            self._state.failure_count = 0
            self._state.success_count = 0
        elif new_state == "open":
            self._state.opened_at = datetime.utcnow()
        elif new_state == "half_open":
            self._state.half_open_probe_count = 0

    def record_success(self) -> None:
        if self._state.state == "half_open":
            self._state.success_count += 1
            if self._state.success_count >= self.success_threshold:
                self._transition_to("closed")
                print(
                    f"[CircuitBreaker:{self.name}] 熔断关闭（{self._state.success_count} 次成功）"
                )
        elif self._state.state == "closed":
            self._state.failure_count = 0

    def record_failure(self) -> None:
        if self._state.state == "half_open":
            self._transition_to("open")
            print(f"[CircuitBreaker:{self.name}] 半开试探失败，重新打开")
            return

        self._state.failure_count += 1
        self._state.last_failure_time = datetime.utcnow()

        if self._state.failure_count >= self.failure_threshold:
            self._transition_to("open")
            print(
                f"[CircuitBreaker:{self.name}] 熔断打开（失败 {self._state.failure_count} 次）"
            )

    async def call(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if self._state.state == "open":
            self._check_transition()
            if self._state.state == "open":
                raise CircuitBreakerOpen(
                    f"CircuitBreaker '{self.name}' is OPEN, call rejected"
                )

        if self._state.state == "half_open":
            if self._state.half_open_probe_count >= self.half_open_max_calls:
                raise CircuitBreakerOpen(
                    f"CircuitBreaker '{self.name}' half_open probe limit reached"
                )
            self._state.half_open_probe_count += 1

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise e

    def reset(self) -> None:
        self._state = CircuitBreakerState(name=self.name)
        self._last_state_change = datetime.utcnow()


class CircuitBreakerOpen(Exception):
    pass
