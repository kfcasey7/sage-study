; Inno Setup recipe for the Windows installer. Build after PyInstaller, from the repo root:
;     ISCC.exe packaging\windows\sage-study.iss
; Set the version with the SAGE_VERSION environment variable.

#define Version GetEnv("SAGE_VERSION")
#if Version == ""
  #define Version "0.0.0"
#endif

[Setup]
AppId={{7A0F5A3E-2E0C-4F0B-9E0A-5C6B1D2F9A41}
AppName=Sage Study
AppVersion={#Version}
AppPublisher=kfcasey7
AppPublisherURL=https://github.com/kfcasey7/sage-study
DefaultDirName={localappdata}\Programs\Sage Study
DefaultGroupName=Sage Study
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=SageStudy-Setup-{#Version}
SetupIconFile=..\..\backend\sage\assets\icon\icon.ico
UninstallDisplayIcon={app}\SageStudy.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\..\dist\SageStudy\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Sage Study"; Filename: "{app}\SageStudy.exe"
Name: "{autodesktop}\Sage Study"; Filename: "{app}\SageStudy.exe"

[Run]
Filename: "{app}\SageStudy.exe"; Description: "Open Sage Study"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\SageStudy');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your study data (quizzes, study guides, uploaded files)?' + #13#10 + #13#10 + DataDir + #13#10 + #13#10 + 'This can''t be undone.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
