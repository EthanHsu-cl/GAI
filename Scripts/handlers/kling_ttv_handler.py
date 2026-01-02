"""Kling Text-to-Video API Handler."""
from pathlib import Path
import time
import shutil
from .base_handler import BaseAPIHandler


class KlingTTVHandler(BaseAPIHandler):
    """
    Kling Text-to-Video handler.
    
    Generates videos from text prompts using Kling's TextToVideo API.
    """
    
    def _make_api_call(self, file_path, task_config, attempt):
        """
        Make Kling TTV API call.
        
        Args:
            file_path: Ignored (text-to-video has no input file)
            task_config: Task configuration dict
            attempt: Current attempt number
            
        Returns:
            Tuple: (output_url, output_video_dict, video_id, task_id, error_msg)
        """
        return self.client.predict(
            prompt=task_config.get('prompt', ''),
            model=task_config.get('model', self.api_defs.get('api_params', {}).get('model', 'v1.6')),
            mode=task_config.get('mode', self.api_defs.get('api_params', {}).get('mode', 'std')),
            duration=task_config.get('duration', self.api_defs.get('api_params', {}).get('duration', '5')),
            ratio=task_config.get('ratio', self.api_defs.get('api_params', {}).get('ratio', '9:16')),
            cfg=task_config.get('cfg', self.api_defs.get('api_params', {}).get('cfg', 0.5)),
            neg_prompt=task_config.get('neg_prompt', self.api_defs.get('api_params', {}).get('neg_prompt', '')),
            sound_enabled=task_config.get('sound_enabled', self.api_defs.get('api_params', {}).get('sound_enabled', False)),
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """
        Handle Kling TTV API result.
        
        Args:
            result: Tuple containing (output_url, output_video_dict, video_id, task_id, error_msg)
            file_path: Ignored (text-to-video)
            task_config: Task configuration dict
            output_folder: Path to output folder
            metadata_folder: Path to metadata folder
            base_name: Base name for output files
            file_name: Ignored (text-to-video)
            start_time: Processing start time
            attempt: Current attempt number
            
        Returns:
            bool: True if successful, False otherwise
        """
        output_url, output_video, video_id, task_id, error_msg = result
        processing_time = time.time() - start_time
        
        self.logger.info(f" Video ID: {video_id}, Task ID: {task_id}")
        
        # Check for API error
        if error_msg:
            self.logger.info(f" ❌ API Error: {error_msg}")
            metadata = {
                'video_id': video_id,
                'task_id': task_id,
                'error': error_msg,
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
        
        # Method 1: Download from URL
        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)
            if video_saved:
                self.logger.info(f" ✅ Downloaded from URL: {output_path.name}")
        
        # Method 2: Copy from local file
        if not video_saved and output_video and isinstance(output_video, dict) and 'video' in output_video:
            local_path = Path(output_video['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
                self.logger.info(f" ✅ Copied from local: {output_path.name}")
            else:
                self.logger.warning(f" ⚠️ Video file not found: {local_path}")
        
        # Save metadata
        metadata = {
            'output_url': output_url,
            'video_id': video_id,
            'task_id': task_id,
            'generated_video': output_path.name if video_saved else None,
            'attempts': attempt + 1,
            'success': video_saved,
            'processing_time_seconds': round(processing_time, 1)
        }
        
        # Add subtitles if available
        if output_video and isinstance(output_video, dict) and 'subtitles' in output_video:
            if output_video['subtitles']:
                metadata['subtitles'] = str(output_video['subtitles'])
        
        self.processor.save_metadata(Path(metadata_folder), base_name, None, 
                                    metadata, task_config, log_status=True)
        
        return video_saved
    
    def process_task(self, task, task_num, total_tasks):
        """
        Process entire Kling TTV task.
        
        Each task generates one or more videos based on generation_count.
        """
        # Get root folder from config
        root_folder = Path(self.config.get('output_folder', ''))
        
        # Create Generated_Video and Metadata subdirectories
        output_folder = root_folder / "Generated_Video"
        metadata_folder = root_folder / "Metadata"
        
        if not output_folder.exists():
            output_folder.mkdir(parents=True, exist_ok=True)
        if not metadata_folder.exists():
            metadata_folder.mkdir(parents=True, exist_ok=True)
        
        # Get style name and generation count
        style_name = task.get('style_name', f'Task{task_num}')
        task_count = task.get('generation_count')
        global_count = self.config.get('generation_count', 1)
        generation_count = task_count if task_count is not None else global_count
        
        # Ensure at least 1 generation
        if generation_count < 1:
            generation_count = 1
        
        # Truncate prompt for display
        prompt_display = task.get('prompt', '')[:50]
        if len(task.get('prompt', '')) > 50:
            prompt_display += '...'
        
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
            
            # Add generation metadata to task config
            task_with_gen = task.copy()
            task_with_gen['generation_number'] = gen_num
            task_with_gen['style_name'] = style_name
            
            # Apply global settings with task-level override
            # Model
            if 'model' not in task_with_gen:
                task_with_gen['model'] = self.config.get('model', 'v2.5-turbo')
            
            # Links
            if 'design_link' not in task_with_gen:
                task_with_gen['design_link'] = self.config.get('design_link', '')
            if 'source_video_link' not in task_with_gen:
                task_with_gen['source_video_link'] = self.config.get('source_video_link', '')
            
            # Process single text-to-video generation
            success = self.processor.process_file(None, task_with_gen, output_folder, metadata_folder)
            
            if success:
                successful += 1
            
            # Rate limiting between generations
            if gen_num < generation_count:
                time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{generation_count} successful ({skipped} skipped)")
    
    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """
        Process a single Kling TTV generation.
        
        Override to handle text-to-video (no input file).
        """
        # Get style name and generation number for naming
        style_name = task_config.get('style_name', 'kling_ttv')
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
            # Save failure metadata for text-to-video (no file_path)
            processing_time = time.time() - start_time
            metadata = {
                'error': str(e),
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1)
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, None, 
                                        metadata, task_config)
            raise e
