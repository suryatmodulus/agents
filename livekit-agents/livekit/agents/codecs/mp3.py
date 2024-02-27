import asyncio
import ctypes
import logging
from importlib import import_module


class Mp3StreamDecoder:
    """A class that can be used to stream arbitrary MP3 data (i.e. from an HTTP chunk) and decode it into PCM audio.
    This class is meant to be ephemeral. When you're done sending data, call close() to flush
    the decoder and create a new instance of this class if you need to decode more data.
    """

    def __init__(self):
        try:
            globals()["av"] = import_module("av")
        except ImportError:
            raise ImportError(
                "You haven't included the decoder_utils optional dependencies. Please install the decoder_utils extra by running `pip install livekit-agents[decoder_utils]`"
            )
        self._closed = False
        self._input_queue = asyncio.Queue()
        self._output_queue = asyncio.Queue()
        self._codec = av.CodecContext.create("mp3", "r")  # noqa
        self._run_task = asyncio.create_task(self._run())

    def close(self):
        self._closed = True
        self._input_queue.put_nowait(None)

    def push_chunk(self, chunk: bytes):
        if self._closed:
            raise ValueError("Cannot push chunk to closed decoder")
        self._input_queue.put_nowait(chunk)

    async def _run(self):
        while True:
            input = await self._input_queue.get()
            if input is None:
                self._output_queue.put_nowait(None)
                break

            result = await asyncio.to_thread(self._decode_input, input)
            # If error decoding, skip it
            if result is None:
                continue
            self._output_queue.put_nowait(result)

    def _decode_input(self, input: bytes):
        packets = self._codec.parse(input)
        for packet in packets:
            try:
                decoded = self._codec.decode(packet)
                plane = decoded[0].planes[0]
                ptr = plane.buffer_ptr
                size = plane.buffer_size
                byte_array_pointer = ctypes.cast(
                    ptr, ctypes.POINTER(ctypes.c_char * size)
                )
                return bytes(byte_array_pointer.contents)
            except Exception as e:
                logging.error(f"Error decoding chunk: {e}")
                return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        packet = await self._output_queue.get()
        if packet is None:
            raise StopAsyncIteration
        return packet
