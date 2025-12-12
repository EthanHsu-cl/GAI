"""
Base API Handler - Consolidates all common processing logic.
New APIs only need to implement the unique parts.
"""
import time
from pathlib import Path
from datetime import datetime


class BaseAPIHandler:
    """Base handler with ALL common logic. Subclasses override only what's different."""
    
    # Connection error patterns that warrant extended retry with backoff
    CONNECTION_ERROR_PATTERNS = [
        'Connection refused',
        'ConnectionRefusedError',
        'ConnectionResetError',
        'ConnectionError',
        'Errno 61',   # Connection refused (macOS)
        'Errno 111',  # Connection refused (Linux)
        'Errno 10061',  # Connection refused (Windows)
        'RemoteDisconnected',
        'ConnectionAbortedError',
        'BrokenPipeError',
        'Server disconnected',
        'Connection reset by peer',
    ]
    
    # Connection retry configuration
    CONNECTION_RETRY_MAX_DURATION = 240  # 4 minutes max wait
    CONNECTION_RETRY_INITIAL_WAIT = 10   # Start with 10 seconds
    CONNECTION_RETRY_MAX_WAIT = 60       # Cap at 60 seconds between retries
    CONNECTION_RETRY_BACKOFF = 1.5       # Exponential backoff multiplier
    
    def __init__(self, processor):
        self.processor = processor
        self.api_defs = processor.api_definitions
        self.config = processor.config
        self.client = processor.client
        self.logger = processor.logger
        self.api_name = processor.api_name
    
    def _is_connection_error(self, error_str):
        """Check if an error is a connection-related error."""
        error_lower = error_str.lower()
        return any(p.lower() in error_lower for p in self.CONNECTION_ERROR_PATTERNS)
    
    def _make_api_call_with_connection_retry(self, file_path, task_config, attempt):
        """Wrap API call with connection error retry logic.
        
        Implements exponential backoff retry specifically for connection errors,
        allowing the server up to CONNECTION_RETRY_MAX_DURATION seconds to recover.
        
        Args:
            file_path: Path to the source file.
            task_config: Task configuration dictionary.
            attempt: Current attempt number from the outer retry loop.
        
        Returns:
            API result if successful.
        
        Raises:
            Exception: Re-raises the last exception if all retries fail.
        """
        total_wait_time = 0
        current_wait = self.CONNECTION_RETRY_INITIAL_WAIT
        connection_retry_count = 0
        last_exception = None
        
        while total_wait_time < self.CONNECTION_RETRY_MAX_DURATION:
            try:
                return self._make_api_call(file_path, task_config, attempt)
            except Exception as e:
                error_str = str(e)
                
                # Only retry for connection errors
                if not self._is_connection_error(error_str):
                    raise e
                
                last_exception = e
                connection_retry_count += 1
                remaining_time = self.CONNECTION_RETRY_MAX_DURATION - total_wait_time
                
                # Don't wait if we've exceeded max duration
                if remaining_time <= 0:
                    break
                
                # Cap wait time to remaining duration
                actual_wait = min(current_wait, remaining_time)
                
                self.logger.warning(
                    f" ⚠️ Connection error (attempt {connection_retry_count}): {error_str}"
                )
                self.logger.info(
                    f" ⏳ Waiting {actual_wait:.0f}s for server recovery "
                    f"(total waited: {total_wait_time:.0f}s / {self.CONNECTION_RETRY_MAX_DURATION}s max)"
                )
                
                time.sleep(actual_wait)
                total_wait_time += actual_wait
                
                # Apply exponential backoff for next iteration
                current_wait = min(current_wait * self.CONNECTION_RETRY_BACKOFF, 
                                   self.CONNECTION_RETRY_MAX_WAIT)
        
        # All connection retries exhausted
        self.logger.error(
            f" ❌ Server unavailable after {total_wait_time:.0f}s "
            f"({connection_retry_count} connection retries)"
        )
        raise last_exception
    
    def process(self, file_path, task_config, output_folder, metadata_folder, attempt, max_retries):
        """Process a single file. Override _make_api_call() to customize."""
        base_name = Path(file_path).stem
        file_name = Path(file_path).name
        start_time = time.time()
        
        try:
            # Make API-specific call with connection retry wrapper
            result = self._make_api_call_with_connection_retry(file_path, task_config, attempt)
            
            # Parse and save result (subclass can override)
            success = self._handle_result(result, file_path, task_config, output_folder, 
                                         metadata_folder, base_name, file_name, start_time, attempt)
            
            if not success and attempt < max_retries - 1:
                time.sleep(5)
                return False
            
            return success
            
        except Exception as e:
            self._save_failure(file_path, task_config, metadata_folder, str(e), 
                             attempt, start_time)
            raise e
    
    def _make_api_call(self, file_path, task_config, attempt):
        """Override this in subclass to make API-specific call."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _make_api_call()")
    
    def _handle_result(self, result, file_path, task_config, output_folder, 
                      metadata_folder, base_name, file_name, start_time, attempt):
        """Override this to handle API-specific result format."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement _handle_result()")
    
    def _save_failure(self, file_path, task_config, metadata_folder, error, attempt, start_time):
        """Save failure metadata - common for all APIs."""
        # Handle text-to-video cases where file_path might be None
        if file_path is not None:
            base_name = Path(file_path).stem
            file_name = Path(file_path).name
        else:
            # For text-to-video, use style name or fallback
            style_name = task_config.get('style_name', 'unknown')
            gen_num = task_config.get('generation_number', 1)
            safe_style = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in style_name)
            safe_style = safe_style.strip().replace(' ', '_')
            base_name = f"{safe_style}-{gen_num}"
            file_name = None
        
        processing_time = time.time() - start_time
        
        metadata = {
            "error": error,
            "attempts": attempt + 1,
            "success": False,
            "processing_time_seconds": round(processing_time, 1),
            "processing_timestamp": datetime.now().isoformat(),
            "api_name": self.api_name
        }
        
        # Add source file name if available
        if file_name is not None:
            metadata[self._get_source_field()] = file_name
        
        # Add task-specific fields
        for key in ['prompt', 'effect', 'model']:
            if key in task_config:
                metadata[key] = task_config[key]
        
        self.processor.save_metadata(Path(metadata_folder), base_name, file_name, 
                                    metadata, task_config)
    
    def _get_source_field(self):
        """Get appropriate source field name based on API."""
        return "source_video" if self.api_name == "runway" else "source_image"
    
    def _is_file_processed(self, file_path, metadata_folder):
        """Check if a file has already been successfully processed.
        
        Args:
            file_path: Path to the source file.
            metadata_folder: Path to the metadata folder.
        
        Returns:
            bool: True if file has successful metadata, False otherwise.
        """
        base_name = Path(file_path).stem
        metadata_file = Path(metadata_folder) / f"{base_name}_metadata.json"
        
        if metadata_file.exists():
            try:
                import json
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                # Only skip if previous processing was successful
                return metadata.get('success', False)
            except (json.JSONDecodeError, IOError):
                return False
        return False
    
    def process_task(self, task, task_num, total_tasks):
        """Process entire task - common structure for most APIs."""
        folder = Path(task.get('folder', task.get('folder_path', '')))
        
        # Get folder paths (handles both structures)
        if 'source_dir' in task:
            source_folder = Path(task['source_dir'])
            output_folder = Path(task['generated_dir'])
            metadata_folder = Path(task['metadata_dir'])
        else:
            source_folder = folder / "Source"
            output_folder = self._get_output_folder(folder)
            metadata_folder = folder / "Metadata"
        
        task_name = task.get('effect', folder.name)
        self.logger.info(f"📁 Task {task_num}/{total_tasks}: {task_name}")
        
        # Get files to process
        files = self._get_task_files(task, source_folder)
        
        # Process files
        successful = 0
        skipped = 0
        for i, file_path in enumerate(files, 1):
            # Check if file was already successfully processed
            if self._is_file_processed(file_path, metadata_folder):
                self.logger.info(f" ⏭️ {i}/{len(files)}: {file_path.name} (already processed)")
                skipped += 1
                successful += 1
                continue
            
            self.logger.info(f" 🖼️ {i}/{len(files)}: {file_path.name}")
            
            if self.processor.process_file(file_path, task, output_folder, metadata_folder):
                successful += 1
            
            if i < len(files):
                time.sleep(self.api_defs.get('rate_limit', 3))
        
        self.logger.info(f"✓ Task {task_num}: {successful}/{len(files)} successful ({skipped} skipped)")
    
    def _get_output_folder(self, folder):
        """Get output folder name based on API type."""
        if self.api_name == "genvideo":
            return folder / "Generated_Image"
        elif self.api_name == "nano_banana":
            return folder / "Generated_Output"
        else:
            return folder / "Generated_Video"
    
    def _get_task_files(self, task, source_folder):
        """Get files for this task. Override for special handling."""
        file_type = 'video' if self.api_name == 'runway' else 'image'
        return self.processor._get_files_by_type(source_folder, file_type)
