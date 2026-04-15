import sys
import logging
from pathlib import Path
from typing import Dict, Optional, Any

# Import unified processors and report generators
from unified_api_processor import create_processor, ValidationError
from unified_report_generator import create_report_generator
from config_loader import load_and_merge_config, get_default_config_path

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# API mapping for backward compatibility
API_MAPPING = {
    'kling': 'kling',
    'klingfx': 'kling_effects',
    'kling_effects': 'kling_effects',
    'kling_endframe': 'kling_endframe',
    'kling_ttv': 'kling_ttv',
    'kling_motion': 'kling_motion',
    'klingmotion': 'kling_motion',
    'vidu': 'vidu_effects', 
    'viduref': 'vidu_reference',
    'nano': 'nano_banana',
    'runway': 'runway',
    'genvideo': 'genvideo',
    'pixverse': 'pixverse',
    'pixverse_ttv': 'pixverse_ttv',
    'pixversettv': 'pixverse_ttv',
    'wan': 'wan',
    'veo': 'veo',
    'veoitv': 'veo_itv',
    'dreamactor': 'dreamactor',
}

# Config file mapping
CONFIG_MAPPING = {
    'kling': 'config/batch_kling_config.yaml',
    'kling_effects': 'config/batch_kling_effects_config.yaml',
    'kling_endframe': 'config/batch_kling_endframe_config.yaml',
    'kling_ttv': 'config/batch_kling_ttv_config.yaml',
    'kling_motion': 'config/batch_kling_motion_config.yaml',
    'vidu_effects': 'config/batch_vidu_effects_config.yaml',
    'vidu_reference': 'config/batch_vidu_reference_config.yaml', 
    'nano_banana': 'config/batch_nano_banana_config.yaml',
    'runway': 'config/batch_runway_config.yaml',
    'genvideo': 'config/batch_genvideo_config.yaml',
    'pixverse': 'config/batch_pixverse_config.yaml',
    'pixverse_ttv': 'config/batch_pixverse_ttv_config.yaml',
    'wan': 'config/batch_wan_config.yaml',
    'veo': 'config/batch_veo_config.yaml',
    'veo_itv': 'config/batch_veo_itv_config.yaml',
    'dreamactor': 'config/batch_dreamactor_config.yaml'
}


def run_automation(
    platform: str,
    action: str = "auto",
    config_path: Optional[str] = None,
    parallel: bool = False,
    verbose: bool = False,
    runtime_overrides: Optional[Dict[str, Any]] = None,
    working_dir: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> int:
    """
    Run a single automation job programmatically.
    
    This is the main entry point for the GUI and other programmatic usage.
    Accepts runtime_overrides that are applied on top of the loaded YAML
    config without modifying files on disk.
    
    Args:
        platform: Platform short name (kling, klingfx, nano, etc.) or 'all'.
        action: Action to perform - 'process', 'report', or 'auto'.
        config_path: Optional path to config file. Uses default if not provided.
        parallel: Whether to run platforms in parallel (only for 'all').
        verbose: Enable verbose/debug logging.
        runtime_overrides: Dictionary of config overrides. Supports dot notation
            for nested keys (e.g., "tasks.0.prompt"). Applied in memory only.
        working_dir: Base directory for resolving relative paths in config.
            If not provided, uses the parent of the Scripts directory.
        progress_callback: Optional callback function for progress updates.
            Called with (message: str, level: str) where level is 'info',
            'warning', or 'error'.
    
    Returns:
        Exit code: 0 for success, 1 for failure.
    """
    # Set working directory for relative path resolution
    import os
    if not working_dir:
        # Default to the GAI project root (parent of the Scripts directory)
        working_dir = str(Path(__file__).parent.parent.parent)
    os.chdir(working_dir)
    logger.info(f"📂 Working directory: {working_dir}")
    
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("🔍 Verbose logging enabled")

    valid_platforms = list(API_MAPPING.keys()) + ['all']
    valid_actions = ['process', 'report', 'auto']

    if platform.lower() not in valid_platforms:
        msg = f"Invalid platform: {platform}. Valid: {', '.join(valid_platforms)}"
        logger.error(msg)
        if progress_callback:
            progress_callback(msg, 'error')
        return 1

    if action.lower() not in valid_actions:
        msg = f"Invalid action: {action}. Valid: {', '.join(valid_actions)}"
        logger.error(msg)
        if progress_callback:
            progress_callback(msg, 'error')
        return 1

    platform = platform.lower()
    action = action.lower()

    platforms_to_run = get_platforms_to_run(platform)

    logger.info(f"🚀 Starting execution")
    logger.info(f"Platforms: {', '.join(platforms_to_run)}")
    logger.info(f"Action: {action}")

    if progress_callback:
        progress_callback(f"Starting: {', '.join(platforms_to_run)} ({action})", 'info')

    if len(platforms_to_run) > 1 and parallel:
        all_results = _run_parallel_with_overrides(
            platforms_to_run, action, config_path, runtime_overrides, progress_callback
        )
    else:
        all_results = _run_sequential_with_overrides(
            platforms_to_run, action, config_path, runtime_overrides, progress_callback
        )

    success = _print_summary(all_results, action)

    logger.info("🏁 Execution completed")
    if progress_callback:
        status = "completed successfully" if success else "completed with errors"
        progress_callback(f"Execution {status}", 'info' if success else 'warning')

    return 0 if success else 1


def _run_sequential_with_overrides(
    platforms: list,
    action: str,
    config_path: Optional[str],
    runtime_overrides: Optional[Dict[str, Any]],
    progress_callback: Optional[callable] = None,
) -> Dict[str, Dict[str, bool]]:
    """
    Run platforms sequentially with runtime override support.
    
    Args:
        platforms: List of platform short names to run.
        action: Action to perform.
        config_path: Optional config file path override.
        runtime_overrides: Runtime config overrides.
        progress_callback: Optional progress callback.
    
    Returns:
        Dictionary mapping platform names to their results.
    """
    all_results = {}

    for i, platform in enumerate(platforms, 1):
        logger.info("=" * 60)
        logger.info(f"PLATFORM {i}/{len(platforms)}: {platform.upper()}")
        logger.info("=" * 60)

        if progress_callback:
            progress_callback(f"Processing {platform} ({i}/{len(platforms)})", 'info')

        results = _run_platform_with_overrides(
            platform, action, config_path, runtime_overrides
        )
        all_results[platform] = results

    return all_results


def _run_parallel_with_overrides(
    platforms: list,
    action: str,
    config_path: Optional[str],
    runtime_overrides: Optional[Dict[str, Any]],
    progress_callback: Optional[callable] = None,
) -> Dict[str, Dict[str, bool]]:
    """
    Run platforms in parallel with runtime override support.
    
    Args:
        platforms: List of platform short names to run.
        action: Action to perform.
        config_path: Optional config file path override.
        runtime_overrides: Runtime config overrides.
        progress_callback: Optional progress callback.
    
    Returns:
        Dictionary mapping platform names to their results.
    """
    from concurrent.futures import ThreadPoolExecutor

    logger.info(f"🚀 Running {len(platforms)} platforms in parallel")
    if progress_callback:
        progress_callback(f"Running {len(platforms)} platforms in parallel", 'info')

    all_results = {}

    with ThreadPoolExecutor(max_workers=min(4, len(platforms))) as executor:
        futures = {}
        for platform in platforms:
            future = executor.submit(
                _run_platform_with_overrides,
                platform, action, config_path, runtime_overrides
            )
            futures[future] = platform

        for future in futures:
            platform = futures[future]
            try:
                results = future.result()
                all_results[platform] = results
            except Exception as e:
                logger.error(f"❌ {platform} failed with exception: {e}")
                all_results[platform] = {'processing': False, 'reporting': False}

    return all_results


def _run_platform_with_overrides(
    platform: str,
    action: str,
    config_path: Optional[str],
    runtime_overrides: Optional[Dict[str, Any]],
) -> Dict[str, bool]:
    """
    Run processing and/or reporting for a single platform with overrides.
    
    Args:
        platform: Platform short name.
        action: Action to perform.
        config_path: Optional config file path override.
        runtime_overrides: Runtime config overrides.
    
    Returns:
        Results dictionary with 'processing' and/or 'reporting' keys.
    """
    api_name = API_MAPPING[platform]

    if not config_path:
        config_path = CONFIG_MAPPING.get(api_name)
        if config_path:
            script_dir = Path(__file__).parent.parent
            full_path = script_dir / config_path
            if full_path.exists():
                config_path = str(full_path)
            elif not Path(config_path).exists():
                logger.warning(f"⚠️ Config file not found: {config_path}")
                config_path = None
    else:
        # User-provided config path: if not found directly, try from Scripts dir
        if not Path(config_path).exists():
            script_dir = Path(__file__).parent.parent
            alt_path = script_dir / config_path
            if alt_path.exists():
                config_path = str(alt_path)

    merged_config = None
    if config_path or runtime_overrides:
        try:
            merged_config = load_and_merge_config(config_path, runtime_overrides)
        except FileNotFoundError:
            logger.warning(f"⚠️ Config file not found: {config_path}")
            merged_config = runtime_overrides.copy() if runtime_overrides else {}
        except Exception as e:
            logger.error(f"❌ Error loading config: {e}")
            merged_config = runtime_overrides.copy() if runtime_overrides else {}

    results = {}
    skip_report = False

    if action in ['process', 'auto']:
        processing_success, skip_report = _run_processor_with_config(
            api_name, config_path, merged_config
        )
        results['processing'] = processing_success

    if action in ['report', 'auto']:
        if skip_report:
            logger.warning(
                f"⏭️ Skipping report generation for {platform} due to validation errors"
            )
            results['reporting'] = False
        else:
            results['reporting'] = _run_report_with_config(
                api_name, config_path, merged_config
            )

    return results


def _run_processor_with_config(
    api_name: str,
    config_file: Optional[str],
    merged_config: Optional[Dict[str, Any]],
) -> tuple:
    """
    Run API processor with pre-merged configuration.
    
    Args:
        api_name: Internal API name.
        config_file: Config file path (for processor reference).
        merged_config: Pre-merged configuration dictionary.
    
    Returns:
        Tuple of (success: bool, skip_report: bool).
    """
    try:
        logger.info(f"🔄 Processing: {api_name.replace('_', ' ').title()}")

        processor = create_processor(api_name, config_file)
        
        if merged_config:
            processor.set_config(merged_config)

        success = processor.run()

        if success:
            logger.info(f"✅ {api_name} processing completed successfully")
        else:
            logger.error(f"❌ {api_name} processing failed")

        return success, False

    except ValidationError as e:
        logger.error(f"❌ {api_name} validation failed: {e}")
        logger.warning("⚠️ Skipping report generation due to validation errors")
        return False, True

    except Exception as e:
        logger.error(f"❌ {api_name} processing error: {e}")
        return False, False


def _run_report_with_config(
    api_name: str,
    config_file: Optional[str],
    merged_config: Optional[Dict[str, Any]],
) -> bool:
    """
    Run report generator with pre-merged configuration.
    
    Args:
        api_name: Internal API name.
        config_file: Config file path (for generator reference).
        merged_config: Pre-merged configuration dictionary.
    
    Returns:
        True if report generation succeeded, False otherwise.
    """
    try:
        logger.info(f"📊 Generating report: {api_name.replace('_', ' ').title()}")

        generator = create_report_generator(api_name, config_file)
        
        if merged_config:
            generator.set_config(merged_config)

        success = generator.run()

        if success:
            logger.info(f"✅ {api_name} report generated successfully")
        else:
            logger.error(f"❌ {api_name} report generation failed")

        return success

    except Exception as e:
        logger.error(f"❌ {api_name} report generation error: {e}")
        return False


def _print_summary(all_results: Dict[str, Dict[str, bool]], action: str) -> bool:
    """
    Print execution summary and return overall success status.
    
    Args:
        all_results: Dictionary of platform results.
        action: Action that was performed.
    
    Returns:
        True if at least one operation succeeded, False otherwise.
    """
    logger.info("=" * 60)
    logger.info("EXECUTION SUMMARY")
    logger.info("=" * 60)

    total_platforms = len(all_results)

    if action in ['process', 'auto']:
        processing_success = sum(
            1 for results in all_results.values()
            if results.get('processing', False)
        )
        logger.info(f"📊 Processing: {processing_success}/{total_platforms} successful")

        for platform, results in all_results.items():
            status = "✅ SUCCESS" if results.get('processing', False) else "❌ FAILED"
            logger.info(f"   {platform:10} → {status}")

    if action in ['report', 'auto']:
        reporting_success = sum(
            1 for results in all_results.values()
            if results.get('reporting', False)
        )
        logger.info(f"📈 Reporting: {reporting_success}/{total_platforms} successful")

        for platform, results in all_results.items():
            status = "✅ GENERATED" if results.get('reporting', False) else "❌ FAILED"
            logger.info(f"   {platform:10} → {status}")

    total_operations = 0
    successful_operations = 0

    for results in all_results.values():
        for success in results.values():
            total_operations += 1
            if success:
                successful_operations += 1

    success_rate = (
        (successful_operations / total_operations * 100)
        if total_operations > 0 else 0
    )
    logger.info(
        f"🎯 Overall Success Rate: {successful_operations}/{total_operations} "
        f"({success_rate:.1f}%)"
    )

    return successful_operations > 0

def show_usage():
    """Display usage information"""
    print("Usage: python runall.py [platform] [action] [options]")
    print()
    print("PLATFORMS:")
    print("  kling - Kling Image2Video processing")
    print("  klingfx - Kling Video Effects (premade effects)")
    print("  kling_endframe - Kling Endframe (start/end image pairs)")
    print("  kling_ttv - Kling Text-to-Video processing")
    print("  vidu - Vidu Effects processing")
    print("  viduref - Vidu Reference processing")
    print("  nano - Google Flash/Nano Banana processing")
    print("  runway - Runway face swap processing")
    print("  genvideo - GenVideo image generation processing")
    print("  pixverse - Pixverse Effects processing")
    print("  pixverse_ttv - Pixverse Text-to-Video processing")
    print("  wan - Wan 2.2 image-video animation processing")
    print("  veo - Google Veo text-to-video processing")
    print("  veoitv - Google Veo image-to-video processing")
    print("  all - Run all platforms")
    print()
    print("ACTIONS:")
    print("  process - Run API processors only")
    print("  report - Generate PowerPoint reports only")
    print("  auto - Run processor + generate report (default)")
    print()
    print("OPTIONS:")
    print("  --config FILE - Override config file path")
    print("  --parallel - Run platforms in parallel (for 'all')")
    print("  --verbose - Enable verbose logging")
    print()
    print("EXAMPLES:")
    print("  python runall.py nano report")
    print("  python runall.py kling process")
    print("  python runall.py klingfx auto")
    print("  python runall.py kling_endframe auto")
    print("  python runall.py kling_ttv auto")
    print("  python runall.py vidu auto")
    print("  python runall.py viduref auto --verbose")
    print("  python runall.py pixverse process")
    print("  python runall.py pixverse_ttv auto")
    print("  python runall.py wan auto")
    print("  python runall.py veo auto")
    print("  python runall.py all auto --parallel")
    print("  python runall.py runway process --config custom_runway_config.json")
    print("  python runall.py genvideo process")

def parse_arguments():
    """Parse command line arguments"""
    if len(sys.argv) < 2:
        show_usage()
        sys.exit(1)

    args = {
        'platform': sys.argv[1].lower(),
        'action': sys.argv[2].lower() if len(sys.argv) > 2 else "auto",
        'config': None,
        'parallel': False,
        'verbose': False
    }

    # Parse options
    i = 3
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--config' and i + 1 < len(sys.argv):
            args['config'] = sys.argv[i + 1]
            i += 2
        elif arg == '--parallel':
            args['parallel'] = True
            i += 1
        elif arg == '--verbose':
            args['verbose'] = True
            i += 1
        else:
            logger.warning(f"Unknown option: {arg}")
            i += 1

    return args

def validate_arguments(args):
    """Validate parsed arguments"""
    valid_platforms = list(API_MAPPING.keys()) + ['all']
    valid_actions = ['process', 'report', 'auto']

    if args['platform'] not in valid_platforms:
        logger.error(f"Invalid platform: {args['platform']}")
        logger.error(f"Valid platforms: {', '.join(valid_platforms)}")
        return False

    if args['action'] not in valid_actions:
        logger.error(f"Invalid action: {args['action']}")
        logger.error(f"Valid actions: {', '.join(valid_actions)}")
        return False

    return True

def get_platforms_to_run(platform_arg):
    """Get list of platforms to run based on argument"""
    if platform_arg == 'all':
        return list(API_MAPPING.keys())
    else:
        return [platform_arg]

def run_processor(api_name, config_file=None):
    """Run API processor for given platform.
    
    Args:
        api_name: Name of the API to process.
        config_file: Optional path to config file.
    
    Returns:
        tuple: (success: bool, skip_report: bool)
            - success: True if processing completed successfully
            - skip_report: True if validation failed and report should be skipped
    """
    try:
        logger.info(f"🔄 Processing: {api_name.replace('_', ' ').title()}")

        processor = create_processor(api_name, config_file)
        success = processor.run()

        if success:
            logger.info(f"✅ {api_name} processing completed successfully")
        else:
            logger.error(f"❌ {api_name} processing failed")

        return success, False  # success status, don't skip report

    except ValidationError as e:
        logger.error(f"❌ {api_name} validation failed: {e}")
        logger.warning(f"⚠️ Skipping report generation due to validation errors")
        return False, True  # failed, skip report
    
    except Exception as e:
        logger.error(f"❌ {api_name} processing error: {e}")
        return False, False  # failed, but don't skip report (other errors)

def run_report_generator(api_name, config_file=None):
    """Run report generator for given platform"""
    try:
        logger.info(f"📊 Generating report: {api_name.replace('_', ' ').title()}")

        # All APIs now use unified report generator
        generator = create_report_generator(api_name, config_file)
        
        success = generator.run()

        if success:
            logger.info(f"✅ {api_name} report generated successfully")
        else:
            logger.error(f"❌ {api_name} report generation failed")

        return success

    except Exception as e:
        logger.error(f"❌ {api_name} report generation error: {e}")
        return False

def run_platform(platform, action, config_file=None):
    """Run processing and/or reporting for a single platform.
    
    Args:
        platform: Platform name to run.
        action: Action to perform ('process', 'report', or 'auto').
        config_file: Optional path to config file.
    
    Returns:
        dict: Results dictionary with 'processing' and/or 'reporting' keys.
    """
    api_name = API_MAPPING[platform]

    # Use provided config or default
    if not config_file:
        config_file = CONFIG_MAPPING.get(api_name)

    # Resolve config path: try Scripts dir as fallback for relative paths
    if config_file and not Path(config_file).exists():
        script_dir = Path(__file__).parent.parent
        alt_path = script_dir / config_file
        if alt_path.exists():
            config_file = str(alt_path)
        else:
            logger.warning(f"⚠️ Config file not found: {config_file}")
            logger.info(f"Proceeding without config file for {platform}")
            config_file = None

    results = {}
    skip_report = False

    # Run processing if requested
    if action in ['process', 'auto']:
        processing_success, skip_report = run_processor(api_name, config_file)
        results['processing'] = processing_success

    # Run reporting if requested (skip if validation failed during processing)
    if action in ['report', 'auto']:
        if skip_report:
            logger.warning(f"⏭️ Skipping report generation for {platform} due to validation errors")
            results['reporting'] = False
        else:
            results['reporting'] = run_report_generator(api_name, config_file)

    return results

def run_parallel(platforms, action, args):
    """Run platforms in parallel"""
    from concurrent.futures import ThreadPoolExecutor

    logger.info(f"🚀 Running {len(platforms)} platforms in parallel")

    all_results = {}

    with ThreadPoolExecutor(max_workers=min(4, len(platforms))) as executor:
        # Submit all tasks
        futures = {}
        for platform in platforms:
            config_file = args['config'] if args['config'] else CONFIG_MAPPING.get(API_MAPPING[platform])
            future = executor.submit(run_platform, platform, action, config_file)
            futures[future] = platform

        # Collect results
        for future in futures:
            platform = futures[future]
            try:
                results = future.result()
                all_results[platform] = results
            except Exception as e:
                logger.error(f"❌ {platform} failed with exception: {e}")
                all_results[platform] = {'processing': False, 'reporting': False}

    return all_results

def run_sequential(platforms, action, args):
    """Run platforms sequentially"""
    all_results = {}

    for i, platform in enumerate(platforms, 1):
        logger.info(f"{'='*60}")
        logger.info(f"PLATFORM {i}/{len(platforms)}: {platform.upper()}")
        logger.info("="*60)

        config_file = args['config'] if args['config'] else CONFIG_MAPPING.get(API_MAPPING[platform])
        results = run_platform(platform, action, config_file)
        all_results[platform] = results

    return all_results

def print_summary(all_results, action):
    """Print execution summary"""
    logger.info(f"{'='*60}")
    logger.info("EXECUTION SUMMARY")
    logger.info("="*60)

    total_platforms = len(all_results)

    if action in ['process', 'auto']:
        processing_success = sum(1 for results in all_results.values() 
                               if results.get('processing', False))
        logger.info(f"📊 Processing: {processing_success}/{total_platforms} successful")

        for platform, results in all_results.items():
            status = "✅ SUCCESS" if results.get('processing', False) else "❌ FAILED"
            logger.info(f"   {platform:10} → {status}")

    if action in ['report', 'auto']:
        reporting_success = sum(1 for results in all_results.values() 
                              if results.get('reporting', False))
        logger.info(f"📈 Reporting: {reporting_success}/{total_platforms} successful")

        for platform, results in all_results.items():
            status = "✅ GENERATED" if results.get('reporting', False) else "❌ FAILED"
            logger.info(f"   {platform:10} → {status}")

    # Overall success
    total_operations = 0
    successful_operations = 0

    for results in all_results.values():
        for operation, success in results.items():
            total_operations += 1
            if success:
                successful_operations += 1

    success_rate = (successful_operations / total_operations * 100) if total_operations > 0 else 0
    logger.info(f"🎯 Overall Success Rate: {successful_operations}/{total_operations} ({success_rate:.1f}%)")

    return successful_operations > 0

def main():
    """Main execution function for CLI usage."""
    args = parse_arguments()

    exit_code = run_automation(
        platform=args['platform'],
        action=args['action'],
        config_path=args['config'],
        parallel=args['parallel'],
        verbose=args['verbose'],
        runtime_overrides=None,
        working_dir=None,
    )

    return exit_code == 0


if __name__ == "__main__":
    try:
        sys.exit(0 if main() else 1)
    except KeyboardInterrupt:
        logger.info("\n⏹️ Execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)
