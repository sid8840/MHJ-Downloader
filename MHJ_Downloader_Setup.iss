#define MyAppName "महाराष्ट्राची हास्य जत्रा"
#define MyAppVersion "1.0.1"
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
OutputBaseFilename=MHJ-Downloader-v1.0.1-Setup

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

VersionInfoVersion=1.0.1.0
VersionInfoProductName=MHJ Downloader
VersionInfoProductVersion=1.0.1
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

[Code]
var
  RemoveApplicationData: Boolean;

function CreateDataRemovalForm(): Boolean;
var
  Form: TSetupForm;
  TitleLabel: TNewStaticText;
  InfoLabel: TNewStaticText;
  WarningLabel: TNewStaticText;
  CheckBox: TNewCheckBox;
  RemoveButton: TNewButton;
  KeepButton: TNewButton;
begin
  Form := CreateCustomForm(ScaleX(560), ScaleY(300), False, False);
  Form.Caption := 'महाराष्ट्राची हास्य जत्रा - Uninstall';
  Form.BorderStyle := bsDialog;

  TitleLabel := TNewStaticText.Create(Form);
  TitleLabel.Parent := Form;
  TitleLabel.Left := ScaleX(24);
  TitleLabel.Top := ScaleY(20);
  TitleLabel.Width := ScaleX(510);
  TitleLabel.Height := ScaleY(28);
  TitleLabel.Font.Size := 13;
  TitleLabel.Font.Style := [fsBold];
  TitleLabel.Caption := 'What would you like to remove?';

  InfoLabel := TNewStaticText.Create(Form);
  InfoLabel.Parent := Form;
  InfoLabel.Left := ScaleX(24);
  InfoLabel.Top := ScaleY(62);
  InfoLabel.Width := ScaleX(510);
  InfoLabel.Height := ScaleY(45);
  InfoLabel.Caption := 'The application itself will be removed. Application data is normally kept for future reinstallation.';

  CheckBox := TNewCheckBox.Create(Form);
  CheckBox.Parent := Form;
  CheckBox.Left := ScaleX(24);
  CheckBox.Top := ScaleY(125);
  CheckBox.Width := ScaleX(510);
  CheckBox.Height := ScaleY(24);
  CheckBox.Caption := 'Remove application data and settings';
  CheckBox.Checked := False;

  WarningLabel := TNewStaticText.Create(Form);
  WarningLabel.Parent := Form;
  WarningLabel.Left := ScaleX(44);
  WarningLabel.Top := ScaleY(160);
  WarningLabel.Width := ScaleX(490);
  WarningLabel.Height := ScaleY(42);
  WarningLabel.Caption := 'Warning: this permanently deletes settings, download history, catalogue/cache, logs and other data stored by the application.';

  KeepButton := TNewButton.Create(Form);
  KeepButton.Parent := Form;
  KeepButton.Left := ScaleX(326);
  KeepButton.Top := ScaleY(238);
  KeepButton.Width := ScaleX(100);
  KeepButton.Height := ScaleY(30);
  KeepButton.Caption := 'Keep Data';
  KeepButton.ModalResult := mrNo;

  RemoveButton := TNewButton.Create(Form);
  RemoveButton.Parent := Form;
  RemoveButton.Left := ScaleX(436);
  RemoveButton.Top := ScaleY(238);
  RemoveButton.Width := ScaleX(100);
  RemoveButton.Height := ScaleY(30);
  RemoveButton.Caption := 'Uninstall';
  RemoveButton.ModalResult := mrYes;

  Form.ActiveControl := KeepButton;

  Result := Form.ShowModal = mrYes;
  RemoveApplicationData := CheckBox.Checked;
end;

function InitializeUninstall(): Boolean;
begin
  RemoveApplicationData := False;
  Result := CreateDataRemovalForm();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveApplicationData then
  begin
    DataDir := ExpandConstant('{commonappdata}\MHJ Downloader');

    if DirExists(DataDir) then
    begin
      Log('Removing application data: ' + DataDir);

      if DelTree(DataDir, True, True, True) then
        Log('Application data removed successfully.')
      else
        MsgBox(
          'The application was uninstalled, but some application data could not be removed. Location: ' + DataDir,
          mbError,
          MB_OK
        );
    end;
  end;
end;
