from typing import Protocol


class NodeChecker(Protocol):
    def check(self, node: dict, *, timeout_seconds: int) -> dict: ...


class UnavailableNodeChecker:
    def check(self, node: dict, *, timeout_seconds: int) -> dict:
        raise NotImplementedError("链路检测器尚未接入")
