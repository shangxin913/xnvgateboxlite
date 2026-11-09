from typing import Protocol


class EgressExecutor(Protocol):
    def apply(self, egresses: list[dict], default_egress_id: int | None) -> None: ...


class UnavailableEgressExecutor:
    def apply(self, egresses: list[dict], default_egress_id: int | None) -> None:
        raise NotImplementedError("VPS 接入监听、隧道及出口执行层尚未接入")
