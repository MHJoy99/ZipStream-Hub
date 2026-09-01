# 🗂️ WebDAV Network Drive & Infuse / Kodi Streaming Guide

**ZipStreamHub** features an integrated **RFC 4918 WebDAV Server & Range Proxy** operating at `http://127.0.0.1:8787/webdav/`.

This allows mounting remote cloud ZIP/ZIP64 archives directly as virtual network drives in **Windows File Explorer**, macOS Finder, Linux (davfs2), and streaming them natively with **Infuse (Apple TV / iOS / macOS)** and **Kodi**.

---

## 📑 Table of Contents
1. [WebDAV Architecture & Capabilities](#-webdav-architecture--capabilities)
2. [Mounting in Windows File Explorer (Network Drive)](#-mounting-in-windows-file-explorer-network-drive)
3. [Infuse Setup (Apple TV, iOS, iPadOS, macOS)](#-infuse-setup-apple-tv-ios-ipados-macos)
4. [Kodi WebDAV Source Setup](#-kodi-webdav-source-setup)
5. [macOS Finder & Linux Mounting](#-macos-finder--linux-mounting)
6. [Web Browser HTML Directory View](#-web-browser-html-directory-view)
7. [Troubleshooting & Windows Registry Fix](#-troubleshooting--windows-registry-fix)

---

## 🏗️ WebDAV Architecture & Capabilities

The ZipStreamHub WebDAV bridge implements standard HTTP and WebDAV specifications:

```
┌────────────────────────────────────────────────────────────────────────┐
│               Client (Windows Explorer / Infuse / Kodi)                │
│       Sends PROPFIND / GET / HEAD / OPTIONS to /webdav/                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ZipStreamHub WebDAV Bridge                           │
│   - Responds with RFC 4918 Multistatus XML (<D:multistatus>)           │
│   - Translates virtual paths to archive Entry IDs                      │
│   - Streams media via HTTP 206 Partial Content Range prefetcher        │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Remote Cloud ZIP / ZIP64 Archive Storage                 │
└────────────────────────────────────────────────────────────────────────┘
```

### Supported WebDAV Methods:
- **`OPTIONS`**: Returns DAV compliance headers (`DAV: 1, 2`, `MS-Author-Via: DAV`).
- **`PROPFIND`**: Returns RFC 4918 multistatus XML directory tree (files, folders, sizes, timestamps, MIME types) for Depth `0`, `1`, or `infinity`.
- **`HEAD`**: Returns file headers, `Content-Length`, and `Accept-Ranges: bytes`.
- **`GET`**: 
  - On directories: Renders an HTML directory listing with direct stream and download links.
  - On media files: Transparently streams file content via sliding-window byte-range prefetching.

---

## 🪟 Mounting in Windows File Explorer (Network Drive)

You can assign a Windows drive letter (e.g. `Z:`) directly to the virtual ZIP contents.

### Step 1: Open "Map Network Drive"
1. Open **File Explorer** (`Win + E`).
2. Right-click **This PC** $\to$ select **Map network drive...** (or click **Computer** ribbon $\to$ **Map network drive**).

### Step 2: Configure WebDAV Connection
1. **Drive:** Choose an available letter (e.g., `Z:`).
2. **Folder:** Enter the ZipStreamHub WebDAV URL:
   ```
   http://127.0.0.1:8787/webdav/
   ```
   *(Or for LAN access: `http://192.168.1.100:8787/webdav/`)*
3. Check **Reconnect at sign-in** if desired.
4. Click **Finish**.

### Step 3: Command Line Mounting (Alternative)
You can also mount or unmount via Windows Command Prompt / PowerShell:

```cmd
:: Map drive Z: to WebDAV
net use Z: http://127.0.0.1:8787/webdav

:: Disconnect mapped drive
net use Z: /delete
```

Now you can browse folders inside the cloud archive, double-click to play in PotPlayer/VLC, or view file properties just like a local hard drive.

---

## 🍎 Infuse Setup (Apple TV, iOS, iPadOS, macOS)

**Infuse** by Firecore is one of the most powerful media players for the Apple ecosystem, featuring native WebDAV direct streaming, Dolby Vision, and HDR10+ support.

### Step-by-Step Configuration:

1. **Launch Infuse** on your Apple TV, iPhone, iPad, or Mac.
2. Go to **Settings** $\to$ **Add Files** (or **Shares**).
3. Under **Network Shares**, tap **Add WebDAV...** (or **Other...** $\to$ **WebDAV**).
4. Enter your connection details:
   - **Protocol:** `WebDAV (HTTP)`
   - **Name:** `ZipStreamHub`
   - **Address / Host:** `127.0.0.1` (or your PC's LAN IP address, e.g., `192.168.1.100`)
   - **Port:** `8787`
   - **Path:** `/webdav/`
   - **Username:** *(Leave blank / Anonymous)*
   - **Password:** *(Leave blank / Anonymous)*
5. Tap **Save** / **Done**.
6. Infuse will connect, index the video files, fetch metadata from TMDb, and present movie posters and episode lists.
7. Click any file to begin instant, zero-buffer playback.

---

## 📺 Kodi WebDAV Source Setup

Kodi supports WebDAV directories as native media sources.

### Step-by-Step Configuration:

1. Open **Kodi** $\to$ Go to **Settings (Gear Icon)** $\to$ **Media** $\to$ **Library** $\to$ **Videos...**
2. Select **Add videos...** $\to$ Click **Browse**.
3. Scroll down and select **Add network location...**
4. Configure the network location dialog:
   - **Protocol:** `WebDAV server (HTTP)`
   - **Server address:** `127.0.0.1` (or your LAN IP, e.g. `192.168.1.100`)
   - **Remote path:** `webdav/`
   - **Port:** `8787`
   - **Username:** *(Leave blank)*
   - **Password:** *(Leave blank)*
5. Click **OK**.
6. Select the newly created WebDAV source (e.g., `dav://127.0.0.1:8787/webdav/`).
7. Assign content type (`Movies` or `TV Shows`) and select scrapers (*The Movie Database*).
8. Kodi scans the virtual archive and integrates all media into your main library.

---

## 🐧 macOS Finder & Linux Mounting

### macOS Finder:
1. Open Finder $\to$ Press `Cmd + K` (or click **Go** $\to$ **Connect to Server...**).
2. Enter: `http://127.0.0.1:8787/webdav/`
3. Click **Connect** $\to$ Select **Guest / Anonymous**.
4. The virtual archive volume mounts on your Desktop and Finder sidebar.

### Linux (davfs2):
```bash
sudo apt install davfs2
sudo mkdir -p /mnt/zipstream
sudo mount -t davfs http://127.0.0.1:8787/webdav/ /mnt/zipstream -o noauth
```

---

## 🌐 Web Browser HTML Directory View

When navigating to `http://127.0.0.1:8787/webdav/` inside any standard web browser (Chrome, Firefox, Edge, Safari):
- ZipStreamHub serves a styled HTML Directory Listing.
- Displays file names, folder hierarchies, exact file sizes in MB/GB, and last modified dates.
- Provides 1-click links to stream or download individual files directly.

---

## 🔧 Troubleshooting & Windows Registry Fix

### 1. Windows File Explorer: "The folder you entered does not appear to be valid"
Windows WebClient service by default blocks unencrypted HTTP Basic authentication on non-HTTPS WebDAV servers. Because ZipStreamHub is a zero-auth local stream server, adjust the `BasicAuthLevel` registry key:

1. Press `Win + R` $\to$ type `regedit` $\to$ press Enter.
2. Navigate to:
   ```
   HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\WebClient\Parameters
   ```
3. Find or create DWORD (32-bit) value:
   - Name: `BasicAuthLevel`
   - Value: `2` *(Enables HTTP & HTTPS WebDAV)*
4. Restart the WebClient service via PowerShell as Administrator:
   ```powershell
   Restart-Service WebClient
   ```

### 2. Windows 50MB File Size Copy Limit (Error 0x800700DF)
Windows WebClient default file size transfer limit is 50MB. For streaming or copying large media files:
1. In `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\WebClient\Parameters`:
2. Find `FileSizeLimitInBytes`.
3. Set value to `4294967295` (Decimal) or `ffffffff` (Hex) for 4GB (or up to maximum supported).
4. Restart the `WebClient` service.
