"""Runway API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from PIL import Image
from .base_handler import BaseAPIHandler, ValidationError


class RunwayHandler(BaseAPIHandler):
    """Runway video processing handler."""

    def validate_file(self, file_path, file_type='image'):
        """Runway-specific reference image validation.

        Args:
            file_path: Path to the file to validate.
            file_type: 'image' or 'video'.

        Returns:
            tuple: (is_valid, reason_string)
        """
        if file_type == 'video':
            return super().validate_file(file_path, file_type)
        try:
            validation_rules = self.api_defs.get('validation', {})
            file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
            file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)
            min_dimensions = validation_rules.get('min_dimension', 300)

            with Image.open(file_path) as img:
                w, h = img.size
                if file_size_mb >= validation_rules.get('max_size_mb', 32):
                    return False, "Reference image > 32MB"
                if w < min_dimensions or h < min_dimensions:
                    return False, f"Reference image {w}x{h} too small"
                return True, f"Reference: {w}x{h}"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def validate_structure(self, tasks, config):
        """Validate Runway with video source and optional reference images.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        valid_tasks = []
        invalid_videos = []

        for i, task in enumerate(tasks, 1):
            folder = Path(task['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)

            use_comparison_template = task.get('use_comparison_template', False)
            reference_folder_path = task.get('reference_folder', '').strip()
            requires_reference = use_comparison_template or bool(reference_folder_path)

            reference_images = []
            if requires_reference:
                if reference_folder_path:
                    ref_folder = Path(reference_folder_path)
                else:
                    ref_folder = folder / "Reference"
                if not ref_folder.exists():
                    self.logger.warning(f"Missing reference folder {ref_folder}")
                    continue
                reference_images = self.processor._get_files_by_type(ref_folder, 'reference_image')
                if not reference_images:
                    self.logger.warning(f"Empty reference folder {ref_folder}")
                    continue

            video_files = self.processor._get_files_by_type(source_folder, 'video')
            if not video_files:
                self.logger.warning(f"Empty source folder {source_folder}")
                continue

            valid_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file), 'folder': str(folder),
                        'name': video_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count == 0:
                continue

            (folder / "Generated_Video").mkdir(exist_ok=True)
            (folder / "Metadata").mkdir(exist_ok=True)

            task['requires_reference'] = requires_reference
            if requires_reference:
                task['reference_images'] = reference_images

            valid_tasks.append(task)
            self.logger.info(
                f"Task {i}: {valid_count}/{len(video_files)} valid videos"
                + (f", {len(reference_images)} reference images" if requires_reference
                   else " (text-to-video mode)")
            )

        if invalid_videos:
            self.processor.write_invalid_report(invalid_videos, 'runway')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")
        return valid_tasks

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
