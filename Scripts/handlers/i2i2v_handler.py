"""Image-to-Image-to-Video orchestrator handler.

Two-step pipeline per source image:
  1. Image generation via either /nano_banana or /openai_image
     (chosen per-task with `image_service`)
  2. Video generation via Kling /Image2Video using the generated image

Both steps run against separate Gradio testbeds, so this handler manages
two clients (one for image_generation, one for kling) instead of relying
on the single `processor.client` that other handlers share.

The intermediate image is saved to Generated_Frames/ and reused on resume
if present — only the failed step (video) is retried.

Per-task folder layout:
    {task_folder}/
    ├── Source/             # input reference images
    ├── Generated_Frames/   # intermediate images
    ├── Generated_Video/    # final videos
    └── Metadata/
"""
import base64
import queue
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from gradio_client import Client, handle_file
from PIL import Image

from .base_handler import BaseAPIHandler, ValidationError


class I2i2vHandler(BaseAPIHandler):
    """Orchestrates image-gen → Kling video-gen as one pipeline.

    Class name uses I2i2v (not I2I2V) so the registry's CamelCase→snake_case
    conversion yields `i2i2v`.
    """

    VALID_ASPECT_RATIOS = [
        'auto', '1:1', '2:3', '3:2', '3:4', '4:3', '4:5', '5:4',
        '9:16', '16:9', '21:9',
    ]
    BASE64_MIN_LEN = 2048

    def __init__(self, processor):
        super().__init__(processor)
        self._kling_client = None  # lazy init
        # Guards the lazy Kling-client init so concurrent workers don't each
        # race to create a separate client on first use.
        self._kling_client_lock = threading.Lock()
        # Bounds concurrent image-gen calls on the shared image testbed client.
        # A permit count of 1 (default) preserves the serial-pipeline behaviour;
        # the two-phase concurrent path swaps in a wider semaphore sized by
        # `image_concurrency` for the duration of the task.
        self._image_semaphore = threading.Semaphore(1)
        # Maps str(source_path) → image-gen seconds for frames the producer
        # generated ahead of time, so the consumer can report honest timings.
        self._prefetch_times = {}

    def _get_kling_client(self):
        """Lazily create the Kling Gradio client (separate testbed).

        Double-checked locking keeps concurrent-mode workers from each building
        their own client on first use.
        """
        if self._kling_client is None:
            with self._kling_client_lock:
                if self._kling_client is None:
                    endpoint = self.api_defs.get(
                        'kling_endpoint',
                        'http://192.168.31.161/external-testbed/kling/',
                    )
                    headers = {}
                    cookie = self.config.get('testbed_cookie') or self.processor._testbed_cookie
                    if cookie:
                        headers['Cookie'] = cookie
                    self._kling_client = Client(endpoint, headers=headers or None)
                    self.logger.info(f"✓ Kling client initialized: {endpoint}")
        return self._kling_client

    def _get_stage_concurrency(self, task, key):
        """Resolve a per-stage concurrency cap.

        Lookup order: per-task/root ``key`` (e.g. ``image_concurrency`` or
        ``video_concurrency``) → fall back to the shared ``concurrent_requests``
        (per-task → root → 1). Clamped to [1, MAX_CONCURRENT_REQUESTS].

        Args:
            task: Task configuration dictionary.
            key: Stage-specific concurrency key to look up first.

        Returns:
            int: Worker count for this stage.
        """
        raw = task.get(key, self.config.get(key))
        if raw is None:
            return self._get_concurrent_requests(task)
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return self._get_concurrent_requests(task)
        return max(1, min(val, self.MAX_CONCURRENT_REQUESTS))

    def validate_structure(self, tasks, config):
        """Validate per-task Source/ layout and prepare enhanced tasks."""
        valid_tasks = []
        invalid_images = []

        for i, task in enumerate(tasks, 1):
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

            frames_folder = folder / "Generated_Frames"
            output_folder = folder / "Generated_Video"
            metadata_folder = folder / "Metadata"
            frames_folder.mkdir(parents=True, exist_ok=True)
            output_folder.mkdir(parents=True, exist_ok=True)
            metadata_folder.mkdir(parents=True, exist_ok=True)

            enhanced_task = task.copy()
            enhanced_task.update({
                'folder': str(folder),
                'folder_name': folder.name,
                'style_name': task.get('style_name', folder.name),
                'source_dir': str(source_folder),
                'frames_dir': str(frames_folder),
                'generated_dir': str(output_folder),
                'metadata_dir': str(metadata_folder),
                'task_num': i,
            })
            valid_tasks.append(enhanced_task)
            self.logger.info(f"✓ Task {i}: {valid_count}/{len(image_files)} valid images")

        if invalid_images:
            self.processor.write_invalid_report(invalid_images, "i2i2v")
            raise ValidationError(f"{len(invalid_images)} invalid images found")

        if not valid_tasks:
            raise Exception("No valid i2i2v tasks found")
        return valid_tasks

    def _resolve_aspect_ratio(self, value):
        """Validate aspect ratio or fall back to 'auto'."""
        ratio = str(value or '').strip()
        if ratio in self.VALID_ASPECT_RATIOS:
            return ratio
        return 'auto'

    def _resolve_sound_enabled(self, task_config, api_params):
        """Resolve the Kling ``sound_enabled`` flag.

        Lookup order: per-task ``video_sound_enabled`` → ``api_params``
        ``video_sound_enabled`` → default ``True``. Accepts bools or common
        string/int truthy-falsey representations from YAML.
        """
        raw = task_config.get('video_sound_enabled')
        if raw is None:
            raw = api_params.get('video_sound_enabled', True)
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() not in ('false', '0', 'no', 'off', '')

    def _existing_generated_image(self, frames_folder, base_name):
        """Find a previously generated intermediate image for this source."""
        frames_folder = Path(frames_folder)
        for ext in ('.png', '.jpg', '.jpeg', '.webp'):
            candidate = frames_folder / f"{base_name}_image{ext}"
            if candidate.exists():
                return candidate
        return None

    def _call_image_api(self, source_path, task_config):
        """Generate an image via /nano_banana or /openai_image.

        Returns:
            tuple: (Path-to-generated-image, debug_info_dict)
        """
        api_params = self.api_defs.get('api_params', {})
        service = task_config.get('image_service') or api_params.get('image_service', 'nano_banana')
        service = str(service).strip().lower()

        if service not in ('nano_banana', 'openai_image'):
            raise ValueError(
                f"image_service must be 'nano_banana' or 'openai_image' (got {service!r})"
            )

        api_name = self.api_defs.get('image_api_names', {}).get(
            service, f"/{service}"
        )

        model = task_config.get('image_model') or api_params.get('image_model')
        resolution = str(task_config.get('image_resolution') or api_params.get('image_resolution', '1K'))
        aspect_ratio = self._resolve_aspect_ratio(
            task_config.get('image_aspect_ratio') or api_params.get('image_aspect_ratio')
        )
        prompt = task_config.get('image_prompt', '')
        if not prompt:
            raise ValueError("image_prompt is empty")

        images_list = [handle_file(str(source_path))]

        # Note prefetch (producer) vs inline (consumer fallback) so the source
        # of the image-gen call is clear when stages interleave.
        where = 'prefetch' if threading.current_thread().name.startswith('i2i2v-prefetch') else 'inline'
        self.logger.info(
            f"   🖼️ [IMG] {where} · service={service}, model={model}, "
            f"resolution={resolution}, aspect={aspect_ratio}"
        )

        if service == 'openai_image':
            quality = str(task_config.get('image_quality') or api_params.get('image_quality', 'auto'))
            with self._image_semaphore:
                result = self.client.predict(
                    prompt=prompt,
                    model=model,
                    quality=quality,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    images=images_list,
                    api_name=api_name,
                )
            return self._parse_openai_image_response(result), {'service': service, 'model': model}
        else:
            with self._image_semaphore:
                result = self.client.predict(
                    prompt=prompt,
                    model=model,
                    images=images_list,
                    resolution=resolution,
                    aspect_ratio=aspect_ratio,
                    api_name=api_name,
                )
            return self._parse_nano_banana_response(result), {'service': service, 'model': model}

    def _parse_nano_banana_response(self, result):
        """Extract base64 image bytes from a /nano_banana response.

        Response shape: (response_id, error_msg, response_data) where
        response_data is a list of {type, data} dicts with base64 image data.
        """
        if not isinstance(result, (list, tuple)) or len(result) < 3:
            raise RuntimeError(f"Unexpected nano_banana response shape: {type(result).__name__}")
        response_id, error_msg, response_data = result[0], result[1], result[2]

        if error_msg:
            raise RuntimeError(f"nano_banana error: {error_msg}")

        text_messages = []
        for item in response_data or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get('type')
            item_data = item.get('data')
            if item_data == 'BLOCKED_MODERATION':
                raise RuntimeError("nano_banana: BLOCKED_MODERATION")
            if item_type == 'Image' and item_data:
                data_str = item_data
                if data_str.startswith('image'):
                    header, b64 = data_str.split(',', 1)
                    ext = header.split('/')[1].split(';')[0]
                else:
                    b64 = data_str
                    ext = 'png'
                if not b64.strip():
                    continue
                image_bytes = base64.b64decode(b64)
                if len(image_bytes) < 100:
                    continue
                return ('bytes', image_bytes, ext, response_id)
            elif item_type == 'Text' and item_data:
                text_messages.append(str(item_data))

        msg = '; '.join(text_messages) if text_messages else 'no image in response'
        raise RuntimeError(f"nano_banana: {msg}")

    def _parse_openai_image_response(self, result):
        """Extract file path / URL / base64 from /openai_image response.

        Response shape: (list[paths_or_dicts], status_text)
        """
        image_outputs = []
        status_text = ''
        if isinstance(result, (list, tuple)):
            if len(result) >= 1:
                image_outputs = result[0] or []
            if len(result) >= 2:
                status_text = result[1] or ''
        elif isinstance(result, str):
            image_outputs = [result]
        if isinstance(image_outputs, str):
            image_outputs = [image_outputs]

        if not image_outputs:
            raise RuntimeError(f"openai_image: no output ({status_text or 'empty response'})")

        first = image_outputs[0]
        path_str = self._extract_path(first)
        if not path_str:
            raise RuntimeError(f"openai_image: could not extract path from {first!r}")

        return ('path_or_url', path_str, status_text)

    def _extract_path(self, item):
        """Pull a usable path/URL string from a Gradio result element."""
        if not item:
            return ''
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            direct = item.get('path') or item.get('name')
            if direct:
                return direct
            if 'image' in item and item['image']:
                nested = self._extract_path(item['image'])
                if nested:
                    return nested
            return item.get('url') or ''
        if isinstance(item, (list, tuple)) and item:
            return self._extract_path(item[0])
        return ''

    def _save_generated_image(self, parsed, frames_folder, base_name):
        """Persist the parsed image-api response to disk.

        Returns:
            Path: Saved file path.
        """
        frames_folder = Path(frames_folder)
        frames_folder.mkdir(parents=True, exist_ok=True)

        kind = parsed[0]
        if kind == 'bytes':
            _, image_bytes, ext, _ = parsed
            out_path = frames_folder / f"{base_name}_image.{ext}"
            out_path.write_bytes(image_bytes)
            return out_path

        # 'path_or_url'
        _, path_str, _ = parsed

        # Local filesystem path
        if not path_str.startswith(('http://', 'https://', 'data:')):
            candidate = Path(path_str)
            if candidate.is_absolute() and candidate.exists():
                ext = candidate.suffix or '.png'
                out_path = frames_folder / f"{base_name}_image{ext}"
                shutil.copy2(candidate, out_path)
                return out_path

        # data URL
        if path_str.startswith('data:'):
            header, _, payload = path_str.partition(',')
            mime = header.split(';')[0].removeprefix('data:')
            ext = '.' + mime.split('/')[-1] if '/' in mime else '.png'
            out_path = frames_folder / f"{base_name}_image{ext}"
            out_path.write_bytes(base64.b64decode(payload))
            return out_path

        # Raw base64
        if (len(path_str) >= self.BASE64_MIN_LEN
                and not path_str.startswith(('http', '/', '.'))
                and bool(re.match(r'^[A-Za-z0-9+/=]+$', path_str[:256]))):
            out_path = frames_folder / f"{base_name}_image.png"
            out_path.write_bytes(base64.b64decode(path_str))
            return out_path

        # URL download
        if path_str.startswith(('http://', 'https://')):
            download_url = path_str
        else:
            endpoint = self.config.get('testbed') or self.api_defs.get('endpoint', '')
            download_url = endpoint.rstrip('/') + (
                path_str if path_str.startswith('/') else '/' + path_str
            )
        ext = Path(path_str.split('?')[0]).suffix or '.png'
        out_path = frames_folder / f"{base_name}_image{ext}"
        if not self.processor.download_file(download_url, out_path):
            raise RuntimeError(f"openai_image: download failed from {download_url}")
        return out_path

    def _call_kling_api(self, image_path, task_config):
        """Generate a video from `image_path` via Kling /Image2Video.

        Returns:
            tuple: (url, video_dict, video_id, task_id, error_msg)
        """
        api_params = self.api_defs.get('api_params', {})
        client = self._get_kling_client()

        model = task_config.get('video_model') or api_params.get('video_model', 'v3')
        mode = task_config.get('video_mode') or api_params.get('video_mode', 'pro')
        duration = int(task_config.get('video_duration') or api_params.get('video_duration', 5))
        prompt = task_config.get('video_prompt', '')
        negative_prompt = task_config.get('video_negative_prompt', '')
        sound_enabled = self._resolve_sound_enabled(task_config, api_params)

        self.logger.info(
            f"   🎬 [VID] kling: model={model}, mode={mode}, duration={duration}, "
            f"sound={sound_enabled}"
        )

        result = client.predict(
            image=handle_file(str(image_path)),
            prompt=prompt,
            mode=mode,
            duration=duration,
            cfg=0.5,
            model=model,
            negative_prompt=negative_prompt,
            sound_enabled=sound_enabled,
            voice_ids='',
            multishot_type='none',
            multishot_df={"headers": ["prompt", "duration"], "data": [], "metadata": None},
            end_frame_image=None,
            api_name=self.api_defs.get('kling_api_name', '/Image2Video'),
        )
        return result

    def _make_api_call(self, file_path, task_config, attempt):
        """Run image-gen → video-gen for a single source image.

        Skips image-gen if a previously generated frame is on disk
        (resume-safe behaviour requested by config).
        """
        frames_folder = Path(task_config.get('frames_dir')
                             or Path(task_config['folder']) / "Generated_Frames")
        base_name = Path(file_path).stem

        # Step 1 — image gen (or reuse)
        image_start = time.time()
        existing = self._existing_generated_image(frames_folder, base_name)
        if existing:
            generated_image_path = existing
            prefetch_time = self._prefetch_times.pop(str(file_path), None)
            if prefetch_time is not None:
                # Frame was produced ahead of time by the prefetch worker; the
                # generation cost was hidden under the previous video render.
                self.logger.info(
                    f"   🖼️ [IMG] prefetched frame ready: {existing.name} "
                    f"({prefetch_time:.1f}s, overlapped)"
                )
                image_debug = {'reused': False, 'prefetched': True}
                image_time = prefetch_time
            else:
                self.logger.info(f"   🖼️ [IMG] reusing existing frame: {existing.name}")
                image_debug = {'reused': True}
                image_time = 0.0
        else:
            parsed, image_debug = self._call_image_api(file_path, task_config)
            generated_image_path = self._save_generated_image(parsed, frames_folder, base_name)
            image_time = time.time() - image_start
            self.logger.info(f"   🖼️ [IMG] saved: {generated_image_path.name} ({image_time:.1f}s)")

        # Step 2 — video gen
        video_start = time.time()
        video_result = self._call_kling_api(generated_image_path, task_config)
        video_time = time.time() - video_start

        return {
            'video_result': video_result,
            'generated_image_path': generated_image_path,
            'image_debug': image_debug,
            'image_time': image_time,
            'video_time': video_time,
        }

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Save video + combined metadata."""
        video_result = result['video_result']
        generated_image_path = result['generated_image_path']

        # Kling returns (url, video_dict, video_id, task_id, error)
        if isinstance(video_result, (list, tuple)):
            url = video_result[0] if len(video_result) > 0 else None
            video_dict = video_result[1] if len(video_result) > 1 else None
            video_id = video_result[2] if len(video_result) > 2 else None
            task_id = video_result[3] if len(video_result) > 3 else None
            kling_error = video_result[4] if len(video_result) > 4 else None
        else:
            url, video_dict, video_id, task_id, kling_error = None, video_result, None, None, None

        processing_time = time.time() - start_time
        output_path = Path(output_folder) / f"{base_name}.mp4"
        video_saved = False

        if not kling_error:
            if url:
                video_saved = self.processor.download_file(url, output_path)
            if not video_saved and video_dict and isinstance(video_dict, dict) and 'video' in video_dict:
                local_path = Path(video_dict['video'])
                if local_path.exists():
                    shutil.copy2(local_path, output_path)
                    video_saved = True

        style_name = task_config.get('style_name', Path(task_config.get('folder', '')).name)

        metadata = {
            'source_image': file_name,
            'style_name': style_name,
            'image_service': task_config.get('image_service', 'nano_banana'),
            'image_model': task_config.get('image_model'),
            'image_quality': task_config.get('image_quality'),
            'image_resolution': task_config.get('image_resolution'),
            'image_aspect_ratio': task_config.get('image_aspect_ratio'),
            'image_prompt': task_config.get('image_prompt', ''),
            'generated_image': generated_image_path.name if generated_image_path else None,
            'image_reused': result['image_debug'].get('reused', False),
            'image_processing_time': round(result['image_time'], 1),
            'video_model': task_config.get('video_model', 'v3'),
            'video_mode': task_config.get('video_mode', 'pro'),
            'video_duration': task_config.get('video_duration', 5),
            'video_prompt': task_config.get('video_prompt', ''),
            'video_negative_prompt': task_config.get('video_negative_prompt', ''),
            'video_sound_enabled': self._resolve_sound_enabled(
                task_config, self.api_defs.get('api_params', {})
            ),
            'video_id': video_id,
            'task_id': task_id,
            'output_url': url,
            'video_processing_time': round(result['video_time'], 1),
            'generated_video': output_path.name if video_saved else None,
            'kling_error': kling_error or None,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': video_saved,
            'api_name': self.api_name,
        }

        self.processor.save_metadata(Path(metadata_folder), base_name, file_name,
                                     metadata, task_config, log_status=True)

        if video_saved:
            self.logger.info(f"   🎬 [VID] generated ✓ {output_path.name}")
        elif kling_error:
            self.logger.warning(f"   🎬 [VID] error ✗ {kling_error}")

        return video_saved

    def _generate_frame(self, file_path, frames_folder, enhanced_task):
        """Ensure ``Generated_Frames/{name}_image.*`` exists for one source image.

        Generates the intermediate image via the image testbed when missing and
        records its wall-clock time in ``self._prefetch_times`` so the later
        video stage can report the cost as overlapped/hidden. Existing frames
        (resume) are left untouched and no time is recorded.

        Failures are swallowed and returned, not raised — the caller falls back
        to inline generation, so a bad frame never crashes a worker.

        Args:
            file_path: Source image path.
            frames_folder: Path to the Generated_Frames folder.
            enhanced_task: Task config with runtime dirs populated.

        Returns:
            tuple: (ok: bool, err: str|None)
        """
        name = Path(file_path).name
        try:
            base_name = Path(file_path).stem
            if not self._existing_generated_image(frames_folder, base_name):
                self.logger.info(f"   🖼️ [IMG] gen start → {name}")
                t0 = time.time()
                parsed, _ = self._call_image_api(file_path, enhanced_task)
                self._save_generated_image(parsed, frames_folder, base_name)
                dt = time.time() - t0
                self._prefetch_times[str(file_path)] = dt
                self.logger.info(f"   🖼️ [IMG] gen done ✓ {name} ({dt:.1f}s)")
            return True, None
        except Exception as e:  # noqa: BLE001 — surface to caller, don't crash thread
            self.logger.warning(f"   🖼️ [IMG] gen failed ✗ {name}: {e} (will retry inline)")
            return False, str(e)

    def _prefetch_worker(self, pending, frames_folder, enhanced_task, ready_q):
        """Generate intermediate frames one (or a few) steps ahead of video-gen.

        Runs in a background thread. For each pending source image it ensures
        `Generated_Frames/{name}_image.*` exists (generating via the image
        testbed if missing), then signals readiness on `ready_q`. The queue is
        bounded, so this stays only ~prefetch_depth images ahead of the serial
        video stage instead of racing through every image up front.

        Image-gen failures are swallowed and reported via the queue — the
        consumer falls back to inline generation, so a bad frame never crashes
        the run or stalls the pipeline.
        """
        for file_path in pending:
            _ok, err = self._generate_frame(file_path, frames_folder, enhanced_task)
            ready_q.put((file_path, err))

    def _process_two_phase_concurrent(self, pending, enhanced_task, frames_folder,
                                      output_folder, metadata_folder,
                                      image_concurrency, video_concurrency):
        """Two-phase concurrent pipeline: all frames, then all videos.

        Phase 1 generates every pending frame in parallel (up to
        ``image_concurrency`` workers) against the image testbed, sized via a
        temporary semaphore swapped into ``self._image_semaphore``. Phase 2 then
        renders every video in parallel (up to ``video_concurrency`` workers) via
        ``processor.process_file``; because the frames already exist, each video
        worker reuses its pre-made frame (and reports the image cost as
        overlapped through ``self._prefetch_times``) instead of regenerating it.

        A frame that fails in Phase 1 simply won't exist, so its Phase 2 worker
        falls back to inline image-gen — the same behaviour as a prefetch miss
        in the serial path.

        Args:
            pending: Source image paths still needing processing.
            enhanced_task: Task config with runtime dirs already populated.
            frames_folder: Path to the Generated_Frames folder.
            output_folder: Path to the Generated_Video folder.
            metadata_folder: Path to the Metadata folder.
            image_concurrency: Max parallel image-gen workers (Phase 1).
            video_concurrency: Max parallel video-gen workers (Phase 2).

        Returns:
            int: Number of images that produced a video successfully.
        """
        # Phase 1 — generate all intermediate frames in parallel.
        self.logger.info(
            f" 🖼️ Phase 1/2: generating {len(pending)} frames "
            f"(up to {image_concurrency} concurrent)"
        )
        prev_semaphore = self._image_semaphore
        self._image_semaphore = threading.Semaphore(image_concurrency)
        try:
            self._run_concurrent(
                pending,
                lambda fp: self._generate_frame(fp, frames_folder, enhanced_task)[0],
                image_concurrency,
            )

            # Phase 2 — render all videos in parallel, reusing the frames above.
            self.logger.info(
                f" 🎬 Phase 2/2: generating {len(pending)} videos "
                f"(up to {video_concurrency} concurrent)"
            )

            def run_video(file_path):
                self.logger.info(f" 🎬 [VID] {file_path.name}")
                # Per-call copy so concurrent threads never mutate the same dict.
                return self.processor.process_file(
                    file_path, dict(enhanced_task), output_folder, metadata_folder
                )

            return self._run_concurrent(pending, run_video, video_concurrency)
        finally:
            self._image_semaphore = prev_semaphore
            self._prefetch_times.clear()

    def process_task(self, task, task_num, total_tasks):
        """Iterate source images and run the pipeline for each.

        Two execution modes, selected by the resolved concurrency caps:

        * Concurrent (``image_concurrency > 1`` or ``video_concurrency > 1``) —
          a two-phase pipeline: every frame is generated in parallel (capped by
          ``image_concurrency``, which can exceed the video cap since the image
          testbed has more headroom), then every video is rendered in parallel
          (capped by ``video_concurrency``).
        * Serial (both caps == 1) — image-gen (separate testbed) is pipelined
          one step ahead of the serial Kling video stage via a bounded
          producer/consumer queue, so the image cost for image N+1 is hidden
          under the video render for image N.

        Caps resolve per stage via ``image_concurrency`` / ``video_concurrency``,
        each falling back to the shared ``concurrent_requests`` (then 1).
        """
        folder = Path(task.get('folder', ''))
        source_folder = Path(task.get('source_dir', folder / "Source"))
        frames_folder = Path(task.get('frames_dir', folder / "Generated_Frames"))
        output_folder = Path(task.get('generated_dir', folder / "Generated_Video"))
        metadata_folder = Path(task.get('metadata_dir', folder / "Metadata"))

        frames_folder.mkdir(parents=True, exist_ok=True)
        output_folder.mkdir(parents=True, exist_ok=True)
        metadata_folder.mkdir(parents=True, exist_ok=True)

        style_name = task.get('style_name', folder.name)
        image_concurrency = self._get_stage_concurrency(task, 'image_concurrency')
        video_concurrency = self._get_stage_concurrency(task, 'video_concurrency')
        use_concurrent = image_concurrency > 1 or video_concurrency > 1
        suffix = f" (img×{image_concurrency} → vid×{video_concurrency})" if use_concurrent else ""
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {style_name}{suffix}")

        source_files = self.processor._get_files_by_type(source_folder, 'image')
        if not source_files:
            self.logger.warning(f" ⚠️ No source images found in {source_folder}")
            return

        self.logger.info(f" 📸 Found {len(source_files)} source images")

        # Make sure runtime fields are propagated to per-file task configs
        enhanced_task = task.copy()
        enhanced_task['frames_dir'] = str(frames_folder)

        # Partition up front: already-finished images are skipped (and never
        # prefetched), so resuming a run does no redundant image-gen.
        total = len(source_files)
        pending = []
        successful = 0
        skipped = 0
        for i, file_path in enumerate(source_files, 1):
            is_complete, status = self._get_processing_status(file_path, metadata_folder)
            if is_complete:
                if status == 'success':
                    self.logger.info(f" ⏭️ {i}/{total}: {file_path.name} (already processed)")
                    successful += 1
                else:
                    self.logger.info(f" ⏭️ {i}/{total}: {file_path.name} (failed - max retries reached)")
                skipped += 1
            else:
                pending.append(file_path)

        if not pending:
            self.logger.info(f"✓ Task {task_num}: {successful}/{total} successful ({skipped} skipped)")
            return

        # Concurrent mode: two-phase parallel frames → parallel videos.
        if use_concurrent:
            successful += self._process_two_phase_concurrent(
                pending, enhanced_task, frames_folder, output_folder, metadata_folder,
                image_concurrency, video_concurrency,
            )
            self.logger.info(f"✓ Task {task_num}: {successful}/{total} successful ({skipped} skipped)")
            return

        # Producer pre-generates frames; depth-1 queue keeps it ~1 image ahead
        # of the serial video stage (override via api_defs `prefetch_depth`).
        prefetch_depth = max(1, int(self.api_defs.get('prefetch_depth', 1)))
        ready_q = queue.Queue(maxsize=prefetch_depth)
        producer = threading.Thread(
            target=self._prefetch_worker,
            args=(pending, frames_folder, enhanced_task, ready_q),
            name=f"i2i2v-prefetch-{task_num}",
            daemon=True,
        )
        producer.start()

        try:
            for idx, _expected in enumerate(pending, 1):
                file_path, prefetch_err = ready_q.get()  # in-order: single producer
                note = " · prefetch missed → inline image-gen" if prefetch_err else ""
                self.logger.info("")  # blank line separates each video block
                self.logger.info(f" {'─' * 56}")
                self.logger.info(f" 🎬 [VID] {idx}/{len(pending)} · {file_path.name}{note}")

                if self.processor.process_file(file_path, enhanced_task, output_folder, metadata_folder):
                    successful += 1

                if idx < len(pending):
                    # Paces Kling submissions; the next frame prefetches during this wait.
                    time.sleep(self.api_defs.get('rate_limit', 5))
        finally:
            # Drain any unconsumed signals so a producer blocked on a full
            # queue (e.g. consumer exited early) can finish and the thread joins.
            while producer.is_alive():
                try:
                    ready_q.get_nowait()
                except queue.Empty:
                    producer.join(timeout=1)
            self._prefetch_times.clear()

        self.logger.info(f"✓ Task {task_num}: {successful}/{total} successful ({skipped} skipped)")

    def validate_file(self, file_path, file_type='image'):
        """Validate input image with i2i2v's relaxed limits."""
        if file_type == 'video':
            return super().validate_file(file_path, file_type)
        try:
            validation_rules = self.api_defs.get('validation', {})
            file_path_obj = file_path if isinstance(file_path, Path) else Path(file_path)
            file_size_mb = file_path_obj.stat().st_size / (1024 * 1024)
            # Source-image limits match nano_banana / openai_image (the upstream image step).
            # Generated frame size is independent — the image API upscales to >=1K,
            # which clears Kling's stricter 300px minimum for the video step.
            min_dim = validation_rules.get('min_dimension', 100)
            max_size = validation_rules.get('max_size_mb', 32)

            with Image.open(file_path) as img:
                w, h = img.size
                if file_size_mb >= max_size:
                    return False, f"Size > {max_size}MB"
                if w < min_dim or h < min_dim:
                    return False, f"Dims {w}x{h} too small"
                return True, f"{w}x{h}"
        except Exception as e:
            return False, f"Error: {str(e)}"
