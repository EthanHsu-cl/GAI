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
from handlers.base_handler import ValidationError

"""
file download command example:
yt-dlp -f "bv*[vcodec~='^(h264|avc)']+ba[acodec~='^(mp?4a|aac)']" "https://youtube.com/playlist?list=PLSgBrV2b0XA_ofBZ4c3e85sTNBh3BKN2y&si=_5VpzvdI7hsF-a4o"
"""


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
        """Delegate file validation to the appropriate handler.

        Args:
            file_path: Path to the file to validate.
            file_type: 'image' or 'video'.

        Returns:
            tuple: (is_valid, reason_string)
        """
        handler = HandlerRegistry.get_handler(self.api_name, self)
        return handler.validate_file(file_path, file_type)

    def validate_and_prepare(self):
        """Validate folder structure by delegating to the handler.

        Returns:
            list: Valid task dictionaries ready for processing.

        Raises:
            ValidationError: If invalid files are found.
        """
        self._tasks_cache = self.config.get('tasks', [])
        handler = HandlerRegistry.get_handler(self.api_name, self)
        return handler.validate_structure(self._tasks_cache, self.config)

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

    def process_task(self, task, task_num, total_tasks):
        """Process task using registered handler."""
        handler = HandlerRegistry.get_handler(self.api_name, self)
        handler.process_task(task, task_num, total_tasks)

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
