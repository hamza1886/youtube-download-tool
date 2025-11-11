#!/usr/bin/env python3
"""
YouTube Download Tool - A comprehensive command-line utility for downloading YouTube videos.
Supports format selection, audio extraction, subtitle downloading and embedding.
Author: Hamza Rashid
License: MIT
"""

import os
import sys
import json
import shutil
import tempfile
import argparse
import subprocess
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from urllib.parse import urlparse

# Third-party imports
try:
    import yt_dlp
except ImportError:
    print("Error: yt-dlp is not installed. Please run: pip install yt-dlp")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # Fallback to basic progress

# Constants
DEFAULT_OUTPUT_DIR = os.getcwd()
FFMPEG_CHECK_CMD = ["ffmpeg", "-version"]
SUPPORTED_SUBTITLE_FORMATS = ['.vtt', '.srt', '.ass']
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_NETWORK_ERROR = 2
EXIT_INVALID_INPUT = 3
EXIT_MISSING_DEPENDENCY = 4


class DownloadProgressHook:
    """Progress hook for yt-dlp downloads."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self.pbar = None

    def __call__(self, d: Dict):
        """Handle download progress updates."""
        if self.quiet:
            return

        if d['status'] == 'downloading':
            # Extract progress information
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)

            if tqdm and total > 0:
                if self.pbar is None:
                    self.pbar = tqdm(total=total, unit='B', unit_scale=True, desc="Downloading")
                self.pbar.update(downloaded - self.pbar.n)
            else:
                # Fallback progress display
                percent = d.get('_percent_str', 'N/A')
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                print(f"\rProgress: {percent} | Speed: {speed} | ETA: {eta}", end='')

        elif d['status'] == 'finished':
            if self.pbar:
                self.pbar.close()
                self.pbar = None
            elif not self.quiet:
                print()  # New line after progress


class YouTubeDownloader:
    """Main YouTube downloader class handling all download operations."""

    def __init__(self, args: argparse.Namespace):
        """
        Initialize the downloader with command-line arguments.

        Args:
            args: Parsed command-line arguments
        """
        self.args = args
        self.output_dir = Path(args.output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check ffmpeg availability
        self.ffmpeg_available = self._check_ffmpeg()
        if not self.ffmpeg_available and (args.merge or args.embed_subs):
            print("Warning: ffmpeg not found. Merge and embed features will be disabled.")
            print("Install ffmpeg from: https://ffmpeg.org/download.html")

    def _check_ffmpeg(self) -> bool:
        """
        Check if ffmpeg is available on the system.

        Returns:
            bool: True if ffmpeg is available, False otherwise
        """
        try:
            result = subprocess.run(
                FFMPEG_CHECK_CMD,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _get_ydl_opts(self, temp_dir: str) -> Dict:
        """
        Build yt-dlp options based on command-line arguments.

        Args:
            temp_dir: Temporary directory for downloads

        Returns:
            Dict: yt-dlp configuration options
        """
        opts = {
            'outtmpl': str(self.output_dir / '%(title)s.%(ext)s'),
            'quiet': self.args.quiet,
            'no_warnings': self.args.quiet,
            'progress_hooks': [DownloadProgressHook(self.args.quiet)],
            'overwrites': self.args.overwrite,
            'restrictfilenames': True,  # Avoid problematic filenames
            'windowsfilenames': True,  # Windows-safe filenames
            'no_color': False,
            'merge_output_format': 'mp4' if self.args.merge else None,
        }

        # Format selection
        if self.args.audio_only:
            opts['format'] = self.args.format or 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }] if self.ffmpeg_available else []
        elif self.args.video_only:
            opts['format'] = self.args.format or 'bestvideo'
        else:
            opts['format'] = self.args.format or 'bestvideo+bestaudio/best'

        # Subtitle options
        if self.args.subtitles:
            opts['writesubtitles'] = True
            opts['writeautomaticsub'] = True
            opts['subtitlesformat'] = 'srt/vtt/best'

            if self.args.sub_lang == 'all':
                opts['subtitleslangs'] = ['all']
            else:
                opts['subtitleslangs'] = [self.args.sub_lang]

        # File size limit
        if self.args.max_filesize:
            # Convert MB to bytes
            max_bytes = self.args.max_filesize * 1024 * 1024
            opts['max_filesize'] = max_bytes

        # Temporary directory for downloads
        if temp_dir:
            opts['paths'] = {'temp': temp_dir, 'home': str(self.output_dir)}

        return opts

    def list_formats(self, url: str) -> None:
        """
        List available formats for a video.

        Args:
            url: YouTube video URL
        """
        print(f"\nFetching available formats for: {url}")

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'simulate': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                print(f"\nTitle: {info.get('title', 'Unknown')}")
                print(f"Duration: {info.get('duration', 0)} seconds")
                print(f"Uploader: {info.get('uploader', 'Unknown')}")
                print("\nAvailable formats:")
                print("-" * 80)
                print(f"{'ID':<10} {'EXT':<5} {'RESOLUTION':<12} {'FPS':<5} {'FILESIZE':<10} {'NOTE':<30}")
                print("-" * 80)

                formats = info.get('formats', [])
                for fmt in formats:
                    format_id = fmt.get('format_id', 'N/A')
                    ext = fmt.get('ext', 'N/A')
                    resolution = f"{fmt.get('width', '?')}x{fmt.get('height', '?')}"
                    fps = fmt.get('fps', 'N/A')
                    filesize = fmt.get('filesize', 0)
                    filesize_str = self._format_bytes(filesize) if filesize else 'N/A'
                    note = fmt.get('format_note', '')

                    # Add audio/video indicators
                    if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                        note = f"{note} (video+audio)"
                    elif fmt.get('vcodec') != 'none':
                        note = f"{note} (video only)"
                    elif fmt.get('acodec') != 'none':
                        note = f"{note} (audio only)"

                    print(f"{format_id:<10} {ext:<5} {resolution:<12} {str(fps):<5} {filesize_str:<10} {note:<30}")

                # Show available subtitles
                if info.get('subtitles') or info.get('automatic_captions'):
                    print("\nAvailable subtitles:")
                    if info.get('subtitles'):
                        print("  Manual:", ', '.join(info['subtitles'].keys()))
                    if info.get('automatic_captions'):
                        print("  Auto-generated:", ', '.join(info['automatic_captions'].keys()))

        except yt_dlp.utils.DownloadError as e:
            print(f"Error fetching video info: {e}")
            sys.exit(EXIT_NETWORK_ERROR)

    def download_video(self, url: str) -> Optional[str]:
        """
        Download a video with specified options.

        Args:
            url: YouTube video URL

        Returns:
            Optional[str]: Path to downloaded file or None if failed
        """
        # Create temporary directory for downloads
        with tempfile.TemporaryDirectory() as temp_dir:
            ydl_opts = self._get_ydl_opts(temp_dir)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    if not self.args.quiet:
                        print(f"\nDownloading: {url}")

                    # Extract info and download
                    info = ydl.extract_info(url, download=not self.args.simulate)

                    if self.args.simulate:
                        # Dry run - show what would be downloaded
                        print(f"\n[DRY RUN] Would download:")
                        print(f"  Title: {info.get('title', 'Unknown')}")
                        print(f"  Format: {ydl_opts['format']}")
                        print(f"  Output directory: {self.output_dir}")
                        return None

                    # Get the output filename
                    filename = ydl.prepare_filename(info)
                    output_path = Path(filename)

                    # Handle different extensions based on post-processing
                    if self.args.audio_only and self.ffmpeg_available:
                        output_path = output_path.with_suffix('.mp3')

                    # Embed subtitles if requested
                    if self.args.embed_subs and self.args.subtitles and self.ffmpeg_available:
                        output_path = self._embed_subtitles(output_path, info)

                    if output_path.exists():
                        print(f"✓ Downloaded: {output_path}")
                        return str(output_path)
                    else:
                        print(f"Warning: Expected file not found: {output_path}")
                        return None

            except yt_dlp.utils.DownloadError as e:
                print(f"Download error: {e}")
                return None
            except Exception as e:
                print(f"Unexpected error: {e}")
                return None

    def _embed_subtitles(self, video_path: Path, info: Dict) -> Path:
        """
        Embed subtitles into video file using ffmpeg.

        Args:
            video_path: Path to video file
            info: Video information dictionary from yt-dlp

        Returns:
            Path: Path to video with embedded subtitles
        """
        if not video_path.exists():
            print(f"Warning: Video file not found for subtitle embedding: {video_path}")
            return video_path

        # Find subtitle files
        subtitle_files = []
        base_path = video_path.with_suffix('')

        for lang in (info.get('subtitles', {}).keys() | info.get('automatic_captions', {}).keys()):
            for ext in SUPPORTED_SUBTITLE_FORMATS:
                sub_file = Path(f"{base_path}.{lang}{ext}")
                if sub_file.exists():
                    subtitle_files.append((lang, sub_file))
                    break

        if not subtitle_files:
            print("No subtitle files found to embed")
            return video_path

        print(f"Embedding {len(subtitle_files)} subtitle track(s)...")

        # Create temporary output file
        temp_output = video_path.with_suffix('.temp' + video_path.suffix)

        # Build ffmpeg command
        cmd = ['ffmpeg', '-i', str(video_path)]

        # Add subtitle inputs
        for _, sub_file in subtitle_files:
            cmd.extend(['-i', str(sub_file)])

        # Map video and audio from first input
        cmd.extend(['-map', '0:v', '-map', '0:a'])

        # Map all subtitle streams
        for i in range(len(subtitle_files)):
            cmd.extend(['-map', f'{i + 1}:s'])

        # Set subtitle metadata
        for i, (lang, _) in enumerate(subtitle_files):
            cmd.extend([f'-metadata:s:s:{i}', f'language={lang}'])

        # Copy codecs (no re-encoding)
        cmd.extend(['-c', 'copy'])

        # Output file
        cmd.extend(['-y' if self.args.overwrite else '-n', str(temp_output)])

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL if self.args.quiet else None,
                stderr=subprocess.DEVNULL if self.args.quiet else None,
                check=True
            )

            # Replace original with embedded version
            if temp_output.exists():
                video_path.unlink()
                temp_output.rename(video_path)
                print(f"✓ Subtitles embedded successfully")

                # Clean up subtitle files
                for _, sub_file in subtitle_files:
                    sub_file.unlink()

        except subprocess.CalledProcessError as e:
            print(f"Warning: Failed to embed subtitles: {e}")
            if temp_output.exists():
                temp_output.unlink()

        return video_path

    def _format_bytes(self, bytes: int) -> str:
        """
        Format bytes to human-readable string.

        Args:
            bytes: Number of bytes

        Returns:
            str: Formatted string (e.g., "10.5 MB")
        """
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024.0:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.1f} TB"

    def run(self) -> int:
        """
        Main execution method.

        Returns:
            int: Exit code
        """
        # Show formats if requested or in dry-run mode
        if self.args.simulate:
            for url in self.args.urls:
                self.list_formats(url)
                print("\n" + "=" * 80)
            return EXIT_SUCCESS

        # Download each URL
        success_count = 0
        failed_urls = []

        for url in self.args.urls:
            result = self.download_video(url)
            if result:
                success_count += 1
            else:
                failed_urls.append(url)

        # Summary
        print(f"\n{'=' * 60}")
        print(f"Download Summary:")
        print(f"  Successful: {success_count}/{len(self.args.urls)}")
        if failed_urls:
            print(f"  Failed URLs:")
            for url in failed_urls:
                print(f"    - {url}")

        return EXIT_SUCCESS if success_count == len(self.args.urls) else EXIT_GENERAL_ERROR


def validate_url(url: str) -> bool:
    """
    Validate if the provided string is a valid YouTube URL.

    Args:
        url: URL string to validate

    Returns:
        bool: True if valid YouTube URL, False otherwise
    """
    parsed = urlparse(url)
    valid_hosts = ['youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com']
    return parsed.scheme in ['http', 'https'] and any(host in parsed.netloc for host in valid_hosts)


def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description='YouTube Download Tool - Download videos with format selection and subtitle support',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download best quality video
  %(prog)s https://youtube.com/watch?v=VIDEO_ID

  # Download audio only as MP3
  %(prog)s --audio-only https://youtube.com/watch?v=VIDEO_ID

  # Download with subtitles and embed them
  %(prog)s --subtitles --embed-subs --sub-lang en https://youtube.com/watch?v=VIDEO_ID

  # List available formats
  %(prog)s --simulate https://youtube.com/watch?v=VIDEO_ID

  # Download specific format
  %(prog)s -f 137+140 https://youtube.com/watch?v=VIDEO_ID
        """
    )

    # Required arguments
    parser.add_argument(
        'urls',
        nargs='+',
        help='YouTube video or playlist URL(s)'
    )

    # Output options
    parser.add_argument(
        '-o', '--output-dir',
        default=DEFAULT_OUTPUT_DIR,
        help=f'Output directory (default: {DEFAULT_OUTPUT_DIR})'
    )

    # Format options
    parser.add_argument(
        '-f', '--format',
        help='Format selection (yt-dlp format string or itag)'
    )

    parser.add_argument(
        '--audio-only',
        action='store_true',
        help='Download audio only (best audio unless --format specified)'
    )

    parser.add_argument(
        '--video-only',
        action='store_true',
        help='Download video only (no audio)'
    )

    # Subtitle options
    parser.add_argument(
        '-s', '--subtitles',
        action='store_true',
        help='Download subtitles'
    )

    parser.add_argument(
        '--sub-lang',
        default='en',
        help='Subtitle language code (e.g., en, fr, or "all") (default: en)'
    )

    parser.add_argument(
        '--embed-subs',
        action='store_true',
        help='Embed subtitles into video file (requires ffmpeg)'
    )

    # Processing options
    parser.add_argument(
        '-m', '--merge',
        action='store_true',
        help='Merge audio and video streams (requires ffmpeg)'
    )

    parser.add_argument(
        '--overwrite',
        action='store_true',
        help='Overwrite existing files'
    )

    # Output control
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Minimal output'
    )

    parser.add_argument(
        '--progress',
        action='store_true',
        default=True,
        help='Show download progress (default: True)'
    )

    # Filtering options
    parser.add_argument(
        '--max-filesize',
        type=float,
        help='Maximum file size in MB'
    )

    # Simulation
    parser.add_argument(
        '--simulate', '--dry-run',
        action='store_true',
        help='Show what would be downloaded without downloading'
    )

    args = parser.parse_args()

    # Validate arguments
    if args.audio_only and args.video_only:
        parser.error("--audio-only and --video-only are mutually exclusive")

    # Validate URLs
    for url in args.urls:
        if not validate_url(url):
            parser.error(f"Invalid YouTube URL: {url}")

    return args


def main():
    """Main entry point for the application."""
    try:
        # Parse arguments
        args = parse_arguments()

        # Create and run downloader
        downloader = YouTubeDownloader(args)
        exit_code = downloader.run()

        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n\nDownload cancelled by user.")
        sys.exit(EXIT_GENERAL_ERROR)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(EXIT_GENERAL_ERROR)


if __name__ == '__main__':
    main()
