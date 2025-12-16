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
        '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4', '9:16', '16:9', '21:9'
    ]
    DEFAULT_ASPECT_RATIO = '1:1'
    
    def __init__(self, processor):
        """Initialize handler with multi-image support."""
        super().__init__(processor)
        self._additional_image_pools = {}
        self._used_combinations = set()
        self._source_file_indices = {}  # Track source file index for sequential matching
        self._random_source_selections = {}  # Track random source selections for reproducibility
        self._source_image_cache = {}  # Cache source images per task
        self._iteration_partitions = {}  # Pre-computed partitions for each task
    
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
    
    def _get_random_source_selection(self, task_config, iteration_index):
        """Select a unique, non-overlapping subset of images for an API call.
        
        Pre-partitions all source images into unique groups (computed once per task).
        Each iteration gets its own dedicated subset - no image reuse across iterations.
        
        Partition strategy:
        - Image counts spread evenly from min_images to max_images
        - Images assigned sequentially to each partition (no overlap)
        - Deterministic: same folder + same config = same partitions every run
        
        Example with 30 source images, num_iterations=10, min=1, max=5:
            Iteration 0: images [0]           (1 image)
            Iteration 1: images [1]           (1 image)  
            Iteration 2: images [2, 3]        (2 images)
            Iteration 3: images [4, 5]        (2 images)
            ...
            Iteration 9: images [25-29]       (5 images)
        
        Args:
            task_config: Task configuration dictionary containing:
                - min_images: Minimum images per call (default: 1)
                - max_images: Maximum images per call (default: model max)
                - num_iterations: Number of API calls to make
            iteration_index: 0-based iteration index.
        
        Returns:
            list: List of unique image Path objects for this iteration.
        """
        task_key = str(task_config.get('folder', ''))
        
        # Check if partitions already computed for this task
        if task_key not in self._iteration_partitions:
            self._compute_partitions(task_config)
        
        partitions = self._iteration_partitions.get(task_key, [])
        
        if iteration_index >= len(partitions):
            self.logger.error(
                f" ❌ Iteration {iteration_index} exceeds partition count ({len(partitions)})"
            )
            return []
        
        selected = partitions[iteration_index]
        
        # Initialize tracking for this task if needed
        if task_key not in self._random_source_selections:
            self._random_source_selections[task_key] = []
        
        # Record selection
        selection_record = {
            'iteration_index': iteration_index,
            'num_images': len(selected),
            'selected_files': [img.name for img in selected],
            'selection_mode': 'unique_partition',
            'timestamp': datetime.now().isoformat()
        }
        self._random_source_selections[task_key].append(selection_record)
        
        self.logger.info(
            f" 📊 Iteration {iteration_index}/{len(partitions)-1}: {len(selected)} unique images"
        )
        self.logger.debug(f" 📋 Selected: {[img.name for img in selected]}")
        
        return selected
    
    def _compute_partitions(self, task_config):
        """Pre-compute unique, non-overlapping image partitions for all iterations.
        
        Distributes source images across num_iterations groups with sizes
        spreading from min_images to max_images. Each image is used exactly once.
        
        Args:
            task_config: Task configuration with min_images, max_images, num_iterations.
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
        total_images = len(source_images)
        
        if total_images == 0:
            self.logger.error(f" ❌ No source images found for partitioning")
            self._iteration_partitions[task_key] = []
            return
        
        # Get num_iterations from config, or calculate based on available images
        num_iterations = task_config.get('num_iterations', 0)
        
        if num_iterations <= 0:
            # Auto-calculate: how many iterations can we do with unique images?
            # Use average of min and max as typical partition size
            avg_size = (min_images + max_images) / 2
            num_iterations = max(1, int(total_images / avg_size))
            self.logger.info(
                f" 🔢 Auto-calculated num_iterations={num_iterations} "
                f"(from {total_images} images, avg {avg_size:.1f} per call)"
            )
        
        # Calculate partition sizes (spread from min to max)
        partition_sizes = []
        for i in range(num_iterations):
            if num_iterations == 1:
                size = min_images
            else:
                # Linear interpolation from min to max
                ratio = i / (num_iterations - 1)
                size = int(min_images + ratio * (max_images - min_images))
            partition_sizes.append(size)
        
        # Check if we have enough images
        total_needed = sum(partition_sizes)
        if total_needed > total_images:
            self.logger.warning(
                f" ⚠️ Not enough images: need {total_needed}, have {total_images}. "
                f"Reducing num_iterations..."
            )
            # Recalculate with fewer iterations
            while total_needed > total_images and num_iterations > 1:
                num_iterations -= 1
                partition_sizes = []
                for i in range(num_iterations):
                    if num_iterations == 1:
                        size = min_images
                    else:
                        ratio = i / (num_iterations - 1)
                        size = int(min_images + ratio * (max_images - min_images))
                    partition_sizes.append(size)
                total_needed = sum(partition_sizes)
            
            self.logger.info(f" 📉 Adjusted to {num_iterations} iterations (using {total_needed} images)")
        
        # Build partitions
        partitions = []
        image_index = 0
        
        for size in partition_sizes:
            if image_index >= total_images:
                break
            
            # Take 'size' images starting at image_index
            end_index = min(image_index + size, total_images)
            partition = source_images[image_index:end_index]
            partitions.append(partition)
            image_index = end_index
        
        self._iteration_partitions[task_key] = partitions
        
        # Log partition summary
        self.logger.info(
            f" 📦 Created {len(partitions)} partitions from {total_images} images:"
        )
        for i, p in enumerate(partitions[:5]):  # Show first 5
            self.logger.info(f"    Iteration {i}: {len(p)} images → {[img.name for img in p]}")
        if len(partitions) > 5:
            self.logger.info(f"    ... and {len(partitions) - 5} more partitions")
    
    def get_iteration_count(self, task_config):
        """Get the number of iterations (API calls) for a task.
        
        Call this to determine how many times to call process() for this task
        when using random source selection mode.
        
        Args:
            task_config: Task configuration dictionary.
        
        Returns:
            int: Number of iterations, or 0 if not using random source selection.
        """
        if not task_config.get('use_random_source_selection', False):
            return 0
        
        task_key = str(task_config.get('folder', ''))
        
        # Compute partitions if not already done
        if task_key not in self._iteration_partitions:
            self._compute_partitions(task_config)
        
        return len(self._iteration_partitions.get(task_key, []))
    
    def process_random_source_task(self, task, task_num, total_tasks, output_folder, metadata_folder):
        """Process a task using random source selection mode.
        
        Instead of iterating over each source file, this method:
        1. Pre-partitions all source images into unique groups
        2. Makes one API call per partition with its unique image set
        3. Each image is used exactly once across all API calls
        
        Args:
            task: Task configuration dictionary.
            task_num: Current task number (for logging).
            total_tasks: Total number of tasks (for logging).
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
        
        Returns:
            int: Number of successful API calls.
        """
        task_name = Path(task.get('folder', '')).name
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {task_name} (Random Source Selection)")
        
        # Get iteration count (also triggers partition computation)
        num_iterations = self.get_iteration_count(task)
        
        if num_iterations == 0:
            self.logger.warning(" ⚠️ No iterations computed - check source folder")
            return 0
        
        task_key = str(task.get('folder', ''))
        partitions = self._iteration_partitions.get(task_key, [])
        
        successful = 0
        skipped = 0
        max_retries = self.api_defs.get('max_retries', 3)
        
        for iteration_idx, partition in enumerate(partitions):
            # Create a unique identifier for this iteration (for metadata naming)
            # Use first image in partition as the "anchor" for naming
            anchor_file = partition[0] if partition else None
            
            if not anchor_file:
                self.logger.warning(f" ⚠️ Empty partition at iteration {iteration_idx}")
                continue
            
            # Check if this iteration was already processed
            base_name = f"iter{iteration_idx:03d}_{anchor_file.stem}"
            if self._is_iteration_processed(base_name, metadata_folder):
                self.logger.info(
                    f" ⏭️ {iteration_idx+1}/{num_iterations}: {base_name} (already processed)"
                )
                skipped += 1
                successful += 1
                continue
            
            self.logger.info(
                f" 🎲 {iteration_idx+1}/{num_iterations}: {len(partition)} images "
                f"[{', '.join(img.name for img in partition[:3])}{'...' if len(partition) > 3 else ''}]"
            )
            
            # Inject iteration_index into task config for _make_api_call
            task_with_iteration = task.copy()
            task_with_iteration['_iteration_index'] = iteration_idx
            task_with_iteration['_partition'] = partition
            
            # Process with retries
            for attempt in range(max_retries):
                try:
                    success = self.process(
                        anchor_file,  # Use anchor file for compatibility
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
            
            # Rate limit between iterations
            if iteration_idx < num_iterations - 1:
                time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(
            f"✓ Task {task_num}: {successful}/{num_iterations} successful "
            f"({skipped} skipped)"
        )
        return successful
    
    def _is_iteration_processed(self, base_name, metadata_folder):
        """Check if an iteration has already been successfully processed.
        
        Args:
            base_name: Base name for the iteration (e.g., "iter000_image1").
            metadata_folder: Path to metadata folder.
        
        Returns:
            bool: True if iteration has successful metadata.
        """
        import json
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                return metadata.get('success', False)
            except (json.JSONDecodeError, IOError):
                return False
        return False
    
    def process_task(self, task, task_num, total_tasks):
        """Process task - dispatches to appropriate method based on mode.
        
        If use_random_source_selection is enabled, uses partition-based processing.
        Otherwise, uses the standard file-by-file processing from base class.
        
        Args:
            task: Task configuration dictionary.
            task_num: Current task number (for logging).
            total_tasks: Total number of tasks (for logging).
        """
        folder = Path(task.get('folder', ''))
        
        # Set up folder paths
        source_folder = folder / "Source"
        output_folder = folder / "Generated_Output"
        metadata_folder = folder / "Metadata"
        
        # Check if using random source selection mode
        if task.get('use_random_source_selection', False):
            # Use partition-based processing
            self.process_random_source_task(
                task, task_num, total_tasks, output_folder, metadata_folder
            )
        else:
            # Use standard file-by-file processing from base class
            super().process_task(task, task_num, total_tasks)
    
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
        # Check if aspect_ratio is specified in config (ensure it's a string)
        config_ratio = str(task_config.get('aspect_ratio', '')) if task_config.get('aspect_ratio') else ''
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
        resolution = str(task_config.get('resolution', '1K'))
        
        # Check if using random source selection mode
        use_random_source = task_config.get('use_random_source_selection', False)
        
        if use_random_source:
            # Random source selection mode: use pre-computed partition
            # Check for injected partition from process_random_source_task
            partition = task_config.get('_partition')
            iteration_index = task_config.get('_iteration_index', 0)
            
            if partition:
                # Use the injected partition directly
                selected_images = partition
            else:
                # Fallback: compute partition based on file_path index
                # (for backwards compatibility if called without process_random_source_task)
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
            images_list = [handle_file(str(img)) for img in selected_images]
            
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
        
        # Check if using random source selection mode
        use_random_source = task_config.get('use_random_source_selection', False)
        iteration_index = task_config.get('_iteration_index')
        
        # Override base_name for iteration mode
        if use_random_source and iteration_index is not None:
            base_name = f"iter{iteration_index:03d}_{Path(file_path).stem}"
            file_name = f"iteration_{iteration_index}"
        
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
