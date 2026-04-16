"""Seedance Image-to-Video API Handler."""
from pathlib import Path
from gradio_client import handle_file
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class SeedanceI2vHandler(BaseAPIHandler):
    """
    Seedance Image-to-Video handler.

    Generates videos from source images using Seedance's I2V API.
    Each style folder contains a Source subfolder with input images.
    """

    def validate_structure(self, tasks, config):
        """Validate Seedance I2V folder structure with Source images.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid enhanced task dictionaries.

        Raises:
            Exception: If no valid tasks found.
        """
        from .base_handler import ValidationError

        valid_tasks = []
        invalid_images = []

        for i, task in enumerate(tasks, 1):
            if not task.get('prompt'):
                self.logger.warning(f"⚠️ Task {i}: Missing prompt")
                continue

            folder = Path(task.get('folder', ''))
            if not folder or str(folder) == '':
                self.logger.warning(f"⚠️ Task {i}: Missing folder path")
                continue

            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_folder, 'image')
            if not image_files:
                self.logger.warning(f"⚠️ Task {i}: No images found in {source_folder}")
                continue

            valid_count = 0
            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_images.append({
                        'folder': folder.name, 'filename': img_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count == 0:
                self.logger.warning(f"⚠️ Task {i}: No valid images in {source_folder}")
                continue

            output_folder = folder / "Generated_Video"
            metadata_folder = folder / "Metadata"
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)

            task_count = task.get('generation_count')
            global_count = config.get('generation_count', 1)
            generation_count = task_count if task_count is not None else global_count

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
            self.logger.info(
                f"✓ Task {i}: {valid_count} images × {generation_count} generations = {total_expected} videos"
            )

        if invalid_images:
            self.processor.write_invalid_report(invalid_images, "seedance_i2v")
            self.logger.warning(f"⚠️ {len(invalid_images)} invalid images found (see report)")

        if not valid_tasks:
            raise Exception("No valid Seedance I2V tasks found")
        return valid_tasks

    def _make_api_call(self, file_path, task_config, attempt):
        """Make Seedance I2V API call.

        Args:
            file_path: Path to the source image.
            task_config: Task configuration dict.
            attempt: Current attempt number.

        Returns:
            tuple: API response tuple.
        """
        default_settings = self.config.get("default_settings", {})

        return self.client.predict(
            p_t2v="",
            m_t2v=default_settings.get("model", "dreamina-seedance-2-0-260128"),
            p_i2v=task_config.get('prompt', ''),
            m_i2v=default_settings.get("model", "dreamina-seedance-2-0-260128"),
            f_i2v=handle_file(str(file_path)),
            p_fl="",
            m_fl=default_settings.get("model", "dreamina-seedance-2-0-260128"),
            f_fl=None,
            l_fl=None,
            ratio=task_config.get("aspect_ratio", default_settings.get("aspect_ratio", "adaptive")),
            duration=default_settings.get("duration", 5),
            resolution=default_settings.get("resolution", "720p"),
            seed=default_settings.get("seed", -1),
            service_tier=default_settings.get("service_tier", "default"),
            gen_audio=default_settings.get("generate_audio", True),
            draft=default_settings.get("draft", False),
            ret_last=False,
            watermark=False,
            cam_fix=task_config.get("cam_fix", default_settings.get("cam_fix", False)),
            expires=default_settings.get("expires", 172800),
            api_name=self.api_defs["api_name"]
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Seedance I2V API result.

        Args:
            result: Tuple containing (output_video, task_id, status, debug_info, elapsed_time).
            file_path: Path to the source image.
            task_config: Task configuration dict.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
            base_name: Base name for output files.
            file_name: Source file name.
            start_time: Processing start time.
            attempt: Current attempt number.

        Returns:
            bool: True if successful, False otherwise.
        """
        if not isinstance(result, tuple):
            raise ValueError(f"Invalid API response format: {result}")

        output_video = result[0] if len(result) > 0 else None
        task_id = result[1] if len(result) > 1 else None
        status = result[2] if len(result) > 2 else None
        debug_info = result[3] if len(result) > 3 else None
        elapsed_time = result[4] if len(result) > 4 else None

        processing_time = time.time() - start_time
        style_name = task_config.get('style_name', 'seedance_i2v')
        default_settings = self.config.get("default_settings", {})
        gen_num = task_config.get('generation_number', 1)

        self.logger.info(f"   Task ID: {task_id}, Status: {status}")

        if status and "error" in str(status).lower():
            self.logger.info(f"   ❌ API Error: {status}")
            metadata = {
                'source_image': file_name,
                'style_name': style_name,
                'model': default_settings.get("model", "dreamina-seedance-2-0-260128"),
                'task_id': task_id,
                'status': status,
                'debug_info': debug_info,
                'elapsed_time': elapsed_time,
                'error': status,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'attempts': attempt + 1,
                'success': False,
                'api_name': self.api_name
            }
            gen_base_name = f"{base_name}_{gen_num}"
            self.processor.save_metadata(Path(metadata_folder), gen_base_name, file_name,
                                         metadata, task_config)
            return False

        output_filename = f"{base_name}_{gen_num}.mp4"
        output_path = Path(output_folder) / output_filename
        video_saved = False

        if output_video and isinstance(output_video, dict) and 'video' in output_video:
            local_path = Path(output_video['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
                self.logger.info(f"   ✅ Generated: {output_path.name}")

        if not video_saved:
            self.logger.info("   ❌ Video save failed")
            metadata = {
                'source_image': file_name,
                'style_name': style_name,
                'model': default_settings.get("model", "dreamina-seedance-2-0-260128"),
                'task_id': task_id,
                'status': status,
                'debug_info': debug_info,
                'elapsed_time': elapsed_time,
                'error': 'Video download/save failed',
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'attempts': attempt + 1,
                'success': False,
                'api_name': self.api_name
            }
            gen_base_name = f"{base_name}_{gen_num}"
            self.processor.save_metadata(Path(metadata_folder), gen_base_name, file_name,
                                         metadata, task_config)
            return False

        metadata = {
            'source_image': file_name,
            'style_name': style_name,
            'model': default_settings.get("model", "dreamina-seedance-2-0-260128"),
            'task_id': task_id,
            'status': status,
            'debug_info': debug_info,
            'elapsed_time': elapsed_time,
            'generated_video': output_filename,
            'generation_number': gen_num,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': True,
            'api_name': self.api_name
        }
        gen_base_name = f"{base_name}_{gen_num}"
        self.processor.save_metadata(Path(metadata_folder), gen_base_name, file_name,
                                     metadata, task_config, log_status=True)

        return True

    def _get_generation_status(self, base_name, gen_num, metadata_folder):
        """Get processing status for a specific generation.

        Args:
            base_name: Base name of the source file.
            gen_num: Generation number.
            metadata_folder: Path to the metadata folder.

        Returns:
            tuple: (is_complete, status_reason).
        """
        gen_base_name = f"{base_name}_{gen_num}"
        metadata_file = Path(metadata_folder) / f"{gen_base_name}_metadata.json"

        if metadata_file.exists():
            try:
                import json
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

                if metadata.get('success', False):
                    return True, 'success'

                max_retries = self.api_defs.get('max_retries', 3)
                attempts = metadata.get('attempts', 0)
                if not metadata.get('success', False) and attempts >= max_retries:
                    return True, 'failed_exhausted'

                return False, None
            except (json.JSONDecodeError, IOError):
                return False, None
        return False, None

    def process_task(self, task, task_num, total_tasks):
        """Process entire Seedance I2V task.

        Iterates over source images in the style folder and generates
        multiple videos per image based on generation_count.

        Args:
            task: Task configuration dictionary.
            task_num: Current task number.
            total_tasks: Total number of tasks.
        """
        folder = Path(task.get('folder', ''))
        source_folder = folder / "Source"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"

        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)

        style_name = task.get('style_name', folder.name)

        task_count = task.get('generation_count')
        global_count = self.config.get('generation_count', 1)
        generation_count = task_count if task_count is not None else global_count

        if generation_count < 1:
            generation_count = 1

        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {style_name}")

        source_files = self.processor._get_files_by_type(source_folder, 'image')

        if not source_files:
            self.logger.warning(f" ⚠️ No source images found in {source_folder}")
            return

        self.logger.info(f" 📸 Found {len(source_files)} source images × {generation_count} generations = {len(source_files) * generation_count} total")

        successful = 0
        skipped = 0
        total_generations = len(source_files) * generation_count
        current = 0

        for file_path in source_files:
            base_name = file_path.stem
            file_name = file_path.name

            for gen_num in range(1, generation_count + 1):
                current += 1

                is_complete, status = self._get_generation_status(base_name, gen_num, metadata_folder)
                if is_complete:
                    if status == 'success':
                        self.logger.info(f" ⏭️ {current}/{total_generations}: {base_name}_{gen_num} (already processed)")
                        successful += 1
                    else:
                        self.logger.info(f" ⏭️ {current}/{total_generations}: {base_name}_{gen_num} (failed - max retries reached)")
                    skipped += 1
                    continue

                self.logger.info(f" 🎬 {current}/{total_generations}: {file_name} → {base_name}_{gen_num}.mp4")

                task_with_gen = task.copy()
                task_with_gen['generation_number'] = gen_num
                task_with_gen['style_name'] = style_name

                if self.processor.process_file(file_path, task_with_gen, output_folder, metadata_folder):
                    successful += 1

                if current < total_generations:
                    time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(f"✓ Task {task_num}: {successful}/{total_generations} successful ({skipped} skipped)")

    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single Seedance I2V generation.

        Args:
            file_path: Path to the source image.
            task_config: Task configuration dict.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            bool: True if successful, False otherwise.
        """
        base_name = Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()

        try:
            result = self._make_api_call(file_path, task_config, attempt)

            success = self._handle_result(result, file_path, task_config, output_folder,
                                          metadata_folder, base_name, file_name, start_time, attempt)

            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False

            return success

        except Exception as e:
            self.logger.error(f"   ❌ Error: {e}")
            raise
