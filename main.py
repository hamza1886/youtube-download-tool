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
        "Fix: pip install yt-dlp\n"
        "     or: pip install -r requirements.txt"
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

# Subtitle file extensions we recognize and try to embed
SUPPORTED_SUBTITLE_EXTENSIONS = [".srt", ".vtt", ".ass", ".ssa"]

# yt-dlp format string that avoids the SABR/403 issue:
#   1. Prefer AVC (h264) video + m4a audio  → most stable CDN path
#   2. Fall back to any bestvideo+bestaudio pair
#   3. Final fallback: single best pre-muxed stream
SAFE_DEFAULT_FORMAT = (
    "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
    "bestvideo+bestaudio/best"
)

# Chunk size for HTTP downloads (5 MiB).
# Smaller chunks mean each individual request is cheaper → fewer 403s.
HTTP_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MiB

# Exit codes
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_INVALID_INPUT = 3
EXIT_MISSING_DEP = 4


# ---------------------------------------------------------------------------
# Progress hook
# ---------------------------------------------------------------------------
class ProgressHook:
    """
    yt-dlp progress hook.  Uses tqdm when available, otherwise prints a
    simple one-liner that overwrites itself on each update.
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
            self._on_finished(d)
        elif status == "error":
            self._close_pbar()
            print("\nDownload reported an error.", file=sys.stderr)

    # -- private helpers ----------------------------------------------------

    def _on_downloading(self, d: Dict) -> None:
        total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
        downloaded = d.get("downloaded_bytes", 0)

        if TQDM_AVAILABLE:
            if self._pbar is None and total:
                self._pbar = tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="  Downloading",
                    ncols=90,
                    leave=True,
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
            speed_str = d.get("_speed_str", "? B/s")
            eta_str = d.get("_eta_str", "?")
            print(f"\r  {pct:>6}  speed={speed_str}  eta={eta_str}   ", end="", flush=True)

    def _on_finished(self, d: Dict) -> None:
        self._close_pbar()
        if not TQDM_AVAILABLE:
            print()  # newline after overwriting line

    def _close_pbar(self) -> None:
        if self._pbar is not None:
            self._pbar.close()
            self._pbar = None


# ---------------------------------------------------------------------------
# Core downloader
# ---------------------------------------------------------------------------
class YouTubeDownloader:
    """
    Wraps yt-dlp to provide a clean interface for:
      - format listing (dry-run / simulate)
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
        self.ffmpeg_path = self._find_ffmpeg()

        # Warn early so the user can act before any download starts
        if self.ffmpeg_path is None:
            if args.merge or args.embed_subs or args.audio_only:
                print(
                    "Warning: ffmpeg was not found on PATH.\n"
                    "         --merge, --embed-subs, and audio conversion will be disabled.\n"
                    "         Install ffmpeg from: https://ffmpeg.org/download.html"
                )

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

        successes, failures = 0, []

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
        """Print a human-readable table of available formats."""
        print(f"Fetching format list for:\n  {url}\n")

        ydl_opts = {
            "quiet": True,
            "no_warnings": False,
            "simulate": True,
        }

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
        col = (8, 5, 11, 5, 9, 12, 0)  # column widths (last = free)
        header = ("ID", "EXT", "RESOLUTION", "FPS", "SIZE", "STREAMS", "NOTE")
        sep = "  ".join("-" * w for w in col[:-1]) + "  " + "-" * 20
        hdr = "  ".join(h.ljust(w) for h, w in zip(header[:-1], col[:-1]))
        hdr += f"  {header[-1]}"

        print(f"\n{hdr}\n{sep}")
        for row in rows:
            line = "  ".join(cell.ljust(w) for cell, w in zip(row[:-1], col[:-1]))
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

        Strategy
        --------
        1. Use a temp directory for all intermediate files.
        2. On success, yt-dlp moves the finished file to output_dir
           (we configure 'paths' so that outtmpl is RELATIVE, which lets
           yt-dlp honour the temp/home split properly — this fixes the
           "--paths ignored" warning from the original code).
        3. Embed subtitles if requested.
        4. Return the final path.
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

                    results = []
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
                        "  2. Try a different format:  -f 'best[ext=mp4]'\n"
                        "  3. Supply cookies:  add --cookies browser or --cookies-from-browser chrome\n"
                        "  4. See: https://github.com/yt-dlp/yt-dlp/issues/12482",
                        file=sys.stderr,
                    )
                    return None
                if any(kw in msg for kw in ("urlopen error", "timeout", "SSLError")):
                    print(
                        f"\nNetwork error: {exc}\n"
                        "Check your internet connection and try again.",
                        file=sys.stderr,
                    )
                    return None
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

    def _build_ydl_opts(self, tmp_dir: str) -> Dict:
        """
        Construct the yt-dlp options dict.

        Key design decisions
        --------------------
        * outtmpl uses a RELATIVE path (just the filename template).
          The actual directories are set via 'paths':
            - 'home' → final output directory
            - 'temp' → temporary directory for partial downloads
          This is the correct way to use both simultaneously.  Using an
          absolute path in outtmpl causes yt-dlp to ignore 'paths' entirely
          (that was the "--paths is ignored" warning in the original code).

        * format defaults to SAFE_DEFAULT_FORMAT which prefers h264/m4a.
          This avoids the VP9 (format 315) SABR 403 issue on the current
          YouTube CDN.

        * http_chunk_size breaks large streams into 5 MiB HTTP requests.
          This dramatically reduces 403 mid-stream failures for big files.

        * retries / fragment_retries give yt-dlp multiple chances to
          recover from transient network or CDN hiccups.
        """
        args = self.args

        # ------------------------------------------------------------------
        # Format string
        # ------------------------------------------------------------------
        if args.audio_only:
            fmt = args.format or "bestaudio/best"
        elif args.video_only:
            fmt = args.format or "bestvideo"
        else:
            fmt = args.format or SAFE_DEFAULT_FORMAT

        # ------------------------------------------------------------------
        # Post-processors
        # ------------------------------------------------------------------
        postprocessors = []

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

        # ------------------------------------------------------------------
        # Subtitle options
        # ------------------------------------------------------------------
        sub_opts: Dict = {}
        if args.subtitles:
            sub_opts = {
                "writesubtitles": True,
                "writeautomaticsub": True,
                "subtitlesformat": "srt/vtt/best",
                "subtitleslangs": ["all"] if args.sub_lang == "all"
                else [args.sub_lang],
            }

        # ------------------------------------------------------------------
        # Merge / container
        # ------------------------------------------------------------------
        # Always ask for mp4 when merging so the container is predictable.
        merge_fmt = "mp4" if (args.merge or True) else None
        # Note: "or True" because bestvideo+bestaudio always needs a merge.
        # If the user asked for a single-stream format this is a no-op.

        # ------------------------------------------------------------------
        # File-size filter
        # ------------------------------------------------------------------
        max_fs_opts: Dict = {}
        if args.max_filesize:
            max_fs_opts["max_filesize"] = int(args.max_filesize * 1024 * 1024)

        # ------------------------------------------------------------------
        # Assemble
        # ------------------------------------------------------------------
        opts: Dict = {
            # --- output paths (RELATIVE template + paths dict) ---
            "outtmpl": "%(title)s.%(ext)s",  # ← relative, not absolute
            "paths": {
                "home": str(self.output_dir),  # final destination
                "temp": tmp_dir,  # partial downloads live here
            },

            # --- format ---
            "format": fmt,
            "merge_output_format": merge_fmt,

            # --- reliability / anti-403 ---
            "http_chunk_size": HTTP_CHUNK_SIZE,  # 5 MiB chunks
            "retries": 10,  # retry on transient errors
            "fragment_retries": 10,  # retry individual fragments
            "file_access_retries": 5,
            "extractor_retries": 3,
            "sleep_interval_requests": 1,  # polite 1-second gap

            # --- filename hygiene ---
            # 'restrictfilenames' replaces spaces/special chars with underscores.
            # Do NOT apply 'windowsfilenames' on top — it can mangle format
            # selection strings on some yt-dlp versions.
            "restrictfilenames": True,
            "windowsfilenames": sys.platform == "win32",  # only on Windows

            # --- behaviour ---
            "overwrites": args.overwrite,
            "quiet": args.quiet,
            "no_warnings": args.quiet,
            "progress_hooks": [ProgressHook(args.quiet)],
            "postprocessors": postprocessors,

            # ffmpeg location (None → search PATH)
            "ffmpeg_location": self.ffmpeg_path or None,

            **sub_opts,
            **max_fs_opts,
        }

        return opts

    # -----------------------------------------------------------------------
    # Path resolution
    # -----------------------------------------------------------------------

    def _resolve_output_path(
            self, ydl: yt_dlp.YoutubeDL, info: Dict
    ) -> Optional[Path]:
        """
        Work out where yt-dlp actually wrote the file.

        yt-dlp stores the real path in info['requested_downloads'][n]['filepath']
        after a successful download.  We fall back to prepare_filename() if that
        key is absent (e.g. when a post-processor changed the extension).
        """
        # Preferred: yt-dlp tells us the exact path
        for req in info.get("requested_downloads") or []:
            fp = req.get("filepath")
            if fp:
                p = Path(fp)
                if p.exists():
                    return p
                # Post-processors may have changed the extension
                for candidate in p.parent.glob(p.stem + ".*"):
                    if candidate.exists():
                        return candidate

        # Fallback: reconstruct from template
        try:
            filename = ydl.prepare_filename(info)
            p = Path(filename)
            if p.exists():
                return p
            # Audio-only: yt-dlp changes .webm/.m4a → .mp3
            for ext in (".mp3", ".m4a", ".ogg", ".opus", ".wav"):
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
        sub_files: List[tuple] = []  # [(lang_code, Path), ...]

        all_sub_langs = set(
            list((info.get("subtitles") or {}).keys())
            + list((info.get("automatic_captions") or {}).keys())
        )

        for lang in sorted(all_sub_langs):
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
        if out_suffix == ".mp4":
            cmd += ["-c:s", "mov_text"]
        else:
            cmd += ["-c:s", "copy"]

        # Metadata: language tags for each subtitle stream
        for idx, (lang, _) in enumerate(sub_files):
            cmd += [f"-metadata:s:s:{idx}", f"language={lang}"]

        cmd.append(str(tmp_out))

        if not self.args.quiet:
            print(f"  ffmpeg: {' '.join(str(c) for c in cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
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
            print(
                "  Warning: ffmpeg not found — cannot embed subtitles.",
                file=sys.stderr,
            )
            return video_path

        # Replace original with embedded version
        final_path = video_path.with_suffix(out_suffix)
        try:
            if final_path != video_path and video_path.exists():
                video_path.unlink()
            tmp_out.rename(final_path)
            # Remove the now-embedded subtitle sidecar files
            for _, sub_path in sub_files:
                sub_path.unlink(missing_ok=True)
            print(f"  ✓ Subtitles embedded → {final_path.name}")
            return final_path
        except OSError as exc:
            print(f"  Warning: Could not rename temp file: {exc}", file=sys.stderr)
            return video_path

    # -----------------------------------------------------------------------
    # ffmpeg detection
    # -----------------------------------------------------------------------

    def _find_ffmpeg(self) -> Optional[str]:
        """
        Locate the ffmpeg binary.

        Returns the full path string if found, else None.
        Uses shutil.which() which searches PATH correctly on all platforms
        (including Windows where the extension '.exe' must be considered).
        """
        path = shutil.which("ffmpeg")
        if path:
            return path
        # Extra Windows fallback locations
        if sys.platform == "win32":
            candidates = [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
            ]
            for c in candidates:
                if Path(c).exists():
                    return c
        return None


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
        description=(
            "YouTube Download Tool\n"
            "Download videos, audio, playlists, and subtitles from YouTube."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py https://www.youtube.com/watch?v=VIDEO_ID
  python main.py --audio-only -o ~/Music https://www.youtube.com/watch?v=VIDEO_ID
  python main.py --subtitles --embed-subs --sub-lang en URL
  python main.py --simulate URL          # list formats, do not download
  python main.py -f "137+140" URL        # specific format IDs
        """,
    )

    # --- positional ---------------------------------------------------------
    parser.add_argument(
        "urls",
        nargs="+",
        metavar="URL",
        help="YouTube video or playlist URL(s)",
    )

    # --- output -------------------------------------------------------------
    parser.add_argument(
        "-o", "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help=f"Destination directory (default: current directory)",
    )

    # --- format selection ---------------------------------------------------
    fmt_group = parser.add_argument_group("format selection")
    fmt_group.add_argument(
        "-f", "--format",
        metavar="FMT",
        help=(
            "yt-dlp format string or itag (e.g. 'bestvideo+bestaudio', "
            "'137+140', 'best[ext=mp4]').  "
            f"Default: {SAFE_DEFAULT_FORMAT!r}"
        ),
    )
    me = fmt_group.add_mutually_exclusive_group()
    me.add_argument(
        "--audio-only",
        action="store_true",
        help="Extract audio only (converted to MP3 if ffmpeg available)",
    )
    me.add_argument(
        "--video-only",
        action="store_true",
        help="Download video stream only (no audio track)",
    )

    # --- subtitles ----------------------------------------------------------
    sub_group = parser.add_argument_group("subtitles")
    sub_group.add_argument(
        "-s", "--subtitles",
        action="store_true",
        help="Download subtitle files",
    )
    sub_group.add_argument(
        "--sub-lang",
        default="en",
        metavar="LANG",
        help="Subtitle language code (e.g. en, fr, de, 'all').  Default: en",
    )
    sub_group.add_argument(
        "--embed-subs",
        action="store_true",
        help="Embed subtitles into the video container via ffmpeg",
    )

    # --- processing ---------------------------------------------------------
    proc_group = parser.add_argument_group("processing")
    proc_group.add_argument(
        "-m", "--merge",
        action="store_true",
        help="Explicitly request audio+video merge (always mp4 output)",
    )
    proc_group.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    proc_group.add_argument(
        "--max-filesize",
        type=float,
        metavar="MB",
        help="Skip any stream larger than this many megabytes",
    )

    # --- output control -----------------------------------------------------
    out_group = parser.add_argument_group("output control")
    out_group.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress all output except errors",
    )
    out_group.add_argument(
        "--simulate", "--dry-run",
        dest="simulate",
        action="store_true",
        help="List available formats without downloading",
    )

    return parser


def _parse_and_validate(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = _build_parser()
    args = parser.parse_args(argv)

    invalid = [u for u in args.urls if not _validate_url(u)]
    if invalid:
        parser.error(
            "The following URL(s) do not look like YouTube URLs:\n"
            + "\n".join(f"  {u}" for u in invalid)
        )

    return args


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_and_validate(argv)
    try:
        downloader = YouTubeDownloader(args)
        return downloader.run()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        return EXIT_GENERAL_ERROR
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        return EXIT_GENERAL_ERROR


if __name__ == "__main__":
    sys.exit(main())
