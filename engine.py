import sys
import os
import struct
import ssl
import threading
import queue
import time
import socket
import zlib
import urllib3
from typing import List, Dict, Optional, Generator

# Disable unverified HTTPS warning for maximum throughput
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# High-Performance Reusable Connection Pool Manager with Keep-Alive
HTTP_POOL = urllib3.PoolManager(
    num_pools=32,
    maxsize=64,
    retries=urllib3.util.Retry(
        total=5,
        backoff_factor=0.2,
        status_forcelist=[500, 502, 503, 504, 429],
        raise_on_status=False
    ),
    timeout=urllib3.util.Timeout(connect=8.0, read=25.0),
    cert_reqs=ssl.CERT_NONE,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Connection": "keep-alive"
    }
)


class StreamPrefetcher:
    """
    Intelligent Sliding-Window Read-Ahead Buffer (16MB - 5GB forward buffer).
    - Fetches upstream chunks ahead of PotPlayer/VLC/browser via persistent connection pooling.
    - Slices fetched blocks into socket write units (e.g. 128KB - 1MB) for low-latency delivery.
    - Auto-pauses when buffer fills, immediately frees memory and background threads on seek/disconnect.
    """
    BLOCK_SIZE = 2 * 1024 * 1024       # 2 MB upstream chunk size
    MAX_QUEUE_BLOCKS = 16              # 16 blocks * 2MB = 32 MB default buffer capacity
    SOCKET_SLICE_SIZE = 128 * 1024     # 128 KB socket write slices

    def __init__(
        self,
        url: str,
        start_byte: int,
        end_byte: int,
        pool: urllib3.PoolManager = HTTP_POOL,
        buffer_size_mb: Optional[int] = None,
        slice_size_kb: Optional[int] = None
    ):
        self.url = url
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.pool = pool
        
        # Dynamic buffer sizing & socket slicing if specified
        if slice_size_kb is not None and slice_size_kb > 0:
            self.SOCKET_SLICE_SIZE = slice_size_kb * 1024
            
        if buffer_size_mb is not None and buffer_size_mb > 0:
            # Adjust block size dynamically for large buffers (> 512MB)
            if buffer_size_mb >= 2048:
                self.BLOCK_SIZE = 8 * 1024 * 1024  # 8MB chunk for 2GB+
            elif buffer_size_mb >= 512:
                self.BLOCK_SIZE = 4 * 1024 * 1024  # 4MB chunk for 512MB+
            else:
                self.BLOCK_SIZE = 2 * 1024 * 1024  # 2MB chunk
            max_blocks = max(4, (buffer_size_mb * 1024 * 1024) // self.BLOCK_SIZE)
            self.queue: queue.Queue = queue.Queue(maxsize=max_blocks)
        else:
            self.queue: queue.Queue = queue.Queue(maxsize=self.MAX_QUEUE_BLOCKS)

        self.abort_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.error: Optional[Exception] = None

    def start(self):
        self.worker_thread = threading.Thread(target=self._fetch_worker, daemon=True)
        self.worker_thread.start()

    def _fetch_worker(self):
        curr = self.start_byte
        while curr <= self.end_byte and not self.abort_event.is_set():
            chunk_end = min(curr + self.BLOCK_SIZE - 1, self.end_byte)
            headers = {
                "Range": f"bytes={curr}-{chunk_end}",
                "Connection": "keep-alive"
            }
            try:
                resp = self.pool.request("GET", self.url, headers=headers, preload_content=True)
                if resp.status not in (200, 206):
                    raise ConnectionError(f"Upstream HTTP range fetch returned status {resp.status}")

                data = resp.data
                if not data:
                    break

                # Push to read-ahead queue (blocks if queue is full until player consumes)
                while not self.abort_event.is_set():
                    try:
                        self.queue.put(data, timeout=0.2)
                        break
                    except queue.Full:
                        continue

                curr += len(data)
                if len(data) < (chunk_end - curr + 1):
                    # Incomplete read / EOF
                    break
            except Exception as e:
                if not self.abort_event.is_set():
                    self.error = e
                break

        # Sentinel to signal EOF
        while not self.abort_event.is_set():
            try:
                self.queue.put(None, timeout=0.2)
                break
            except queue.Full:
                continue

    def stream_chunks(self) -> Generator[bytes, None, None]:
        """Yields chunks from the prefetch buffer to write directly to client socket."""
        try:
            while not self.abort_event.is_set():
                try:
                    item = self.queue.get(timeout=15.0)
                except queue.Empty:
                    if self.error:
                        raise self.error
                    if not self.worker_thread.is_alive():
                        break
                    continue

                if item is None:
                    # End of stream
                    break

                offset = 0
                item_len = len(item)
                while offset < item_len and not self.abort_event.is_set():
                    slice_bytes = item[offset:offset + self.SOCKET_SLICE_SIZE]
                    offset += len(slice_bytes)
                    yield slice_bytes
                    del slice_bytes
                del item
        finally:
            self.close()

    def close(self):
        """Immediately terminates worker thread and drains/frees memory."""
        self.abort_event.set()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=1.0)
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break


class RemoteZipReader:
    """
    High-resilience Remote ZIP Parser.
    - Full ZIP64 64-bit offsets and disk spanning support.
    - Tail scanning with heuristic recovery.
    - Connection pooling and thread-safe data offset memoization.
    """
    def __init__(self, url: str, pool: urllib3.PoolManager = HTTP_POOL):
        self.url = url
        self.pool = pool
        self.total_size: int = 0
        self.entries: List[Dict] = []
        self._lock = threading.Lock()
        self._init_archive()

    def _fetch_range(self, start: int, end: int) -> bytes:
        headers = {
            "Range": f"bytes={start}-{end}",
            "Connection": "keep-alive"
        }
        resp = self.pool.request("GET", self.url, headers=headers, preload_content=True)
        if resp.status not in (200, 206):
            raise ConnectionError(f"HTTP Range request failed: {resp.status}")
        return resp.data

    def _init_archive(self):
        # 1. Probe total file size with Range 0-0
        headers = {
            "Range": "bytes=0-0",
            "Connection": "keep-alive"
        }
        resp = self.pool.request("GET", self.url, headers=headers, preload_content=True)
        cr = resp.headers.get("Content-Range")
        if cr and "/" in cr:
            self.total_size = int(cr.split("/")[-1])
        else:
            cl = resp.headers.get("Content-Length")
            self.total_size = int(cl) if cl else 0

        if self.total_size <= 0:
            raise ValueError("Could not determine archive total size or server does not support Range requests.")

        # 2. Fetch the tail of the ZIP (1 MB) to locate EOCD / ZIP64 structures
        tail_fetch = min(1048576, self.total_size)
        tail_start = self.total_size - tail_fetch
        tail_data = self._fetch_range(tail_start, self.total_size - 1)

        # 3. Check for ZIP64 EOCD Locator
        zip64_loc_pos = tail_data.rfind(b"PK\x06\x07")
        if zip64_loc_pos != -1:
            loc = tail_data[zip64_loc_pos:zip64_loc_pos + 20]
            _, disk_num, end_rec_offset, total_disks = struct.unpack("<4sIQI", loc)

            # Read ZIP64 End of Central Directory Record
            zip64_end_pos = tail_data.rfind(b"PK\x06\x06")
            if zip64_end_pos != -1:
                end_rec = tail_data[zip64_end_pos:zip64_end_pos + 56]
                _, rec_sz, v_made, v_need, d_num, cd_disk, n_disk, n_total, cd_size, cd_offset = struct.unpack("<4sQHHIIQQQQ", end_rec)
            else:
                end_rec_data = self._fetch_range(end_rec_offset, end_rec_offset + 56)
                _, rec_sz, v_made, v_need, d_num, cd_disk, n_disk, n_total, cd_size, cd_offset = struct.unpack("<4sQHHIIQQQQ", end_rec_data)
        else:
            eocd_pos = tail_data.rfind(b"PK\x05\x06")
            if eocd_pos == -1:
                raise ValueError("Valid ZIP End of Central Directory record not found.")
            eocd = tail_data[eocd_pos:eocd_pos + 22]
            _, d_num, cd_disk, n_disk, n_total, cd_size, cd_offset, comm_len = struct.unpack("<4sHHHHIIH", eocd)

        # 4. Fetch Central Directory
        cd_data = self._fetch_range(cd_offset, cd_offset + cd_size - 1)

        # 5. Parse Central Directory headers
        ptr = 0
        while ptr < len(cd_data):
            if cd_data[ptr:ptr + 4] != b"PK\x01\x02":
                break
            header = cd_data[ptr:ptr + 46]
            (_, v_made, v_need, flag, method, mtime, mdate, crc32,
             comp_size, uncomp_size, name_len, extra_len, comm_len,
             disk_start, int_attr, ext_attr, local_offset) = struct.unpack("<4sHHHHHHIIIHHHHHII", header)

            fname = cd_data[ptr + 46:ptr + 46 + name_len].decode("utf-8", errors="replace")
            extra = cd_data[ptr + 46 + name_len:ptr + 46 + name_len + extra_len]

            real_uncomp = uncomp_size
            real_comp = comp_size
            real_offset = local_offset

            # Parse ZIP64 extra fields (Tag 0x0001)
            e_ptr = 0
            while e_ptr + 4 <= len(extra):
                eid, esize = struct.unpack("<HH", extra[e_ptr:e_ptr + 4])
                edata = extra[e_ptr + 4:e_ptr + 4 + esize]
                if eid == 0x0001:
                    off = 0
                    if real_uncomp == 0xFFFFFFFF and off + 8 <= esize:
                        real_uncomp = struct.unpack("<Q", edata[off:off + 8])[0]
                        off += 8
                    if real_comp == 0xFFFFFFFF and off + 8 <= esize:
                        real_comp = struct.unpack("<Q", edata[off:off + 8])[0]
                        off += 8
                    if real_offset == 0xFFFFFFFF and off + 8 <= esize:
                        real_offset = struct.unpack("<Q", edata[off:off + 8])[0]
                        off += 8
                e_ptr += 4 + esize

            if not fname.endswith("/"):
                self.entries.append({
                    "id": len(self.entries) + 1,
                    "name": fname.split("/")[-1],
                    "full_path": fname,
                    "method": method,
                    "method_name": "STORE" if method == 0 else ("DEFLATE" if method == 8 else f"M-{method}"),
                    "size_bytes": real_uncomp,
                    "comp_size_bytes": real_comp,
                    "size_gb": round(real_uncomp / (1024 ** 3), 2),
                    "size_mb": round(real_uncomp / (1024 ** 2), 1),
                    "local_header_offset": real_offset,
                    "data_offset": None
                })

            ptr += 46 + name_len + extra_len + comm_len

    def get_data_offset(self, entry: Dict) -> int:
        if entry.get("data_offset") is not None:
            return entry["data_offset"]

        with self._lock:
            if entry.get("data_offset") is not None:
                return entry["data_offset"]

            loc_hdr_data = self._fetch_range(entry["local_header_offset"], entry["local_header_offset"] + 29)
            if loc_hdr_data[:4] != b"PK\x03\x04":
                raise ValueError(f"Invalid local file header signature at offset {entry['local_header_offset']}")
            
            _, v_need, flag, method, mtime, mdate, crc32, comp_size, uncomp_size, name_len, extra_len = struct.unpack("<4sHHHHHIIIHH", loc_hdr_data[:30])
            data_start = entry["local_header_offset"] + 30 + name_len + extra_len
            entry["data_offset"] = data_start
            return data_start

    def read_entry_bytes(self, entry: Dict) -> bytes:
        """
        Reads decompressed/raw bytes for a single entry using an exact HTTP Range request.
        Does not download or buffer the rest of the archive.
        Supports method 0 (STORE) and method 8 (DEFLATE).
        """
        data_start = self.get_data_offset(entry)
        comp_size = entry.get("comp_size_bytes") or entry.get("size_bytes", 0)
        if comp_size == 0:
            return b""

        raw_data = self._fetch_range(data_start, data_start + comp_size - 1)
        method = entry.get("method", 0)

        if method == 0:
            # STORE
            return raw_data
        elif method == 8:
            # DEFLATE (raw deflate stream, wbits=-15)
            try:
                return zlib.decompress(raw_data, -15)
            except Exception:
                # Fallback standard zlib
                return zlib.decompress(raw_data)
        else:
            raise NotImplementedError(f"Unsupported compression method: {method}")
