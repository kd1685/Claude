; =====================================================================
;  Ascent Terminal — Windows installer (Inno Setup script)
;
;  1. Build the app first:   cd ../desktop && python build_desktop.py
;  2. Install Inno Setup (free): https://jrsoftware.org/isinfo.php
;  3. Open this file in Inno Setup -> Build -> Compile
;  Output: installer_output/AscentTerminal-Setup-1.0.0.exe
;
;  A real installer (with publisher info, version metadata, an uninstall
;  entry and Start-menu shortcuts) builds far more antivirus/SmartScreen
;  reputation than a bare .exe in a zip. Sign it too if you have a cert:
;  Tools -> Configure Sign Tools ->
;    signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a $f
; =====================================================================

#define AppName "Ascent Terminal"
#define AppVersion "1.0.0"
#define AppPublisher "Ascent Terminal"
#define AppURL "https://ascentterminal.com"
#define AppExe "AscentTerminal.exe"

[Setup]
AppId={{B7A2E6C4-9D31-4F8A-A4C2-ASCENTTERM01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer_output
OutputBaseFilename=AscentTerminal-Setup-{#AppVersion}
SetupIconFile=..\desktop\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
; ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\desktop\dist\AscentTerminal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
