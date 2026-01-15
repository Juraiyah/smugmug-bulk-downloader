#!/usr/bin/env python3
"""
SmugMug OAuth Authentication Script
Run this once to obtain your access tokens.
"""

from requests_oauthlib import OAuth1Session
from urllib.parse import parse_qs
import webbrowser
import http.server
import socketserver
import sys

def authenticate(api_key, api_secret):
    """
    Perform OAuth 1.0a authentication flow with SmugMug.
    Returns access token and access secret.
    """
    CALLBACK_URI = 'http://localhost:8080/'
    REQUEST_TOKEN_URL = 'https://api.smugmug.com/services/oauth/1.0a/getRequestToken'
    AUTHORIZE_URL = 'https://api.smugmug.com/services/oauth/1.0a/authorize'
    ACCESS_TOKEN_URL = 'https://api.smugmug.com/services/oauth/1.0a/getAccessToken'

    print("Starting SmugMug OAuth authentication...\n")

    smug = OAuth1Session(api_key, client_secret=api_secret, callback_uri=CALLBACK_URI)

    try:
        # Step 1: Get request token
        print("Fetching request token...")
        try:
            req_token = smug.fetch_request_token(REQUEST_TOKEN_URL)
            print(f"Got request token: {req_token.get('oauth_token', 'N/A')[:20]}...")
        except Exception as e:
            print(f"\n[ERROR] Failed to fetch request token")
            print(f"Error: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Status Code: {e.response.status_code}")
                print(f"Response: {e.response.text[:500]}")
            print("\nPossible issues:")
            print("  1. Check your API Key and Secret are correct")
            print("  2. Ensure callback URL is set to: http://localhost:8080/")
            print("  3. Verify your SmugMug app is approved and active")
            raise

        auth_url = smug.authorization_url(AUTHORIZE_URL, Access='Full', Permissions='Modify')

        print(f"\nOpening browser for authorization...")
        print(f"If browser doesn't open, go to: {auth_url}\n")

        # Step 2: Local server to catch callback
        class CallbackHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Suppress server logs

            def do_GET(self):
                query = parse_qs(self.path.split('?')[1] if '?' in self.path else '')
                verifier = query.get('oauth_verifier', [None])[0]
                if verifier:
                    self.server.verifier = verifier
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'<html><body><h1>Authorization Successful!</h1><p>You can close this tab and return to the terminal.</p></body></html>')
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'<html><body><h1>Authorization Failed</h1></body></html>')

        with socketserver.TCPServer(('', 8080), CallbackHandler) as httpd:
            httpd.verifier = None
            webbrowser.open(auth_url)

            print("Waiting for authorization...")
            # Wait for callback
            while not hasattr(httpd, 'verifier') or httpd.verifier is None:
                httpd.handle_request()

            # Step 3: Exchange for access token
            print("\nExchanging verifier for access token...")
            try:
                access_token = smug.fetch_access_token(
                    ACCESS_TOKEN_URL,
                    verifier=httpd.verifier
                )
            except Exception as e:
                print(f"\n[ERROR] Failed to exchange verifier for access token")
                print(f"Error: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"Status Code: {e.response.status_code}")
                    print(f"Response: {e.response.text[:500]}")
                raise

            print("\n" + "="*60)
            print("SUCCESS! Save these credentials to config.py:")
            print("="*60)
            print(f"\nAPI_KEY = '{api_key}'")
            print(f"API_SECRET = '{api_secret}'")
            print(f"ACCESS_TOKEN = '{access_token['oauth_token']}'")
            print(f"ACCESS_SECRET = '{access_token['oauth_token_secret']}'")
            print("\n" + "="*60)

            return access_token['oauth_token'], access_token['oauth_token_secret']

    except Exception as e:
        print(f"\nError during authentication: {e}")
        sys.exit(1)


if __name__ == '__main__':
    print("\nSmugMug OAuth Authentication")
    print("="*60)
    print("\nYou need to register an application at:")
    print("https://api.smugmug.com/api/developer/apply")
    print("\nSet the callback URL to: http://localhost:8080/")
    print("="*60 + "\n")

    api_key = input("Enter your API Key: ").strip()
    api_secret = input("Enter your API Secret: ").strip()

    if not api_key or not api_secret:
        print("Error: API Key and Secret are required")
        sys.exit(1)

    authenticate(api_key, api_secret)
