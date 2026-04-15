"""Pixverse Text-to-Video API Handler."""
from pathlib import Path
import time
import re
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class PixverseTTVHandler(BaseAPIHandler):
    """
    Pixverse Text-to-Video handler.

    Generates videos from text prompts using Pixverse's TTV API.
    """

    def validate_structure(self, tasks, config):
        """Validate Pixverse TTV text-to-video structure.

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
        """Make Pixverse TTV API call.

        Args:
            file_path: Ignored (text-to-video has no input file).
            task_config: Task configuration dict.
            attempt: Current attempt number.

        Returns:
            tuple: API response tuple.
        """
        default_settings = self.config.get("default_settings", {})

        return self.client.predict(
            model=default_settings.get("model", "v6"),
            aspect_ratio=task_config.get("aspect_ratio", default_settings.get("aspect_ratio", "16:9")),
            duration=default_settings.get("duration", "5s"),
            v6_duration=default_settings.get("v6_duration", 5),
            motion_mode=default_settings.get("motion_mode", "normal"),
            quality=default_settings.get("quality", "540p"),
            style=task_config.get("style", default_settings.get("style", "none")),
            effect=task_config.get("effect", "none") if not task_config.get("custom_effect_id") else "none",
            custom_effect_id=task_config.get("custom_effect_id", ""),
            negative_prompt=task_config.get("negative_prompt", ""),
            prompt=task_config.get("prompt", ""),
            seed=default_settings.get("seed", -1),
            generate_audio_switch=default_settings.get("generate_audio", False),
            generate_multi_clip_switch=default_settings.get("generate_multi_clip", False),
            thinking_type=default_settings.get("thinking_type", "auto"),
            api_name=self.api_defs["api_name"]
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Pixverse TTV API result.

        Args:
            result: Tuple containing API response fields.
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

        all_fields = self.processor._capture_all_api_fields(
            result, ['output_url', 'output_video', 'error_message', 'completion_time', 'elapsed_time'])

        error_message = all_fields.get('error_message')

        # Extract VideoID
        video_id = None
        if error_message and "VideoID:" in error_message:
            match = re.search(r'VideoID:\s*(\d+)', error_message)
            if match:
                video_id = match.group(1)

        output_url = all_fields.get('output_url')
        output_video = result[1] if len(result) > 1 else None

        style_name = task_config.get('style_name', 'pixverse_ttv')
        output_video_name = f"{base_name}_generated.mp4"
        output_path = Path(output_folder) / output_video_name

        video_saved = False
        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)

        if not video_saved and output_video and isinstance(output_video, dict) and "video" in output_video:
            local_path = Path(output_video["video"])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True

        processing_time = time.time() - start_time
        default_settings = self.config.get("default_settings", {})

        if not video_saved:
            if error_message:
                self.logger.info(f"   ❌ API Error: {error_message}")

            metadata = {
                'style_name': style_name,
                'model': default_settings.get("model", "v6"),
                'video_id': video_id,
                'error': error_message or 'Video download/save failed',
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'attempts': attempt + 1,
                'success': False,
                'api_name': self.api_name,
                **all_fields
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                         metadata, task_config)
            return False

        metadata = {
            'style_name': style_name,
            'model': default_settings.get("model", "v6"),
            'video_id': video_id,
            'generated_video': output_video_name,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': True,
            'api_name': self.api_name,
            **all_fields
        }

        self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                     metadata, task_config, log_status=True)

        return True

    def process_task(self, task, task_num, total_tasks):
        """Process entire Pixverse TTV task.

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
        """Process a single Pixverse TTV generation.

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
        style_name = task_config.get('style_name', 'pixverse_ttv')
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
