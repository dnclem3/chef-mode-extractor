from dotenv import load_dotenv
import os

# Load environment variables from your .env.local file BEFORE other imports
load_dotenv(dotenv_path=".env.local")

from http.server import HTTPServer
from api.extract_recipe import handler

PORT = 8000

def run(server_class=HTTPServer, handler_class=handler, port=PORT):
    """Starts a local HTTP server to run the API."""
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    
    print("--- Local API Server ---")
    print(f"Server starting on http://localhost:{port}")
    print("Press Ctrl+C to stop the server.")
    print("-" * 24)
    print("\nTo test, open a new terminal and use a command like this:")
    print(f'curl "http://localhost:{PORT}/extract?url=<RECIPE_URL>" -H "x-api-key: <YOUR_API_KEY>"')
    print("\nRemember to:")
    print("1. Replace <RECIPE_URL> with an actual recipe URL.")
    print("2. Replace <YOUR_API_KEY> with the EXTRACTOR_API_KEY from your .env file.")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n--- Server stopping ---")
        httpd.server_close()

if __name__ == '__main__':
    # Ensure you have created a .env file with your API keys
    if not os.getenv("GEMINI_API_KEY") or not os.getenv("EXTRACTOR_API_KEY"):
        print("\n[WARNING] GEMINI_API_KEY or EXTRACTOR_API_KEY not found.")
        print("Please ensure you have a .env file in the project root with both keys defined.")
    else:
        print("\n.env file loaded successfully.")
    
    run() 