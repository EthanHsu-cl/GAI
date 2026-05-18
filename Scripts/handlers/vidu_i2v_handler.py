"""Vidu Image-to-Video API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class ViduI2vHandler(BaseAPIHandler):
    """Vidu Image-to-Video handler (/submitI2V)."""

    def validate_structure(self, tasks, config):
        """Validate Vidu I2V with base_folder/effect subfolders.

        Supports both 'effect' and 'custom_effect_name' keys, matching the
        existing Vidu Effects layout.
        """
        return self._validate_base_folder_effects_structure(
            tasks, config, effect_key='effect', custom_effect_key='custom_effect_name',
            parallel=True
        )

    def _resolve_param(self, task_config, key, default):
        """Per-task overrides global config which overrides api_params default."""
        api_default = self.api_defs.get('api_params', {}).get(key, default)
        return task_config.get(key, self.config.get(key, api_default))

    def _make_api_call(self, file_path, task_config, attempt):
        """Make Vidu I2V API call."""
        prompt = task_config.get('prompt', '') or self.config.get('prompt', '')
        model = self._resolve_param(task_config, 'model', 'viduq2-pro')
        duration = self._resolve_param(task_config, 'duration', 5)
        resolution = self._resolve_param(task_config, 'resolution', '720p')
        movement = self._resolve_param(task_config, 'movement', 'auto')
        audio = self._resolve_param(task_config, 'audio', True)

        self.logger.info(
            f"   Model: {model}, Duration: {duration}s, Resolution: {resolution}, "
            f"Movement: {movement}, Audio: {audio}"
        )

        return self.client.predict(
            model=model,
            first_image=handle_file(str(file_path)),
            prompt=prompt,
            duration=duration,
            resolution=resolution,
            movement=movement,
            audio=audio,
            api_name=self.api_defs['api_name']
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Vidu I2V API result.

        API returns 5-tuple:
          [0] output URL (str)
          [1] video dict {video: filepath, subtitles: ...}
          [2] thumbnail dict
          [3] task_id (str)
          [4] error_msg (str)
        """
        if not isinstance(result, tuple) or len(result) < 5:
            raise ValueError("Invalid API response format")

        output_url = result[0]
        video_dict = result[1] if len(result) >= 2 else None
        thumbnail_dict = result[2] if len(result) >= 3 else None
        task_id = result[3] if len(result) >= 4 else ''
        error_msg = result[4] if len(result) >= 5 else ''

        self.logger.info(f" Task ID: {task_id}")

        if error_msg:
            raise ValueError(f"API error: {error_msg}")

        effect_name = (task_config.get('effect', '') or
                       task_config.get('custom_effect_name', '')).replace(' ', '_').replace('-', '_')
        output_video_name = (f"{base_name}_{effect_name}_i2v.mp4"
                             if effect_name else f"{base_name}_i2v.mp4")
        output_path = Path(output_folder) / output_video_name

        video_saved = False

        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)

        if not video_saved and isinstance(video_dict, dict) and video_dict.get('video'):
            local_path = Path(video_dict['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True

        if not video_saved:
            raise IOError("Video download/copy failed")

        thumbnail_url = ''
        if isinstance(thumbnail_dict, dict):
            thumbnail_url = thumbnail_dict.get('url') or thumbnail_dict.get('path') or ''

        processing_time = time.time() - start_time
        metadata = {
            "effect_name": task_config.get('effect', ''),
            "custom_effect_name": task_config.get('custom_effect_name', ''),
            "model": self._resolve_param(task_config, 'model', 'viduq2-pro'),
            "prompt": task_config.get('prompt', ''),
            "duration": self._resolve_param(task_config, 'duration', 5),
            "resolution": self._resolve_param(task_config, 'resolution', '720p'),
            "movement": self._resolve_param(task_config, 'movement', 'auto'),
            "audio": self._resolve_param(task_config, 'audio', True),
            "video_url": output_url,
            "thumbnail_url": thumbnail_url,
            "task_id": task_id,
            "generated_video": output_video_name,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "attempts": attempt + 1,
            "success": True,
            "api_name": self.api_name
        }

        self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                     metadata, {})
        self.logger.info(f" ✅ Generated: {output_video_name}")

        return True
