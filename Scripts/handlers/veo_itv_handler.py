"""Veo ITV API Handler - Image-to-video generation."""
from pathlib import Path
from gradio_client import handle_file
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class VeoItvHandler(BaseAPIHandler):
    """
    Veo image-to-video handler.
    
    Handles image-to-video generation where each style folder contains
    source images and generated videos are named based on the source image.
    """
    
    def _make_api_call(self, file_path, task_config, attempt):
        """
        Make Veo ITV API call.
        
        Args:
            file_path: Path to the source image.
            task_config: Task configuration dictionary.
            attempt: Current attempt number.
        
        Returns:
            API result tuple.
        """
        return self.client.predict(
            image=handle_file(str(file_path)),
            prompt=task_config.get('prompt', ''),
            model_id=task_config.get('model_id', self.api_defs.get('api_params', {}).get('model_id', 'veo-3.1-generate-001')),
            duration_seconds=task_config.get('duration_seconds', self.api_defs.get('api_params', {}).get('duration_seconds', 8)),
            aspect_ratio=task_config.get('aspect_ratio', self.api_defs.get('api_params', {}).get('aspect_ratio', '16:9')),
            resolution=task_config.get('resolution', self.api_defs.get('api_params', {}).get('resolution', '1080p')),
            compression_quality=task_config.get('compression_quality', self.api_defs.get('api_params', {}).get('compression_quality', 'optimized')),
            seed=task_config.get('seed', self.api_defs.get('api_params', {}).get('seed', 0)),
            negative_prompt=task_config.get('negative_prompt', ''),
            enhance_prompt=task_config.get('enhance_prompt', self.api_defs.get('api_params', {}).get('enhance_prompt', True)),
            generate_audio=task_config.get('generate_audio', self.api_defs.get('api_params', {}).get('generate_audio', False)),
            person_generation=task_config.get('person_generation', self.api_defs.get('api_params', {}).get('person_generation', 'allow_all')),
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """
        Handle Veo ITV API result.
        
        Args:
            result: Tuple containing (status_message, video_dict).
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
        status_message, video_dict = result
        processing_time = time.time() - start_time
        
        self.logger.info(f" Status: {status_message}")
        
        # Check if API returned an error in the status message
        if status_message and ('error' in status_message.lower() or 'failed' in status_message.lower()):
            self.logger.info(f" ❌ API Error: {status_message}")
            metadata = {
                'source_image': file_name,
                'status_message': status_message,
                'error': status_message,
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat()
            }
            self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                        metadata, task_config)
            return False
        
        # Get generation number for output filename
        gen_num = task_config.get('generation_number', 1)
        output_filename = f"{base_name}_{gen_num}.mp4"
        output_path = Path(output_folder) / output_filename
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
            'source_image': file_name,
            'status_message': status_message,
            'generated_video': output_filename if video_saved else None,
            'generation_number': gen_num,
            'attempts': attempt + 1,
            'success': video_saved,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'model_id': task_config.get('model_id', ''),
            'prompt': task_config.get('prompt', ''),
            'duration_seconds': task_config.get('duration_seconds', 8),
            'aspect_ratio': task_config.get('aspect_ratio', '16:9'),
            'resolution': task_config.get('resolution', '1080p')
        }
        
        # Add video metadata if available
        if video_dict and isinstance(video_dict, dict):
            if 'subtitles' in video_dict and video_dict['subtitles']:
                metadata['subtitles'] = str(video_dict['subtitles'])
        
        # Use generation-specific metadata file name
        gen_base_name = f"{base_name}_{gen_num}"
        self.processor.save_metadata(Path(metadata_folder), gen_base_name, file_name, 
                                    metadata, task_config)
        
        return video_saved
    
    def _get_generation_status(self, base_name, gen_num, metadata_folder):
        """
        Get detailed processing status for a specific generation.
        
        Args:
            base_name: Base name of the source file.
            gen_num: Generation number.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            tuple: (is_complete, status_reason) where:
                - is_complete: True if generation should be skipped
                - status_reason: 'success', 'failed_exhausted', or None if not complete
        """
        gen_base_name = f"{base_name}_{gen_num}"
        metadata_file = Path(metadata_folder) / f"{gen_base_name}_metadata.json"
        
        if metadata_file.exists():
            try:
                import json
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                # Skip if previous processing was successful
                if metadata.get('success', False):
                    return True, 'success'
                
                # Also skip if failed and exhausted all retries
                max_retries = self.api_defs.get('max_retries', 3)
                attempts = metadata.get('attempts', 0)
                if not metadata.get('success', False) and attempts >= max_retries:
                    return True, 'failed_exhausted'
                
                return False, None
            except (json.JSONDecodeError, IOError):
                return False, None
        return False, None
    
    def _is_generation_processed(self, base_name, gen_num, metadata_folder):
        """
        Check if a specific generation has already been processed.
        
        A generation is considered processed if:
        - It was successfully processed (success: True), OR
        - It failed but has exhausted all retry attempts (success: False, attempts >= max_retries)
        
        Args:
            base_name: Base name of the source file.
            gen_num: Generation number.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            bool: True if generation was processed, False otherwise.
        """
        is_complete, _ = self._get_generation_status(base_name, gen_num, metadata_folder)
        return is_complete
    
    def process_task(self, task, task_num, total_tasks):
        """
        Process entire Veo ITV task.
        
        Iterates over source images in the style folder and generates
        multiple videos per image based on generation_count.
        
        Args:
            task: Task configuration dictionary.
            task_num: Current task number.
            total_tasks: Total number of tasks.
        """
        # Get folder paths
        folder = Path(task.get('folder', ''))
        source_folder = folder / "Source"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"
        
        # Create folders if they don't exist
        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)
        
        # Get style name from folder name or task config
        style_name = task.get('style_name', folder.name)
        
        # Get generation count (task-level overrides global)
        task_count = task.get('generation_count')
        global_count = self.config.get('generation_count', 1)
        generation_count = task_count if task_count is not None else global_count
        
        # Ensure generation_count is at least 1
        if generation_count < 1:
            generation_count = 1
        
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {style_name}")
        
        # Get source images
        source_files = self.processor._get_files_by_type(source_folder, 'image')
        
        if not source_files:
            self.logger.warning(f" ⚠️ No source images found in {source_folder}")
            return
        
        self.logger.info(f" 📸 Found {len(source_files)} source images × {generation_count} generations = {len(source_files) * generation_count} total")
        
        # Process each source image
        successful = 0
        skipped = 0
        total_generations = len(source_files) * generation_count
        current = 0
        
        for file_path in source_files:
            base_name = file_path.stem
            file_name = file_path.name
            
            # Generate multiple videos for this image
            for gen_num in range(1, generation_count + 1):
                current += 1
                
                # Check if this generation was already processed (success or failed with exhausted retries)
                is_complete, status = self._get_generation_status(base_name, gen_num, metadata_folder)
                if is_complete:
                    if status == 'success':
                        self.logger.info(f" ⏭️ {current}/{total_generations}: {base_name}_{gen_num} (already processed)")
                        successful += 1
                    else:  # failed_exhausted
                        self.logger.info(f" ⏭️ {current}/{total_generations}: {base_name}_{gen_num} (failed - max retries reached)")
                    skipped += 1
                    continue
                
                self.logger.info(f" 🎬 {current}/{total_generations}: {file_name} → {base_name}_{gen_num}.mp4")
                
                # Create task config with generation number
                task_with_gen = task.copy()
                task_with_gen['generation_number'] = gen_num
                task_with_gen['style_name'] = style_name
                
                # Process single generation
                if self.processor.process_file(file_path, task_with_gen, output_folder, metadata_folder):
                    successful += 1
                
                # Rate limiting between generations
                if current < total_generations:
                    time.sleep(self.api_defs.get('rate_limit', 5))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{total_generations} successful ({skipped} skipped)")
