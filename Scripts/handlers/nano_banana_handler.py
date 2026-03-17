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
    
    Modes:
        - Standard: 1 source image + additional images from Additional folder
        - Random Source Selection: Randomly select N images from Source folder
          (configured via use_random_source_selection, min_images, max_images)
    """
    
    # Maximum images allowed per model
    MODEL_MAX_IMAGES = {
        'gemini-2.5-flash-image': 3,
        'gemini-3-pro-image-preview': 14
    }
    DEFAULT_MAX_IMAGES = 3
    DEFAULT_MIN_IMAGES = 1
    
    # Valid aspect ratios supported by the API
    VALID_ASPECT_RATIOS = [
        'auto', '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9'
    ]
    DEFAULT_ASPECT_RATIO = 'auto'
    
    # Error 429 patterns for Resource Exhausted detection
    ERROR_429_PATTERNS = [
        'Error 429',
        'RESOURCE_EXHAUSTED',
        'Resource exhausted',
    ]
    
    def __init__(self, processor):
        """Initialize handler with multi-image support."""
        super().__init__(processor)
        self._additional_image_pools = {}
        self._used_combinations = set()
        self._source_file_indices = {}  # Track source file index for sequential matching
        self._random_source_selections = {}  # Track random source selections for reproducibility
        self._source_image_cache = {}  # Cache source images per task
        self._last_error_is_429 = False  # Track if last failure was a 429
    
    def _is_error_429(self, error_str):
        """Check if an error string indicates a 429 Resource Exhausted error.

        Args:
            error_str: The error message string to check.

        Returns:
            bool: True if the error matches a 429 pattern.
        """
        if not error_str:
            return False
        error_lower = error_str.lower()
        return any(p.lower() in error_lower for p in self.ERROR_429_PATTERNS)

    def _read_error429_retries(self, base_name, metadata_folder):
        """Read existing error 429 retry count from a metadata file.

        Args:
            base_name: Base name for the metadata file (without suffix).
            metadata_folder: Path to the metadata folder.

        Returns:
            int: The current error429_retries count, or 0 if not found.
        """
        import json
        meta_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        if meta_file.exists():
            try:
                with open(meta_file, 'r') as f:
                    meta = json.load(f)
                return meta.get('error429_retries', 0)
            except (json.JSONDecodeError, IOError):
                pass
        return 0

    def _check_metadata_status(self, metadata):
        """Check completion status from loaded metadata dict.

        Handles both normal retry exhaustion and 429-specific retry limits.

        Args:
            metadata: Metadata dictionary loaded from a metadata JSON file.

        Returns:
            tuple: (is_complete, status_reason) where:
                - is_complete: True if file/iteration should be skipped
                - status_reason: 'success', 'failed_exhausted',
                  'failed_error429_exhausted', or None if not complete
        """
        if metadata.get('success', False):
            return True, 'success'

        # Check for 429 error with separate retry limit
        error = str(metadata.get('error', ''))
        all_errors = ' '.join(str(e) for e in metadata.get('all_errors', []))
        if self._is_error_429(error) or self._is_error_429(all_errors):
            max_429 = self.api_defs.get('max_retries_error429', 0)
            if max_429 > 0:
                if metadata.get('error429_retries', 0) >= max_429:
                    return True, 'failed_error429_exhausted'
                return False, None

        # Normal retry exhaustion check
        max_retries = self.api_defs.get('max_retries', 3)
        if metadata.get('attempts', 0) >= max_retries:
            return True, 'failed_exhausted'

        return False, None

    def _load_image_pools(self, task_config, max_additional=None):
        """Load and cache image pools from additional folders.
        
        Args:
            task_config: Task configuration dictionary containing multi_image_config.
            max_additional: Maximum number of additional images to use.
        
        Returns:
            dict: Pool data with 'pools', 'mode', and 'allow_duplicates' keys,
                  or None if multi-image is not configured.
        """
        multi_image_config = task_config.get('multi_image_config', {})
        
        # Auto-detect Additional folder if use_multi_image is true but no explicit config
        if not multi_image_config or not multi_image_config.get('enabled', False):
            # Check for simple multi_image mode with auto-detected Additional folder
            if task_config.get('use_multi_image', False):
                task_folder = Path(task_config.get('folder', ''))
                additional_folder = task_folder / 'Additional'
                if additional_folder.exists():
                    self.logger.info(f" 📂 Auto-detected Additional folder for multi-image mode")
                    # Create implicit config for auto-detected folder
                    multi_image_config = {
                        'enabled': True,
                        'mode': 'sequential',  # Default to sequential for predictable pairing
                        'folders': [str(additional_folder)],
                        'allow_duplicates': True
                    }
                else:
                    return None
            else:
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
        
        # Check for user-specified multi_image_count (limits additional images)
        # multi_image_count specifies TOTAL images including source
        # e.g., multi_image_count: 2 means 1 source + 1 additional
        user_count = task_config.get('multi_image_count', 0)
        if user_count > 0:
            # Validate against model limit
            if user_count > max_images:
                self.logger.warning(
                    f" ⚠️ multi_image_count ({user_count}) exceeds model limit ({max_images}). "
                    f"Using model limit."
                )
                user_count = max_images
            max_additional = user_count - 1  # -1 for source image
        
        # Check if multi-image is explicitly disabled
        if not task_config.get('use_multi_image', True):
            return []
        
        # If multi_image_count is 1 or less, no additional images needed
        if user_count == 1:
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
            return result[:max_additional]
        
        # Check for multi-image configuration
        pool_data = self._load_image_pools(task_config, max_additional)
        if not pool_data or not pool_data['pools']:
            return []
        
        pools = pool_data['pools']
        mode = pool_data['mode']
        allow_duplicates = pool_data['allow_duplicates']
        
        # Limit pools to max_additional count
        effective_max = max_additional if max_additional else len(pools)
        
        if mode == 'random_pairing':
            return self._random_pairing(pools, file_path, allow_duplicates, effective_max)
        elif mode == 'sequential':
            return self._sequential_selection(pools, file_path, effective_max)
        else:
            self.logger.warning(f" ⚠️ Unknown mode '{mode}', using random_pairing")
            return self._random_pairing(pools, file_path, allow_duplicates, effective_max)
    
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
    
    def _get_source_images_for_task(self, task_config):
        """Get and cache all source images for a task.
        
        Args:
            task_config: Task configuration dictionary.
        
        Returns:
            list: Sorted list of Path objects for source images.
        """
        task_key = str(task_config.get('folder', ''))
        
        if task_key not in self._source_image_cache:
            source_folder = Path(task_config.get('folder', '')) / "Source"
            if source_folder.exists():
                images = self.processor._get_files_by_type(source_folder, 'image')
                images = sorted(images, key=lambda x: x.name.lower())
                self._source_image_cache[task_key] = images
                self.logger.info(f" 📂 Cached {len(images)} source images for random selection")
            else:
                self._source_image_cache[task_key] = []
                self.logger.warning(f" ⚠️ Source folder not found: {source_folder}")
        
        return self._source_image_cache[task_key]
    
    def _build_selection_plan(self, task_config):
        """Pre-build the complete selection plan for all iterations.
        
        Two modes based on 'use_deterministic_random' option:
        1. Sequential (default): Sorted alphabetically, consumed sequentially
        2. Deterministic Random: Shuffled with seed, appears random but reproducible
        
        Both modes:
        - Pre-calculate image count for each iteration (even bucket distribution)
        - No repeats until pool exhausted, then restart from beginning
        - Same folder + same config = same selection plan every time
        
        Optimal formula: total_needed = num_iterations × (min + max) / 2
        
        Args:
            task_config: Task configuration dictionary.
        
        Returns:
            list: List of lists, where each inner list contains Path objects
                  for that iteration's selected images.
        """
        task_key = str(task_config.get('folder', ''))
        
        # Get model limits
        model = task_config.get('model', 'gemini-2.5-flash-image')
        model_max = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        
        # Get configured min/max images
        min_images = task_config.get('min_images', self.DEFAULT_MIN_IMAGES)
        max_images = task_config.get('max_images', model_max)
        
        # Validate and clamp to model limits
        min_images = max(1, min(min_images, model_max))
        max_images = max(min_images, min(max_images, model_max))
        
        # Get all source images (sorted deterministically)
        source_images = self._get_source_images_for_task(task_config)
        total_available = len(source_images)
        
        if not source_images:
            return []
        
        # Clamp max to available images
        max_images = min(max_images, total_available)
        min_images = min(min_images, max_images)
        
        # Get num_iterations
        num_iterations = task_config.get('num_iterations', 0)
        if num_iterations <= 0:
            num_iterations = total_available
        
        # Pre-calculate image counts for each iteration (even bucket distribution)
        iteration_counts = []
        for iteration_index in range(num_iterations):
            if num_iterations <= 1:
                num_images = max_images
            elif min_images == max_images:
                num_images = min_images
            else:
                num_counts = max_images - min_images + 1
                bucket = (iteration_index * num_counts) // num_iterations
                bucket = min(bucket, num_counts - 1)
                num_images = min_images + bucket
            iteration_counts.append(num_images)
        
        # Calculate total images needed
        total_needed = sum(iteration_counts)
        
        # Check if deterministic random mode is enabled
        use_deterministic_random = task_config.get('use_deterministic_random', False)
        random_seed = task_config.get('random_seed', None)
        
        # Determine selection mode for logging
        if use_deterministic_random:
            # Determine seed for deterministic shuffling
            if random_seed is not None:
                # Use explicit seed from config
                seed = int(random_seed)
                self.logger.info(f" 🎲 Using deterministic random mode with seed: {seed}")
            else:
                # Auto-generate seed from folder path for consistency
                seed = abs(hash(task_key)) % (2**32)
                self.logger.info(f" 🎲 Using deterministic random mode (auto-seed: {seed})")
            
            selection_mode = f'deterministic_random_seed_{seed}'
        else:
            selection_mode = 'sequential_sorted'
            self.logger.info(f" 📝 Using sequential sorted mode")
        
        # Log optimization info
        if total_needed <= total_available:
            self.logger.info(
                f" ✅ Optimal selection: {total_needed} images needed, "
                f"{total_available} available (no repeats)"
            )
        else:
            cycles = (total_needed + total_available - 1) // total_available
            self.logger.warning(
                f" ⚠️ {total_needed} images needed but only {total_available} available. "
                f"Images will repeat across {cycles} cycles."
            )
        
        # Prepare source pool based on mode
        if use_deterministic_random:
            # Shuffle with deterministic seed
            source_pool = source_images[:]
            random.seed(seed)
            random.shuffle(source_pool)
            self.logger.debug(f" 🔀 Shuffled source pool with seed {seed}")
        else:
            # Use sorted list (already sorted from _get_source_images_for_task)
            source_pool = source_images[:]
        
        # Build selection plan by consuming from pool sequentially
        selection_plan = []
        available_pool = []
        
        for iteration_index in range(num_iterations):
            num_images = iteration_counts[iteration_index]
            
            # Refill pool if needed
            if len(available_pool) < num_images:
                if use_deterministic_random:
                    # Re-shuffle with same seed for consistent repeats
                    temp_pool = source_images[:]
                    random.seed(seed)
                    random.shuffle(temp_pool)
                    available_pool.extend(temp_pool)
                else:
                    # Use sorted source images
                    available_pool.extend(source_images[:])
            
            # Consume images from pool (no repeats within cycle)
            selected = available_pool[:num_images]
            available_pool = available_pool[num_images:]
            
            # Sort selected images for consistent API input ordering
            selected = sorted(selected, key=lambda x: x.name.lower())
            selection_plan.append(selected)
        
        # Store selection mode for metadata tracking
        if not hasattr(self, '_selection_modes'):
            self._selection_modes = {}
        self._selection_modes[task_key] = selection_mode
        
        return selection_plan
    
    def _get_random_source_selection(self, task_config, iteration_index):
        """Deterministically select N images from Source folder for an API call.
        
        Uses sorted list consumption approach for consistent selection:
        - Pre-builds complete selection plan on first call
        - Each iteration gets unique images (until pool exhausted)
        - Fully deterministic: same folder + same config = same selection every time
        - Images are consumed in alphabetical filename order
        
        Optimal formula: sources_needed = num_iterations × (min + max) / 2
        
        Args:
            task_config: Task configuration dictionary containing:
                - min_images: Minimum images per call (default: 1)
                - max_images: Maximum images per call (default: model max)
                - num_iterations: Optional number of API calls to make
            iteration_index: 0-based iteration index.
        
        Returns:
            list: List of selected image Path objects.
        """
        task_key = str(task_config.get('folder', ''))
        
        # Build selection plan on first call for this task
        if not hasattr(self, '_selection_plans'):
            self._selection_plans = {}
        
        if task_key not in self._selection_plans:
            self._selection_plans[task_key] = self._build_selection_plan(task_config)
        
        selection_plan = self._selection_plans[task_key]
        
        if not selection_plan:
            self.logger.error(f" ❌ No source images found for selection")
            return []
        
        # Get pre-computed selection for this iteration
        if iteration_index >= len(selection_plan):
            self.logger.error(
                f" ❌ Iteration {iteration_index} exceeds plan size {len(selection_plan)}"
            )
            return []
        
        selected = selection_plan[iteration_index]
        
        # Get config values for logging
        model = task_config.get('model', 'gemini-2.5-flash-image')
        model_max = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        min_images = max(1, min(task_config.get('min_images', self.DEFAULT_MIN_IMAGES), model_max))
        max_images = max(min_images, min(task_config.get('max_images', model_max), model_max))
        num_iterations = task_config.get('num_iterations', 0) or len(self._get_source_images_for_task(task_config))
        num_images = len(selected)
        
        # Initialize tracking for this task if needed
        if task_key not in self._random_source_selections:
            self._random_source_selections[task_key] = []
        
        # Get selection mode from stored value
        selection_mode = getattr(self, '_selection_modes', {}).get(task_key, 'sequential_sorted')
        
        # Record selection for reproducibility
        selection_record = {
            'iteration_index': iteration_index,
            'num_iterations': num_iterations,
            'num_images': num_images,
            'selected_files': [img.name for img in selected],
            'min_images': min_images,
            'max_images': max_images,
            'selection_mode': selection_mode,
            'use_deterministic_random': task_config.get('use_deterministic_random', False),
            'random_seed': task_config.get('random_seed'),
            'timestamp': datetime.now().isoformat()
        }
        self._random_source_selections[task_key].append(selection_record)
        
        # Calculate iterations per bucket for logging
        num_counts = max_images - min_images + 1
        iters_per_bucket = num_iterations // num_counts
        current_bucket = (iteration_index * num_counts) // num_iterations
        
        self.logger.info(
            f" 📊 Iteration {iteration_index + 1}/{num_iterations}: {num_images} images "
            f"(bucket {current_bucket + 1}/{num_counts}, ~{iters_per_bucket} iters each)"
        )
        self.logger.debug(f" 📋 Selected: {[img.name for img in selected]}")
        
        return selected
    
    def get_random_selection_log(self, task_config):
        """Get the log of all random selections made for a task.
        
        Useful for reproducing results or debugging.
        
        Args:
            task_config: Task configuration dictionary.
        
        Returns:
            list: List of selection records with call_index, files, and timestamps.
        """
        task_key = str(task_config.get('folder', ''))
        return self._random_source_selections.get(task_key, [])
    
    def process_task(self, task, task_num, total_tasks):
        """Process task - handles both standard and random source selection modes.
        
        If use_random_source_selection is enabled:
        - Uses iteration-based processing with deterministic spread
        - num_iterations defaults to number of source files if not specified
        
        Otherwise uses standard file-by-file processing.
        
        Args:
            task: Task configuration dictionary.
            task_num: Current task number (for logging).
            total_tasks: Total number of tasks (for logging).
        """
        folder = Path(task.get('folder', ''))
        output_folder = folder / "Generated_Output"
        metadata_folder = folder / "Metadata"
        
        use_random_source = task.get('use_random_source_selection', False)
        
        if use_random_source:
            # Random source selection mode - always use iteration-based processing
            # Default num_iterations to number of source files if not specified
            source_images = self._get_source_images_for_task(task)
            num_iterations = task.get('num_iterations') or len(source_images)
            
            if num_iterations <= 0:
                self.logger.warning(f" ⚠️ No source images found, skipping task")
                return
            
            # Update task with resolved num_iterations
            task_with_iterations = task.copy()
            task_with_iterations['num_iterations'] = num_iterations
            
            self._process_iterations(task_with_iterations, task_num, total_tasks, 
                                    output_folder, metadata_folder)
        else:
            # Use standard file-by-file processing from base class
            super().process_task(task, task_num, total_tasks)
    
    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single file with iteration-based naming support.
        
        Overrides base class to support custom base_name from iteration mode.
        
        Args:
            file_path: Path to the source file.
            task_config: Task configuration dictionary.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.
        
        Returns:
            bool: True if processing succeeded, False otherwise.
        """
        # Use custom base_name if provided (from iteration mode)
        base_name = task_config.get('_base_name') or Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()
        self._last_error_is_429 = False
        
        try:
            # Make API-specific call with connection retry wrapper
            result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
            
            # Parse and save result
            success = self._handle_result(result, file_path, task_config, output_folder,
                                         metadata_folder, base_name, file_name, start_time, attempt)
            
            # Retry loop for 429 Resource Exhausted errors (independent of max_retries)
            max_429 = self.api_defs.get('max_retries_error429', 0)
            while not success and self._last_error_is_429 and max_429 > 0:
                count = self._read_error429_retries(base_name, metadata_folder)
                if count >= max_429:
                    self.logger.info(f" ⏭️ 429 retry limit reached ({count}/{max_429})")
                    break
                self.logger.info(f" ⏳ 429 retry {count}/{max_429} (waiting {30 * count}s)")
                time.sleep(30 * count)
                self._last_error_is_429 = False
                start_time = time.time()
                try:
                    result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
                    success = self._handle_result(result, file_path, task_config, output_folder,
                                                 metadata_folder, base_name, file_name, start_time, attempt)
                except Exception:
                    break
            
            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False
            
            return success
            
        except Exception as e:
            self.logger.error(f" ❌ Error processing {base_name}: {e}")
            # Save failure metadata so every attempt produces a metadata file
            processing_time = time.time() - start_time
            use_random_source = task_config.get('use_random_source_selection', False)
            all_imgs = getattr(self, '_current_all_images', {}).get(str(file_path), [])
            all_imgs_info = [Path(img).name for img in all_imgs if img]
            additional_imgs = getattr(self, '_current_additional_images', {}).get(str(file_path), [])
            additional_imgs_info = [Path(img).name for img in additional_imgs if img]
            error_str = str(e)

            metadata = {
                'error': error_str,
                'success': False,
                'attempts': attempt + 1,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name
            }
            if self._is_error_429(error_str):
                self._last_error_is_429 = True
                metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
            if use_random_source and all_imgs_info:
                metadata['all_images_used'] = all_imgs_info
                metadata['random_source_selection'] = True
            elif additional_imgs_info:
                metadata['additional_images_used'] = additional_imgs_info

            self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                             metadata, task_config)
            raise
    
    def _process_iterations(self, task, task_num, total_tasks, output_folder, metadata_folder):
        """Process task using iteration-based loop (for num_iterations mode).
        
        Args:
            task: Task configuration dictionary.
            task_num: Current task number.
            total_tasks: Total number of tasks.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
        """
        task_name = Path(task.get('folder', '')).name
        num_iterations = task.get('num_iterations', 1)
        source_images = self._get_source_images_for_task(task)
        min_images = task.get('min_images', self.DEFAULT_MIN_IMAGES)
        max_images = task.get('max_images', self.MODEL_MAX_IMAGES.get(
            task.get('model', 'gemini-2.5-flash-image'), self.DEFAULT_MAX_IMAGES))
        
        self.logger.info(
            f"📁 Task {task_num}/{total_tasks}: {task_name} "
            f"({num_iterations} iterations, {len(source_images)} source images, "
            f"images per call: {min_images}-{max_images})"
        )
        
        successful = 0
        skipped = 0
        max_retries = self.api_defs.get('max_retries', 3)
        
        # Pre-build selection plan to get actual selected images for naming
        task_key = str(task.get('folder', ''))
        if not hasattr(self, '_selection_plans'):
            self._selection_plans = {}
        if task_key not in self._selection_plans:
            self._selection_plans[task_key] = self._build_selection_plan(task)
        selection_plan = self._selection_plans.get(task_key, [])
        
        for iteration_idx in range(num_iterations):
            # Get the actual selected images for this iteration from pre-built plan
            selected_images = selection_plan[iteration_idx] if iteration_idx < len(selection_plan) else []
            
            if not selected_images:
                self.logger.warning(f" ⚠️ No source images for iteration {iteration_idx}")
                continue
            
            # Create unique identifier based on actual selected image names
            # Use first selected image as primary, include count if multiple
            primary_image = selected_images[0]
            if len(selected_images) == 1:
                base_name = f"iter{iteration_idx:03d}_{primary_image.stem}"
            else:
                # Include all image names for multi-image selections
                image_names = "_".join([img.stem for img in selected_images])
                # Truncate if too long (max 200 chars for filename safety)
                if len(image_names) > 150:
                    image_names = image_names[:147] + "..."
                base_name = f"iter{iteration_idx:03d}_{image_names}"
            
            # Check if already processed (success or failed with exhausted retries)
            is_complete, status = self._get_iteration_status(base_name, metadata_folder)
            if is_complete:
                if status == 'success':
                    self.logger.info(f" ⏭️ {iteration_idx+1}/{num_iterations}: {base_name} (already processed)")
                    successful += 1
                elif status == 'failed_error429_exhausted':
                    self.logger.info(f" ⏭️ {iteration_idx+1}/{num_iterations}: {base_name} (failed - 429 retries exhausted)")
                else:  # failed_exhausted
                    self.logger.info(f" ⏭️ {iteration_idx+1}/{num_iterations}: {base_name} (failed - max retries reached)")
                skipped += 1
                continue
            
            self.logger.info(f" 🎲 {iteration_idx+1}/{num_iterations}: Processing iteration {iteration_idx}")
            
            # Inject iteration_index and base_name into task config
            task_with_iteration = task.copy()
            task_with_iteration['_iteration_index'] = iteration_idx
            task_with_iteration['_base_name'] = base_name
            
            # Process with retries
            for attempt in range(max_retries):
                try:
                    success = self.process(
                        primary_image,
                        task_with_iteration,
                        output_folder,
                        metadata_folder,
                        attempt,
                        max_retries
                    )
                    if success:
                        successful += 1
                        break
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f" ⚠️ Attempt {attempt+1} failed: {e}")
                        time.sleep(5)
                    else:
                        self.logger.error(f" ❌ All {max_retries} attempts failed: {e}")
            
            # Rate limit — scale proportionally by number of images used
            if iteration_idx < num_iterations - 1:
                base_rate = self.api_defs.get('rate_limit', 3)
                num_images_used = len(selected_images)
                effective_max = max_images if max_images > 0 else 1
                scaled_wait = max(1, base_rate * num_images_used / effective_max)
                self.logger.info(f" ⏳ Rate limit: {scaled_wait:.0f}s ({num_images_used}/{effective_max} images)")
                time.sleep(scaled_wait)
        
        self.logger.info(
            f"✓ Task {task_num}: {successful}/{num_iterations} successful ({skipped} skipped)"
        )
    
    def _get_iteration_status(self, base_name, metadata_folder):
        """Get detailed processing status for an iteration.
        
        Args:
            base_name: Base name for the iteration.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            tuple: (is_complete, status_reason) where:
                - is_complete: True if iteration should be skipped
                - status_reason: 'success', 'failed_exhausted', or None if not complete
        """
        import json
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                return self._check_metadata_status(metadata)
            except (json.JSONDecodeError, IOError):
                return False, None
        return False, None
    
    def _get_processing_status(self, file_path, metadata_folder):
        """Get processing status with 429 error awareness.

        Overrides base class to check for 429 errors with their own retry limit.

        Args:
            file_path: Path to the source file.
            metadata_folder: Path to the metadata folder.

        Returns:
            tuple: (is_complete, status_reason)
        """
        import json
        base_name = Path(file_path).stem
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"

        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                return self._check_metadata_status(metadata)
            except (json.JSONDecodeError, IOError):
                return False, None
        return False, None
    
    def _is_iteration_processed(self, base_name, metadata_folder):
        """Check if an iteration has already been processed (success or exhausted retries).
        
        An iteration is considered processed if:
        - It was successfully processed (success: True), OR
        - It failed but has exhausted all retry attempts (success: False, attempts >= max_retries)
        """
        is_complete, _ = self._get_iteration_status(base_name, metadata_folder)
        return is_complete
    
    def _get_aspect_ratio(self, file_path, task_config):
        """Determine aspect ratio from config or use 'auto' as default.
        
        If aspect_ratio is specified in task_config, validates and uses it.
        Otherwise, returns 'auto' to let the API determine the best ratio.
        
        Args:
            file_path: Path to the source image file.
            task_config: Task configuration dictionary.
        
        Returns:
            str: Valid aspect ratio string (e.g., '16:9', '1:1', 'auto').
        """
        # Check if aspect_ratio is specified in config (handle null/empty values)
        config_ratio = str(task_config.get('aspect_ratio') or '')
        if config_ratio:
            if config_ratio in self.VALID_ASPECT_RATIOS:
                return config_ratio
            else:
                self.logger.warning(
                    f" ⚠️ Invalid aspect_ratio '{config_ratio}' in config. "
                    f"Valid options: {self.VALID_ASPECT_RATIOS}. Using default: {self.DEFAULT_ASPECT_RATIO}"
                )
        
        # Return default 'auto' to let API determine best ratio
        return self.DEFAULT_ASPECT_RATIO
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Make Nano Banana API call with multi-image support.
        
        Supports two modes:
        1. Standard mode: 1 source image (file_path) + additional images from Additional folder
        2. Random source selection mode: Randomly select N images from Source folder
           (use_random_source_selection: true in config)
        
        Args:
            file_path: Path to the source image file (used as primary in standard mode,
                      or as call identifier in random source selection mode).
            task_config: Task configuration dictionary.
            attempt: Current attempt number (0-indexed).
        
        Returns:
            tuple: API response tuple (response_id, error_msg, response_data).
        """
        # Initialize tracking dict if needed
        if not hasattr(self, '_current_additional_images'):
            self._current_additional_images = {}
        if not hasattr(self, '_current_all_images'):
            self._current_all_images = {}
        
        # Get model from task config or use default
        model = task_config.get('model', 'gemini-2.5-flash-image')
        
        # Get resolution from task config or use default (ensure it's a string)
        # Handle null/empty values by defaulting to '1K'
        resolution = str(task_config.get('resolution') or '1K')
        
        # Check if using random source selection mode
        use_random_source = task_config.get('use_random_source_selection', False)
        
        if use_random_source:
            # Random source selection mode: select N images from Source folder
            # Use injected _iteration_index if available, otherwise find from file position
            iteration_index = task_config.get('_iteration_index')
            
            if iteration_index is None:
                # Fallback: find iteration index from file position
                source_images = self._get_source_images_for_task(task_config)
                try:
                    iteration_index = next(
                        i for i, img in enumerate(source_images) 
                        if str(img) == str(file_path)
                    )
                except StopIteration:
                    iteration_index = 0
            
            selected_images = self._get_random_source_selection(task_config, iteration_index)
            
            if not selected_images:
                self.logger.error(" ❌ No images selected for API call")
                return (None, "No images selected", [])
            
            # Store all selected images for metadata
            self._current_all_images[str(file_path)] = [str(img) for img in selected_images]
            self._current_additional_images[str(file_path)] = []  # No "additional" in this mode
            
            # Build images list from random selection
            # Use handle_file for each image to properly upload to Gradio API
            images_list = [handle_file(str(img)) for img in selected_images]
            
            # Log the number of images being sent
            self.logger.info(f" 📷 Sending {len(images_list)} images to API: {[img.name for img in selected_images]}")
            
            # Use first selected image for aspect ratio detection
            aspect_ratio = str(self._get_aspect_ratio(selected_images[0], task_config))
        else:
            # Standard mode: source image + additional images
            additional_imgs = self._get_additional_images(file_path, task_config)
            
            # Store for metadata
            self._current_additional_images[str(file_path)] = additional_imgs
            self._current_all_images[str(file_path)] = [str(file_path)] + additional_imgs
            
            # Build images list: source image first, then additional images
            images_list = [handle_file(str(file_path))]
            for img_path in additional_imgs:
                if img_path:
                    images_list.append(handle_file(img_path))
            
            # Get aspect ratio from config or auto-detect from source image
            aspect_ratio = str(self._get_aspect_ratio(file_path, task_config))
        
        # Log image count and aspect ratio for debugging
        max_images = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        self.logger.debug(f" 📷 Sending {len(images_list)} images (max {max_images} for {model})")
        self.logger.debug(f" 📐 Using aspect ratio: {aspect_ratio}")
        prompt = task_config['prompt']
        
        return self.client.predict(
            prompt=prompt,
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
        
        # Check if using random source selection mode
        use_random_source = task_config.get('use_random_source_selection', False)
        
        # Get images info for metadata
        additional_imgs = getattr(self, '_current_additional_images', {}).get(str(file_path), [])
        additional_imgs_info = [Path(img).name for img in additional_imgs if img]
        
        # Get all images used (for random source selection mode)
        all_imgs = getattr(self, '_current_all_images', {}).get(str(file_path), [])
        all_imgs_info = [Path(img).name for img in all_imgs if img]
        
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
        
        # If response_data is empty or no content parts found
        if not response_data or (isinstance(response_data, list) and len(response_data) == 0):
            is_failed = True
            if not failure_reason:
                failure_reason = "No content parts in response"
                all_error_messages.append(failure_reason)
        
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
            # Log the failure with text responses if available
            if text_responses_list:
                self.logger.info(f" ❌ API Error: {failure_reason}")
                self.logger.info(f" 📝 Text response: {text_responses_list[0][:200]}")  # Show first 200 chars
            else:
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
            # Track 429 error retries for cross-run persistence
            combined_errors = str(failure_reason or '') + ' '.join(str(e) for e in all_error_messages)
            if self._is_error_429(combined_errors):
                self._last_error_is_429 = True
                metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
            if use_random_source and all_imgs_info:
                metadata['all_images_used'] = all_imgs_info
                metadata['random_source_selection'] = True
            elif additional_imgs_info:
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
            # Check if we have text responses captured earlier
            if text_responses_list:
                # Use text from earlier parsing (more reliable)
                error_reason = f"{text_responses_list[0]}"
                if not any(error_reason.lower().startswith(prefix) for prefix in ['error', 'failed', 'blocked', 'invalid']):
                    error_reason = f"Error: {error_reason}"
            elif text_responses:
                # Fallback: extract text content from processor's parsed responses
                text_contents = [tr.get('content', '') for tr in text_responses if isinstance(tr, dict)]
                if text_contents:
                    error_reason = text_contents[0]
                    if not any(error_reason.lower().startswith(prefix) for prefix in ['error', 'failed', 'blocked', 'invalid']):
                        error_reason = f"Error: {error_reason}"
            
            self.logger.info(f" ❌ {error_reason}")
            if text_responses_list and len(text_responses_list[0]) > 100:
                # Log longer text responses
                self.logger.info(f" 📝 Full text response: {text_responses_list[0]}")
            
            metadata = {
                'response_id': response_id,
                'error': error_reason,
                'success': False,
                'attempts': attempt + 1,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name
            }
            # Include text responses for debugging - use the more reliable source
            if text_responses_list:
                metadata['text_responses'] = text_responses_list
            elif text_responses:
                metadata['text_responses'] = text_responses
            # Track 429 error retries for cross-run persistence
            if self._is_error_429(error_reason):
                self._last_error_is_429 = True
                metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
            if use_random_source and all_imgs_info:
                metadata['all_images_used'] = all_imgs_info
                metadata['random_source_selection'] = True
            elif additional_imgs_info:
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
        
        if use_random_source and all_imgs_info:
            metadata['all_images_used'] = all_imgs_info
            metadata['random_source_selection'] = True
            metadata['min_images'] = task_config.get('min_images', self.DEFAULT_MIN_IMAGES)
            metadata['max_images'] = task_config.get('max_images', 
                self.MODEL_MAX_IMAGES.get(task_config.get('model', 'gemini-2.5-flash-image'), self.DEFAULT_MAX_IMAGES))
        elif additional_imgs_info:
            metadata['additional_images_used'] = additional_imgs_info
        
        self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name, 
                                         metadata, task_config)
        
        self.logger.info(f" ✅ Generated: {len(saved_files)} images")
        if use_random_source and all_imgs_info:
            self.logger.info(f" 🖼️ Input images ({len(all_imgs_info)}): {', '.join(all_imgs_info)}")
        elif additional_imgs_info:
            self.logger.info(f" 🖼️ Additional images: {', '.join(additional_imgs_info)}")
        
        return True
