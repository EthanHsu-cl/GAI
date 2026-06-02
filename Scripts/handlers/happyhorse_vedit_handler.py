"""HappyHorse Video Edit API Handler — video editing with optional reference images."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
import json
from datetime import datetime
from .base_handler import BaseAPIHandler, ValidationError


class HappyhorseVeditHandler(BaseAPIHandler):
    """HappyHorse Video Edit handler (/vedit endpoint).

    Takes a required source video + prompt and up to 5 optional reference images.

    Folder structure (per task):
        TaskFolder/
        ├── Source/           # Source video(s) — the required input
        ├── Reference/        # Optional reference images (up to 5), auto-created
        │                     #   when use_reference_images is true
        ├── Generated_Video/  # Output videos (auto-created)
        └── Metadata/         # JSON metadata (auto-created)

    Reference image behavior mirrors Nano Banana:
        - reference_cross_match: false (default) → all reference images are
          appended after the source video (sent as i1..i5) in a single call per
          source video. N videos + M refs = N calls, each [video, ref1..refM].
        - reference_cross_match: true → each source video is paired with each
          reference image individually (one ref per call). N videos × M refs = N×M
          calls, each [video, single_ref]. Outputs are named
          '<video>_refNN_<refname>' so each pairing is independently resumable.
    """

    MAX_REF_IMAGES = 5
    DEFAULT_MODEL = 'happyhorse-1.0-video-edit'

    def validate_file(self, file_path, file_type='image'):
        """Validate a file against the HappyHorse Video Edit spec.

        Videos: MP4/MOV, 3–60 s, shorter side ≥ 320 px, longer side ≤ 2160 px,
        aspect ratio 1:2.5–2.5:1, ≤ 100 MB. The base validator does not check the
        longer-side max or aspect ratio for videos, so those are enforced here.

        Reference images delegate to the base validator (JPEG/PNG/WEBP, ≥ 300 px
        per side, ≤ 10 MB — driven by the top-level validation rules).
        """
        if file_type != 'video':
            return super().validate_file(file_path, file_type)

        try:
            rules = self.api_defs.get('validation', {}).get('video', {})
            path = file_path if isinstance(file_path, Path) else Path(file_path)
            size_mb = path.stat().st_size / (1024 * 1024)
            if size_mb > rules.get('max_size_mb', 100):
                return False, f"Size {size_mb:.1f}MB too large"

            info = self.processor._get_video_info(file_path)
            if not info:
                return False, "Cannot read video info"

            dmin, dmax = rules.get('duration', [3, 60])
            if not (dmin <= info['duration'] <= dmax):
                return False, f"Duration {info['duration']:.1f}s outside {dmin}-{dmax}s"

            w, h = info['width'], info['height']
            short_side, long_side = min(w, h), max(w, h)

            min_dim = rules.get('min_dimension', 320)
            if short_side < min_dim:
                return False, f"Shorter side {short_side}px < {min_dim}px"

            max_dim = rules.get('max_dimension', 2160)
            if long_side > max_dim:
                return False, f"Longer side {long_side}px > {max_dim}px"

            ar_lo, ar_hi = rules.get('aspect_ratio', [0.4, 2.5])
            ratio = w / h if h else 0
            if not (ar_lo <= ratio <= ar_hi):
                return False, f"Aspect ratio {ratio:.2f} outside {ar_lo}-{ar_hi}"

            return True, f"{w}x{h}, {info['duration']:.1f}s, {size_mb:.1f}MB"
        except Exception as e:
            return False, f"Error: {str(e)}"

    def validate_structure(self, tasks, config):
        """Validate folder/Source (videos) + optional folder/Reference (images).

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
        invalid_images = []

        for i, task in enumerate(tasks, 1):
            folder = Path(task['folder'])
            folder.mkdir(parents=True, exist_ok=True)
            source_folder = folder / "Source"
            source_folder.mkdir(exist_ok=True)
            if task.get('use_reference_images', False):
                (folder / "Reference").mkdir(exist_ok=True)

            video_files = self.processor._get_files_by_type(source_folder, 'video')
            if not video_files:
                self.logger.warning(f"❌ Task {i}: No videos found in {source_folder}")
                continue

            valid_video_count = 0
            for video_file in video_files:
                is_valid, reason = self.validate_file(video_file, 'video')
                if not is_valid:
                    invalid_videos.append({
                        'path': str(video_file), 'folder': str(folder),
                        'name': video_file.name, 'reason': reason
                    })
                else:
                    valid_video_count += 1

            # Validate reference images when enabled (do not block on missing folder)
            if task.get('use_reference_images', False):
                ref_folder = folder / "Reference"
                for img_file in self.processor._get_files_by_type(ref_folder, 'image'):
                    is_valid, reason = self.validate_file(img_file, 'image')
                    if not is_valid:
                        invalid_images.append({
                            'path': str(img_file), 'folder': str(folder),
                            'name': img_file.name, 'reason': reason
                        })

            if valid_video_count > 0:
                (folder / "Generated_Video").mkdir(exist_ok=True)
                (folder / "Metadata").mkdir(exist_ok=True)
                valid_tasks.append(task)
                self.logger.info(
                    f"✓ Task {i}: {valid_video_count}/{len(video_files)} valid videos"
                )

        if invalid_videos:
            self.processor.write_invalid_report(invalid_videos, f'{self.api_name}_videos')
            raise ValidationError(f"{len(invalid_videos)} invalid videos found")
        if invalid_images:
            self.processor.write_invalid_report(invalid_images, f'{self.api_name}_images')
            raise ValidationError(f"{len(invalid_images)} invalid reference images found")
        return valid_tasks

    def _get_reference_images(self, task_config):
        """Get reference images from the Reference folder if enabled.

        Returns:
            list: Sorted list of Path objects (capped at MAX_REF_IMAGES), or
                empty list if disabled / none found.
        """
        if not task_config.get('use_reference_images', False):
            return []

        ref_folder = Path(task_config.get('folder', '')) / "Reference"
        if not ref_folder.exists():
            self.logger.warning(f" ⚠️ Reference folder not found: {ref_folder}")
            return []

        images = self.processor._get_files_by_type(ref_folder, 'image')
        images = sorted(images, key=lambda x: x.name.lower())
        if not images:
            self.logger.warning(f" ⚠️ Reference folder exists but no images found: {ref_folder}")
            return []

        if len(images) > self.MAX_REF_IMAGES:
            self.logger.warning(
                f" ⚠️ {len(images)} reference images found, using first {self.MAX_REF_IMAGES}"
            )
            images = images[:self.MAX_REF_IMAGES]
        else:
            self.logger.info(f" 📂 Loaded {len(images)} reference image(s) from Reference/")
        return images

    def process_task(self, task, task_num, total_tasks):
        """Process all source videos for a task, appending or cross-matching refs."""
        folder = Path(task['folder'])
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {folder.name}")

        source_folder = folder / "Source"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"
        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)

        video_files = self.processor._get_files_by_type(source_folder, 'video')
        if not video_files:
            self.logger.warning(f"⚠️ No videos found in {source_folder}")
            return

        reference_images = self._get_reference_images(task)
        cross_match = task.get('reference_cross_match', False) and len(reference_images) > 0

        # Each variant is (filename_suffix, ref_paths_for_this_call).
        if cross_match:
            ref_variants = [
                (f"_ref{i + 1:02d}_{Path(r).stem}", [str(r)])
                for i, r in enumerate(reference_images)
            ]
        else:
            ref_variants = [("", [str(r) for r in reference_images])]

        work_items = []
        for video_file in video_files:
            for suffix, ref_list in ref_variants:
                base_name = f"{video_file.stem}{suffix}"
                work_items.append((video_file, ref_list, base_name))

        total = len(work_items)
        ref_info = (
            f", {len(reference_images)} ref image(s)"
            f"{' (cross-match)' if cross_match else ''}"
            if reference_images else ""
        )
        self.logger.info(
            f"🎬 {len(video_files)} video(s){ref_info} = {total} generation(s)"
        )

        successful = 0
        skipped = 0
        max_retries = self.api_defs.get('max_retries', 3)

        for idx, (video_file, ref_list, base_name) in enumerate(work_items, 1):
            meta_file = metadata_folder / f"{base_name}_metadata.json"
            if meta_file.exists():
                try:
                    with open(meta_file, 'r') as f:
                        meta = json.load(f)
                    if meta.get('success', False):
                        self.logger.info(f" ⏭️ {idx}/{total}: {base_name} (already processed)")
                        skipped += 1
                        successful += 1
                        continue
                    if meta.get('attempts', 0) >= max_retries:
                        self.logger.info(
                            f" ⏭️ {idx}/{total}: {base_name} (failed - max retries reached)"
                        )
                        skipped += 1
                        continue
                except (json.JSONDecodeError, IOError):
                    pass

            self.logger.info(f" 🎬 {idx}/{total}: {base_name}")
            call_task = dict(task)
            call_task['_reference_images'] = ref_list
            call_task['_base_name'] = base_name

            if self.processor.process_file(str(video_file), call_task,
                                           output_folder, metadata_folder):
                successful += 1

            if idx < total:
                time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(
            f"✓ Task {task_num}: {successful}/{total} successful ({skipped} skipped)"
        )

    def _make_api_call(self, file_path, task_config, attempt):
        """Make the /vedit API call with the source video and i1..i5 reference images.

        Args:
            file_path: Path to the source video file.
            task_config: Task configuration (carries '_reference_images' for this call).
            attempt: Current retry attempt number.

        Returns:
            API result tuple of 5 elements
            (video_dict, task_id, status, debug_info, elapsed_time).
        """
        defaults = self.config.get('default_settings', {})
        ref_images = task_config.get('_reference_images', [])

        predict_kwargs = {
            'model': task_config.get('model', defaults.get('model', self.DEFAULT_MODEL)),
            'video': {"video": handle_file(str(file_path)), "subtitles": None},
            'prompt': task_config['prompt'],
            'resolution': task_config.get('resolution', defaults.get('resolution', '720P')),
            'audio_setting': task_config.get('audio_setting', defaults.get('audio_setting', 'origin')),
            'seed': task_config.get('seed', defaults.get('seed', -1)),
        }

        # Reference images map to i1..i5; unfilled slots are sent as None.
        for i in range(1, self.MAX_REF_IMAGES + 1):
            if i <= len(ref_images):
                predict_kwargs[f"i{i}"] = handle_file(str(ref_images[i - 1]))
            else:
                predict_kwargs[f"i{i}"] = None

        predict_kwargs['api_name'] = self.api_defs['api_name']
        return self.client.predict(**predict_kwargs)

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle the /vedit 5-element response tuple and save video + metadata."""
        base_name = task_config.get('_base_name') or base_name

        if not isinstance(result, tuple) or len(result) < 5:
            raise ValueError(
                f"Invalid API response format: expected 5-element tuple, got {type(result)}"
            )

        video_dict, task_id, status, debug_info, elapsed_time = result[:5]
        ref_images = task_config.get('_reference_images', [])
        ref_names = [Path(r).name for r in ref_images]
        self.logger.info(f"   Task ID: {task_id}")

        # Extract the output video path (dict first, then plain string)
        video_path = None
        if isinstance(video_dict, dict) and video_dict.get('video'):
            video_path = video_dict['video']
        elif isinstance(video_dict, str) and video_dict:
            video_path = video_dict

        if not video_path:
            error_reason = status or "API returned no video"
            self.logger.warning(f"   ⚠️ {error_reason} — will retry")
            self._save_result_metadata(
                metadata_folder, base_name, file_path, task_config,
                {
                    'task_id': task_id,
                    'status': status,
                    'error': error_reason,
                    'reference_images_used': ref_names,
                    'attempts': attempt + 1,
                    'success': False,
                    'processing_time_seconds': round(time.time() - start_time, 1),
                }
            )
            return False

        output_filename = f"{base_name}_generated.mp4"
        output_path = Path(output_folder) / output_filename

        video_source = Path(video_path)
        if video_source.exists():
            shutil.copy2(video_source, output_path)
            self.logger.info(f"   📥 Copied local file: {video_source}")
        else:
            if not self.processor.download_file(video_path, output_path):
                raise IOError(f"Failed to download video from {video_path}")

        self._save_result_metadata(
            metadata_folder, base_name, file_path, task_config,
            {
                'task_id': task_id,
                'status': status,
                'elapsed_time': elapsed_time,
                'generated_video': output_filename,
                'reference_images_used': ref_names,
                'attempts': attempt + 1,
                'success': True,
                'processing_time_seconds': round(time.time() - start_time, 1),
            }
        )

        self.logger.info(f"   ✅ Generated: {output_filename}")
        return True

    def _save_result_metadata(self, metadata_folder, base_name, file_path, task_config, extra):
        """Write a metadata file keyed by base_name (handles cross-match naming)."""
        metadata = {
            'source_video': Path(file_path).name,
            'processing_timestamp': datetime.now().isoformat(),
            'api_name': self.api_name,
        }
        metadata.update(extra)
        self.processor.save_metadata(Path(metadata_folder), base_name,
                                     Path(file_path).name, metadata, task_config)

    def _save_failure(self, file_path, task_config, metadata_folder, error, attempt,
                      start_time, timeout_retries=None):
        """Override: save failure metadata keyed by the per-call base_name."""
        base_name = task_config.get('_base_name') or Path(file_path).stem
        ref_images = task_config.get('_reference_images', [])
        extra = {
            'error': error,
            'reference_images_used': [Path(r).name for r in ref_images],
            'attempts': attempt + 1,
            'success': False,
            'processing_time_seconds': round(time.time() - start_time, 1),
        }
        if timeout_retries is not None:
            extra['timeout_retries'] = timeout_retries
        self._save_result_metadata(metadata_folder, base_name, file_path, task_config, extra)

    def _get_source_field(self):
        """Override: vedit's source is a video."""
        return "source_video"
