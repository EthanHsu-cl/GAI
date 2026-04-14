"""Kling Video Effects API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class KlingEffectsHandler(BaseAPIHandler):
    """Kling Video Effects handler for applying premade video effects to images."""

    def validate_structure(self, tasks, config):
        """Validate Kling Effects with base_folder/effect subfolders.

        Uses custom_effect (priority) or effect name from tasks.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid enhanced task dictionaries with folder paths.

        Raises:
            ValidationError: If invalid files are found.
        """
        return self._validate_base_folder_effects_structure(
            tasks, config, effect_key='effect', custom_effect_key='custom_effect'
        )

    def _make_api_call(self, file_path, task_config, attempt):
        """Make Kling Video Effects API call.
        
        Args:
            file_path: Path to the source image file.
            task_config: Dictionary containing effect configuration.
            attempt: Current retry attempt number.
        
        Returns:
            Tuple containing (url, video_dict, video_id, task_id, error).
        """
        # Custom effect has priority over preset effect (both from task_config only)
        custom_effect = task_config.get('custom_effect', '')
        effect = task_config.get('effect', '3d_cartoon_1')
        duration = task_config.get('duration', self.config.get('duration', 5))
        
        # Log which effect is being used
        if custom_effect:
            self.logger.info(f"   Using custom effect: {custom_effect}")
        else:
            self.logger.info(f"   Using preset effect: {effect}")
        
        return self.client.predict(
            image=handle_file(str(file_path)),
            duration=int(duration),
            custom_effect=custom_effect,
            effect=effect,
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Kling Video Effects API result.
        
        Args:
            result: API response tuple.
            file_path: Path to the source image.
            task_config: Dictionary containing effect configuration.
            output_folder: Path to save generated video.
            metadata_folder: Path to save metadata.
            base_name: Base filename without extension.
            file_name: Original filename with extension.
            start_time: Processing start timestamp.
            attempt: Current retry attempt number.
        
        Returns:
            bool: True if video was successfully generated and saved.
        """
        url, video_dict, video_id, task_id, error = result[:5]
        processing_time = time.time() - start_time
        
        self.logger.info(f" Video ID: {video_id}, Task ID: {task_id}")
        
        # Determine effect name for output file and metadata (from task_config only)
        custom_effect = task_config.get('custom_effect', '')
        effect = custom_effect if custom_effect else task_config.get('effect', '3d_cartoon_1')
        effect_safe = effect.replace(' ', '_').replace('-', '_')
        
        # Check for API error - dump all data to metadata if no video generated
        if error:
            self.logger.info(f" ❌ API Error: {error}")
            metadata = {
                'source_image': file_name,
                'effect': effect,
                'custom_effect': custom_effect,
                'duration': int(task_config.get('duration', self.config.get('duration', 5))),
                'video_id': video_id,
                'task_id': task_id,
                'output_url': url,
                'error': error,
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name,
                'raw_response': {
                    'url': url,
                    'video_dict': str(video_dict) if video_dict else None,
                    'video_id': video_id,
                    'task_id': task_id,
                    'error': error
                }
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                        metadata, {})
            return False
        
        # Try to save video
        output_video_name = f"{base_name}_{effect_safe}_effect.mp4"
        output_path = Path(output_folder) / output_video_name
        video_saved = False
        
        # Method 1: URL download
        if url:
            video_saved = self.processor.download_file(url, output_path)
        
        # Method 2: Local file copy
        if not video_saved and video_dict and 'video' in video_dict:
            local_path = Path(video_dict['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
        
        # If no video was saved, dump all data to metadata
        if not video_saved:
            self.logger.info(f" ❌ Failed to save video")
            metadata = {
                'source_image': file_name,
                'effect': effect,
                'custom_effect': custom_effect,
                'duration': int(task_config.get('duration', self.config.get('duration', 5))),
                'video_id': video_id,
                'task_id': task_id,
                'output_url': url,
                'error': 'Video download/save failed',
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name,
                'raw_response': {
                    'url': url,
                    'video_dict': str(video_dict) if video_dict else None,
                    'video_id': video_id,
                    'task_id': task_id,
                    'error': error
                }
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                        metadata, {})
            return False
        
        # Save success metadata
        metadata = {
            'source_image': file_name,
            'effect': effect,
            'custom_effect': custom_effect,
            'duration': int(task_config.get('duration', self.config.get('duration', 5))),
            'output_url': url,
            'video_id': video_id,
            'task_id': task_id,
            'generated_video': output_video_name,
            'attempts': attempt + 1,
            'success': True,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'api_name': self.api_name
        }
        
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                    metadata, {})
        self.logger.info(f" ✅ Generated: {output_video_name}")
        
        return video_saved
