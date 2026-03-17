"""Kling Motion Control API Handler - Image-video cross-matching for motion transfer."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
import json
from datetime import datetime
from .base_handler import BaseAPIHandler


class KlingMotionHandler(BaseAPIHandler):
    """
    Kling Motion Control handler.

    Processes images and videos through cross-matching:
    each reference image is paired with each motion source video
    to produce motion-controlled output videos.

    Cross-matches all images with all videos
    (e.g., 3 images x 4 videos = 12 generations).
    """

    def process_task(self, task, task_num, total_tasks):
        """Override: Handle image-video cross-matching."""
        folder = Path(task['folder'])
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {folder.name}")

        source_image_folder = folder / "Source Image"
        source_video_folder = folder / "Source Video"
        output_folder = folder / "Generated_Video"
        metadata_folder = folder / "Metadata"

        image_files = self.processor._get_files_by_type(source_image_folder, 'image')
        video_files = self.processor._get_files_by_type(source_video_folder, 'video')

        if not image_files:
            self.logger.warning(f"⚠️ No images found in {source_image_folder}")
            return

        if not video_files:
            self.logger.warning(f"⚠️ No videos found in {source_video_folder}")
            return

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

                combo_base = f"{video_file.stem}_{image_file.stem}"
                combo_metadata = metadata_folder / f"{combo_base}_metadata.json"
                if combo_metadata.exists():
                    try:
                        with open(combo_metadata, 'r') as f:
                            meta = json.load(f)
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

                combined_task = task.copy()
                combined_task['image_file'] = str(image_file)
                combined_task['video_file'] = str(video_file)

                if self.processor.process_file(
                    str(image_file), combined_task, output_folder, metadata_folder
                ):
                    successful += 1

                if combination_num < total_combinations:
                    time.sleep(self.api_defs.get('rate_limit', 3))

        self.logger.info(
            f"✓ Task {task_num}: {successful}/{total_combinations} successful "
            f"({skipped} skipped)"
        )

    def _make_api_call(self, file_path, task_config, attempt):
        """
        Make Kling Motion Control API call.

        Sends a reference image and motion source video to the
        /MotionControlSubmit endpoint for motion-controlled generation.

        Args:
            file_path: Path to reference image (character appearance).
            task_config: Task configuration containing video_file and parameters.
            attempt: Current retry attempt number.

        Returns:
            API result tuple (output_url, output_video, video_id, task_id, error_msg).
        """
        image_path = Path(file_path)
        video_path = Path(task_config['video_file'])

        return self.client.predict(
            image=handle_file(str(image_path)),
            video={
                "video": handle_file(str(video_path)),
                "subtitles": None,
            },
            prompt=task_config.get('prompt', ''),
            model=task_config.get(
                'model',
                self.config.get(
                    'model',
                    self.api_defs.get('api_params', {}).get('model', 'v3')
                )
            ),
            character_orientation=task_config.get(
                'character_orientation',
                self.config.get(
                    'character_orientation',
                    self.api_defs.get('api_params', {}).get('character_orientation', 'video')
                )
            ),
            mode=task_config.get(
                'mode',
                self.config.get(
                    'mode',
                    self.api_defs.get('api_params', {}).get('mode', 'pro')
                )
            ),
            keep_original_sound=task_config.get(
                'keep_original_sound',
                self.config.get(
                    'keep_original_sound',
                    self.api_defs.get('api_params', {}).get('keep_original_sound', True)
                )
            ),
            element_list_str=task_config.get(
                'element_list_str',
                self.config.get(
                    'element_list_str',
                    self.api_defs.get('api_params', {}).get('element_list_str', '')
                )
            ),
            api_name=self.api_defs['api_name']
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time,
                       attempt):
        """
        Handle Kling Motion Control API result.

        Args:
            result: API result tuple of 5 elements
                (output_url, output_video, video_id, task_id, error_msg).
            file_path: Source image path.
            task_config: Task configuration.
            output_folder: Output video directory.
            metadata_folder: Metadata directory.
            base_name: Base filename without extension.
            file_name: Full source filename.
            start_time: Processing start timestamp.
            attempt: Current retry attempt.

        Returns:
            bool: True if processing succeeded, False otherwise.
        """
        if not isinstance(result, tuple) or len(result) < 5:
            raise ValueError(
                f"Invalid API response format: expected 5-element tuple, "
                f"got {type(result)}"
            )

        output_url = result[0]
        video_dict = result[1]
        video_id = result[2]
        task_id = result[3]
        error_msg = result[4]

        processing_time = time.time() - start_time
        self.logger.info(f"   Video ID: {video_id}, Task ID: {task_id}")

        # Check for API error
        if error_msg:
            self.logger.info(f"   ❌ API Error: {error_msg}")
            image_name = Path(file_path).stem
            video_name = Path(task_config['video_file']).stem
            combo_base = f"{video_name}_{image_name}"

            metadata = {
                'source_image': Path(file_path).name,
                'source_video': Path(task_config['video_file']).name,
                'video_id': video_id,
                'task_id': task_id,
                'error': error_msg,
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name,
            }
            self.processor.save_metadata(
                Path(metadata_folder), combo_base, file_name,
                metadata, task_config
            )
            return False

        # Build output filename: video-first ordering
        image_name = Path(file_path).stem
        video_name = Path(task_config['video_file']).stem
        output_filename = f"{video_name}_{image_name}_motion.mp4"
        output_path = Path(output_folder) / output_filename

        # Try to save video
        video_saved = False

        # Method 1: URL download
        if output_url:
            video_saved = self.processor.download_file(output_url, output_path)
            if video_saved:
                self.logger.info(f"   📥 Downloaded from URL: {output_path.name}")

        # Method 2: Local file copy
        if not video_saved and video_dict and isinstance(video_dict, dict) and 'video' in video_dict:
            local_path = Path(video_dict['video'])
            if local_path.exists():
                shutil.copy2(local_path, output_path)
                video_saved = True
                self.logger.info(f"   📥 Copied local file: {local_path}")

        if not video_saved:
            self.logger.warning("   ⚠️ Failed to save video — will retry")
            # Save failure metadata
            combo_base = f"{video_name}_{image_name}"
            metadata = {
                'source_image': Path(file_path).name,
                'source_video': Path(task_config['video_file']).name,
                'video_id': video_id,
                'task_id': task_id,
                'output_url': output_url,
                'error': 'Video download/save failed',
                'attempts': attempt + 1,
                'success': False,
                'processing_time_seconds': round(processing_time, 1),
                'processing_timestamp': datetime.now().isoformat(),
                'api_name': self.api_name,
            }
            self.processor.save_metadata(
                Path(metadata_folder), combo_base, file_name,
                metadata, task_config
            )
            return False

        # Save success metadata
        combo_base = f"{video_name}_{image_name}"
        metadata = {
            'source_image': Path(file_path).name,
            'source_video': Path(task_config['video_file']).name,
            'prompt': task_config.get('prompt', ''),
            'model': task_config.get('model', 'v3'),
            'character_orientation': task_config.get('character_orientation', 'video'),
            'mode': task_config.get('mode', 'pro'),
            'keep_original_sound': task_config.get('keep_original_sound', True),
            'element_list_str': task_config.get('element_list_str', ''),
            'output_url': output_url,
            'video_id': video_id,
            'task_id': task_id,
            'generated_video': output_filename,
            'processing_time_seconds': round(processing_time, 1),
            'processing_timestamp': datetime.now().isoformat(),
            'attempts': attempt + 1,
            'success': True,
            'api_name': self.api_name,
        }

        self.processor.save_metadata(
            Path(metadata_folder),
            combo_base,
            file_name,
            metadata,
            task_config,
        )

        self.logger.info(f"   ✅ Generated: {output_filename}")
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
        """Override: Kling Motion uses both images and videos."""
        return "source_image"
