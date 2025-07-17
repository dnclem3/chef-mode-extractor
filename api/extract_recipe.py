from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import sys
import os
import logging
from recipe_scrapers import scrape_me
import time
import uuid

# Set up logging with more detailed format
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True
)
logger = logging.getLogger(__name__)

# Ensure logs are flushed immediately for Vercel
import sys
sys.stdout.flush()
sys.stderr.flush()

def log_and_print(level, message, exc_info=False):
    """Log message and also print for Vercel visibility"""
    getattr(logger, level)(message, exc_info=exc_info)
    print(f"[{level.upper()}] {message}", flush=True)

def extract_recipe_full(url, request_id=None):
    """
    Extracts core recipe data using recipe_scrapers.
    This is the single source of truth for all recipe processing.
    """
    log_prefix = f"[{request_id}]" if request_id else ""
    
    try:
        log_and_print("info", f"{log_prefix} Starting recipe extraction from URL: {url}")
        extraction_start = time.time()
        
        scraper = scrape_me(url)
        log_and_print("debug", f"{log_prefix} Successfully created scraper instance for {url}")

        # Extract recipe data matching the specified schema
        recipe_data = {
            "title": getattr(scraper, 'title', lambda: 'No Title')(),
            "image": getattr(scraper, 'image', lambda: None)(),
            "totalTime": getattr(scraper, 'total_time', lambda: 0)(),
            "yields": getattr(scraper, 'yields', lambda: 'N/A')(),
            "sourceUrl": url,
            "ingredients": getattr(scraper, 'ingredients', lambda: [])(),
            "instructions": getattr(scraper, 'instructions_list', lambda: [])(),
        }

        extraction_duration = time.time() - extraction_start
        log_and_print("info", f"{log_prefix} Successfully extracted recipe data in {extraction_duration:.2f}s")
        logger.debug(f"{log_prefix} Recipe details - Title: '{recipe_data['title']}', "
                    f"Ingredients: {len(recipe_data['ingredients'])}, "
                    f"Instructions: {len(recipe_data['instructions'])}, "
                    f"Total Time: {recipe_data['totalTime']}")
        
        return {"success": True, "data": recipe_data}

    except Exception as e:
        extraction_duration = time.time() - extraction_start if 'extraction_start' in locals() else 0
        log_and_print("error", f"{log_prefix} Failed to extract recipe from {url} after {extraction_duration:.2f}s: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

# Handle both serverless function and command line usage
if __name__ == "__main__":
    log_and_print("info", "Application started in command line mode")
    if len(sys.argv) > 1:
        url = sys.argv[1]
        log_and_print("info", f"Processing URL from command line: {url}")
        result = extract_recipe_full(url)
        
        if result["success"]:
            log_and_print("info", "Command line extraction successful")
            print(json.dumps(result))
            sys.exit(0)
        else:
            log_and_print("error", f"Command line extraction failed: {result.get('error', 'Unknown error')}")
            print(json.dumps(result))
            sys.exit(1)
    else:
        log_and_print("error", "No URL provided in command line arguments")
        sys.exit(1)
else:
    log_and_print("info", "Application started in serverless function mode")
    # This 'handler' class is for deployment environments like Vercel's Python runtime
    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Generate unique request ID for tracking
            request_id = str(uuid.uuid4())[:8]
            request_start = time.time()
            
            log_and_print("info", f"[{request_id}] Incoming GET request from {self.client_address[0]}")
            
            try:
                # Parse request
                parsed_url = urlparse(self.path)
                query = parse_qs(parsed_url.query)
                url = query.get('url', [None])[0]
                
                logger.debug(f"[{request_id}] Request path: {self.path}")
                logger.debug(f"[{request_id}] Parsed URL parameter: {url}")

                if not url:
                    log_and_print("warning", f"[{request_id}] Request missing required 'url' parameter")
                    self._send_error_response(400, {"success": False, "error": "Missing 'url' query parameter"}, request_id)
                    return

                log_and_print("info", f"[{request_id}] Processing recipe extraction for URL: {url}")
                
                # Call the extraction function
                result = extract_recipe_full(url, request_id)

                # Send response
                if result["success"]:
                    self._send_success_response(result["data"], request_id, request_start)
                else:
                    self._send_error_response(500, result, request_id)
                    
            except Exception as e:
                log_and_print("error", f"[{request_id}] Unexpected error processing request: {str(e)}", exc_info=True)
                self._send_error_response(500, {"success": False, "error": "Internal server error"}, request_id)
        
        def _send_success_response(self, data, request_id, request_start):
            """Send a successful response with logging"""
            total_duration = time.time() - request_start
            response_payload = json.dumps(data, indent=2)
            
            log_and_print("info", f"[{request_id}] Sending successful response (200 OK) after {total_duration:.2f}s")
            logger.debug(f"[{request_id}] Response size: {len(response_payload)} bytes")
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response_payload.encode('utf-8'))
            
            log_and_print("info", f"[{request_id}] Request completed successfully in {total_duration:.2f}s")
        
        def _send_error_response(self, status_code, error_data, request_id):
            """Send an error response with logging"""
            response_payload = json.dumps(error_data, indent=2)
            
            log_and_print("error", f"[{request_id}] Sending error response ({status_code}) - {error_data.get('error', 'Unknown error')}")
            
            self.send_response(status_code)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response_payload.encode('utf-8'))
        
        def log_message(self, format, *args):
            """Override default HTTP server logging to use our logger"""
            logger.debug(f"HTTP Server: {format % args}")

    sys.modules['__main__'].handler = handler # type: ignore