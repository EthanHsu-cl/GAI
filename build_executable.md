# Building the Desktop Application

This guide explains how to package the AI Video Processing Suite as a standalone executable for Windows and macOS.

## Prerequisites

- Python 3.8 or higher
- pip or conda package manager
- FFmpeg installed system-wide

## Step 1: Set Up Python Environment

### Option A: Using Conda (Recommended)

```bash
# Navigate to the project root
cd /path/to/GAI

# Create conda environment (if not already created)
conda create -n myenv python=3.11

# Activate
conda activate myenv

# Install dependencies
pip install -r Scripts/requirements.txt
pip install pyinstaller
```

### Option B: Using venv (macOS / Linux)

```bash
# Navigate to the project root
cd /path/to/GAI

# Create virtual environment
python3 -m venv venv

# Activate
source venv/bin/activate

# Install dependencies
pip install -r Scripts/requirements.txt
pip install pyinstaller
```

### Option C: Using venv (Windows)

```powershell
# Navigate to the project root
cd C:\path\to\GAI

# Create virtual environment
python -m venv venv

# Activate
.\venv\Scripts\activate

# Install dependencies
pip install -r Scripts\requirements.txt
pip install pyinstaller
```

## Step 2: Build the Executable

### Quick Build (macOS with Conda)

For a quick build using conda without activating the environment:

```bash
cd Scripts
rm -rf build dist
conda run -n myenv pyinstaller \
    --name "AI Video Suite" \
    --onedir \
    --windowed \
    --add-data "config:config" \
    --add-data "templates:templates" \
    --add-data "core:core" \
    --add-data "handlers:handlers" \
    --hidden-import PIL \
    --hidden-import PIL.Image \
    --hidden-import yaml \
    --hidden-import gradio_client \
    --hidden-import cv2 \
    --hidden-import pillow_heif \
    --hidden-import wakepy \
    --hidden-import pptx \
    --collect-data gradio_client \
    gui_app.py
```

### macOS - App Bundle (Recommended)

> **Note**: macOS app bundles require `--onedir` mode. The `--onefile` option is
> deprecated for windowed macOS apps and will become an error in PyInstaller v7.0.

```bash
cd Scripts

pyinstaller \
    --name "AI Video Suite" \
    --onedir \
    --windowed \
    --add-data "config:config" \
    --add-data "templates:templates" \
    --add-data "core:core" \
    --add-data "handlers:handlers" \
    --hidden-import PIL \
    --hidden-import PIL.Image \
    --hidden-import yaml \
    --hidden-import gradio_client \
    --hidden-import cv2 \
    --hidden-import pillow_heif \
    --hidden-import wakepy \
    --hidden-import pptx \
    --collect-data gradio_client \
    gui_app.py

# OpQuick Build (macOS with Conda)

For a quick build using conda without activating the environment:

```bash
cd Scripts
rm -rf build dist
conda run -n myenv pyinstaller \
    --name "AI Video Suite" \
    --onedir \
    --windowed \
    --add-data "config:config" \
    --add-data "templates:templates" \
    --add-data "core:core" \
    --add-data "handlers:handlers" \
    --hidden-import PIL \
    --hidden-import PIL.Image \
    --hidden-import yaml \
    --hidden-import gradio_client \
    --hidden-import cv2 \
    --hidden-import pillow_heif \
    --hidden-import wakepy \
    --hidden-import pptx \
    --collect-data gradio_client \
    gui_app.py
```

### macOS - App Bundle (Recommended)

> **Note**: macOS app bundles require `--onedir` mode. The `--onefile` option is
> deprecated for windowed macOS apps and will become an error in PyInstaller v7.0.

```bash
cd Scripts

pyinstaller \
    --name "AI Video Suite" \
    --onedir \
    --windowed \
    --add-data "config:config" \
    --add-data "templates:templates" \
    --add-data "core:core" \
    --add-data "handlers:handlers" \
    --hidden-import PIL \
    --hidden-import PIL.Image \
    --hidden-import yaml \
    --hidden-import gradio_client \
    --hidden-import cv2 \
    --hidden-import pillow_heif \
    --hidden-import wakepy \
    --hidden-import pptx \
    --collect-data gradio_client \
    gui_app.py

# Optional: Add a custom icon if you have one:
#   --icon path/to/your/icon.icns
```

The app bundle will be created in `Scripts/dist/AI Video Suite.app`.

### macOS - With Bundle Identifier (for Distribution)

For distributing outside your organization, add a bundle identifier:

```bash
cd Scripts

pyinstaller \
    --name "AI Video Suite" \
    --onedir \
    --windowed \
    --add-data "config:config" \
    --add-data "templates:templates" \
    --add-data "core:core" \
    --add-data "handlers:handlers" \
    --hidden-import PIL \
    --hidden-import PIL.Image \
    --hidden-import yaml \
    --hidden-import gradio_client \
    --hidden-import cv2 \
    --hidden-import pillow_heif \
    --hidden-import wakepy \
    --hidden-import pptx \
    --collect-data gradio_client \
    --osx-bundle-identifier com.company.aivideosuite \
    gui_app.py
```

### Windows - Single Executable

```powershell
cd Scripts

pyinstaller `
    --name "AI Video Suite" `
    --onefile `
    --windowed `
    --add-data "config;config" `
    --add-data "templates;templates" `
    --add-data "core;core" `
    --add-data "handlers;handlers" `
    --hidden-import PIL `
    --hidden-import PIL.Image `
    --hidden-import yaml `
    --hidden-import gradio_client `
    --hidden-import cv2 `
    --hidden-import pillow_heif `
    --hidden-import wakepy `
    --hidden-import pptx `
    --collect-data gradio_client `
    gui_app.py

# Optional: Add a custom icon if you have one:
#   --icon path\to\your\icon.ico
```

The executable will be created at `Scripts\dist\AI Video Suite.exe`.

### Windows - Directory Bundle (Faster Startup)

```powershell
cd Scripts

pyinstaller `
    --name "AI Video Suite" `
    --onedir `
    --windowed `
    --add-data "config;config" `
    --add-data "templates;templates" `
    --add-data "core;core" `
    --add-data "handlers;handlers" `
    --hidden-import PIL `
    --hidden-import PIL.Image `
    --hidden-import yaml `
    --hidden-import gradio_client `
    --hidden-import cv2 `
    --hidden-import pillow_heif `
    --hidden-import wakepy `
    --hidden-import pptx `
    --collect-data gradio_client `
    gui_app.py
```

## Step 3: Verify the Build

1. Navigate to `Scripts/dist/`
2. Run the application:
   - **macOS**: Double-click `AI Video Suite.app` or run `open "AI Video Suite.app"`
   - **Windows**: Double-click `AI Video Suite.exe`
3. Verify all platforms appear in the dropdown
4. Test with a simple job (e.g., Report Only on an existing folder)

## File Structure After Build

```
Scripts/
├── dist/
│   ├── AI Video Suite.app/    # macOS app bundle (or .exe for Windows)
│   └── AI Video Suite/        # Directory bundle (if using --onedir)
├── build/                      # Build artifacts (can be deleted)
└── AI Video Suite.spec         # PyInstaller spec file
```

## Distribution

### macOS

For distribution to other macOS users:

1. **Notarization (Recommended)**: Apple requires notarization for apps distributed outside the App Store
   ```bash
   # Create a zip for notarization
   ditto -c -k --keepParent "dist/AI Video Suite.app" "AI Video Suite.zip"
   
   # Submit for notarization (requires Apple Developer account)
   xcrun notarytool submit "AI Video Suite.zip" --apple-id YOUR_APPLE_ID --team-id YOUR_TEAM_ID --password YOUR_APP_PASSWORD
   ```

2. **Ad-hoc distribution**: Users may need to right-click → Open for first launch

### Windows

1. The `.exe` file can be distributed directly
2. Consider creating an installer using NSIS or Inno Setup for a professional experience
3. Windows SmartScreen may show a warning on first run - users click "More info" → "Run anyway"

## Troubleshooting

### Common Issues

#### 1. "Module not found" errors

Add the missing module to `--hidden-import`:
```bash
pyinstaller ... --hidden-import missing_module
```

#### 2. tkinter not found (Linux only)

Install tkinter separately:
```bash
# Ubuntu/Debian
sudo apt-get install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

#### 3. Application crashes on startup

Run from terminal to see error messages:
```bash
# macOS
./dist/AI\ Video\ Suite.app/Contents/MacOS/AI\ Video\ Suite

# Windows
.\dist\AI Video Suite.exe
```

#### 4. Config/template files not found

Ensure `--add-data` paths are correct:
- macOS/Linux: Use `:` as separator (`source:dest`)
- Windows: Use `;` as separator (`source;dest`)

#### 5. FFmpeg not working

FFmpeg must be installed system-wide - it is **not bundled** with the app.

**macOS**:
```bash
brew install ffmpeg
```

**Windows**:
1. Download from https://ffmpeg.org/download.html
2. Add to System PATH

#### 6. PIL/Pillow import errors

```bash
pip uninstall pillow
pip install pillow --force-reinstall
```

#### 7. gradio_client connection errors

Ensure the bundled app has network access. Firewall/antivirus may block it.

### Creating a PyInstaller Spec File

For complex builds, generate and customize a spec file:

```bash
pyi-makespec --windowed --onefile gui_app.py
```

Then edit `gui_app.spec` and build with:
```bash
pyinstaller gui_app.spec
```

### Debug Build

For troubleshooting, create a console build:
```bash
pyinstaller --onefile --console gui_app.py
```

This shows stdout/stderr in a terminal window.

## Notes on Dependencies

### FFmpeg

FFmpeg is required for video processing but is **not bundled** with the application. Users must install FFmpeg separately:

- **macOS**: `brew install ffmpeg`
- **Windows**: Download from ffmpeg.org and add to PATH
- **Linux**: `sudo apt install ffmpeg` or equivalent

### API Server

The application connects to external API servers (configured in YAML files). Ensure:
1. Network connectivity is available
2. API server URLs in config files are correct
3. Any VPN or proxy settings are configured

## Updating the Application

When updating the source code:

1. Delete the `build/` and `dist/` directories
2. Re-run the PyInstaller command
3. Test the new build before distribution

## Icon Files

Create icon files for professional appearance:

- **macOS**: `icon.icns` (use `iconutil` or online converters)
- **Windows**: `icon.ico` (use ImageMagick or online converters)

Place in `assets/` directory at project root.
