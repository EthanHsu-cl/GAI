"""Base handler for image-generation APIs (Nano Banana, OpenAI Image, ...).

Holds the logic shared by every multi-image generation endpoint:
    - image validation + Source/Reference/Additional folder structure
    - additional-image pools (random pairing / sequential matching)
    - deterministic random source selection + iteration-based processing
    - reference images, generations-per-source
    - 429 (Resource Exhausted) retry tracking and persistence

Subclasses implement only the per-endpoint parts: ``_make_api_call`` and
``_handle_result`` (plus model/quality constants).
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import time
import random
from datetime import datetime
from PIL import Image

from .base_handler import BaseAPIHandler


class BaseImageGenerationHandler(BaseAPIHandler):
    """Shared base for multi-image generation handlers."""

    # Subclasses override these per endpoint/model.
    MODEL_MAX_IMAGES = {}
    DEFAULT_MAX_IMAGES = 3
    DEFAULT_MIN_IMAGES = 1
    DEFAULT_MODEL = 'gemini-2.5-flash-image'

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
        self._reference_image_cache = {}  # Cache reference images per task
        self._selection_modes = {}  # Track selection modes per task
        self._selection_plans = {}  # Pre-built selection plans per task
        # Per-call state (additional/all images, 429 flag) is stored on the per-call
        # task_config copy rather than on `self` so concurrent threads don't collide.
        self._combinations_lock = threading.Lock()  # guards _used_combinations

    def validate_file(self, file_path, file_type='image'):
        """Image validation with 32MB limit.

        Args:
            file_path: Path to the file to validate.
            file_type: 'image' or 'video'.

        Returns:
            tuple: (is_valid, reason_string)
        """
        if file_type == 'video':
            return super().validate_file(file_path, file_type)
        try:
            validation_rules = self.api_defs.get('validation', {})
            file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
            file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)
            min_dimensions = validation_rules.get('min_dimension', 300)

            with Image.open(file_path) as img:
                w, h = img.size
                if file_size_mb >= validation_rules.get('max_size_mb', 32):
                    return False, "Size > 32MB"
                if w <= min_dimensions or h <= min_dimensions:
                    return False, f"Dims {w}x{h} too small"
                return True, f"{w}x{h}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def validate_structure(self, tasks, config):
        """Validate Source folder structure with optional parallel processing.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        from .base_handler import ValidationError

        valid_tasks = []
        invalid_images = []

        def process_task(task):
            folder = Path(task['folder'])
            folder.mkdir(parents=True, exist_ok=True)

            # Text-to-image: generate purely from the prompt — no Source folder
            # required, so skip the source-image validation entirely.
            if task.get('text_to_image', False):
                if task.get('use_reference_images', False):
                    (folder / "Reference").mkdir(exist_ok=True)
                (folder / "Generated_Output").mkdir(exist_ok=True)
                (folder / "Metadata").mkdir(exist_ok=True)
                self.logger.info(f"✓ Task: {folder.name} - text-to-image mode (prompt only)")
                return task, []

            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)
            if task.get('use_reference_images', False):
                (folder / "Reference").mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_folder, 'image')
            if not image_files:
                self.logger.warning(f"⚠️ No images found in: {source_folder}")
                return None, []

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
                (folder / "Generated_Output").mkdir(exist_ok=True)
                (folder / "Metadata").mkdir(exist_ok=True)
                self.logger.info(f"✓ Task: {folder.name} - {valid_count}/{len(image_files)} valid images")
                return task, invalid_for_task
            return None, invalid_for_task

        if self.api_defs.get('parallel_validation', False):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(process_task, tasks))
        else:
            results = [process_task(task) for task in tasks]

        for task, invalid_for_task in results:
            if task:
                valid_tasks.append(task)
            invalid_images.extend(invalid_for_task)

        if invalid_images:
            self.processor.write_invalid_report(invalid_images, self.api_name)
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        return valid_tasks

    def _is_error_429(self, error_str):
        """Check if an error string indicates a 429 Resource Exhausted error."""
        if not error_str:
            return False
        error_lower = error_str.lower()
        return any(p.lower() in error_lower for p in self.ERROR_429_PATTERNS)

    def _read_error429_retries(self, base_name, metadata_folder):
        """Read existing error 429 retry count from a metadata file."""
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

        Returns:
            tuple: (is_complete, status_reason) where status_reason is
                'success', 'failed_exhausted', 'failed_error429_exhausted', or None.
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

    def _setup_concurrent_task(self, task):
        """Preload additional-image pools single-threaded before workers run.

        Overrides BaseAPIHandler's no-op hook so the lazy cache init in
        _load_image_pools doesn't race across worker threads.
        """
        self._load_image_pools(task)

    def _load_image_pools(self, task_config, max_additional=None):
        """Load and cache image pools from additional folders.

        Returns:
            dict: Pool data with 'pools', 'mode', and 'allow_duplicates' keys,
                  or None if multi-image is not configured.
        """
        multi_image_config = task_config.get('multi_image_config', {})

        # Auto-detect Additional folder if use_multi_image is true but no explicit config
        if not multi_image_config or not multi_image_config.get('enabled', False):
            if task_config.get('use_multi_image', False):
                task_folder = Path(task_config.get('folder', ''))
                additional_folder = task_folder / 'Additional'
                if additional_folder.exists():
                    self.logger.info(f" 📂 Auto-detected Additional folder for multi-image mode")
                    multi_image_config = {
                        'enabled': True,
                        'mode': 'sequential',
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

        Returns:
            list: List of additional image paths (can be empty for unused slots).
        """
        model = task_config.get('model', self.DEFAULT_MODEL)
        max_images = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        # Reserve 1 slot for source image
        max_additional = max_images - 1

        # multi_image_count specifies TOTAL images including source
        user_count = task_config.get('multi_image_count', 0)
        if user_count > 0:
            if user_count > max_images:
                self.logger.warning(
                    f" ⚠️ multi_image_count ({user_count}) exceeds model limit ({max_images}). "
                    f"Using model limit."
                )
                user_count = max_images
            max_additional = user_count - 1  # -1 for source image

        if not task_config.get('use_multi_image', True):
            return []

        if user_count == 1:
            return []

        # Static additional images (legacy support)
        additional_images = task_config.get('additional_images', {})
        if additional_images:
            result = []
            for i in range(1, max_additional + 1):
                img = additional_images.get(f'image{i}', '')
                if img:
                    result.append(img)
            return result[:max_additional]

        # Multi-image configuration
        pool_data = self._load_image_pools(task_config, max_additional)
        if not pool_data or not pool_data['pools']:
            return []

        pools = pool_data['pools']
        mode = pool_data['mode']
        allow_duplicates = pool_data['allow_duplicates']

        effective_max = max_additional if max_additional else len(pools)

        if mode == 'random_pairing':
            return self._random_pairing(pools, file_path, allow_duplicates, effective_max)
        elif mode == 'sequential':
            return self._sequential_selection(pools, file_path, effective_max)
        else:
            self.logger.warning(f" ⚠️ Unknown mode '{mode}', using random_pairing")
            return self._random_pairing(pools, file_path, allow_duplicates, effective_max)

    def _random_pairing(self, pools, file_path, allow_duplicates, max_additional):
        """Randomly select one image from each pool, optionally avoiding duplicates."""
        selected = []
        max_attempts = 100

        for pool in pools[:max_additional]:
            if not pool:
                continue

            if allow_duplicates:
                selected.append(str(random.choice(pool)))
            else:
                # lock guards shared _used_combinations against concurrent access
                with self._combinations_lock:
                    for _ in range(max_attempts):
                        candidate = random.choice(pool)
                        combo_key = (str(file_path), str(candidate))
                        if combo_key not in self._used_combinations:
                            self._used_combinations.add(combo_key)
                            selected.append(str(candidate))
                            break
                    else:
                        selected.append(str(random.choice(pool)))

        return selected[:max_additional]

    def _sequential_selection(self, pools, file_path, max_additional):
        """Select images sequentially from each pool based on source file index.

        Ensures one-to-one matching when enough images are available, cycling
        with modulo when a pool is smaller than the source set.
        """
        file_index = None
        for key, index_map in self._source_file_indices.items():
            if str(file_path) in index_map:
                file_index = index_map[str(file_path)]
                break
        if file_index is None:
            self.logger.warning(f" ⚠️ File not found in source index: {file_path.name}")
            file_index = hash(str(file_path)) % 10000

        selected = []

        for pool in pools[:max_additional]:
            if pool:
                index = file_index % len(pool)
                selected.append(str(pool[index]))

                if file_index < 3 or (file_index % 10 == 0):
                    pool_size = len(pool)
                    if pool_size >= file_index + 1:
                        self.logger.debug(f" 🔗 One-to-one match: source#{file_index} → additional#{index}")
                    else:
                        self.logger.debug(f" 🔄 Cycling match: source#{file_index} → additional#{index} (pool size: {pool_size})")

        return selected[:max_additional]

    def _get_reference_images(self, task_config):
        """Get reference images from the Reference folder if enabled.

        Reference images are appended after the source images in every API call
        and do NOT count toward the min_images/max_images limits.

        Returns:
            list: Sorted list of Path objects, or empty list if disabled/none.
        """
        if not task_config.get('use_reference_images', False):
            return []

        task_key = str(task_config.get('folder', ''))

        if task_key in self._reference_image_cache:
            return self._reference_image_cache[task_key]

        ref_folder = Path(task_config.get('folder', '')) / "Reference"
        if ref_folder.exists():
            images = self.processor._get_files_by_type(ref_folder, 'image')
            images = sorted(images, key=lambda x: x.name.lower())
            self._reference_image_cache[task_key] = images
            if images:
                self.logger.info(f" 📂 Loaded {len(images)} reference images from Reference/")
            else:
                self.logger.warning(f" ⚠️ Reference folder exists but no images found: {ref_folder}")
        else:
            self._reference_image_cache[task_key] = []
            self.logger.warning(f" ⚠️ Reference folder not found: {ref_folder}")

        return self._reference_image_cache[task_key]

    def _get_source_images_for_task(self, task_config):
        """Get and cache all source images for a task.

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

        Two modes based on 'use_deterministic_random':
            1. Sequential (default): sorted alphabetically, consumed in order.
            2. Deterministic Random: shuffled with a seed (reproducible).

        Both pre-calculate per-iteration image counts (even bucket distribution),
        avoid repeats until the pool is exhausted, then restart.

        Returns:
            list: List of lists of Path objects (one inner list per iteration).
        """
        task_key = str(task_config.get('folder', ''))

        model = task_config.get('model', self.DEFAULT_MODEL)
        model_max = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)

        min_images = task_config.get('min_images', self.DEFAULT_MIN_IMAGES)
        max_images = task_config.get('max_images', model_max)

        # Validate and clamp to model limits
        min_images = max(1, min(min_images, model_max))
        max_images = max(min_images, min(max_images, model_max))

        source_images = self._get_source_images_for_task(task_config)
        total_available = len(source_images)

        if not source_images:
            return []

        # Clamp max to available images
        max_images = min(max_images, total_available)
        min_images = min(min_images, max_images)

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

        total_needed = sum(iteration_counts)

        use_deterministic_random = task_config.get('use_deterministic_random', False)
        random_seed = task_config.get('random_seed', None)

        if use_deterministic_random:
            if random_seed is not None:
                seed = int(random_seed)
                self.logger.info(f" 🎲 Using deterministic random mode with seed: {seed}")
            else:
                seed = abs(hash(task_key)) % (2**32)
                self.logger.info(f" 🎲 Using deterministic random mode (auto-seed: {seed})")
            selection_mode = f'deterministic_random_seed_{seed}'
        else:
            selection_mode = 'sequential_sorted'
            self.logger.info(f" 📝 Using sequential sorted mode")

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

        if use_deterministic_random:
            source_pool = source_images[:]
            random.seed(seed)
            random.shuffle(source_pool)
            self.logger.debug(f" 🔀 Shuffled source pool with seed {seed}")
        else:
            source_pool = source_images[:]

        # Build selection plan by consuming from pool sequentially
        selection_plan = []
        available_pool = []

        for iteration_index in range(num_iterations):
            num_images = iteration_counts[iteration_index]

            # Refill pool if needed
            if len(available_pool) < num_images:
                if use_deterministic_random:
                    temp_pool = source_images[:]
                    random.seed(seed)
                    random.shuffle(temp_pool)
                    available_pool.extend(temp_pool)
                else:
                    available_pool.extend(source_images[:])

            # Consume images from pool (no repeats within cycle)
            selected = available_pool[:num_images]
            available_pool = available_pool[num_images:]

            # Sort selected images for consistent API input ordering
            selected = sorted(selected, key=lambda x: x.name.lower())
            selection_plan.append(selected)

        self._selection_modes[task_key] = selection_mode

        return selection_plan

    def _get_random_source_selection(self, task_config, iteration_index):
        """Deterministically select N images from Source folder for an API call.

        Pre-builds the complete selection plan on first call, then returns the
        pre-computed selection for the given iteration.

        Returns:
            list: List of selected image Path objects.
        """
        task_key = str(task_config.get('folder', ''))

        if task_key not in self._selection_plans:
            self._selection_plans[task_key] = self._build_selection_plan(task_config)

        selection_plan = self._selection_plans[task_key]

        if not selection_plan:
            self.logger.error(f" ❌ No source images found for selection")
            return []

        if iteration_index >= len(selection_plan):
            self.logger.error(
                f" ❌ Iteration {iteration_index} exceeds plan size {len(selection_plan)}"
            )
            return []

        selected = selection_plan[iteration_index]

        model = task_config.get('model', self.DEFAULT_MODEL)
        model_max = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        min_images = max(1, min(task_config.get('min_images', self.DEFAULT_MIN_IMAGES), model_max))
        max_images = max(min_images, min(task_config.get('max_images', model_max), model_max))
        num_iterations = task_config.get('num_iterations', 0) or len(self._get_source_images_for_task(task_config))
        num_images = len(selected)

        if task_key not in self._random_source_selections:
            self._random_source_selections[task_key] = []

        selection_mode = getattr(self, '_selection_modes', {}).get(task_key, 'sequential_sorted')

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

        num_counts = max_images - min_images + 1
        iters_per_bucket = num_iterations // num_counts if num_counts else num_iterations
        current_bucket = (iteration_index * num_counts) // num_iterations if num_iterations else 0

        self.logger.info(
            f" 📊 Iteration {iteration_index + 1}/{num_iterations}: {num_images} images "
            f"(bucket {current_bucket + 1}/{num_counts}, ~{iters_per_bucket} iters each)"
        )
        self.logger.debug(f" 📋 Selected: {[img.name for img in selected]}")

        return selected

    def get_random_selection_log(self, task_config):
        """Get the log of all random selections made for a task."""
        task_key = str(task_config.get('folder', ''))
        return self._random_source_selections.get(task_key, [])

    def process_task(self, task, task_num, total_tasks):
        """Route to iteration-based processing (random source) or standard mode.

        Random source selection always uses iteration-based processing; standard
        mode defers to the base class, which handles concurrency itself.
        """
        # Text-to-image: no source images — generate num_iterations images
        # purely from the prompt. Kept fully separate from the image-to-image
        # paths so their Source-folder handling is untouched.
        if task.get('text_to_image', False):
            folder = Path(task.get('folder', ''))
            output_folder = folder / "Generated_Output"
            metadata_folder = folder / "Metadata"
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)
            self._process_text_to_image(task, task_num, total_tasks,
                                        output_folder, metadata_folder)
            return

        use_random_source = task.get('use_random_source_selection', False)

        if use_random_source:
            folder = Path(task.get('folder', ''))
            output_folder = folder / "Generated_Output"
            metadata_folder = folder / "Metadata"

            source_images = self._get_source_images_for_task(task)
            num_iterations = task.get('num_iterations') or len(source_images)

            if num_iterations <= 0:
                self.logger.warning(f" ⚠️ No source images found, skipping task")
                return

            task_with_iterations = task.copy()
            task_with_iterations['num_iterations'] = num_iterations

            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)

            self._process_iterations(task_with_iterations, task_num, total_tasks,
                                     output_folder, metadata_folder)
        else:
            # Standard mode (Source-folder, optional Additional). Reference images
            # are only wired into the iteration path, so load them here too and
            # stamp the task so _make_api_call appends them after the sources.
            if task.get('use_reference_images', False):
                reference_images = self._get_reference_images(task)
                # Cross-match: pair each source with each reference individually
                # (N sources × M refs calls) instead of one call per source with
                # all refs appended together.
                if task.get('reference_cross_match', False) and reference_images:
                    folder = Path(task.get('folder', ''))
                    output_folder = self._get_output_folder(folder)
                    metadata_folder = folder / "Metadata"
                    output_folder.mkdir(parents=True, exist_ok=True)
                    metadata_folder.mkdir(parents=True, exist_ok=True)
                    self._process_cross_match(task, task_num, total_tasks,
                                              output_folder, metadata_folder,
                                              reference_images)
                    return
                task = dict(task)
                task['_reference_images'] = [str(img) for img in reference_images]
            super().process_task(task, task_num, total_tasks)

    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single file with 429 retry and iteration-based naming support."""
        # Shallow-copy so per-call state stays local to this thread.
        task_config = dict(task_config)
        task_config['_last_error_is_429'] = False

        base_name = task_config.get('_base_name') or Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()
        metadata_saved = False
        success = False

        try:
            result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)

            success = self._handle_result(result, file_path, task_config, output_folder,
                                          metadata_folder, base_name, file_name, start_time, attempt)
            metadata_saved = True

            # Retry loop for 429 Resource Exhausted errors (independent of max_retries)
            max_429 = self.api_defs.get('max_retries_error429', 0)
            while not success and task_config.get('_last_error_is_429') and max_429 > 0:
                count = self._read_error429_retries(base_name, metadata_folder)
                if count >= max_429:
                    self.logger.info(f" ⏭️ 429 retry limit reached ({count}/{max_429})")
                    break
                self.logger.info(f" ⏳ 429 retry {count}/{max_429} (waiting {30 * count}s)")
                time.sleep(30 * count)
                task_config['_last_error_is_429'] = False
                start_time = time.time()
                try:
                    result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
                    success = self._handle_result(result, file_path, task_config, output_folder,
                                                  metadata_folder, base_name, file_name, start_time, attempt)
                    metadata_saved = True
                except Exception:
                    break

            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False

            return success

        except Exception as e:
            self.logger.error(f" ❌ Error processing {base_name}: {e}")
            if not metadata_saved:
                processing_time = time.time() - start_time
                use_random_source = task_config.get('use_random_source_selection', False)
                all_imgs = task_config.get('_call_all_images', [])
                all_imgs_info = [Path(img).name for img in all_imgs if img]
                additional_imgs = task_config.get('_call_additional_images', [])
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
                    task_config['_last_error_is_429'] = True
                    metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
                if use_random_source and all_imgs_info:
                    metadata['all_images_used'] = all_imgs_info
                    metadata['random_source_selection'] = True
                elif additional_imgs_info:
                    metadata['additional_images_used'] = additional_imgs_info

                self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                                  metadata, task_config)
                metadata_saved = True
            raise

        finally:
            if not metadata_saved:
                # Last-resort fallback for unexpected failures
                processing_time = time.time() - start_time
                metadata = {
                    'error': 'Unexpected failure - no metadata saved by normal paths',
                    'success': False,
                    'attempts': attempt + 1,
                    'processing_time_seconds': round(processing_time, 1),
                    'processing_timestamp': datetime.now().isoformat(),
                    'api_name': self.api_name
                }
                try:
                    self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                                      metadata, task_config)
                except Exception:
                    self.logger.error(f" ❌ Failed to save fallback metadata for {base_name}")

    def _process_iterations(self, task, task_num, total_tasks, output_folder, metadata_folder):
        """Process task using an iteration-based loop (num_iterations mode).

        Supports generations_per_source (repeat the same source group N times)
        and reference images appended after sources in every call.
        """
        task_name = Path(task.get('folder', '')).name
        num_iterations = task.get('num_iterations', 1)
        generations_per_source = max(1, task.get('generations_per_source', 1))
        source_images = self._get_source_images_for_task(task)
        reference_images = self._get_reference_images(task)
        min_images = task.get('min_images', self.DEFAULT_MIN_IMAGES)
        max_images = task.get('max_images', self.MODEL_MAX_IMAGES.get(
            task.get('model', self.DEFAULT_MODEL), self.DEFAULT_MAX_IMAGES))
        concurrent_requests = self._get_concurrent_requests(task)

        # Cross-match: split each call into one-per-reference (single ref each)
        # instead of appending all references together.
        cross_match = task.get('reference_cross_match', False) and len(reference_images) > 0
        if cross_match:
            ref_variants = [(f"_ref{i:02d}_{r.stem}", [str(r)])
                            for i, r in enumerate(reference_images)]
        else:
            ref_variants = [("", [str(img) for img in reference_images])]
        total_api_calls = num_iterations * generations_per_source * len(ref_variants)

        gen_info = f", {generations_per_source} gen/source" if generations_per_source > 1 else ""
        ref_info = (f", {len(reference_images)} ref images{' (cross-match)' if cross_match else ''}"
                    if reference_images else "")
        conc_info = f", up to {concurrent_requests} concurrent" if concurrent_requests > 1 else ""
        self.logger.info(
            f"📁 Task {task_num}/{total_tasks}: {task_name} "
            f"({num_iterations} iterations{gen_info}{ref_info}{conc_info}, {len(source_images)} source images, "
            f"images per call: {min_images}-{max_images}, total API calls: {total_api_calls})"
        )

        max_retries = self.api_defs.get('max_retries', 3)

        # Pre-build selection plan single-threaded to prevent concurrent cache races.
        task_key = str(task.get('folder', ''))
        if task_key not in self._selection_plans:
            self._selection_plans[task_key] = self._build_selection_plan(task)
        selection_plan = self._selection_plans.get(task_key, [])

        # Build the list of work items first, skipping already-processed iterations.
        work_items = []  # (call_index, base_name, primary_image, task_with_iteration, num_selected)
        successful = 0
        skipped = 0
        call_index = 0

        for iteration_idx in range(num_iterations):
            selected_images = selection_plan[iteration_idx] if iteration_idx < len(selection_plan) else []
            if not selected_images:
                self.logger.warning(f" ⚠️ No source images for iteration {iteration_idx}")
                continue

            primary_image = selected_images[0]
            if len(selected_images) == 1:
                iter_base = f"iter{iteration_idx:03d}_{primary_image.stem}"
            else:
                image_names = "_".join([img.stem for img in selected_images])
                if len(image_names) > 150:
                    image_names = image_names[:147] + "..."
                iter_base = f"iter{iteration_idx:03d}_{image_names}"

            for gen_idx in range(generations_per_source):
                gen_base = f"{iter_base}_gen{gen_idx:02d}" if generations_per_source > 1 else iter_base
                for ref_suffix, ref_list in ref_variants:
                    base_name = gen_base + ref_suffix
                    call_index += 1

                    is_complete, status = self._get_iteration_status(base_name, metadata_folder)
                    if is_complete:
                        if status == 'success':
                            self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (already processed)")
                            successful += 1
                        elif status == 'failed_error429_exhausted':
                            self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (failed - 429 retries exhausted)")
                        else:
                            self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (failed - max retries reached)")
                        skipped += 1
                        continue

                    task_with_iteration = task.copy()
                    task_with_iteration['_iteration_index'] = iteration_idx
                    task_with_iteration['_base_name'] = base_name
                    task_with_iteration['_generation_index'] = gen_idx
                    task_with_iteration['_generations_per_source'] = generations_per_source
                    task_with_iteration['_reference_images'] = ref_list

                    work_items.append((call_index, base_name, primary_image,
                                       task_with_iteration, len(selected_images)))

        def run_one(item):
            call_idx, base_name, primary_image, task_with_iteration, _ = item
            self.logger.info(f" 🎲 {call_idx}/{total_api_calls}: Processing {base_name}")
            for attempt in range(max_retries):
                try:
                    if self.process(primary_image, task_with_iteration, output_folder,
                                    metadata_folder, attempt, max_retries):
                        return True
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f" ⚠️ Attempt {attempt+1} failed for {base_name}: {e}")
                        time.sleep(5)
                    else:
                        self.logger.error(f" ❌ All {max_retries} attempts failed for {base_name}: {e}")
            return False

        if concurrent_requests > 1 and work_items:
            self.logger.info(
                f" 🚀 Dispatching {len(work_items)} API calls with up to "
                f"{concurrent_requests} in parallel"
            )
            with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
                futures = [executor.submit(run_one, item) for item in work_items]
                for future in as_completed(futures):
                    try:
                        if future.result():
                            successful += 1
                    except Exception as e:
                        self.logger.error(f" ❌ Worker raised: {e}")
        else:
            for idx, item in enumerate(work_items):
                if run_one(item):
                    successful += 1
                # Inter-request rate limit (sequential mode only). Scaled by images used.
                if idx < len(work_items) - 1:
                    base_rate = self.api_defs.get('rate_limit', 3)
                    num_images_used = item[4] + len(reference_images)
                    effective_max = max_images if max_images > 0 else 1
                    scaled_wait = max(1, base_rate * num_images_used / effective_max)
                    self.logger.info(f" ⏳ Rate limit: {scaled_wait:.0f}s ({num_images_used}/{effective_max} images)")
                    time.sleep(scaled_wait)

        self.logger.info(
            f"✓ Task {task_num}: {successful}/{total_api_calls} successful ({skipped} skipped)"
        )

    def _process_text_to_image(self, task, task_num, total_tasks, output_folder, metadata_folder):
        """Process a text-to-image task: generate purely from the prompt.

        There are no source images. ``num_iterations`` controls how many images
        are generated (defaults to 1). Supports generations_per_source, optional
        reference images, reference cross-match, and concurrency — mirroring
        _process_iterations but without any Source-folder selection.
        """
        task_name = Path(task.get('folder', '')).name
        num_iterations = task.get('num_iterations', 0) or 1
        generations_per_source = max(1, task.get('generations_per_source', 1))
        reference_images = self._get_reference_images(task)
        concurrent_requests = self._get_concurrent_requests(task)

        # Cross-match: split each call into one-per-reference (single ref each)
        # instead of appending all references together.
        cross_match = task.get('reference_cross_match', False) and len(reference_images) > 0
        if cross_match:
            ref_variants = [(f"_ref{i:02d}_{r.stem}", [str(r)])
                            for i, r in enumerate(reference_images)]
        else:
            ref_variants = [("", [str(img) for img in reference_images])]
        total_api_calls = num_iterations * generations_per_source * len(ref_variants)

        gen_info = f", {generations_per_source} gen/iter" if generations_per_source > 1 else ""
        ref_info = (f", {len(reference_images)} ref images{' (cross-match)' if cross_match else ''}"
                    if reference_images else "")
        conc_info = f", up to {concurrent_requests} concurrent" if concurrent_requests > 1 else ""
        self.logger.info(
            f"📁 Task {task_num}/{total_tasks}: {task_name} "
            f"(text-to-image, {num_iterations} iterations{gen_info}{ref_info}{conc_info}, "
            f"total API calls: {total_api_calls})"
        )

        max_retries = self.api_defs.get('max_retries', 3)

        # Build the list of work items, skipping already-processed iterations.
        work_items = []  # (call_index, base_name, task_with_iteration)
        successful = 0
        skipped = 0
        call_index = 0

        for iteration_idx in range(num_iterations):
            iter_base = f"iter{iteration_idx:03d}"
            for gen_idx in range(generations_per_source):
                gen_base = f"{iter_base}_gen{gen_idx:02d}" if generations_per_source > 1 else iter_base
                for ref_suffix, ref_list in ref_variants:
                    base_name = gen_base + ref_suffix
                    call_index += 1

                    is_complete, status = self._get_iteration_status(base_name, metadata_folder)
                    if is_complete:
                        if status == 'success':
                            self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (already processed)")
                            successful += 1
                        else:
                            self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (failed - retries exhausted)")
                        skipped += 1
                        continue

                    task_with_iteration = task.copy()
                    task_with_iteration['_iteration_index'] = iteration_idx
                    task_with_iteration['_base_name'] = base_name
                    task_with_iteration['_generation_index'] = gen_idx
                    task_with_iteration['_generations_per_source'] = generations_per_source
                    task_with_iteration['_reference_images'] = ref_list
                    work_items.append((call_index, base_name, task_with_iteration))

        def run_one(item):
            call_idx, base_name, task_with_iteration = item
            self.logger.info(f" ✍️ {call_idx}/{total_api_calls}: Processing {base_name}")
            for attempt in range(max_retries):
                try:
                    # base_name doubles as the synthetic "file path": process()
                    # uses _base_name for naming and the t2i path ignores the
                    # source image, so no real file is needed.
                    if self.process(base_name, task_with_iteration, output_folder,
                                    metadata_folder, attempt, max_retries):
                        return True
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f" ⚠️ Attempt {attempt+1} failed for {base_name}: {e}")
                        time.sleep(5)
                    else:
                        self.logger.error(f" ❌ All {max_retries} attempts failed for {base_name}: {e}")
            return False

        if concurrent_requests > 1 and work_items:
            self.logger.info(
                f" 🚀 Dispatching {len(work_items)} API calls with up to "
                f"{concurrent_requests} in parallel"
            )
            with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
                futures = [executor.submit(run_one, item) for item in work_items]
                for future in as_completed(futures):
                    try:
                        if future.result():
                            successful += 1
                    except Exception as e:
                        self.logger.error(f" ❌ Worker raised: {e}")
        else:
            for idx, item in enumerate(work_items):
                if run_one(item):
                    successful += 1
                if idx < len(work_items) - 1:
                    time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(
            f"✓ Task {task_num}: {successful}/{total_api_calls} successful ({skipped} skipped)"
        )

    def _process_cross_match(self, task, task_num, total_tasks, output_folder,
                             metadata_folder, reference_images):
        """Standard-mode cross-match: pair every source with every reference.

        Produces len(sources) × len(references) API calls. Each call sends
        [source, single_reference] rather than appending all references at once.
        Output/metadata names get a `_refNN_<refstem>` suffix so every pairing is
        saved separately and is independently resumable. Honors concurrent_requests.
        """
        folder = Path(task.get('folder', ''))
        source_folder = folder / "Source"
        source_images = sorted(self._get_task_files(task, source_folder),
                               key=lambda x: x.name.lower())
        concurrent_requests = self._get_concurrent_requests(task)
        max_retries = self.api_defs.get('max_retries', 3)
        total_api_calls = len(source_images) * len(reference_images)

        conc_info = f", up to {concurrent_requests} concurrent" if concurrent_requests > 1 else ""
        self.logger.info(
            f"📁 Task {task_num}/{total_tasks}: {folder.name} "
            f"(cross-match: {len(source_images)} sources × {len(reference_images)} references "
            f"= {total_api_calls} API calls{conc_info})"
        )

        if not source_images:
            self.logger.warning(" ⚠️ No source images found, skipping task")
            return

        work_items = []  # (call_index, base_name, source_image, task_with_pair)
        successful = 0
        skipped = 0
        call_index = 0

        for source_image in source_images:
            for ref_idx, ref_image in enumerate(reference_images):
                base_name = f"{source_image.stem}_ref{ref_idx:02d}_{ref_image.stem}"
                if len(base_name) > 150:
                    base_name = base_name[:147] + "..."
                call_index += 1

                is_complete, status = self._get_iteration_status(base_name, metadata_folder)
                if is_complete:
                    if status == 'success':
                        self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (already processed)")
                        successful += 1
                    else:
                        self.logger.info(f" ⏭️ {call_index}/{total_api_calls}: {base_name} (failed - retries exhausted)")
                    skipped += 1
                    continue

                task_with_pair = task.copy()
                task_with_pair['_base_name'] = base_name
                task_with_pair['_reference_images'] = [str(ref_image)]
                work_items.append((call_index, base_name, source_image, task_with_pair))

        def run_one(item):
            call_idx, base_name, source_image, task_with_pair = item
            self.logger.info(f" 🔗 {call_idx}/{total_api_calls}: Processing {base_name}")
            for attempt in range(max_retries):
                try:
                    if self.process(source_image, task_with_pair, output_folder,
                                    metadata_folder, attempt, max_retries):
                        return True
                except Exception as e:
                    if attempt < max_retries - 1:
                        self.logger.warning(f" ⚠️ Attempt {attempt+1} failed for {base_name}: {e}")
                        time.sleep(5)
                    else:
                        self.logger.error(f" ❌ All {max_retries} attempts failed for {base_name}: {e}")
            return False

        if concurrent_requests > 1 and work_items:
            self.logger.info(
                f" 🚀 Dispatching {len(work_items)} API calls with up to "
                f"{concurrent_requests} in parallel"
            )
            with ThreadPoolExecutor(max_workers=concurrent_requests) as executor:
                futures = [executor.submit(run_one, item) for item in work_items]
                for future in as_completed(futures):
                    try:
                        if future.result():
                            successful += 1
                    except Exception as e:
                        self.logger.error(f" ❌ Worker raised: {e}")
        else:
            for idx, item in enumerate(work_items):
                if run_one(item):
                    successful += 1
                if idx < len(work_items) - 1:
                    time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(
            f"✓ Task {task_num}: {successful}/{total_api_calls} successful ({skipped} skipped)"
        )

    def _get_iteration_status(self, base_name, metadata_folder):
        """Get detailed processing status for an iteration."""
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
        """Get processing status with 429 error awareness."""
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
        """Check if an iteration has already been processed (success or exhausted)."""
        is_complete, _ = self._get_iteration_status(base_name, metadata_folder)
        return is_complete

    def _get_aspect_ratio(self, file_path, task_config):
        """Determine aspect ratio from config, or use 'auto' as default."""
        config_ratio = str(task_config.get('aspect_ratio') or '')
        if config_ratio:
            if config_ratio in self.VALID_ASPECT_RATIOS:
                return config_ratio
            else:
                self.logger.warning(
                    f" ⚠️ Invalid aspect_ratio '{config_ratio}' in config. "
                    f"Valid options: {self.VALID_ASPECT_RATIOS}. Using default: {self.DEFAULT_ASPECT_RATIO}"
                )
        return self.DEFAULT_ASPECT_RATIO
