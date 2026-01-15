#!/usr/bin/env python3
"""
SmugMug Downloader
Downloads all albums and images from a SmugMug account, preserving folder hierarchy.
"""

import os
import sys
import requests
from requests_oauthlib import OAuth1Session
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

try:
    from config import API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, NICKNAME
except ImportError:
    print("Error: config.py not found!")
    print("\nPlease create config.py with your credentials.")
    sys.exit(1)


class Logger:
    """Simple logger that writes to both terminal and file."""
    def __init__(self, log_file_path, also_print=True):
        self.log_file_path = log_file_path
        self.also_print = also_print
        self.log_file = None

    def __enter__(self):
        self.log_file = open(self.log_file_path, 'w', encoding='utf-8')
        self.log(f"SmugMug Download Log - Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("="*80)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.log_file:
            self.log("="*80)
            self.log(f"Log ended at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.log_file.close()

    def log(self, message):
        """Write message to log file and optionally to terminal."""
        if self.log_file:
            self.log_file.write(message + '\n')
            self.log_file.flush()  # Ensure immediate write
        if self.also_print:
            print(message)


class SmugMugDownloader:
    def __init__(self, api_key, api_secret, access_token, access_secret, base_path, logger=None):
        self.oauth = OAuth1Session(
            api_key,
            client_secret=api_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_secret
        )
        self.base_path = Path(base_path)
        self.logger = logger
        self.total_downloaded = 0
        self.total_skipped = 0
        self.total_images = 0
        self.total_albums = 0
        self.total_folders = 0
        self.total_metadata_saved = 0
        self.total_album_metadata_saved = 0
        self.total_duplicates = 0  # True duplicates (same ImageKey)
        self.total_renamed = 0  # Filename collisions (renamed)
        self.failed_downloads = []  # List of (filename, album, reason) tuples
        self.duplicate_log = []  # List of (imagekey, filename, album, reason) tuples
        self.renamed_files = []  # List of (original, renamed, album) tuples
        self.skipped_log = []  # List of (filename, album, imagekey, original_path, skipped_path) tuples

    def log(self, message):
        """Write to logger if available, otherwise print."""
        if self.logger:
            self.logger.log(message)
        else:
            print(message)

    def fetch_images(self, album_uri):
        """Fetch all images in an album with pagination support."""
        images = []
        url = f'https://api.smugmug.com{album_uri}!images'
        headers = {'Accept': 'application/json'}
        # Request image size details, metadata, and largest image URIs
        params = {'_expand': 'ImageSizeDetails,LargestImage', '_verbosity': 1}
        first_request = True

        while url:
            try:
                # Use params only for first request; pagination URLs include params
                if first_request:
                    response = self.oauth.get(url, headers=headers, params=params)
                    first_request = False
                else:
                    response = self.oauth.get(url, headers=headers)

                if response.status_code != 200:
                    self.log(f"  [Warning: HTTP {response.status_code} fetching images from {album_uri}]")
                    break

                data = response.json()['Response']
                images.extend(data.get('AlbumImage', []))

                # Check for next page
                next_page = data.get('Pages', {}).get('NextPage')
                if next_page:
                    url = f'https://api.smugmug.com{next_page}'
                else:
                    url = None
            except Exception as e:
                self.log(f"  [Error fetching images: {e}]")
                break

        return images

    def get_image_download_url(self, image_info):
        """Get the best download URL for an image (original or largest available)."""
        uris = image_info.get('Uris', {})

        # 1. Try ImageSizeDetails to get Original or largest size
        size_details_uri = uris.get('ImageSizeDetails', {})
        if isinstance(size_details_uri, dict):
            size_details_uri = size_details_uri.get('Uri', '')

        if size_details_uri:
            try:
                resp = self.oauth.get(
                    f'https://api.smugmug.com{size_details_uri}',
                    headers={'Accept': 'application/json'}
                )
                if resp.status_code == 200:
                    sizes = resp.json().get('Response', {}).get('ImageSizeDetails', {})
                    # Prefer original, then progressively smaller sizes
                    for size_key in ['ImageSizeOriginal', 'ImageSizeX5Large', 'ImageSizeX4Large',
                                     'ImageSizeX3Large', 'ImageSizeX2Large', 'ImageSizeXLarge',
                                     'ImageSizeLarge']:
                        size_info = sizes.get(size_key, {})
                        url = size_info.get('Url')
                        if url:
                            return url
            except Exception:
                pass

        # 2. Fallback: try ArchivedUri directly
        archived_uri = image_info.get('ArchivedUri')
        if archived_uri:
            return archived_uri

        # 3. Try LargestImage endpoint
        largest_image_uri = uris.get('LargestImage', {})
        if isinstance(largest_image_uri, dict):
            largest_image_uri = largest_image_uri.get('Uri', '')

        if largest_image_uri:
            try:
                resp = self.oauth.get(
                    f'https://api.smugmug.com{largest_image_uri}',
                    headers={'Accept': 'application/json'}
                )
                if resp.status_code == 200:
                    largest = resp.json().get('Response', {}).get('LargestImage', {})
                    url = largest.get('Url')
                    if url:
                        return url
            except Exception:
                pass

        # 4. Final fallback: ImageDownload
        image_download = uris.get('ImageDownload', {})
        if isinstance(image_download, dict):
            return image_download.get('Uri', '')
        elif isinstance(image_download, str):
            return image_download

        return None

    def save_album_metadata(self, album_info, album_path):
        """Save album/gallery metadata (title, description) to a text file."""
        # Create metadata filename based on album name
        album_name = album_info.get('Name', 'album')
        # Replace spaces with underscores and sanitize
        metadata_filename = album_name.replace(' ', '_')
        metadata_filename = self.sanitize_filename(metadata_filename) + '.txt'
        metadata_path = album_path / metadata_filename

        # Check if metadata file already exists
        if metadata_path.exists():
            return

        # Extract metadata
        name = album_info.get('Name', '')
        description = album_info.get('Description', '')
        keywords = album_info.get('Keywords', '')

        # Only create file if there's metadata to save
        if not name and not description and not keywords:
            return

        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                if name:
                    f.write(f"Gallery Title: {name}\n")
                if description:
                    f.write(f"Gallery Description: {description}\n")
                if keywords:
                    f.write(f"Keywords: {keywords}\n")
            self.total_album_metadata_saved += 1
        except Exception as e:
            self.log(f"  [Warning: Failed to save album metadata: {e}]")

    def save_image_metadata(self, image_info, image_path):
        """Save image metadata (title, caption, keywords) to a text file."""
        # Create metadata filename: image.jpg -> image.txt (not image.jpg.txt)
        metadata_path = image_path.with_suffix('.txt')

        # Check if metadata file already exists
        if metadata_path.exists():
            return

        # Extract metadata
        title = image_info.get('Title', '')
        caption = image_info.get('Caption', '')
        keywords = image_info.get('Keywords', '')

        # Only create file if there's metadata to save
        if not title and not caption and not keywords:
            return

        try:
            with open(metadata_path, 'w', encoding='utf-8') as f:
                if title:
                    f.write(f"Title: {title}\n")
                if caption:
                    f.write(f"Caption: {caption}\n")
                if keywords:
                    f.write(f"Keywords: {keywords}\n")
            self.total_metadata_saved += 1
        except Exception as e:
            self.log(f"  [Warning: Failed to save metadata for {image_path.name}: {e}]")

    def download_image(self, image_info, download_path, album_name="Unknown Album"):
        """Download a single image and save its metadata."""
        filename = download_path.name
        original_download_path = download_path

        # Check if file already exists
        if download_path.exists():
            # This should ONLY happen on resume, not on fresh downloads
            # Instead of skipping, save to Skipped_Images directory to prevent data loss
            image_key = image_info.get('ImageKey', 'no-key')

            # Create path in Skipped_Images directory, preserving album structure
            skipped_dir = self.base_path / 'Skipped_Images'
            album_subfolder = download_path.parent.relative_to(self.base_path)
            skipped_album_dir = skipped_dir / album_subfolder
            skipped_album_dir.mkdir(parents=True, exist_ok=True)

            # New download path in Skipped_Images
            download_path = skipped_album_dir / filename

            # If it exists in Skipped_Images too, add counter
            if download_path.exists():
                base_name = Path(filename).stem
                extension = Path(filename).suffix
                counter = 2
                while (skipped_album_dir / f"{base_name}_{counter}{extension}").exists():
                    counter += 1
                download_path = skipped_album_dir / f"{base_name}_{counter}{extension}"

            self.total_skipped += 1
            self.skipped_log.append((filename, album_name, image_key, str(original_download_path), str(download_path)))
            self.log(f"    [File exists, saving to Skipped_Images: {filename} → {download_path.name}]")

        # Get the best download URL
        image_url = self.get_image_download_url(image_info)

        if not image_url:
            reason = "No download URL found (no ImageSizeOriginal, ArchivedUri, LargestImage, or ImageDownload)"
            self.log(f"  [Warning: {reason} for {filename}]")
            self.failed_downloads.append((filename, album_name, reason))
            return False

        try:
            # Download the image (ArchivedUri or OriginalUrl gives original quality)
            with requests.get(image_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(download_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            # Save metadata alongside the image
            self.save_image_metadata(image_info, download_path)

            self.total_downloaded += 1
            return True
        except requests.exceptions.HTTPError as e:
            reason = f"HTTP {e.response.status_code} error"
            self.log(f"  [Error downloading {filename}: {reason}]")
            self.failed_downloads.append((filename, album_name, reason))
            # Remove partial file if exists
            if download_path.exists():
                download_path.unlink()
            return False
        except requests.exceptions.Timeout:
            reason = "Download timeout (>30s)"
            self.log(f"  [Error downloading {filename}: {reason}]")
            self.failed_downloads.append((filename, album_name, reason))
            # Remove partial file if exists
            if download_path.exists():
                download_path.unlink()
            return False
        except Exception as e:
            reason = f"{type(e).__name__}: {str(e)}"
            self.log(f"  [Error downloading {filename}: {reason}]")
            self.failed_downloads.append((filename, album_name, reason))
            # Remove partial file if exists
            if download_path.exists():
                download_path.unlink()
            return False

    def process_album(self, album, folder_path):
        """Process a single album - create folder and download images."""
        album_name = album.get('Name', 'Unnamed Album')
        album_uri = album.get('Uri', '')

        if not album_uri:
            self.log(f"  [Warning: No URI for album '{album_name}']")
            return

        # Create album folder
        album_path = folder_path / self.sanitize_filename(album_name)
        album_path.mkdir(parents=True, exist_ok=True)

        self.log(f"\n  Processing album: {album_name}")

        # Save album metadata
        self.save_album_metadata(album, album_path)

        # Fetch images
        images = self.fetch_images(album_uri)
        self.total_images += len(images)
        self.total_albums += 1

        if not images:
            self.log("    No images found")
            return

        self.log(f"    Found {len(images)} images, downloading...")

        # Track ImageKeys and filenames in this album to detect duplicates
        seen_image_keys = {}  # {ImageKey: original_filename}
        used_filenames = {}  # {filename: ImageKey}

        # Pre-process images to detect duplicates and rename collisions
        processed_images = []
        for idx, image in enumerate(images):
            image_key = image.get('ImageKey', '')
            original_filename = image.get('FileName', f"image_{image_key if image_key else idx}")

            # For images without ImageKey, use URI or index as unique identifier
            if not image_key:
                image_uri = image.get('Uri', '')
                unique_id = f"uri_{image_uri}" if image_uri else f"idx_{idx}"
            else:
                unique_id = image_key

            # Check for true duplicate (same ImageKey or URI)
            if unique_id in seen_image_keys:
                self.total_duplicates += 1
                original_file = seen_image_keys[unique_id]
                reason = f"True duplicate (ID={unique_id}, already seen as {original_file})"
                self.duplicate_log.append((unique_id, original_filename, album_name, reason))
                self.log(f"    [Duplicate detected: {original_filename} - same as {original_file}]")
                continue  # Skip this duplicate

            # Check for filename collision (different ImageKey, same filename)
            final_filename = original_filename
            if original_filename in used_filenames:
                other_id = used_filenames[original_filename]
                # Same filename but different unique ID - this is a collision!
                # Rename the second file
                base_name = Path(original_filename).stem
                extension = Path(original_filename).suffix
                counter = 2
                while f"{base_name}_{counter}{extension}" in used_filenames:
                    counter += 1
                final_filename = f"{base_name}_{counter}{extension}"

                self.total_renamed += 1
                self.renamed_files.append((original_filename, final_filename, album_name))
                self.log(f"    [Filename collision: {original_filename} → {final_filename}]")

            # Track this image
            seen_image_keys[unique_id] = original_filename
            used_filenames[final_filename] = unique_id

            # Add to processing list with final filename
            processed_images.append((image, final_filename))

        if not processed_images:
            self.log("    All images were duplicates")
            return

        # Download images with threading
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for image, final_filename in processed_images:
                download_path = album_path / final_filename
                futures.append(executor.submit(self.download_image, image, download_path, album_name))

            # Wait for all downloads to complete
            completed = 0
            for future in as_completed(futures):
                completed += 1
                if completed % 10 == 0 or completed == len(processed_images):
                    self.log(f"    Progress: {completed}/{len(processed_images)} images")
                try:
                    future.result()
                except Exception as e:
                    self.log(f"    [Error: {e}]")

    def sanitize_filename(self, name):
        """Remove or replace characters that are invalid in filenames."""
        # Replace invalid characters with underscores
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        # Remove leading/trailing spaces and dots
        name = name.strip('. ')
        # Limit length
        if len(name) > 200:
            name = name[:200]
        return name if name else 'unnamed'

    def process_folder(self, folder, parent_path, indent_level=0):
        """Recursively process a folder and its subfolders."""
        folder_name = folder.get('Name', 'Unnamed Folder')
        folder_path = parent_path / self.sanitize_filename(folder_name)
        folder_path.mkdir(parents=True, exist_ok=True)

        self.total_folders += 1
        indent = "  " * indent_level
        self.log(f"\n{indent}{'='*60}")
        self.log(f"{indent}Folder: {folder_name}/")
        self.log(f"{indent}{'='*60}")

        # Process albums in this folder
        albums_data = folder.get('Uris', {}).get('FolderAlbums')
        if albums_data:
            if isinstance(albums_data, str):
                albums_uri = albums_data
            else:
                albums_uri = albums_data.get('Uri', '')

            if albums_uri:
                try:
                    resp = self.oauth.get(
                        f"https://api.smugmug.com{albums_uri}",
                        params={'_expand': 'ImageCount', '_verbosity': 1},
                        headers={'Accept': 'application/json'}
                    )
                    if resp.status_code == 200:
                        albums = resp.json()['Response'].get('Album', [])
                        self.log(f"{indent}Found {len(albums)} album(s) in this folder")

                        for album in albums:
                            self.process_album(album, folder_path)
                    else:
                        self.log(f"{indent}[Warning: HTTP {resp.status_code} fetching albums]")
                except Exception as e:
                    self.log(f"{indent}[Error fetching albums: {e}]")

        # Process subfolders
        subfolders_data = folder.get('Uris', {}).get('Folders')
        if subfolders_data:
            if isinstance(subfolders_data, str):
                subfolders_uri = subfolders_data
            else:
                subfolders_uri = subfolders_data.get('Uri', '')

            if subfolders_uri:
                try:
                    resp = self.oauth.get(
                        f"https://api.smugmug.com{subfolders_uri}",
                        params={'_verbosity': 1},
                        headers={'Accept': 'application/json'}
                    )
                    if resp.status_code == 200:
                        subfolders = resp.json()['Response'].get('Folder', [])
                        if subfolders:
                            self.log(f"{indent}Found {len(subfolders)} subfolder(s)")
                            for subfolder in subfolders:
                                self.process_folder(subfolder, folder_path, indent_level + 1)
                except Exception as e:
                    self.log(f"{indent}[Error fetching subfolders: {e}]")

    def download_all(self, nickname):
        """Main entry point to download all content."""
        self.log("\n" + "="*80)
        self.log(f"SmugMug Downloader for: {nickname}")
        self.log(f"Download location: {self.base_path}")
        self.log("="*80)

        try:
            # Fetch user's folder structure
            self.log("\nFetching folder structure...")
            resp = self.oauth.get(
                f"https://api.smugmug.com/api/v2/folder/user/{nickname}!folders",
                params={'_verbosity': 1},
                headers={'Accept': 'application/json'}
            )

            if resp.status_code != 200:
                self.log(f"Error: Failed to fetch folders (HTTP {resp.status_code})")
                return

            folders_data = resp.json()['Response']
            folders = folders_data.get('Folder', [])

            self.log(f"Found {len(folders)} top-level folder(s)\n")

            # Process each top-level folder
            for folder in folders:
                self.process_folder(folder, self.base_path)

            # Print summary
            self.log("\n" + "="*80)
            self.log("DOWNLOAD COMPLETE")
            self.log("="*80)
            self.log(f"Folders processed: {self.total_folders}")
            self.log(f"Albums processed: {self.total_albums}")
            self.log(f"Total images found: {self.total_images}")
            self.log(f"Images downloaded: {self.total_downloaded}")
            self.log(f"Images skipped (already existed): {self.total_skipped}")
            self.log(f"True duplicates skipped: {self.total_duplicates}")
            self.log(f"Filename collisions renamed: {self.total_renamed}")
            self.log(f"Images failed: {len(self.failed_downloads)}")
            self.log(f"Image metadata files saved: {self.total_metadata_saved}")
            self.log(f"Album metadata files saved: {self.total_album_metadata_saved}")
            self.log(f"Download location: {self.base_path.absolute()}")

            # Write failed downloads log if there were any failures
            if self.failed_downloads:
                failed_log_path = self.base_path / 'failed_downloads.txt'
                try:
                    with open(failed_log_path, 'w', encoding='utf-8') as f:
                        f.write("SmugMug Download Failures\n")
                        f.write("="*80 + "\n")
                        f.write(f"Total failed: {len(self.failed_downloads)}\n")
                        f.write("="*80 + "\n\n")

                        for filename, album, reason in self.failed_downloads:
                            f.write(f"File: {filename}\n")
                            f.write(f"Album: {album}\n")
                            f.write(f"Reason: {reason}\n")
                            f.write("-"*80 + "\n\n")

                    self.log(f"\nFailed downloads logged to: {failed_log_path}")
                except Exception as e:
                    self.log(f"\nWarning: Could not write failed downloads log: {e}")

            # Write duplicates log if there were any
            if self.duplicate_log:
                dup_log_path = self.base_path / 'duplicates.txt'
                try:
                    with open(dup_log_path, 'w', encoding='utf-8') as f:
                        f.write("SmugMug True Duplicates (Same ImageKey)\n")
                        f.write("="*80 + "\n")
                        f.write(f"Total duplicates: {self.total_duplicates}\n")
                        f.write("="*80 + "\n")
                        f.write("These images appeared multiple times in SmugMug API responses\n")
                        f.write("with the same ImageKey. Only one copy was downloaded.\n")
                        f.write("="*80 + "\n\n")

                        for image_key, filename, album, reason in self.duplicate_log:
                            f.write(f"File: {filename}\n")
                            f.write(f"Album: {album}\n")
                            f.write(f"ImageKey: {image_key}\n")
                            f.write(f"Reason: {reason}\n")
                            f.write("-"*80 + "\n\n")

                    self.log(f"Duplicates logged to: {dup_log_path}")
                except Exception as e:
                    self.log(f"\nWarning: Could not write duplicates log: {e}")

            # Write renamed files log if there were any
            if self.renamed_files:
                rename_log_path = self.base_path / 'renamed_files.txt'
                try:
                    with open(rename_log_path, 'w', encoding='utf-8') as f:
                        f.write("SmugMug Filename Collisions (Renamed)\n")
                        f.write("="*80 + "\n")
                        f.write(f"Total renamed: {self.total_renamed}\n")
                        f.write("="*80 + "\n")
                        f.write("These are DIFFERENT images with the same filename.\n")
                        f.write("The second occurrence was renamed to avoid overwriting the first.\n")
                        f.write("="*80 + "\n\n")

                        for original, renamed, album in self.renamed_files:
                            f.write(f"Album: {album}\n")
                            f.write(f"Original: {original}\n")
                            f.write(f"Renamed to: {renamed}\n")
                            f.write("-"*80 + "\n\n")

                    self.log(f"Renamed files logged to: {rename_log_path}")
                except Exception as e:
                    self.log(f"\nWarning: Could not write renamed files log: {e}")

            # Write skipped images log if there were any
            if self.skipped_log:
                skipped_log_path = self.base_path / 'skipped_images.txt'
                try:
                    with open(skipped_log_path, 'w', encoding='utf-8') as f:
                        f.write("SmugMug Skipped Images (Already Existed)\n")
                        f.write("="*80 + "\n")
                        f.write(f"Total skipped: {self.total_skipped}\n")
                        f.write("="*80 + "\n")
                        f.write("These images already existed at their intended location.\n")
                        f.write("They were saved to the Skipped_Images directory instead.\n")
                        f.write("This is expected on resume. On fresh downloads, this may indicate:\n")
                        f.write("- Threading race condition (same image processed twice)\n")
                        f.write("- API returning same image multiple times without same ImageKey\n")
                        f.write("="*80 + "\n\n")

                        for filename, album, image_key, original_path, skipped_path in self.skipped_log:
                            f.write(f"File: {filename}\n")
                            f.write(f"Album: {album}\n")
                            f.write(f"ImageKey: {image_key}\n")
                            f.write(f"Original Path: {original_path}\n")
                            f.write(f"Saved to: {skipped_path}\n")
                            f.write("-"*80 + "\n\n")

                    self.log(f"Skipped images logged to: {skipped_log_path}")
                    self.log(f"Skipped images saved to: {self.base_path / 'Skipped_Images'}")
                except Exception as e:
                    self.log(f"\nWarning: Could not write skipped images log: {e}")

            self.log("="*80 + "\n")

        except Exception as e:
            self.log(f"\nError: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    print("\nSmugMug Complete Downloader")
    print("="*80)
    print("This script will download ALL albums and images from your SmugMug account.")
    print("It will preserve the folder hierarchy and skip files that already exist.")
    print("="*80 + "\n")

    # Prompt for download location
    default_path = os.path.join(os.path.expanduser("~"), "SmugMug-Downloads")
    download_path = input(f"Enter download location [{default_path}]: ").strip()

    if not download_path:
        download_path = default_path

    download_path = os.path.expanduser(download_path)

    # Create base directory if it doesn't exist
    Path(download_path).mkdir(parents=True, exist_ok=True)

    # Confirm before starting
    print(f"\nDownload location: {download_path}")
    confirm = input("Start download? (yes/no): ").strip().lower()

    if confirm not in ['yes', 'y']:
        print("Download cancelled.")
        sys.exit(0)

    # Create logger and start download
    log_file_path = Path(download_path) / 'download_log.txt'
    with Logger(log_file_path, also_print=True) as logger:
        downloader = SmugMugDownloader(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, download_path, logger)
        downloader.download_all(NICKNAME)


if __name__ == "__main__":
    main()
