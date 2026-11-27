; Inno Setup 6 script for maew usage (per-user Windows installer, no UAC prompt)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{7B6E8C2F-4F4A-4D7E-9A5D-2C8E4B3A9102}
AppName=maew usage
AppVersion={#AppVersion}
AppVerName=maew usage {#AppVersion}
AppPublisher=maew usage
AppPublisherURL=https://github.com/ieatbaozi-stack/maew-ai-check
AppSupportURL=https://github.com/ieatbaozi-stack/maew-ai-check/issues
AppUpdatesURL=https://github.com/ieatbaozi-stack/maew-ai-check/releases
DefaultDirName={autopf}\maew-usage
DefaultGroupName=maew usage
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=maew-usage-v{#AppVersion}-windows-x64-setup
SetupIconFile=..\src\maew\assets\maew-usage.ico
UninstallDisplayIcon={app}\maew-usage.exe
UninstallDisplayName=maew usage
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Launch maew usage automatically when Windows starts"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\maew-usage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\maew usage"; Filename: "{app}\maew-usage.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\maew\assets\maew-usage.ico"
Name: "{autodesktop}\maew usage"; Filename: "{app}\maew-usage.exe"; WorkingDir: "{app}"; IconFilename: "{app}\_internal\maew\assets\maew-usage.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "maew usage"; ValueData: """{app}\maew-usage.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\maew-usage.exe"; Description: "{cm:LaunchProgram,maew usage}"; Flags: nowait postinstall skipifsilent
