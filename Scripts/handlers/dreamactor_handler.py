"""DreamActor API Handler - Image-video cross-matching for face reenactment."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
import json
from datetime import datetime
from .base_handler import BaseAPIHandler


class DreamactorHandler(BaseAPIHandler):
    """
    DreamActor handler.

    Processes images and videos through cross-matching:
    each source image is paired with each driver video to produce
    face-reenacted output videos.

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

                combo_base = f"{image_file.stem}_{video_file.stem}"
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
        Make DreamActor API call.

        Sends a source image and driver video to the /process_dreamactor
        endpoint for face reenactment generation.

        Args:
            file_path: Path to source image (reference face).
            task_config: Task configuration containing video_file and parameters.
            attempt: Current retry attempt number.

        Returns:
            API result tuple (video, task_id, time_taken, status_code, debug_info).
        """
        image_path = Path(file_path)
        video_path = Path(task_config['video_file'])

        use_base64 = task_config.get(
            'use_base64', self.config.get('use_base64', True)
        )
        video_url_direct = task_config.get('video_url_direct', '')
        cut_switch = task_config.get(
            'cut_switch', self.config.get('cut_switch', True)
        )

        return self.client.predict(
            image_input_path=handle_file(str(image_path)),
            use_base64=use_base64,
            video_file_path={
                "video": handle_file(str(video_path)),
                "subtitles": None,
            },
            video_url_direct=video_url_direct,
            cut_switch=cut_switch,
            api_name=self.api_defs['api_name']
        )

    def _handle_result(self, result, file_path, task_config, output_folder,
                       metadata_folder, base_name, file_name, start_time,
                       attempt):
        """
        Handle DreamActor API result.

        Args:
            result: API result tuple of 5 elements
                (video_dict, task_id, time_taken, status_code, debug_info).
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

        video_dict = result[0]
        task_id = result[1]
        time_taken = result[2]
        status_code = result[3]
        debug_info = result[4]

        self.logger.info(f"   Task ID: {task_id}")

        # Extract video path from result
        video_path = None
        if video_dict is None:
            self.logger.warning(
                f"   ⚠️ API returned None video — generation failed, will retry"
            )
            return False
        elif isinstance(video_dict, dict) and 'video' in video_dict:
            video_path = video_dict['video']
        elif isinstance(video_dict, str):
            video_path = video_dict
        else:
            self.logger.warning(
                f"   ⚠️ Unexpected video format: {type(video_dict)} — will retry"
            )
            return False

        if not video_path:
            self.logger.warning("   ⚠️ Empty video path returned — will retry")
            return False

        # Build output filename: video-first ordering
        image_name = Path(file_path).stem
        video_name = Path(task_config['video_file']).stem
        output_filename = f"{video_name}_{image_name}_dreamactor.mp4"
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
            "use_base64": task_config.get('use_base64', True),
            "cut_switch": task_config.get('cut_switch', True),
            "task_id": task_id,
            "time_taken": time_taken,
            "status_code": status_code,
            "debug_info": debug_info,
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
        """Override: DreamActor uses both images and videos."""
        return "source_image"
