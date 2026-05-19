"""FIFA Image-to-Image-to-Video API Handler.

Multi-step pipeline:
  1. (Optional) /on_generate_frame    → start frame from ref image + start_frame_prompt
  2. (Optional) /on_generate_frame_1  → end   frame from ref image + end_frame_prompt
  3. /on_generate_video                → video from start &/ end frames + video_prompt

Per-task flags `generate_start` / `generate_end` control which frames are produced.
If a flag is False, the corresponding frame is left empty when calling video generation.
"""
from pathlib import Path
from gradio_client import handle_file
import time
import shutil
from datetime import datetime
from .base_handler import BaseAPIHandler


class FifaI2i2vHandler(BaseAPIHandler):
    """FIFA image-to-image-to-video pipeline handler.

    Class name uses I2i2v (not I2I2v) so the registry's CamelCase→snake_case
    conversion yields `fifa_i2i2v` rather than `fifa_i2_i2v`.
    """

    def validate_structure(self, tasks, config):
        """Validate folder structure with Source images and prepare enhanced tasks."""
        valid_tasks = []
        invalid_images = []

        for i, task in enumerate(tasks, 1):
            if not task.get('generate_start', True) and not task.get('generate_end', False):
                if not task.get('video_prompt'):
                    self.logger.warning(f"⚠️ Task {i}: Missing video_prompt")
                    continue

            folder = Path(task.get('folder', ''))
            if not folder or str(folder) == '':
                self.logger.warning(f"⚠️ Task {i}: Missing folder path")
                continue

            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)

            image_files = self.processor._get_files_by_type(source_folder, 'image')
            if not image_files:
                self.logger.warning(f"⚠️ Task {i}: No images found in {source_folder}")
                continue

            valid_count = 0
            for img_file in image_files:
                is_valid, reason = self.validate_file(img_file)
                if not is_valid:
                    invalid_images.append({
                        'folder': folder.name, 'filename': img_file.name, 'reason': reason
                    })
                else:
                    valid_count += 1

            if valid_count == 0:
                self.logger.warning(f"⚠️ Task {i}: No valid images in {source_folder}")
                continue

            output_folder = folder / "Generated_Video"
            frames_folder = folder / "Generated_Frames"
            metadata_folder = folder / "Metadata"
            output_folder.mkdir(parents=True, exist_ok=True)
            frames_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)

            task_count = task.get('generation_count')
            global_count = config.get('generation_count', 1)
            generation_count = task_count if task_count is not None else global_count

            enhanced_task = task.copy()
            enhanced_task.update({
                'folder': str(folder),
                'folder_name': folder.name,
                'style_name': task.get('style_name', folder.name),
                'source_dir': str(source_folder),
                'generated_dir': str(output_folder),
                'frames_dir': str(frames_folder),
                'metadata_dir': str(metadata_folder),
                'generation_count': generation_count,
                'task_num': i
            })
            valid_tasks.append(enhanced_task)
            total_expected = valid_count * generation_count
            self.logger.info(
                f"✓ Task {i}: {valid_count} images × {generation_count} generations = {total_expected} videos"
            )

        if invalid_images:
            self.processor.write_invalid_report(invalid_images, "fifa_i2i2v")
            self.logger.warning(f"⚠️ {len(invalid_images)} invalid images found (see report)")

        if not valid_tasks:
            raise Exception("No valid FIFA I2I2V tasks found")
        return valid_tasks

    def _generate_frame(self, ref_image_path, prompt, model, endpoint):
        """Call /on_generate_frame or /on_generate_frame_1 to produce a single frame.

        Args:
            ref_image_path: Path to source/reference image.
            prompt: Frame generation prompt.
            model: Image generation model.
            endpoint: '/on_generate_frame' or '/on_generate_frame_1'.

        Returns:
            tuple: (frame_dict, debug_text) where frame_dict has 'path'/'url' keys
                   suitable for passing as start_output/end_output.
        """
        result = self.client.predict(
            model=model,
            prompt=prompt,
            ref_image=handle_file(str(ref_image_path)),
            api_name=endpoint
        )
        if isinstance(result, tuple):
            frame_dict = result[0] if len(result) > 0 else None
            debug_text = result[1] if len(result) > 1 else ''
        else:
            frame_dict = result
            debug_text = ''
        return frame_dict, debug_text

    def _save_frame(self, frame_dict, frames_folder, base_name, gen_num, role):
        """Save a generated frame to the Generated_Frames folder.

        Args:
            frame_dict: Dict returned from /on_generate_frame with 'path' or 'url'.
            frames_folder: Path to save into.
            base_name: Source filename stem.
            gen_num: Generation number.
            role: 'start' or 'end'.

        Returns:
            Optional[Path]: Saved file path, or None on failure.
        """
        if not frame_dict or not isinstance(frame_dict, dict):
            return None

        out_path = Path(frames_folder) / f"{base_name}_{gen_num}_{role}.png"
        url = frame_dict.get('url')
        local_path = frame_dict.get('path')

        if url:
            if self.processor.download_file(url, out_path):
                return out_path
        if local_path:
            src = Path(local_path)
            if src.exists():
                shutil.copy2(src, out_path)
                return out_path
        return None

    def _frame_to_input(self, frame_dict):
        """Convert a frame dict from /on_generate_frame into a handle_file input.

        The output of /on_generate_frame is dict(path, url, size, ...). When
        re-used as input to /on_generate_video, the gradio client serializes
        a raw dict to just its path string, which the server rejects
        ("Input should be a valid dictionary or instance of ImageData").
        Wrapping the path/url with handle_file() produces a proper FileData
        payload the server accepts.
        """
        if not frame_dict or not isinstance(frame_dict, dict):
            return None
        url = frame_dict.get('url')
        path = frame_dict.get('path')
        target = url or path
        return handle_file(target) if target else None

    def _make_api_call(self, file_path, task_config, attempt):
        """Run the full image→frames→video pipeline for a single source image."""
        default_settings = self.config.get("default_settings", {})

        generate_start = task_config.get('generate_start', default_settings.get('generate_start', True))
        generate_end = task_config.get('generate_end', default_settings.get('generate_end', False))

        if not generate_start and not generate_end:
            raise ValueError("At least one of generate_start or generate_end must be True")

        frame_model = task_config.get('frame_model', default_settings.get('frame_model', 'gemini-3-pro-image-preview'))

        start_frame = None
        end_frame = None
        start_debug = ''
        end_debug = ''

        if generate_start:
            start_prompt = task_config.get('start_frame_prompt', '')
            if not start_prompt:
                raise ValueError("generate_start is True but start_frame_prompt is empty")
            self.logger.info(f"   🖼️ Generating start frame (model={frame_model})")
            start_frame, start_debug = self._generate_frame(
                file_path, start_prompt, frame_model, '/on_generate_frame'
            )
            if not start_frame:
                raise RuntimeError(f"Start frame generation returned no output: {start_debug}")

        if generate_end:
            end_prompt = task_config.get('end_frame_prompt', '')
            if not end_prompt:
                raise ValueError("generate_end is True but end_frame_prompt is empty")
            self.logger.info(f"   🖼️ Generating end frame (model={frame_model})")
            end_frame, end_debug = self._generate_frame(
                file_path, end_prompt, frame_model, '/on_generate_frame_1'
            )
            if not end_frame:
                raise RuntimeError(f"End frame generation returned no output: {end_debug}")

        service = task_config.get('service', default_settings.get('service', 'kling'))
        model = task_config.get('model', default_settings.get('model', 'v3'))

        start_input = self._frame_to_input(start_frame)
        end_input = self._frame_to_input(end_frame)

        self.logger.info(f"   🎬 Generating video (service={service}, model={model})")
        video_result = self.client.predict(
            service=service,
            model=model,
            start_output=start_input,
            end_output=end_input,
            prompt=task_config.get('video_prompt', ''),
            wan_resolution=task_config.get('wan_resolution', default_settings.get('wan_resolution', '1080P')),
            wan_duration=task_config.get('wan_duration', default_settings.get('wan_duration', 5)),
            pv_duration=task_config.get('pv_duration', default_settings.get('pv_duration', 5)),
            pv_motion=task_config.get('pv_motion', default_settings.get('pv_motion', 'normal')),
            pv_quality=task_config.get('pv_quality', default_settings.get('pv_quality', '540p')),
            kling_mode=task_config.get('kling_mode', default_settings.get('kling_mode', 'pro')),
            kling_duration=int(task_config.get('kling_duration', default_settings.get('kling_duration', 5))),
            kling_ratio=task_config.get('kling_ratio', default_settings.get('kling_ratio', '16:9')),
            veo_duration=task_config.get('veo_duration', default_settings.get('veo_duration', 8)),
            veo_aspect=task_config.get('veo_aspect', default_settings.get('veo_aspect', '16:9')),
            veo_resolution=task_config.get('veo_resolution', default_settings.get('veo_resolution', '1080p')),
            sd_duration=task_config.get('sd_duration', default_settings.get('sd_duration', 5)),
            sd_ratio=task_config.get('sd_ratio', default_settings.get('sd_ratio', '16:9')),
            sd_resolution=task_config.get('sd_resolution', default_settings.get('sd_resolution', '720p')),
            api_name=self.api_defs['api_name']
        )

        return {
            'video_result': video_result,
            'start_frame': start_frame,
            'end_frame': end_frame,
            'start_debug': start_debug,
            'end_debug': end_debug,
        }

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Save video, generated frames, and metadata."""
        video_result = result['video_result']
        start_frame = result.get('start_frame')
        end_frame = result.get('end_frame')

        if isinstance(video_result, tuple):
            video_dict = video_result[0] if len(video_result) > 0 else None
            debug_info = video_result[1] if len(video_result) > 1 else ''
        else:
            video_dict = video_result
            debug_info = ''

        processing_time = time.time() - start_time
        gen_num = task_config.get('generation_number', 1)
        style_name = task_config.get('style_name', 'fifa_i2i2v')
        default_settings = self.config.get("default_settings", {})
        frames_folder = Path(task_config.get('frames_dir', Path(output_folder).parent / "Generated_Frames"))
        frames_folder.mkdir(parents=True, exist_ok=True)

        saved_start = self._save_frame(start_frame, frames_folder, base_name, gen_num, 'start') if start_frame else None
        saved_end = self._save_frame(end_frame, frames_folder, base_name, gen_num, 'end') if end_frame else None

        output_filename = f"{base_name}_{gen_num}.mp4"
        output_path = Path(output_folder) / output_filename
        video_saved = False

        if video_dict and isinstance(video_dict, dict) and 'video' in video_dict:
            local_path = Path(video_dict['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
                self.logger.info(f"   ✅ Generated: {output_path.name}")

        service = task_config.get('service', default_settings.get('service', 'kling'))
        model = task_config.get('model', default_settings.get('model', 'v3'))

        metadata = {
            'source_image': file_name,
            'style_name': style_name,
            'service': service,
            'model': model,
            'frame_model': task_config.get('frame_model', default_settings.get('frame_model', 'gemini-3-pro-image-preview')),
            'generate_start': bool(start_frame),
            'generate_end': bool(end_frame),
            'start_frame_file': saved_start.name if saved_start else None,
            'end_frame_file': saved_end.name if saved_end else None,
            'start_frame_prompt': task_config.get('start_frame_prompt', ''),
            'end_frame_prompt': task_config.get('end_frame_prompt', ''),
            'video_prompt': task_config.get('video_prompt', ''),
            'video_negative_prompt': task_config.get('video_negative_prompt', ''),
            'debug_info': debug_info,
            'generated_video': output_filename if video_saved else None,
            'generation_number': gen_num,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': video_saved,
            'api_name': self.api_name
        }

        gen_base_name = f"{base_name}_{gen_num}"
        self.processor.save_metadata(Path(metadata_folder), gen_base_name, file_name,
                                     metadata, task_config, log_status=True)

        return video_saved

    def _get_generation_status(self, base_name, gen_num, metadata_folder):
        """Check if a specific generation has already been processed."""
        gen_base_name = f"{base_name}_{gen_num}"
        metadata_file = Path(metadata_folder) / f"{gen_base_name}_metadata.json"

        if metadata_file.exists():
            try:
                import json
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

                if metadata.get('success', False):
                    return True, 'success'

                max_retries = self.api_defs.get('max_retries', 3)
                attempts = metadata.get('attempts', 0)
                if not metadata.get('success', False) and attempts >= max_retries:
                    return True, 'failed_exhausted'

                return False, None
            except (json.JSONDecodeError, IOError):
                return False, None
        return False, None

    def process_task(self, task, task_num, total_tasks):
        """Iterate source images and generate {generation_count} videos per image."""
        folder = Path(task.get('folder', ''))
        source_folder = folder / "Source"
        output_folder = folder / "Generated_Video"
        frames_folder = folder / "Generated_Frames"
        metadata_folder = folder / "Metadata"

        output_folder.mkdir(parents=True, exist_ok=True)
        frames_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)

        style_name = task.get('style_name', folder.name)

        task_count = task.get('generation_count')
        global_count = self.config.get('generation_count', 1)
        generation_count = task_count if task_count is not None else global_count
        if generation_count < 1:
            generation_count = 1

        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {style_name}")

        source_files = self.processor._get_files_by_type(source_folder, 'image')
        if not source_files:
            self.logger.warning(f" ⚠️ No source images found in {source_folder}")
            return

        self.logger.info(
            f" 📸 Found {len(source_files)} source images × {generation_count} generations = "
            f"{len(source_files) * generation_count} total"
        )

        successful = 0
        skipped = 0
        total_generations = len(source_files) * generation_count
        current = 0

        for file_path in source_files:
            base_name = file_path.stem
            file_name = file_path.name

            for gen_num in range(1, generation_count + 1):
                current += 1

                is_complete, status = self._get_generation_status(base_name, gen_num, metadata_folder)
                if is_complete:
                    if status == 'success':
                        self.logger.info(f" ⏭️ {current}/{total_generations}: {base_name}_{gen_num} (already processed)")
                        successful += 1
                    else:
                        self.logger.info(f" ⏭️ {current}/{total_generations}: {base_name}_{gen_num} (failed - max retries reached)")
                    skipped += 1
                    continue

                self.logger.info(f" 🎬 {current}/{total_generations}: {file_name} → {base_name}_{gen_num}.mp4")

                task_with_gen = task.copy()
                task_with_gen['generation_number'] = gen_num
                task_with_gen['style_name'] = style_name
                task_with_gen['frames_dir'] = str(frames_folder)

                if self.processor.process_file(file_path, task_with_gen, output_folder, metadata_folder):
                    successful += 1

                if current < total_generations:
                    time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(f"✓ Task {task_num}: {successful}/{total_generations} successful ({skipped} skipped)")

    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single source image through the full pipeline."""
        base_name = Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()

        try:
            result = self._make_api_call(file_path, task_config, attempt)
            success = self._handle_result(result, file_path, task_config, output_folder,
                                          metadata_folder, base_name, file_name, start_time, attempt)

            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False

            return success

        except Exception as e:
            self.logger.error(f"   ❌ Error: {e}")
            raise
