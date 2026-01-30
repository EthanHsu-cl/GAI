from PIL import Image
import os
from pathlib import Path

def resize_images(input_folder, output_folder=None, max_size=4000):
    input_path = Path(input_folder)
    output_path = Path(output_folder) if output_folder else input_path / "resized"
    output_path.mkdir(exist_ok=True)
    
    # Fixed: separate glob patterns for each extension
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.tiff', '*.bmp', '*.JPG', '*.JPEG', '*.PNG']
    
    image_files = []
    for ext in extensions:
        image_files.extend(input_path.glob(ext))
    
    if not image_files:
        print(f"No image files found in {input_path}")
        print("Files in directory:")
        for file in input_path.iterdir():
            print(f"  {file.name}")
        return
    
    for image_file in image_files:
        try:
            with Image.open(image_file) as img:
                original_size = img.size
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                new_size = img.size
                
                output_file = output_path / image_file.name
                img.save(output_file, quality=95, optimize=True)
                print(f"Resized: {image_file.name} from {original_size} to {new_size}")
        except Exception as e:
            print(f"Error processing {image_file.name}: {e}")

# Usage
resize_images("/Users/ethanhsu/Desktop/GAI/Pixverse/0922 4 Styles/Skull Multiverse/Source")