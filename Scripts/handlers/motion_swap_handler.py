"""Motion Swap API Handler - Image-video cross-matching for motion transfer."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
import json
from datetime import datetime
from .base_handler import BaseAPIHandler


class MotionSwapHandler(BaseAPIHandler):
    """
    Motion Swap handler.

    Processes images and videos through cross-matching:
    each subject image is paired with each motion reference video to
    produce motion-swapped output videos.

    Cross-matches all images with all videos
    (e.g., 3 images x 4 videos = 12 generations).
    """

    def validate_structure(self, tasks, config):
        """Validate Motion Swap with Source Image + Source Video cross-match.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        return self._validate_image_video_cross_match_structure(tasks)

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

                # Skip metadata uses video-first ordering to match success records
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
        Make Motion Swap API call.

        Sends a subject image and motion reference video to the
        /motion_swap_submit endpoint for motion transfer generation.

        Args:
            file_path: Path to subject image.
            task_config: Task configuration containing video_file.
            attempt: Current retry attempt number.

        Returns:
            API result tuple of 5 elements
            (output_url, video_dict, thumbnail, task_id, error_message).
        """
        image_path = Path(file_path)
        video_path = Path(task_config['video_file'])

        return self.client.predict(
            subject_image=handle_file(str(image_path)),
            motion_video={
                "video": handle_file(str(video_path)),
                "subtitles": None,
            },
            api_name=self.api_defs['api_name']
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time,
                       attempt):
        """
        Handle Motion Swap API result.

        Args:
            result: API result tuple of 5 elements
                (output_url, video_dict, thumbnail, task_id, error_message).
            file_path: Subject image path.
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
        thumbnail = result[2]
        task_id = result[3]
        error_message = result[4]

        self.logger.info(f"   Task ID: {task_id}")

        # Helper to save failure metadata for early exits
        def _save_fail_meta(error_reason):
            meta = {
                "source_image": Path(file_path).name,
                "source_video": Path(task_config['video_file']).name,
                "task_id": task_id,
                "error": error_reason,
                "attempts": attempt + 1,
                "success": False,
                "processing_time_seconds": round(time.time() - start_time, 1),
                "processing_timestamp": datetime.now().isoformat(),
                "api_name": self.api_name,
            }
            image_n = Path(file_path).stem
            video_n = Path(task_config['video_file']).stem
            self.processor.save_metadata(
                Path(metadata_folder), f"{video_n}_{image_n}",
                file_name, meta, task_config,
            )

        # Surface API-reported errors before attempting extraction
        if error_message:
            self.logger.warning(
                f"   ⚠️ API returned error: {error_message} — will retry"
            )
            _save_fail_meta(error_message)
            return False

        # Extract video path from result (video dict first, then output URL)
        video_path = None
        if isinstance(video_dict, dict) and video_dict.get('video'):
            video_path = video_dict['video']
        elif isinstance(video_dict, str) and video_dict:
            video_path = video_dict
        elif output_url:
            video_path = output_url

        if not video_path:
            self.logger.warning(
                f"   ⚠️ API returned no video — generation failed, will retry"
            )
            _save_fail_meta("API returned no video")
            return False

        # Build output filename: video-first ordering
        image_name = Path(file_path).stem
        video_name = Path(task_config['video_file']).stem
        output_filename = f"{video_name}_{image_name}_motion_swap.mp4"
        output_path = Path(output_folder) / output_filename

        # Save video (local copy or remote download)
        video_source = Path(video_path)
        if video_source.exists():
            shutil.copy2(video_source, output_path)
            self.logger.info(f"   📥 Copied local file: {video_source}")
        else:
            if not self.processor.download_file(video_path, output_path):
                raise IOError(f"Failed to download video from {video_path}")

        # Save success metadata
        processing_time = time.time() - start_time
        metadata = {
            "source_image": Path(file_path).name,
            "source_video": Path(task_config['video_file']).name,
            "task_id": task_id,
            "output_url": output_url,
            "generated_video": output_filename,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "attempts": attempt + 1,
            "success": True,
            "api_name": self.api_name,
        }

        self.processor.save_metadata(
            Path(metadata_folder),
            f"{video_name}_{image_name}",
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
            file_path: Subject image path.
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
        """Override: Motion Swap uses both images and videos."""
        return "source_image"
