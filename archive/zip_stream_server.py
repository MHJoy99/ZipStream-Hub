import http.server
import socketserver
import ssl
import sys
import os
import subprocess
from zip_stream_engine import RemoteZipReader, StreamPrefetcher, HTTP_POOL

PORT = 8787

class ZipStreamHandler(http.server.BaseHTTPRequestHandler):
    reader: RemoteZipReader = None
    target_entry = None
    data_start_offset: int = 0
    file_total_size: int = 0

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", "video/x-matroska")
        self.send_header("Content-Length", str(self.file_total_size))
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range")
        
        if not range_header:
            # Full file requested or stream start
            start_byte = 0
            end_byte = self.file_total_size - 1
            status_code = 200
        else:
            # Range request from player (e.g. PotPlayer seek)
            range_val = range_header.strip().replace("bytes=", "")
            if range_val.startswith("-"):
                # Suffix range
                suffix = int(range_val[1:])
                start_byte = max(0, self.file_total_size - suffix)
                end_byte = self.file_total_size - 1
            elif "-" in range_val:
                parts = range_val.split("-")
                start_byte = int(parts[0])
                end_byte = int(parts[1]) if parts[1] else self.file_total_size - 1
            else:
                start_byte = int(range_val)
                end_byte = self.file_total_size - 1
            status_code = 206

        content_length = end_byte - start_byte + 1

        # Map to remote ZIP offset
        remote_start = self.data_start_offset + start_byte
        remote_end = self.data_start_offset + end_byte

        self.send_response(status_code)
        self.send_header("Content-Type", "video/x-matroska")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(content_length))
        if status_code == 206:
            self.send_header("Content-Range", f"bytes {start_byte}-{end_byte}/{self.file_total_size}")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # High-Throughput Streaming with Read-Ahead Prefetch Buffer
        prefetcher = StreamPrefetcher(
            url=self.reader.url,
            start_byte=remote_start,
            end_byte=remote_end,
            pool=HTTP_POOL
        )
        prefetcher.start()

        try:
            for chunk in prefetcher.stream_chunks():
                self.wfile.write(chunk)
        except (ConnectionResetError, BrokenPipeError):
            # Player sought to a new location or closed connection
            pass
        except Exception:
            pass
        finally:
            prefetcher.close()

    def log_message(self, format, *args):
        # Concise logging for range requests
        sys.stdout.write(f"[HTTP] {self.address_string()} - {format%args}\n")
        sys.stdout.flush()

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def start_stream_server(url: str, episode_index: int = 1):
    print(f"[*] Reading remote ZIP header metadata from URL...")
    reader = RemoteZipReader(url)
    
    if episode_index < 1 or episode_index > len(reader.entries):
        print(f"[!] Invalid episode index. Available: 1 to {len(reader.entries)}")
        return

    entry = reader.entries[episode_index - 1]
    data_start = reader.get_data_offset(entry)
    
    print(f"\n[+] Selected Episode: {entry['name']}")
    print(f"[+] File Size: {entry['size_gb']} GB ({entry['size_bytes']} bytes)")
    print(f"[+] Mode: {entry['method_name']} (Direct 1:1 byte translation)")
    print(f"[+] ZIP Byte Offset: {data_start}")

    ZipStreamHandler.reader = reader
    ZipStreamHandler.target_entry = entry
    ZipStreamHandler.data_start_offset = data_start
    ZipStreamHandler.file_total_size = entry["size_bytes"]

    stream_url = f"http://127.0.0.1:{PORT}/stream/{episode_index}/{entry['name']}"
    print(f"\n🚀 Direct Stream URL ready: {stream_url}")

    # Check PotPlayer
    potplayer_paths = [
        r"C:\Program Files\DAUM\PotPlayer\PotPlayerMini64.exe",
        r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayerMini.exe",
        r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe"
    ]
    pot_exe = next((p for p in potplayer_paths if os.path.exists(p)), None)

    if pot_exe:
        print(f"[+] Found PotPlayer at: {pot_exe}")
        print(f"[+] Launching PotPlayer with stream...")
        subprocess.Popen([pot_exe, stream_url])
    else:
        print("[!] PotPlayer not detected in standard path, you can open the stream URL manually in any player.")

    print(f"\n[*] Server listening on http://127.0.0.1:{PORT} (Press Ctrl+C to stop)...")
    server = ThreadedHTTPServer(("127.0.0.1", PORT), ZipStreamHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping server.")
        server.shutdown()

if __name__ == "__main__":
    test_url = "https://motionpicturepro55.mhjoybots.workers.dev/0:findpath?id=1C_oTML7by_QacdPcO6nQ7_jxPDjxygPy"
    ep_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    start_stream_server(test_url, ep_num)
