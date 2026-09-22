"""xxHash64 support.

The optional native ``xxhash`` package is used when it is installed because it
hashes several gigabytes per second.  When it is missing, the pure-Python
implementation below keeps the feature available at a much lower throughput, so
xxHash64 never becomes an unusable option on a fresh checkout.
"""

from __future__ import annotations

import struct

PRIME64_1 = 0x9E3779B185EBCA87
PRIME64_2 = 0xC2B2AE3D27D4EB4F
PRIME64_3 = 0x165667B19E3779F9
PRIME64_4 = 0x85EBCA77C2B2AE63
PRIME64_5 = 0x27D4EB2F165667C5

_MASK64 = 0xFFFFFFFFFFFFFFFF
_UNPACK_BLOCK = struct.Struct("<4Q").unpack_from

try:  # pragma: no cover - depends on the local environment
    import xxhash as _native
except ImportError:  # pragma: no cover - depends on the local environment
    _native = None

NATIVE_AVAILABLE = _native is not None


def _rotl64(value: int, bits: int) -> int:
    return ((value << bits) | (value >> (64 - bits))) & _MASK64


def _round64(accumulator: int, lane: int) -> int:
    accumulator = (accumulator + lane * PRIME64_2) & _MASK64
    accumulator = _rotl64(accumulator, 31)
    return (accumulator * PRIME64_1) & _MASK64


def _merge_round64(accumulator: int, lane: int) -> int:
    accumulator ^= _round64(0, lane)
    return (accumulator * PRIME64_1 + PRIME64_4) & _MASK64


class PureXXH64:
    """Incremental xxHash64 in pure Python.

    ``update`` returns ``self`` so callers can chain, unlike ``hashlib``.
    """

    __slots__ = ("_seed", "_v1", "_v2", "_v3", "_v4", "_buffer", "_total", "_large")

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed & _MASK64
        self._v1 = (self._seed + PRIME64_1 + PRIME64_2) & _MASK64
        self._v2 = (self._seed + PRIME64_2) & _MASK64
        self._v3 = self._seed
        self._v4 = (self._seed - PRIME64_1) & _MASK64
        self._buffer = b""
        self._total = 0
        self._large = False

    def update(self, data: bytes) -> PureXXH64:
        length = len(data)
        if not length:
            return self
        self._total += length
        view = memoryview(data)
        position = 0

        if self._buffer:
            needed = 32 - len(self._buffer)
            if length < needed:
                self._buffer += bytes(view)
                return self
            self._buffer += bytes(view[:needed])
            self._absorb_block(self._buffer)
            self._buffer = b""
            position = needed

        remaining = length - position
        full = remaining - (remaining % 32)
        if full:
            end = position + full
            unpack = _UNPACK_BLOCK
            round64 = _round64
            v1, v2, v3, v4 = self._v1, self._v2, self._v3, self._v4
            while position < end:
                a, b, c, d = unpack(view, position)
                v1 = round64(v1, a)
                v2 = round64(v2, b)
                v3 = round64(v3, c)
                v4 = round64(v4, d)
                position += 32
            self._v1, self._v2, self._v3, self._v4 = v1, v2, v3, v4
            self._large = True

        if position < length:
            self._buffer = bytes(view[position:])
        return self

    def _absorb_block(self, block: bytes) -> None:
        a, b, c, d = _UNPACK_BLOCK(block, 0)
        self._v1 = _round64(self._v1, a)
        self._v2 = _round64(self._v2, b)
        self._v3 = _round64(self._v3, c)
        self._v4 = _round64(self._v4, d)
        self._large = True

    def intdigest(self) -> int:
        if self._large:
            v1, v2, v3, v4 = self._v1, self._v2, self._v3, self._v4
            value = (_rotl64(v1, 1) + _rotl64(v2, 7) + _rotl64(v3, 12) + _rotl64(v4, 18)) & _MASK64
            value = _merge_round64(value, v1)
            value = _merge_round64(value, v2)
            value = _merge_round64(value, v3)
            value = _merge_round64(value, v4)
        else:
            value = (self._seed + PRIME64_5) & _MASK64

        value = (value + self._total) & _MASK64

        tail = self._buffer
        tail_length = len(tail)
        position = 0
        while position + 8 <= tail_length:
            value ^= _round64(0, int.from_bytes(tail[position : position + 8], "little"))
            value = (_rotl64(value, 27) * PRIME64_1 + PRIME64_4) & _MASK64
            position += 8
        if position + 4 <= tail_length:
            lane = int.from_bytes(tail[position : position + 4], "little")
            value ^= (lane * PRIME64_1) & _MASK64
            value = (_rotl64(value, 23) * PRIME64_2 + PRIME64_3) & _MASK64
            position += 4
        while position < tail_length:
            value ^= (tail[position] * PRIME64_5) & _MASK64
            value = (_rotl64(value, 11) * PRIME64_1) & _MASK64
            position += 1

        value ^= value >> 33
        value = (value * PRIME64_2) & _MASK64
        value ^= value >> 29
        value = (value * PRIME64_3) & _MASK64
        value ^= value >> 32
        return value

    def digest(self) -> bytes:
        return self.intdigest().to_bytes(8, "big")

    def hexdigest(self) -> str:
        return f"{self.intdigest():016x}"

    def copy(self) -> PureXXH64:
        clone = PureXXH64(self._seed)
        clone._v1 = self._v1
        clone._v2 = self._v2
        clone._v3 = self._v3
        clone._v4 = self._v4
        clone._buffer = self._buffer
        clone._total = self._total
        clone._large = self._large
        return clone


class XXH64Digest:
    """Uniform xxHash64 digest API over the native and pure-Python backends."""

    __slots__ = ("_impl",)

    def __init__(self, seed: int = 0, *, pure: bool = False) -> None:
        if pure or _native is None:
            self._impl = PureXXH64(seed)
        else:  # pragma: no cover - depends on the local environment
            self._impl = _native.xxh64(seed=seed)

    def update(self, data: bytes) -> XXH64Digest:
        self._impl.update(data)
        return self

    def digest(self) -> bytes:
        return self._impl.digest()

    def hexdigest(self) -> str:
        return self._impl.hexdigest()

    def intdigest(self) -> int:
        return self._impl.intdigest()

    def copy(self) -> XXH64Digest:
        clone = XXH64Digest.__new__(XXH64Digest)
        clone._impl = self._impl.copy()
        return clone


def new(seed: int = 0) -> XXH64Digest:
    """Return a fresh xxHash64 digest object exposing ``update``/``hexdigest``."""
    return XXH64Digest(seed)


def native_available() -> bool:
    return _native is not None
