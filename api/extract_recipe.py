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
    """
    if not GEMINI_API_KEY:
        logger.warning("Skipping Gemini call because GEMINI_API_KEY is not set.")
        return {}
        
    logger.info("Calling Gemini API for step ingredients...")

    steps = recipe_data.get("cook", {}).get("steps", [])
    # Simplify ingredient strings to just the essential information
    ingredients = recipe_data.get("prep", {}).get("ingredients", [])

    # Construct a more focused prompt
    system_prompt = """
    You are an expert recipe assistant. Your task is to identify which ingredients are used in each step of a recipe based on a provided list of ingredients and a list of step-by-step cooking instructions.

    Follow these rules exactly:

    1. Match ingredients directly from the provided list. Only include ingredients that are explicitly used in each instruction step.
    2. Match ingredients **by intent**, even if phrasing or formatting differs slightly between the ingredient list and the instructions (e.g., “dice the onion” matches “1 yellow onion (small dice)”).
    3. Normalize each item to a clean version (e.g., “1 yellow onion”, “2 cloves garlic”).
    4. If a step does not use any ingredients, return an empty array for that step.
    5. If a step refers to a group (e.g. “the sauce”), include all ingredients that make up that group if they’ve been introduced earlier in the instructions.
    6. Return the final result as a valid JSON object. Keys must be 0-indexed strings representing the step number. Each value must be an array of ingredients (strings).

    ---

    💡 Example input:

    ```json
    {
    "ingredients": [
        "1 yellow onion (small dice)",
        "2 cloves garlic (minced, 1 Tbsp, $0.12)",
        "1 Tbsp olive oil ($0.18)",
        "14.5 oz. diced tomatoes (1 can, $0.96)",
        "1 tsp dried oregano ($0.12)",
        ".5 tsp dried basil ($0.13)"
    ],
    "instructions": [
        "Gather and prepare all ingredients.",
        "Prepare the creamy tomato sauce. Dice the onion and mince the garlic. Add the onion, garlic, and olive oil to a large skillet and sauté over medium heat until the onions are soft and translucent (3-5 minutes).",
        "Add the diced tomatoes (with juices), oregano, basil.",
        "Turn the heat down to low."
    ]
    }

    Example JSON Output:

    {
    "0": [],
    "1": ["1 yellow onion", "2 cloves garlic", "1 Tbsp olive oil"],
    "2": ["14.5 oz. diced tomatoes", "1 tsp dried oregano", ".5 tsp dried basil"],
    "3": []
    }
    """
    user_prompt = f"""Ingredients:
{json.dumps(ingredients, indent=2)}

Steps:
{json.dumps(steps, indent=2)}"""

    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ])
        
        logger.debug(f"Stage: Gemini Processing - Raw Output: {response.text}")
        
        if response.text is None:
            logger.error("Stage: Gemini Processing - Error: Gemini response text is None")
            return {}
        
        # Clean response: Strip potential Markdown code blocks
        cleaned_text = response.text.strip()
        if cleaned_text.startswith('```json'):
            cleaned_text = cleaned_text[7:]
        if cleaned_text.endswith('```'):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()
        
        step_ingredients_response = json.loads(cleaned_text)
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
            "prep": {"ingredients": initial_recipe_data["ingredients"]},
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