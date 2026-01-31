# Surfscape Web Browser

Surfscape is a lightweight and customizable web browser built using PyQt6. It provides essential features for web browsing, including tabbed browsing, bookmarks, history, and customizable settings. Suitable for Tilling Window Managers under Linux or *BSD.

![Surfscape Web Browser](https://raw.githubusercontent.com/machaddr/surfscape/main/screenshots/browser.png)

## Features

- **Tabbed Browsing:** Open multiple web pages in separate tabs.
- **Bookmarks:** Save and manage your favorite web pages.
- **History:** Keep track of your browsing history.
- **Cookies Management:** Manage cookies for better privacy and control.
- **AdBlocker:** Block unwanted ads for a cleaner browsing experience.
    - Incremental, per-domain rule subsets compiled asynchronously using a multiprocessing pool for faster first paint.
- **Multiprocessing Offload:** Heavy tasks (Markdown rendering, adblock subset compilation) are processed in background worker processes (configurable with --workers flag).
- **Customizable Settings:** Change the homepage, theme, font, and more.
- **Keyboard Shortcuts:** Use convenient keyboard shortcuts for common actions.

## Building Executable

Surfscape uses a professional Makefile-based build system that works across Linux, macOS, and Windows platforms. The build system uses PyInstaller to create standalone executables that include all dependencies.

### Build System

- `Makefile` - Professional cross-platform build system
- `surfscape.spec` - PyInstaller specification file
- `requirements.txt` - Python dependencies
- Legacy scripts: `build.sh`, `build.bat`, `clean.sh`, `clean.bat` (deprecated)

### Prerequisites for Building

#### System Dependencies

**Linux/Unix:**
- Python 3.6 or higher
- pip3
- make (usually pre-installed)
- Development packages for audio (for PyAudio)

On Ubuntu/Debian:
```bash
sudo apt-get install python3-dev portaudio19-dev build-essential
```

On CentOS/RHEL/Fedora:
```bash
sudo dnf install python3-devel portaudio-devel make
# or for older versions:
sudo yum install python3-devel portaudio-devel make
```

**macOS:**
- Python 3.6 or higher
- Xcode Command Line Tools
- Homebrew (recommended)

```bash
xcode-select --install
brew install portaudio
```

**Windows:**
- Python 3.6 or higher (from python.org)
- Microsoft Visual C++ Build Tools
- make utility (via Chocolatey, MSYS2, or WSL)
- PortAudio development files (optional, for voice input)

Optional voice input on Windows:
```cmd
git clone https://github.com/microsoft/vcpkg C:\vcpkg
cd C:\vcpkg
.\bootstrap-vcpkg.bat
.\vcpkg.exe install portaudio:x64-windows
setx VCPKG_PATH C:\vcpkg
```

```cmd
# Using Chocolatey
choco install make

# Or use Windows Subsystem for Linux (WSL)
```

### Quick Start

The easiest way to build Surfscape is using the Makefile:

```bash
# See all available commands
make help

# Install system dependencies (Linux only)
make install-system-deps

# Build the executable (installs Python deps automatically)
make build

# Run from source (for development)
make run

# Clean build artifacts
make clean
```

### Available Make Targets

#### Build Targets
- `make build` - Build the executable (default target)
- `make package` - Create distribution package
- `make debug` - Build with debug information

#### Development Targets
- `make deps` - Install Python dependencies
- `make venv` - Create virtual environment
- `make install` - Install in development mode
- `make run` - Run from source
- `make format` - Format code with black

#### Quality Assurance
- `make check` - Run code quality checks (flake8, pylint, black)
- `make test` - Run test suite

#### Maintenance Targets
- `make clean` - Clean build artifacts
- `make clean-all` - Clean everything including virtual environment
- `make info` - Show project information
- `make update-deps` - Update dependencies

#### CI/CD Targets
- `make ci` - Full CI pipeline (deps, check, test, build)
- `make release` - Prepare release package

### Build Output

The executable will be created in the `dist/` directory:
- **Linux/Unix:** `dist/surfscape`
- **macOS:** `dist/surfscape`
- **Windows:** `dist/surfscape.exe`

### Advanced Build Configuration

#### Virtual Environment

The Makefile automatically manages a Python virtual environment in the `venv/` directory. This ensures clean dependency management and doesn't interfere with your system Python installation.

#### Cross-Platform Support

The Makefile automatically detects your platform and adjusts build commands accordingly:
- Uses `python3` on Linux/macOS, falls back to `python` on Windows
- Sets correct executable extensions (`.exe` on Windows)
- Handles different virtual environment activation scripts

#### Customizing the Build

You can customize the build by editing `surfscape.spec`:

```python
# Add custom icon
icon='path/to/icon.ico'  # Windows
icon='path/to/icon.icns'  # macOS

# Exclude modules to reduce size
excludes=['module_to_exclude']

# Add hidden imports
hiddenimports=['your_module']
```

### Cleaning Build Artifacts

To clean build artifacts:

```bash
# Clean build files only
make clean

# Clean everything including virtual environment
make clean-all
```

### Legacy Build Scripts

The project still includes the original build scripts for compatibility:
- `build.sh` (Linux/Unix)
- `build.bat` (Windows)
- `clean.sh` (Linux/Unix)
- `clean.bat` (Windows)

However, it's recommended to use the Makefile for new development as it provides better dependency management and cross-platform support.

### Distribution

The built executable can be distributed as a single file. Users don't need Python or any dependencies installed.

Use `make package` to create a complete distribution package that includes the executable, documentation, and other assets.

#### System Requirements for End Users

- **Linux**: glibc 2.17+ (most modern distributions)
- **Windows**: Windows 7 SP1+ (64-bit)
- **macOS**: macOS 10.9+ (if building on macOS)

## Development Dependencies

If you want to run Surfscape from source code, make sure you have the following dependencies installed:

- [Python 3.6 or above](https://www.python.org/downloads/)
- [PyQt6](https://pypi.org/project/PyQt6/)
- [PyQt6 WebEngine](https://pypi.org/project/PyQt6-WebEngine/)
- [Adblockparser](https://pypi.org/project/adblockparser/)
- [Anthropic](https://pypi.org/project/anthropic/)
- [SpeechRecognition](https://pypi.org/project/SpeechRecognition/) (optional, voice input)
- [PyAudio](https://pypi.org/project/PyAudio/) (optional, voice input; requires PortAudio dev libs)
- [markdown](https://pypi.org/project/markdown/)

You can install these dependencies using `pip`, the Python package installer. Open a terminal or command prompt and run the following command:

```bash
pip install -r requirements.txt
# Optional voice input support
pip install -r requirements-voice.txt
```

Or you can install these dependencies using the package manager of your favorite Linux Distribution.

### Running from Source

After installing dependencies using the Makefile, you can run Surfscape directly:

```bash
# Using the Makefile (recommended)
make run

# Or manually
python3 surfscape.py
```

### Multiprocessing & Adblock Performance

Surfscape now supports a configurable process pool used to accelerate CPU-bound tasks like large Markdown rendering and per-domain adblock rule subset compilation.

Usage examples:
```bash
# Auto-detect CPU count (default when not in safe mode)
python3 surfscape.py

# Explicitly set number of worker processes
python3 surfscape.py --workers 4

# Disable multiprocessing (forces in-process execution)
python3 surfscape.py --workers 1
```

Notes:
- On platforms detected as "safe mode" (typically ARM devices/Raspberry Pi) the pool is forced to a single process to avoid GPU/QtWebEngine issues.
- Adblock lists are downloaded once in a background thread; domain-specific rule subsets are compiled lazily and prefetched as soon as a tab begins loading.
- The first requests on a fresh domain may proceed without blocking until the compiled subset is ready; subsequent requests leverage cached decisions.

## Build Troubleshooting

### Common Build Issues

1. **Make command not found**:
   - **Linux/macOS**: Install build tools with `sudo apt-get install build-essential` or `xcode-select --install`
   - **Windows**: Install make via Chocolatey (`choco install make`) or use WSL

2. **PyAudio installation fails**:
   - **Linux**: Use `make install-system-deps` to install system dependencies
   - **macOS**: Install with `brew install portaudio`
   - **Windows**: Install Visual C++ Build Tools and PortAudio dev files (e.g., via vcpkg), then install `requirements-voice.txt`

3. **Python virtual environment issues**:
   - Run `make clean-all` then `make build` to recreate the environment
   - Ensure Python 3.6+ is installed and accessible

4. **Missing modules in executable**:
   - Add missing modules to `hiddenimports` in `surfscape.spec`
   - Use `make debug` to build with verbose output

5. **Large executable size**:
   - Review dependencies in `requirements.txt`
   - Add unused packages to `excludes` in `surfscape.spec`

6. **Permission denied errors**:
   - Ensure you have write permissions in the project directory
   - On Linux/macOS, the Makefile automatically sets executable permissions

### Development Workflow

For active development, use these commands:

```bash
# Set up development environment
make venv deps

# Run code quality checks
make check

# Format code
make format

# Run tests
make test

# Run from source
make run

# Build when ready
make build
```

### CI/CD Integration

The Makefile includes targets designed for continuous integration:

```bash
# Full CI pipeline
make ci

# Prepare release
make release
```

### Version Control

The project includes a comprehensive `.gitignore` file that excludes:
- Python cache files and bytecode
- Build artifacts and distribution files
- Virtual environments
- IDE configuration files
- OS-specific files
- Temporary files

This ensures that only source code and essential configuration files are tracked in version control.

### Customizing the Build

#### Adding an Icon

To add an icon to the executable:

1. Place your icon file in the project directory
2. Edit `surfscape.spec` and update the `icon` parameter:
   ```python
   # For Windows
   icon='icon.ico'
   
   # For macOS
   icon='icon.icns'
   ```

#### Build Options

The PyInstaller spec file (`surfscape.spec`) can be customized:

- `console=False` - Creates a windowed application (no console)
- `upx=True` - Enables UPX compression (if UPX is installed)
- `onefile=True` - Creates a single executable file
- `debug=False` - Disables debug output

## Tor Setup

To configure Tor to use specific ports and enable cookie authentication, add the following lines to your `torrc` file:

```
ControlPort 9051
SocksPort 9050
CookieAuthentication 1
```

The `torrc` file is typically located in `/etc/tor/` on Linux or in the HOME directory on Windows.

To start Tor via `systemctl` using your Linux Distribution of choice, run the following command:

```bash
sudo systemctl start tor
```

To enable Tor to start at boot, use:

```bash
sudo systemctl enable tor
```

Alternatively, on Windows, you can configure Tor to start at boot by creating a shortcut to `tor.exe` in the Startup folder. Follow these steps:

1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Create a shortcut to `tor.exe` in the Startup folder.

This will ensure Tor starts automatically when you log in to your Windows account.

After these steps you can enable or disable Tor via Surfscape Browser Settings.

## I2P Setup

### Linux

1. **Install I2P:**
    You can install I2P using your distribution's package manager. For example, on Debian-based systems, run:
    ```bash
    sudo apt update
    sudo apt install i2p
    ```

2. **Start I2P:**
    To start I2P, use the following command:
    ```bash
    i2prouter start
    ```

3. **Enable I2P to start at boot:**
    To ensure I2P starts automatically at boot, use:
    ```bash
    sudo systemctl enable i2p
    ```

4. **Configure I2P:**
    Open your web browser and navigate to `http://127.0.0.1:7657` to access the I2P router console. Configure your I2P settings as needed.

### Windows

1. **Download I2P:**
    Download the I2P installer from the [official I2P website](https://geti2p.net/en/download).

2. **Install I2P:**
    Run the installer and follow the on-screen instructions to install I2P.

3. **Start I2P:**
    After installation, start I2P from the Start Menu or by running `i2prouter` from the command prompt.

4. **Configure I2P:**
    Open your web browser and navigate to `http://127.0.0.1:7657` to access the I2P router console. Configure your I2P settings as needed.

5. **Enable I2P to start at boot:**
    To configure I2P to start at boot, create a shortcut to `i2prouter.exe` in the Startup folder. Follow these steps:
    1. Press `Win + R`, type `shell:startup`, and press Enter.
    2. Create a shortcut to `i2prouter.exe` in the Startup folder.

After these steps, you can enable or disable I2P via Surfscape Browser Settings.

## Contributing

If you would like to contribute, please follow these steps:

1. **Fork the repository** on GitHub.
2. **Clone your forked repository** to your local machine.
3. **Create a new branch** for your feature or bugfix:
    ```bash
    git checkout -b feature-name
    ```
4. **Make your changes** and commit them with clear and descriptive messages.
5. **Push your changes** to your forked repository:
    ```bash
    git push origin feature-name
    ```
6. **Create a pull request** on GitHub, describing your changes and the problem they solve.

Please ensure your code adheres to our coding standards and includes appropriate tests. We will review your pull request and provide feedback.

Thank you for contributing to Surfscape!

## License
This library is free software; you can redistribute it and/or modify it under
the terms of the GNU General Public License, version 3. See [LICENSE](LICENSE) for details.

## Author
Surfscace is developed and maintained by André Machado. <br />You can contact him at sedzcat@gmail.com.
