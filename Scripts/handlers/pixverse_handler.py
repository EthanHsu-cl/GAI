"""Pixverse API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
import re
from datetime import datetime
from .base_handler import BaseAPIHandler


class PixverseHandler(BaseAPIHandler):
    """Pixverse effects handler."""
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Make Pixverse API call."""
        default_settings = self.config.get("default_settings", {})
        
        return self.client.predict(
            model=default_settings.get("model", "v5.5"),
            duration=default_settings.get("duration", "5s"),
            motion_mode=default_settings.get("motion_mode", "normal"),
            quality=default_settings.get("quality", "720p"),
            style=default_settings.get("style", "none"),
            effect=task_config.get("effect", "none") if not task_config.get("custom_effect_id") else "none",
            custom_effect_id=task_config.get("custom_effect_id", ""),
            negative_prompt=task_config.get("negative_prompt", ""),
            prompt=task_config.get("prompt", ""),
            use_url=False,
            image=handle_file(str(file_path)),
            image_url="",
            generate_audio_switch=default_settings.get("generate_audio", False),
            generate_multi_clip_switch=default_settings.get("generate_multi_clip", False),
            thinking_type=default_settings.get("thinking_type", "auto"),
            api_name=self.api_defs["api_name"]
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Pixverse API result."""
        if not isinstance(result, tuple):
            raise ValueError(f"Invalid API response format: {result}")
        
        # Capture all fields
        all_fields = self.processor._capture_all_api_fields(
            result, ['output_url', 'output_video', 'error_message', 'completion_time', 'elapsed_time'])
        
        error_message = all_fields.get('error_message')
        
        # Extract VideoID
        video_id = None
        if error_message and "VideoID:" in error_message:
            match = re.search(r'VideoID:\s*(\d+)', error_message)
            if match:
                video_id = match.group(1)
        
        # Try to save video first (prioritize video output over error checking)
        output_url = all_fields.get('output_url')
        output_video = result[1] if len(result) > 1 else None
        
        effect = task_config.get("effect", "none")
        output_video_name = f"{base_name}_{effect.replace(' ', '_')}_effect.mp4"
        output_path = Path(output_folder) / output_video_name
        
        video_saved = False
        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)
        
        if not video_saved and output_video and isinstance(output_video, dict) and "video" in output_video:
            local_path = Path(output_video["video"])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
        
        # If video wasn't saved, check for actual error
        if not video_saved:
            # Log the error message for debugging
            if error_message:
                self.logger.info(f"   ❌ API Error: {error_message}")
            
            # Save failure metadata
            processing_time = time.time() - start_time
            default_settings = self.config.get("default_settings", {})
            metadata = {
                'effect_name': effect,
                'model': default_settings.get("model", "v5.5"),
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
        
        # Save success metadata
        processing_time = time.time() - start_time
        default_settings = self.config.get("default_settings", {})
        
        metadata = {
            'effect_name': effect,
            'model': default_settings.get("model", "v5.5"),
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
                                    metadata, task_config)
        
        return True
        
        return True
