# REMOVED: import requests # <--- This line is correctly removed as per your instruction
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import google.generativeai as genai
import json
import sys
import os
import logging
from recipe_scrapers import scrape_me
import time

# --- Gemini Integration Imports ---
# No additional imports needed here, handled by google.generativeai

# ----------------------------------

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# --- Configure Gemini ---
# Ensure your GEMINI_API_KEY environment variable is set in your deployment environment.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Gemini API configured successfully.")
    except Exception as e:
        logger.critical(f"Failed to configure Gemini API: {e}", exc_info=True)
else:
    logger.critical("GEMINI_API_KEY environment variable not set. Gemini features will be disabled.")

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
    if not GEMINI_API_KEY:
        logger.warning("Skipping Gemini call because GEMINI_API_KEY is not set.")
        return {}
        
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
        "IMPORTANT: Return ONLY the JSON object. Do not include any explanations, Markdown, code blocks (like ```json), or additional text."
    ]
    
    gemini_input_for_log = {
        "ingredients": all_ingredients_for_prompt,
        "steps": steps
    }
    logger.debug(f"Stage: Gemini Processing - Input: {json.dumps(gemini_input_for_log, indent=2)}")

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content("".join(prompt_parts))
        
        # Log the raw response text for debugging Gemini's output
        logger.debug(f"Stage: Gemini Processing - Raw Output: {response.text}")
        
        if response.text is None:
            logger.error("Stage: Gemini Processing - Error: Gemini response text is None")
            return {}
        
        # Clean response: Strip potential Markdown code blocks
        cleaned_text = response.text.strip()
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]  # Remove ```json
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]  # Remove trailing ```
        cleaned_text = cleaned_text.strip()
        
        # Attempt to parse Gemini's response as JSON
        step_ingredients_response = json.loads(cleaned_text)
        
        # Ensure keys are integers if Gemini returns strings for keys, for consistency with TypeScript interface
        final_step_ingredients = {int(k): v for k, v in step_ingredients_response.items()}
        
        logger.info("Stage: Gemini Processing - Success: Successfully received and parsed response from Gemini.")
        return final_step_ingredients
    
    except json.JSONDecodeError as e:
        logger.error(f"Stage: Gemini Processing - Error: Failed to decode JSON from Gemini response: {e}. Response text: {response.text}")
        return {}
    except Exception as e:
        logger.error(f"Stage: Gemini Processing - Error: Unexpected error during API call: {e}", exc_info=True)
        return {}
# ----------------------------------

def extract_recipe_full(url):
    """
    Extracts core recipe data using recipe_scrapers, enriches it with step-specific
    ingredients from Gemini, and handles errors gracefully.
    This is the single source of truth for all recipe processing.
    """
    try:
        logger.debug(f"Attempting to scrape recipe from URL: {url}")
        scraper = scrape_me(url)
        logger.debug("Successfully created scraper instance.")

        # --- Safely extract core recipe data ---
        # Call scraper methods safely, providing default values if an attribute is missing.
        initial_recipe_data = {
            "title": getattr(scraper, 'title', lambda: 'No Title')(),
            "totalTime": getattr(scraper, 'total_time', lambda: 0)(),
            "yields": getattr(scraper, 'yields', lambda: 'N/A')(),
            "ingredients": getattr(scraper, 'ingredients', lambda: [])(),
            "instructions": getattr(scraper, 'instructions_list', lambda: [])(),
            "image": getattr(scraper, 'image', lambda: None)(),
            "sourceUrl": url,
        }

        # Structure data for Gemini call
        recipe_for_gemini = {
            "prep": {"ingredients": [{"item": ing} for ing in initial_recipe_data["ingredients"]]},
            "cook": {"steps": initial_recipe_data["instructions"]}
        }

        logger.debug("Successfully extracted initial recipe data.")

        # --- Call Gemini for step_ingredients ---
        step_ingredients = call_gemini_for_step_ingredients(recipe_for_gemini)
        initial_recipe_data["step_ingredients"] = step_ingredients
        logger.debug(f"Enriched with step_ingredients from Gemini.")
        
        return {"success": True, "data": initial_recipe_data}

    except Exception as e:
        logger.error(f"Error extracting or enriching recipe from {url}: {str(e)}", exc_info=True)
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
            # --- Stage: Request Received ---
            start_time = time.time()
            logger.info("Stage: Request Received - Start")
            query = parse_qs(urlparse(self.path).query)
            url = query.get('url', [None])[0]

            if not url:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "Missing 'url' query parameter"}).encode('utf-8'))
                logger.warning("Stage: Request Received - End: Responded with 400 due to missing URL.")
                return
            
            request_duration = time.time() - start_time
            logger.info(f"Stage: Request Received - End, Duration: {request_duration:.2f}s")

            # --- Call the consolidated extraction function ---
            result = extract_recipe_full(url)

            # --- Stage: Response Assembly ---
            assembly_start_time = time.time()
            logger.info("Stage: Response Assembly - Start")
            if result["success"]:
                response_payload = json.dumps(result["data"], indent=2)
                logger.info(f"Stage: Response Assembly - Final Output (200 OK):\n{response_payload}")
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(response_payload.encode('utf-8'))
            else:
                response_payload = json.dumps(result, indent=2)
                logger.error(f"Stage: Response Assembly - Final Output (500 Error):\n{response_payload}")
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(response_payload.encode('utf-8'))
            
            assembly_duration = time.time() - assembly_start_time
            logger.info(f"Stage: Response Assembly - End - Duration: {assembly_duration:.2f}s")

    sys.modules['__main__'].handler = handler # type: ignore