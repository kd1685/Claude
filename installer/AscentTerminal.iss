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
#define AppVersion "1.0.1"
#define AppPublisher "Ascent Terminal"
#define AppURL "https://ascentterminal.com"
#define AppExe "AscentTerminal.exe"
#define DotNetMinMajor 8

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

[Code]

// ---------------------------------------------------------------------------
// .NET Runtime detection
// Checks HKLM\SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.NETCore.App
// for any key whose name starts with "8." (i.e. .NET 8.x is installed).
// Falls back to x86 path on 32-bit systems.
// ---------------------------------------------------------------------------
function IsDotNetInstalled(MajorVersion: Integer): Boolean;
var
  SubKeyNames: TArrayOfString;
  RegPath: String;
  i: Integer;
begin
  Result := False;

  // Try 64-bit path first, then 32-bit
  RegPath := 'SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx\Microsoft.NETCore.App';
  if not RegGetSubkeyNames(HKLM, RegPath, SubKeyNames) then
    RegPath := 'SOFTWARE\dotnet\Setup\InstalledVersions\x86\sharedfx\Microsoft.NETCore.App';
  if not RegGetSubkeyNames(HKLM, RegPath, SubKeyNames) then
    Exit;

  for i := 0 to GetArrayLength(SubKeyNames) - 1 do
  begin
    // Each subkey name is a version string like "8.0.14"
    if Copy(SubKeyNames[i], 1, Length(IntToStr(MajorVersion)) + 1) =
       IntToStr(MajorVersion) + '.' then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

// ---------------------------------------------------------------------------
// Called before the installer pages are shown.
// Blocks install and directs user to download .NET if missing.
// ---------------------------------------------------------------------------
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Answer: Integer;
begin
  Result := '';

  if not IsDotNetInstalled({#DotNetMinMajor}) then
  begin
    Answer := MsgBox(
      'Ascent Terminal requires the .NET ' + IntToStr({#DotNetMinMajor}) + ' Runtime, ' +
      'which is not installed on this machine.' + #13#10 + #13#10 +
      'Click OK to open the download page, then:' + #13#10 +
      '  1. Download ".NET Runtime ' + IntToStr({#DotNetMinMajor}) + '.x" (not the SDK)' + #13#10 +
      '  2. Install it' + #13#10 +
      '  3. Re-run this installer' + #13#10 + #13#10 +
      'Click Cancel to abort the installation.',
      mbConfirmation, MB_OKCANCEL);

    if Answer = IDOK then
      ShellExec('open', 'https://dotnet.microsoft.com/download/dotnet/' +
        IntToStr({#DotNetMinMajor}) + '.0', '', '', SW_SHOWNORMAL, ewNoWait, Answer);

    Result := '.NET ' + IntToStr({#DotNetMinMajor}) + ' Runtime is required. ' +
              'Please install it and re-run the installer.';
  end;
end;
