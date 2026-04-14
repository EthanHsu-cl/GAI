"""Vidu Effects API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from .base_handler import BaseAPIHandler


class ViduEffectsHandler(BaseAPIHandler):
    """Vidu Effects handler."""

    def validate_structure(self, tasks, config):
        """Validate Vidu Effects with base_folder/effect subfolders.

        Supports both 'effect' and 'custom_effect_name' keys.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid enhanced task dictionaries with folder paths.

        Raises:
            ValidationError: If invalid files are found.
        """
        return self._validate_base_folder_effects_structure(
            tasks, config, effect_key='effect', custom_effect_key='custom_effect_name',
            parallel=True
        )

    def _make_api_call(self, file_path, task_config, attempt):
        """Make Vidu Effects API call."""
        prompt = task_config.get('prompt', '') or self.config.get('prompt', '')
        effect = task_config.get('effect', '')
        custom_effect_name = task_config.get('custom_effect_name', '')
        model = task_config.get('model', self.config.get('model_version', 'viduq2-pro'))
        
        # When custom_effect_name is provided, category and effect must be "Custom"
        if custom_effect_name:
            effect = 'Custom'
            task_config['category'] = 'Custom'
        
        self.logger.info(f"   Model: {model}, Effect: {effect}")
        if custom_effect_name:
            self.logger.info(f"   Custom Effect Name: {custom_effect_name}")
        
        return self.client.predict(
            effect=effect,
            prompt=prompt,
            aspect_ratio="as input image",
            area="auto",
            beast="auto",
            bgm=False,
            images=(handle_file(str(file_path)),),
            custom_effect_name=custom_effect_name,
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Vidu Effects API result."""
        if not isinstance(result, tuple) or len(result) < 4:
            raise ValueError("Invalid API response format")
        
        # Vidu Effects API returns: (video_url, video_url_duplicate, thumbnail_url, task_id, error_msg)
        output_urls = result[0]  # Video URL
        thumbnail_url = result[2] if len(result) >= 3 else ''
        task_id = result[3] if len(result) >= 4 else ''  # Actual task ID (numeric string)
        
        self.logger.info(f" Task ID: {task_id}")
        
        if not output_urls:
            raise ValueError("No output URLs returned")
        
        # Download video
        output_url = output_urls[0] if isinstance(output_urls, (tuple, list)) else output_urls
        effect_name = (task_config.get('effect', '') or task_config.get('custom_effect_name', '')).replace(' ', '_').replace('-', '_')
        output_video_name = f"{base_name}_{effect_name}_effect.mp4"
        output_path = Path(output_folder) / output_video_name
        
        if not self.processor.download_file(output_url, output_path):
            raise IOError("Video download failed")
        
        # Save success metadata - only essential fields, no config duplication
        processing_time = time.time() - start_time
        metadata = {
            "effect_category": task_config.get('category', ''),
            "effect_name": task_config.get('effect', ''),
            "custom_effect_name": task_config.get('custom_effect_name', ''),
            "model": task_config.get('model', self.config.get('model_version', 'viduq2-pro')),
            "prompt": task_config.get('prompt', ''),
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
        
        # Pass empty dict as task_config to prevent config pollution
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                    metadata, {})
        self.logger.info(f" ✅ Generated: {output_video_name}")
        
        return True
