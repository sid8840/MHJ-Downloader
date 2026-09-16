# महाराष्ट्राची हास्य जत्रा Downloader

A Windows desktop downloader for **SonyLIV's महाराष्ट्राची हास्य जत्रा**.

The application is designed to be simple to operate, with a parent-friendly interface focused on downloading episodes and maintaining an existing local collection.

---

## Latest Release — v1.0.1

**v1.0.1** is the latest official release.

### Download

Download the latest Windows installer from the [GitHub Releases](../../releases/latest) page.

The installer is intended for:

- Windows 10 / Windows 11
- 64-bit (x64) systems

The installed application does **not** require Python or manual Python package installation.

---

## Installation

Run:

```text
MHJ-Downloader-v1.0.1-Setup.exe
```

The application is installed under:

```text
C:\Program Files\MHJ Downloader\
```

Application data and user settings are stored separately under:

```text
C:\ProgramData\MHJ Downloader\
```

This keeps the installed application separate from user-generated application data.

---

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

FFmpeg and FFprobe are bundled with the application. No separate FFmpeg installation or PATH configuration is required.

---

## Download Modes

### New Episodes

New Episodes mode is designed for maintaining an existing local collection.

The application checks the local download folder and compares the local collection with the episodes available from SonyLIV.

It can detect:

- New episodes
- Missing episodes inside an existing collection

For example, if the local collection contains:

```text
798 - 839
```

and SonyLIV has episodes available through:

```text
851
```

the application can identify:

```text
840 - 851
```

rather than assuming that only the newest 10 episodes are missing.

### Empty Download Folder

When New Episodes mode is selected and the destination folder is empty, the application downloads only the latest 10 episodes.

To process more episodes, select a specific episode, an episode range, or another appropriate mode in Settings.

### Specific Episode

Downloads a selected episode number.

### Episode Range

Downloads a specified range of episodes.

Example:

```text
824 - 850
```

### Entire Library

Checks the available SonyLIV catalogue and processes the library according to the local collection and download state.

---

## Local Collection Handling

The local files are treated as the primary authority for determining whether an episode is already present.

Download history is maintained separately, allowing the application to track download state and reconcile cases where the on-disk collection and history differ.

The basic reconciliation logic is:

```text
Episode exists on disk
        ↓
Already downloaded
        ↓
Skip

Episode missing on disk
        ↓
Determine download state
        ↓
Download or resume as appropriate
```

This prevents already downloaded episodes from being unnecessarily downloaded again.

---

## Resumable Downloads

Downloads use private temporary working data so that interrupted downloads can be continued rather than restarted from the beginning.

Temporary fragments and intermediate files are kept outside the main download folder.

When a download is successfully finalized:

```text
Temporary working data
        ↓
Media processing / finalization
        ↓
Completed MP4
        ↓
Selected download folder
```

Only the completed MP4 is placed in the destination folder.

---

## Premium Episodes

Some SonyLIV episodes may require authentication or premium access.

When yt-dlp reports that authentication is required, the application identifies the episode as premium content and skips it rather than repeatedly retrying the download.

Premium episodes therefore do not unnecessarily block processing of other episodes.

---

## FFmpeg

FFmpeg and FFprobe are bundled with the application.

No separate FFmpeg installation or PATH configuration is required for the installed application.

They are used for processing and finalizing downloaded media.

---

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

---

## Activity Logs

Application activity logs are stored under:

```text
C:\ProgramData\MHJ Downloader\logs\
```

A new activity log is created for each application session.

These logs are useful when diagnosing:

- SonyLIV connectivity
- Episode discovery
- Download operations
- Media processing
- Errors and interrupted operations

When reporting a problem, provide the relevant session log from the logs directory.

---

## Uninstallation

The uninstaller provides a choice regarding application data.

By default, uninstalling the application does **not** remove:

```text
C:\ProgramData\MHJ Downloader\
```

This preserves settings, download history, catalogue data, and other application-owned data.

The uninstaller also provides an option to remove the application's stored data and settings.

This allows the user to choose between:

```text
Uninstall application
+
Keep application data
```

or:

```text
Uninstall application
+
Remove application data and settings
```

Selecting the data-removal option removes the application-owned data stored under the MHJ Downloader ProgramData directory.

---

## Project Structure

The repository contains:

- Application source code
- Qt Designer UI files
- PyInstaller configuration
- Installer configuration
- Application resources
- SonyLIV catalogue data

Generated build output, runtime data, logs, temporary download files, installer output, and local development backups are intentionally excluded from the Git repository.

---

## Versioning

The project uses Git tags and GitHub Releases for official application versions.

Current release:

```text
v1.0.1
```

Release history:

```text
v1.0
    First official release

v1.0.1
    Installer and application maintenance release
```

Future versions will be published as new GitHub Releases with their corresponding Windows installer.

---

## License

License information will be added when the project is formally licensed.

---

## Disclaimer

This software is an independent downloader application and is not affiliated with or endorsed by SonyLIV.

Users are responsible for complying with SonyLIV's terms of service and applicable copyright laws when using the application.
