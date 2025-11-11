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

1. **[Python 3.7+](https://www.python.org/downloads/)** installed on your system
2. **[ffmpeg](http://ffmpeg.org/download.html)** (required for audio conversion and subtitle embedding)

### Step 1: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Run the download tool

```bash
python main.py https://youtube.com/watch?v=VIDEO_ID
```

### Usage

```bash
python main.py --help
```

```bash
usage: main.py [-h] [-o OUTPUT_DIR] [-f FORMAT] [--audio-only] [--video-only] [-s] [--sub-lang SUB_LANG] [--embed-subs] [-m] [--overwrite] [--quiet] [--progress] [--max-filesize MAX_FILESIZE] [--simulate] urls [urls ...]

YouTube Download Tool - Download videos with format selection and subtitle support

positional arguments:
  urls                  YouTube video or playlist URL(s)

options:
  -h, --help            show this help message and exit
  -o, --output-dir OUTPUT_DIR
                        Output directory (default: E:\PycharmProjects\youtube-downloader)
  -f, --format FORMAT   Format selection (yt-dlp format string or itag)
  --audio-only          Download audio only (best audio unless --format specified)
  --video-only          Download video only (no audio)
  -s, --subtitles       Download subtitles
  --sub-lang SUB_LANG   Subtitle language code (e.g., en, fr, or "all") (default: en)
  --embed-subs          Embed subtitles into video file (requires ffmpeg)
  -m, --merge           Merge audio and video streams (requires ffmpeg)
  --overwrite           Overwrite existing files
  --quiet               Minimal output
  --progress            Show download progress (default: True)
  --max-filesize MAX_FILESIZE
                        Maximum file size in MB
  --simulate, --dry-run
                        Show what would be downloaded without downloading
```

### Examples
  
#### Download best quality video

```bash
python main.py https://youtube.com/watch?v=VIDEO_ID
```

#### Download audio only as MP3

```bash 
python main.py --audio-only https://youtube.com/watch?v=VIDEO_ID
```
 
#### Download with subtitles and embed them

```bash 
python main.py --subtitles --embed-subs --sub-lang en https://youtube.com/watch?v=VIDEO_ID
```

#### List available formats

```bash
python main.py --simulate https://youtube.com/watch?v=VIDEO_ID
```

#### Download specific format

```bash 
python main.py -f 137+140 https://youtube.com/watch?v=VIDEO_ID
```         

## How to cut a video

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
