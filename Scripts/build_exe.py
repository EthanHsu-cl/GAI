"""
Build script for creating GAI Scripts executable.

This script uses PyInstaller to package the GUI launcher and all dependencies
into a standalone executable for distribution.

Usage:
    python build_exe.py

The output will be placed in the 'dist' folder.
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path

# Configuration
APP_NAME = "GAI_Launcher"
SCRIPT_DIR = Path(__file__).parent
MAIN_SCRIPT = SCRIPT_DIR / "gui_launcher.py"
CORE_DIR = SCRIPT_DIR / "core"
CONFIG_DIR = SCRIPT_DIR / "config"
HANDLERS_DIR = SCRIPT_DIR / "handlers"
TEMPLATES_DIR = SCRIPT_DIR / "templates"

# PyInstaller options
PYINSTALLER_OPTIONS = [
    "--name", APP_NAME,
    "--onefile",  # Single executable file
    "--windowed",  # No console window (for GUI app)
    "--noconfirm",  # Replace output without asking
    
    # Add data folders
    f"--add-data={CORE_DIR}{os.pathsep}core",
    f"--add-data={CONFIG_DIR}{os.pathsep}config",
    f"--add-data={HANDLERS_DIR}{os.pathsep}handlers",
    f"--add-data={TEMPLATES_DIR}{os.pathsep}templates",
    
    # Hidden imports that PyInstaller might miss
    "--hidden-import=yaml",
    "--hidden-import=PIL",
    "--hidden-import=PIL.Image",
    "--hidden-import=requests",
    "--hidden-import=tqdm",
    "--hidden-import=cv2",
    "--hidden-import=pptx",
    "--hidden-import=pillow_heif",
    "--hidden-import=wakepy",
    "--hidden-import=gradio_client",
    
    # Collect all submodules
    "--collect-submodules=handlers",
    "--collect-submodules=PIL",
    "--collect-submodules=pptx",
]


def check_pyinstaller() -> bool:
    """
    Check if PyInstaller is installed.

    Returns:
        True if PyInstaller is available, False otherwise.
    """
    try:
        import PyInstaller
        print(f"✅ PyInstaller version: {PyInstaller.__version__}")
        return True
    except ImportError:
        return False


def install_pyinstaller() -> bool:
    """
    Install PyInstaller using pip.

    Returns:
        True if installation succeeded, False otherwise.
    """
    print("📦 Installing PyInstaller...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        return True
    except subprocess.CalledProcessError:
        return False


def build_executable() -> bool:
    """
    Build the executable using PyInstaller.

    Returns:
        True if build succeeded, False otherwise.
    """
    print(f"\n🔨 Building {APP_NAME}...")
    print(f"   Main script: {MAIN_SCRIPT}")
    print(f"   Output: {SCRIPT_DIR / 'dist' / APP_NAME}")

    # Build command
    cmd = [sys.executable, "-m", "PyInstaller"] + PYINSTALLER_OPTIONS + [str(MAIN_SCRIPT)]

    print(f"\n📋 Running: {' '.join(cmd[:5])}...")

    try:
        # Run PyInstaller
        result = subprocess.run(
            cmd,
            cwd=str(SCRIPT_DIR),
            capture_output=False,
            text=True
        )

        if result.returncode == 0:
            print(f"\n✅ Build successful!")
            return True
        else:
            print(f"\n❌ Build failed with return code: {result.returncode}")
            return False

    except Exception as e:
        print(f"\n❌ Build error: {e}")
        return False


def create_distribution_package() -> None:
    """Create a distribution package with the executable and necessary files."""
    dist_dir = SCRIPT_DIR / "dist"
    release_dir = dist_dir / f"{APP_NAME}_Release"

    print(f"\n📦 Creating distribution package at {release_dir}...")

    # Create release directory
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True)

    # Determine executable name based on platform
    if sys.platform == "win32":
        exe_name = f"{APP_NAME}.exe"
    elif sys.platform == "darwin":
        exe_name = APP_NAME
    else:
        exe_name = APP_NAME

    # Copy executable
    exe_source = dist_dir / exe_name
    if exe_source.exists():
        shutil.copy2(exe_source, release_dir / exe_name)
        print(f"   ✅ Copied executable")

    # Copy config folder (users might want to modify configs)
    config_dest = release_dir / "config"
    if CONFIG_DIR.exists():
        shutil.copytree(CONFIG_DIR, config_dest, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
        print(f"   ✅ Copied config folder")

    # Copy templates folder
    templates_dest = release_dir / "templates"
    if TEMPLATES_DIR.exists():
        shutil.copytree(TEMPLATES_DIR, templates_dest, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
        print(f"   ✅ Copied templates folder")

    # Create a simple README for the release
    readme_content = f"""# {APP_NAME}

## Quick Start

1. Double-click `{exe_name}` to launch the application
2. Select a platform from the dropdown menu
3. Choose an action (Auto, Process, or Report)
4. Optionally select a custom config file
5. Click "Run" to start processing

## Folder Structure

- `{exe_name}` - The main application
- `config/` - Configuration files for each platform
- `templates/` - PowerPoint templates for report generation

## Configuration

You can modify the YAML files in the `config/` folder to customize:
- Input/output directories
- API endpoints
- Processing parameters
- Report settings

## Requirements

- Ensure your media files are accessible at the paths specified in config files
- Network access is required for API calls

## Troubleshooting

If the application doesn't start:
1. Try running from command line to see error messages
2. Ensure all config paths are valid
3. Check that required media folders exist
"""

    readme_path = release_dir / "README.md"
    readme_path.write_text(readme_content)
    print(f"   ✅ Created README.md")

    print(f"\n✅ Distribution package created at: {release_dir}")


def main() -> None:
    """Main entry point for the build script."""
    print("=" * 60)
    print(f"  GAI Scripts - Executable Builder")
    print("=" * 60)

    # Check Python version
    print(f"\n🐍 Python version: {sys.version}")

    # Check/install PyInstaller
    if not check_pyinstaller():
        print("⚠️ PyInstaller not found.")
        if not install_pyinstaller():
            print("❌ Failed to install PyInstaller. Please install manually:")
            print("   pip install pyinstaller")
            sys.exit(1)

    # Build executable
    if not build_executable():
        print("\n❌ Build failed. Check the errors above.")
        sys.exit(1)

    # Create distribution package
    create_distribution_package()

    print("\n" + "=" * 60)
    print("  Build Complete!")
    print("=" * 60)
    print(f"\nTo distribute:")
    print(f"  1. Zip the 'dist/{APP_NAME}_Release' folder")
    print(f"  2. Upload to GitHub Releases")
    print(f"\nFor GitHub Release:")
    print(f"  - Go to your repo > Releases > Create new release")
    print(f"  - Upload the zip file as a release asset")


if __name__ == "__main__":
    main()
