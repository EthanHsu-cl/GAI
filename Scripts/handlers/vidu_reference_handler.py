"""Vidu Reference API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from PIL import Image
from .base_handler import BaseAPIHandler, ValidationError


class ViduReferenceHandler(BaseAPIHandler):
    """Vidu Reference handler."""

    def validate_structure(self, tasks, config):
        """Validate Vidu Reference with base_folder, Source and Reference per effect.

        Discovers effect subfolders under base_folder, matches to configured tasks,
        validates source and reference images, and detects aspect ratios.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries with image_sets.

        Raises:
            Exception: If validation errors are found.
        """
        base_folder = Path(config.get('base_folder', ''))
        base_folder.mkdir(parents=True, exist_ok=True)

        configured_tasks = {t['effect']: t for t in tasks}
        valid_tasks = []
        errors = []

        for task in tasks:
            effect_name = task.get('effect', '')
            if effect_name:
                task_folder = base_folder / effect_name
                task_folder.mkdir(parents=True, exist_ok=True)
                (task_folder / 'Source').mkdir(exist_ok=True)
                (task_folder / 'Reference').mkdir(exist_ok=True)

        for folder in base_folder.iterdir():
            if not (folder.is_dir() and not folder.name.startswith(('.', '_'))
                    and (folder / 'Source').exists() and (folder / 'Reference').exists()):
                continue

            if folder.name in configured_tasks:
                task = configured_tasks[folder.name].copy()
                task['folder_path'] = str(folder)
                self.logger.info(f"✓ Matched: {folder.name}")
            else:
                task = {
                    'effect': folder.name, 'folder_path': str(folder),
                    'prompt': config.get('default_prompt', ''),
                    'model': config.get('model', 'default'),
                    'duration': config.get('duration', 5),
                    'resolution': config.get('resolution', '1080p'),
                    'movement': config.get('movement', 'auto')
                }
                self.logger.info(f"⚠️ No config match: {folder.name} -> using defaults")

            result, task_errors = self._validate_reference_task(task, config)
            if result:
                valid_tasks.append(result)
            else:
                errors.extend(task_errors)

        if errors:
            for error in errors:
                self.logger.error(f"❌ {error}")
            raise Exception(f"{len(errors)} validation errors")
        return valid_tasks

    def _validate_reference_task(self, task, config):
        """Validate a single reference task with smart reference finding.

        Args:
            task: Task dictionary with 'folder_path' and 'effect' keys.
            config: Full processor configuration dictionary.

        Returns:
            tuple: (task_dict_or_None, list_of_errors)
        """
        fp = Path(task['folder_path'])
        src_dir, ref_dir = fp / 'Source', fp / 'Reference'

        if not (src_dir.exists() and ref_dir.exists()):
            return None, [f"{task['effect']}: Missing Source/Reference folders"]

        src_imgs = self.processor._get_files_by_type(src_dir, 'image')
        if not src_imgs:
            return None, [f"{task['effect']}: No source images"]

        ref_imgs = self._find_reference_images(ref_dir)
        if not ref_imgs:
            return None, [f"{task['effect']}: No reference images"]

        valid_sets = []
        for src in src_imgs:
            invalids = []
            try:
                with Image.open(src) as img:
                    ar = self._closest_aspect_ratio(img.width, img.height)
                    self.logger.info(f" 📐 {src.name} ({img.width}x{img.height}) → {ar}")
            except Exception as e:
                invalids.append(f"{src.name}: Cannot read dims - {e}")
                continue

            for img in [src] + ref_imgs:
                valid, reason = self.validate_file(img)
                if not valid:
                    invalids.append(f"{img.name}: {reason}")

            if not invalids:
                valid_sets.append({
                    'source_image': src, 'reference_images': ref_imgs,
                    'all_images': [src] + ref_imgs, 'aspect_ratio': ar,
                    'reference_count': len(ref_imgs)
                })
                self.logger.info(f" Found {len(ref_imgs)} reference images for {src.name}")

        if not valid_sets:
            return None, [f"{task['effect']}: No valid image sets"]

        for d in ['Generated_Video', 'Metadata']:
            (fp / d).mkdir(exist_ok=True)

        task.update({
            'generated_dir': str(fp / 'Generated_Video'),
            'metadata_dir': str(fp / 'Metadata'),
            'image_sets': valid_sets
        })
        return task, []

    def _find_reference_images(self, ref_dir):
        """Smart reference image finding with naming convention detection.

        Args:
            ref_dir: Path to the Reference directory.

        Returns:
            list: Sorted list of reference image Path objects.
        """
        refs = []
        file_types = self.api_defs['file_types']
        max_refs = self.api_defs.get('max_references', 6)

        for i in range(2, max_refs + 2):
            files = [f for f in ref_dir.iterdir()
                     if f.suffix.lower() in file_types and
                     (f.stem.lower().startswith(f'image{i}') or
                      f.stem.lower().startswith(f'image {i}') or
                      f.stem.split('_')[0] == str(i) or
                      f.stem.split('.')[0] == str(i))]
            if files:
                refs.append(files[0])
            else:
                break

        return refs or sorted([f for f in ref_dir.iterdir()
                               if f.suffix.lower() in file_types])[:max_refs]

    def _closest_aspect_ratio(self, w, h):
        """Detect closest supported aspect ratio.

        Args:
            w: Image width.
            h: Image height.

        Returns:
            str: Aspect ratio string (e.g. '16:9').
        """
        r = w / h
        aspect_ratios = self.api_defs.get('aspect_ratios', ["16:9", "9:16", "1:1"])
        if "16:9" in aspect_ratios and r > 1.2:
            return "16:9"
        elif "9:16" in aspect_ratios and r < 0.8:
            return "9:16"
        else:
            return "1:1"

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
