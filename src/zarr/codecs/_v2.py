from __future__ import annotations

from dataclasses import dataclass

from zarr.buffer import Buffer, NDBuffer
from zarr.codecs.mixins import ArrayArrayCodecBatchMixin, ArrayBytesCodecBatchMixin
from zarr.common import JSON, ArraySpec, to_thread

import numcodecs
from numcodecs.compat import ensure_bytes, ensure_ndarray


@dataclass(frozen=True)
class V2Compressor(ArrayBytesCodecBatchMixin):
    compressor: dict[str, JSON] | None

    is_fixed_size = False

    async def decode_single(
        self,
        chunk_bytes: Buffer,
        chunk_spec: ArraySpec,
    ) -> NDBuffer:
        if chunk_bytes is None:
            return None

        if self.compressor is not None:
            compressor = numcodecs.get_codec(self.compressor)
            chunk_numpy_array = ensure_ndarray(
                await to_thread(compressor.decode, chunk_bytes.as_array_like())
            )
        else:
            chunk_numpy_array = ensure_ndarray(chunk_bytes.as_array_like())

        # ensure correct dtype
        if str(chunk_numpy_array.dtype) != chunk_spec.dtype:
            chunk_numpy_array = chunk_numpy_array.view(chunk_spec.dtype)

        return NDBuffer.from_numpy_array(chunk_numpy_array)

    async def encode_single(
        self,
        chunk_array: NDBuffer,
        _chunk_spec: ArraySpec,
    ) -> Buffer | None:
        chunk_numpy_array = chunk_array.as_numpy_array()
        if self.compressor is not None:
            compressor = numcodecs.get_codec(self.compressor)
            if (
                not chunk_numpy_array.flags.c_contiguous
                and not chunk_numpy_array.flags.f_contiguous
            ):
                chunk_numpy_array = chunk_numpy_array.copy(order="A")
            encoded_chunk_bytes = ensure_bytes(
                await to_thread(compressor.encode, chunk_numpy_array)
            )
        else:
            encoded_chunk_bytes = ensure_bytes(chunk_numpy_array)

        return Buffer.from_bytes(encoded_chunk_bytes)

    def compute_encoded_size(self, _input_byte_length: int, _chunk_spec: ArraySpec) -> int:
        raise NotImplementedError


@dataclass(frozen=True)
class V2Filters(ArrayArrayCodecBatchMixin):
    filters: list[dict[str, JSON]]

    is_fixed_size = False

    async def decode_single(
        self,
        chunk_array: NDBuffer,
        chunk_spec: ArraySpec,
    ) -> NDBuffer:
        chunk_numpy_array = chunk_array.as_numpy_array()
        # apply filters in reverse order
        if self.filters is not None:
            for filter_metadata in self.filters[::-1]:
                filter = numcodecs.get_codec(filter_metadata)
                chunk_numpy_array = await to_thread(filter.decode, chunk_numpy_array)

        # ensure correct chunk shape
        if chunk_numpy_array.shape != chunk_spec.shape:
            chunk_numpy_array = chunk_numpy_array.reshape(
                chunk_spec.shape,
                order=chunk_spec.order,
            )

        return NDBuffer.from_numpy_array(chunk_numpy_array)

    async def encode_single(
        self,
        chunk_array: NDBuffer,
        chunk_spec: ArraySpec,
    ) -> NDBuffer | None:
        chunk_numpy_array = chunk_array.as_numpy_array().ravel(order=chunk_spec.order)

        for filter_metadata in self.filters:
            filter = numcodecs.get_codec(filter_metadata)
            chunk_numpy_array = await to_thread(filter.encode, chunk_numpy_array)

        return NDBuffer.from_numpy_array(chunk_numpy_array)

    def compute_encoded_size(self, _input_byte_length: int, _chunk_spec: ArraySpec) -> int:
        raise NotImplementedError
