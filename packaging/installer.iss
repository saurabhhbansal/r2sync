// Inno Setup Script for r2sync Windows Installer
#define MyAppName "r2sync"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "saurabhhbansal"
#define MyAppURL "https://github.com/saurabhhbansal/r2sync"
#define MyAppExeName "r2sync.exe"
#define MyServiceExeName "r2sync-service.exe"

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
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Start r2sync background service on Windows startup"; GroupDescription: "Background Service:"

[Files]
Source: "..\dist\r2sync\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyServiceExeName}"" --standalone"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyServiceExeName}"; Parameters: "--standalone"; Flags: nowait postinstall skipifsilent; Description: "Start r2sync background service"
Filename: "{app}\{#MyAppExeName}"; Flags: nowait postinstall skipifsilent; Description: "Launch r2sync application"

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden
Filename: "taskkill"; Parameters: "/F /IM {#MyServiceExeName}"; Flags: runhidden

[UninstallDelete]
Type: files; Name: "{app}\*.log"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // Note: Remote Cloudflare R2 backup data is NEVER deleted upon uninstallation.
  end;
end;
