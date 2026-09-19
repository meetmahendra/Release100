; Release100 Windows Single Executable Installer Script
; Inno Setup 6.x Script
; Copyright 2026 Mahendra GURAV (Apache License 2.0)

#define MyAppName "Release100 Industrial Automation Platform"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "Mahendra GURAV"
#define MyAppURL "https://github.com/mahendragurav/Release100"
#define MyAppExeName "Release100.exe"

[Setup]
AppId={{D1F4B924-428E-45EE-A85A-8A46B01BC100}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Release100
DefaultGroupName=Release100
AllowNoIcons=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=Release100_Setup_v1.3.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Launch Release100 automatically at Windows startup"; GroupDescription: "Windows Integration:"

[Files]
Source: "..\..\dist\Release100\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "run --mode headless"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "health"; Description: "Verify installation and run health diagnostic"; Flags: nowait postinstall skipifsilent
