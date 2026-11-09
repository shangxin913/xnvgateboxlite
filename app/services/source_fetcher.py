from typing import Protocol


class SourceFetcher(Protocol):
    def fetch(self, source_url: str) -> list[dict]: ...


class VPNGateSourceFetcher:
    def fetch(self, source_url: str) -> list[dict]:
        raise NotImplementedError("VPN Gate 抓取适配器尚未接入")
