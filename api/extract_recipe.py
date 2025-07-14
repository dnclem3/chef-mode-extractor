import requests # Make sure this import is at the top
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json
import sys
import os
import logging
from recipe_scrapers import scrape_me

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def extract_recipe(url, user_agent_from_request='default'):
    # Define a common browser User-Agent
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    if user_agent_from_request and user_agent_from_request != 'default':
        headers['User-Agent'] = user_agent_from_request

    try:
        logger.debug(f"Attempting to fetch URL: {url}")
        logger.debug(f"Using User-Agent for fetch: {headers['User-Agent']}")
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        html_content = response.text
        
        logger.debug(f"Fetched HTML content (first 500 chars): {html_content[:500]}")
        if 'recipeIngredient' in html_content:
            logger.debug("Found 'recipeIngredient' string in fetched HTML.")
        if "1.5 pounds skinless, boneless chicken breast halves" in html_content:
            logger.debug("Found exact ingredient text in fetched HTML.")
        else:
            logger.warning("Did NOT find exact ingredient text in fetched HTML. Content might differ.")

        # Pass the HTML content to scrape_me (using html= instead of url=)
        # REMOVED: wild_mode=True
        scraper = scrape_me(
            html=html_content,
            org_url=url
        )
        logger.debug("Successfully created scraper instance from HTML content.")
        
        ingredients = scraper.ingredients()
        logger.debug(f"Scraped ingredients: {ingredients}")
        
        instructions = scraper.instructions_list()
        logger.debug(f"Extracted instructions: {instructions}")
        
        recipe = {
            "title": scraper.title(),
            "image": scraper.image() if scraper.image() else None,
            "totalTime": scraper.total_time() or 0,
            "yields": scraper.yields(),
            "sourceUrl": url,
            "prep": {
                "ingredients": [
                    {"item": ingredient}
                    for ingredient in ingredients
                ]
            },
            "cook": {
                "steps": instructions 
            }
        }
        logger.debug("Successfully extracted recipe data.")
        
        return {"success": True, "data": recipe}
    except requests.exceptions.RequestException as e:
        logger.error(f"Network or HTTP error during scraping: {str(e)}", exc_info=True)
        return {"success": False, "error": f"Network or HTTP error during scraping: {str(e)}"}
    except Exception as e:
        logger.error(f"Error extracting recipe: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

# Handle both serverless function and command line usage
if __name__ == "__main__":
    logger.debug("Running in command line mode")
    if len(sys.argv) > 1:
        url = sys.argv[1]
        logger.debug(f"Received URL argument: {url}")
        result = extract_recipe(url)
        print(json.dumps(result))
        sys.exit(0 if result["success"] else 1)
    else:
        logger.error("No URL provided in command line arguments")
        sys.exit(1)
else:
    logger.debug("Running in serverless function mode")
    from http.server import BaseHTTPRequestHandler
    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # API Key validation
            expected_api_key = os.environ.get('EXTRACTOR_API_KEY')
            if not expected_api_key:
                logger.error("EXTRACTOR_API_KEY environment variable not set on server.")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Server configuration error: API Key missing.'}).encode('utf-8'))
                return

            client_api_key = self.headers.get('x-api-key')
            if not client_api_key or client_api_key != expected_api_key:
                logger.warning(f"Unauthorized access attempt. Client API Key: {client_api_key}")
                self.send_response(401)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Unauthorized: Invalid or missing API Key.'}).encode('utf-8'))
                return

            # Proceed with recipe extraction if authenticated
            parsed_url = urlparse(self.path)
            params = parse_qs(parsed_url.query)
            url = params.get('url', [None])[0]
            user_agent_from_request_header = self.headers.get('user-agent', 'default')

            logger.debug(f"Received request for URL: {url}")
            logger.debug(f"Client User-Agent: {user_agent_from_request_header}")

            if not url:
                logger.error("No URL provided in request")
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'URL is required'}).encode('utf-8'))
                return

            result = extract_recipe(url, user_agent_from_request_header)
            logger.debug(f"Extract result: {json.dumps(result)}")
            
            if result["success"]:
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(result["data"]).encode('utf-8'))
            else:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': result["error"]}).encode('utf-8'))

    sys.modules['__main__'].handler = handler # type: ignore