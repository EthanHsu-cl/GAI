"""Nano Banana API Handler - Multi-Image Support."""
from pathlib import Path
from gradio_client import handle_file
import time
import random
from datetime import datetime
from PIL import Image
from .base_handler import BaseAPIHandler


class NanoBananaHandler(BaseAPIHandler):
    """Google Flash/Nano Banana handler with multi-image support.
    
    Supports:
        - gemini-2.5-flash-image: max 3 images (faster)
        - gemini-3-pro-image-preview: max 14 images (better quality)
    """
    
    # Maximum images allowed per model
    MODEL_MAX_IMAGES = {
        'gemini-2.5-flash-image': 3,
        'gemini-3-pro-image-preview': 14
    }
    DEFAULT_MAX_IMAGES = 3
    
    # Valid aspect ratios supported by the API
    VALID_ASPECT_RATIOS = [
        '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9'
    ]
    DEFAULT_ASPECT_RATIO = '1:1'
    
    def __init__(self, processor):
        """Initialize handler with multi-image support."""
        super().__init__(processor)
        self._additional_image_pools = {}
        self._used_combinations = set()
        self._source_file_indices = {}  # Track source file index for sequential matching
    
    def _load_image_pools(self, task_config):
        """Load and cache image pools from additional folders.
        
        Args:
            task_config: Task configuration dictionary containing multi_image_config.
        
        Returns:
            dict: Pool data with 'pools', 'mode', and 'allow_duplicates' keys,
                  or None if multi-image is not configured.
        """
        multi_image_config = task_config.get('multi_image_config', {})
        
        if not multi_image_config or not multi_image_config.get('enabled', False):
            return None
        
        mode = multi_image_config.get('mode', 'random_pairing')
        folders = multi_image_config.get('folders', [])
        
        if not folders:
            return None
        
        # Cache image pools per task
        task_key = str(task_config.get('folder', ''))
        if task_key not in self._additional_image_pools:
            pools = []
            for folder_path in folders:
                folder = Path(folder_path)
                if folder.exists():
                    images = self.processor._get_files_by_type(folder, 'image')
                    if images:
                        # Sort images by filename for deterministic ordering across runs
                        images = sorted(images, key=lambda x: x.name.lower())
                        pools.append(images)
                        self.logger.info(f" 📂 Loaded {len(images)} images from {folder.name}")
                else:
                    self.logger.warning(f" ⚠️ Folder not found: {folder}")
            
            # Build source file index for this task (for sequential one-to-one matching)
            source_folder = Path(task_config.get('folder', '')) / "Source"
            if source_folder.exists():
                source_files = self.processor._get_files_by_type(source_folder, 'image')
                source_files = sorted(source_files, key=lambda x: x.name.lower())
                self._source_file_indices[task_key] = {
                    str(f): idx for idx, f in enumerate(source_files)
                }
                self.logger.info(f" 📝 Indexed {len(source_files)} source files for sequential matching")
            
            self._additional_image_pools[task_key] = {
                'pools': pools,
                'mode': mode,
                'allow_duplicates': multi_image_config.get('allow_duplicates', False)
            }
        
        return self._additional_image_pools[task_key]
    
    def _get_additional_images(self, file_path, task_config):
        """Get additional images based on configuration mode.
        
        Args:
            file_path: Path to the source file being processed.
            task_config: Task configuration dictionary.
        
        Returns:
            list: List of additional image paths (can be empty strings for unused slots).
        """
        # Get model to determine max images
        model = task_config.get('model', 'gemini-2.5-flash-image')
        max_images = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        # Reserve 1 slot for source image
        max_additional = max_images - 1
        
        # Check if multi-image is explicitly disabled
        if not task_config.get('use_multi_image', True):
            return []
        
        # Check for static additional images (legacy support)
        additional_images = task_config.get('additional_images', {})
        if additional_images:
            result = []
            # Support legacy format with image1, image2, etc.
            for i in range(1, max_additional + 1):
                img = additional_images.get(f'image{i}', '')
                if img:
                    result.append(img)
            return result
        
        # Check for multi-image configuration
        pool_data = self._load_image_pools(task_config)
        if not pool_data or not pool_data['pools']:
            return []
        
        pools = pool_data['pools']
        mode = pool_data['mode']
        allow_duplicates = pool_data['allow_duplicates']
        
        if mode == 'random_pairing':
            return self._random_pairing(pools, file_path, allow_duplicates, max_additional)
        elif mode == 'sequential':
            return self._sequential_selection(pools, file_path, max_additional)
        else:
            self.logger.warning(f" ⚠️ Unknown mode '{mode}', using random_pairing")
            return self._random_pairing(pools, file_path, allow_duplicates, max_additional)
    
    def _random_pairing(self, pools, file_path, allow_duplicates, max_additional):
        """Randomly select one image from each pool, optionally avoiding duplicates.
        
        Args:
            pools: List of image pools (each pool is a list of Path objects).
            file_path: Path to the source file being processed.
            allow_duplicates: Whether to allow duplicate combinations.
            max_additional: Maximum number of additional images to return.
        
        Returns:
            list: List of selected image paths as strings.
        """
        selected = []
        max_attempts = 100
        
        for pool in pools[:max_additional]:
            if not pool:
                continue
            
            if allow_duplicates:
                selected.append(str(random.choice(pool)))
            else:
                # Try to find unused combination
                for _ in range(max_attempts):
                    candidate = random.choice(pool)
                    combo_key = (str(file_path), str(candidate))
                    if combo_key not in self._used_combinations:
                        self._used_combinations.add(combo_key)
                        selected.append(str(candidate))
                        break
                else:
                    # If we can't find unused after max_attempts, just use random
                    selected.append(str(random.choice(pool)))
        
        return selected[:max_additional]
    
    def _sequential_selection(self, pools, file_path, max_additional):
        """Select images sequentially from each pool based on source file index.
        
        Ensures one-to-one matching when enough images are available:
        - Uses sorted source file index for consistent pairing
        - First source file → first additional image(s)
        - Second source file → second additional image(s)
        - When pool is smaller than source files, cycles back using modulo
        
        Args:
            pools: List of image pools (each pool is a list of Path objects).
            file_path: Path to the source file being processed.
            max_additional: Maximum number of additional images to return.
        
        Returns:
            list: List of selected image paths as strings.
        """
        # Get the source file's index from our pre-built index
        task_key = None
        for key, index_map in self._source_file_indices.items():
            if str(file_path) in index_map:
                task_key = key
                file_index = index_map[str(file_path)]
                break
        else:
            # Fallback if file not found in index (shouldn't happen)
            self.logger.warning(f" ⚠️ File not found in source index: {file_path.name}")
            file_index = hash(str(file_path)) % 10000
        
        selected = []
        
        for pool in pools[:max_additional]:
            if pool:
                # Use the source file index for one-to-one matching
                # When there are enough images, each source gets a unique additional image
                # When pool is smaller, it cycles back using modulo
                index = file_index % len(pool)
                selected.append(str(pool[index]))
                
                # Log info about the pairing for first few files
                if file_index < 3 or (file_index % 10 == 0):
                    pool_size = len(pool)
                    if pool_size >= file_index + 1:
                        self.logger.debug(f" 🔗 One-to-one match: source#{file_index} → additional#{index}")
                    else:
                        self.logger.debug(f" 🔄 Cycling match: source#{file_index} → additional#{index} (pool size: {pool_size})")
        
        return selected[:max_additional]
    
    def _get_aspect_ratio(self, file_path, task_config):
        """Determine aspect ratio from config or auto-detect from source image.
        
        If aspect_ratio is specified in task_config, validates and uses it.
        Otherwise, analyzes the source image dimensions and selects the
        closest matching aspect ratio from VALID_ASPECT_RATIOS.
        
        Args:
            file_path: Path to the source image file.
            task_config: Task configuration dictionary.
        
        Returns:
            str: Valid aspect ratio string (e.g., '16:9', '1:1').
        """
        # Check if aspect_ratio is specified in config
        config_ratio = task_config.get('aspect_ratio', '')
        if config_ratio:
            if config_ratio in self.VALID_ASPECT_RATIOS:
                return config_ratio
            else:
                self.logger.warning(
                    f" ⚠️ Invalid aspect_ratio '{config_ratio}' in config. "
                    f"Valid options: {self.VALID_ASPECT_RATIOS}. Auto-detecting..."
                )
        
        # Auto-detect from source image
        try:
            with Image.open(file_path) as img:
                width, height = img.size
            
            image_ratio = width / height
            
            # Calculate ratio values for all valid aspect ratios
            best_ratio = self.DEFAULT_ASPECT_RATIO
            best_diff = float('inf')
            
            for ratio_str in self.VALID_ASPECT_RATIOS:
                w, h = map(int, ratio_str.split(':'))
                ratio_value = w / h
                diff = abs(image_ratio - ratio_value)
                
                if diff < best_diff:
                    best_diff = diff
                    best_ratio = ratio_str
            
            self.logger.debug(
                f" 📐 Auto-detected aspect ratio: {best_ratio} "
                f"(image: {width}x{height}, ratio: {image_ratio:.3f})"
            )
            return best_ratio
            
        except Exception as e:
            self.logger.warning(
                f" ⚠️ Failed to detect aspect ratio from {file_path.name}: {e}. "
                f"Using default: {self.DEFAULT_ASPECT_RATIO}"
            )
            return self.DEFAULT_ASPECT_RATIO
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Make Nano Banana API call with multi-image support.
        
        Args:
            file_path: Path to the source image file.
            task_config: Task configuration dictionary.
            attempt: Current attempt number (0-indexed).
        
        Returns:
            tuple: API response tuple (response_id, error_msg, response_data).
        """
        additional_imgs = self._get_additional_images(file_path, task_config)
        
        # Store the additional images used for this specific file (for metadata)
        if not hasattr(self, '_current_additional_images'):
            self._current_additional_images = {}
        self._current_additional_images[str(file_path)] = additional_imgs
        
        # Get model from task config or use default
        model = task_config.get('model', 'gemini-2.5-flash-image')
        
        # Get resolution from task config or use default
        resolution = task_config.get('resolution', '1K')
        
        # Get aspect ratio from config or auto-detect from source image
        aspect_ratio = self._get_aspect_ratio(file_path, task_config)
        
        # Build images list: source image first, then additional images
        images_list = [handle_file(str(file_path))]
        for img_path in additional_imgs:
            if img_path:
                images_list.append(handle_file(img_path))
        
        # Log image count and aspect ratio for debugging
        max_images = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        self.logger.debug(f" 📷 Sending {len(images_list)} images (max {max_images} for {model})")
        self.logger.debug(f" 📐 Using aspect ratio: {aspect_ratio}")
        
        return self.client.predict(
            prompt=task_config['prompt'],
            model=model,
            images=images_list,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Nano Banana API result with multi-image tracking.
        
        Args:
            result: API response tuple (response_id, error_msg, response_data).
            file_path: Path to the source image file.
            task_config: Task configuration dictionary.
            output_folder: Path to save generated outputs.
            metadata_folder: Path to save metadata files.
            base_name: Base name for output files.
            file_name: Original source file name.
            start_time: Processing start timestamp.
            attempt: Current attempt number (0-indexed).
        
        Returns:
            bool: True if processing succeeded, False otherwise.
        """
        response_id, error_msg, response_data = result[:3]
        processing_time = time.time() - start_time
        
        self.logger.info(f" Response ID: {response_id}")
        
        # Get additional images info for metadata
        additional_imgs = getattr(self, '_current_additional_images', {}).get(str(file_path), ['', ''])
        additional_imgs_info = [Path(img).name for img in additional_imgs if img]
        
        # Check for failure patterns in response_data
        is_failed = False
        failure_reason = error_msg if error_msg else None
        has_images_in_response = False
        text_responses_list = []
        all_error_messages = []
        
        # Collect error_msg if present
        if error_msg:
            all_error_messages.append(error_msg)
        
        if response_data and isinstance(response_data, list):
            for item in response_data:
                if isinstance(item, dict):
                    item_data = item.get('data')
                    item_type = item.get('type')
                    
                    # Check for explicit moderation block
                    if item_data == 'BLOCKED_MODERATION':
                        is_failed = True
                        failure_reason = 'BLOCKED_MODERATION'
                        all_error_messages.append('BLOCKED_MODERATION')
                    # Collect all text responses (could be errors or messages)
                    elif item_type == 'Text':
                        text_content = str(item_data) if item_data else ''
                        if text_content:
                            text_responses_list.append(text_content)
                            all_error_messages.append(text_content)
                    # Check for image responses
                    elif item_type == 'Image':
                        has_images_in_response = True
                    # Capture any other unexpected item types
                    else:
                        if item_type or item_data:
                            unknown_msg = f"Unknown response type: {item_type}, data: {item_data}"
                            all_error_messages.append(unknown_msg)
                            self.logger.warning(f" ⚠️ {unknown_msg}")
        
        # Determine failure status and reason
        if text_responses_list and not has_images_in_response:
            is_failed = True
            # Use the most specific error message available
            if not failure_reason:
                # Prefer the first non-empty text response as the failure reason
                failure_reason = text_responses_list[0] if text_responses_list else "Unknown error"
                # Don't add "Error:" prefix if it already looks like an error message
                if not any(failure_reason.lower().startswith(prefix) for prefix in ['error', 'failed', 'blocked', 'invalid']):
                    failure_reason = f"Error: {failure_reason}"
        
        # Early return for explicit failures
        if error_msg or is_failed:
            self.logger.info(f" ❌ API Error: {failure_reason}")
            metadata = {
                'response_id': response_id, 
                'error': failure_reason, 
                'success': False,
                'attempts': attempt + 1, 
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name
            }
            # Include all error messages for comprehensive debugging
            if all_error_messages:
                metadata['all_errors'] = all_error_messages
            # Include text responses in failure metadata for debugging
            if text_responses_list:
                metadata['text_responses'] = text_responses_list
            if additional_imgs_info:
                metadata['additional_images_used'] = additional_imgs_info
            self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name, 
                                             metadata, task_config)
            return False
        
        # Save response data
        saved_files, text_responses = self.processor.save_nano_responses(
            response_data, Path(output_folder), base_name)
        has_images = len(saved_files) > 0
        
        # If no images were saved but we got here, treat as failure
        if not has_images:
            error_reason = "No images generated"
            if text_responses:
                # Extract text content for error message
                text_contents = [tr.get('content', '') for tr in text_responses if isinstance(tr, dict)]
                if text_contents:
                    error_reason = f"Error: {text_contents[0]}"
            
            self.logger.info(f" ❌ {error_reason}")
            metadata = {
                'response_id': response_id,
                'error': error_reason,
                'text_responses': text_responses,
                'success': False,
                'attempts': attempt + 1,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name
            }
            if additional_imgs_info:
                metadata['additional_images_used'] = additional_imgs_info
            self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                             metadata, task_config)
            return False
        
        # Success case - images were generated
        metadata = {
            'response_id': response_id, 
            'saved_files': [Path(f).name for f in saved_files],
            'text_responses': text_responses, 
            'success': True, 
            'attempts': attempt + 1,
            'images_generated': len(saved_files), 
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'api_name': self.api_name
        }
        
        if additional_imgs_info:
            metadata['additional_images_used'] = additional_imgs_info
        
        self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name, 
                                         metadata, task_config)
        
        self.logger.info(f" ✅ Generated: {len(saved_files)} images")
        if additional_imgs_info:
            self.logger.info(f" 🖼️ Additional images: {', '.join(additional_imgs_info)}")
        
        return True
