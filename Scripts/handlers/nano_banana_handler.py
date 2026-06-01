"""Nano Banana API Handler - Gemini multi-image generation."""
from pathlib import Path
from gradio_client import handle_file
import time
from datetime import datetime
from .image_generation_base import BaseImageGenerationHandler


class NanoBananaHandler(BaseImageGenerationHandler):
    """Gemini-based image generation handler (Nano Banana endpoint).

    Supports:
        - gemini-2.5-flash-image: max 3 images (faster)
        - gemini-3-pro-image-preview: max 14 images (better quality)
        - gemini-3.1-flash-image-preview: max 14 images

    Modes (inherited from BaseImageGenerationHandler):
        - Standard: 1 source image + optional Additional folder images
        - Random Source Selection: N images chosen from Source folder per call
    """

    MODEL_MAX_IMAGES = {
        'gemini-2.5-flash-image': 3,
        'gemini-3-pro-image-preview': 14,
        'gemini-3.1-flash-image-preview': 14,
    }
    DEFAULT_MAX_IMAGES = 3
    DEFAULT_MODEL = 'gemini-2.5-flash-image'

    def _make_api_call(self, file_path, task_config, attempt):
        """Make Nano Banana API call with multi-image support.

        Args:
            file_path: Path to the source image file.
            task_config: Task configuration dictionary.
            attempt: Current attempt number (0-indexed).

        Returns:
            tuple: API response tuple (response_id, error_msg, response_data).
        """
        model = task_config.get('model', self.DEFAULT_MODEL)
        resolution = str(task_config.get('resolution') or '1K')
        use_random_source = task_config.get('use_random_source_selection', False)
        text_to_image = task_config.get('text_to_image', False)

        if text_to_image:
            # No source image — generate from the prompt alone. Reference images
            # (if any) are still sent so they can guide the generation.
            ref_image_paths = task_config.get('_reference_images', [])
            images_list = [handle_file(str(ref)) for ref in ref_image_paths]
            task_config['_call_all_images'] = list(ref_image_paths)
            task_config['_call_additional_images'] = []
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
                return (None, "No images selected", [])

            task_config['_call_all_images'] = [str(img) for img in selected_images]
            task_config['_call_additional_images'] = []

            images_list = [handle_file(str(img)) for img in selected_images]

            ref_image_paths = task_config.get('_reference_images', [])
            if ref_image_paths:
                images_list = images_list + [handle_file(str(ref)) for ref in ref_image_paths]
                task_config['_call_all_images'] = [str(img) for img in selected_images] + ref_image_paths
                self.logger.info(f" 📎 Appended {len(ref_image_paths)} reference images after sources")

            self.logger.info(f" 📷 Sending {len(images_list)} images to API: {[img.name for img in selected_images]}")
            aspect_ratio = str(self._get_aspect_ratio(selected_images[0], task_config))
        else:
            additional_imgs = self._get_additional_images(file_path, task_config)
            task_config['_call_additional_images'] = additional_imgs
            task_config['_call_all_images'] = [str(file_path)] + additional_imgs

            images_list = [handle_file(str(file_path))]
            for img_path in additional_imgs:
                if img_path:
                    images_list.append(handle_file(img_path))

            ref_image_paths = task_config.get('_reference_images', [])
            if ref_image_paths:
                images_list = images_list + [handle_file(str(ref)) for ref in ref_image_paths]
                task_config['_call_all_images'] = [str(file_path)] + additional_imgs + ref_image_paths
                self.logger.info(f" 📎 Appended {len(ref_image_paths)} reference images after sources")

            aspect_ratio = str(self._get_aspect_ratio(file_path, task_config))

        max_images = self.MODEL_MAX_IMAGES.get(model, self.DEFAULT_MAX_IMAGES)
        self.logger.debug(f" 📷 Sending {len(images_list)} images (max {max_images} for {model})")
        self.logger.debug(f" 📐 Using aspect ratio: {aspect_ratio}")

        return self.client.predict(
            prompt=task_config['prompt'],
            model=model,
            images=images_list,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            api_name=self.api_defs['api_name']
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time, attempt):
        """Handle Nano Banana API result — response format: (response_id, error_msg, response_data).

        Args:
            result: API response tuple.
            file_path: Path to the source image file.
            task_config: Task configuration dictionary.
            output_folder: Path to save generated outputs.
            metadata_folder: Path to save metadata files.
            base_name: Base name for output files.
            file_name: Original source file name.
            start_time: Processing start timestamp.
            attempt: Current attempt number (0-indexed).

        Returns:
            bool: True if processing succeeded, False otherwise.
        """
        response_id, error_msg, response_data = result[:3]
        processing_time = time.time() - start_time

        self.logger.info(f" Response ID: {response_id}")

        use_random_source = task_config.get('use_random_source_selection', False)
        additional_imgs = task_config.get('_call_additional_images', [])
        additional_imgs_info = [Path(img).name for img in additional_imgs if img]
        ref_image_paths = task_config.get('_reference_images', [])
        ref_imgs_info = [Path(img).name for img in ref_image_paths if img]
        all_imgs = task_config.get('_call_all_images', [])
        all_imgs_info = [Path(img).name for img in all_imgs if img]

        is_failed = False
        failure_reason = error_msg if error_msg else None
        has_images_in_response = False
        text_responses_list = []
        all_error_messages = []

        if error_msg:
            all_error_messages.append(error_msg)

        if response_data and isinstance(response_data, list):
            for item in response_data:
                if isinstance(item, dict):
                    item_data = item.get('data')
                    item_type = item.get('type')

                    if item_data == 'BLOCKED_MODERATION':
                        is_failed = True
                        failure_reason = 'BLOCKED_MODERATION'
                        all_error_messages.append('BLOCKED_MODERATION')
                    elif item_type == 'Text':
                        text_content = str(item_data) if item_data else ''
                        if text_content:
                            text_responses_list.append(text_content)
                            all_error_messages.append(text_content)
                    elif item_type == 'Image':
                        has_images_in_response = True
                    else:
                        if item_type or item_data:
                            unknown_msg = f"Unknown response type: {item_type}, data: {item_data}"
                            all_error_messages.append(unknown_msg)
                            self.logger.warning(f" ⚠️ {unknown_msg}")

        if not response_data or (isinstance(response_data, list) and len(response_data) == 0):
            is_failed = True
            if not failure_reason:
                failure_reason = "No content parts in response"
                all_error_messages.append(failure_reason)

        if text_responses_list and not has_images_in_response:
            is_failed = True
            if not failure_reason:
                failure_reason = text_responses_list[0]
                if not any(failure_reason.lower().startswith(p) for p in ['error', 'failed', 'blocked', 'invalid']):
                    failure_reason = f"Error: {failure_reason}"

        if error_msg or is_failed:
            if text_responses_list:
                self.logger.info(f" ❌ API Error: {failure_reason}")
                self.logger.info(f" 📝 Text response: {text_responses_list[0][:200]}")
            else:
                self.logger.info(f" ❌ API Error: {failure_reason}")

            metadata = {
                'response_id': response_id,
                'error': failure_reason,
                'success': False,
                'attempts': attempt + 1,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name
            }
            if all_error_messages:
                metadata['all_errors'] = all_error_messages
            if text_responses_list:
                metadata['text_responses'] = text_responses_list
            combined_errors = str(failure_reason or '') + ' '.join(str(e) for e in all_error_messages)
            if self._is_error_429(combined_errors):
                task_config['_last_error_is_429'] = True
                metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
            if use_random_source and all_imgs_info:
                metadata['all_images_used'] = all_imgs_info
                metadata['random_source_selection'] = True
            elif additional_imgs_info:
                metadata['additional_images_used'] = additional_imgs_info
            gen_idx = task_config.get('_generation_index')
            gens_per_source = task_config.get('_generations_per_source', 1)
            if gen_idx is not None and gens_per_source > 1:
                metadata['generation_index'] = gen_idx
                metadata['generations_per_source'] = gens_per_source
            if task_config.get('_base_name'):
                metadata['_base_name'] = task_config['_base_name']
            self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                              metadata, task_config)
            return False

        saved_files, text_responses = self.processor.save_nano_responses(
            response_data, Path(output_folder), base_name)
        has_images = len(saved_files) > 0

        if not has_images:
            error_reason = "No images generated"
            if text_responses_list:
                error_reason = text_responses_list[0]
                if not any(error_reason.lower().startswith(p) for p in ['error', 'failed', 'blocked', 'invalid']):
                    error_reason = f"Error: {error_reason}"
            elif text_responses:
                text_contents = [tr.get('content', '') for tr in text_responses if isinstance(tr, dict)]
                if text_contents:
                    error_reason = text_contents[0]
                    if not any(error_reason.lower().startswith(p) for p in ['error', 'failed', 'blocked', 'invalid']):
                        error_reason = f"Error: {error_reason}"

            self.logger.info(f" ❌ {error_reason}")

            metadata = {
                'response_id': response_id,
                'error': error_reason,
                'success': False,
                'attempts': attempt + 1,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name
            }
            if text_responses_list:
                metadata['text_responses'] = text_responses_list
            elif text_responses:
                metadata['text_responses'] = text_responses
            if self._is_error_429(error_reason):
                task_config['_last_error_is_429'] = True
                metadata['error429_retries'] = self._read_error429_retries(base_name, metadata_folder) + 1
            if use_random_source and all_imgs_info:
                metadata['all_images_used'] = all_imgs_info
                metadata['random_source_selection'] = True
            elif additional_imgs_info:
                metadata['additional_images_used'] = additional_imgs_info
            gen_idx = task_config.get('_generation_index')
            gens_per_source = task_config.get('_generations_per_source', 1)
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
            'response_id': response_id,
            'saved_files': [Path(f).name for f in saved_files],
            'text_responses': text_responses,
            'success': True,
            'attempts': attempt + 1,
            'images_generated': len(saved_files),
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'api_name': self.api_name
        }
        if use_random_source and all_imgs_info:
            metadata['all_images_used'] = all_imgs_info
            metadata['random_source_selection'] = True
            metadata['min_images'] = task_config.get('min_images', self.DEFAULT_MIN_IMAGES)
            metadata['max_images'] = task_config.get('max_images',
                self.MODEL_MAX_IMAGES.get(task_config.get('model', self.DEFAULT_MODEL), self.DEFAULT_MAX_IMAGES))
        elif additional_imgs_info:
            metadata['additional_images_used'] = additional_imgs_info
        if ref_imgs_info:
            metadata['reference_images_used'] = ref_imgs_info
        gen_idx = task_config.get('_generation_index')
        gens_per_source = task_config.get('_generations_per_source', 1)
        if gen_idx is not None and gens_per_source > 1:
            metadata['generation_index'] = gen_idx
            metadata['generations_per_source'] = gens_per_source
        if task_config.get('_base_name'):
            metadata['_base_name'] = task_config['_base_name']

        self.processor.save_nano_metadata(Path(metadata_folder), base_name, file_name,
                                          metadata, task_config)

        self.logger.info(f" ✅ Generated: {len(saved_files)} images")
        if use_random_source and all_imgs_info:
            self.logger.info(f" 🖼️ Input images ({len(all_imgs_info)}): {', '.join(all_imgs_info)}")
        elif additional_imgs_info:
            self.logger.info(f" 🖼️ Additional images: {', '.join(additional_imgs_info)}")

        return True
