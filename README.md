# YouTube Download Tool

A comprehensive command-line utility for downloading YouTube videos with support for format selection, audio extraction, and subtitle embedding.

## Features

- 🎥 Download videos in various formats and qualities
- 🎵 Extract audio-only (MP3/M4A)
- 📝 Download and embed subtitles
- 📊 Format selection with preview
- 🔄 Playlist support
- 🚀 Progress tracking
- 💾 Cross-platform (Windows, macOS, Linux)

## Installation

### Prerequisites

1. **Python 3.7+** installed on your system
2. **ffmpeg** (required for audio conversion and subtitle embedding)

### Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Install ffmpeg

#### Windows

Download from [ffmpeg.org](https://ffmpeg.org/download.html) or use:

```bash
# Using Chocolatey
choco install ffmpeg

# Using Scoop
scoop install ffmpeg
```

#### macOS

```bash
# Using Homebrew
brew install ffmpeg
```
#### Linux

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch
sudo pacman -S ffmpeg
```

### Step 3: Verify Installation

```bash
python main.py --help
ffmpeg -version
```

## Usage Examples

### Basic Download (Best Quality)

```bash
python main.py https://www.youtube.com/watch?v=VIDEO_ID
```

### Download Audio Only

```bash
# Download as MP3
python main.py --audio-only https://www.youtube.com/watch?v=VIDEO_ID

# Download best audio format
python main.py --audio-only -f bestaudio https://www.youtube.com/watch?v=VIDEO_ID
```

### Download with Subtitles

```bash
# Download English subtitles
python main.py -s --sub-lang en https://www.youtube.com/watch?v=VIDEO_ID

# Download and embed subtitles into video
python main.py -s --embed-subs --sub-lang en https://www.youtube.com/watch?v=VIDEO_ID

# Download all available subtitles
python main.py -s --sub-lang all https://www.youtube.com/watch?v=VIDEO_ID
```

### Format Selection

```bash
# List available formats
python main.py --simulate https://www.youtube.com/watch?v=VIDEO_ID

# Download specific format by ID
python main.py -f 137 https://www.youtube.com/watch?v=VIDEO_ID

# Download best video + best audio and merge
python main.py -f "bestvideo+bestaudio" --merge https://www.youtube.com/watch?v=VIDEO_ID

# Download 1080p video if available
python main.py -f "bestvideo[height<=1080]+bestaudio/best" https://www.youtube.com/watch?v=VIDEO_ID
```

### Advanced Options

```bash
# Download to specific directory
python main.py -o /path/to/downloads https://www.youtube.com/watch?v=VIDEO_ID

# Download multiple videos
python main.py https://www.youtube.com/watch?v=VIDEO1 https://www.youtube.com/watch?v=VIDEO2

# Limit file size (skip files over 100MB)
python main.py --max-filesize 100 https://www.youtube.com/watch?v=VIDEO_ID

# Quiet mode with overwrite
python main.py --quiet --overwrite https://www.youtube.com/watch?v=VIDEO_ID

# Dry run to see what would be downloaded
python main.py --dry-run https://www.youtube.com/watch?v=VIDEO_ID
```

### Command-Line Options

| Option                  | Description                                   |
|-------------------------|-----------------------------------------------|
| `-h, --help`            | Show this help message and exit               |
| `-o, --output-dir DIR`  | Output directory (default: current directory) |
| `-f, --format FORMAT`	  | Format selection string or itag               |
| `--audio-only`          | Download audio only                           |
| `--video-only`          | Download video only (no audio)                |
| `-s, --subtitles`       | Download subtitles                            |
| `--sub-lang LANG`       | Subtitle language (e.g., 'en', 'fr', 'all')   |
| `--embed-subs`          | Embed subtitles into video                    |
| `-m, --merge`           | Merge audio+video streams                     |
| `--overwrite`           | Overwrite existing files                      |
| `--quiet`               | Minimal output                                |
| `--progress`            | Show progress bar                             |
| `--max-filesize MB`     | Skip files over specified size                |
| `--simulate, --dry-run` | Preview without downloading                   |

### Testing with Sample Videos

You can test the tool using these Creative Commons licensed videos:

```bash
# Test basic download (Blender Foundation - Big Buck Bunny trailer)
python main.py https://www.youtube.com/watch?v=aqz-KE-bpKQ

# Test audio extraction
python main.py --audio-only https://www.youtube.com/watch?v=aqz-KE-bpKQ

# Test format listing
python main.py --simulate https://www.youtube.com/watch?v=aqz-KE-bpKQ

# Test subtitle download (if available)
python main.py -s --sub-lang en https://www.youtube.com/watch?v=aqz-KE-bpKQ
```

### Container Format Notes

#### MP4 vs MKV for Subtitle Embedding

- **MP4:** Widely compatible, but limited subtitle format support. Best for devices/players with limited format support.
- **MKV:** Better subtitle support (multiple tracks, more formats), but less universal compatibility.

For maximum compatibility, the tool defaults to MP4 with embedded subtitles when possible, falling back to 
external .srt files when embedding fails.

### Troubleshooting

#### Common Issues
- **"ffmpeg not found":** Ensure ffmpeg is installed and in your system PATH
- **"yt-dlp not installed":** Run `pip install -r requirements.txt`
- **Network errors:** Check internet connection; YouTube may be rate-limiting
- **Format not available:** Use `--simulate` to see available formats
- **Subtitle embedding fails:** Ensure video container supports subtitles (use MKV for best results)

#### Error Codes

- `0`: Success
- `1`: General error
- `2`: Network error
- `3`: Invalid input
- `4`: Missing dependency

## Legal and Ethical Notice

⚠️ **Important:** This tool is provided for educational purposes and personal use only.

- Only download content you have permission to download
- Respect copyright laws in your jurisdiction
- Follow YouTube's Terms of Service
- Consider supporting content creators through official channels
- Do not use this tool for piracy or copyright infringement

The authors of this tool are not responsible for any misuse or legal consequences arising from its use.

## Performance Tips

- Use `--quiet` for faster downloads (reduces output overhead)
- Specify exact formats with `-f` to avoid format selection overhead
- Use `--simulate` first to preview available formats
- For batch downloads, consider using a playlist URL instead of multiple video URLs

---
## Aside: How to cut a video

### Install ffmpeg

Make sure you [download a recent version of `ffmpeg`](http://ffmpeg.org/download.html), and don't use the one 
that comes with your distribution (e.g. Ubuntu). Packaged versions from various distributions are often outdated 
and do not behave as expected.

Or [compile it yourself](https://trac.ffmpeg.org/wiki/CompilationGuide). Under macOS, you can 
[use Homebrew](https://brew.sh/) and `brew install ffmpeg`.

### Cutting a video without re-encoding

Use this to cut video from `[start]` for `[duration]`:

```bash
ffmpeg -ss [start] -i in.mp4 -t [duration] -map 0 -c copy out.mp4
```

Use this to cut video from [start] to [end]:

```bash
ffmpeg -copyts -ss [start] -i in.mp4 -to [end] -map 0 -c copy out.mp4
```

#### Explaining the options

The options mean the following:

- `-ss` specifies the start time, e.g. `00:01:23.000` or `83` (in seconds)
- `-t` specifies the duration of the clip. The format of the time is the same.
- Instead of `-t`, you can also use `-to`, which specifies the end time.
- `-map 0` maps all streams: audio, video and subtitles
- `-copyts` preserves the original timestamps from the input file
- `-c` copy copies the first video, audio, and subtitle bitstream from the input to the output file without 
re-encoding them. This won't harm the quality and make the command run within seconds.

**Important note about `-copyts`:** By default, ffmpeg resets timestamps to start from 0 after seeking with `-ss`. 
When you use `-copyts`, the original timestamps are preserved, which makes `-to` work as expected (specifying the 
absolute end time from the original file). Without `-copyts`, the `-to` parameter behaves unexpectedly because it 
operates on the reset timeline.

For example:

```bash
ffmpeg -ss 5 -i in.mp4 -t 30 -map 0 -c copy out.mp4
```

This seeks forward in the input by 5 seconds and generates a 30-second long output file. In other words, you get 
the input video's part from 5–35 seconds.

#### Without `-copyts` (timestamps reset to 0):

```bash
ffmpeg -ss 5 -i in.mp4 -to 30 -map 0 -c copy out.mp4
```

This does NOT give you 5–35 seconds as you might expect. Instead, it gives you a 30-second output because the 
timestamps are reset to 0 after the initial seek, making `-to 30` equivalent to `-t 30`.

#### With `-copyts` (preserves original timestamps):

```bash
ffmpeg -copyts -ss 5 -i in.mp4 -to 35 -map 0 -c copy out.mp4
```

This correctly gives you the part from 5–35 seconds (30 seconds total) because `-copyts` preserves the original 
timeline, allowing `-to 35` to work intuitively.

**Do you need timestamps starting at 0?** The `-copyts` approach creates output files where timestamps don't start 
at 0 (they preserve the original timeline). For most playback scenarios, this works fine. However, if you need 
timestamps starting exactly at 0 (for editing workflows, concatenation, or certain streaming platforms), you can 
add a second pass:

```bash
ffmpeg -copyts -ss 5 -i in.mp4 -to 35 -map 0 -c copy temp.mp4
ffmpeg -i temp.mp4 -c copy out.mp4
rm temp.mp4
```

For more info on seeking, see https://trac.ffmpeg.org/wiki/Seeking

### Cutting a video with re-encoding

Sometimes, using `-c copy` leads to output files that some players cannot process (they'll show a black frame or 
have audio-video sync errors).

If you leave out the `-c copy` option, `ffmpeg` will automatically re-encode the output video and audio according 
to the format you chose. For high quality video and audio, read the 
[x264 Encoding Guide](https://ffmpeg.org/trac/ffmpeg/wiki/x264EncodingGuide) and the 
[AAC Encoding Guide](http://ffmpeg.org/trac/ffmpeg/wiki/AACEncodingGuide), respectively.

For example:

```bash
ffmpeg -ss [start] -i in.mp4 -t [duration] -c:v libx264 -crf 23 -c:a aac -b:a 192k out.mp4
```

You can change the CRF and audio bitrate parameters to vary the output quality. Lower CRF means better quality, 
and vice-versa. Sane values are between 18 and 28.

---


## Contributing
Feel free to submit issues, fork the repository, and create pull requests for any improvements.

## License

MIT License - See [LICENSE](LICENSE) file for details

## Acknowledgments

- Built on top of [yt-dlp](https://github.com/yt-dlp/yt-dlp)
- Uses [ffmpeg](https://github.com/yt-dlp/yt-dlp) for media processing
- Progress bars powered by [tqdm](https://github.com/tqdm/tqdm)
