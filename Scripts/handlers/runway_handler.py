"""Runway API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from .base_handler import BaseAPIHandler


class RunwayHandler(BaseAPIHandler):
    """Runway video processing handler."""
    
    def process_task(self, task, task_num, total_tasks):
        """Override: Handle video-reference pairing strategies."""
        folder = Path(task['folder'])
        self.logger.info(f"Task {task_num}/{total_tasks}: {folder.name}")
        
        source_folder = folder / "Source"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"
        
        video_files = self.processor._get_files_by_type(source_folder, 'video')
        requires_reference = task.get('requires_reference', False)
        
        successful = 0
        skipped = 0
        if requires_reference:
            reference_images = task.get('reference_images', [])
            pairing_strategy = task.get('pairing_strategy', 'one_to_one')
            
            if pairing_strategy == "all_combinations":
                total = len(video_files) * len(reference_images)
                for i, (video_file, ref_image) in enumerate(
                    [(v, r) for v in video_files for r in reference_images], 1):
                    
                    # Check if already processed (success or failed with exhausted retries)
                    is_complete, status = self._get_processing_status(video_file, metadata_folder)
                    if is_complete:
                        if status == 'success':
                            self.logger.info(f" ⏭️ {i}/{total}: {video_file.name} (already processed)")
                            successful += 1
                        else:  # failed_exhausted
                            self.logger.info(f" ⏭️ {i}/{total}: {video_file.name} (failed - max retries reached)")
                        skipped += 1
                        continue
                    
                    self.logger.info(f"{i}/{total}: {video_file.name} + {ref_image.name}")
                    task_config = task.copy()
                    task_config['reference_image'] = str(ref_image)
                    
                    if self.processor.process_file(str(video_file), task_config, output_folder, metadata_folder):
                        successful += 1
                    
                    if i < total:
                        time.sleep(self.api_defs.get('rate_limit', 3))
            else:  # one_to_one
                pairs = list(zip(video_files, reference_images))
                for i, (video_file, ref_image) in enumerate(pairs, 1):
                    # Check if already processed (success or failed with exhausted retries)
                    is_complete, status = self._get_processing_status(video_file, metadata_folder)
                    if is_complete:
                        if status == 'success':
                            self.logger.info(f" ⏭️ {i}/{len(pairs)}: {video_file.name} (already processed)")
                            successful += 1
                        else:  # failed_exhausted
                            self.logger.info(f" ⏭️ {i}/{len(pairs)}: {video_file.name} (failed - max retries reached)")
                        skipped += 1
                        continue
                    
                    self.logger.info(f"{i}/{len(pairs)}: {video_file.name} + {ref_image.name}")
                    task_config = task.copy()
                    task_config['reference_image'] = str(ref_image)
                    
                    if self.processor.process_file(str(video_file), task_config, output_folder, metadata_folder):
                        successful += 1
                    
                    if i < len(pairs):
                        time.sleep(self.api_defs.get('rate_limit', 3))
        else:
            # Text-to-video without reference
            for i, video_file in enumerate(video_files, 1):
                # Check if already processed (success or failed with exhausted retries)
                is_complete, status = self._get_processing_status(video_file, metadata_folder)
                if is_complete:
                    if status == 'success':
                        self.logger.info(f" ⏭️ {i}/{len(video_files)}: {video_file.name} (already processed)")
                        successful += 1
                    else:  # failed_exhausted
                        self.logger.info(f" ⏭️ {i}/{len(video_files)}: {video_file.name} (failed - max retries reached)")
                    skipped += 1
                    continue
                
                self.logger.info(f"{i}/{len(video_files)}: {video_file.name} (text-to-video)")
                
                if self.processor.process_file(str(video_file), task, output_folder, metadata_folder):
                    successful += 1
                
                if i < len(video_files):
                    time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(f"Task {task_num}: {successful} successful ({skipped} skipped)")
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Make Runway API call."""
        video_info = self.processor._get_video_info(file_path)
        optimal_ratio = self.processor.get_optimal_runway_ratio(
            video_info['width'], video_info['height']) if video_info else '1280:720'
        
        reference_image_path = task_config.get('reference_image')
        
        return self.client.predict(
            video_path={"video": handle_file(str(file_path))},
            prompt=task_config['prompt'],
            model=self.config.get('model', 'gen4_aleph'),
            ratio=optimal_ratio,
            reference_image=handle_file(str(reference_image_path)) if reference_image_path else None,
            public_figure_moderation=self.config.get('public_figure_moderation', 'low'),
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Runway API result."""
        output_url = result[0] if len(result) > 0 else None
        
        if not output_url:
            return False
        
        # Generate output filename
        reference_image_path = task_config.get('reference_image')
        if reference_image_path:
            ref_stem = Path(reference_image_path).stem
            output_filename = f"{base_name}_ref_{ref_stem}_runway_generated.mp4"
        else:
            output_filename = f"{base_name}_text_runway_generated.mp4"
        
        output_path = Path(output_folder) / output_filename
        video_saved = self.processor.download_file(output_url, output_path)
        
        # Save metadata
        processing_time = time.time() - start_time
        video_info = self.processor._get_video_info(file_path)
        
        metadata = {
            'source_dimensions': f"{video_info['width']}x{video_info['height']}" if video_info else "unknown",
            'reference_image': Path(reference_image_path).name if reference_image_path else None,
            'prompt': task_config['prompt'],
            'output_url': output_url,
            'generated_video': output_filename,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'attempts': attempt + 1,
            'success': video_saved,
            'api_name': self.api_name,
            'generation_type': 'image_to_video' if reference_image_path else 'text_to_video'
        }
        
        ref_stem = Path(reference_image_path).stem if reference_image_path else ''
        self.processor.save_runway_metadata(
            Path(metadata_folder), base_name, ref_stem, file_name,
            Path(reference_image_path).name if reference_image_path else None,
            metadata, task_config)
        
        if video_saved:
            self.logger.info(f"Generated {output_filename}")
        
        return video_saved
