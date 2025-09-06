; Inno Setup Script for Surfscape
; Assumes PyInstaller built app resides in DistDir (passed via /DDistDir) with executable surfscape.exe

; Accept /DVersion, /DDistDir, /DOutputDir passed from ISCC; otherwise fall back to defaults
#ifndef Version
#define Version "1.0"
#endif

#ifndef DistDir
#define DistDir "..\\dist\\surfscape"
#endif

#ifndef OutputDir
#define OutputDir "Output"
#endif

[Setup]
AppId={{A1E9299E-1E90-4D34-9B92-8F7B5E0A9F9A}}
AppName=Surfscape
AppVersion={#Version}
AppPublisher=André Machado
AppPublisherURL=https://github.com/machaddr/surfscape
AppSupportURL=https://github.com/machaddr/surfscape
AppUpdatesURL=https://github.com/machaddr/surfscape
DefaultDirName={pf64}\\Surfscape
DefaultGroupName=Surfscape
AllowNoIcons=yes
OutputDir={#OutputDir}
OutputBaseFilename=Surfscape-setup-{#Version}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
DisableDirPage=no
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\\surfscape.exe
LicenseFile={#DistDir}\\LICENSE
AppReadmeFile={#DistDir}\\README.md

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; Flags: unchecked

[Files]
; Main application files from PyInstaller dist folder
Source: "{#DistDir}\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\\Surfscape"; Filename: "{app}\\surfscape.exe"; WorkingDir: "{app}"
Name: "{group}\\Uninstall Surfscape"; Filename: "{uninstallexe}"
Name: "{userdesktop}\\Surfscape"; Filename: "{app}\\surfscape.exe"; Tasks: desktopicon; WorkingDir: "{app}"

[Run]
Filename: "{app}\\surfscape.exe"; Description: "Launch Surfscape"; Flags: nowait postinstall skipifsilent
