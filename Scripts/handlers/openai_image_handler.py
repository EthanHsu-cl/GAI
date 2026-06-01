"""OpenAI Image API Handler.

Wraps the /openai_image gradio endpoint (gpt-image-N models). Builds on the
shared image-generation base (multi-image input, random source selection,
reference images, generations-per-source, iteration-based processing, and
429-error retry) and adds the parts unique to this endpoint:

* its own model/quality/resolution parameters (independent of Nano Banana)
* the predict() signature (adds ``quality``)
* the response format (``(list[str], str)`` of file paths + status text
  instead of Nano Banana's base64-in-response_data tuple)
* server-side timeout retry.
"""
import base64
import shutil
import time
from pathlib import Path
from datetime import datetime

from gradio_client import handle_file

from .image_generation_base import BaseImageGenerationHandler


class OpenaiImageHandler(BaseImageGenerationHandler):
    """Handler for the /openai_image endpoint."""

    # Conservative per-call image cap; can be overridden per-task with max_images.
    MODEL_MAX_IMAGES = {
        'gpt-image-1': 10,
        'gpt-image-2': 10,
    }

    def __init__(self, processor):
        """Initialize handler with per-file image tracking dicts."""
        super().__init__(processor)
        self._current_additional_images = {}  # file_path -> list of additional image paths
        self._current_all_images = {}          # file_path -> list of all image paths sent to API

    def _check_metadata_status(self, metadata):
        """Check completion status, accounting for timeout retries.

        Extends the nano_banana check so that a timed-out file is not
        considered exhausted until its timeout retry limit is also reached.

        Args:
            metadata: Metadata dictionary loaded from a metadata JSON file.

        Returns:
            tuple: (is_complete, status_reason).
        """
        if metadata.get('success', False):
            return True, 'success'

        error = str(metadata.get('error', ''))
        max_timeout = self.api_defs.get('max_retries_timeout', 3)
        timeout_retries = metadata.get('timeout_retries', 0)

        # If timeout retries were exhausted, skip regardless of current error type
        if max_timeout > 0 and timeout_retries >= max_timeout:
            return True, 'failed_timeout_exhausted'

        # Timeout errors still within retry budget
        if self._is_timeout_error(error) and max_timeout > 0:
            return False, None

        # Delegate remaining checks (429, normal exhaustion) to parent
        return super()._check_metadata_status(metadata)

    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single file with timeout retry support.

        Extends the nano_banana process loop to automatically retry when the
        server returns a timeout in the response status text (as opposed to a
        connection-level timeout, which is handled by the base class).

        Args:
            file_path: Path to the source file.
            task_config: Task configuration dictionary.
            output_folder: Path to output folder.
            metadata_folder: Path to metadata folder.
            attempt: Current attempt number.
            max_retries: Maximum number of retries.

        Returns:
            bool: True if processing succeeded, False otherwise.
        """
        self._last_error_is_timeout = False

        # Delegate to parent (nano_banana) for the main processing + 429 retry
        success = super().process(file_path, task_config, output_folder,
                                  metadata_folder, attempt, max_retries)

        if success:
            return True

        # If it failed due to a server-side timeout, retry independently
        max_timeout = self.api_defs.get('max_retries_timeout', 3)
        base_name = task_config.get('_base_name') or Path(file_path).stem
        file_name = Path(file_path).name

        while not success and self._last_error_is_timeout and max_timeout > 0:
            count = self._read_timeout_retries(base_name, metadata_folder)
            if count >= max_timeout:
                self.logger.info(f" ⏭️ Timeout retry limit reached ({count}/{max_timeout})")
                break
            wait_secs = self.TIMEOUT_RETRY_WAIT * count
            self.logger.info(f" ⏳ Timeout retry {count}/{max_timeout} (waiting {wait_secs}s)")
            time.sleep(wait_secs)
            self._last_error_is_timeout = False
            start_time = time.time()
            try:
                result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
                success = self._handle_result(result, file_path, task_config, output_folder,
                                              metadata_folder, base_name, file_name, start_time, attempt)
            except Exception:
                break

        return success
    DEFAULT_MAX_IMAGES = 10
    DEFAULT_MIN_IMAGES = 1

    DEFAULT_MODEL = 'gpt-image-2'
    DEFAULT_QUALITY = 'auto'
    DEFAULT_RESOLUTION = '1K'

    def _make_api_call(self, file_path, task_config, attempt):
        """Build the image list (parity with nano_banana) and call /openai_image."""
        api_params = self.api_defs.get('api_params', {})
        model = task_config.get('model') or api_params.get('model', self.DEFAULT_MODEL)
        quality = str(task_config.get('quality') or api_params.get('quality', self.DEFAULT_QUALITY))
        resolution = str(task_config.get('resolution') or api_params.get('resolution', self.DEFAULT_RESOLUTION))

        use_random_source = task_config.get('use_random_source_selection', False)
        text_to_image = task_config.get('text_to_image', False)

        if text_to_image:
            # No source image — generate from the prompt alone. Reference images
            # (if any) are still sent so they can guide the generation.
            ref_image_paths = task_config.get('_reference_images', [])
            images_list = [handle_file(str(ref)) for ref in ref_image_paths]
            self._current_all_images[str(file_path)] = list(ref_image_paths)
            self._current_additional_images[str(file_path)] = []
            if ref_image_paths:
                self.logger.info(f" ✍️ Text-to-image with {len(ref_image_paths)} reference image(s)")
            else:
                self.logger.info(" ✍️ Text-to-image (prompt only, no images)")
            aspect_ratio = str(self._get_aspect_ratio(file_path, task_config))
        elif use_random_source:
            iteration_index = task_config.get('_iteration_index')
            if iteration_index is None:
                source_images = self._get_source_images_for_task(task_config)
                try:
                    iteration_index = next(
                        i for i, img in enumerate(source_images)
                        if str(img) == str(file_path)
                    )
                except StopIteration:
                    iteration_index = 0

            selected_images = self._get_random_source_selection(task_config, iteration_index)
            if not selected_images:
                self.logger.error(" ❌ No images selected for API call")
                return ([], "No images selected")

            self._current_all_images[str(file_path)] = [str(img) for img in selected_images]
            self._current_additional_images[str(file_path)] = []

            images_list = [handle_file(str(img)) for img in selected_images]

            ref_image_paths = task_config.get('_reference_images', [])
            if ref_image_paths:
                images_list = [handle_file(str(ref)) for ref in ref_image_paths] + images_list
                self._current_all_images[str(file_path)] = ref_image_paths + [str(img) for img in selected_images]
                self.logger.info(f" 📎 Prepended {len(ref_image_paths)} reference images")

            self.logger.info(
                f" 📷 Sending {len(images_list)} images to API: {[img.name for img in selected_images]}"
            )
            aspect_ratio = str(self._get_aspect_ratio(selected_images[0], task_config))
        else:
            additional_imgs = self._get_additional_images(file_path, task_config)
            self._current_additional_images[str(file_path)] = additional_imgs
            self._current_all_images[str(file_path)] = [str(file_path)] + additional_imgs

            images_list = [handle_file(str(file_path))]
            for img_path in additional_imgs:
                if img_path:
                    images_list.append(handle_file(img_path))

            ref_image_paths = task_config.get('_reference_images', [])
            if ref_image_paths:
                images_list = [handle_file(str(ref)) for ref in ref_image_paths] + images_list
                self._current_all_images[str(file_path)] = ref_image_paths + [str(file_path)] + additional_imgs
                self.logger.info(f" 📎 Prepended {len(ref_image_paths)} reference images")

            aspect_ratio = str(self._get_aspect_ratio(file_path, task_config))

        max_images = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        self.logger.info(f"   Model: {model}, Quality: {quality}, Resolution: {resolution}, Aspect: {aspect_ratio}")
        self.logger.debug(f" 📷 Sending {len(images_list)} images (max {max_images} for {model})")

        prompt = task_config['prompt']
        return self.client.predict(
            prompt=prompt,
            model=model,
            quality=quality,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            images=images_list,
            api_name=self.api_defs['api_name'],
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle (list[str] paths, str status_text) response.

        Mirrors nano_banana's metadata bookkeeping (multi-image, reference,
        generation index, 429 retry tracking) so reports and resumability
        behave identically.
        """
        processing_time = time.time() - start_time

        # Parse the tuple — be tolerant of unusual shapes.
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
        if not isinstance(image_outputs, list):
            image_outputs = []

        # Diagnostic: log what came back so failures are inspectable.
        self.logger.info(f" 📦 API returned {len(image_outputs)} output entries")
        if image_outputs:
            sample = image_outputs[0]
            if isinstance(sample, dict):
                self.logger.info(f" 🔎 First entry: dict keys={list(sample.keys())}")
            elif isinstance(sample, str):
                preview = sample[:80].replace('\n', ' ')
                self.logger.info(f" 🔎 First entry: str(len={len(sample)}) preview={preview!r}")
            else:
                self.logger.info(f" 🔎 First entry: type={type(sample).__name__}")

        # Full structured summary of the raw response — gets attached to metadata
        # so every run is fully inspectable from the JSON alone.
        raw_response_summary = {
            'result_type': type(result).__name__,
            'result_len':  len(result) if isinstance(result, (list, tuple)) else None,
            'image_outputs_count': len(image_outputs),
            'image_outputs': [self._describe_entry(e) for e in image_outputs],
            'status_text':  status_text,
            'extra_fields': (
                [self._describe_entry(x) for x in list(result)[2:]]
                if isinstance(result, (list, tuple)) and len(result) > 2 else []
            ),
        }

        use_random_source = task_config.get('use_random_source_selection', False)
        additional_imgs = self._current_additional_images.get(str(file_path), [])
        additional_imgs_info = [Path(img).name for img in additional_imgs if img]
        ref_image_paths = task_config.get('_reference_images', [])
        ref_imgs_info = [Path(img).name for img in ref_image_paths if img]
        all_imgs = self._current_all_images.get(str(file_path), [])
        all_imgs_info = [Path(img).name for img in all_imgs if img]

        # Save generated images
        saved_files = []
        for idx, item in enumerate(image_outputs, 1):
            try:
                out = self._save_one_output(item, idx, len(image_outputs),
                                            base_name, output_folder)
                if out:
                    saved_files.append(str(out))
            except Exception as e:
                self.logger.warning(f" ⚠️ Failed to save image {idx}: {e}")

        has_images = len(saved_files) > 0
        gen_idx = task_config.get('_generation_index')
        gens_per_source = task_config.get('_generations_per_source', 1)

        if not has_images:
            error_reason = status_text or "No images generated"
            self.logger.info(f" ❌ {error_reason}")

            metadata = {
                'error': error_reason,
                'status_text': status_text,
                'success': False,
                'attempts': attempt + 1,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name,
                'raw_response': raw_response_summary,
            }
            if self._is_error_429(error_reason):
                self._last_error_is_429 = True
                metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
            existing_timeout_retries = self._read_timeout_retries(base_name, metadata_folder)
            if self._is_timeout_error(error_reason):
                self._last_error_is_timeout = True
                metadata['timeout_retries'] = existing_timeout_retries + 1
            elif existing_timeout_retries > 0:
                metadata['timeout_retries'] = existing_timeout_retries
            if use_random_source and all_imgs_info:
                metadata['all_images_used'] = all_imgs_info
                metadata['random_source_selection'] = True
            elif additional_imgs_info:
                metadata['additional_images_used'] = additional_imgs_info
            if ref_imgs_info:
                metadata['reference_images_used'] = ref_imgs_info
            if gen_idx is not None and gens_per_source > 1:
                metadata['generation_index'] = gen_idx
                metadata['generations_per_source'] = gens_per_source
            if task_config.get('_base_name'):
                metadata['_base_name'] = task_config['_base_name']

            self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                              metadata, task_config)
            return False

        # Success
        metadata = {
            'saved_files': [Path(f).name for f in saved_files],
            'images_generated': len(saved_files),
            'status_text': status_text,
            'success': True,
            'attempts': attempt + 1,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'api_name': self.api_name,
            'raw_response': raw_response_summary,
        }

        if use_random_source and all_imgs_info:
            metadata['all_images_used'] = all_imgs_info
            metadata['random_source_selection'] = True
            metadata['min_images'] = task_config.get('min_images', self.DEFAULT_MIN_IMAGES)
            metadata['max_images'] = task_config.get('max_images', self.MODEL_MAX_IMAGES.get(
                task_config.get('model', self.DEFAULT_MODEL), self.DEFAULT_MAX_IMAGES))
        elif additional_imgs_info:
            metadata['additional_images_used'] = additional_imgs_info
        if ref_imgs_info:
            metadata['reference_images_used'] = ref_imgs_info
        if gen_idx is not None and gens_per_source > 1:
            metadata['generation_index'] = gen_idx
            metadata['generations_per_source'] = gens_per_source
        if task_config.get('_base_name'):
            metadata['_base_name'] = task_config['_base_name']

        self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                          metadata, task_config)

        self.logger.info(f" ✅ Generated: {len(saved_files)} image(s)")
        if use_random_source and all_imgs_info:
            self.logger.info(f" 🖼️ Input images ({len(all_imgs_info)}): {', '.join(all_imgs_info)}")
        elif additional_imgs_info:
            self.logger.info(f" 🖼️ Additional images: {', '.join(additional_imgs_info)}")
        return True

    # Heuristic: base64 payloads are >2KB of A-Z, a-z, 0-9, +, /, = with no
    # filesystem separators. Real paths and URLs are much shorter.
    _BASE64_MIN_LEN = 2048

    @staticmethod
    def _looks_like_base64(s):
        """Check whether the first 256 chars consist only of base64 characters."""
        import re
        return bool(re.match(r'^[A-Za-z0-9+/=]+$', s[:256]))

    @staticmethod
    def _describe_entry(item, *, max_str=160, max_dict_str=160):
        """Return a JSON-safe summary of one response entry.

        Strings longer than ``max_str`` get summarized as
        ``{type:str, len:N, head:'...', tail:'...'}`` so a multi-MB base64
        payload doesn't bloat the metadata file. Dicts have their str-valued
        fields treated the same way; non-str fields are kept as-is when small.
        """
        if item is None:
            return {'type': 'NoneType'}
        if isinstance(item, str):
            if len(item) <= max_str:
                return {'type': 'str', 'len': len(item), 'value': item}
            return {
                'type': 'str',
                'len':  len(item),
                'head': item[:80],
                'tail': item[-40:],
            }
        if isinstance(item, dict):
            out = {'type': 'dict', 'keys': list(item.keys())}
            for k, v in item.items():
                if isinstance(v, str) and len(v) > max_dict_str:
                    out[k] = {'len': len(v), 'head': v[:80], 'tail': v[-40:]}
                elif isinstance(v, (str, int, float, bool)) or v is None:
                    out[k] = v
                elif isinstance(v, dict):
                    out[k] = OpenaiImageHandler._describe_entry(v, max_str=max_dict_str)
                elif isinstance(v, (list, tuple)):
                    out[k] = {'type': type(v).__name__, 'len': len(v)}
                else:
                    out[k] = {'type': type(v).__name__, 'repr': repr(v)[:120]}
            return out
        if isinstance(item, (list, tuple)):
            return {
                'type': type(item).__name__,
                'len':  len(item),
                'items_preview': [OpenaiImageHandler._describe_entry(x, max_str=max_str)
                                  for x in list(item)[:3]],
            }
        return {'type': type(item).__name__, 'repr': repr(item)[:max_str]}

    def _save_one_output(self, item, idx, total, base_name, output_folder):
        """Resolve one gradio output entry and save it to ``output_folder``.

        Handles four cases, in order:
          1. local filesystem path (gradio /tmp/...) — copy
          2. data URL (``data:image/png;base64,...``)  — decode
          3. raw base64 string                         — decode
          4. URL (absolute or relative to endpoint)    — download

        Returns the saved Path on success, else None.
        """
        path_str = self._extract_path(item)
        if not path_str:
            self.logger.warning(f" ⚠️ Image {idx}: could not extract path from entry")
            return None

        suffix = f"_image_{idx}" if total > 1 else "_image_1"
        # _image_N naming matches the report-generator's nano_banana parser.

        # (1) Local filesystem path
        if not path_str.startswith(('http://', 'https://', 'data:')):
            candidate = Path(path_str)
            if candidate.is_absolute() and candidate.exists():
                ext = candidate.suffix or '.png'
                out_path = Path(output_folder) / f"{base_name}{suffix}{ext}"
                shutil.copy2(candidate, out_path)
                return out_path

        # (2) data URL
        if path_str.startswith('data:'):
            header, _, payload = path_str.partition(',')
            mime = header.split(';')[0].removeprefix('data:')
            ext = '.' + mime.split('/')[-1] if '/' in mime else '.png'
            out_path = Path(output_folder) / f"{base_name}{suffix}{ext}"
            try:
                out_path.write_bytes(base64.b64decode(payload))
                return out_path
            except Exception as e:
                self.logger.warning(f" ⚠️ Image {idx}: data-URL decode failed: {e}")
                return None

        # (3) Raw base64 (long string containing only base64 characters)
        if (len(path_str) >= self._BASE64_MIN_LEN
                and not path_str.startswith(('http', '/', '.'))
                and self._looks_like_base64(path_str)):
            out_path = Path(output_folder) / f"{base_name}{suffix}.png"
            try:
                out_path.write_bytes(base64.b64decode(path_str))
                return out_path
            except Exception as e:
                self.logger.warning(f" ⚠️ Image {idx}: base64 decode failed: {e}")
                return None

        # (4) URL (absolute or relative to testbed endpoint)
        if path_str.startswith(('http://', 'https://')):
            download_url = path_str
        else:
            endpoint = (self.config.get('testbed')
                        or self.api_defs.get('endpoint', ''))
            download_url = endpoint.rstrip('/') + (
                path_str if path_str.startswith('/') else '/' + path_str
            )
        ext = Path(path_str.split('?')[0]).suffix or '.png'
        out_path = Path(output_folder) / f"{base_name}{suffix}{ext}"
        if not self.processor.download_file(download_url, out_path):
            self.logger.warning(f" ⚠️ Image {idx}: download failed: {download_url}")
            return None
        return out_path

    def _extract_path(self, item):
        """Extract a usable path or URL string from a gradio result element.

        Handles the common shapes returned by gradio components:
          - plain string (File / Image)
          - FileData dict: {'path': ..., 'url': ..., 'orig_name': ...}
          - Gallery item:  {'image': {...FileData...}, 'caption': ...}
          - nested list/tuple
        """
        if not item:
            return ''
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            # Prefer local path (avoids needing testbed auth cookie for HTTP).
            direct = item.get('path') or item.get('name')
            if direct:
                return direct
            # Gallery: descend into the 'image' sub-dict.
            if 'image' in item and item['image']:
                nested = self._extract_path(item['image'])
                if nested:
                    return nested
            # Fall back to URL (may be relative; resolved by caller).
            return item.get('url') or ''
        if isinstance(item, (list, tuple)) and item:
            return self._extract_path(item[0])
        return ''
