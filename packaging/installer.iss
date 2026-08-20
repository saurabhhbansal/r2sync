// Inno Setup Script for r2sync Windows Installer
#define MyAppName "r2sync"
#define MyAppVersion "1.2.5"
#define MyAppPublisher "saurabhhbansal"
#define MyAppURL "https://github.com/saurabhhbansal/r2sync"
#define MyAppExeName "r2sync.exe"
#define MyServiceExeName "r2sync-service.exe"
#define MyCliExeName "r2sync-cli.exe"
#define MyServiceRunName "r2sync Service"

[Setup]
AppId={{D37E8492-74B0-4A59-8692-069E7FD1A982}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\dist
OutputBaseFilename=r2sync-setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; "force" rather than "yes": Restart Manager can only close an application by
; asking its window to shut, and neither of ours will oblige -- the GUI hides
; to the tray instead of exiting and the service has no window at all. When the
; polite request failed, Setup fell back to replacing the files on next boot
; and reported that a restart was required, which is what made installing on
; top of an existing copy fail. See PrepareToInstall for the rest of it.
CloseApplications=force
; Restart Manager must not relaunch what it closed: the [Run] section starts
; the service itself, and two of them race for the IPC port.
RestartApplications=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start r2sync automatically on Windows startup (minimized to system tray)"; GroupDescription: "Startup:"
Name: "autosync"; Description: "Keep folders synchronized in the background after every restart (recommended)"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\r2sync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart
; The background service is registered separately from the GUI: synchronization
; has to resume at logon whether or not the user wants the window to open.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyServiceRunName}"; ValueData: """{app}\{#MyServiceExeName}"" --standalone"; Flags: uninsdeletevalue; Tasks: autosync

[Run]
; Start syncing immediately after install rather than waiting for the next logon.
Filename: "{app}\{#MyServiceExeName}"; Parameters: "--standalone"; Flags: nowait runhidden; Tasks: autosync
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifsilent; Description: "Launch r2sync"

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden
Filename: "taskkill"; Parameters: "/F /IM {#MyServiceExeName}"; Flags: runhidden

[UninstallDelete]
Type: files; Name: "{app}\*.log"

[Code]
// Both executables are onefile PyInstaller builds, so a running copy holds its
// own .exe open and Setup cannot overwrite it. Close them before any file is
// touched rather than relying on Restart Manager reaching a windowless service.
procedure StopIfRunning(const ExeName: String);
var
  ResultCode: Integer;
begin
  // Give anything with a window the chance to shut itself down cleanly first.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM "' + ExeName + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(300);
  // /T takes the rclone the service spawned down with it. An interrupted
  // bisync is recoverable: it expires its own workdir lock via --max-lock.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM "' + ExeName + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // Nothing here needs a reboot; say so explicitly.
  NeedsRestart := False;

  StopIfRunning('{#MyAppExeName}');
  StopIfRunning('{#MyServiceExeName}');
  StopIfRunning('{#MyCliExeName}');

  // Windows releases the image file slightly after the process itself goes.
  Sleep(1200);

  // Empty string means "carry on with the installation".
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Note: Remote Cloudflare R2 backup data is NEVER deleted upon uninstallation.
  end;
end;
