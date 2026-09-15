"""Versioned llama.cpp settings and the backend boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class LlamaRuntimeConfig:
    chat_format: str = ""
    max_tokens: int = 2048
    temperature: float = 0.2
    top_p: float = 0.9
    repetition_penalty: float = 1.05
    gpu_layers: int = -1
    n_batch: int = 512
    n_ctx: int = 16_384
    flash_attn: bool = True
    kv_cache_type: str = "q8_0"
    op_offload: bool = True
    keep_model_loaded: bool = False
    seed: int = 1

    def validate(self) -> None:
        if not 0 <= self.n_ctx <= 131_072:
            raise ValueError("n_ctx must be in 0..131072")
        if self.max_tokens < 1 or self.n_batch < 1:
            raise ValueError("max_tokens and n_batch must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be in 0..2")
        if not 0.0 <= self.top_p <= 1.0:
            raise ValueError("top_p must be in [0, 1]")
        if self.repetition_penalty <= 0.0:
            raise ValueError("repetition_penalty must be positive")
        if not 1 <= self.seed <= 2_147_483_647:
            raise ValueError("seed must be in 1..2147483647")
        if self.kv_cache_type not in {"f16", "q8_0", "q4_0"}:
            raise ValueError("unsupported KV cache type")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return asdict(self)


class TextInferenceBackend(Protocol):
    @property
    def effective_n_ctx(self) -> int:
        ...

    def count_serialized_tokens(self, system: str, payload: str) -> int:
        """Count the final chat serialization, including its template."""

    def translate_ja_to_en(self, units: Sequence[str]) -> Sequence[str]:
        ...

    def close(self) -> None:
        ...
