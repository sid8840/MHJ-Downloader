# महाराष्ट्राची हास्य जत्रा Downloader

A Windows desktop downloader for **SonyLIV's महाराष्ट्राची हास्य जत्रा**.

The application is designed to be simple to operate, with a parent-friendly interface focused on downloading episodes and maintaining an existing local collection.

## v1.0

This is the first official release of the application.

### Download

Download the latest installer from the [GitHub Releases](../../releases) page.

The installer is intended for:

- Windows 10 / Windows 11
- 64-bit systems

The installed application does not require Python or manual Python package installation.

## Installation

Run:

```text
MHJ-Downloader-v1.0-Setup.exe
```

The application is installed under:

```text
C:\Program Files\MHJ Downloader\
```

Application data and user settings are stored separately under:

```text
C:\ProgramData\MHJ Downloader\
```

This keeps the installed application separate from user-generated data.

## Main Features

- SonyLIV episode discovery
- Automatic source discovery
- Manual SonyLIV episode/collection URL
- New Episodes mode
- Specific Episode mode
- Episode Range mode
- Entire Library mode
- Episode thumbnails
- Resumable downloads
- FFmpeg-based finalization
- Download progress and overall progress
- STOP operation with resumable temporary data preserved
- Download history
- Local collection reconciliation
- Premium-content detection and skipping
- Persistent settings
- Windows x64 installer

## Download Modes

### New Episodes

New Episodes mode is designed for maintaining an existing collection.

The application checks the local download folder and compares the local collection with the episodes available from SonyLIV.

It can detect:

- New episodes
- Missing episodes inside an existing collection

If the destination folder is empty, the application downloads only the latest 10 episodes.

If the collection already exists, the application reconciles the available SonyLIV episode list with the local files instead of simply assuming that only the newest episodes are missing.

### Specific Episode

Downloads a selected episode number.

### Episode Range

Downloads a specified range of episodes.

For example:

```text
824 - 850
```

### Entire Library

Checks the available SonyLIV catalogue and processes the library according to the local collection and download history.

## Local Collection Handling

The local files are treated as the primary authority for determining whether an episode is already present.

The application maintains download history separately, allowing it to repair history when an episode exists on disk but is missing from the history record.

The basic reconciliation logic is:

```text
Episode exists on disk
        ↓
Already downloaded
        ↓
Skip

Episode missing on disk
        ↓
Check download state/history
        ↓
Download or resume as appropriate
```

This prevents already downloaded episodes from being unnecessarily downloaded again.

## Resumable Downloads

Downloads use temporary working data so that an interrupted download can be continued rather than restarted from the beginning.

Temporary download data is kept outside the main download folder.

When a download is successfully finalized, only the completed MP4 is placed in the selected destination folder.

## Premium Episodes

Some SonyLIV episodes may require authentication or premium access.

When yt-dlp reports that authentication is required, the application identifies the episode as premium content and skips it rather than repeatedly retrying the download.

If the remaining required episodes are successfully downloaded, premium episodes do not cause the entire download operation to be reported as a failure.

## FFmpeg

FFmpeg and FFprobe are bundled with the application.

No separate FFmpeg installation or PATH configuration is required for the installed application.

They are used for processing and finalizing downloaded media.

## Settings

The Settings window provides:

- Automatic or manual SonyLIV source
- Episode selection mode
- Download folder
- Simultaneous episode setting
- Concurrent fragment setting
- Retry attempts
- Collection maintenance

Settings are stored under:

```text
C:\ProgramData\MHJ Downloader\data\
```

## Activity Logs

Application activity logs are stored under:

```text
C:\ProgramData\MHJ Downloader\logs\
```

A new activity log is created for each application session.

These logs are useful when diagnosing SonyLIV connectivity, discovery, download, or processing problems.

## Troubleshooting

If a download or discovery operation behaves unexpectedly, provide the relevant session log from:

```text
C:\ProgramData\MHJ Downloader\logs\
```

The log contains information about the application's discovery, download, processing, and error states.

## Project Structure

The repository contains the application source, Qt Designer UI files, PyInstaller configuration, installer configuration, application resources, and the catalogue used by the application.

Generated build output, runtime data, logs, temporary download files, and local development backups are intentionally excluded from the Git repository.

## Versioning

The project uses Git tags and GitHub Releases for application versions.

The official baseline is:

```text
v1.0
```

Future versions will be published as new GitHub Releases with their corresponding Windows installer.

## License

License information will be added when the project is formally licensed.

## Disclaimer

This software is an independent downloader application and is not affiliated with or endorsed by SonyLIV.

Users are responsible for complying with SonyLIV's terms of service and applicable copyright laws when using the application.
