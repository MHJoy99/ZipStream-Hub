import sys
import os
from zip_stream_engine import RemoteZipReader
from zip_stream_server import start_stream_server

def main():
    print("==========================================================")
    print("       ⚡ REMOTE ZIP DIRECT STREAM & EPISODE PLAYER ⚡      ")
    print("==========================================================")
    
    if len(sys.argv) > 1:
        zip_url = sys.argv[1]
    else:
        zip_url = input("\nEnter Remote ZIP URL: ").strip()

    if not zip_url:
        zip_url = "https://motionpicturepro55.mhjoybots.workers.dev/0:findpath?id=1C_oTML7by_QacdPcO6nQ7_jxPDjxygPy"
        print(f"Using default URL: {zip_url}")

    print("\n[*] Scanning ZIP Central Directory in < 2 seconds...")
    try:
        reader = RemoteZipReader(zip_url)
    except Exception as e:
        print(f"[!] Error parsing ZIP: {e}")
        return

    print(f"\n[✓] Archive parsed successfully! Total Archive Size: {reader.total_size / (1024**3):.2f} GB")
    print(f"[✓] Found {len(reader.entries)} files:\n")

    for e in reader.entries:
        print(f"  [{e['id']}] {e['name']}")
        print(f"      Size: {e['size_gb']} GB | Compression: {e['method_name']}")

    print("\n----------------------------------------------------------")
    while True:
        try:
            choice = input(f"Enter episode number to stream (1-{len(reader.entries)}) or 'q' to quit: ").strip()
            if choice.lower() == 'q':
                return
            ep_idx = int(choice)
            if 1 <= ep_idx <= len(reader.entries):
                break
            print(f"Please enter a number between 1 and {len(reader.entries)}.")
        except ValueError:
            print("Invalid input.")

    print("\n" + "="*58)
    start_stream_server(zip_url, ep_idx)

if __name__ == "__main__":
    main()
