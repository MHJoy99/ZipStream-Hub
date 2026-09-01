# 🎬 Beginner's Guide to ZipStreamHub (Zero Coding Required!)

Welcome to **ZipStreamHub**! This guide will teach you how to watch videos locked inside cloud ZIP files instantly, without waiting hours for them to download to your computer.

---

## 🌟 What Does ZipStreamHub Do?

Imagine a friend shares a **50 GB ZIP file** containing a whole season of your favorite TV show.
- **Old Way**: Wait 3 hours to download 50 GB $\to$ Wait 15 minutes to extract $\to$ Fill up your hard drive $\to$ Finally watch.
- **ZipStreamHub Way**: Paste the link $\to$ Click **Play** $\to$ Starts streaming in **0.6 seconds**! No disk space used!

```
[Remote ZIP on Cloud]  ─────────►  [ZipStreamHub Engine]  ─────────►  [Your Video Player (PotPlayer/VLC/MPV)]
   (50 GB on Web)                   (Virtual Stream Bridge)                  (Instant 4K Playback)
```

---

## 🚀 3 Easy Steps to Start Streaming

### Step 1: Start ZipStreamHub
1. Open the `ZipStreamHub` folder on your computer.
2. Double-click **`launch_zipstream.vbs`** (or open `server.py`).
3. Your web browser will open automatically to the ZipStreamHub Dashboard at `http://127.0.0.1:8787`.

---

### Step 2: Paste Your ZIP Link
1. Copy the direct link to any ZIP file (e.g. from Google Drive, Dropbox, or your private server).
2. Paste the URL into the **"Enter Remote ZIP URL"** box.
3. Click **"Inspect Archive"** 🔍.

```
┌────────────────────────────────────────────────────────────────────────┐
│  Remote ZIP Link: [ https://example.com/Anime_Season1.zip            ] │
│                                                                        │
│  [ 🔍 Inspect Archive ]                                                │
└────────────────────────────────────────────────────────────────────────┘
```

In less than 1 second, the dashboard will list all episodes with their file sizes!

---

### Step 3: Click & Watch!
- Click the **"▶ Play in PotPlayer"** or **"▶ Play in VLC"** button next to any episode.
- Your media player will immediately pop up and start playing the video!
- You can fast-forward, rewind, and skip chapters just like a video stored directly on your computer!

---

## 💡 Frequently Asked Questions

#### Q: Does this use up my computer's hard drive space?
**A:** No! ZipStreamHub only holds a tiny 32MB streaming buffer in memory while playing. 0 bytes are saved to your drive.

#### Q: Which video players are supported?
**A:** Any modern media player works! We recommend **PotPlayer** (Windows), **MPV** (Windows/Mac/Linux), or **VLC**.

#### Q: Why can't I seek on some ZIP files?
**A:** For instant seeking, the ZIP file must be packed with **Store (0% compression)** mode. Most video files (like `.mkv` and `.mp4`) are already compressed, so ZIP files with Store mode are identical in size but stream 10x faster!

---

## 🎁 Summary Checklist

- [x] Launch `ZipStreamHub`
- [x] Paste the direct ZIP link
- [x] Inspect & click Play
- [x] Enjoy your show! 🍿
