# REMOVED: import requests # <--- This line is correctly removed as per your instruction
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import google.generativeai as genai
from google.genai import types
import json
import sys
import os
import logging
from recipe_scrapers import scrape_me, exceptions as recipe_exceptions
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
        "IMPORTANT: Return ONLY the JSON object. Do not include any explanations, Markdown, code blocks (like ```json), or additional text.",
        "\n--- Full Ingredients List ---",
        "\n".join(all_ingredients_for_prompt),
        "\n--- Cooking Steps ---",
        "\n".join([f"Step {i+1}: {step}" for i, step in enumerate(steps)]),
        "\n--- JSON Output for step_ingredients ---",
    ]
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content("".join(prompt_parts))
        
        # Log the raw response text for debugging Gemini's output
        logger.debug(f"Raw Gemini response text: {response.text}")
        
        if response.text is None:
            logger.error("Gemini response text is None")
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
            start_time = time.time()
            logger.info("Stage: Request Received - Start")
            try:
                query = parse_qs(urlparse(self.path).query)
                url = query.get('url', [None])[0]
                if not url:
                    self.send_error(400, "Missing 'url' query parameter")
                    return
                request_input = {'url': url, 'user_agent': self.headers.get('user-agent', 'default')}
                logger.info(f"Stage: Request Received - Input: {request_input}")
                request_success = True
            except Exception as e:
                logger.error(f"Stage: Request Received - Error: {str(e)}")
                request_success = False
            request_duration = time.time() - start_time
            logger.info(f"Stage: Request Received - End - Success: {request_success}, Duration: {request_duration:.2f}s")
            
            # Stage: Recipe Scraping
            scrape_start = time.time()
            logger.info("Stage: Recipe Scraping - Start")
            try:
                if not url:
                    self.send_error(400, "Missing 'url' query parameter")
                    return
                assert url is not None  # Satisfy type checker
                scraper = scrape_me(url, wild_mode=True)
                scraped_data = {
                    'title': scraper.title(),
                    'total_time': scraper.total_time(),
                    'yields': scraper.yields(),
                    'ingredients': scraper.ingredients(),
                    'instructions': scraper.instructions(),
                    'image': scraper.image(),
                    'host': scraper.host(),
                    'canonical_url': scraper.canonical_url(),
                    'nutrients': scraper.nutrients(),
                    'ratings': scraper.ratings(),
                    'reviews': scraper.reviews(),
                    'author': scraper.author(),
                    'cuisine': scraper.cuisine(),
                    'category': scraper.category(),
                    'cook_time': scraper.cook_time(),
                    'prep_time': scraper.prep_time(),
                    'description': scraper.description(),
                    'keywords': scraper.keywords(),  # type: ignore
                    'language': scraper.language(),
                    'equipment': scraper.equipment(),
                    'ingredient_groups': scraper.ingredient_groups(),
                    'instructions_list': scraper.instructions_list(),
                    'suitable_for_diet': scraper.suitable_for_diet(),  # type: ignore
                }
                scrape_output = scraped_data  # Full output for logging
                scrape_success = True
                logger.info(f"Stage: Recipe Scraping - Output: {json.dumps(scrape_output, indent=2)}")  # Log full scraped data
            except Exception as e:
                logger.error(f"Stage: Recipe Scraping - Error: {str(e)}")
                scrape_success = False
                scrape_output = {}
            scrape_duration = time.time() - scrape_start
            logger.info(f"Stage: Recipe Scraping - End - Success: {scrape_success}, Duration: {scrape_duration:.2f}s")
            
            # Stage: Gemini Processing
            gemini_start = time.time()
            logger.info("Stage: Gemini Processing - Start")
            try:
                gemini_input = scraped_data  # Sanitized: full scraped data as input to Gemini
                logger.info(f"Stage: Gemini Processing - Input: {json.dumps(gemini_input, indent=2)}")
                step_ingredients = call_gemini_for_step_ingredients(scraped_data)
                gemini_output = step_ingredients
                gemini_success = True
            except Exception as e:
                logger.error(f"Stage: Gemini Processing - Error: {str(e)}")
                gemini_success = False
                gemini_output = {}
            gemini_duration = time.time() - gemini_start
            logger.info(f"Stage: Gemini Processing - End - Success: {gemini_success}, Duration: {gemini_duration:.2f}s, Output: {json.dumps(gemini_output, indent=2)}")
            
            # Stage: Response Assembly
            assembly_start = time.time()
            logger.info("Stage: Response Assembly - Start")
            try:
                assembly_input = {'scraped_data': scraped_data, 'step_ingredients': step_ingredients}
                result = {'recipe': scraped_data, 'step_ingredients': step_ingredients}
                assembly_output = result
                assembly_success = True
            except Exception as e:
                logger.error(f"Stage: Response Assembly - Error: {str(e)}")
                assembly_success = False
                assembly_output = {}
            assembly_duration = time.time() - assembly_start
            logger.info(f"Stage: Response Assembly - End - Success: {assembly_success}, Duration: {assembly_duration:.2f}s, Output: {json.dumps(assembly_output, indent=2)}")
            
            # Send response
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))

    sys.modules['__main__'].handler = handler # type: ignore