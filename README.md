# MHJ Downloader v2.0.1

Parent-friendly SonyLIV Maharashtrachi Hasya Jatra downloader.

Copy these files to:

    D:\Desktop\project\mhj

Install/update:

    py -m pip install -U -r requirements.txt

FFmpeg and ffprobe must be available in PATH.

Run:

    run_mhj.bat

## Main screen

The normal screen intentionally exposes only Download, Stop, progress, thumbnail,
current episode and Settings.

## Settings

- Automatic source discovery or manual SonyLIV URL + Check
- New Episodes (default)
- Specific Episode
- Episode Range
- Entire Library
- Download folder
- 1-5 simultaneous episodes
- concurrent fragments
- retries

## CSV + disk reconciliation

CSV present + file present: skip.
CSV absent + file present: skip and repair CSV.
CSV present + file absent: ask before re-downloading.
CSV absent + file absent: download.

## 403 handling

Direct SonyLIV requests retry with exponential backoff. If direct discovery still
fails, the program attempts yt-dlp's SonyLIVSeries extractor as a fallback.

## Troubleshooting

Send:

    D:\Desktop\project\mhj\logs\mhj_activity.log

The log rotates automatically.


## v2.0.1 SonyLIV 403 fix

SonyLIV discovery and individual episode extraction/download now use yt-dlp's
curl_cffi browser impersonation (`Chrome-116 / Windows-10`) as the primary
network path. This remains HTTP-only: no Selenium, ChromeDriver, or browser is
launched.

The old direct SonyLIV API implementation remains only as a secondary fallback.
