"""Kling Endframe API Handler - Generates videos from start and end images."""
from pathlib import Path
from gradio_client import handle_file
import time
import shutil
from .base_handler import BaseAPIHandler


class KlingEndframeHandler(BaseAPIHandler):
    """
    Kling Endframe handler for generating videos from start and end frame images.
    
    Processes image pairs (A and B) where A is the starting frame and B is the ending frame.
    Supports both A/B naming convention and sequential pairing mode.
    """
    
    def __init__(self, processor):
        """Initialize handler with sequential pairing support."""
        super().__init__(processor)
        self._source_file_indices = {}  # Track source file index for sequential pairing

    def validate_structure(self, tasks, config):
        """Validate Kling Endframe structure with image pairs.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        from .base_handler import ValidationError

        valid_tasks = []
        invalid_images = []

        for i, task in enumerate(tasks, 1):
            folder = Path(task['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_folder, 'image')
            if not image_files:
                self.logger.warning(f"⚠️ Task {i}: No images found in {source_folder}")
                continue

            pairs = self._group_endframe_pairs(image_files)
            if not pairs:
                self.logger.warning(f"⚠️ Task {i}: No valid image pairs found")
                continue

            valid_pairs = 0
            for start_img, end_img in pairs:
                start_valid, start_msg = self.validate_file(start_img, 'image')
                end_valid, end_msg = self.validate_file(end_img, 'image')
                if not start_valid:
                    invalid_images.append(f"{start_img}: {start_msg}")
                if not end_valid:
                    invalid_images.append(f"{end_img}: {end_msg}")
                if start_valid and end_valid:
                    valid_pairs += 1

            if valid_pairs > 0:
                (folder / "Generated_Video").mkdir(parents=True, exist_ok=True)
                (folder / "Metadata").mkdir(parents=True, exist_ok=True)
                valid_tasks.append(task)
                self.logger.info(f"✓ Task {i}: {valid_pairs}/{len(pairs)} valid image pairs")

        if invalid_images:
            self.processor.write_invalid_report(invalid_images, "kling_endframe")
            raise ValidationError(f"{len(invalid_images)} invalid images found")
        return valid_tasks

    @staticmethod
    def _group_endframe_pairs(all_images):
        """Group images into start/end pairs for Kling Endframe.

        Expects naming: "name_A resolution.ext" and "name_B resolution.ext"

        Args:
            all_images: List of Path objects for all images in folder.

        Returns:
            list: Sorted list of (start_image, end_image) tuples.
        """
        image_dict = {}
        for img_path in all_images:
            name = img_path.stem
            parts = name.rsplit('_', 1)
            if len(parts) != 2:
                continue
            name_parts = name.split()
            if len(name_parts) >= 2:
                resolution = name_parts[-1]
                base_name = ' '.join(name_parts[:-1])
            else:
                continue
            base_key = base_name.rsplit('_', 1)[0] + '_' + resolution
            frame_marker = parts[1].split()[0] if parts[1] else None
            if base_key not in image_dict:
                image_dict[base_key] = {}
            if frame_marker in ['A', 'B']:
                image_dict[base_key][frame_marker] = img_path
        pairs = []
        for base_key, frames in image_dict.items():
            if 'A' in frames and 'B' in frames:
                pairs.append((frames['A'], frames['B']))
        return sorted(pairs, key=lambda x: x[0].name)

    def process_task(self, task, task_num, total_tasks):
        """
        Override: Process image pairs instead of individual files.
        
        Args:
            task: Task configuration dictionary
            task_num: Current task number
            total_tasks: Total number of tasks
        """
        folder = Path(task.get('folder', task.get('folder_path', '')))
        source_folder = folder / "Source"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"
        
        # Create output directories if they don't exist
        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)
        
        task_name = folder.name
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {task_name}")
        
        # Get pairing mode and generation count
        pairing_mode = task.get('pairing_mode', 'ab_naming')  # 'ab_naming' or 'sequential'
        
        # Generation count: task-level overrides global config
        generation_count = task.get('generation_count')
        if generation_count is None:
            # Fall back to global config setting
            generation_count = self.config.get('generation_count', 1)
        
        # Get all image files and group into pairs
        all_images = self._get_task_files(task, source_folder)
        
        if pairing_mode == 'sequential':
            self.logger.info(f" 🔄 Using sequential pairing mode")
            image_pairs = self._group_sequential_pairs(all_images, str(folder))
        else:
            self.logger.info(f" 🔤 Using A/B naming convention pairing")
            image_pairs = self._group_image_pairs(all_images)
        
        if not image_pairs:
            self.logger.warning(f" ⚠️  No valid image pairs found in {source_folder}")
            return
        
        self.logger.info(f" 📸 Found {len(image_pairs)} image pairs")
        if generation_count > 1:
            self.logger.info(f" 🔁 Will generate {generation_count} videos per pair")
        
        # Process each pair
        successful = 0
        skipped = 0
        total_generations = len(image_pairs) * generation_count
        
        for pair_idx, (start_image, end_image) in enumerate(image_pairs, 1):
            # Check if pair was already processed (success or failed with exhausted retries)
            is_complete, status = self._get_processing_status(start_image, metadata_folder)
            if is_complete:
                if status == 'success':
                    self.logger.info(f" ⏭️ Pair {pair_idx}/{len(image_pairs)}: {start_image.name} (already processed)")
                    successful += generation_count
                else:  # failed_exhausted
                    self.logger.info(f" ⏭️ Pair {pair_idx}/{len(image_pairs)}: {start_image.name} (failed - max retries reached)")
                skipped += generation_count
                continue
            
            self.logger.info(f" 🖼️  Pair {pair_idx}/{len(image_pairs)}: {start_image.name} → {end_image.name}")
            
            # Generate multiple times if specified
            pair_successful = 0
            for gen_num in range(1, generation_count + 1):
                if generation_count > 1:
                    self.logger.info(f"   Generation {gen_num}/{generation_count}")
                
                # Create a modified task config with both images
                pair_task = task.copy()
                pair_task['end_image'] = str(end_image)
                pair_task['generation_number'] = gen_num
                pair_task['total_generations'] = generation_count
                
                if self.processor.process_file(start_image, pair_task, output_folder, metadata_folder):
                    pair_successful += 1
                    successful += 1
                
                # Rate limit between generations
                if gen_num < generation_count or pair_idx < len(image_pairs):
                    time.sleep(self.api_defs.get('rate_limit', 3))
            
            if generation_count > 1:
                self.logger.info(f"   ✓ Pair {pair_idx}: {pair_successful}/{generation_count} generations successful")
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{total_generations} total generations successful ({skipped} skipped)")
    
    def _group_image_pairs(self, all_images):
        """
        Group images into start/end pairs based on naming convention.
        
        Expects naming pattern: "name_A resolution.ext" and "name_B resolution.ext"
        
        Args:
            all_images: List of Path objects for all images in folder
            
        Returns:
            List of tuples: [(start_image_path, end_image_path), ...]
        """
        # Group images by base name and resolution
        image_dict = {}
        
        for img_path in all_images:
            name = img_path.stem  # e.g., "Anime Awakening_A 1024x1024"
            
            # Parse the name to extract: base_name, frame_marker (A/B), and resolution
            parts = name.rsplit('_', 1)
            if len(parts) != 2:
                continue
                
            base_with_res = parts[0]
            frame_marker = parts[1].split()[0] if parts[1] else None
            
            # Extract resolution from the end
            name_parts = name.split()
            if len(name_parts) >= 2:
                resolution = name_parts[-1]
                base_name = ' '.join(name_parts[:-1])
            else:
                continue
            
            # Create key: base_name + resolution (without A/B marker)
            base_key = base_name.rsplit('_', 1)[0] + '_' + resolution
            
            if base_key not in image_dict:
                image_dict[base_key] = {}
            
            if frame_marker in ['A', 'B']:
                image_dict[base_key][frame_marker] = img_path
        
        # Create pairs from grouped images
        pairs = []
        for base_key, frames in image_dict.items():
            if 'A' in frames and 'B' in frames:
                pairs.append((frames['A'], frames['B']))
            else:
                missing = 'A' if 'A' not in frames else 'B'
                self.logger.warning(f" ⚠️  Missing frame {missing} for {base_key}")
        
        # Sort pairs by name for consistent ordering
        pairs.sort(key=lambda x: x[0].name)
        
        return pairs
    
    def _group_sequential_pairs(self, all_images, folder_key):
        """
        Group images sequentially by sorted filename order.
        First half of images become start frames, second half become end frames.
        
        For example, with 6 images sorted alphabetically:
        - Images 1-3 are start frames
        - Images 4-6 are end frames
        - Pairs: (1,4), (2,5), (3,6)
        
        Args:
            all_images: List of Path objects for all images in folder
            folder_key: Unique key for this folder (for tracking indices)
            
        Returns:
            List of tuples: [(start_image_path, end_image_path), ...]
        """
        if not all_images:
            return []
        
        # Sort images by filename for consistent pairing
        sorted_images = sorted(all_images, key=lambda x: x.name.lower())
        
        # Build source file index for this task
        if folder_key not in self._source_file_indices:
            self._source_file_indices[folder_key] = {
                str(f): idx for idx, f in enumerate(sorted_images)
            }
            self.logger.info(f" 📝 Indexed {len(sorted_images)} images for sequential pairing")
        
        # Split into two halves
        total_count = len(sorted_images)
        half_count = total_count // 2
        
        if total_count < 2:
            self.logger.warning(f" ⚠️  Need at least 2 images for sequential pairing, found {total_count}")
            return []
        
        start_images = sorted_images[:half_count]
        end_images = sorted_images[half_count:half_count * 2]
        
        # Create pairs
        pairs = list(zip(start_images, end_images))
        
        self.logger.info(f" 🔗 Sequential pairing: {len(start_images)} start images → {len(end_images)} end images")
        if len(sorted_images) % 2 != 0:
            self.logger.warning(f" ⚠️  Odd number of images ({total_count}), last image will be unused")
        
        return pairs
    
    def _make_api_call(self, file_path, task_config, attempt):
        """
        Make Kling Endframe API call with both start and end images.
        
        Args:
            file_path: Path to the starting frame image (A)
            task_config: Task configuration containing end_image path
            attempt: Current attempt number
            
        Returns:
            API result tuple
        """
        end_image_path = task_config.get('end_image')
        if not end_image_path:
            raise ValueError("End image path not provided in task configuration")
        
        end_image_path = Path(end_image_path)
        if not end_image_path.exists():
            raise FileNotFoundError(f"End image not found: {end_image_path}")
        
        return self.client.predict(
            first_image=handle_file(str(file_path)),
            end_image=handle_file(str(end_image_path)),
            prompt=task_config['prompt'],
            mode=task_config.get('mode', 'pro'),
            duration=task_config.get('duration', '5'),
            cfg=task_config.get('cfg', 0.5),
            model=self.config.get('model_version', 'v2.1'),
            negative_prompt=task_config.get('negative_prompt', ''),
            api_name=self.api_defs['api_name']
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """
        Handle Kling Endframe API result.
        
        Args:
            result: API result tuple
            file_path: Path to the starting frame image
            task_config: Task configuration
            output_folder: Output directory path
            metadata_folder: Metadata directory path
            base_name: Base filename without extension
            file_name: Full filename with extension
            start_time: Processing start timestamp
            attempt: Current attempt number
            
        Returns:
            bool: True if successful, False otherwise
        """
        output_url, video_dict, video_id, task_id, error = result[:5]
        processing_time = time.time() - start_time
        
        self.logger.info(f" Video ID: {video_id}, Task ID: {task_id}")
        
        # Get generation info early for both filename and metadata
        gen_num = task_config.get('generation_number', 1)
        total_gens = task_config.get('total_generations', 1)
        
        # Adjust base_name to include generation number for multiple generations
        metadata_base_name = f"{base_name}_generated_{gen_num}" if total_gens > 1 else base_name
        
        # Check for API error
        if error:
            self.logger.info(f" ❌ API Error: {error}")
            
            metadata = {
                'start_image': file_name,
                'end_image': Path(task_config['end_image']).name,
                'video_id': video_id,
                'task_id': task_id,
                'error': error,
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1)
            }
            
            if total_gens > 1:
                metadata['generation_number'] = gen_num
                metadata['total_generations'] = total_gens
            
            self.processor.save_kling_metadata(Path(metadata_folder), metadata_base_name, file_name, 
                                              metadata, task_config)
            return False
        
        # Determine output filename (with generation number if multiple generations)
        if total_gens > 1:
            output_filename = f"{base_name}_generated_{gen_num}.mp4"
        else:
            output_filename = f"{base_name}_generated.mp4"
        
        output_path = Path(output_folder) / output_filename
        video_saved = False
        
        # Method 1: URL download
        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)
        
        # Method 2: Local file copy
        if not video_saved and video_dict and 'video' in video_dict:
            local_path = Path(video_dict['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
        
        # Save metadata
        metadata = {
            'start_image': file_name,
            'end_image': Path(task_config['end_image']).name,
            'output_url': output_url,
            'video_id': video_id,
            'task_id': task_id,
            'generated_video': output_path.name if video_saved else None,
            'attempts': attempt + 1,
            'success': video_saved,
            'processing_time_seconds': round(processing_time, 1)
        }
        
        # Add generation info if multiple generations
        if total_gens > 1:
            metadata['generation_number'] = gen_num
            metadata['total_generations'] = total_gens
        
        self.processor.save_kling_metadata(Path(metadata_folder), metadata_base_name, file_name, 
                                          metadata, task_config)
        
        if video_saved:
            self.logger.info(f" ✅ Generated: {output_path.name}")
        
        return video_saved
