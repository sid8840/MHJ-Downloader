#define MyAppName "महाराष्ट्राची हास्य जत्रा"
#define MyAppVersion "2.2.12"
#define MyAppPublisher "Siddhesh Dinde"
#define MyAppExeName "महाराष्ट्राची हास्य जत्रा.exe"

[Setup]
AppId={{C41976EF-59BB-47BC-A456-0DA79C32B507}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}

DefaultDirName={autopf}\MHJ Downloader
DefaultGroupName=MHJ Downloader

OutputDir=installer
OutputBaseFilename=MHJ-Downloader-v2.2.12-Setup

SetupIconFile=mhj.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumFastBytes=273

WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

DisableProgramGroupPage=yes

VersionInfoVersion=2.2.12.0
VersionInfoProductName=MHJ Downloader
VersionInfoProductVersion=2.2.12
VersionInfoDescription=महाराष्ट्राची हास्य जत्रा
VersionInfoCompany={#MyAppPublisher}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\महाराष्ट्राची हास्य जत्रा\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MHJ Downloader"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\MHJ Downloader"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch MHJ Downloader"; Flags: nowait postinstall skipifsilent
