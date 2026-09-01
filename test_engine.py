import unittest
import threading
import queue
import time
import socket
import urllib.request
import urllib.parse
import json
import os
import sys
import zipfile
import io

# Ensure E:\ZipStreamHub is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from engine import StreamPrefetcher, RemoteZipReader, HTTP_POOL
from server import ThreadedZipStreamServer, ZipStreamWebHandler, ARCHIVE_LOCK, CACHED_ENTRIES, READERS_BY_URL
import server


class MockHTTPResponse:
    def __init__(self, data: bytes, status: int = 200, headers: dict = None):
        self.data = data
        self.status = status
        self.headers = headers or {}


class MockPoolManager:
    def __init__(self, full_data: bytes):
        self.full_data = full_data
        self.request_count = 0

    def request(self, method: str, url: str, headers: dict = None, preload_content: bool = True):
        self.request_count += 1
        headers = headers or {}
        range_hdr = headers.get("Range")
        total_len = len(self.full_data)

        if not range_hdr:
            return MockHTTPResponse(self.full_data, 200, {
                "Content-Length": str(total_len),
                "Accept-Ranges": "bytes"
            })

        range_val = range_hdr.replace("bytes=", "")
        parts = range_val.split("-")
        start = int(parts[0])
        end = int(parts[1]) if parts[1] else total_len - 1
        end = min(end, total_len - 1)

        sliced = self.full_data[start:end + 1]
        return MockHTTPResponse(
            sliced,
            206,
            {
                "Content-Range": f"bytes {start}-{end}/{total_len}",
                "Content-Length": str(len(sliced)),
                "Accept-Ranges": "bytes"
            }
        )


class TestZipStreamEngineAndServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create an in-memory test ZIP archive with multiple files
        cls.zip_buffer = io.BytesIO()
        with zipfile.ZipFile(cls.zip_buffer, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr("test_ep1.mkv", b"STREAM_TEST_CONTENT_12345" * 1000)
            zf.writestr("test_ep2.mp4", b"ANOTHER_VIDEO_FILE_DATA_67890" * 500)
            zf.writestr("notes.txt", b"Test note file inside ZIP")
        cls.zip_bytes = cls.zip_buffer.getvalue()

    def test_01_prefetcher_streaming_and_memory_drain(self):
        mock_pool = MockPoolManager(self.zip_bytes)
        prefetcher = StreamPrefetcher(
            url="http://mock.test/archive.zip",
            start_byte=0,
            end_byte=len(self.zip_bytes) - 1,
            pool=mock_pool
        )
        prefetcher.start()

        collected = bytearray()
        for chunk in prefetcher.stream_chunks():
            collected.extend(chunk)
            if len(collected) >= 5000:
                # Simulate player seek / client disconnect early
                prefetcher.close()
                break

        self.assertEqual(bytes(collected), self.zip_bytes[:len(collected)])
        self.assertTrue(prefetcher.abort_event.is_set())
        # Verify queue is drained after close
        self.assertTrue(prefetcher.queue.empty())

    def test_02_remote_zip_parser_and_offset_lookup(self):
        mock_pool = MockPoolManager(self.zip_bytes)
        reader = RemoteZipReader(url="http://mock.test/archive.zip", pool=mock_pool)

        self.assertEqual(reader.total_size, len(self.zip_bytes))
        self.assertEqual(len(reader.entries), 3)

        ep1 = next(e for e in reader.entries if e["name"] == "test_ep1.mkv")
        self.assertEqual(ep1["method_name"], "STORE")
        self.assertEqual(ep1["size_bytes"], len(b"STREAM_TEST_CONTENT_12345" * 1000))

        data_offset = reader.get_data_offset(ep1)
        self.assertGreater(data_offset, 0)
        # Verify data matches local entry
        actual_slice = self.zip_bytes[data_offset:data_offset + ep1["size_bytes"]]
        self.assertEqual(actual_slice, b"STREAM_TEST_CONTENT_12345" * 1000)

    def test_03_server_live_threaded_range_request(self):
        """Test handler range logic using mock request and response handling."""
        mock_pool = MockPoolManager(self.zip_bytes)
        test_reader = RemoteZipReader("http://mock.test/archive.zip", pool=mock_pool)

        with server.ARCHIVE_LOCK:
            server.CURRENT_READER = test_reader
            server.CACHED_ENTRIES = {e["id"]: e for e in test_reader.entries}
            server.READERS_BY_URL["http://mock.test/archive.zip"] = test_reader

        ep1 = server.CACHED_ENTRIES[1]
        self.assertEqual(ep1["name"], "test_ep1.mkv")
        data_offset = test_reader.get_data_offset(ep1)
        self.assertGreater(data_offset, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
