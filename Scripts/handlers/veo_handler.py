"""Veo API Handler - Text-to-video generation."""
from pathlib import Path
import time
import shutil
from .base_handler import BaseAPIHandler


class VeoHandler(BaseAPIHandler):
    """
    Veo text-to-video handler.
    
    Veo is a text-to-video API that generates videos from text prompts only
    (no input image required).
    """
    
    def _make_api_call(self, file_path, task_config, attempt):
        """
        Make Veo API call.
        
        Note: file_path is ignored for Veo since it's text-to-video.
        """
        return self.client.predict(
            prompt=task_config.get('prompt', ''),
            model_id=task_config.get('model_id', self.api_defs.get('api_params', {}).get('model_id', 'veo-3.1-generate-001')),
            duration_seconds=task_config.get('duration_seconds', self.api_defs.get('api_params', {}).get('duration_seconds', 8)),
            aspect_ratio=task_config.get('aspect_ratio', self.api_defs.get('api_params', {}).get('aspect_ratio', '16:9')),
            resolution=task_config.get('resolution', self.api_defs.get('api_params', {}).get('resolution', '1080p')),
            compression_quality=task_config.get('compression_quality', self.api_defs.get('api_params', {}).get('compression_quality', 'optimized')),
            seed=task_config.get('seed', self.api_defs.get('api_params', {}).get('seed', 0)),
            negative_prompt=task_config.get('negative_prompt', ''),
            output_storage_uri=task_config.get('output_storage_uri', ''),
            enhance_prompt=task_config.get('enhance_prompt', self.api_defs.get('api_params', {}).get('enhance_prompt', True)),
            generate_audio=task_config.get('generate_audio', self.api_defs.get('api_params', {}).get('generate_audio', False)),
            person_generation=task_config.get('person_generation', self.api_defs.get('api_params', {}).get('person_generation', 'allow_all')),
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """
        Handle Veo API result.
        
        Args:
            result: Tuple containing (status_message, video_dict)
            file_path: Ignored for text-to-video
            task_config: Task configuration dict
            output_folder: Path to output folder
            metadata_folder: Path to metadata folder
            base_name: Base name for output files
            file_name: Ignored for text-to-video
            start_time: Processing start time
            attempt: Current attempt number
            
        Returns:
            bool: True if successful, False otherwise
        """
        status_message, video_dict = result
        processing_time = time.time() - start_time
        
        self.logger.info(f" Status: {status_message}")
        
        # Check if API returned an error in the status message
        if status_message and ('error' in status_message.lower() or 'failed' in status_message.lower()):
            self.logger.info(f" ❌ API Error: {status_message}")
            metadata = {
                'status_message': status_message,
                'error': status_message,
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1)
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, None, 
                                        metadata, task_config)
            return False
        
        # Try to save video
        output_path = Path(output_folder) / f"{base_name}_generated.mp4"
        video_saved = False
        
        # Extract video from video_dict
        if video_dict and isinstance(video_dict, dict) and 'video' in video_dict:
            local_path = Path(video_dict['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
                self.logger.info(f" ✅ Generated: {output_path.name}")
            else:
                self.logger.warning(f" ⚠️ Video file not found: {local_path}")
        
        # Save metadata
        metadata = {
            'status_message': status_message,
            'generated_video': output_path.name if video_saved else None,
            'attempts': attempt + 1,
            'success': video_saved,
            'processing_time_seconds': round(processing_time, 1)
        }
        
        # Add video metadata if available
        if video_dict and isinstance(video_dict, dict):
            if 'subtitles' in video_dict and video_dict['subtitles']:
                metadata['subtitles'] = str(video_dict['subtitles'])
        
        self.processor.save_metadata(Path(metadata_folder), base_name, None, 
                                    metadata, task_config)
        
        return video_saved
    
    def process_task(self, task, task_num, total_tasks):
        """
        Process entire Veo task.
        
        Veo is text-to-video, so we don't iterate over files.
        Each task generates one or more videos from a text prompt based on generation_count.
        """
        # Get output folder from task or create default
        output_folder = Path(task.get('output_folder', ''))
        if not output_folder.exists():
            output_folder.mkdir(parents=True, exist_ok=True)
        
        # Create metadata folder alongside output
        metadata_folder = output_folder.parent / "Metadata"
        if not metadata_folder.exists():
            metadata_folder.mkdir(parents=True, exist_ok=True)
        
        # Get style name and generation count
        style_name = task.get('style_name', f'Task{task_num}')
        task_count = task.get('generation_count')
        global_count = self.config.get('generation_count', 1)
        generation_count = task_count if task_count is not None else global_count
        
        # Ensure generation_count is at least 1
        if generation_count < 1:
            generation_count = 1
        
        task_name = task.get('prompt', '')[:50] + '...' if len(task.get('prompt', '')) > 50 else task.get('prompt', f'Task {task_num}')
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {style_name} ({generation_count} generations)")
        
        # Generate multiple videos if needed
        successful = 0
        skipped = 0
        for gen_num in range(1, generation_count + 1):
            # Check if this generation was already processed
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
                except (json.JSONDecodeError, IOError):
                    pass
            
            self.logger.info(f" 🎬 Generation {gen_num}/{generation_count}: {style_name}-{gen_num}")
            
            # Add generation number to task config
            task_with_gen = task.copy()
            task_with_gen['generation_number'] = gen_num
            task_with_gen['style_name'] = style_name
            
            # Process single text-to-video generation
            success = self.processor.process_file(None, task_with_gen, output_folder, metadata_folder)
            
            if success:
                successful += 1
            
            # Rate limiting between generations
            if gen_num < generation_count:
                time.sleep(self.api_defs.get('rate_limit', 5))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{generation_count} successful ({skipped} skipped)")
    
    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """
        Process a single Veo generation.
        
        Override to handle text-to-video (no input file).
        """
        # Get style name and generation number for naming
        style_name = task_config.get('style_name', 'veo_task')
        gen_num = task_config.get('generation_number', 1)
        
        # Create safe filename from style name
        safe_style = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in style_name)
        safe_style = safe_style.strip().replace(' ', '_')
        base_name = f"{safe_style}-{gen_num}"
        
        file_name = None  # No source file for text-to-video
        start_time = time.time()
        
        try:
            # Make API call (file_path is ignored)
            result = self._make_api_call(file_path, task_config, attempt)
            
            # Parse and save result
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
