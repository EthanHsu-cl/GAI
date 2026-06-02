"""Pixverse Multi-Input API Handler (/submit_5 — up to 4 image inputs per call)."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
import random
import re
from datetime import datetime
from .base_handler import BaseAPIHandler


class PixverseMultiHandler(BaseAPIHandler):
    """Pixverse effects handler for templates that take multiple image inputs.

    Each effect's Source/ folder is consumed in groups of `image_count` images
    per API call. Selection is either sequential (alphabetical) or deterministic
    random (shuffled with a seed). num_iterations defaults to one full pass.
    """

    MAX_IMAGES_PER_CALL = 4

    def validate_structure(self, tasks, config):
        """Reuse the base_folder/effect_name/Source layout from regular pixverse."""
        return self._validate_base_folder_effects_structure(
            tasks, config, effect_key='effect', custom_effect_key='custom_effect_id',
            parallel=True
        )

    def _resolve_image_count(self, task_config):
        default = self.config.get('default_settings', {}).get('image_count', 1)
        count = int(task_config.get('image_count', default) or 1)
        return max(1, min(count, self.MAX_IMAGES_PER_CALL))

    def _resolve_selection_mode(self, task_config):
        default = self.config.get('default_settings', {}).get('selection_mode', 'sequential')
        mode = str(task_config.get('selection_mode', default) or 'sequential').lower()
        return mode if mode in ('sequential', 'random') else 'sequential'

    def _build_selection_plan(self, source_images, image_count, num_iterations,
                              mode, seed, task_key):
        """Return a list of length num_iterations, each entry a list of image_count Paths.

        Sequential: images consumed in sorted order, cycling when exhausted.
        Random: same, but pool is shuffled with a deterministic seed first.
        """
        if not source_images:
            return []

        pool = list(source_images)
        if mode == 'random':
            rng = random.Random(seed)
            rng.shuffle(pool)

        plan = []
        cursor = 0
        for _ in range(num_iterations):
            picks = []
            for _ in range(image_count):
                if cursor >= len(pool):
                    cursor = 0
                    if mode == 'random':
                        # Re-shuffle for next cycle (same seed → same order)
                        rng = random.Random(seed)
                        rng.shuffle(pool)
                picks.append(pool[cursor])
                cursor += 1
            plan.append(picks)
        return plan

    def process_task(self, task, task_num, total_tasks):
        """Override base: iterate selection plans instead of one-file-at-a-time."""
        folder = Path(task.get('folder', task.get('folder_path', '')))
        source_folder = Path(task.get('source_dir', folder / 'Source'))
        output_folder = Path(task.get('generated_dir', folder / 'Generated_Video'))
        metadata_folder = Path(task.get('metadata_dir', folder / 'Metadata'))

        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)

        effect = task.get('effect', '') or folder.name
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {effect}")

        source_images = self.processor._get_files_by_type(source_folder, 'image')
        source_images = sorted(source_images, key=lambda p: p.name.lower())
        if not source_images:
            self.logger.warning(f" ⚠️ No source images found in {source_folder}")
            return

        image_count = self._resolve_image_count(task)
        if len(source_images) < image_count:
            self.logger.warning(
                f" ⚠️ {effect}: image_count={image_count} but only "
                f"{len(source_images)} source image(s) available — skipping"
            )
            return

        mode = self._resolve_selection_mode(task)
        default_seed = self.config.get('default_settings', {}).get('random_seed')
        seed_raw = task.get('random_seed', default_seed)
        if seed_raw is None:
            seed = abs(hash(str(folder))) % (2 ** 32)
        else:
            seed = int(seed_raw)

        default_iterations = self.config.get('default_settings', {}).get('num_iterations', 0)
        num_iterations = int(task.get('num_iterations', default_iterations) or 0)
        if num_iterations <= 0:
            num_iterations = len(source_images) // image_count

        if num_iterations <= 0:
            self.logger.warning(f" ⚠️ {effect}: 0 iterations resolved — skipping")
            return

        plan = self._build_selection_plan(source_images, image_count, num_iterations,
                                          mode, seed, str(folder))

        seed_info = f", seed={seed}" if mode == 'random' else ""
        self.logger.info(
            f" 🎬 {effect}: {num_iterations} iterations × {image_count} image(s) "
            f"({mode}{seed_info}, pool={len(source_images)})"
        )

        max_retries = self.api_defs.get('max_retries', 3)
        successful = 0
        skipped = 0

        for idx, picks in enumerate(plan):
            base_name = self._make_base_name(idx, picks, len(plan))
            primary = picks[0]

            is_complete, status = self._get_iteration_status(base_name, metadata_folder)
            if is_complete:
                if status == 'success':
                    self.logger.info(f" ⏭️ {idx + 1}/{num_iterations}: {base_name} (already processed)")
                    successful += 1
                else:
                    self.logger.info(f" ⏭️ {idx + 1}/{num_iterations}: {base_name} (failed - max retries reached)")
                skipped += 1
                continue

            picks_label = ", ".join(p.name for p in picks)
            self.logger.info(f" 🖼️ {idx + 1}/{num_iterations}: {picks_label}")

            iter_task = task.copy()
            iter_task['_iteration_index'] = idx
            iter_task['_base_name'] = base_name
            iter_task['_selected_images'] = [str(p) for p in picks]
            iter_task['_image_count'] = image_count
            iter_task['_selection_mode'] = mode
            iter_task['_random_seed'] = seed if mode == 'random' else None

            for attempt in range(max_retries):
                try:
                    if attempt > 0:
                        self.logger.info(f" 🔄 Retry {attempt}/{max_retries - 1}")
                        time.sleep(5)
                    ok = self.process(primary, iter_task, output_folder, metadata_folder,
                                      attempt, max_retries)
                    if ok:
                        successful += 1
                        break
                except Exception as e:
                    if attempt == max_retries - 1:
                        self.logger.error(f" ❌ All {max_retries} attempts failed: {e}")

            if idx + 1 < num_iterations:
                time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(
            f"✓ Task {task_num}: {successful}/{num_iterations} successful ({skipped} skipped)"
        )

    def _make_base_name(self, iteration_index, picks, total_iterations):
        """Build a deterministic base name from iteration index and picked image stems."""
        joined = "_".join(p.stem for p in picks)
        if len(joined) > 120:
            joined = joined[:117] + "..."
        width = max(3, len(str(total_iterations)))
        return f"iter{iteration_index:0{width}d}_{joined}"

    def _get_iteration_status(self, base_name, metadata_folder):
        """Check whether an iteration's metadata file marks it complete."""
        import json
        meta_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        if not meta_file.exists():
            return False, None
        try:
            with open(meta_file, 'r') as f:
                meta = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False, None

        if meta.get('success', False):
            return True, 'success'
        max_retries = self.api_defs.get('max_retries', 3)
        if meta.get('attempts', 0) >= max_retries:
            return True, 'failed_exhausted'
        return False, None

    def process(self, file_path, task_config, output_folder, metadata_folder,
                attempt, max_retries):
        """Override base process() to use the injected _base_name for naming/metadata."""
        base_name = task_config.get('_base_name') or Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()

        try:
            result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
            success = self._handle_result(result, file_path, task_config, output_folder,
                                          metadata_folder, base_name, file_name,
                                          start_time, attempt)
            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False
            return success
        except Exception as e:
            self._save_failure(file_path, task_config, metadata_folder, str(e),
                               attempt, start_time)
            raise

    def _make_api_call(self, file_path, task_config, attempt):
        """Call /submit_5 with up to 4 image slots (unused slots repeat the first image)."""
        default_settings = self.config.get('default_settings', {})
        selected = [Path(p) for p in task_config.get('_selected_images', [file_path])]
        if not selected:
            selected = [Path(file_path)]

        # Pad unused image slots by repeating the first picked image — the API
        # ignores anything past image_count, but every param_7..param_10 is "Required".
        padded = list(selected) + [selected[0]] * (self.MAX_IMAGES_PER_CALL - len(selected))
        image_handles = [handle_file(str(p)) for p in padded]

        template_id = task_config.get('custom_effect_id') or task_config.get('template_id') or ''
        if not template_id:
            raise ValueError(
                f"pixverse_multi requires 'custom_effect_id' for effect "
                f"'{task_config.get('effect', '')}'"
            )

        return self.client.predict(
            model=default_settings.get('model', 'v6'),
            duration=default_settings.get('duration', 5),
            quality=default_settings.get('quality', '1080p'),
            template_id=str(template_id),
            sound_effect_switch=bool(default_settings.get('sound_effect_switch', True)),
            image_count=len(selected),
            use_url=False,
            param_7=image_handles[0],
            param_8=image_handles[1],
            param_9=image_handles[2],
            param_10=image_handles[3],
            param_11="",
            param_12="",
            param_13="",
            param_14="",
            api_name=self.api_defs['api_name'],
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Mirrors PixverseHandler but tracks the multi-image selection in metadata."""
        if not isinstance(result, tuple):
            raise ValueError(f"Invalid API response format: {result}")

        all_fields = self.processor._capture_all_api_fields(
            result, ['output_url', 'output_video', 'error_message',
                     'completion_time', 'elapsed_time'])

        error_message = all_fields.get('error_message')
        video_id = None
        if error_message and "VideoID:" in error_message:
            match = re.search(r'VideoID:\s*(\d+)', error_message)
            if match:
                video_id = match.group(1)

        output_url = all_fields.get('output_url')
        output_video = result[1] if len(result) > 1 else None

        effect = task_config.get('effect', 'none')
        safe_effect = effect.replace(' ', '_')
        output_video_name = f"{base_name}_{safe_effect}_effect.mp4"
        output_path = Path(output_folder) / output_video_name

        video_saved = False
        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)
        if not video_saved and output_video and isinstance(output_video, dict) and "video" in output_video:
            local_path = Path(output_video["video"])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True

        processing_time = time.time() - start_time
        default_settings = self.config.get('default_settings', {})
        selected_images = task_config.get('_selected_images', [str(file_path)])
        selected_names = [Path(p).name for p in selected_images]

        base_metadata = {
            'effect_name': effect,
            'model': default_settings.get('model', 'v6'),
            'video_id': video_id,
            'image_count': task_config.get('_image_count', len(selected_images)),
            'selection_mode': task_config.get('_selection_mode', 'sequential'),
            'random_seed': task_config.get('_random_seed'),
            'iteration_index': task_config.get('_iteration_index'),
            'source_images_used': selected_names,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'api_name': self.api_name,
            **all_fields,
        }

        if not video_saved:
            if error_message:
                self.logger.info(f"   ❌ API Error: {error_message}")
            base_metadata['success'] = False
            base_metadata['error'] = error_message or 'Video download/save failed'
            self.processor.save_metadata(Path(metadata_folder), base_name,
                                         selected_names[0] if selected_names else file_name,
                                         base_metadata, task_config)
            return False

        base_metadata['success'] = True
        base_metadata['generated_video'] = output_video_name
        self.processor.save_metadata(Path(metadata_folder), base_name,
                                     selected_names[0] if selected_names else file_name,
                                     base_metadata, task_config)
        return True
