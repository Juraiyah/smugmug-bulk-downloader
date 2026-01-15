#!/usr/bin/env python3
"""
SmugMug Album Counter
Lists all albums and sub-albums with image counts in a tree structure.
"""

from requests_oauthlib import OAuth1Session
import sys

try:
    from config import API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, NICKNAME
except ImportError:
    print("Error: config.py not found!")
    print("\nPlease create config.py with your credentials:")
    print("  1. Run: python auth.py")
    print("  2. Copy the output to create config.py")
    print("  3. Add your NICKNAME (SmugMug username)")
    sys.exit(1)


class SmugMugCounter:
    def __init__(self, api_key, api_secret, access_token, access_secret, debug=False):
        self.oauth = OAuth1Session(
            api_key,
            client_secret=api_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_secret
        )
        self.total_images = 0
        self.total_albums = 0
        self.debug = debug

    def get_image_count(self, album_uri):
        """Get the number of images for an album."""
        try:
            # Use the album URI directly and request image count
            resp = self.oauth.get(
                f"https://api.smugmug.com{album_uri}",
                params={'_verbosity': 1},
                headers={'Accept': 'application/json'}
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()['Response']
                    album_data = data.get('Album', {})
                    # Try to get image count from album metadata
                    image_count = album_data.get('ImageCount', 0)
                    return image_count
                except Exception as e:
                    print(f"    [Error parsing JSON for image count: {e}]")
                    print(f"    [Response keys: {list(resp.json().get('Response', {}).keys())}]")
            else:
                print(f"    [HTTP {resp.status_code} fetching image count from {album_uri}]")
        except Exception as e:
            print(f"    [Error fetching image count: {e}]")
        return 0

    def print_album(self, album, indent_level, prefix=""):
        """Print a single album with its image count."""
        name = album.get('Name', 'Unnamed Album')

        # Get image count directly from album data if available
        count = album.get('ImageCount', None)

        # If not in the data, try to fetch it from the album URI
        if count is None:
            if self.debug:
                print(f"  [DEBUG: ImageCount not found for '{name}', fetching...]")
            album_uri = album.get('Uri', '')
            if album_uri:
                count = self.get_image_count(album_uri)
            else:
                count = 0
                if self.debug:
                    print(f"  [DEBUG: No Uri found for album '{name}']")

        self.total_images += count
        self.total_albums += 1

        indent = "  " * indent_level
        print(f"{indent}{prefix}{name}: {count} images")
        return count

    def process_node(self, node, indent_level=0, is_root=False):
        """Recursively process folders and albums."""
        node_total = 0
        node_name = node.get('Name', 'Root')

        # Print folder header (except for root)
        if not is_root and node_name:
            indent = "  " * indent_level
            print(f"\n{indent}{'='*60}")
            print(f"{indent}{node_name}/")
            print(f"{indent}{'='*60}")

            if self.debug:
                uris = node.get('Uris', {})
                print(f"  [DEBUG: Available URIs: {list(uris.keys())}]")

        # Process albums in this folder
        albums_data = node.get('Uris', {}).get('FolderAlbums')
        if albums_data:
            # Handle both string URI and dict with Uri key
            if isinstance(albums_data, str):
                albums_uri = albums_data
            else:
                albums_uri = albums_data.get('Uri', '')
            if albums_uri:
                try:
                    resp = self.oauth.get(
                        f"https://api.smugmug.com{albums_uri}",
                        params={'_expand': 'ImageCount'},
                        headers={'Accept': 'application/json'}
                    )
                    if resp.status_code == 200:
                        response_data = resp.json()['Response']
                        albums = response_data.get('Album', [])

                        # Debug: check if we got any albums
                        if self.debug:
                            print(f"  [DEBUG: Found {len(albums)} albums]")

                        if not albums:
                            indent = "  " * (indent_level + 1)
                            print(f"{indent}(No albums in this folder)")
                        else:
                            for album in albums:
                                count = self.print_album(album, indent_level + 1, "├─ ")
                                node_total += count
                    else:
                        print(f"  Error: HTTP {resp.status_code} fetching albums from {albums_uri}")
                except Exception as e:
                    print(f"  Error fetching albums: {e}")
                    import traceback
                    traceback.print_exc()
        elif self.debug:
            print("  [DEBUG: No FolderAlbums URI found]")

        # Process subfolders
        # SmugMug uses 'Folders' not 'ChildFolders'
        subfolders_data = node.get('Uris', {}).get('Folders')
        if subfolders_data:
            # Handle both string URI and dict with Uri key
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
                        folders = resp.json()['Response'].get('Folder', [])
                        if self.debug:
                            print(f"  [DEBUG: Found {len(folders)} subfolders]")
                        for folder in folders:
                            folder_count = self.process_node(folder, indent_level + 1)
                            node_total += folder_count
                    else:
                        print(f"  Error: HTTP {resp.status_code} fetching subfolders")
                except Exception as e:
                    print(f"  Error fetching subfolders: {e}")
                    import traceback
                    traceback.print_exc()
        elif self.debug:
            print("  [DEBUG: No Folders URI found]")

        # Print folder subtotal (except for root)
        if not is_root:
            indent = "  " * indent_level
            print(f"{indent}{'─'*60}")
            if node_total > 0:
                print(f"{indent}Subtotal for {node_name}: {node_total} images")
            else:
                print(f"{indent}Subtotal for {node_name}: 0 images (empty folder)")

        return node_total

    def count_all(self, nickname):
        """Main entry point to count all photos."""
        print("\n" + "="*80)
        print(f"SmugMug Album Counter for: {nickname}")
        print("="*80)

        try:
            # Fetch user's folder structure
            print("\nFetching folder structure...")
            resp = self.oauth.get(
                f"https://api.smugmug.com/api/v2/folder/user/{nickname}!folders",
                params={'_verbosity': 1},
                headers={'Accept': 'application/json'}
            )

            if resp.status_code != 200:
                print(f"\nError: Failed to fetch folders (HTTP {resp.status_code})")
                print(f"Response: {resp.text[:500]}")
                return

            try:
                folders_data = resp.json()['Response']
            except Exception as e:
                print(f"\nError parsing JSON response: {e}")
                print(f"Response status: {resp.status_code}")
                print(f"Response headers: {resp.headers}")
                print(f"Response text (first 500 chars): {resp.text[:500]}")
                return
            folders = folders_data.get('Folder', [])

            print(f"Found {len(folders)} top-level folders\n")

            # Process each top-level folder
            for folder in folders:
                self.process_node(folder, indent_level=0)

            # Print grand total
            print("\n" + "="*80)
            print("GRAND TOTAL")
            print("="*80)
            print(f"Total Albums: {self.total_albums}")
            print(f"Total Images: {self.total_images}")
            print("="*80 + "\n")

        except Exception as e:
            print(f"\nError: {e}")
            sys.exit(1)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Count SmugMug albums and images')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()

    counter = SmugMugCounter(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET, debug=args.debug)
    counter.count_all(NICKNAME)


if __name__ == "__main__":
    main()
