import struct
import io
import gc
import pytest
from unittest.mock import MagicMock
from urllib3.response import HTTPResponse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import RemoteZipReader


class MockZipRangePool:
    """Mock urllib3.PoolManager responding with crafted byte ranges representing ZIP/ZIP64 archives."""
    def __init__(self, raw_zip_data: bytes):
        self.raw_zip_data = raw_zip_data

    def request(self, method: str, url: str, headers: dict = None, preload_content: bool = True):
        headers = headers or {}
        range_header = headers.get("Range", "")
        
        if range_header == "bytes=0-0":
            return HTTPResponse(
                body=self.raw_zip_data[0:1],
                status=206,
                headers={"Content-Range": f"bytes 0-0/{len(self.raw_zip_data)}", "Content-Length": "1"}
            )
        
        if range_header.startswith("bytes="):
            range_spec = range_header.replace("bytes=", "").strip()
            parts = range_spec.split("-")
            start = int(parts[0]) if parts[0] else 0
            end = int(parts[1]) if parts[1] else len(self.raw_zip_data) - 1
            end = min(end, len(self.raw_zip_data) - 1)
            chunk = self.raw_zip_data[start:end + 1]
            return HTTPResponse(
                body=chunk,
                status=206,
                headers={"Content-Range": f"bytes {start}-{end}/{len(self.raw_zip_data)}", "Content-Length": str(len(chunk))}
            )

        return HTTPResponse(
            body=self.raw_zip_data,
            status=200,
            headers={"Content-Length": str(len(self.raw_zip_data))}
        )


def build_synthetic_standard_zip(filename="video.mkv", file_data=b"HELLO_WORLD_VIDEO_CONTENT"):
    """Builds an in-memory valid standard ZIP archive with 1 stored entry."""
    file_bytes = file_data
    file_size = len(file_bytes)
    name_bytes = filename.encode("utf-8")
    
    # 1. Local File Header
    # Signature: PK\x03\x04
    # version: 20, flags: 0, method: 0 (STORE), mtime: 0, mdate: 0, crc32: 0, comp: size, uncomp: size, name_len: len, extra_len: 0
    local_hdr = struct.pack(
        "<4sHHHHHIIIHH",
        b"PK\x03\x04", 20, 0, 0, 0, 0, 0x12345678, file_size, file_size, len(name_bytes), 0
    ) + name_bytes
    
    local_offset = 0
    file_content_offset = len(local_hdr)
    
    # 2. Central Directory Header
    # Signature: PK\x01\x02
    cd_hdr = struct.pack(
        "<4sHHHHHHIIIHHHHHII",
        b"PK\x01\x02", 20, 20, 0, 0, 0, 0, 0x12345678, file_size, file_size, len(name_bytes), 0, 0, 0, 0, 0, local_offset
    ) + name_bytes
    
    cd_offset = len(local_hdr) + len(file_bytes)
    cd_size = len(cd_hdr)
    
    # 3. EOCD
    # Signature: PK\x05\x06
    eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06", 0, 0, 1, 1, cd_size, cd_offset, 0
    )
    
    full_zip = local_hdr + file_bytes + cd_hdr + eocd
    return full_zip, file_content_offset, file_size


def build_synthetic_zip64(filename="huge_movie.mkv", file_size=0x120000000, file_content_stub=b"HUGE_MKV_HEADER_12345"):
    """Builds a mock ZIP64 structure containing ZIP64 EOCD Locator + ZIP64 EOCD Record + Extra Field 0x0001."""
    name_bytes = filename.encode("utf-8")
    
    # 1. Local File Header with 0xFFFFFFFF indicator for ZIP64 or standard stub
    local_hdr = struct.pack(
        "<4sHHHHHIIIHH",
        b"PK\x03\x04", 45, 0, 0, 0, 0, 0x99999999, 0xFFFFFFFF, 0xFFFFFFFF, len(name_bytes), 0
    ) + name_bytes
    
    local_offset = 0
    data_start = len(local_hdr)
    
    # Pad or simulate file payload space
    # For mock in-memory, we can place a small byte sequence and position CD at higher simulated offset
    file_bytes = file_content_stub
    
    # ZIP64 Extra field (tag 0x0001, size 24 bytes: uncomp 8B, comp 8B, local_offset 8B)
    zip64_extra = struct.pack(
        "<HHQQQ",
        0x0001, 24, file_size, file_size, local_offset
    )
    
    # 2. Central Directory Header
    cd_hdr = struct.pack(
        "<4sHHHHHHIIIHHHHHII",
        b"PK\x01\x02", 45, 45, 0, 0, 0, 0, 0x99999999, 0xFFFFFFFF, 0xFFFFFFFF, len(name_bytes), len(zip64_extra), 0, 0, 0, 0, 0xFFFFFFFF
    ) + name_bytes + zip64_extra
    
    cd_offset = len(local_hdr) + len(file_bytes)
    cd_size = len(cd_hdr)
    
    # 3. ZIP64 End of Central Directory Record
    # Signature: PK\x06\x06
    # rec_size: 44, v_made: 45, v_need: 45, d_num: 0, cd_disk: 0, n_disk: 1, n_total: 1, cd_size, cd_offset
    zip64_eocd_rec = struct.pack(
        "<4sQHHIIQQQQ",
        b"PK\x06\x06", 44, 45, 45, 0, 0, 1, 1, cd_size, cd_offset
    )
    zip64_eocd_rec_offset = cd_offset + cd_size
    
    # 4. ZIP64 End of Central Directory Locator
    # Signature: PK\x06\x07
    # disk_num: 0, end_rec_offset, total_disks: 1
    zip64_locator = struct.pack(
        "<4sIQI",
        b"PK\x06\x07", 0, zip64_eocd_rec_offset, 1
    )
    
    # 5. Standard EOCD (with 0xFFFF / 0xFFFFFFFF fields)
    eocd = struct.pack(
        "<4sHHHHIIH",
        b"PK\x05\x06", 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0
    )
    
    full_zip = local_hdr + file_bytes + cd_hdr + zip64_eocd_rec + zip64_locator + eocd
    return full_zip, data_start, file_size


def test_standard_zip_parsing():
    """Verify parsing standard 32-bit ZIP file headers and entry extraction."""
    zip_bytes, expected_data_offset, expected_size = build_synthetic_standard_zip("test_episode_01.mkv", b"TEST_MKV_BYTES_123")
    mock_pool = MockZipRangePool(zip_bytes)

    reader = RemoteZipReader(url="http://mock.test/archive.zip", pool=mock_pool)

    assert len(reader.entries) == 1
    entry = reader.entries[0]
    assert entry["name"] == "test_episode_01.mkv"
    assert entry["size_bytes"] == expected_size
    assert entry["method_name"] == "STORE"

    data_offset = reader.get_data_offset(entry)
    assert data_offset == expected_data_offset


def test_zip64_extended_parsing():
    """Verify ZIP64 parsing: ZIP64 EOCD Locator, ZIP64 EOCD Record, and 64-bit size/offset extra fields."""
    huge_size = 5_000_000_000  # ~5 GB
    zip_bytes, expected_data_offset, expected_size = build_synthetic_zip64("movie_4k_hdr.mkv", file_size=huge_size)
    mock_pool = MockZipRangePool(zip_bytes)

    reader = RemoteZipReader(url="http://mock.test/archive_zip64.zip", pool=mock_pool)

    assert len(reader.entries) == 1
    entry = reader.entries[0]
    assert entry["name"] == "movie_4k_hdr.mkv"
    assert entry["size_bytes"] == huge_size
    assert entry["size_gb"] == round(huge_size / (1024 ** 3), 2)

    data_offset = reader.get_data_offset(entry)
    assert data_offset == expected_data_offset


def test_zip_invalid_archive_handling():
    """Verify proper exceptions on invalid archives or missing EOCD signatures."""
    corrupt_bytes = b"CORRUPT_NOT_A_ZIP_FILE_DATA_PADDING_12345"
    mock_pool = MockZipRangePool(corrupt_bytes)

    with pytest.raises(ValueError, match="Valid ZIP End of Central Directory record not found"):
        RemoteZipReader(url="http://mock.test/corrupt.zip", pool=mock_pool)


def test_zip64_memory_stress():
    """Stress test parser instantiation and entry extraction for memory cleanliness."""
    gc.collect()
    start_objects = len(gc.get_objects())

    huge_size = 10_000_000_000  # 10 GB
    zip_bytes, _, _ = build_synthetic_zip64("stress_test.mkv", file_size=huge_size)
    mock_pool = MockZipRangePool(zip_bytes)

    for _ in range(100):
        reader = RemoteZipReader(url="http://mock.test/archive_zip64.zip", pool=mock_pool)
        assert len(reader.entries) == 1
        entry = reader.entries[0]
        offset = reader.get_data_offset(entry)
        assert offset > 0
        del reader

    gc.collect()
    end_objects = len(gc.get_objects())
    assert abs(end_objects - start_objects) < 200
