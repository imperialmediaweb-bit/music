; ============================================================
; LUTH — Inno Setup Installer Script
; Creates a professional Windows installer (.exe)
;
; To build: Install Inno Setup (https://jrsoftware.org/isinfo.php)
;           then compile this file.
; ============================================================

#define MyAppName "LUTH"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "LUTH Music"
#define MyAppURL "https://github.com/luth-music"
#define MyAppExeName "LUTH.vbs"

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
WizardImageFile=assets\wizard.bmp
WizardSmallImageFile=assets\wizard_small.bmp
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Include all project files
Source: "app.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "pipeline.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "config.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: ".env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "install.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "run.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "run.sh"; DestDir: "{app}"; Flags: ignoreversion
Source: "modules\*"; DestDir: "{app}\modules"; Flags: ignoreversion recursesubdirs
Source: "utils\*"; DestDir: "{app}\utils"; Flags: ignoreversion recursesubdirs
Source: "tests\*"; DestDir: "{app}\tests"; Flags: ignoreversion recursesubdirs
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

[Dirs]
Name: "{app}\output"
Name: "{app}\input"
Name: "{app}\cookies"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\LUTH.vbs"; IconFilename: "{app}\assets\luth.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\LUTH.vbs"; IconFilename: "{app}\assets\luth.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
; Run install.bat after files are extracted
Filename: "{app}\install.bat"; Description: "Install dependencies (Python, FFmpeg, etc.)"; Flags: nowait postinstall skipifsilent shellexec
Filename: "{app}\LUTH.vbs"; Description: "Launch LUTH"; Flags: nowait postinstall skipifsilent unchecked shellexec

[Code]
// Create LUTH.vbs launcher during install
procedure CurStepChanged(CurStep: TSetupStep);
var
  VBSContent: String;
begin
  if CurStep = ssPostInstall then
  begin
    VBSContent :=
      'Set WshShell = CreateObject("WScript.Shell")' + #13#10 +
      'WshShell.CurrentDirectory = "' + ExpandConstant('{app}') + '"' + #13#10 +
      'WshShell.Run "cmd /c call venv\Scripts\activate.bat && pythonw app.py", 0, False' + #13#10;
    SaveStringToFile(ExpandConstant('{app}\LUTH.vbs'), VBSContent, False);

    // Create .env from template if not exists
    if not FileExists(ExpandConstant('{app}\.env')) then
    begin
      FileCopy(ExpandConstant('{app}\.env.example'), ExpandConstant('{app}\.env'), False);
    end;
  end;
end;
