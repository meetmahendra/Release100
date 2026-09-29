; Release100 Kiosk & Retail Edition Windows Single Executable Installer Script
; Inno Setup 6.x Script
; Copyright 2026 Mahendra GURAV (Apache License 2.0)

#define MyAppName "Release100 Kiosk & Retail Edition"
#define MyAppVersion "1.3.0"
#define MyAppPublisher "Mahendra GURAV"
#define MyAppURL "https://github.com/mahendragurav/Release100"
#define MyAppExeName "Release100_Kiosk.exe"

[Setup]
AppId={{C1E4A812-74DF-4B6A-9122-CANEBOT04KIO}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\Release100_Kiosk
DefaultGroupName=Release100 Kiosk Edition
AllowNoIcons=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=Release100_Kiosk_Setup_v1.3.0
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Launch Release100 Kiosk automatically at Windows startup"; GroupDescription: "Windows Integration:"

[Files]
Source: "..\..\dist\Release100_Kiosk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "run --mode tray"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "health"; Description: "Verify installation and run health diagnostic"; Flags: nowait postinstall skipifsilent
