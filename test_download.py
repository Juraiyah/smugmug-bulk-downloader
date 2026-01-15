#!/usr/bin/env python3
"""
Test script to download a single album/gallery with metadata
"""

import sys
from pathlib import Path
from download import SmugMugDownloader
from config import API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, NICKNAME

def main():
    print("\nSmugMug Single Album Test Downloader")
    print("="*80)
    print("This will download just the FIRST album found for testing purposes.\n")

    # Prompt for download location
    default_path = "./test-download"
    download_path = input(f"Enter download location [{default_path}]: ").strip()
    if not download_path:
        download_path = default_path

    download_path = Path(download_path)
    download_path.mkdir(parents=True, exist_ok=True)

    # Create downloader
    downloader = SmugMugDownloader(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, download_path)

    print(f"\nFetching folder structure for: {NICKNAME}")
    print("Looking for first album...\n")

    try:
        # Fetch folders
        resp = downloader.oauth.get(
            f"https://api.smugmug.com/api/v2/folder/user/{NICKNAME}!folders",
            params={'_verbosity': 1},
            headers={'Accept': 'application/json'}
        )

        if resp.status_code != 200:
            print(f"Error: Failed to fetch folders (HTTP {resp.status_code})")
            sys.exit(1)

        folders = resp.json()['Response'].get('Folder', [])

        # Find first album in any folder
        album_found = False
        for folder in folders:
            if album_found:
                break

            folder_name = folder.get('Name', 'Unnamed')
            albums_data = folder.get('Uris', {}).get('FolderAlbums')

            if not albums_data:
                continue

            if isinstance(albums_data, str):
                albums_uri = albums_data
            else:
                albums_uri = albums_data.get('Uri', '')

            if albums_uri:
                resp = downloader.oauth.get(
                    f"https://api.smugmug.com{albums_uri}",
                    params={'_expand': 'ImageCount', '_verbosity': 1},
                    headers={'Accept': 'application/json'}
                )

                if resp.status_code == 200:
                    albums = resp.json()['Response'].get('Album', [])
                    if albums:
                        album = albums[0]  # Get first album
                        album_name = album.get('Name', 'Unnamed')
                        image_count = album.get('ImageCount', 0)

                        print(f"Found album: '{album_name}' in folder '{folder_name}'")
                        print(f"Image count: {image_count}")
                        print(f"\nDownloading to: {download_path}\n")

                        confirm = input("Proceed with test download? (yes/no): ").strip().lower()
                        if confirm not in ['yes', 'y']:
                            print("Test cancelled.")
                            sys.exit(0)

                        # Download this one album
                        folder_path = download_path / folder_name
                        downloader.process_album(album, folder_path)

                        print("\n" + "="*80)
                        print("TEST DOWNLOAD COMPLETE")
                        print("="*80)
                        print(f"Album downloaded: {album_name}")
                        print(f"Images downloaded: {downloader.total_downloaded}")
                        print(f"Image metadata files: {downloader.total_metadata_saved}")
                        print(f"Album metadata files: {downloader.total_album_metadata_saved}")
                        print(f"Location: {folder_path.absolute()}")
                        print("="*80)

                        # Show what was created
                        print("\nFiles created:")
                        for item in sorted(folder_path.rglob('*')):
                            if item.is_file():
                                rel_path = item.relative_to(folder_path)
                                print(f"  {rel_path}")

                        album_found = True
                        break

        if not album_found:
            print("No albums found in account!")
            sys.exit(1)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

