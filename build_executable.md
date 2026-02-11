# Building the Desktop Application

This guide explains how to package the AI Video Processing Suite as a standalone executable for Windows and macOS.

---

## Using the Application

There are two ways to use this application depending on what you have:

### Option 1: Executable Only (Recommended for End Users)

If you received only the `AI Video Suite.app` (macOS) or `AI Video Suite.exe` (Windows):

**What you have:**

- The standalone application bundle
- No Python or source code required

**Setup:**

1. **Install FFmpeg** (required for video processing):
   - **macOS**: `brew install ffmpeg`
   - **Windows**: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH

2. **Create a working folder** with your media files:

   ```bash
   MyProject/
   ├── config/
   │   └── my_config.yaml      # Your configuration file
   └── Media Files/
       └── TaskFolder/
           ├── Source/          # Input images/videos
           └── Generated_Video/ # Outputs (auto-created)
   ```

3. **Launch the app** and use the GUI:
   - Select your platform (Kling, Nano Banana, etc.)
   - Click "Browse" to select your config file
   - Use **absolute paths** in your config file, or launch from your project folder:

     ```bash
     cd /path/to/MyProject && open /path/to/AI\ Video\ Suite.app
     ```

**Limitations:**

- Must use absolute paths in config files (relative paths resolve from app's working directory)
- No command-line interface
- Cannot modify core processing logic

---

### Option 2: Full Source Code (Recommended for Developers)

If you have the complete `GAI/` project folder:

**What you have:**

- Complete source code
- Configuration files and templates
- Command-line tools and GUI

**Setup:**

1. **Install Python 3.8+** and create environment:

   ```bash
   cd /path/to/GAI
   conda create -n myenv python=3.11
   conda activate myenv
   pip install -r Scripts/requirements.txt
   ```

2. **Install FFmpeg**:
   - **macOS**: `brew install ffmpeg`
   - **Windows**: Download and add to PATH

3. **Run via command line or GUI**:

   ```bash
   cd Scripts
   
   # Command line
   python core/runall.py kling auto
   python core/runall.py nano process --config config/my_config.yaml
   
   # GUI
   python gui_app.py
   ```

   Note: The working directory automatically defaults to the GAI project root,
   so relative paths like `Media Files/...` in configs resolve correctly
   regardless of where you invoke the script from.

**Advantages:**

- Use relative paths in config files (e.g., `Media Files/...`)
- Full command-line interface with all options
- Can modify handlers, add new APIs, customize reports
- Can build your own executable for distribution

---

### Quick Reference: Config Path Differences

| Scenario | Config Path Style | Example |
| ---------- | ------------------- | -------- |
| **Full source** (run from GAI/) | Relative | `folder: Media Files/Kling/Task1` |
| **Executable only** | Absolute | `folder: /Users/me/Projects/Media Files/Kling/Task1` |
| **Executable** (launched from project dir) | Relative | Works if you `cd` to project folder first |

---

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

### Common Build Options

All builds use these shared options:

| Option | Purpose |
| ---------- | --------- |
| `--add-data "config:config"` | Bundle config files |
| `--add-data "templates:templates"` | Bundle template files |
| `--add-data "core:core"` | Bundle core modules |
| `--add-data "handlers:handlers"` | Bundle API handlers |
| `--hidden-import ...` | PIL, yaml, gradio_client, cv2, pillow_heif, wakepy, pptx, ruamel.yaml |
| `--collect-data gradio_client` | Include gradio_client data files |

> **Note**: macOS uses `:` as path separator, Windows uses `;`

---

### macOS Build

> **Note**: macOS app bundles require `--onedir` mode. The `--onefile` option is deprecated for windowed macOS apps.

```bash
cd Scripts
rm -rf build dist && pyinstaller --name "AI Video Suite" --onedir --windowed --add-data "config:config" --add-data "templates:templates" --add-data "core:core" --add-data "handlers:handlers" --hidden-import PIL --hidden-import PIL.Image --hidden-import yaml --hidden-import gradio_client --hidden-import cv2 --hidden-import pillow_heif --hidden-import wakepy --hidden-import pptx --hidden-import ruamel.yaml --collect-data gradio_client gui_app.py

# Optional flags:
#   --icon path/to/icon.icns                           # Custom icon
#   --osx-bundle-identifier com.company.aivideosuite   # For distribution
```

**Output:** `Scripts/dist/AI Video Suite.app`

**Quick build with conda** (without activating environment):

```bash
conda run -n myenv pyinstaller [options above] gui_app.py
```

---

### Windows Build

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
    --hidden-import ruamel.yaml `
    --collect-data gradio_client `
    gui_app.py

# Optional flags:
#   --icon path\to\icon.ico   # Custom icon
#   --onedir                  # Faster startup (use instead of --onefile)
```

**Output:** `Scripts\dist\AI Video Suite.exe`

## Step 3: Verify the Build

1. Run the application:
   - **macOS**: `open "dist/AI Video Suite.app"` or double-click
   - **Windows**: Double-click `dist\AI Video Suite.exe`
2. Verify all platforms appear in the dropdown
3. Expand "Advanced Options" and check API-specific fields
4. Test with a simple job (e.g., Report Only with absolute paths)

**Debug from terminal** (to see errors):

```bash
# macOS
./dist/AI\ Video\ Suite.app/Contents/MacOS/AI\ Video\ Suite

# Windows
.\dist\AI Video Suite.exe
```

## File Structure After Build

```bash
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

| Issue | Solution |
| ---------- | ----------- |
| Module not found | Add `--hidden-import missing_module` to build command |
| tkinter not found (Linux) | `sudo apt-get install python3-tk` |
| Config/template not found | Check `--add-data` separator (`:` for macOS, `;` for Windows) |
| FFmpeg not working | Install system-wide: `brew install ffmpeg` (macOS) or add to PATH (Windows) |
| PIL/Pillow errors | `pip install pillow --force-reinstall` |
| gradio_client errors | Check network/firewall; bundled app needs internet access |
| "No valid pairs" | Use absolute paths in config, or `cd` to project dir before launching |
| Scroll not working (macOS) | Rebuild the app (fixed in recent builds) |

### Debug Build

For troubleshooting, create a console build to see stdout/stderr:

```bash
pyinstaller --onefile --console gui_app.py
```

### Custom Spec File

For complex builds:

```bash
pyi-makespec --windowed --onefile gui_app.py
# Edit gui_app.spec, then:
pyinstaller gui_app.spec
```

## Notes

### FFmpeg

FFmpeg is **not bundled** - users must install separately:

- **macOS**: `brew install ffmpeg`
- **Windows**: Download from ffmpeg.org and add to PATH

### Working Directory

When running as a bundled app:

- Working directory defaults to user's home folder
- Relative config paths resolve from current working directory
- **Best practice:** Use absolute paths, or launch from project dir:

  ```bash
  cd /path/to/project && open AI\ Video\ Suite.app
  ```

### Updating the App

```bash
rm -rf build/ dist/
# Re-run PyInstaller command
```

### Icon Files

- **macOS**: `icon.icns` (use `iconutil` or online converters)
- **Windows**: `icon.ico` (use ImageMagick or online converters)

---

## Creating a GitHub Release

Pushing an annotated tag triggers GitHub Actions to automatically build macOS and Windows executables and create a GitHub Release with the tag message as release notes.

### Step 1: Commit and Push All Changes

```bash
git add -A
git commit -m "Description of changes"
git push origin main
```

### Step 2: Create an Annotated Tag

Use an annotated tag (`-a`) so the message becomes the release notes. The first line is the tag subject; subsequent lines become the release body.

```bash
git tag -a v1.0.5 -m "Release v1.0.5

Summary of changes

- **New:** Feature description
- **Fix:** Bug fix description
- **Improve:** Improvement description
- **Update:** Config or doc update description"
```

### Step 3: Push the Tag

```bash
git push origin v1.0.5
```

This triggers the `build-release.yml` workflow which will:

1. Build the macOS `.app` bundle and zip it
2. Build the Windows `.exe`
3. Create a GitHub Release titled `Release v1.0.5` with the tag message as notes
4. Attach both binaries as release assets

### Verify

- Check the **Actions** tab on GitHub to monitor build progress
- Once complete, the release appears under **Releases** with both assets attached

### Quick Reference

| Action | Command |
| ------ | ------- |
| Create tag | `git tag -a v1.0.X -m "Release v1.0.X..."` |
| Push tag | `git push origin v1.0.X` |
| List tags | `git tag -l` |
| View tag message | `git tag -l --format='%(contents)' v1.0.X` |
| Delete local tag | `git tag -d v1.0.X` |
| Delete remote tag | `git push origin :refs/tags/v1.0.X` |
