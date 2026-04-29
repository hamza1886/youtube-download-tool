#!/usr/bin/env python3
"""
YouTube Download Tool - A comprehensive command-line utility for downloading YouTube videos.
Supports format selection, audio extraction, subtitle downloading and embedding.

Usage:
    python main.py https://www.youtube.com/watch?v=VIDEO_ID
    python main.py --audio-only https://www.youtube.com/watch?v=VIDEO_ID
    python main.py --subtitles --embed-subs https://www.youtube.com/watch?v=VIDEO_ID
    python main.py --simulate https://www.youtube.com/watch?v=VIDEO_ID

Author: Hamza Rashid
License: MIT
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Third-party imports — fail fast with clear instructions if missing
# ---------------------------------------------------------------------------
try:
    import yt_dlp
    from yt_dlp.utils import DownloadError, ExtractorError
except ImportError:
    print(
        "Error: yt-dlp is not installed.\n"
        "Fix:   pip install -U yt-dlp\n"
        "       or: pip install -r requirements.txt"
    )
    sys.exit(4)  # EXIT_MISSING_DEPENDENCY

try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False  # Graceful fallback to plain-text progress

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_DIR = os.path.join(os.getcwd(), 'downloads')

# Subtitle extensions we recognize and try to embed
SUPPORTED_SUBTITLE_EXTENSIONS = [".srt", ".vtt", ".ass", ".ssa"]

# yt-dlp format string that avoids the SABR/403 issue:
#   1. Prefer AVC (h264) video + m4a audio  → most stable CDN path
#   2. Fall back to any bestvideo+bestaudio pair
#   3. Final fallback: single best pre-muxed stream
SAFE_DEFAULT_FORMAT = (
    "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
    "bestvideo+bestaudio/best"
)

# HTTP chunk size (5 MiB) — smaller chunks reduce mid-stream 403 errors
HTTP_CHUNK_SIZE = 5 * 1024 * 1024

# JavaScript runtimes that yt-dlp can use to solve YouTube challenges,
# listed in order of preference (deno is recommended by yt-dlp upstream).
JS_RUNTIMES = ["deno", "node", "bun"]

# Exit codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_INVALID_INPUT = 3
EXIT_MISSING_DEP = 4


# ---------------------------------------------------------------------------
# Environment checks
# ---------------------------------------------------------------------------

def find_executable(name: str) -> Optional[str]:
    """
    Locate an executable on PATH using shutil.which().
    Returns the full path string or None.
    """
    return shutil.which(name)


def check_js_runtime() -> Optional[str]:
    """
    Find an installed JavaScript runtime that yt-dlp can use for YouTube's
    signature and n-parameter challenges.

    Returns:
        The name of the first available runtime (e.g. "deno"), or None if
        none are installed.
    """
    for rt in JS_RUNTIMES:
        if find_executable(rt):
            return rt
    return None


def print_js_runtime_instructions() -> None:
    """
    Print clear, cross-platform installation instructions for a JS runtime.
    """
    print(
        "\n"
        "╔══════════════════════════════════════════════════════════════╗\n"
        "║  A JavaScript runtime is required for YouTube downloads.   ║\n"
        "║  yt-dlp needs it to solve YouTube's signature challenges.  ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n"
        "\n"
        "Install ONE of the following (Deno is recommended):\n"
    )

    if sys.platform == "win32":
        print(
            "  Deno  (recommended):\n"
            "    irm https://deno.land/install.ps1 | iex\n"
            "      — or —\n"
            "    winget install DenoLand.Deno\n"
            "      — or —\n"
            "    choco install deno\n"
            "\n"
            "  Node.js:\n"
            "    winget install OpenJS.NodeJS.LTS\n"
            "      — or —\n"
            "    https://nodejs.org/en/download\n"
        )
    elif sys.platform == "darwin":
        print(
            "  Deno  (recommended):\n"
            "    brew install deno\n"
            "      — or —\n"
            "    curl -fsSL https://deno.land/install.sh | sh\n"
            "\n"
            "  Node.js:\n"
            "    brew install node\n"
        )
    else:  # Linux and others
        print(
            "  Deno  (recommended):\n"
            "    curl -fsSL https://deno.land/install.sh | sh\n"
            "      — or —\n"
            "    snap install deno\n"
            "\n"
            "  Node.js:\n"
            "    sudo apt install nodejs        # Debian/Ubuntu\n"
            "    sudo dnf install nodejs         # Fedora\n"
            "    sudo pacman -S nodejs           # Arch\n"
        )

    print(
        "After installing, restart your terminal so it appears on PATH,\n"
        "then re-run this script.\n"
    )


def check_ffmpeg() -> Optional[str]:
    """
    Locate ffmpeg.  Returns full path or None.
    Checks PATH first, then common Windows install locations.
    """
    path = find_executable("ffmpeg")
    if path:
        return path
    if sys.platform == "win32":
        for candidate in (
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ):
            if Path(candidate).exists():
                return candidate
    return None


# ---------------------------------------------------------------------------
# Progress hook
# ---------------------------------------------------------------------------

class ProgressHook:
    """
    yt-dlp progress callback.  Uses tqdm if available, otherwise prints
    a simple overwriting progress line.
    """

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self._pbar: Optional[tqdm] = None
        self._last_downloaded = 0

    # -- public interface ---------------------------------------------------

    def __call__(self, d: Dict) -> None:
        """Handle download progress updates."""
        if self.quiet:
            return

        status = d.get("status")
        if status == "downloading":
            self._on_downloading(d)
        elif status == "finished":
            self._on_finished()
        elif status == "error":
            self._close()
            print("\n  Download reported an error.", file=sys.stderr)

    # -- private helpers ----------------------------------------------------

    def _on_downloading(self, d: Dict) -> None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        downloaded = d.get("downloaded_bytes", 0)

        if TQDM_AVAILABLE:
            if self._pbar is None and total:
                self._pbar = tqdm(
                    total=total, unit="B", unit_scale=True,
                    unit_divisor=1024, desc="  Downloading",
                    ncols=90, leave=True,
                )
                self._last_downloaded = 0

            if self._pbar is not None:
                delta = downloaded - self._last_downloaded
                if delta > 0:
                    self._pbar.update(delta)
                    self._last_downloaded = downloaded
        else:
            # Simple overwriting line
            pct = d.get("_percent_str", "??%").strip()
            speed = d.get("_speed_str", "? B/s")
            eta = d.get("_eta_str", "?")
            print(f"\r  {pct:>6}  speed={speed}  eta={eta}   ", end="", flush=True)

    def _on_finished(self) -> None:
        self._close()
        if not TQDM_AVAILABLE:
            print()

    def _close(self) -> None:
        if self._pbar is not None:
            self._pbar.close()
            self._pbar = None


# ---------------------------------------------------------------------------
# Core downloader
# ---------------------------------------------------------------------------

class YouTubeDownloader:
    """
    Wraps yt-dlp to provide a clean interface for:
      - format listing (simulate / dry-run)
      - video+audio download with optional merge
      - audio-only download
      - subtitle download + optional ffmpeg embedding
    """

    def __init__(self, args: argparse.Namespace):
        """
        Initialize the downloader with command-line arguments.

        Args:
            args: Parsed command-line arguments
        """
        self.args = args
        self.output_dir = Path(args.output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Locate external tools
        self.ffmpeg_path = check_ffmpeg()
        self.js_runtime = check_js_runtime()

        # ---- Pre-flight warnings ------------------------------------------
        if self.ffmpeg_path is None:
            if args.merge or args.embed_subs or args.audio_only:
                print(
                    "Warning: ffmpeg not found.\n"
                    "         --merge, --embed-subs, and audio conversion disabled.\n"
                    "         Install ffmpeg from: https://ffmpeg.org/download.html\n"
                )

        if self.js_runtime is None:
            print_js_runtime_instructions()
            print(
                "Continuing anyway — but most formats will be unavailable,\n"
                "downloads may be throttled, and some videos will fail.\n"
            )
        else:
            if not args.quiet:
                print(f"  JS runtime : {self.js_runtime}")
                if self.ffmpeg_path:
                    print(f"  ffmpeg      : {self.ffmpeg_path}")
                print()

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    def run(self) -> int:
        """Process every URL and return a final exit code."""
        if self.args.simulate:
            for url in self.args.urls:
                self._list_formats(url)
                print()
            return EXIT_SUCCESS

        successes: int = 0
        failures: List[str] = []

        for url in self.args.urls:
            path = self._download(url)
            if path is not None:
                successes += 1
                print(f"  ✓  Saved to: {path}")
            else:
                failures.append(url)

        # Summary
        total = len(self.args.urls)
        print(f"\n{'=' * 60}")
        print(f"Summary: {successes}/{total} succeeded")
        if failures:
            print("Failed URLs:")
            for u in failures:
                print(f"  • {u}")

        return EXIT_SUCCESS if not failures else EXIT_GENERAL_ERROR

    # -----------------------------------------------------------------------
    # Format listing (simulate / dry-run)
    # -----------------------------------------------------------------------

    def _list_formats(self, url: str) -> None:
        """Print a table of every available format for *url*."""
        print(f"Fetching format list for:\n  {url}\n")

        ydl_opts: Dict = {
            "quiet": True,
            "no_warnings": False,
            "simulate": True,
        }
        # Enable JS challenge solving for format extraction too
        self._apply_js_challenge_opts(ydl_opts)

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except DownloadError as exc:
            print(f"Error fetching info: {exc}", file=sys.stderr)
            return

        print(f"Title    : {info.get('title', 'Unknown')}")
        print(f"Uploader : {info.get('uploader', 'Unknown')}")
        duration = info.get("duration", 0)
        mins, secs = divmod(int(duration), 60)
        print(f"Duration : {mins}m {secs:02d}s")

        formats = info.get("formats") or []

        # Build display rows
        rows = []
        for f in formats:
            fid = f.get("format_id", "?")
            ext = f.get("ext", "?")
            w, h = f.get("width"), f.get("height")
            res = f"{w}x{h}" if w and h else "audio"
            fps = f.get("fps") or ""
            fs = f.get("filesize") or f.get("filesize_approx")
            fs_str = _fmt_bytes(fs) if fs else "?"
            note = f.get("format_note") or ""
            vcodec = f.get("vcodec") or "none"
            acodec = f.get("acodec") or "none"

            if vcodec != "none" and acodec != "none":
                streams = "video+audio"
            elif vcodec != "none":
                streams = "video"
            else:
                streams = "audio"

            rows.append((fid, ext, res, str(fps), fs_str, streams, note))

        # Print table
        widths = (8, 5, 11, 5, 9, 12)
        header = ("ID", "EXT", "RESOLUTION", "FPS", "SIZE", "STREAMS", "NOTE")
        sep = "  ".join("-" * w for w in widths) + "  " + "-" * 20
        hdr = "  ".join(h.ljust(w) for h, w in zip(header[:-1], widths))
        hdr += f"  {header[-1]}"

        print(f"\n{hdr}\n{sep}")
        for row in rows:
            line = "  ".join(cell.ljust(w) for cell, w in zip(row[:-1], widths))
            line += f"  {row[-1]}"
            print(line)

        # Subtitles summary
        manual_subs = info.get("subtitles") or {}
        auto_subs = info.get("automatic_captions") or {}
        if manual_subs:
            print(f"\nManual subtitles    : {', '.join(sorted(manual_subs))}")
        if auto_subs:
            print(f"Auto-gen subtitles  : {', '.join(sorted(auto_subs))}")

    # -----------------------------------------------------------------------
    # Main download logic
    # -----------------------------------------------------------------------

    def _download(self, url: str) -> Optional[str]:
        """
        Download one URL.  Returns the final file path on success, else None.
        """
        if not self.args.quiet:
            print(f"\nDownloading: {url}")

        with tempfile.TemporaryDirectory(prefix="ytdl_") as tmp:
            ydl_opts = self._build_ydl_opts(tmp)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                    # For playlists, entries is a list; for single videos it's
                    # the info dict itself.
                    entries = info.get("entries") or [info]

                    results: List[str] = []

                    for entry in entries:
                        if entry is None:
                            continue
                        path = self._resolve_output_path(ydl, entry)
                        if path and path.exists():
                            if self.args.embed_subs and self.args.subtitles:
                                path = self._embed_subtitles(path, entry)
                            results.append(str(path))

                    if len(results) == 1:
                        return results[0]
                    if results:
                        # Playlist: print each path and return the count
                        for p in results:
                            print(f"  ✓  Saved to: {p}")
                        return results[-1]  # signal success to caller
                    return None

            except DownloadError as exc:
                # yt-dlp already prints details; we add context and exit code
                msg = str(exc)

                if "HTTP Error 403" in msg:
                    print(
                        "\nHTTP 403 Forbidden — YouTube blocked the download.\n"
                        "Possible fixes:\n"
                        "  1. Update yt-dlp:   pip install -U yt-dlp\n"
                        "  2. Install a JS runtime (deno/node) — see above\n"
                        "  3. Try a different format:  -f 'best[ext=mp4]'\n"
                        "  4. Supply cookies:  add --cookies browser or --cookies-from-browser chrome\n"
                        "  5. See: https://github.com/yt-dlp/yt-dlp/issues/12482",
                        file=sys.stderr,
                    )
                elif "Sign in" in msg or "private" in msg.lower():
                    print(
                        f"\nAccess denied: {msg}\n"
                        "The video may be private or age-restricted.\n"
                        "Try supplying cookies: --cookies-from-browser chrome",
                        file=sys.stderr,
                    )
                elif any(kw in msg for kw in ("urlopen", "timeout", "SSL")):
                    print(
                        f"\nNetwork error: {exc}\n"
                        "Check your internet connection and try again.",
                        file=sys.stderr,
                    )
                else:
                    print(f"\nDownload error: {exc}", file=sys.stderr)

                # Generic yt-dlp error — message already printed by yt-dlp
                return None

            except KeyboardInterrupt:
                raise  # re-raise so the outer handler can clean up

            except Exception as exc:  # noqa: BLE001
                print(f"Unexpected error for {url}: {exc}", file=sys.stderr)
                return None

    # -----------------------------------------------------------------------
    # yt-dlp options builder
    # -----------------------------------------------------------------------

    def _apply_js_challenge_opts(self, opts: Dict) -> None:
        """
        Configure yt-dlp to solve YouTube's JS-based signature challenges.

        YouTube encrypts video URLs using JavaScript. yt-dlp must execute
        that JS code, which requires:
          1. A JavaScript runtime on the system (deno, node, or bun).
          2. The challenge-solver script bundle, which yt-dlp can auto-
             download from GitHub when 'remote_components' is enabled.

        Without these, yt-dlp emits the three warnings the user saw:
          - "Remote components challenge solver script ... were skipped"
          - "Signature solving failed"
          - "n challenge solving failed"

        The 'remote_components' option tells yt-dlp to automatically
        fetch the solver scripts.  The format is a list of component
        specifiers; 'ejs:github' downloads from the official GitHub
        release — this is the recommended method per yt-dlp docs.
        """
        # Enable automatic download of challenge-solver scripts.
        # This is the programmatic equivalent of CLI --remote-components ejs:github
        #
        # yt-dlp versions that predate this option simply ignore the key,
        # so this is safe to set unconditionally.
        opts["remote_components"] = ["ejs:github"]

        # If we know which JS runtime is installed, tell yt-dlp explicitly.
        # This avoids yt-dlp's own runtime search and the log noise it produces.
        if self.js_runtime:
            # The 'js_runtime' option is available in yt-dlp 2025+ builds.
            # Older versions ignore it gracefully.
            opts["js_runtime"] = self.js_runtime

    def _build_ydl_opts(self, tmp_dir: str) -> Dict:
        """
        Construct the complete yt-dlp options dict.

        Key design decisions (see inline comments for rationale):
          - outtmpl is RELATIVE so 'paths' dict is honoured
          - http_chunk_size avoids mid-stream 403 errors
          - remote_components enables JS challenge solving
          - restrictfilenames + conditional windowsfilenames
        """
        args = self.args

        # -- Format string --------------------------------------------------
        if args.audio_only:
            fmt = args.format or "bestaudio/best"
        elif args.video_only:
            fmt = args.format or "bestvideo"
        else:
            fmt = args.format or SAFE_DEFAULT_FORMAT

        # -- Post-processors ------------------------------------------------
        postprocessors: List[Dict] = []

        if args.audio_only and self.ffmpeg_path:
            # Convert to MP3 after download
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            })

        if args.subtitles and args.embed_subs and self.ffmpeg_path:
            # We do embedding ourselves after download (gives more control),
            # but yt-dlp's built-in embedder is a safe fallback.
            postprocessors.append({"key": "FFmpegEmbedSubtitle"})

        # -- Subtitle options -----------------------------------------------
        sub_opts: Dict = {}
        if args.subtitles:
            sub_opts = {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitlesformat": "srt/vtt/best",
                "subtitleslangs": (["all"] if args.sub_lang == "all" else [args.sub_lang]),
            }

        # -- Merge / container ----------------------------------------------
        # Always ask for mp4 when merging so the container is predictable.
        merge_fmt = "mp4" if (args.merge or True) else None
        # Note: "or True" because bestvideo+bestaudio always needs a merge.
        # If the user asked for a single-stream format this is a no-op.

        # -- File-size filter -----------------------------------------------
        fs_opts: Dict = {}
        if args.max_filesize:
            fs_opts["max_filesize"] = int(args.max_filesize * 1024 * 1024)

        # -- Assemble -------------------------------------------------------
        opts: Dict = {
            # --- Output paths (RELATIVE template + paths dict) ---
            # Using a relative outtmpl lets yt-dlp honour the 'paths' dict.
            # An absolute outtmpl causes yt-dlp to ignore 'paths' entirely.
            "outtmpl": "%(title)s.%(ext)s",
            "paths": {
                "home": str(self.output_dir),  # final destination
                "temp": tmp_dir,  # partial downloads
            },

            # --- Format & merge ---
            "format": fmt,
            "merge_output_format": merge_fmt,

            # --- Reliability / anti-403 ---
            "http_chunk_size": HTTP_CHUNK_SIZE,  # 5 MiB chunks
            "retries": 10,  # retry on transient errors
            "fragment_retries": 10,  # retry individual fragments
            "file_access_retries": 5,
            "extractor_retries": 3,
            "sleep_interval_requests": 1,  # polite 1-second gap

            # --- Filename hygiene ---
            # 'restrictfilenames' replaces spaces/special chars with underscores.
            # Do NOT apply 'windowsfilenames' on top — it can mangle format
            # selection strings on some yt-dlp versions.
            "restrictfilenames": True,
            "windowsfilenames": sys.platform == "win32",  # only on Windows

            # --- Behaviour ---
            "overwrites": args.overwrite,
            "quiet": args.quiet,
            "no_warnings": args.quiet,
            "progress_hooks": [ProgressHook(args.quiet)],
            "postprocessors": postprocessors,
            "ffmpeg_location": self.ffmpeg_path,

            **sub_opts,
            **fs_opts,
        }

        # --- JS challenge solving (the key fix for the warnings) ---
        self._apply_js_challenge_opts(opts)

        return opts

    # -----------------------------------------------------------------------
    # Path resolution
    # -----------------------------------------------------------------------

    def _resolve_output_path(
            self, ydl: yt_dlp.YoutubeDL, info: Dict
    ) -> Optional[Path]:
        """
        Determine where yt-dlp wrote the final file.

        yt-dlp stores the real path in info['requested_downloads'][*]['filepath']
        after successful download.  We fall back to prepare_filename() and glob if that
        key is absent (e.g. when a post-processor changed the extension).
        """
        # 1) Preferred: yt-dlp tells us the exact path
        for req in info.get("requested_downloads") or []:
            fp = req.get("filepath")
            if fp:
                p = Path(fp)
                if p.exists():
                    return p
                # Post-processor may have changed extension
                for candidate in p.parent.glob(p.stem + ".*"):
                    if candidate.exists():
                        return candidate

        # 2) Fallback: reconstruct from template
        try:
            filename = ydl.prepare_filename(info)
            p = Path(filename)
            if p.exists():
                return p
            for ext in (".mp4", ".mp3", ".m4a", ".mkv", ".webm", ".ogg", ".opus"):
                candidate = p.with_suffix(ext)
                if candidate.exists():
                    return candidate
        except Exception:  # noqa: BLE001
            pass

        return None

    # -----------------------------------------------------------------------
    # Subtitle embedding
    # -----------------------------------------------------------------------

    def _embed_subtitles(self, video_path: Path, info: Dict) -> Path:
        """
        Embed subtitle files into the video container using ffmpeg.

        Falls back gracefully:
          - If ffmpeg is unavailable → leave .srt files alongside video.
          - If ffmpeg fails           → same fallback; original video untouched.

        Subtitles are embedded without re-encoding (codec copy) so it is fast.
        MP4 containers support one subtitle track (tx3g/mov_text).
        MKV containers support multiple tracks of any format.
        """
        if self.ffmpeg_path is None:
            print(
                "  Skipping subtitle embedding (ffmpeg not available).\n"
                "  Subtitle .srt/.vtt files saved alongside the video."
            )
            return video_path

        # Find subtitle files written by yt-dlp next to the video
        base = video_path.with_suffix("")  # e.g. /out/My_Video
        all_langs = sorted(set(
            list((info.get("subtitles") or {}).keys())
            + list((info.get("automatic_captions") or {}).keys())
        ))

        sub_files: List[tuple] = []
        for lang in all_langs:
            for ext in SUPPORTED_SUBTITLE_EXTENSIONS:
                # yt-dlp names subtitle files:  Title.LANG.ext
                candidate = Path(f"{base}.{lang}{ext}")
                if candidate.exists():
                    sub_files.append((lang, candidate))
                    break  # prefer the first matching extension

        if not sub_files:
            # Nothing to embed — yt-dlp may have already embedded via its own
            # FFmpegEmbedSubtitle post-processor.
            return video_path

        print(
            f"  Embedding {len(sub_files)} subtitle track(s) "
            f"({', '.join(l for l, _ in sub_files)}) …"
        )

        # Determine output container
        suffix = video_path.suffix.lower()
        # MKV supports all subtitle formats; MP4 needs conversion to mov_text
        out_suffix = suffix if suffix in (".mkv", ".mp4", ".mov") else ".mkv"

        tmp_out = video_path.with_suffix(f".tmp_embed{out_suffix}")

        # Build ffmpeg command
        cmd = [self.ffmpeg_path, "-y" if self.args.overwrite else "-n"]
        cmd += ["-i", str(video_path)]
        for _, sub_path in sub_files:
            cmd += ["-i", str(sub_path)]

        # Map: video from input 0, audio from input 0, subtitles from inputs 1..N
        cmd += ["-map", "0:v", "-map", "0:a?"]
        for i in range(len(sub_files)):
            cmd += ["-map", f"{i + 1}:s"]

        # Codec: copy everything; convert subtitles for MP4
        cmd += ["-c:v", "copy", "-c:a", "copy"]
        cmd += ["-c:s", "mov_text" if out_suffix == ".mp4" else "copy"]

        # Metadata: language tags for each subtitle stream
        for idx, (lang, _) in enumerate(sub_files):
            cmd += [f"-metadata:s:s:{idx}", f"language={lang}"]

        cmd.append(str(tmp_out))

        if not self.args.quiet:
            print(f"  ffmpeg cmd: {' '.join(str(c) for c in cmd)}")

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="replace")
            print(
                f"  Warning: ffmpeg subtitle embedding failed.\n"
                f"  ffmpeg said: {stderr[-400:]}\n"
                f"  Subtitle files kept alongside video.",
                file=sys.stderr,
            )
            if tmp_out.exists():
                tmp_out.unlink()
            return video_path  # original video untouched
        except FileNotFoundError:
            print("  Warning: ffmpeg not found — cannot embed subtitles.", file=sys.stderr)
            return video_path

        # Swap temp → final
        final = video_path.with_suffix(out_suffix)
        try:
            if final != video_path and video_path.exists():
                video_path.unlink()
            tmp_out.rename(final)
            # Remove the now-embedded subtitle files
            for _, sub_path in sub_files:
                sub_path.unlink(missing_ok=True)
            print(f"  ✓ Subtitles embedded → {final.name}")
            return final
        except OSError as exc:
            print(f"  Warning: rename failed: {exc}", file=sys.stderr)
            return video_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    """Return a human-readable byte count string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def _validate_url(url: str) -> bool:
    """
    Return True only if *url* looks like a plausible YouTube URL.

    Accepted hosts: youtube.com, youtu.be, music.youtube.com, m.youtube.com
    and any www. variant.
    """
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    host = p.netloc.lower().lstrip("www.")
    return host in (
        "youtube.com",
        "youtu.be",
        "m.youtube.com",
        "music.youtube.com",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="YouTube Download Tool — videos, audio, playlists, subtitles",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py URL
  python main.py --audio-only -o ~/Music URL
  python main.py --subtitles --embed-subs --sub-lang en URL
  python main.py --simulate URL
  python main.py -f "137+140" URL
        """,
    )

    # Positional
    parser.add_argument("urls", nargs="+", metavar="URL",
                        help="YouTube video or playlist URL(s)")

    # Output
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR,
                        metavar="DIR", help=f"Destination directory (default: {DEFAULT_OUTPUT_DIR})")

    # Format
    fmt = parser.add_argument_group("format selection")
    fmt.add_argument("-f", "--format", metavar="FMT",
                     help=(
                         "yt-dlp format string or itag (e.g. 'bestvideo+bestaudio', "
                         "'137+140', 'best[ext=mp4]').  "
                         f"Default: {SAFE_DEFAULT_FORMAT!r}"
                     ))
    me = fmt.add_mutually_exclusive_group()
    me.add_argument("--audio-only", action="store_true",
                    help="Extract audio only (converted to MP3 if ffmpeg available)")
    me.add_argument("--video-only", action="store_true",
                    help="Download video stream only (no audio track)")

    # Subtitles
    sub = parser.add_argument_group("subtitles")
    sub.add_argument("-s", "--subtitles", action="store_true",
                     help="Download subtitle files")
    sub.add_argument("--sub-lang", default="en", metavar="LANG",
                     help="Subtitle language code (e.g. en, fr, de) or 'all'. Default: en")
    sub.add_argument("--embed-subs", action="store_true",
                     help="Embed subtitles into the video (needs ffmpeg)")

    # Processing
    proc = parser.add_argument_group("processing")
    proc.add_argument("-m", "--merge", action="store_true",
                      help="Merge audio+video into mp4")
    proc.add_argument("--overwrite", action="store_true",
                      help="Overwrite existing output files")
    proc.add_argument("--max-filesize", type=float, metavar="MB",
                      help="Skip streams larger than N MB")

    # Output control
    out = parser.add_argument_group("output control")
    out.add_argument("--quiet", action="store_true",
                     help="Suppress all output except errors")
    out.add_argument("--simulate", "--dry-run", dest="simulate",
                     action="store_true",
                     help="List available formats without downloading")

    return parser


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)

    bad = [u for u in args.urls if not _validate_url(u)]
    if bad:
        parser.error(
            "Invalid YouTube URL(s):\n" +
            "\n".join(f"  {u}" for u in bad)
        )

    return args


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        dl = YouTubeDownloader(args)
        return dl.run()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        return EXIT_GENERAL_ERROR
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        return EXIT_GENERAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
