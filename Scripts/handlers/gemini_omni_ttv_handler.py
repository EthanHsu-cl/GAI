"""Gemini Omni (Google Veo) Text-to-Video API Handler.

Drives the /gemini_omni_async_submit endpoint as a prompt-only text-to-video
generator. The endpoint also accepts an optional video and up to 5 reference
images for multi-turn editing, but this handler sends only the prompt and leaves
all media inputs empty.

Run mode: the handler defaults to Async (``Async（背景輪詢）``), matching the
Gradio UI's own default and the recorded working session — the gradio_client
predict() call still blocks until the video is ready even in Async mode, so no
separate poll step is needed. Override via ``default_settings.mode`` if Sync
is confirmed to behave the same.
"""
from pathlib import Path
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class GeminiOmniTTVHandler(BaseAPIHandler):
    """
    Gemini Omni Text-to-Video handler.

    Generates videos from text prompts using the Google Veo /gemini_omni
    endpoint.
    """

    def validate_structure(self, tasks, config):
        """Validate Gemini Omni TTV text-to-video structure.

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
        """Make Gemini Omni TTV API call.

        Sends only the prompt; all video/image inputs and gs:// URIs are left
        empty (pure text-to-video).

        Args:
            file_path: Ignored (text-to-video has no input file).
            task_config: Task configuration dict.
            attempt: Current attempt number.

        Returns:
            tuple: API response tuple.
        """
        default_settings = self.config.get("default_settings", {})

        return self.client.predict(
            prompt=task_config.get("prompt", ""),
            parent_id_field=default_settings.get("parent_id_field", "previous_interaction_id"),
            parent_id=task_config.get("parent_id", ""),
            mode=default_settings.get("mode", "Async（背景輪詢）"),
            video_upload=None,
            video_uri="",
            img1_up=None,
            img1_uri="",
            img2_up=None,
            img2_uri="",
            img3_up=None,
            img3_uri="",
            img4_up=None,
            img4_uri="",
            img5_up=None,
            img5_uri="",
            api_name=self.api_defs["api_name"]
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Gemini Omni TTV API result.

        Response tuple:
            [0] status message
            [1] interaction id (debug)
            [2] generated video dict {video: filepath, subtitles: filepath|None}
            [3] parent id for multi-turn continuation

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

        status_message = result[0] if len(result) > 0 else ""
        interaction_id = result[1] if len(result) > 1 else None
        video_dict = result[2] if len(result) > 2 else None
        parent_id = result[3] if len(result) > 3 else None

        processing_time = time.time() - start_time
        default_settings = self.config.get("default_settings", {})
        style_name = task_config.get('style_name', 'gemini_omni_ttv')
        gen_num = task_config.get('generation_number', 1)

        self.logger.info(f"   Status: {status_message}")

        output_video_name = f"{base_name}_generated.mp4"
        output_path = Path(output_folder) / output_video_name
        video_saved = False

        # Extract video from video_dict (URL first, then local copy)
        if video_dict and isinstance(video_dict, dict):
            url = video_dict.get("url")
            if url:
                video_saved = self.processor.download_file(url, output_path)
            if not video_saved and video_dict.get("video"):
                local_path = Path(video_dict["video"])
                if local_path.exists():
                    shutil.copy2(local_path, output_path)
                    video_saved = True

        # Treat explicit error/failure status as a failure even if no exception
        error_status = bool(status_message) and (
            'error' in status_message.lower() or 'failed' in status_message.lower()
        )

        if not video_saved or error_status:
            if status_message:
                self.logger.info(f"   ❌ API Error: {status_message}")
            metadata = {
                'style_name': style_name,
                'generation_number': gen_num,
                'mode': default_settings.get("mode", "Async（背景輪詢）"),
                'interaction_id': interaction_id,
                'parent_id': parent_id,
                'status_message': status_message,
                'error': status_message or 'Video download/save failed',
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'attempts': attempt + 1,
                'success': False,
                'api_name': self.api_name,
                'prompt': task_config.get('prompt', '')
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                         metadata, task_config)
            return False

        self.logger.info(f"   ✅ Generated: {output_path.name}")

        metadata = {
            'style_name': style_name,
            'generation_number': gen_num,
            'mode': default_settings.get("mode", "Async（背景輪詢）"),
            'interaction_id': interaction_id,
            'parent_id': parent_id,
            'status_message': status_message,
            'generated_video': output_video_name,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': True,
            'api_name': self.api_name,
            'prompt': task_config.get('prompt', '')
        }

        if video_dict and isinstance(video_dict, dict) and video_dict.get('subtitles'):
            metadata['subtitles'] = str(video_dict['subtitles'])

        self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                     metadata, task_config, log_status=True)

        return True

    def process_task(self, task, task_num, total_tasks):
        """Process entire Gemini Omni TTV task.

        Each task generates one or more videos based on generation_count.

        Args:
            task: Task configuration dictionary.
            task_num: Current task number.
            total_tasks: Total number of tasks.
        """
        root_folder = Path(self.config.get('output_folder', ''))

        output_folder = root_folder / "Generated_Video"
        metadata_folder = root_folder / "Metadata"

        output_folder.mkdir(parents=True, exist_ok=True)
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
        """Process a single Gemini Omni TTV generation.

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
        style_name = task_config.get('style_name', 'gemini_omni_ttv')
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
