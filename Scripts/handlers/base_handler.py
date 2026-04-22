"""
Base API Handler - Consolidates all common processing logic.
New APIs only need to implement the unique parts.
"""
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from PIL import Image


class ValidationError(Exception):
    """Exception raised when file validation fails.

    This exception signals that invalid files were found during validation.
    When caught, processing should stop and report generation should be skipped.
    """
    pass


class BaseAPIHandler:
    """Base handler with ALL common logic. Subclasses override only what's different."""
    
    # Connection error patterns that warrant extended retry with backoff
    CONNECTION_ERROR_PATTERNS = [
        'Connection refused',
        'ConnectionRefusedError',
        'ConnectionResetError',
        'ConnectionError',
        'Errno 61',   # Connection refused (macOS)
        'Errno 111',  # Connection refused (Linux)
        'Errno 10061',  # Connection refused (Windows)
        'RemoteDisconnected',
        'ConnectionAbortedError',
        'BrokenPipeError',
        'Server disconnected',
        'Connection reset by peer',
    ]
    
    # Connection retry configuration
    CONNECTION_RETRY_MAX_DURATION = 240  # 4 minutes max wait
    CONNECTION_RETRY_INITIAL_WAIT = 10   # Start with 10 seconds
    CONNECTION_RETRY_MAX_WAIT = 60       # Cap at 60 seconds between retries
    CONNECTION_RETRY_BACKOFF = 1.5       # Exponential backoff multiplier
    
    def __init__(self, processor):
        self.processor = processor
        self.api_defs = processor.api_definitions
        self.config = processor.config
        self.client = processor.client
        self.logger = processor.logger
        self.api_name = processor.api_name
    
    def _is_connection_error(self, error_str):
        """Check if an error is a connection-related error."""
        error_lower = error_str.lower()
        return any(p.lower() in error_lower for p in self.CONNECTION_ERROR_PATTERNS)
    
    def _make_api_call_with_connection_retry(self, file_path, task_config, attempt):
        """Wrap API call with connection error retry logic.
        
        Implements exponential backoff retry specifically for connection errors,
        allowing the server up to CONNECTION_RETRY_MAX_DURATION seconds to recover.
        
        Args:
            file_path: Path to the source file.
            task_config: Task configuration dictionary.
            attempt: Current attempt number from the outer retry loop.
        
        Returns:
            API result if successful.
        
        Raises:
            Exception: Re-raises the last exception if all retries fail.
        """
        total_wait_time = 0
        current_wait = self.CONNECTION_RETRY_INITIAL_WAIT
        connection_retry_count = 0
        last_exception = None
        
        while total_wait_time < self.CONNECTION_RETRY_MAX_DURATION:
            try:
                return self._make_api_call(file_path, task_config, attempt)
            except Exception as e:
                error_str = str(e)
                
                # Only retry for connection errors
                if not self._is_connection_error(error_str):
                    raise e
                
                last_exception = e
                connection_retry_count += 1
                remaining_time = self.CONNECTION_RETRY_MAX_DURATION - total_wait_time
                
                # Don't wait if we've exceeded max duration
                if remaining_time <= 0:
                    break
                
                # Cap wait time to remaining duration
                actual_wait = min(current_wait, remaining_time)
                
                self.logger.warning(
                    f" ⚠️ Connection error (attempt {connection_retry_count}): {error_str}"
                )
                self.logger.info(
                    f" ⏳ Waiting {actual_wait:.0f}s for server recovery "
                    f"(total waited: {total_wait_time:.0f}s / {self.CONNECTION_RETRY_MAX_DURATION}s max)"
                )
                
                time.sleep(actual_wait)
                total_wait_time += actual_wait
                
                # Apply exponential backoff for next iteration
                current_wait = min(current_wait * self.CONNECTION_RETRY_BACKOFF, 
                                   self.CONNECTION_RETRY_MAX_WAIT)
        
        # All connection retries exhausted
        self.logger.error(
            f" ❌ Server unavailable after {total_wait_time:.0f}s "
            f"({connection_retry_count} connection retries)"
        )
        raise last_exception
    
    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single file. Override _make_api_call() to customize."""
        base_name = Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()
        
        try:
            # Make API-specific call with connection retry wrapper
            result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
            
            # Parse and save result (subclass can override)
            success = self._handle_result(result, file_path, task_config, output_folder, 
                                         metadata_folder, base_name, file_name, start_time, attempt)
            
            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False
            
            return success
            
        except Exception as e:
            self._save_failure(file_path, task_config, metadata_folder, str(e), 
                             attempt, start_time)
            raise e
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Override this in subclass to make API-specific call."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _make_api_call()")
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Override this to handle API-specific result format."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _handle_result()")
    
    def _save_failure(self, file_path, task_config, metadata_folder, error, attempt, start_time):
        """Save failure metadata - common for all APIs."""
        # Handle text-to-video cases where file_path might be None
        if file_path is not None:
            base_name = Path(file_path).stem
            file_name = Path(file_path).name
        else:
            # For text-to-video, use style name or fallback
            style_name = task_config.get('style_name', 'unknown')
            gen_num = task_config.get('generation_number', 1)
            safe_style = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in style_name)
            safe_style = safe_style.strip().replace(' ', '_')
            base_name = f"{safe_style}-{gen_num}"
            file_name = None
        
        processing_time = time.time() - start_time
        
        metadata = {
            "error": error,
            "attempts": attempt + 1,
            "success": False,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "api_name": self.api_name
        }
        
        # Add source file name if available
        if file_name is not None:
            metadata[self._get_source_field()] = file_name
        
        # Add task-specific fields
        for key in ['prompt', 'effect', 'model']:
            if key in task_config:
                metadata[key] = task_config[key]
        
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                    metadata, task_config)
    
    def _get_source_field(self):
        """Get appropriate source field name based on API."""
        return "source_video" if self.api_name == "runway" else "source_image"
    
    def _get_processing_status(self, file_path, metadata_folder):
        """Get detailed processing status for a file.
        
        Args:
            file_path: Path to the source file.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            tuple: (is_complete, status_reason) where:
                - is_complete: True if file should be skipped
                - status_reason: 'success', 'failed_exhausted', or None if not complete
        """
        base_name = Path(file_path).stem
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        
        if metadata_file.exists():
            try:
                import json
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                # Skip if previous processing was successful
                if metadata.get('success', False):
                    return True, 'success'
                
                # Also skip if failed and exhausted all retries
                max_retries = self.api_defs.get('max_retries', 3)
                attempts = metadata.get('attempts', 0)
                if not metadata.get('success', False) and attempts >= max_retries:
                    return True, 'failed_exhausted'
                
                return False, None
            except (json.JSONDecodeError, IOError):
                return False, None
        return False, None
    
    def _is_file_processed(self, file_path, metadata_folder):
        """Check if a file has already been processed (success or exhausted retries).
        
        A file is considered processed if:
        - It was successfully processed (success: True), OR
        - It failed but has exhausted all retry attempts (success: False, attempts >= max_retries)
        
        Args:
            file_path: Path to the source file.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            bool: True if file has been processed, False otherwise.
        """
        is_complete, _ = self._get_processing_status(file_path, metadata_folder)
        return is_complete
    
    def process_task(self, task, task_num, total_tasks):
        """Process entire task - common structure for most APIs."""
        folder = Path(task.get('folder', task.get('folder_path', '')))
        
        # Get folder paths (handles both structures)
        if 'source_dir' in task:
            source_folder = Path(task['source_dir'])
            output_folder = Path(task['generated_dir'])
            metadata_folder = Path(task['metadata_dir'])
        else:
            source_folder = folder / "Source"
            output_folder = self._get_output_folder(folder)
            metadata_folder = folder / "Metadata"
        
        # Ensure output and metadata folders exist
        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)
        
        task_name = task.get('effect', '') or task.get('custom_effect_name', '') or folder.name
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {task_name}")
        
        # Get files to process
        files = self._get_task_files(task, source_folder)
        
        # Process files
        successful = 0
        skipped = 0
        for i, file_path in enumerate(files, 1):
            # Check if file was already processed (success or failed with exhausted retries)
            is_complete, status = self._get_processing_status(file_path, metadata_folder)
            if is_complete:
                if status == 'success':
                    self.logger.info(f" ⏭️ {i}/{len(files)}: {file_path.name} (already processed)")
                    successful += 1
                else:  # failed_exhausted
                    self.logger.info(f" ⏭️ {i}/{len(files)}: {file_path.name} (failed - max retries reached)")
                skipped += 1
                continue
            
            self.logger.info(f" 🖼️ {i}/{len(files)}: {file_path.name}")
            
            if self.processor.process_file(file_path, task, output_folder, metadata_folder):
                successful += 1
            
            if i < len(files):
                time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{len(files)} successful ({skipped} skipped)")
    
    def _get_output_folder(self, folder):
        """Get output folder name based on API type."""
        if self.api_name == "genvideo":
            return folder / "Generated_Image"
        elif self.api_name == "nano_banana":
            return folder / "Generated_Output"
        else:
            return folder / "Generated_Video"
    
    def _get_task_files(self, task, source_folder):
        """Get files for this task. Override for special handling."""
        file_type = 'video' if self.api_name == 'runway' else 'image'
        return self.processor._get_files_by_type(source_folder, file_type)

    # ==================== VALIDATION METHODS ====================

    def validate_file(self, file_path, file_type='image'):
        """Validate a single file. Override for API-specific validation rules.

        Args:
            file_path: Path to the file to validate.
            file_type: 'image' or 'video'.

        Returns:
            tuple: (is_valid, reason_string)
        """
        try:
            validation_rules = self.api_defs.get('validation', {})

            if file_type == 'video':
                file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
                file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)
                video_rules = validation_rules.get('video', {})

                if file_size_mb > video_rules.get('max_size_mb', 500):
                    return False, f"Size {file_size_mb:.1f}MB too large"

                info = self.processor._get_video_info(file_path)
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
                file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
                file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)

                with Image.open(file_path) as img:
                    w, h = img.size

                    max_size = validation_rules.get('max_size_mb', 50)
                    if file_size_mb >= max_size:
                        return False, f"Size > {max_size}MB"

                    min_dim = validation_rules.get('min_dimension', 128)
                    if w < min_dim or h < min_dim:
                        return False, f"Dims {w}x{h} too small"

                    max_dim = validation_rules.get('max_dimension')
                    if max_dim and (w > max_dim or h > max_dim):
                        return False, f"Dims {w}x{h} exceed {max_dim}x{max_dim}"

                    aspect_ratio_range = validation_rules.get('aspect_ratio')
                    if aspect_ratio_range:
                        ratio = w / h
                        if not (aspect_ratio_range[0] <= ratio <= aspect_ratio_range[1]):
                            return False, f"Ratio {ratio:.2f} invalid"

                    return True, f"{w}x{h}"

        except Exception as e:
            return False, f"Error: {str(e)}"

    def validate_structure(self, tasks, config):
        """Validate folder structure and return valid tasks.

        Override this in subclasses for API-specific folder structures.
        Default: simple folder/Source → images pattern.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries ready for processing.

        Raises:
            ValidationError: If invalid files are found.
        """
        return self._validate_source_images_structure(tasks)

    def _validate_source_images_structure(self, tasks, output_dir_name='Generated_Video',
                                          extra_dirs=None):
        """Validate simple folder/Source → images structure.

        Shared base pattern for APIs that read images from a Source subfolder.

        Args:
            tasks: List of task dicts each containing 'folder' key.
            output_dir_name: Name of the output directory to create.
            extra_dirs: Optional list of additional directory names to create.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        valid_tasks, invalid_images = [], []
        for i, task in enumerate(tasks, 1):
            folder = Path(task['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_folder, 'image')
            if not image_files:
                self.logger.warning(f"❌ Empty source: {source_folder}")
                continue

            valid_count = 0
            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_images.append({
                        'path': str(img_file), 'folder': str(folder),
                        'name': img_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count > 0:
                (folder / output_dir_name).mkdir(exist_ok=True)
                (folder / "Metadata").mkdir(exist_ok=True)
                if extra_dirs:
                    for d in extra_dirs:
                        (folder / d).mkdir(exist_ok=True)
                valid_tasks.append(task)
                self.logger.info(f"✓ Task {i}: {valid_count}/{len(image_files)} valid images")

        if invalid_images:
            self.processor.write_invalid_report(invalid_images, self.api_name)
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        return valid_tasks

    def _validate_base_folder_effects_structure(self, tasks, config, effect_key='effect',
                                                 custom_effect_key='custom_effect',
                                                 parallel=False):
        """Validate base_folder/effect_name/Source pattern.

        Shared pattern for effects-based APIs (kling_effects, vidu_effects, pixverse).

        Args:
            tasks: List of task dicts each containing an effect key.
            config: Processor config containing 'base_folder'.
            effect_key: Key in task dict for the effect name.
            custom_effect_key: Key in task dict for custom effect override.
            parallel: Whether to use parallel validation.

        Returns:
            list: Valid enhanced task dictionaries with folder paths.

        Raises:
            ValidationError: If invalid files are found.
        """
        base_folder = Path(config.get('base_folder', ''))
        base_folder.mkdir(parents=True, exist_ok=True)

        valid_tasks = []
        invalid_images = []

        def process_task(task):
            custom_effect = task.get(custom_effect_key, '')
            effect = task.get(effect_key, '')
            folder_name = effect if effect else custom_effect
            if not folder_name:
                self.logger.warning(f"⚠️ Task has no {effect_key} or {custom_effect_key} specified")
                return None, []

            task_folder = base_folder / folder_name
            task_folder.mkdir(parents=True, exist_ok=True)
            source_dir = task_folder / "Source"
            source_dir.mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_dir, 'image')
            if not image_files:
                self.logger.warning(f"⚠️ No images found in: {source_dir}")
                return None, []

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
                (task_folder / "Generated_Video").mkdir(exist_ok=True)
                (task_folder / "Metadata").mkdir(exist_ok=True)
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

        if parallel and self.api_defs.get('parallel_validation', False):
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

        if not valid_tasks:
            raise Exception(f"No valid {self.api_name} tasks found")
        return valid_tasks

    def _validate_image_video_cross_match_structure(self, tasks):
        """Validate Source Image + Source Video cross-match pattern.

        Shared pattern for APIs that cross-match images with videos
        (wan, dreamactor, kling_motion).

        Args:
            tasks: List of task dicts each containing 'folder' key.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        valid_tasks = []
        invalid_images = []
        invalid_videos = []

        for i, task in enumerate(tasks, 1):
            folder = Path(task['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            source_image_folder = folder / "Source Image"
            source_video_folder = folder / "Source Video"
            source_image_folder.mkdir(exist_ok=True)
            source_video_folder.mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_image_folder, 'image')
            if not image_files:
                self.logger.warning(f"❌ Task {i}: No images found in {source_image_folder}")
                continue

            video_files = self.processor._get_files_by_type(source_video_folder, 'video')
            if not video_files:
                self.logger.warning(f"❌ Task {i}: No videos found in {source_video_folder}")
                continue

            valid_image_count = 0
            for image_file in image_files:
                is_valid, reason = self.validate_file(image_file, 'image')
                if not is_valid:
                    invalid_images.append({
                        'path': str(image_file), 'folder': str(folder),
                        'name': image_file.name, 'reason': reason
                    })
                else:
                    valid_image_count += 1

            valid_video_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file), 'folder': str(folder),
                        'name': video_file.name, 'reason': reason
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
            self.processor.write_invalid_report(invalid_images, f'{self.api_name}_images')
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        if invalid_videos:
            self.processor.write_invalid_report(invalid_videos, f'{self.api_name}_videos')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")
        return valid_tasks

    def _validate_text_to_video_structure(self, tasks):
        """Validate text-to-video structure (prompt + output_folder).

        Shared pattern for TTV APIs (veo, kling_ttv).

        Args:
            tasks: List of task dicts with 'prompt' and 'output_folder'.

        Returns:
            list: Valid task dictionaries with task_num added.

        Raises:
            Exception: If no valid tasks found.
        """
        valid_tasks = []
        for i, task in enumerate(tasks, 1):
            if not task.get('prompt'):
                self.logger.warning(f"⚠️ Task {i}: Missing prompt")
                continue
            output_folder = Path(task.get('output_folder', ''))
            if not output_folder or str(output_folder) == '':
                self.logger.warning(f"⚠️ Task {i}: Missing output_folder")
                continue
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder = output_folder.parent / "Metadata"
            metadata_folder.mkdir(parents=True, exist_ok=True)
            task['task_num'] = i
            valid_tasks.append(task)
            self.logger.info(f"✓ Task {i}: Text-to-video prompt configured")

        if not valid_tasks:
            raise Exception(f"No valid {self.api_name} tasks found")
        return valid_tasks
