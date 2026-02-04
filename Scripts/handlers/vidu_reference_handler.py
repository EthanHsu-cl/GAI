"""Vidu Reference API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from .base_handler import BaseAPIHandler


class ViduReferenceHandler(BaseAPIHandler):
    """Vidu Reference handler."""
    
    def process_task(self, task, task_num, total_tasks):
        """Override: Process image sets instead of individual files."""
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {task['effect']}")
        
        generated_dir = Path(task['generated_dir'])
        metadata_dir = Path(task['metadata_dir'])
        
        successful = 0
        skipped = 0
        total_sets = len(task['image_sets'])
        
        for i, image_set in enumerate(task['image_sets'], 1):
            source_image = image_set['source_image']
            
            # Check if file was already processed (success or failed with exhausted retries)
            is_complete, status = self._get_processing_status(source_image, metadata_dir)
            if is_complete:
                if status == 'success':
                    self.logger.info(f" ⏭️ {i}/{total_sets}: {source_image.name} (already processed)")
                    successful += 1
                else:  # failed_exhausted
                    self.logger.info(f" ⏭️ {i}/{total_sets}: {source_image.name} (failed - max retries reached)")
                skipped += 1
                continue
            
            self.logger.info(f" 🖼️ {i}/{total_sets}: {source_image.name} + {image_set['reference_count']} refs")
            
            # Create task config with reference images
            ref_task = task.copy()
            ref_task['reference_images'] = [str(ref) for ref in image_set['reference_images']]
            ref_task['aspect_ratio'] = image_set['aspect_ratio']
            
            if self.processor.process_file(source_image, ref_task, generated_dir, metadata_dir):
                successful += 1
            
            if i < total_sets:
                time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{total_sets} successful ({skipped} skipped)")
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Make Vidu Reference API call."""
        reference_images = task_config.get('reference_images', [])
        if not reference_images:
            raise Exception("No reference images provided")
        
        # Prepare all image handles
        all_images = [file_path] + [Path(ref) for ref in reference_images]
        img_handles = tuple(handle_file(str(img)) for img in all_images)
        
        # Get parameters
        effect = task_config.get('effect', '')
        prompt = task_config.get('prompt', '') or self.config.get('default_prompt', '')
        model = task_config.get('model', self.config.get('model', 'default'))
        duration = task_config.get('duration', self.config.get('duration', 5))
        aspect_ratio = task_config.get('aspect_ratio', '1:1')
        resolution = task_config.get('resolution', self.config.get('resolution', '1080p'))
        movement = task_config.get('movement', self.config.get('movement', 'auto'))
        
        self.logger.info(f" 📸 Processing: 1 source + {len(reference_images)} references ({aspect_ratio})")
        
        return self.client.predict(
            model=model,
            prompt=prompt,
            duration=duration,
            aspect_ratio=aspect_ratio,
            images=img_handles,
            resolution=resolution,
            movement=movement,
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Vidu Reference API result."""
        if not isinstance(result, tuple) or len(result) < 4:
            raise ValueError("Invalid API response format")
        
        all_fields = self.processor._capture_all_api_fields(
            result, ['video_url', 'thumbnail_url', 'task_id', 'error_msg'])
        
        video_url = all_fields.get('video_url')
        error_msg = all_fields.get('error_msg')
        
        if error_msg:
            raise ValueError(f"API error: {error_msg}")
        
        if not video_url:
            raise ValueError("No video URL returned")
        
        # Download video
        effect = task_config.get('effect', '')
        effect_clean = effect.replace(' ', '_').replace('-', '_')
        output_filename = f"{base_name}_{effect_clean}.mp4"
        output_path = Path(output_folder) / output_filename
        
        if not self.processor.download_file(video_url, output_path):
            raise IOError("Video download failed")
        
        # Save success metadata
        processing_time = time.time() - start_time
        reference_images = task_config.get('reference_images', [])
        
        metadata = {
            "reference_images": [Path(ref).name for ref in reference_images],
            "reference_count": len(reference_images),
            "total_images": len(reference_images) + 1,
            "effect_name": effect,
            "model": task_config.get('model', ''),
            "prompt": task_config.get('prompt', ''),
            "duration": task_config.get('duration', 5),
            "aspect_ratio": task_config.get('aspect_ratio', '1:1'),
            "resolution": task_config.get('resolution', '1080p'),
            "movement": task_config.get('movement', 'auto'),
            "generated_video": output_filename,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "attempts": attempt + 1,
            "success": True,
            "api_name": self.api_name,
            **all_fields
        }
        
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                    metadata, task_config)
        self.logger.info(f" ✅ Generated: {output_filename}")
        
        return True
