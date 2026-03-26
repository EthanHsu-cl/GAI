import os
import time
import shutil
import json
import yaml
import requests
import base64
import subprocess
import platform
import atexit
import signal
from datetime import datetime
from gradio_client import Client, handle_file
from PIL import Image
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import logging
import sys

from config_loader import get_app_base_path, get_resource_path, get_core_path, get_testbed_cookie

# Register HEIC/HEIF format support for Pillow
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

try:
    from wakepy import keep
    WAKEPY_AVAILABLE = True
except ImportError:
    WAKEPY_AVAILABLE = False

# Detect platform for sleep prevention
IS_MACOS = platform.system() == 'Darwin'

# Add parent directory to path for handler imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from handlers import HandlerRegistry

"""
file download command example:
yt-dlp -f "bv*[vcodec~='^(h264|avc)']+ba[acodec~='^(mp?4a|aac)']" "https://youtube.com/playlist?list=PLSgBrV2b0XA_ofBZ4c3e85sTNBh3BKN2y&si=_5VpzvdI7hsF-a4o"
"""


class ValidationError(Exception):
    """Exception raised when file validation fails.
    
    This exception signals that invalid files were found during validation.
    When caught, processing should stop and report generation should be skipped.
    """
    pass


class UnifiedAPIProcessor:
    """
    Enhanced Consolidated API processor supporting multiple endpoints with all individual processor features:
    - Kling Image2Video (with streaming downloads and dual-save logic)
    - Google Flash/Nano Banana (with base64 handling and parallel validation)
    - Vidu Effects (with parallel validation and optimizations)
    - Vidu Reference (with smart reference finding and aspect ratio detection)
    - Runway Video Processing (with video validation and pairing strategies)
    """

    def __init__(self, api_name, config_file=None):
        self.api_name = api_name
        # Support both .yaml and .json extensions
        if config_file:
            self.config_file = config_file
        else:
            # Try YAML first, then JSON (check in config directory)
            script_dir = Path(__file__).parent
            config_dir = script_dir.parent / "config"
            yaml_file = config_dir / f"batch_{api_name}_config.yaml"
            json_file = config_dir / f"batch_{api_name}_config.json"
            
            if yaml_file.exists():
                self.config_file = str(yaml_file)
            elif json_file.exists():
                self.config_file = str(json_file)
            else:
                # Fallback to relative path for backward compatibility
                self.config_file = f"batch_{api_name}_config.json"
        self.client = None
        self.config = {}
        self.api_definitions = {}
        self._caffeinate_process = None
        self._original_sigint = None
        self._original_sigterm = None
        self._testbed_cookie = get_testbed_cookie()

        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(message)s')
        self.logger = logging.getLogger(__name__)

        # Load API definitions
        self.load_api_definitions()
        
        # Cache file extensions after loading API definitions
        self._cache_file_extensions()
    
    def _cache_file_extensions(self):
        """Cache file extension lists for performance."""
        file_types = self.api_definitions.get('file_types', [])
        if isinstance(file_types, dict):
            self._image_exts = file_types.get('image', ['.jpg', '.jpeg', '.png'])
            self._video_exts = file_types.get('video', ['.mp4', '.mov', '.avi'])
        else:
            self._image_exts = file_types if file_types else ['.jpg', '.jpeg', '.png']
            self._video_exts = ['.mp4', '.mov', '.avi']
        
        # All image extensions including unsupported formats
        self._all_image_exts = self._image_exts + ['.avif', '.webp', '.heic', '.heif', '.bmp', '.tiff', '.tif']
        self._ref_image_exts = ['.jpg', '.jpeg', '.png', '.bmp']

    def load_api_definitions(self):
        """Load API-specific configurations from JSON file."""
        # Use the path helper to find api_definitions.json
        api_def_path = get_core_path("api_definitions.json")
        
        # Also try relative path as fallback
        if not api_def_path.exists():
            script_dir = Path(__file__).parent
            api_def_path = script_dir / "api_definitions.json"
        
        try:
            with open(api_def_path, 'r', encoding='utf-8') as f:
                all_definitions = json.load(f)
                self.api_definitions = all_definitions.get(self.api_name, {})
                if not self.api_definitions:
                    self.logger.warning(f"⚠️ No API definition found for '{self.api_name}'")
                else:
                    self.logger.info(f"✓ API definitions loaded from: {api_def_path}")
        except FileNotFoundError:
            self.logger.error(f"❌ API definitions file not found at: {api_def_path}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ Invalid JSON in api_definitions.json: {e}")
            raise

    def load_config(self):
        """Load and validate configuration from YAML or JSON"""
        # Skip loading if config was already set programmatically
        if self.config:
            self.logger.info("✓ Using pre-set configuration (runtime overrides applied)")
            return True
        
        config_path = Path(self.config_file)
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                # Detect format by extension
                if config_path.suffix.lower() in ['.yaml', '.yml']:
                    self.config = yaml.safe_load(f)
                    self.logger.info(f"✓ Configuration loaded from {self.config_file} (YAML)")
                else:
                    self.config = json.load(f)
                    self.logger.info(f"✓ Configuration loaded from {self.config_file} (JSON)")
                return True
        except FileNotFoundError:
            self.logger.error(f"❌ Config file not found: {self.config_file}")
            return False
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            self.logger.error(f"❌ Config parse error: {e}")
            return False

    def set_config(self, config: dict) -> None:
        """
        Set configuration directly, bypassing file loading.
        
        This method allows the GUI and programmatic callers to inject
        a pre-merged configuration dictionary (with runtime overrides applied)
        without reading from a file.
        
        Args:
            config: Configuration dictionary to use for processing.
        """
        self.config = config
        self.logger.debug("Configuration set programmatically")

    def _get_video_info(self, video_path):
        """Get video information using ffprobe (from runway processor)"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', str(video_path)
            ], capture_output=True, text=True)

            if result.returncode != 0:
                return None

            info = json.loads(result.stdout)
            video_stream = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)

            if video_stream:
                return {
                    'width': int(video_stream.get('width', 0)),
                    'height': int(video_stream.get('height', 0)),
                    'duration': float(info['format'].get('duration', 0)),
                    'size_mb': float(info['format'].get('size', 0)) / (1024 * 1024)
                }
            return None
        except Exception:
            return None

    def _resize_oversized_image(self, image_path, max_dimension=4000, max_attempts=3):
        """
        Resize images that exceed the maximum dimension limit.
        Verifies resize succeeded and retries if needed.
        
        Args:
            image_path: Path object to the image file
            max_dimension: Maximum allowed dimension (width or height)
            max_attempts: Maximum number of resize attempts
            
        Returns:
            Path object to the resized file (or original if no resize needed)
        """
        for attempt in range(max_attempts):
            try:
                with Image.open(image_path) as img:
                    w, h = img.size
                    
                    # Check if resize is needed
                    if w <= max_dimension and h <= max_dimension:
                        return image_path
                    
                    # Calculate new dimensions maintaining aspect ratio
                    # Use slightly smaller target to ensure we're under the limit
                    target_dim = max_dimension - 10 if attempt > 0 else max_dimension
                    
                    if w > h:
                        new_w = target_dim
                        new_h = int(h * (target_dim / w))
                    else:
                        new_h = target_dim
                        new_w = int(w * (target_dim / h))
                    
                    # Resize using high-quality resampling
                    resized_img = img.resize((new_w, new_h), Image.LANCZOS)
                    
                    # Convert to RGB if necessary (for JPG compatibility)
                    if resized_img.mode in ('RGBA', 'P'):
                        resized_img = resized_img.convert('RGB')
                    
                    # Save back to same path (overwrite)
                    if image_path.suffix.lower() in ['.jpg', '.jpeg']:
                        resized_img.save(image_path, 'JPEG', quality=95, optimize=True)
                    elif image_path.suffix.lower() == '.png':
                        resized_img.save(image_path, 'PNG', optimize=True)
                    else:
                        # Default to JPEG
                        new_path = image_path.with_suffix('.jpg')
                        resized_img.save(new_path, 'JPEG', quality=95, optimize=True)
                        image_path.unlink()
                        image_path = new_path
                    
                    self.logger.info(f" 📐 Resized {w}x{h} → {new_w}x{new_h}: {image_path.name}")
                
                # Verify the resize worked
                with Image.open(image_path) as verify_img:
                    vw, vh = verify_img.size
                    if vw <= max_dimension and vh <= max_dimension:
                        return image_path
                    else:
                        self.logger.warning(f" ⚠️ Resize verification failed ({vw}x{vh}), retrying...")
                        
            except Exception as e:
                self.logger.warning(f" ⚠️ Could not resize {image_path.name} (attempt {attempt + 1}): {e}")
        
        # Return path after all attempts (may still be oversized if all attempts failed)
        return image_path

    def _convert_image_to_jpg(self, image_path):
        """
        Convert unsupported image formats to JPG.
        
        Detects format by actual image data, not just extension. This catches
        MPO files that have .jpg extension but are actually multi-picture format.
        Preserves EXIF orientation by applying it before saving.
        
        Args:
            image_path: Path object to the image file
            
        Returns:
            Path object to the converted file (or original if no conversion needed)
        """
        try:
            with Image.open(image_path) as img:
                # Check actual image format (not just extension)
                # MPO files often have .jpg extension but need conversion
                unsupported_formats = {'AVIF', 'WEBP', 'HEIC', 'HEIF', 'BMP', 'TIFF', 'MPO', 'SVG'}
                unsupported_extensions = {'.avif', '.webp', '.heic', '.heif', '.bmp', '.tiff', '.tif', '.svg'}
                
                # Skip conversion if already valid JPEG format
                if img.format == 'JPEG' and image_path.suffix.lower() in {'.jpg', '.jpeg'}:
                    return image_path
                
                needs_conversion = (
                    img.format in unsupported_formats or 
                    image_path.suffix.lower() in unsupported_extensions
                )
                
                if needs_conversion:
                    # Store original format for logging
                    original_format = img.format or image_path.suffix.upper()
                    
                    # For files already named .jpg/.jpeg, save in place (overwrite)
                    # For other extensions, create new .jpg file
                    if image_path.suffix.lower() in {'.jpg', '.jpeg'}:
                        new_path = image_path  # Overwrite in place
                    else:
                        new_path = image_path.with_suffix('.jpg')
                    
                    # Apply EXIF orientation to preserve correct image orientation
                    try:
                        from PIL import ImageOps
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass  # If EXIF transpose fails, continue with original orientation
                    
                    # Convert to RGB mode (required for JPG)
                    rgb_img = img.convert('RGB')
                    
                    # Save as JPG with high quality
                    rgb_img.save(new_path, 'JPEG', quality=95, optimize=True)
                    
                    self.logger.info(f" 🔄 Converted {original_format} → JPEG: {image_path.name}")
                    
                    # Remove original file only if it's a different path
                    if new_path != image_path and image_path.exists():
                        image_path.unlink()
                    
                    return new_path
                
                return image_path
                
        except Exception as e:
            self.logger.warning(f" ⚠️ Could not convert {image_path.name}: {e}")
            return image_path

    def _get_files_by_type(self, folder, file_type='image'):
        """
        Helper method to extract files of a specific type from a folder.
        Automatically converts unsupported image formats to JPG.
        
        Args:
            folder: Path object or string path to the folder
            file_type: 'image', 'video', or 'all' (default: 'image')
        
        Returns:
            List of Path objects matching the file type
        """
        # Cache Path conversion
        folder_path = folder if isinstance(folder, Path) else Path(folder)
        if not folder_path.exists():
            return []
        
        # Use cached extension lists
        if file_type == 'video':
            file_exts = self._video_exts
        elif file_type == 'reference_image':
            file_exts = self._ref_image_exts
        else:
            file_exts = self._all_image_exts
        
        if file_type in ['image', 'reference_image']:
            # Combine filtering and sorting in one pass - sort as we filter
            files = sorted(
                (f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in file_exts),
                key=lambda x: x.name.lower()
            )
            
            # Convert unsupported formats to JPG and resize oversized images
            max_dim = self.api_definitions.get('validation', {}).get('max_dimension')
            processed_files = []
            
            for file_path in files:
                # First convert format if needed
                converted_path = self._convert_image_to_jpg(file_path)
                
                # Then resize if max_dimension is defined and image exceeds it
                if max_dim:
                    converted_path = self._resize_oversized_image(converted_path, max_dim)
                
                processed_files.append(converted_path)
            
            return processed_files
        else:
            # Video files - combine filtering and sorting in one pass
            return sorted(
                (f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in file_exts),
                key=lambda x: x.name.lower()
            )

    def validate_file(self, file_path, file_type='image'):
        """Enhanced file validation with API-specific optimizations"""
        try:
            validation_rules = self.api_definitions.get('validation', {})

            if file_type == 'video':
                # Enhanced video validation for Runway
                # Optimization: Use single stat() call
                file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
                file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)
                video_rules = validation_rules.get('video', {})

                if file_size_mb > video_rules.get('max_size_mb', 500):
                    return False, f"Size {file_size_mb:.1f}MB too large"

                info = self._get_video_info(file_path)
                if not info:
                    return False, "Cannot read video info"

                duration_range = video_rules.get('duration', [1, 30])
                if not (duration_range[0] <= info['duration'] <= duration_range[1]):
                    return False, f"Duration {info['duration']:.1f}s invalid"

                min_dim = video_rules.get('min_dimension', 320)
                if info['width'] < min_dim or info['height'] < min_dim:
                    return False, f"Resolution {info['width']}x{info['height']} too small"

                return True, f"{info['width']}x{info['height']}, {info['duration']:.1f}s, {info['size_mb']:.1f}MB"

            else:
                # Optimization: Cache path conversion and get file size once
                file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
                file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)
                
                min_dimensions = validation_rules.get('min_dimension', 300)
                aspect_ratio_range = validation_rules.get('aspect_ratio', [0.4, 2.5])
                
                # Optimization: Open image once and cache dimensions
                with Image.open(file_path) as img:
                    w, h = img.size
                    
                    # Enhanced image validation by API
                    if self.api_name == "kling":
                        # Kling specific validation
                        if file_size_mb >= validation_rules.get('max_size_mb', 32):
                            return False, "Size > 32MB"
                        if w <= min_dimensions or h <= min_dimensions:
                            return False, f"Dims {w}x{h} too small"
                        ratio = w / h
                        if not (aspect_ratio_range[0] <= ratio <= aspect_ratio_range[1]):
                            return False, f"Ratio {ratio:.2f} invalid"
                        return True, f"{w}x{h}, {ratio:.2f}"

                    elif self.api_name == "runway":
                        # Runway reference image validation
                        if file_size_mb >= validation_rules.get('max_size_mb', 32):
                            return False, "Reference image > 32MB"
                        if w < min_dimensions or h < min_dimensions:
                            return False, f"Reference image {w}x{h} too small"
                        return True, f"Reference: {w}x{h}"

                    elif self.api_name == "nano_banana":
                        # Nano banana specific validation
                        if file_size_mb >= validation_rules.get('max_size_mb', 32):
                            return False, "Size > 32MB"
                        if w <= min_dimensions or h <= min_dimensions:
                            return False, f"Dims {w}x{h} too small"
                        return True, f"{w}x{h}"

                    else:
                        # Standard image validation for vidu APIs
                        max_size = validation_rules.get('max_size_mb', 50)
                        if file_size_mb >= max_size:
                            return False, f"Size > {max_size}MB"

                        min_dim = validation_rules.get('min_dimension', 128)
                        if w < min_dim or h < min_dim:
                            return False, f"Dims {w}x{h} too small"

                        # Check max dimension if defined
                        max_dim = validation_rules.get('max_dimension')
                        if max_dim and (w > max_dim or h > max_dim):
                            return False, f"Dims {w}x{h} exceed {max_dim}x{max_dim}"

                        # Check aspect ratio if defined
                        aspect_ratio_range = validation_rules.get('aspect_ratio')
                        if aspect_ratio_range:
                            ratio = w / h
                            if not (aspect_ratio_range[0] <= ratio <= aspect_ratio_range[1]):
                                return False, f"Ratio {ratio:.2f} invalid"

                        return True, f"{w}x{h}"

        except Exception as e:
            return False, f"Error: {str(e)}"

    def _validate_task_folder_structure(self, task, invalid_list):
        """Base validation template for task-folder structure (kling, nano, genvideo)."""
        folder = Path(task['folder'])
        
        # Auto-create task folder and Source subfolder if they don't exist
        folder.mkdir(parents=True, exist_ok=True)
        source_folder = folder / "Source"
        source_folder.mkdir(exist_ok=True)
        
        if not source_folder.exists():
            self.logger.warning(f"❌ Missing source: {source_folder}")
            return None
        
        image_files = self._get_files_by_type(source_folder, 'image')
        if not image_files:
            self.logger.warning(f"❌ Empty source: {source_folder}")
            return None
        
        # Validate files
        valid_count = 0
        for img_file in image_files:
            is_valid, reason = self.validate_file(img_file)
            if not is_valid:
                invalid_list.append({'path': str(img_file), 'folder': str(folder), 'name': img_file.name, 'reason': reason})
            else:
                valid_count += 1
        
        if valid_count > 0:
            # Create output directories based on API
            if self.api_name == "genvideo":
                (folder / "Generated_Image").mkdir(exist_ok=True)
            else:
                (folder / "Generated_Video").mkdir(exist_ok=True)
            (folder / "Metadata").mkdir(exist_ok=True)
            if self.api_name == "nano_banana":
                (folder / "Generated_Output").mkdir(exist_ok=True)
            return task, valid_count, len(image_files)
        return None

    def validate_and_prepare(self):
        """Enhanced validation with parallel processing support"""
        # Optimization: Cache config tasks list to avoid repeated dict lookups
        self._tasks_cache = self.config.get('tasks', [])
        
        if self.api_name == "kling":
            return self._validate_kling_structure()
        elif self.api_name == "kling_effects":
            return self._validate_kling_effects_structure()
        elif self.api_name == "kling_endframe":
            return self._validate_kling_endframe_structure()
        elif self.api_name == "kling_ttv":
            return self._validate_kling_ttv_structure()
        elif self.api_name == "nano_banana":
            return self._validate_nano_banana_structure()
        elif self.api_name == "runway":
            return self._validate_runway_structure()
        elif self.api_name == "vidu_effects":
            return self._validate_vidu_effects_structure()
        elif self.api_name == "vidu_reference":
            return self._validate_vidu_reference_structure()
        elif self.api_name == "genvideo":
            return self.validate_genvideo_structure()
        elif self.api_name == "pixverse":
            return self.validate_pixverse_structure()
        elif self.api_name == "wan":
            return self._validate_wan_structure()
        elif self.api_name == "dreamactor":
            return self._validate_dreamactor_structure()
        elif self.api_name == "kling_motion":
            return self._validate_kling_motion_structure()
        elif self.api_name == "veo":
            return self._validate_veo_structure()
        elif self.api_name == "veo_itv":
            return self._validate_veo_itv_structure()
        else:
            raise ValueError(f"Validation failed for unknown API: {self.api_name}")

    def _validate_kling_structure(self):
        """Enhanced Kling validation using base template."""
        valid_tasks, invalid_images = [], []
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache):
            result = self._validate_task_folder_structure(task, invalid_images)
            if result:
                valid_tasks.append(result[0])
                self.logger.info(f"✓ Task {i+1}: {result[1]}/{result[2]} valid images")
        if invalid_images:
            self.write_invalid_report(invalid_images, "kling")
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        return valid_tasks

    def _validate_kling_endframe_structure(self):
        """Validate Kling Endframe structure with image pairs."""
        valid_tasks = []
        invalid_images = []
        
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            folder = Path(task['folder'])
            
            # Optimization: mkdir with exist_ok=True handles existence check
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)
            
            # Get all image files
            image_files = self._get_files_by_type(source_folder, 'image')
            if not image_files:
                self.logger.warning(f"⚠️ Task {i}: No images found in {source_folder}")
                continue
            
            # Group into pairs and validate
            pairs = self._group_endframe_pairs(image_files)
            if not pairs:
                self.logger.warning(f"⚠️ Task {i}: No valid image pairs found")
                continue
            
            # Validate each image in pairs
            valid_pairs = 0
            for start_img, end_img in pairs:
                start_valid, start_msg = self.validate_file(start_img, 'image')
                end_valid, end_msg = self.validate_file(end_img, 'image')
                
                if not start_valid:
                    invalid_images.append(f"{start_img}: {start_msg}")
                if not end_valid:
                    invalid_images.append(f"{end_img}: {end_msg}")
                    
                if start_valid and end_valid:
                    valid_pairs += 1
            
            if valid_pairs > 0:
                # Create output directories
                (folder / "Generated_Video").mkdir(parents=True, exist_ok=True)
                (folder / "Metadata").mkdir(parents=True, exist_ok=True)
                
                valid_tasks.append(task)
                self.logger.info(f"✓ Task {i}: {valid_pairs}/{len(pairs)} valid image pairs")
        
        if invalid_images:
            self.write_invalid_report(invalid_images, "kling_endframe")
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        
        return valid_tasks
    
    def _group_endframe_pairs(self, all_images):
        """
        Group images into start/end pairs for Kling Endframe.
        Expects naming: "name_A resolution.ext" and "name_B resolution.ext"
        """
        image_dict = {}
        
        for img_path in all_images:
            name = img_path.stem
            parts = name.rsplit('_', 1)
            if len(parts) != 2:
                continue
            
            # Extract resolution from the end
            name_parts = name.split()
            if len(name_parts) >= 2:
                resolution = name_parts[-1]
                base_name = ' '.join(name_parts[:-1])
            else:
                continue
            
            # Create key: base_name + resolution (without A/B marker)
            base_key = base_name.rsplit('_', 1)[0] + '_' + resolution
            frame_marker = parts[1].split()[0] if parts[1] else None
            
            if base_key not in image_dict:
                image_dict[base_key] = {}
            
            if frame_marker in ['A', 'B']:
                image_dict[base_key][frame_marker] = img_path
        
        # Create pairs
        pairs = []
        for base_key, frames in image_dict.items():
            if 'A' in frames and 'B' in frames:
                pairs.append((frames['A'], frames['B']))
        
        return sorted(pairs, key=lambda x: x[0].name)

    def _validate_nano_banana_structure(self):
        """Enhanced Nano Banana validation with parallel processing (from working processor)"""
        valid_tasks = []
        invalid_images = []

        def process_task(task):
            folder = Path(task['folder'])
            
            # Auto-create task folder and Source subfolder if they don't exist
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)

            # Get and validate images
            image_files = self._get_files_by_type(source_folder, 'image')

            if not image_files:
                self.logger.warning(f"⚠️ No images found in: {source_folder}")
                return None, []

            # Validate images
            invalid_for_task = []
            valid_count = 0

            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_for_task.append({
                        'path': str(img_file), 'folder': str(folder),
                        'name': img_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count > 0:
                # Create output directories
                (folder / "Generated_Output").mkdir(exist_ok=True)
                (folder / "Metadata").mkdir(exist_ok=True)
                self.logger.info(f"✓ Task: {folder.name} - {valid_count}/{len(image_files)} valid images")
                return task, invalid_for_task

            return None, invalid_for_task

        # Process tasks in parallel if enabled
        # Optimization: Use cached tasks list
        if self.api_definitions.get('parallel_validation', False):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(process_task, self._tasks_cache))
        else:
            results = [process_task(task) for task in self._tasks_cache]

        # Collect results
        for task, invalid_for_task in results:
            if task:
                valid_tasks.append(task)
            invalid_images.extend(invalid_for_task)

        if invalid_images:
            self.write_invalid_report(invalid_images, "nano_banana")
            raise ValidationError(f"{len(invalid_images)} invalid images found")

        return valid_tasks

    def _validate_runway_structure(self):
        """Enhanced Runway validation with optional reference image support"""
        valid_tasks = []
        invalid_videos = []
        
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            folder = Path(task['folder'])
            
            # Optimization: mkdir with exist_ok=True handles existence check
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)
            
            # Check if reference is required
            use_comparison_template = task.get('use_comparison_template', False)
            reference_folder_path = task.get('reference_folder', '').strip()
            requires_reference = use_comparison_template or bool(reference_folder_path)
            
            # Validate reference folder if required
            reference_images = []
            if requires_reference:
                if reference_folder_path:
                    ref_folder = Path(reference_folder_path)
                else:
                    ref_folder = folder / "Reference"
                
                if not ref_folder.exists():
                    self.logger.warning(f"Missing reference folder {ref_folder}")
                    continue
                
                reference_images = self._get_files_by_type(ref_folder, 'reference_image')
                
                if not reference_images:
                    self.logger.warning(f"Empty reference folder {ref_folder}")
                    continue
            
            # Get video files
            video_files = self._get_files_by_type(source_folder, 'video')
            
            if not video_files:
                self.logger.warning(f"Empty source folder {source_folder}")
                continue
            
            # Validate videos
            valid_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file),
                        'folder': str(folder),
                        'name': video_file.name,
                        'reason': reason
                    })
                else:
                    valid_count += 1
            
            if valid_count == 0:
                continue
            
            # Create output directories
            (folder / "Generated_Video").mkdir(exist_ok=True)
            (folder / "Metadata").mkdir(exist_ok=True)
            
            # Update task config
            task['requires_reference'] = requires_reference
            if requires_reference:
                task['reference_images'] = reference_images
            
            valid_tasks.append(task)
            self.logger.info(f"Task {i}: {valid_count}/{len(video_files)} valid videos" + 
                            (f", {len(reference_images)} reference images" if requires_reference else " (text-to-video mode)"))
        
        if invalid_videos:
            self.write_invalid_report(invalid_videos, 'runway')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")
        
        return valid_tasks

    def _validate_wan_structure(self):
        """
        Validate Wan 2.2 structure with separate image and video folders.
        
        Wan requires:
        - Source Image/ folder with images
        - Source Video/ folder with videos
        - All images will be cross-matched with all videos
        """
        valid_tasks = []
        invalid_images = []
        invalid_videos = []
        
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            folder = Path(task['folder'])
            
            # Auto-create task folder and Source subfolders if they don't exist
            folder.mkdir(parents=True, exist_ok=True)
            source_image_folder = folder / "Source Image"
            source_video_folder = folder / "Source Video"
            source_image_folder.mkdir(exist_ok=True)
            source_video_folder.mkdir(exist_ok=True)
            
            # Get image files
            image_files = self._get_files_by_type(source_image_folder, 'image')
            if not image_files:
                self.logger.warning(f"❌ Task {i}: No images found in {source_image_folder}")
                continue
            
            # Get video files
            video_files = self._get_files_by_type(source_video_folder, 'video')
            if not video_files:
                self.logger.warning(f"❌ Task {i}: No videos found in {source_video_folder}")
                continue
            
            # Validate images
            valid_image_count = 0
            for image_file in image_files:
                is_valid, reason = self.validate_file(image_file, 'image')
                if not is_valid:
                    invalid_images.append({
                        'path': str(image_file),
                        'folder': str(folder),
                        'name': image_file.name,
                        'reason': reason
                    })
                else:
                    valid_image_count += 1
            
            # Validate videos
            valid_video_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file),
                        'folder': str(folder),
                        'name': video_file.name,
                        'reason': reason
                    })
                else:
                    valid_video_count += 1
            
            # Skip task if no valid files
            if valid_image_count == 0 or valid_video_count == 0:
                self.logger.warning(f"❌ Task {i}: Insufficient valid files")
                continue
            
            # Create output directories
            (folder / "Generated_Video").mkdir(exist_ok=True)
            (folder / "Metadata").mkdir(exist_ok=True)
            
            valid_tasks.append(task)
            total_combinations = valid_image_count * valid_video_count
            self.logger.info(
                f"✓ Task {i}: {valid_image_count} images × {valid_video_count} videos = "
                f"{total_combinations} total generations"
            )
        
        # Report validation errors
        if invalid_images:
            self.write_invalid_report(invalid_images, 'wan_images')
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        
        if invalid_videos:
            self.write_invalid_report(invalid_videos, 'wan_videos')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")
        
        return valid_tasks

    def _validate_dreamactor_structure(self):
        """
        Validate DreamActor structure with separate image and video folders.

        DreamActor requires:
        - Source Image/ folder with reference face images
        - Source Video/ folder with driver videos
        - All images will be cross-matched with all videos
        """
        valid_tasks = []
        invalid_images = []
        invalid_videos = []

        for i, task in enumerate(self._tasks_cache, 1):
            folder = Path(task['folder'])

            # Auto-create task folder and Source subfolders
            folder.mkdir(parents=True, exist_ok=True)
            source_image_folder = folder / "Source Image"
            source_video_folder = folder / "Source Video"
            source_image_folder.mkdir(exist_ok=True)
            source_video_folder.mkdir(exist_ok=True)

            # Get image files
            image_files = self._get_files_by_type(source_image_folder, 'image')
            if not image_files:
                self.logger.warning(f"❌ Task {i}: No images found in {source_image_folder}")
                continue

            # Get video files
            video_files = self._get_files_by_type(source_video_folder, 'video')
            if not video_files:
                self.logger.warning(f"❌ Task {i}: No videos found in {source_video_folder}")
                continue

            # Validate images
            valid_image_count = 0
            for image_file in image_files:
                is_valid, reason = self.validate_file(image_file, 'image')
                if not is_valid:
                    invalid_images.append({
                        'path': str(image_file),
                        'folder': str(folder),
                        'name': image_file.name,
                        'reason': reason
                    })
                else:
                    valid_image_count += 1

            # Validate videos
            valid_video_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file),
                        'folder': str(folder),
                        'name': video_file.name,
                        'reason': reason
                    })
                else:
                    valid_video_count += 1

            # Skip task if no valid files
            if valid_image_count == 0 or valid_video_count == 0:
                self.logger.warning(f"❌ Task {i}: Insufficient valid files")
                continue

            # Create output directories
            (folder / "Generated_Video").mkdir(exist_ok=True)
            (folder / "Metadata").mkdir(exist_ok=True)

            valid_tasks.append(task)
            total_combinations = valid_image_count * valid_video_count
            self.logger.info(
                f"✓ Task {i}: {valid_image_count} images × {valid_video_count} videos = "
                f"{total_combinations} total generations"
            )

        if invalid_images:
            self.write_invalid_report(invalid_images, 'dreamactor_images')
            raise ValidationError(f"{len(invalid_images)} invalid images found")

        if invalid_videos:
            self.write_invalid_report(invalid_videos, 'dreamactor_videos')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")

        return valid_tasks

    def _validate_kling_motion_structure(self):
        """
        Validate Kling Motion structure with separate image and video folders.

        Kling Motion requires:
        - Source Image/ folder with reference images (character appearance)
        - Source Video/ folder with motion source videos
        - All images will be cross-matched with all videos
        """
        valid_tasks = []
        invalid_images = []
        invalid_videos = []

        for i, task in enumerate(self._tasks_cache, 1):
            folder = Path(task['folder'])

            folder.mkdir(parents=True, exist_ok=True)
            source_image_folder = folder / "Source Image"
            source_video_folder = folder / "Source Video"
            source_image_folder.mkdir(exist_ok=True)
            source_video_folder.mkdir(exist_ok=True)

            image_files = self._get_files_by_type(source_image_folder, 'image')
            if not image_files:
                self.logger.warning(f"❌ Task {i}: No images found in {source_image_folder}")
                continue

            video_files = self._get_files_by_type(source_video_folder, 'video')
            if not video_files:
                self.logger.warning(f"❌ Task {i}: No videos found in {source_video_folder}")
                continue

            valid_image_count = 0
            for image_file in image_files:
                is_valid, reason = self.validate_file(image_file, 'image')
                if not is_valid:
                    invalid_images.append({
                        'path': str(image_file),
                        'folder': str(folder),
                        'name': image_file.name,
                        'reason': reason
                    })
                else:
                    valid_image_count += 1

            valid_video_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file),
                        'folder': str(folder),
                        'name': video_file.name,
                        'reason': reason
                    })
                else:
                    valid_video_count += 1

            if valid_image_count == 0 or valid_video_count == 0:
                self.logger.warning(f"❌ Task {i}: Insufficient valid files")
                continue

            (folder / "Generated_Video").mkdir(exist_ok=True)
            (folder / "Metadata").mkdir(exist_ok=True)

            valid_tasks.append(task)
            total_combinations = valid_image_count * valid_video_count
            self.logger.info(
                f"✓ Task {i}: {valid_image_count} images × {valid_video_count} videos = "
                f"{total_combinations} total generations"
            )

        if invalid_images:
            self.write_invalid_report(invalid_images, 'kling_motion_images')
            raise ValidationError(f"{len(invalid_images)} invalid images found")

        if invalid_videos:
            self.write_invalid_report(invalid_videos, 'kling_motion_videos')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")

        return valid_tasks

    def _validate_veo_structure(self):
        """
        Validate Veo text-to-video structure.
        
        Veo is text-to-video only, so we just validate that:
        1. Each task has a prompt
        2. Each task has an output folder specified
        3. Create necessary directories
        """
        valid_tasks = []
        
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            # Validate required fields
            if not task.get('prompt'):
                self.logger.warning(f"⚠️ Task {i}: Missing prompt")
                continue
            
            # Get or create output folder
            output_folder = Path(task.get('output_folder', ''))
            if not output_folder or str(output_folder) == '':
                self.logger.warning(f"⚠️ Task {i}: Missing output_folder")
                continue
            
            # Create output directories
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder = output_folder.parent / "Metadata"
            metadata_folder.mkdir(parents=True, exist_ok=True)
            
            # Add task number to config for handler use
            task['task_num'] = i
            
            valid_tasks.append(task)
            self.logger.info(f"✓ Task {i}: Text-to-video prompt configured")
        
        if not valid_tasks:
            raise Exception("No valid Veo tasks found")
        
        return valid_tasks

    def _validate_veo_itv_structure(self):
        """
        Validate Veo ITV (image-to-video) structure.
        
        Each task should have:
        1. A folder with a Source subfolder containing images
        2. A prompt for generation
        3. Optional: generation_count for multiple videos per image
        """
        valid_tasks = []
        invalid_images = []
        
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            # Validate required fields
            if not task.get('prompt'):
                self.logger.warning(f"⚠️ Task {i}: Missing prompt")
                continue
            
            folder = Path(task.get('folder', ''))
            if not folder or str(folder) == '':
                self.logger.warning(f"⚠️ Task {i}: Missing folder path")
                continue
            
            # Auto-create task folder and Source subfolder if they don't exist
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)
            
            # Get and validate images
            image_files = self._get_files_by_type(source_folder, 'image')
            
            if not image_files:
                self.logger.warning(f"⚠️ Task {i}: No images found in {source_folder}")
                continue
            
            # Validate images
            valid_count = 0
            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_images.append({
                        'folder': folder.name,
                        'filename': img_file.name,
                        'reason': reason
                    })
                else:
                    valid_count += 1
            
            if valid_count == 0:
                self.logger.warning(f"⚠️ Task {i}: No valid images in {source_folder}")
                continue
            
            # Create output directories
            output_folder = folder / "Generated_Video"
            metadata_folder = folder / "Metadata"
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)
            
            # Get generation count
            task_count = task.get('generation_count')
            global_count = self.config.get('generation_count', 1)
            generation_count = task_count if task_count is not None else global_count
            
            # Add enhanced task info
            enhanced_task = task.copy()
            enhanced_task.update({
                'folder': str(folder),
                'folder_name': folder.name,
                'style_name': task.get('style_name', folder.name),
                'source_dir': str(source_folder),
                'generated_dir': str(output_folder),
                'metadata_dir': str(metadata_folder),
                'generation_count': generation_count,
                'task_num': i
            })
            
            valid_tasks.append(enhanced_task)
            total_expected = valid_count * generation_count
            self.logger.info(f"✓ Task {i}: {valid_count} images × {generation_count} generations = {total_expected} videos")
        
        if invalid_images:
            self.write_invalid_report(invalid_images, "veo_itv")
            self.logger.warning(f"⚠️ {len(invalid_images)} invalid images found (see report)")
        
        if not valid_tasks:
            raise Exception("No valid Veo ITV tasks found")
        
        return valid_tasks

    def _validate_kling_ttv_structure(self):
        """
        Validate Kling TTV (text-to-video) structure.
        
        Similar to Veo, Kling TTV generates videos from text prompts only.
        Validates:
        1. Each task has a prompt
        2. Each task has an output folder specified
        3. Creates necessary directories
        """
        valid_tasks = []
        
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            # Validate required fields
            if not task.get('prompt'):
                self.logger.warning(f"⚠️ Task {i}: Missing prompt")
                continue
            
            # Get or create output folder
            output_folder = Path(task.get('output_folder', ''))
            if not output_folder or str(output_folder) == '':
                self.logger.warning(f"⚠️ Task {i}: Missing output_folder")
                continue
            
            # Create output directories
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder = output_folder.parent / "Metadata"
            metadata_folder.mkdir(parents=True, exist_ok=True)
            
            # Add task number to config for handler use
            task['task_num'] = i
            
            valid_tasks.append(task)
            self.logger.info(f"✓ Task {i}: Kling TTV prompt configured")
        
        if not valid_tasks:
            raise Exception("No valid Kling TTV tasks found")
        
        return valid_tasks

    def _validate_kling_effects_structure(self):
        """
        Validate Kling Effects structure with base folder and effect subfolders.
        
        Uses custom_effect (priority) or effect name from tasks to locate subfolders.
        Each effect folder should have Source, Generated_Video, and Metadata subfolders.
        """
        base_folder = Path(self.config.get('base_folder', ''))
        base_folder.mkdir(parents=True, exist_ok=True)

        valid_tasks = []
        invalid_images = []

        def process_task(task):
            # Use custom_effect if specified, otherwise use effect
            custom_effect = task.get('custom_effect', '')
            effect = task.get('effect', '')
            folder_name = custom_effect if custom_effect else effect
            
            if not folder_name:
                self.logger.warning(f"⚠️ Task has no effect or custom_effect specified")
                return None, []
            
            task_folder = base_folder / folder_name
            
            # Auto-create task folder and Source subfolder if they don't exist
            task_folder.mkdir(parents=True, exist_ok=True)
            source_dir = task_folder / "Source"
            source_dir.mkdir(exist_ok=True)

            # Get and validate images
            image_files = self._get_files_by_type(source_dir, 'image')

            if not image_files:
                self.logger.warning(f"⚠️ No images found in: {source_dir}")
                return None, []

            # Validate images
            invalid_for_task = []
            valid_count = 0

            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_for_task.append({
                        'folder': folder_name, 'filename': img_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count > 0:
                # Create output directories
                (task_folder / "Generated_Video").mkdir(exist_ok=True)
                (task_folder / "Metadata").mkdir(exist_ok=True)

                # Add folder paths to task
                enhanced_task = task.copy()
                enhanced_task.update({
                    'folder': str(task_folder),
                    'folder_name': folder_name,
                    'source_dir': str(source_dir),
                    'generated_dir': str(task_folder / "Generated_Video"),
                    'metadata_dir': str(task_folder / "Metadata")
                })

                self.logger.info(f"✓ {folder_name}: {valid_count}/{len(image_files)} valid images")
                return enhanced_task, invalid_for_task

            return None, invalid_for_task

        # Process tasks
        # Optimization: Use cached tasks list
        results = [process_task(task) for task in self._tasks_cache]

        # Collect results
        for task, invalid_for_task in results:
            if task:
                valid_tasks.append(task)
            invalid_images.extend(invalid_for_task)

        if invalid_images:
            self.write_invalid_report(invalid_images, "kling_effects")
            raise ValidationError(f"{len(invalid_images)} invalid images found")

        if not valid_tasks:
            raise Exception("No valid Kling Effects tasks found")

        return valid_tasks

    def _validate_vidu_effects_structure(self):
        """Enhanced Vidu Effects validation with parallel processing"""
        base_folder = Path(self.config.get('base_folder', ''))
        base_folder.mkdir(parents=True, exist_ok=True)

        valid_tasks = []
        invalid_images = []

        def process_task(task):
            effect_name = task.get('effect', '') or task.get('custom_effect_name', '')
            if not effect_name:
                self.logger.warning("⚠️ Task missing both 'effect' and 'custom_effect_name'")
                return None, []
            task_folder = base_folder / effect_name
            
            # Auto-create task folder and Source subfolder if they don't exist
            task_folder.mkdir(parents=True, exist_ok=True)
            source_dir = task_folder / "Source"
            source_dir.mkdir(exist_ok=True)

            # Get and validate images
            image_files = self._get_files_by_type(source_dir, 'image')

            if not image_files:
                self.logger.warning(f"⚠️ No images found in: {source_dir}")
                return None, []

            # Validate images
            invalid_for_task = []
            valid_count = 0

            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_for_task.append({
                        'folder': effect_name, 'filename': img_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count > 0:
                # Create output directories
                (task_folder / "Generated_Video").mkdir(exist_ok=True)
                (task_folder / "Metadata").mkdir(exist_ok=True)

                # Add folder paths to task
                enhanced_task = task.copy()
                enhanced_task.update({
                    'folder': str(task_folder),
                    'source_dir': str(source_dir),
                    'generated_dir': str(task_folder / "Generated_Video"),
                    'metadata_dir': str(task_folder / "Metadata")
                })

                self.logger.info(f"✓ {effect_name}: {valid_count}/{len(image_files)} valid images")
                return enhanced_task, invalid_for_task

            return None, invalid_for_task

        # Use parallel processing if enabled
        # Optimization: Use cached tasks list
        if self.api_definitions.get('parallel_validation', False):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(process_task, self._tasks_cache))
        else:
            results = [process_task(task) for task in self._tasks_cache]

        # Collect results
        for task, invalid_for_task in results:
            if task:
                valid_tasks.append(task)
            invalid_images.extend(invalid_for_task)

        if invalid_images:
            self.write_invalid_report(invalid_images)
            raise ValidationError(f"{len(invalid_images)} invalid images found")

        return valid_tasks

    def _validate_vidu_reference_structure(self):
        """Enhanced Vidu Reference validation with smart reference finding"""
        base_folder = Path(self.config.get('base_folder', ''))
        base_folder.mkdir(parents=True, exist_ok=True)

        # Optimization: Use cached tasks list and cache configured_tasks dict
        configured_tasks = {t['effect']: t for t in self._tasks_cache}
        valid_tasks = []
        errors = []

        # First, auto-create folders for configured tasks
        for task in self._tasks_cache:
            effect_name = task.get('effect', '')
            if effect_name:
                task_folder = base_folder / effect_name
                # Optimization: mkdir with exist_ok=True handles all checks
                task_folder.mkdir(parents=True, exist_ok=True)
                (task_folder / 'Source').mkdir(exist_ok=True)
                (task_folder / 'Reference').mkdir(exist_ok=True)

        for folder in base_folder.iterdir():
            if not (folder.is_dir() and not folder.name.startswith(('.', '_')) and
                   (folder / 'Source').exists() and (folder / 'Reference').exists()):
                continue

            # Get task config or create default
            if folder.name in configured_tasks:
                task = configured_tasks[folder.name].copy()
                task['folder_path'] = str(folder)
                self.logger.info(f"✓ Matched: {folder.name}")
            else:
                task = {
                    'effect': folder.name, 'folder_path': str(folder),
                    'prompt': self.config.get('default_prompt', ''),
                    'model': self.config.get('model', 'default'),
                    'duration': self.config.get('duration', 5),
                    'resolution': self.config.get('resolution', '1080p'),
                    'movement': self.config.get('movement', 'auto')
                }
                self.logger.info(f"⚠️ No config match: {folder.name} -> using defaults")

            result, task_errors = self._validate_reference_task(task)
            if result:
                valid_tasks.append(result)
            else:
                errors.extend(task_errors)

        if errors:
            for error in errors:
                self.logger.error(f"❌ {error}")
            raise Exception(f"{len(errors)} validation errors")

        return valid_tasks

    def _validate_reference_task(self, task):
        """Enhanced reference task validation with smart reference finding"""
        fp = Path(task['folder_path'])
        src_dir, ref_dir = fp / 'Source', fp / 'Reference'

        if not (src_dir.exists() and ref_dir.exists()):
            return None, [f"{task['effect']}: Missing Source/Reference folders"]

        src_imgs = self._get_files_by_type(src_dir, 'image')

        if not src_imgs:
            return None, [f"{task['effect']}: No source images"]

        ref_imgs = self._find_reference_images(ref_dir)
        if not ref_imgs:
            return None, [f"{task['effect']}: No reference images"]

        valid_sets = []
        for src in src_imgs:
            invalids = []

            try:
                with Image.open(src) as img:
                    ar = self.closest_aspect_ratio(img.width, img.height)
                    self.logger.info(f" 📐 {src.name} ({img.width}x{img.height}) → {ar}")
            except Exception as e:
                invalids.append(f"{src.name}: Cannot read dims - {e}")
                continue

            for img in [src] + ref_imgs:
                valid, reason = self.validate_file(img)
                if not valid:
                    invalids.append(f"{img.name}: {reason}")

            if not invalids:
                valid_sets.append({
                    'source_image': src, 'reference_images': ref_imgs,
                    'all_images': [src] + ref_imgs, 'aspect_ratio': ar,
                    'reference_count': len(ref_imgs)
                })
                self.logger.info(f" Found {len(ref_imgs)} reference images for {src.name}")

        if not valid_sets:
            return None, [f"{task['effect']}: No valid image sets"]

        # Create output directories
        for d in ['Generated_Video', 'Metadata']:
            (fp / d).mkdir(exist_ok=True)

        task.update({
            'generated_dir': str(fp / 'Generated_Video'),
            'metadata_dir': str(fp / 'Metadata'),
            'image_sets': valid_sets
        })

        return task, []

    def _find_reference_images(self, ref_dir):
        """Smart reference image finding from reference_processor"""
        refs = []
        file_types = self.api_definitions['file_types']
        max_refs = self.api_definitions.get('max_references', 6)

        # Smart naming convention detection
        for i in range(2, max_refs + 2):
            files = [f for f in ref_dir.iterdir()
                    if f.suffix.lower() in file_types and
                    (f.stem.lower().startswith(f'image{i}') or
                     f.stem.lower().startswith(f'image {i}') or
                     f.stem.split('_')[0] == str(i) or
                     f.stem.split('.')[0] == str(i))]

            if files:
                refs.append(files[0])
            else:
                break

        # Fallback to sorted files if no naming convention found
        return refs or sorted([f for f in ref_dir.iterdir()
                             if f.suffix.lower() in file_types])[:max_refs]

    def closest_aspect_ratio(self, w, h):
        """Enhanced aspect ratio detection from reference_processor"""
        r = w / h
        aspect_ratios = self.api_definitions.get('aspect_ratios', ["16:9", "9:16", "1:1"])

        if "16:9" in aspect_ratios and r > 1.2:
            return "16:9"
        elif "9:16" in aspect_ratios and r < 0.8:
            return "9:16"
        else:
            return "1:1"

    def write_invalid_report(self, invalid_files, api_suffix=""):
        """Print invalid files report to terminal instead of creating a file.
        
        Args:
            invalid_files: List of dictionaries containing invalid file information.
            api_suffix: Optional suffix to identify the API type in the header.
        """
        api_label = api_suffix.upper() if api_suffix else self.api_name.upper()
        
        self.logger.error(f"\n{'='*60}")
        self.logger.error(f"❌ INVALID FILES REPORT - {api_label}")
        self.logger.error(f"{'='*60}")
        self.logger.error(f"Total invalid files: {len(invalid_files)}")
        self.logger.error(f"Generated: {datetime.now()}")
        self.logger.error(f"{'-'*60}")
        
        for file in invalid_files:
            if 'folder' in file:
                if 'filename' in file:
                    self.logger.error(f"  ❌ {file['folder']}: {file['filename']} - {file['reason']}")
                else:
                    self.logger.error(f"  ❌ {file['name']} in {file['folder']}: {file['reason']}")
            elif 'type' in file:
                self.logger.error(f"  ❌ {file['name']} ({file['type']}) in {file.get('folder', 'unknown')}: {file['reason']}")
            else:
                self.logger.error(f"  ❌ {file['name']} in {file.get('path', 'unknown')}: {file['reason']}")
        
        self.logger.error(f"{'='*60}\n")

    def wait_for_schedule(self):
        """Wait for scheduled time if specified"""
        start_time_str = self.config.get('schedule', {}).get('start_time', '')
        if not start_time_str:
            return

        try:
            target_hour, target_min = map(int, start_time_str.split(':'))
            now = datetime.now()
            target = now.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)

            if target <= now:
                target = target.replace(day=target.day + 1)

            wait_seconds = (target - now).total_seconds()
            self.logger.info(f"⏰ Waiting {wait_seconds/3600:.1f}h until {target.strftime('%H:%M')}")
            time.sleep(wait_seconds)
        except ValueError:
            self.logger.warning(f"❌ Invalid time format: {start_time_str}")

    def initialize_client(self):
        """Initialize Gradio client"""
        try:
            endpoint = self.api_definitions.get('endpoint', '')

            # Handle testbed URL override for nano_banana
            if self.api_name == "nano_banana" and self.config.get('testbed'):
                endpoint = self.config['testbed']

            # Build optional headers (cookie for authenticated testbed access)
            headers = {}
            cookie = self.config.get('testbed_cookie') or self._testbed_cookie
            if cookie:
                headers['Cookie'] = cookie

            self.client = Client(endpoint, headers=headers or None)
            self.logger.info(f"✓ Client initialized: {endpoint}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Client init failed: {e}")
            return False

    def save_nano_responses(self, response_data, output_folder, base_name):
        """Save nano banana response data with base64 image handling (from working processor)"""
        if not response_data or not isinstance(response_data, list):
            return [], []

        saved_files = []
        text_responses = []

        for i, item in enumerate(response_data):
            if not isinstance(item, dict) or 'type' not in item or 'data' not in item:
                continue

            if item['type'] == "Text":
                text_responses.append({'index': i + 1, 'content': item['data']})
            elif item['type'] == "Image" and item['data'].strip():
                try:
                    # Handle base64 image data
                    if item['data'].startswith('image'):
                        header, base64_data = item['data'].split(',', 1)
                        ext = header.split('/')[1].split(';')[0]
                    else:
                        base64_data = item['data']
                        ext = 'png'

                    if len(base64_data.strip()) == 0:
                        continue

                    image_bytes = base64.b64decode(base64_data)
                    if len(image_bytes) < 100:  # Too small, likely invalid
                        continue

                    image_file = output_folder / f"{base_name}_image_{i+1}.{ext}"
                    with open(image_file, 'wb') as f:
                        f.write(image_bytes)

                    saved_files.append(str(image_file))
                except Exception as e:
                    self.logger.warning(f"Error saving image {i+1}: {e}")

        return saved_files, text_responses

    def process_file(self, file_path, task_config, output_folder, metadata_folder):
        """Process file using registered handler."""
        max_retries = self.api_definitions.get('max_retries', 3)
        handler = HandlerRegistry.get_handler(self.api_name, self)
        
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.logger.info(f" 🔄 Retry {attempt}/{max_retries-1}")
                    time.sleep(5)
                
                result = handler.process(file_path, task_config, output_folder, 
                                        metadata_folder, attempt, max_retries)
                
                if not result and attempt < max_retries - 1:
                    continue
                return result
                
            except Exception as e:
                if attempt == max_retries - 1:
                    self.save_failure_metadata(file_path, task_config, metadata_folder, str(e), attempt + 1)
                    return False
                continue
        
        return False

    def get_optimal_runway_ratio(self, video_width, video_height):
        input_ratio = video_width / video_height
        available_ratios = self.api_definitions.get('available_ratios', [...])
        
        # Find closest match by calculating ratio differences
        best_ratio = "1280:720"  # fallback
        smallest_difference = float('inf')
        
        for ratio_str in available_ratios:
            w, h = map(int, ratio_str.split(':'))
            ratio_value = w / h
            difference = abs(input_ratio - ratio_value)
            
            if difference < smallest_difference:
                smallest_difference = difference
                best_ratio = ratio_str
        
        return best_ratio

    def _capture_all_api_fields(self, result, known_field_names=None):
        """
        Helper to capture ALL fields from an API result tuple without duplicates.
        
        Args:
            result: The tuple returned from client.predict()
            known_field_names: Optional list of known field names to map to indices
                             e.g., ['output_urls', 'field_1', 'task_id', 'error_msg']
        
        Returns:
            Dict with all result fields captured with known names taking priority:
            - Named fields if known_field_names provided (output_urls, task_id, etc.)
            - api_result_N only for fields without known names
        """
        if not isinstance(result, tuple):
            return {'api_result_0': result}
        
        captured = {}
        
        # Map known field names to result indices (these take priority)
        if known_field_names:
            for i, field_name in enumerate(known_field_names):
                if i < len(result):
                    captured[field_name] = result[i]
        
        # Capture remaining fields by index (skip indices with known names)
        named_indices = set(range(len(known_field_names))) if known_field_names else set()
        for i in range(len(result)):
            if i not in named_indices:
                value = result[i]
                # Store complex types as type name, simple types as-is
                captured[f'api_result_{i}'] = value if not isinstance(value, (dict, list, tuple)) else str(type(value).__name__)
        
        return captured

    def _make_json_serializable(self, obj):
        """Convert non-JSON-serializable objects to strings recursively"""
        if isinstance(obj, dict):
            return {k: self._make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_serializable(item) for item in obj]
        elif isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, datetime):
            return obj.isoformat()
        elif hasattr(obj, '__dict__'):
            return str(obj)
        else:
            try:
                json.dumps(obj)
                return obj
            except (TypeError, ValueError):
                return str(obj)

    def save_failure_metadata(self, file_path, task_config, metadata_folder, error, attempts):
        """Enhanced failure metadata saving"""
        base_name = Path(file_path).stem
        metadata = {
            "source_file": Path(file_path).name,
            "error": error,
            "attempts": attempts,
            "success": False,
            "processing_timestamp": datetime.now().isoformat(),
            "api_name": self.api_name
        }

        # Add API-specific fields (excluding bulk data like image_sets)
        exclude_keys = {'image_sets', 'folder_path', 'source_dir', 'generated_dir', 'metadata_dir', 'all_images'}
        for key in ['prompt', 'effect', 'model', 'duration', 'resolution', 'aspect_ratio', 'movement', 'category']:
            if key in task_config and key not in exclude_keys:
                metadata[key] = task_config[key]
        
        # Add only the relevant reference images for THIS file (vidu_reference specific)
        if 'reference_images' in task_config:
            metadata['reference_images'] = [Path(ref).name for ref in task_config['reference_images']]
            metadata['reference_count'] = len(task_config['reference_images'])

        # Convert non-serializable objects to strings
        metadata = self._make_json_serializable(metadata)
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def save_metadata(self, metadata_folder, base_name, source_name, result_data, task_config, 
                     api_specific_filename=None, log_status=False):
        """
        Universal metadata saving method. Always records all fields from result_data and task_config.
        
        Args:
            metadata_folder: Path to metadata directory
            base_name: Base name for the metadata file
            source_name: Name of the source file
            result_data: Dict containing API result data
            task_config: Dict containing task configuration
            api_specific_filename: Optional custom filename (e.g., for runway with ref_stem)
            log_status: If True, logs success/failure status after saving
        """
        # Determine source field name based on API
        if self.api_name == "runway":
            source_field = "source_video"
        elif self.api_name in ["kling", "nano_banana", "vidu_effects", "vidu_reference", "genvideo", "pixverse"]:
            source_field = "source_image"
        else:
            source_field = "source_file"
        
        # Build base metadata
        metadata = {
            source_field: source_name,
            "processing_timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S') if self.api_name == "kling" else datetime.now().isoformat(),
            "api_name": self.api_name
        }
        
        # Merge result data
        if result_data:
            metadata.update(result_data)
        
        # Merge task config selectively (exclude bulk data that shouldn't be in individual metadata)
        exclude_keys = {'image_sets', 'folder_path', 'source_dir', 'generated_dir', 'metadata_dir', 'all_images'}
        for k, v in task_config.items():
            if k not in metadata and k not in exclude_keys:
                metadata[k] = v
        
        # Convert non-serializable objects to strings
        metadata = self._make_json_serializable(metadata)
        
        # Determine filename
        if api_specific_filename:
            metadata_file = metadata_folder / api_specific_filename
        else:
            metadata_file = metadata_folder / f"{base_name}_metadata.json"
        
        # Write metadata
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # Optional status logging
        if log_status:
            status = "✓" if result_data.get('success') else "❌"
            self.logger.info(f" {status} Metadata saved: {metadata_file.name}")

    # Backwards-compatible wrapper methods (delegate to universal save_metadata)
    def save_kling_metadata(self, metadata_folder, base_name, image_name, result_data, task_config):
        """Kling-specific metadata saving (delegates to universal save_metadata)."""
        self.save_metadata(metadata_folder, base_name, image_name, result_data, task_config, log_status=True)

    def save_nano_metadata(self, metadata_folder, base_name, image_name, result_data, task_config):
        """Nano Banana specific metadata saving (delegates to universal save_metadata)."""
        self.save_metadata(metadata_folder, base_name, image_name, result_data, task_config)

    def save_runway_metadata(self, metadata_folder, base_name, ref_stem, video_name, ref_name, result_data, task_config):
        """Runway-specific metadata saving (delegates to universal save_metadata)."""
        # Add runway-specific field to result_data
        if result_data and ref_name:
            result_data['reference_image'] = ref_name
        filename = f"{base_name}_ref_{ref_stem}_runway_metadata.json"
        self.save_metadata(metadata_folder, base_name, video_name, result_data, task_config, 
                          api_specific_filename=filename, log_status=True)

    def _process_files_in_folder(self, task, task_num, total_tasks, source_folder, output_folder, metadata_folder, task_name=None):
        """Universal file processing loop template."""
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {task_name or source_folder.parent.name}")
        image_files = self._get_files_by_type(source_folder, 'image')
        successful = 0
        skipped = 0
        for i, img_file in enumerate(image_files, 1):
            # Check if file was already successfully processed
            if self._is_file_processed(img_file, metadata_folder):
                self.logger.info(f" ⏭️ {i}/{len(image_files)}: {img_file.name} (already processed)")
                skipped += 1
                successful += 1
                continue
            
            self.logger.info(f" 🖼️ {i}/{len(image_files)}: {img_file.name}")
            if self.process_file(img_file, task, output_folder, metadata_folder):
                successful += 1
            if i < len(image_files):
                time.sleep(self.api_definitions.get('rate_limit', 3))
        self.logger.info(f"✓ Task {task_num}: {successful}/{len(image_files)} successful ({skipped} skipped)")
        return successful
    
    def _is_file_processed(self, file_path, metadata_folder):
        """Check if a file has already been successfully processed.
        
        Args:
            file_path: Path to the source file.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            bool: True if file has successful metadata, False otherwise.
        """
        import json
        base_name = Path(file_path).stem
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                # Only skip if previous processing was successful
                return metadata.get('success', False)
            except (json.JSONDecodeError, IOError):
                return False
        return False

    def process_task(self, task, task_num, total_tasks):
        """Process task using registered handler."""
        handler = HandlerRegistry.get_handler(self.api_name, self)
        handler.process_task(task, task_num, total_tasks)

    def validate_genvideo_structure(self):
        """Validate genvideo folder structure using base template."""
        valid_tasks, invalid_images = [], []
        # Optimization: Use cached tasks list
        for i, task in enumerate(self._tasks_cache, 1):
            result = self._validate_task_folder_structure(task, invalid_images)
            if result:
                valid_tasks.append(result[0])
                self.logger.info(f"✓ Task {i}: {result[1]}/{result[2]} valid images")
        if invalid_images:
            self.write_invalid_report(invalid_images, "genvideo")
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        return valid_tasks

    def validate_pixverse_structure(self):
        """Enhanced Pixverse validation with base folder structure"""
        base_folder = Path(self.config.get("base_folder", ""))
        base_folder.mkdir(parents=True, exist_ok=True)
        
        valid_tasks = []
        invalid_images = []
        
        def process_task(task):
            effect_name = task.get("effect", "")
            task_folder = base_folder / effect_name
            
            # Auto-create task folder and Source subfolder if they don't exist
            task_folder.mkdir(parents=True, exist_ok=True)
            source_dir = task_folder / "Source"
            source_dir.mkdir(exist_ok=True)
            
            image_files = self._get_files_by_type(source_dir, 'image')
            
            if not image_files:
                self.logger.warning(f"⚠️ No images found in: {source_dir}")
                return None, []
            
            invalid_for_task = []
            valid_count = 0
            
            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_for_task.append({
                        "folder": effect_name,
                        "filename": img_file.name,
                        "reason": reason
                    })
                else:
                    valid_count += 1
            
            if valid_count == 0:
                return None, invalid_for_task
            
            # Create output directories
            (task_folder / "Generated_Video").mkdir(exist_ok=True)
            (task_folder / "Metadata").mkdir(exist_ok=True)
            
            enhanced_task = task.copy()
            enhanced_task.update({
                "folder": str(task_folder),
                "source_dir": str(source_dir),
                "generated_dir": str(task_folder / "Generated_Video"),
                "metadata_dir": str(task_folder / "Metadata")
            })
            
            self.logger.info(f"✓ {effect_name}: {valid_count}/{len(image_files)} valid images")
            return enhanced_task, invalid_for_task
        
        # Optimization: Use cached tasks list
        if self.api_definitions.get("parallel_validation", False):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(process_task, self._tasks_cache))
        else:
            results = [process_task(task) for task in self._tasks_cache]
        
        for task, invalid_for_task in results:
            if task:
                valid_tasks.append(task)
            invalid_images.extend(invalid_for_task)
        
        if invalid_images:
            self.write_invalid_report(invalid_images, "pixverse")
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        
        return valid_tasks

    def download_file(self, url, path):
        """Standard file download method"""
        try:
            headers = {}
            cookie = self.config.get('testbed_cookie') or self._testbed_cookie
            if cookie:
                headers['Cookie'] = cookie

            with requests.get(url, stream=True, timeout=30, headers=headers or None) as r:
                r.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=16384):
                        f.write(chunk)
            return True
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            return False

    def run(self):
        """
        Main execution flow for API processing.
        
        Prevents system sleep during processing:
        - macOS: Uses native 'caffeinate' command (most reliable)
        - Other platforms: Uses wakepy if available
        
        Returns:
            bool: True if processing completed successfully, False otherwise
        """
        self.logger.info(f"🚀 Starting {self.api_name.replace('_', ' ').title()} Processor")
        
        # macOS: Use native caffeinate command (most reliable)
        if IS_MACOS:
            self.logger.info("☕ System sleep prevention activated (macOS caffeinate)")
            return self._run_with_caffeinate()
        # Other platforms: Use wakepy if available
        elif WAKEPY_AVAILABLE:
            self.logger.info("☕ System sleep prevention activated (wakepy)")
            with keep.running(on_fail='warn'):
                result = self._execute_processing()
                self.logger.info("💤 System sleep prevention deactivated")
                return result
        else:
            self.logger.warning("⚠️ No sleep prevention available - system may sleep during processing")
            self.logger.warning("   macOS: caffeinate not found | Other: Install wakepy with: pip install wakepy")
            return self._execute_processing()
    
    def _cleanup_caffeinate(self):
        """
        Terminate the caffeinate subprocess tracked by this processor instance.

        Uses SIGTERM first, falling back to SIGKILL if the process does not
        exit within 5 seconds.  Safe to call multiple times; subsequent calls
        are no-ops once the process has been cleaned up.
        """
        proc = self._caffeinate_process
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                self.logger.info("💤 System sleep prevention deactivated")
        except OSError:
            pass
        finally:
            self._caffeinate_process = None

    def _caffeinate_signal_handler(self, signum, frame):
        """
        Signal handler that cleans up caffeinate before re-raising the signal.

        Restores the original signal handler so the default behaviour
        (e.g. KeyboardInterrupt for SIGINT) still occurs after cleanup.

        Args:
            signum: Signal number received.
            frame: Current stack frame.
        """
        self._cleanup_caffeinate()
        # Restore original handler and re-raise so normal behaviour occurs
        if signum == signal.SIGINT and self._original_sigint:
            signal.signal(signal.SIGINT, self._original_sigint)
        elif signum == signal.SIGTERM and self._original_sigterm:
            signal.signal(signal.SIGTERM, self._original_sigterm)
        os.kill(os.getpid(), signum)

    def _run_with_caffeinate(self):
        """
        Run processing with macOS caffeinate to prevent sleep.

        Caffeinate is macOS's native tool that reliably prevents system sleep.
        The caffeinate PID is tracked on the instance so cleanup is scoped to
        this processor only — other concurrent script instances are unaffected.

        Safety nets against orphaned caffeinate processes:
        - ``finally`` block for normal completion or exceptions.
        - ``atexit`` handler for unexpected interpreter exit.
        - ``SIGINT`` / ``SIGTERM`` signal handlers for Ctrl+C / kill.

        Returns:
            bool: True if processing completed successfully, False otherwise.
        """
        try:
            self._caffeinate_process = subprocess.Popen(
                ['caffeinate', '-di'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.logger.info(
                f"☕ caffeinate started (PID {self._caffeinate_process.pid})"
            )

            # Register safety-net cleanup handlers
            atexit.register(self._cleanup_caffeinate)
            self._original_sigint = signal.getsignal(signal.SIGINT)
            self._original_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGINT, self._caffeinate_signal_handler)
            signal.signal(signal.SIGTERM, self._caffeinate_signal_handler)

            try:
                result = self._execute_processing()
                return result
            finally:
                self._cleanup_caffeinate()
                # Restore original signal handlers
                if self._original_sigint:
                    signal.signal(signal.SIGINT, self._original_sigint)
                    self._original_sigint = None
                if self._original_sigterm:
                    signal.signal(signal.SIGTERM, self._original_sigterm)
                    self._original_sigterm = None
                atexit.unregister(self._cleanup_caffeinate)

        except FileNotFoundError:
            self.logger.warning(
                "⚠️ caffeinate command not found - running without sleep prevention"
            )
            return self._execute_processing()
        except Exception as e:
            self._cleanup_caffeinate()
            self.logger.error(f"❌ Error running with caffeinate: {e}")
            self.logger.warning(
                "⚠️ Falling back to execution without sleep prevention"
            )
            return self._execute_processing()
    
    def _execute_processing(self):
        """
        Core processing logic without sleep prevention wrapper.
        
        Returns:
            bool: True if processing completed successfully, False otherwise
        
        Raises:
            ValidationError: If file validation fails (propagates to caller).
        """
        if not self.load_config():
            return False

        try:
            valid_tasks = self.validate_and_prepare()
        except ValidationError:
            # Re-raise ValidationError to signal report should be skipped
            raise
        except Exception as e:
            self.logger.error(str(e))
            return False

        self.wait_for_schedule()

        if not self.initialize_client():
            return False

        start_time = time.time()

        for i, task in enumerate(valid_tasks, 1):
            try:
                self.process_task(task, i, len(valid_tasks))
                if i < len(valid_tasks):
                    task_delay = self.api_definitions.get('task_delay', 10)
                    time.sleep(task_delay)
            except Exception as e:
                self.logger.error(f"Task {i} failed: {e}")

        elapsed = time.time() - start_time
        self.logger.info(f"🎉 Completed {len(valid_tasks)} tasks in {elapsed/60:.1f} minutes")
        
        return True


# Factory function for easy instantiation
def create_processor(api_name, config_file=None):
    """Factory function to create API processor"""
    return UnifiedAPIProcessor(api_name, config_file)

# ==================== MAIN EXECUTION ====================
if __name__ == "__main__":
    import sys

    # Enhanced command line support
    if len(sys.argv) < 2:
        print("Usage: python unified_api_processor.py [api_name] [config_file]")
        print("Supported APIs: kling, nano_banana, vidu_effects, vidu_reference, runway, genvideo")
        sys.exit(1)

    api_name = sys.argv[1]
    config_file = sys.argv[2] if len(sys.argv) > 2 else None

    processor = UnifiedAPIProcessor(api_name, config_file)
    processor.run()
