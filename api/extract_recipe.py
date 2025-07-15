# REMOVED: import requests # <--- This line is correctly removed as per your instruction
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from google import genai
import json
import sys
import os
import logging
from recipe_scrapers import scrape_me

# --- Gemini Integration Imports ---

# ----------------------------------

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Configure Gemini ---
# Ensure your GEMINI_API_KEY environment variable is set in your deployment environment.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

# --- Gemini API Call Function ---
def call_gemini_for_step_ingredients(recipe_data: dict) -> dict:
    """
    Calls Google Gemini API to extract step-specific ingredients.
    
    Args:
        recipe_data (dict): A dictionary containing recipe information,
                            including 'cook' (with 'steps') and 'prep' (with 'ingredients').
    
    Returns:
        dict: A dictionary mapping step indices (as strings) to a list of ingredients for that step.
              Example: {"0": ["ingredient A", "ingredient B"], "1": ["ingredient C"]}
              Returns an empty dictionary if API call fails or response is invalid.
    """
    logger.info("Calling Gemini API for step ingredients...")

    steps = recipe_data.get("cook", {}).get("steps", [])
    # Reconstruct the full ingredient strings for the prompt
    all_ingredients_for_prompt = [
        f"{ing.get('quantity', '') or ''} {ing.get('item', '')}".strip()
        for ing in recipe_data.get("prep", {}).get("ingredients", [])
    ]

    # Construct the prompt for Gemini
    # Ensure this prompt guides Gemini to output valid JSON consistently.
    prompt_parts = [
        "You are an expert recipe assistant. Given the full list of ingredients and cooking steps, "
        "identify and list the specific ingredients (with quantities if available) needed for EACH cooking step.",
        "Provide the output as a JSON object where keys are 0-indexed step numbers (as strings, corresponding to the provided steps list) "
        "and values are arrays of strings, each string being an ingredient specific to that step.",
        "Example output: {'0': ['1 cup flour', '1 tsp salt'], '1': ['2 eggs']}",
        "\n--- Full Ingredients List ---",
        "\n".join(all_ingredients_for_prompt),
        "\n--- Cooking Steps ---",
        "\n".join([f"Step {i+1}: {step}" for i, step in enumerate(steps)]),
        "\n--- JSON Output for step_ingredients ---",
    ]

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_parts
        )
        
        # Log the raw response text for debugging Gemini's output
        logger.debug(f"Raw Gemini response text: {response.text}")

        # Attempt to parse Gemini's response as JSON
        step_ingredients_response = json.loads(response.text)
        
        # Ensure keys are integers if Gemini returns strings for keys, for consistency with TypeScript interface
        final_step_ingredients = {int(k): v for k, v in step_ingredients_response.items()}

        logger.info("Successfully received and parsed response from Gemini.")
        return final_step_ingredients

    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode JSON from Gemini response: {e}. Response text: {response.text}")
        return {}
    except Exception as e:
        logger.error(f"Error during Gemini API call or unexpected response: {e}", exc_info=True)
        return {}
# ----------------------------------

# The user_agent_from_request parameter is kept in the signature for consistency
# with the handler.
def extract_recipe_full(url, user_agent_from_request='default'):
    """
    Extracts recipe data using recipe_scrapers and enriches it with step-specific
    ingredients from Gemini.
    """
    try:
        logger.debug(f"Attempting to scrape recipe from URL: {url}")
        # Log that no custom User-Agent is being passed to the scraper
        logger.debug("Using recipe-scrapers' default internal HTTP client (no custom User-Agent passed).")

        # --- Initial scrape_me call ---
        scraper = scrape_me(url)
        logger.debug("Successfully created scraper instance with default client.")
        
        ingredients_raw = scraper.ingredients()
        logger.debug(f"Scraped raw ingredients: {ingredients_raw}")
        
        instructions = scraper.instructions_list()
        logger.debug(f"Extracted instructions: {instructions}")

        # --- Parse ingredients into item and quantity ---
        # This parsing aims to align with ExtractedRecipe's prep.ingredients structure.
        parsed_ingredients = []
        for ing_str in ingredients_raw:
            parts = ing_str.split(' ', 1)
            if len(parts) > 1:
                parsed_ingredients.append({"quantity": parts[0], "item": parts[1]})
            else:
                parsed_ingredients.append({"quantity": None, "item": ing_str})
        logger.debug(f"Parsed ingredients: {parsed_ingredients}")
        # --- End ingredient parsing ---
        
        # Build initial recipe dictionary based on ExtractedRecipe interface
        initial_recipe_data = {
            "title": scraper.title(),
            "image": scraper.image() if scraper.image() else None,
            "totalTime": scraper.total_time() or 0, # Ensure totalTime is a number
            "yields": scraper.yields(),
            "sourceUrl": url,
            "prep": {
                "ingredients": parsed_ingredients
            },
            "cook": {
                "steps": instructions 
            }
        }
        logger.debug("Successfully extracted initial recipe data.")

        # --- Call Gemini for step_ingredients ---
        step_ingredients = call_gemini_for_step_ingredients(initial_recipe_data)
        initial_recipe_data["step_ingredients"] = step_ingredients
        logger.debug(f"Enriched with step_ingredients from Gemini.")
        # --- End Gemini call ---
        
        return {"success": True, "data": initial_recipe_data}
    except Exception as e:
        logger.error(f"Error extracting or enriching recipe: {str(e)}", exc_info=True)
        return {"success": False, "error": str(e)}

# Handle both serverless function and command line usage
if __name__ == "__main__":
    logger.debug("Running in command line mode")
    if len(sys.argv) > 1:
        url = sys.argv[1]
        logger.debug(f"Received URL argument: {url}")
        result = extract_recipe_full(url) # Call the full extraction function
        print(json.dumps(result))
        sys.exit(0 if result["success"] else 1)
    else:
        logger.error("No URL provided in command line arguments")
        sys.exit(1)
else:
    logger.debug("Running in serverless function mode")
    # This 'handler' class is for deployment environments like Vercel's Python runtime
    class handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # API Key validation for the external service
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

            # Call the full extraction and enrichment function
            result = extract_recipe_full(url, user_agent_from_request_header)
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