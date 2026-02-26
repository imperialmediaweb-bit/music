; ============================================================
; LUTH — Inno Setup Installer Script
; Creates a professional Windows installer (.exe)
;
; Packages the PyInstaller standalone build (dist\LUTH\).
; No Python, pip, or venv needed — everything is bundled.
;
; To build:
;   1. Run build.bat first (creates dist\LUTH\)
;   2. Then compile this with Inno Setup
; ============================================================

#define MyAppName "LUTH"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "LUTH Music"
#define MyAppURL "https://github.com/imperialmediaweb-bit/music"
#define MyAppExeName "LUTH.exe"

[Setup]
AppId={{B8F5E8A1-4C2D-4F6E-9A1B-3D5E7F8C9A0B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=LUTH_Setup_{#MyAppVersion}
SetupIconFile=assets\luth.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Include entire PyInstaller output (all dependencies bundled)
Source: "dist\LUTH\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
Name: "{app}\output"
Name: "{app}\input"
Name: "{app}\cookies"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\luth.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\luth.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch LUTH"; Flags: nowait postinstall skipifsilent

[Code]
// Create .env from template if not exists
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not FileExists(ExpandConstant('{app}\.env')) then
    begin
      FileCopy(ExpandConstant('{app}\.env.example'), ExpandConstant('{app}\.env'), False);
    end;
  end;
end;
