"""GenVideo API Handler - Only unique logic."""
from pathlib import Path
from gradio_client import handle_file
import shutil
import time
from datetime import datetime
from .base_handler import BaseAPIHandler


class GenvideoHandler(BaseAPIHandler):
    """GenVideo image-to-image handler."""

    def validate_structure(self, tasks, config):
        """GenVideo uses Generated_Image instead of Generated_Video.

        Args:
            tasks: List of task configuration dictionaries.
            config: Full processor configuration dictionary.

        Returns:
            list: Valid task dictionaries.

        Raises:
            ValidationError: If invalid files are found.
        """
        return self._validate_source_images_structure(tasks, output_dir_name='Generated_Image')

    def _make_api_call(self, file_path, task_config, attempt):
        """Make GenVideo API call."""
        model = task_config.get('model', self.api_defs['api_params']['model'])
        img_prompt = task_config.get('img_prompt', self.api_defs['api_params']['img_prompt'])
        quality = task_config.get('quality', self.api_defs['api_params']['quality'])
        
        self.logger.info(f"   Model: {model}, Quality: {quality}")
        
        return self.client.predict(
            model=model,
            img_prompt=img_prompt,
            input_image=handle_file(str(file_path)),
            quality=quality,
            api_name="/submit_img2img"
        )
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Handle GenVideo API result."""
        if not result:
            raise ValueError("No result returned from API")
        
        # Handle both dict and string results
        output_filename = f"{base_name}_generated.png"
        output_path = Path(output_folder) / output_filename
        
        if isinstance(result, str):
            source_path = Path(result)
            if not source_path.exists():
                raise ValueError(f"Generated image path does not exist: {source_path}")
            shutil.copy2(source_path, output_path)
        elif isinstance(result, dict):
            if 'path' in result and result['path']:
                source_path = Path(result['path'])
                if not source_path.exists():
                    raise ValueError(f"Generated image path does not exist: {source_path}")
                shutil.copy2(source_path, output_path)
            elif 'url' in result and result['url']:
                if not self.processor.download_file(result['url'], output_path):
                    raise IOError("Image download failed")
            else:
                raise ValueError(f"Dict result missing path/url: {result}")
        else:
            raise ValueError(f"Unexpected result type {type(result)}: {result}")
        
        # Save success metadata
        processing_time = time.time() - start_time
        metadata = {
            "model": task_config.get('model', ''),
            "img_prompt": task_config.get('img_prompt', ''),
            "quality": task_config.get('quality', ''),
            "generated_image": output_filename,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "attempts": attempt + 1,
            "success": True,
            "api_name": self.api_name
        }
        
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                    metadata, task_config)
        self.logger.info(f"   ✅ Generated: {output_filename}")
        
        return True
