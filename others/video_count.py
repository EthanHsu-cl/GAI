import os

def count_videos_in_directory(directory='.'):
    video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.webm'}
    video_count = 0

    for root, _, files in os.walk(directory):
        for file in files:
            if os.path.splitext(file)[1].lower() in video_extensions:
                video_count += 1

    return video_count

if __name__ == "__main__":
    total_videos = count_videos_in_directory()
    print(f"Total video files: {total_videos}")
