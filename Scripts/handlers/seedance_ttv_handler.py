"""Seedance Text-to-Video API Handler."""
from pathlib import Path
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class SeedanceTTVHandler(BaseAPIHandler):
    """
    Seedance Text-to-Video handler.

    Generates videos from text prompts using Seedance's TTV API.
    """

    def validate_structure(self, tasks, config):
        """Validate Seedance TTV text-to-video structure.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries.

        Raises:
            Exception: If no valid tasks found.
        """
        return self._validate_text_to_video_structure(tasks)

    def _make_api_call(self, file_path, task_config, attempt):
        """Make Seedance TTV API call.

        Args:
            file_path: Ignored (text-to-video has no input file).
            task_config: Task configuration dict.
            attempt: Current attempt number.

        Returns:
            tuple: API response tuple.
        """
        default_settings = self.config.get("default_settings", {})

        return self.client.predict(
            p_t2v=task_config.get('prompt', ''),
            m_t2v=default_settings.get("model", "dreamina-seedance-2-0-260128"),
            p_i2v="",
            m_i2v=default_settings.get("model", "dreamina-seedance-2-0-260128"),
            f_i2v=None,
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
        """Handle Seedance TTV API result.

        Args:
            result: Tuple containing (output_video, task_id, status, debug_info, elapsed_time).
            file_path: Ignored (text-to-video).
            task_config: Task configuration dict.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
            base_name: Base name for output files.
            file_name: Ignored (text-to-video).
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
        style_name = task_config.get('style_name', 'seedance_ttv')
        default_settings = self.config.get("default_settings", {})

        self.logger.info(f"   Task ID: {task_id}, Status: {status}")

        # Check for error status
        if status and "error" in str(status).lower():
            self.logger.info(f"   ❌ API Error: {status}")
            metadata = {
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
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                         metadata, task_config)
            return False

        # Try to save video
        output_video_name = f"{base_name}_generated.mp4"
        output_path = Path(output_folder) / output_video_name
        video_saved = False

        if output_video and isinstance(output_video, dict) and 'video' in output_video:
            local_path = Path(output_video['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
                self.logger.info(f"   ✅ Copied from local: {output_path.name}")

        if not video_saved:
            self.logger.info("   ❌ Video save failed")
            metadata = {
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
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                         metadata, task_config)
            return False

        metadata = {
            'style_name': style_name,
            'model': default_settings.get("model", "dreamina-seedance-2-0-260128"),
            'task_id': task_id,
            'status': status,
            'debug_info': debug_info,
            'elapsed_time': elapsed_time,
            'generated_video': output_video_name,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': True,
            'api_name': self.api_name
        }
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                     metadata, task_config, log_status=True)

        return True

    def process_task(self, task, task_num, total_tasks):
        """Process entire Seedance TTV task.

        Each task generates one or more videos based on generation_count.

        Args:
            task: Task configuration dictionary.
            task_num: Current task number.
            total_tasks: Total number of tasks.
        """
        root_folder = Path(self.config.get('output_folder', ''))

        output_folder = root_folder / "Generated_Video"
        metadata_folder = root_folder / "Metadata"

        if not output_folder.exists():
            output_folder.mkdir(parents=True, exist_ok=True)
        if not metadata_folder.exists():
            metadata_folder.mkdir(parents=True, exist_ok=True)

        style_name = task.get('style_name', f'Task{task_num}')
        task_count = task.get('generation_count')
        global_count = self.config.get('generation_count', 1)
        generation_count = task_count if task_count is not None else global_count

        if generation_count < 1:
            generation_count = 1

        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {style_name} ({generation_count} generations)")

        successful = 0
        skipped = 0
        max_retries = self.api_defs.get('max_retries', 3)
        for gen_num in range(1, generation_count + 1):
            safe_style = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in style_name)
            safe_style = safe_style.strip().replace(' ', '_')
            base_name = f"{safe_style}-{gen_num}"
            metadata_file = metadata_folder / f"{base_name}_metadata.json"

            if metadata_file.exists():
                try:
                    import json
                    with open(metadata_file, 'r') as f:
                        meta = json.load(f)
                    if meta.get('success', False):
                        self.logger.info(f" ⏭️ Generation {gen_num}/{generation_count}: {style_name}-{gen_num} (already processed)")
                        skipped += 1
                        successful += 1
                        continue
                    attempts = meta.get('attempts', 0)
                    if not meta.get('success', False) and attempts >= max_retries:
                        self.logger.info(f" ⏭️ Generation {gen_num}/{generation_count}: {style_name}-{gen_num} (failed - max retries reached)")
                        skipped += 1
                        continue
                except (json.JSONDecodeError, IOError):
                    pass

            self.logger.info(f" 🎬 Generation {gen_num}/{generation_count}: {style_name}-{gen_num}")

            task_with_gen = task.copy()
            task_with_gen['generation_number'] = gen_num
            task_with_gen['style_name'] = style_name

            if 'design_link' not in task_with_gen:
                task_with_gen['design_link'] = self.config.get('design_link', '')
            if 'source_video_link' not in task_with_gen:
                task_with_gen['source_video_link'] = self.config.get('source_video_link', '')

            success = self.processor.process_file(None, task_with_gen, output_folder, metadata_folder)

            if success:
                successful += 1

            if gen_num < generation_count:
                time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(f"✓ Task {task_num}: {successful}/{generation_count} successful ({skipped} skipped)")

    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single Seedance TTV generation.

        Args:
            file_path: Ignored (text-to-video has no input file).
            task_config: Task configuration dict.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            bool: True if successful, False otherwise.
        """
        style_name = task_config.get('style_name', 'seedance_ttv')
        gen_num = task_config.get('generation_number', 1)

        safe_style = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in style_name)
        safe_style = safe_style.strip().replace(' ', '_')
        base_name = f"{safe_style}-{gen_num}"

        file_name = None
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
