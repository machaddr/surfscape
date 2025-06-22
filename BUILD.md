# Surfscape Build System

This document describes how to build Surfscape into a standalone executable using the provided build system.

## Overview

The build system uses PyInstaller to create static executables for both Linux/Unix and Windows platforms. The build process creates a single executable file that includes all dependencies.

## Files

- `build.sh` - Linux/Unix build script
- `build.bat` - Windows build script
- `clean.sh` - Linux/Unix cleanup script
- `clean.bat` - Windows cleanup script
- `surfscape.spec` - PyInstaller specification file
- `requirements.txt` - Python dependencies

## Prerequisites

### For Linux/Unix:
- Python 3.6 or higher
- pip3
- Development packages for audio (for PyAudio)

On Ubuntu/Debian:
```bash
sudo apt-get install python3-dev portaudio19-dev
```

On CentOS/RHEL/Fedora:
```bash
sudo yum install python3-devel portaudio-devel
# or for newer versions:
sudo dnf install python3-devel portaudio-devel
```

### For Windows:
- Python 3.6 or higher (from python.org)
- Microsoft Visual C++ Build Tools (for some packages)

## Building

### Linux/Unix

1. Open a terminal in the project directory
2. Run the build script:
   ```bash
   ./build.sh
   ```

The script will:
- Create a virtual environment
- Install all dependencies
- Clean previous builds
- Build the executable using PyInstaller
- Test the executable

### Windows

1. Open Command Prompt or PowerShell in the project directory
2. Run the build script:
   ```cmd
   build.bat
   ```

The script will:
- Create a virtual environment
- Install all dependencies
- Clean previous builds
- Build the executable using PyInstaller

## Output

The executable will be created in the `dist/` directory:
- Linux/Unix: `dist/surfscape`
- Windows: `dist/surfscape.exe`

## Cleaning

To clean all build artifacts:

### Linux/Unix:
```bash
./clean.sh
```

### Windows:
```cmd
clean.bat
```

## Customization

### Adding an Icon

To add an icon to the executable:

1. Place your icon file in the project directory
2. Edit `surfscape.spec` and update the `icon` parameter:
   ```python
   # For Windows
   icon='icon.ico'
   
   # For macOS
   icon='icon.icns'
   ```

### Build Options

The PyInstaller spec file (`surfscape.spec`) can be customized:

- `console=False` - Creates a windowed application (no console)
- `upx=True` - Enables UPX compression (if UPX is installed)
- `onefile=True` - Creates a single executable file
- `debug=False` - Disables debug output

### Dependencies

If you need to add new Python packages:

1. Add them to `requirements.txt`
2. If they're not automatically detected, add them to the `hiddenimports` list in `surfscape.spec`

## Troubleshooting

### Common Issues

1. **PyAudio installation fails**:
   - Install system audio development packages (see Prerequisites)
   - On Windows, you may need Visual C++ Build Tools

2. **Missing modules in executable**:
   - Add missing modules to `hiddenimports` in `surfscape.spec`

3. **Large executable size**:
   - Review dependencies in `requirements.txt`
   - Consider using `--exclude-module` for unused packages

4. **Executable doesn't start**:
   - Run with `--debug` flag to see detailed output
   - Check for missing system libraries with `ldd` (Linux) or Dependency Walker (Windows)

### Build Flags

The build scripts support environment variables for customization:

```bash
# Linux/Unix
PYTHON_EXECUTABLE=python3.9 ./build.sh

# Windows
set PYTHON_EXECUTABLE=python.exe && build.bat
```

## Distribution

The built executable can be distributed as a single file. Users don't need Python or any dependencies installed.

### System Requirements for End Users

- **Linux**: glibc 2.17+ (most modern distributions)
- **Windows**: Windows 7 SP1+ (64-bit)
- **macOS**: macOS 10.9+ (if building on macOS)

## Notes

- The first build may take longer as it downloads and installs dependencies
- Subsequent builds are faster as dependencies are cached
- The executable size will be larger than the source code due to included Python interpreter and libraries
- For production builds, consider signing the executable on Windows and macOS
