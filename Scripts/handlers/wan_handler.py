"""Wan 2.2 API Handler - Image cropping and cross-matching logic."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from .base_handler import BaseAPIHandler


class WanHandler(BaseAPIHandler):
    """
    Wan 2.2 handler.
    
    Processes images and videos through a two-step workflow:
    1. Crop images to match video aspect ratios
    2. Generate animated videos using cropped images and source videos
    
    Cross-matches all images with all videos (e.g., 4 images × 5 videos = 20 generations).
    """
    
    def process_task(self, task, task_num, total_tasks):
        """Override: Handle image-video cross-matching with cropping step."""
        folder = Path(task['folder'])
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {folder.name}")
        
        source_image_folder = folder / "Source Image"
        source_video_folder = folder / "Source Video"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"
        
        # Get all images and videos
        image_files = self.processor._get_files_by_type(source_image_folder, 'image')
        video_files = self.processor._get_files_by_type(source_video_folder, 'video')
        
        if not image_files:
            self.logger.warning(f"⚠️ No images found in {source_image_folder}")
            return
        
        if not video_files:
            self.logger.warning(f"⚠️ No videos found in {source_video_folder}")
            return
        
        # Cross-match: all combinations (video-first ordering to match report slides)
        total_combinations = len(image_files) * len(video_files)
        self.logger.info(
            f"🔄 Cross-matching {len(video_files)} videos × {len(image_files)} images "
            f"= {total_combinations} generations"
        )
        
        successful = 0
        skipped = 0
        combination_num = 0
        max_retries = self.api_defs.get('max_retries', 3)
        
        for video_file in video_files:
            for image_file in image_files:
                combination_num += 1
                
                # Check if this combination was already processed
                # Use video_image ordering to match success metadata naming
                combo_base = f"{video_file.stem}_{image_file.stem}"
                combo_metadata = metadata_folder / f"{combo_base}_metadata.json"
                if combo_metadata.exists():
                    try:
                        import json
                        with open(combo_metadata, 'r') as f:
                            meta = json.load(f)
                        # Skip if successful OR if failed and exhausted all retries
                        if meta.get('success', False):
                            self.logger.info(
                                f" ⏭️ {combination_num}/{total_combinations}: "
                                f"{image_file.name} + {video_file.name} (already processed)"
                            )
                            skipped += 1
                            successful += 1
                            continue
                        attempts = meta.get('attempts', 0)
                        if not meta.get('success', False) and attempts >= max_retries:
                            self.logger.info(
                                f" ⏭️ {combination_num}/{total_combinations}: "
                                f"{image_file.name} + {video_file.name} (failed - max retries reached)"
                            )
                            skipped += 1
                            continue
                    except (json.JSONDecodeError, IOError):
                        pass
                
                self.logger.info(
                    f" 🎬 {combination_num}/{total_combinations}: "
                    f"{image_file.name} + {video_file.name}"
                )
                
                # Create task config with both files
                combined_task = task.copy()
                combined_task['image_file'] = str(image_file)
                combined_task['video_file'] = str(video_file)
                
                if self.processor.process_file(
                    str(image_file), combined_task, output_folder, metadata_folder
                ):
                    successful += 1
                
                # Rate limiting between combinations
                if combination_num < total_combinations:
                    time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{total_combinations} successful ({skipped} skipped)")
    
    def _make_api_call(self, file_path, task_config, attempt):
        """
        Make Wan 2.2 API call.
        
        Two-step process:
        1. Crop image to video aspect ratio using /fn_update_cropped_image
        2. Generate animation using /fn_wan_animate
        
        Args:
            file_path: Path to source image
            task_config: Task configuration containing video_file and parameters
            attempt: Current retry attempt number
            
        Returns:
            API result tuple (video output, designer config)
        """
        image_path = Path(file_path)
        video_path = Path(task_config['video_file'])
        
        # Step 1: Crop image to video aspect ratio
        self.logger.info(f" 🔧 Step 1/2: Cropping {image_path.name} to match {video_path.name}")
        
        cropped_result = self.client.predict(
            image=handle_file(str(image_path)),
            video={"video": handle_file(str(video_path)), "subtitles": None},
            api_name="/fn_update_cropped_image"
        )
        
        if not cropped_result:
            raise ValueError("Image cropping failed - no result returned")
        
        # Extract cropped image path from result
        cropped_image_path = None
        if isinstance(cropped_result, dict) and 'path' in cropped_result:
            cropped_image_path = cropped_result['path']
        elif isinstance(cropped_result, str):
            cropped_image_path = cropped_result
        else:
            raise ValueError(f"Unexpected cropped image format: {type(cropped_result)}")
        
        self.logger.info(f" ✓ Cropped image ready")
        
        # Step 2: Generate animation
        self.logger.info(f" 🎨 Step 2/2: Generating animation")
        
        prompt = task_config.get('prompt', '')
        embed = task_config.get('embed', 'Hello!!')
        num_outputs = task_config.get('num_outputs', 1)
        seed = task_config.get('seed', '-1')
        animation_mode = task_config.get('animation_mode', 'move')
        
        result = self.client.predict(
            video={"video": handle_file(str(video_path)), "subtitles": None},
            image=handle_file(cropped_image_path),
            prompt=prompt,
            embed=embed,
            _=num_outputs,
            seed=seed,
            animation_mode=animation_mode,
            api_name="/fn_wan_animate"
        )
        
        return result
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """
        Handle Wan 2.2 API result.
        
        Args:
            result: API result tuple (video_dict, designer_config)
            file_path: Source image path
            task_config: Task configuration
            output_folder: Output video directory
            metadata_folder: Metadata directory
            base_name: Base filename without extension
            file_name: Full source filename
            start_time: Processing start timestamp
            attempt: Current retry attempt
            
        Returns:
            bool: True if processing succeeded, False otherwise
        """
        if not isinstance(result, tuple) or len(result) < 2:
            raise ValueError(f"Invalid API response format: expected tuple, got {type(result)}")
        
        video_dict, designer_config = result[0], result[1]
        
        # Helper to save failure metadata for early exits
        def _save_fail_meta(error_reason):
            meta = {
                "source_image": Path(file_path).name,
                "source_video": Path(task_config['video_file']).name,
                "error": error_reason,
                "attempts": attempt + 1,
                "success": False,
                "processing_time_seconds": round(time.time() - start_time, 1),
                "processing_timestamp": datetime.now().isoformat(),
                "api_name": self.api_name,
            }
            image_n = Path(file_path).stem
            video_n = Path(task_config['video_file']).stem
            self.processor.save_metadata(
                Path(metadata_folder), f"{video_n}_{image_n}",
                file_name, meta, task_config,
            )

        # Extract video path
        video_path = None
        if video_dict is None:
            self.logger.warning(
                f"   ⚠️ API returned None video — generation failed, will retry"
            )
            _save_fail_meta("API returned None video")
            return False
        elif isinstance(video_dict, dict) and 'video' in video_dict:
            video_path = video_dict['video']
        elif isinstance(video_dict, str):
            video_path = video_dict
        else:
            self.logger.warning(
                f"   ⚠️ Unexpected video format: {type(video_dict)} — will retry"
            )
            _save_fail_meta(f"Unexpected video format: {type(video_dict)}")
            return False
        
        if not video_path:
            self.logger.warning("   ⚠️ Empty video path returned — will retry")
            _save_fail_meta("Empty video path returned")
            return False
        
        # Generate output filename (video-first ordering)
        image_name = Path(file_path).stem
        video_name = Path(task_config['video_file']).stem
        animation_mode = task_config.get('animation_mode', 'move')
        
        output_filename = f"{video_name}_{image_name}_{animation_mode}.mp4"
        output_path = Path(output_folder) / output_filename
        
        # Handle video file (either URL or local path)
        video_source = Path(video_path)
        if video_source.exists():
            # Local file - copy directly
            import shutil
            shutil.copy2(video_source, output_path)
            self.logger.info(f" 📥 Copied local file: {video_source}")
        else:
            # Remote URL - download
            if not self.processor.download_file(video_path, output_path):
                raise IOError(f"Failed to download video from {video_path}")
        
        # Save success metadata
        processing_time = time.time() - start_time
        
        metadata = {
            "source_image": Path(file_path).name,
            "source_video": Path(task_config['video_file']).name,
            "prompt": task_config.get('prompt', ''),
            "embed": task_config.get('embed', 'Hello!!'),
            "num_outputs": task_config.get('num_outputs', 2),
            "seed": task_config.get('seed', '-1'),
            "animation_mode": task_config.get('animation_mode', 'move'),
            "designer_config": designer_config,
            "generated_video": output_filename,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "attempts": attempt + 1,
            "success": True,
            "api_name": self.api_name
        }
        
        self.processor.save_metadata(
            Path(metadata_folder), 
            f"{video_name}_{image_name}", 
            file_name,
            metadata, 
            task_config
        )
        
        self.logger.info(f" ✅ Generated: {output_filename}")
        
        return True

    def _save_failure(self, file_path, task_config, metadata_folder, error,
                      attempt, start_time):
        """
        Override failure metadata to use combo naming.

        Uses {video_stem}_{image_stem} to match success metadata so the
        skip/continue logic can find both success and failure records.

        Args:
            file_path: Source image path.
            task_config: Task configuration with video_file key.
            metadata_folder: Metadata directory.
            error: Error message string.
            attempt: Current retry attempt.
            start_time: Processing start timestamp.
        """
        image_name = Path(file_path).stem
        video_file = task_config.get('video_file', '')
        video_name = Path(video_file).stem if video_file else 'unknown'
        combo_base = f"{video_name}_{image_name}"

        processing_time = time.time() - start_time
        metadata = {
            "source_image": Path(file_path).name,
            "source_video": Path(video_file).name if video_file else "",
            "error": error,
            "attempts": attempt + 1,
            "success": False,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "api_name": self.api_name,
        }

        self.processor.save_metadata(
            Path(metadata_folder),
            combo_base,
            Path(file_path).name,
            metadata,
            task_config,
        )

    def _get_source_field(self):
        """Override: Wan uses both images and videos."""
        return "source_image"
