#!/usr/bin/env python3
import sys
import json
import traceback
import urllib.request
import urllib.error
import urllib.parse
import mcp.types as types
from src.core.api_helpers import API_BASE_URL
from src.core.formatters import format_monster_data, format_spell_data, format_class_data
import requests
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from src.core.cache import APICache
import src.core.formatters as formatters
import src.core.resources as resources
import time
# Import our new source attribution system
from src.attribution import (
    SourceAttribution,
    ConfidenceLevel,
    ConfidenceFactors,
    ConfidenceScorer,
    ToolCategory,
    track_tool_usage,
    source_tracker,
    attribution_manager
)
# Import our new template system
from src.templates import (
    format_dnd_data,
    format_search_results,
    TEMPLATES_ENABLED
)
# Import campaign templates
from src.templates.campaign import (
    format_character_card,
    format_character_list,
    format_character_spells,
    format_character_feats,
    format_character_forms,
    format_character_companions,
    format_inventory_list,
    format_inventory_search_results,
    format_currency_by_location,
    format_wealth_summary,
    format_storage_locations,
    format_diary_entry,
    format_diary_list,
    format_currency_transaction,
    format_inventory_transaction
)
# Import our query enhancement module
from src.query_enhancement import (
    enhance_query,
    expand_query_with_synonyms,
    tokenize_dnd_query,
    fuzzy_match,
    prioritize_categories,
    get_top_categories
)

logger = logging.getLogger(__name__)

# Base URL for the D&D 5e API
BASE_URL = "https://www.dnd5eapi.co/api"
# Request timeout in seconds
REQUEST_TIMEOUT = 10


def register_tools(app, cache: APICache):
    """Register D&D API tools with the FastMCP app.

    Args:
        app: The FastMCP app instance
        cache: The shared API cache
    """
    print("Registering D&D API tools...", file=sys.stderr)

    @app.tool()
    def search_equipment_by_cost(max_cost: float, cost_unit: str = "gp") -> Dict[str, Any]:
        """Search for D&D equipment items that cost less than or equal to a specified maximum price.

        This tool helps find affordable equipment options for character creation or in-game purchases.
        Results include item details such as name, cost, weight, and category.

        Args:
            max_cost: Maximum cost value (e.g., 10 for items costing 10 or less of the specified currency)
            cost_unit: Currency unit (gp=gold pieces, sp=silver pieces, cp=copper pieces)

        Returns:
            A dictionary containing equipment items within the specified cost range, with source attribution
            to the D&D 5e API.
        """
        logger.debug(f"Searching equipment by cost: {max_cost} {cost_unit}")

        # Get equipment list (from cache if available)
        equipment_list = _get_category_items("equipment", cache)
        if "error" in equipment_list:
            return equipment_list

        # Filter equipment by cost
        results = []
        for item in equipment_list.get("items", []):
            # Get detailed item info (from cache if available)
            item_index = item["index"]
            item_details = _get_item_details("equipment", item_index, cache)
            if "error" in item_details:
                continue

            # Check if item has cost and is within budget
            if "cost" in item_details:
                cost = item_details["cost"]
                # Convert cost to requested unit for comparison
                converted_cost = _convert_currency(
                    cost["quantity"], cost["unit"], cost_unit)
                if converted_cost <= max_cost:
                    results.append({
                        "name": item_details["name"],
                        "cost": f"{cost['quantity']} {cost['unit']}",
                        "description": _get_description(item_details),
                        "category": item_details.get("equipment_category", {}).get("name", "Unknown"),
                        "uri": f"resource://dnd/item/equipment/{item_index}"
                    })

        return {
            "query": f"Equipment costing {max_cost} {cost_unit} or less",
            "items": results,
            "count": len(results)
        }

    @app.tool()
    def filter_spells_by_level(min_level: int = 0, max_level: int = 9, school: str = None) -> Dict[str, Any]:
        """Find D&D spells within a specific level range and optionally from a particular magic school.

        This tool is useful for spellcasters looking for spells they can cast at their current level,
        or for finding appropriate spells for NPCs, scrolls, or other magical items. Results include
        spell names, levels, schools, and basic casting information.

        Args:
            min_level: Minimum spell level (0-9, where 0 represents cantrips)
            max_level: Maximum spell level (0-9, where 9 represents 9th-level spells)
            school: Magic school filter (abjuration, conjuration, divination, enchantment, 
                   evocation, illusion, necromancy, transmutation)

        Returns:
            A dictionary containing spells that match the specified criteria, with source attribution
            to the D&D 5e API.
        """
        logger.debug(
            f"Filtering spells by level: {min_level}-{max_level}, school: {school}")

        # Validate input
        if min_level < 0 or max_level > 9 or min_level > max_level:
            return {"error": "Invalid level range. Must be between 0 and 9."}

        # Get spells list (from cache if available)
        spells_list = _get_category_items("spells", cache)
        if "error" in spells_list:
            return spells_list

        # Filter spells by level and school
        results = []
        for item in spells_list.get("items", []):
            # Get detailed spell info (from cache if available)
            item_index = item["index"]
            spell_details = _get_item_details("spells", item_index, cache)
            if "error" in spell_details:
                continue

            # Check if spell level is within range
            spell_level = spell_details.get("level", 0)
            if min_level <= spell_level <= max_level:
                # Check school if specified
                if school:
                    spell_school = spell_details.get(
                        "school", {}).get("name", "").lower()
                    if school.lower() not in spell_school:
                        continue

                results.append({
                    "name": spell_details["name"],
                    "level": spell_level,
                    "school": spell_details.get("school", {}).get("name", "Unknown"),
                    "casting_time": spell_details.get("casting_time", "Unknown"),
                    "description": _get_description(spell_details),
                    "uri": f"resource://dnd/item/spells/{item_index}"
                })

        # Sort results by level and name
        results.sort(key=lambda x: (x["level"], x["name"]))

        return {
            "query": f"Spells of level {min_level}-{max_level}" + (f" in school {school}" if school else ""),
            "items": results,
            "count": len(results)
        }

    @app.tool()
    def find_monsters_by_challenge_rating(min_cr: float = 0, max_cr: float = 30) -> Dict[str, Any]:
        """Find D&D monsters within a specific challenge rating (CR) range for encounter building.

        This tool helps Dungeon Masters find appropriate monsters for encounters based on party level
        and desired difficulty. Results include monster names, challenge ratings, types, and basic stats.

        Challenge ratings indicate a monster's relative threat level:
        - CR 0-4: Low-level threats suitable for parties of levels 1-4
        - CR 5-10: Mid-level threats suitable for parties of levels 5-10
        - CR 11-16: High-level threats suitable for parties of levels 11-16
        - CR 17+: Epic threats suitable for parties of levels 17+

        Args:
            min_cr: Minimum challenge rating (0 to 30, can use fractions like 0.25, 0.5)
            max_cr: Maximum challenge rating (0 to 30)

        Returns:
            A dictionary containing monsters within the specified CR range, with source attribution
            to the D&D 5e API.
        """
        logger.debug(f"Finding monsters by CR: {min_cr}-{max_cr}")

        # Get monsters list (from cache if available)
        monsters_list = _get_category_items("monsters", cache)
        if "error" in monsters_list:
            return monsters_list

        # Filter monsters by CR
        results = []
        for item in monsters_list.get("items", []):
            # Get detailed monster info (from cache if available)
            item_index = item["index"]
            monster_details = _get_item_details("monsters", item_index, cache)
            if "error" in monster_details:
                continue

            # Check if monster CR is within range
            monster_cr = float(monster_details.get("challenge_rating", 0))
            if min_cr <= monster_cr <= max_cr:
                results.append({
                    "name": monster_details["name"],
                    "challenge_rating": monster_cr,
                    "type": monster_details.get("type", "Unknown"),
                    "size": monster_details.get("size", "Unknown"),
                    "alignment": monster_details.get("alignment", "Unknown"),
                    "hit_points": monster_details.get("hit_points", 0),
                    "armor_class": monster_details.get("armor_class", [{"value": 0}])[0].get("value", 0),
                    "uri": f"resource://dnd/item/monsters/{item_index}"
                })

        # Sort results by CR and name
        results.sort(key=lambda x: (x["challenge_rating"], x["name"]))

        return {
            "query": f"Monsters with CR {min_cr}-{max_cr}",
            "items": results,
            "count": len(results)
        }

    @app.tool()
    def get_class_starting_equipment(class_name: str) -> Dict[str, Any]:
        """Get starting equipment for a character class.

        Args:
            class_name: Name of the character class

        Returns:
            Starting equipment for the class
        """
        logger.debug(f"Getting starting equipment for class: {class_name}")

        # Normalize class name
        class_name = class_name.lower()

        # Get class details (from cache if available)
        class_details = _get_item_details("classes", class_name, cache)
        if "error" in class_details:
            return {"error": f"Class '{class_name}' not found"}

        # Extract starting equipment
        starting_equipment = []
        for item in class_details.get("starting_equipment", []):
            equipment = item.get("equipment", {})
            quantity = item.get("quantity", 1)
            starting_equipment.append({
                "name": equipment.get("name", "Unknown"),
                "quantity": quantity
            })

        # Extract starting equipment options
        equipment_options = []
        for option_set in class_details.get("starting_equipment_options", []):
            desc = option_set.get("desc", "Choose one option")
            choices = []

            for option in option_set.get("from", {}).get("options", []):
                if "item" in option:
                    item = option.get("item", {})
                    choices.append({
                        "name": item.get("name", "Unknown"),
                        "quantity": option.get("quantity", 1)
                    })

            equipment_options.append({
                "description": desc,
                "choices": choices
            })

        return {
            "class": class_details.get("name", class_name),
            "starting_equipment": starting_equipment,
            "equipment_options": equipment_options
        }

    @app.tool()
    @track_tool_usage(ToolCategory.SEARCH)
    def search_all_categories(query: str) -> Dict[str, Any]:
        """Search across all D&D 5e API categories for any D&D content matching the query.

        This is the primary search tool for finding D&D content. It searches across all available
        categories including spells, monsters, equipment, classes, races, magic items, and more.
        Results are ranked by relevance and include a "top results" section showing the best matches
        across all categories.

        The search is intelligent and considers:
        - Exact name matches
        - Partial name matches
        - Matches in descriptions
        - Content relevance to the query
        - D&D-specific synonyms and abbreviations
        - Special D&D terms and notation
        - Common misspellings of D&D terms

        For more specific searches, consider using category-specific tools like filter_spells_by_level
        or find_monsters_by_challenge_rating.

        Args:
            query: Search term (minimum 3 characters) to find across all D&D content

        Returns:
            A comprehensive dictionary containing matching items across all categories, organized by
            category with a "top_results" section highlighting the best matches, and source attribution
            to the D&D 5e API.
        """
        logger.debug(f"Searching all categories for: {query}")

        # Clear previous tool usages for this request
        source_tracker.tool_tracker.clear()

        if not query or len(query.strip()) < 3:
            error_response = {
                "error": "Search query must be at least 3 characters long",
                "message": "Please provide a more specific search term",
            }

            # Add attribution for the error message
            error_attr_id = attribution_manager.add_attribution(
                attribution=SourceAttribution(
                    source="D&D 5e API",
                    api_endpoint="N/A",
                    confidence=ConfidenceLevel.HIGH,
                    relevance_score=100.0,
                    tool_used="search_all_categories"
                )
            )

            # Prepare response with attribution for MCP
            return source_tracker.prepare_mcp_response(
                error_response,
                {"error": error_attr_id, "message": error_attr_id}
            )

        # Get available categories
        categories_response = requests.get(
            f"{BASE_URL}", timeout=REQUEST_TIMEOUT)
        if categories_response.status_code != 200:
            error_response = {
                "error": "Failed to fetch categories",
                "message": "API request failed, please try again",
            }

            # Add attribution for the error message
            error_attr_id = attribution_manager.add_attribution(
                attribution=SourceAttribution(
                    source="D&D 5e API",
                    api_endpoint=f"{BASE_URL}",
                    confidence=ConfidenceLevel.HIGH,
                    relevance_score=100.0,
                    tool_used="search_all_categories"
                )
            )

            # Prepare response with attribution for MCP
            return source_tracker.prepare_mcp_response(
                error_response,
                {"error": error_attr_id, "message": error_attr_id}
            )

        categories = list(categories_response.json().keys())

        # Enhance the query using our query enhancement module
        enhanced_query, enhancements = enhance_query(query)

        # Add attribution for the query enhancement
        enhancement_attr_id = attribution_manager.add_attribution(
            attribution=SourceAttribution(
                source="D&D Knowledge Navigator",
                api_endpoint="query_enhancement",
                confidence=ConfidenceLevel.HIGH,
                relevance_score=90.0,
                tool_used="search_all_categories",
                metadata={
                    "original_query": query,
                    "enhanced_query": enhanced_query,
                    "synonyms_added": [f"{orig} → {exp}" for orig, exp in enhancements["synonyms_added"]],
                    "special_terms": enhancements["special_terms"],
                    "fuzzy_matches": [f"{orig} → {corr}" for orig, corr in enhancements["fuzzy_matches"]]
                }
            )
        )

        # Use the enhanced query for tokenization
        query_tokens = [token.lower()
                        for token in enhanced_query.split() if len(token) > 2]

        # Use category prioritization from our module
        category_priorities = enhancements["category_priorities"]

        # Convert normalized scores (0-1) to priority multipliers (1-10)
        for category in category_priorities:
            if category in categories:
                category_priorities[category] = 1 + \
                    (category_priorities[category] * 9)
            else:
                category_priorities[category] = 1

        # Search each category
        results = {}
        total_count = 0
        all_matches = []
        attribution_map = {}

        for category in categories:
            # Skip rule-related categories for efficiency
            if category in ["rule-sections", "rules"]:
                continue

            # Get category items (from cache if available)
            category_data = _get_category_items(category, cache)
            if "error" in category_data:
                continue

            # Search for matching items with relevance scoring
            matching_items = []

            for item in category_data.get("items", []):
                item_name = item["name"].lower()
                item_index = item.get("index", "").lower()

                # Get item details for more comprehensive search
                item_details = None
                if any(token in item_name or token in item_index for token in query_tokens):
                    # Only fetch details if there's a potential match to avoid unnecessary API calls
                    item_details = _get_item_details(
                        category, item["index"], cache)

                # Calculate relevance score
                score = 0

                # Exact match in name or index
                if query.lower() == item_name or query.lower() == item_index:
                    score += 100

                # Also check for exact match with enhanced query
                if enhanced_query.lower() != query.lower() and (
                        enhanced_query.lower() == item_name or enhanced_query.lower() == item_index):
                    score += 90

                # Partial matches in name or index
                for token in query_tokens:
                    if token in item_name:
                        score += 20
                    if token in item_index:
                        score += 15

                # Check if name contains all tokens
                if all(token in item_name for token in query_tokens):
                    score += 50

                # Check if name starts with any token
                if any(item_name.startswith(token) for token in query_tokens):
                    score += 25

                # Search in description if available
                if item_details and isinstance(item_details, dict):
                    description = ""

                    # Extract description based on item type
                    if "desc" in item_details:
                        if isinstance(item_details["desc"], list):
                            description = " ".join(item_details["desc"])
                        else:
                            description = str(item_details["desc"])
                    elif "description" in item_details:
                        description = str(item_details["description"])

                    description = description.lower()

                    # Score based on description matches
                    for token in query_tokens:
                        if token in description:
                            score += 10

                    # Bonus for multiple token matches in description
                    matching_tokens = sum(
                        1 for token in query_tokens if token in description)
                    if matching_tokens > 1:
                        score += matching_tokens * 5

                # Apply category priority multiplier
                score *= category_priorities.get(category, 1)

                # Add to results if score is above threshold
                if score > 0:
                    # Create attribution for this item
                    confidence_level = ConfidenceLevel.HIGH if score > 70 else (
                        ConfidenceLevel.MEDIUM if score > 40 else ConfidenceLevel.LOW
                    )

                    item_attr_id = attribution_manager.add_attribution(
                        attribution=SourceAttribution(
                            source="D&D 5e API",
                            api_endpoint=f"{BASE_URL}/{category}/{item['index']}",
                            confidence=confidence_level,
                            relevance_score=min(score, 100),
                            tool_used="search_all_categories",
                            metadata={
                                "category": category,
                                "score": score
                            }
                        )
                    )

                    item_with_score = item.copy()
                    item_with_score["score"] = score
                    item_with_score["attribution_id"] = item_attr_id
                    matching_items.append(item_with_score)

                    # Add to all matches for cross-category top results
                    all_matches.append({
                        "category": category,
                        "item": item_with_score
                    })

            # Sort matching items by score
            matching_items.sort(key=lambda x: x["score"], reverse=True)

            # Add to results if there are matches
            if matching_items:
                # Create attribution for this category's results
                category_attr_id = attribution_manager.add_attribution(
                    attribution=SourceAttribution(
                        source="D&D 5e API",
                        api_endpoint=f"{BASE_URL}/{category}",
                        confidence=ConfidenceLevel.HIGH,
                        relevance_score=85.0,
                        tool_used="search_all_categories",
                        metadata={
                            "item_count": len(matching_items)
                        }
                    )
                )

                results[category] = {
                    "items": matching_items,
                    "count": len(matching_items),
                }
                attribution_map[f"results.{category}"] = category_attr_id
                total_count += len(matching_items)

        # Sort all matches by score for top results across categories
        all_matches.sort(key=lambda x: x["item"]["score"], reverse=True)
        # Get top 10 results across all categories
        top_results = all_matches[:10]

        # Create attribution for the overall search results
        search_attr_id = attribution_manager.add_attribution(
            attribution=SourceAttribution(
                source="D&D 5e API",
                api_endpoint=f"{BASE_URL}",
                confidence=ConfidenceLevel.HIGH,
                relevance_score=90.0,
                tool_used="search_all_categories",
                metadata={
                    "query": query,
                    "enhanced_query": enhanced_query,
                    "total_results": total_count
                }
            )
        )

        # Create the response data
        response_data = {
            "query": query,
            "enhanced_query": enhanced_query,
            "query_enhancements": {
                "synonyms_added": [f"{orig} → {exp}" for orig, exp in enhancements["synonyms_added"]],
                "special_terms": enhancements["special_terms"],
                "fuzzy_matches": [f"{orig} → {corr}" for orig, corr in enhancements["fuzzy_matches"]]
            },
            "results": results,
            "total_count": total_count,
            "top_results": [
                {
                    "category": match["category"],
                    "name": match["item"]["name"],
                    "index": match["item"]["index"],
                    "score": match["item"]["score"],
                }
                for match in top_results
            ],
        }

        # Add attributions for top results
        for i, match in enumerate(top_results):
            attribution_map[f"top_results.{i}"] = match["item"]["attribution_id"]

        # Add attribution for the overall response
        attribution_map["query"] = search_attr_id
        attribution_map["enhanced_query"] = enhancement_attr_id
        attribution_map["query_enhancements"] = enhancement_attr_id
        attribution_map["total_count"] = search_attr_id

        # Format the response using our template system if enabled
        if TEMPLATES_ENABLED:
            formatted_content = format_search_results(
                response_data, include_attribution=False)
            response_data["content"] = formatted_content

        # Prepare the final response with all attributions
        return source_tracker.prepare_mcp_response(response_data, attribution_map)

    @app.tool()
    @track_tool_usage(ToolCategory.SEARCH)
    def verify_with_api(statement: str, category: str = None) -> Dict[str, Any]:
        """Verify the accuracy of a D&D statement by checking it against the official D&D 5e API data.

        This tool analyzes a statement about D&D 5e rules, creatures, spells, or other game elements
        and verifies its accuracy by searching the official D&D 5e API. It extracts key terms from
        the statement and searches for relevant information.

        The verification process:
        1. Extracts key terms from the statement
        2. Searches the D&D 5e API for these terms
        3. Analyzes the search results to verify the statement
        4. Returns the verification results with confidence levels
        5. Includes source attribution for all information

        Args:
            statement: The D&D statement to verify (e.g., "Fireball is a 3rd-level evocation spell")
            category: Optional category to focus the search (e.g., "spells", "monsters", "classes")

        Returns:
            A dictionary containing verification results, relevant D&D information, and source attribution.
        """
        logger.debug(f"Verifying statement: {statement}")

        # Clear previous tool usages for this request
        source_tracker.tool_tracker.clear()

        # Extract key terms from the statement
        # Filter out common words and keep only meaningful terms
        common_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "with", "by", "about", "against", "between", "into", "through", "during",
            "before", "after", "above", "below", "from", "up", "down", "of", "off",
            "over", "under", "again", "further", "then", "once", "here", "there",
            "when", "where", "why", "how", "all", "any", "both", "each", "few",
            "more", "most", "other", "some", "such", "no", "nor", "not", "only",
            "own", "same", "so", "than", "too", "very", "s", "t", "can", "will",
            "just", "don", "should", "now", "d&d", "dnd", "dungeons", "dragons",
            "dungeon", "dragon", "player", "character", "dm", "game", "roll", "dice",
            "rules", "rule", "edition", "5e", "fifth"
        }

        # Use our query enhancement module to extract key terms
        enhanced_statement, enhancements = enhance_query(statement)

        # Get special terms and synonyms from the enhancements
        special_terms = enhancements["special_terms"]

        # Extract search terms from the statement
        words = statement.lower().split()
        search_terms = [word.strip('.,?!;:()"\'') for word in words
                        if word.strip('.,?!;:()"\'') not in common_words
                        and len(word.strip('.,?!;:()"\'-')) > 2]

        # Add special terms to search terms if they're not already included
        for term in special_terms:
            term_lower = term.lower()
            if term_lower not in search_terms:
                search_terms.append(term_lower)

        # Add expanded terms from synonyms
        for original, expanded in enhancements["synonyms_added"]:
            if expanded.lower() not in search_terms:
                search_terms.append(expanded.lower())

        # Add corrections from fuzzy matches
        for original, correction in enhancements["fuzzy_matches"]:
            if correction.lower() not in search_terms:
                search_terms.append(correction.lower())

        # Remove duplicates while preserving order
        unique_search_terms = []
        for term in search_terms:
            if term not in unique_search_terms:
                unique_search_terms.append(term)
        search_terms = unique_search_terms

        # Create attribution for the statement analysis
        statement_attr_id = attribution_manager.add_attribution(
            attribution=SourceAttribution(
                source="D&D Knowledge Navigator",
                api_endpoint="statement_analysis",
                confidence=ConfidenceLevel.HIGH,
                relevance_score=100.0,
                tool_used="verify_with_api",
                metadata={
                    "statement": statement,
                    "search_terms": search_terms,
                    "enhanced_statement": enhanced_statement
                }
            )
        )

        # Initialize results
        results = {}
        found_matches = False
        attribution_map = {
            "statement": statement_attr_id,
            "search_terms": statement_attr_id
        }

        if category:
            # Search in specific category
            category_data = _get_category_items(category, cache)
            if "error" not in category_data:
                matching_items = []
                for item in category_data.get("items", []):
                    item_name = item["name"].lower()
                    if any(term in item_name for term in search_terms):
                        item_details = _get_item_details(
                            category, item["index"], cache)
                        if "error" not in item_details:
                            # Create attribution for this item
                            item_attr_id = attribution_manager.add_attribution(
                                attribution=SourceAttribution(
                                    source="D&D 5e API",
                                    api_endpoint=f"{BASE_URL}/{category}/{item['index']}",
                                    confidence=ConfidenceLevel.HIGH,
                                    relevance_score=90.0,
                                    tool_used="verify_with_api",
                                    metadata={
                                        "category": category,
                                        "statement": statement
                                    }
                                )
                            )

                            matching_items.append({
                                "name": item["name"],
                                "details": item_details,
                                "attribution_id": item_attr_id
                            })

                if matching_items:
                    results[category] = matching_items
                    found_matches = True
                    attribution_map[f"results.{category}"] = statement_attr_id
        else:
            # Use category prioritization from our module to focus the search
            category_priorities = enhancements["category_priorities"]
            top_categories = get_top_categories(enhanced_statement, 5)

            # Search across prioritized categories
            search_query = " ".join(search_terms)

            # First, try the top categories
            for category_name in top_categories:
                category_data = _get_category_items(category_name, cache)
                if "error" not in category_data:
                    matching_items = []
                    for item in category_data.get("items", []):
                        item_name = item["name"].lower()
                        if any(term in item_name for term in search_terms):
                            item_details = _get_item_details(
                                category_name, item["index"], cache)
                            if "error" not in item_details:
                                # Create attribution for this item
                                item_attr_id = attribution_manager.add_attribution(
                                    attribution=SourceAttribution(
                                        source="D&D 5e API",
                                        api_endpoint=f"{BASE_URL}/{category_name}/{item['index']}",
                                        confidence=ConfidenceLevel.MEDIUM,
                                        relevance_score=category_priorities.get(
                                            category_name, 0.5) * 100,
                                        tool_used="verify_with_api",
                                        metadata={
                                            "category": category_name,
                                            "statement": statement
                                        }
                                    )
                                )

                                matching_items.append({
                                    "name": item["name"],
                                    "details": item_details,
                                    "attribution_id": item_attr_id
                                })

                    if matching_items:
                        results[category_name] = matching_items
                        found_matches = True
                        attribution_map[f"results.{category_name}"] = statement_attr_id

            # If no matches found in top categories, fall back to search_all_categories
            if not found_matches:
                all_results = search_all_categories(search_query)

                if all_results.get("total_count", 0) > 0:
                    for category_name, category_data in all_results.get("results", {}).items():
                        matching_items = []
                        for item in category_data.get("items", []):
                            item_details = _get_item_details(
                                category_name, item["index"], cache)
                            if "error" not in item_details:
                                # Create attribution for this item
                                item_attr_id = attribution_manager.add_attribution(
                                    attribution=SourceAttribution(
                                        source="D&D 5e API",
                                        api_endpoint=f"{BASE_URL}/{category_name}/{item['index']}",
                                        confidence=ConfidenceLevel.MEDIUM,
                                        relevance_score=item.get(
                                            "score", 50.0),
                                        tool_used="verify_with_api",
                                        metadata={
                                            "category": category_name,
                                            "statement": statement
                                        }
                                    )
                                )

                                matching_items.append({
                                    "name": item["name"],
                                    "details": item_details,
                                    "attribution_id": item_attr_id
                                })

                        if matching_items:
                            results[category_name] = matching_items
                            found_matches = True
                            attribution_map[f"results.{category_name}"] = statement_attr_id

        # Create attribution for the overall verification result
        verification_attr_id = attribution_manager.add_attribution(
            attribution=SourceAttribution(
                source="D&D 5e API",
                api_endpoint=f"{BASE_URL}",
                confidence=ConfidenceLevel.HIGH if found_matches else ConfidenceLevel.LOW,
                relevance_score=85.0 if found_matches else 30.0,
                tool_used="verify_with_api",
                metadata={
                    "statement": statement,
                    "found_matches": found_matches,
                    "categories_checked": list(results.keys()) if results else []
                }
            )
        )

        # Create the response data
        response_data = {
            "statement": statement,
            "enhanced_statement": enhanced_statement,
            "search_terms": search_terms,
            "results": results,
            "found_matches": found_matches,
            "query_enhancements": {
                "synonyms_added": [f"{orig} → {exp}" for orig, exp in enhancements["synonyms_added"]],
                "special_terms": enhancements["special_terms"],
                "fuzzy_matches": [f"{orig} → {corr}" for orig, corr in enhancements["fuzzy_matches"]]
            }
        }

        # Add attribution for the overall response
        attribution_map["found_matches"] = verification_attr_id
        attribution_map["enhanced_statement"] = statement_attr_id
        attribution_map["query_enhancements"] = statement_attr_id

        # Format the response using our template system if enabled
        if TEMPLATES_ENABLED:
            formatted_content = f"# Verification of D&D Statement\n\n"
            formatted_content += f"**Statement:** {statement}\n\n"

            if found_matches:
                formatted_content += "## Verification Results\n\n"
                formatted_content += f"Found information related to {len(search_terms)} search terms: "
                formatted_content += f"*{', '.join(search_terms)}*\n\n"

                # Format each category's results
                for category_name, items in results.items():
                    formatted_content += f"### {category_name.replace('_', ' ').title()}\n\n"

                    for item in items:
                        # Format the item details using our template system
                        item_details = item.get("details", {})
                        item_type = category_name[:-1] if category_name.endswith(
                            's') else category_name

                        formatted_content += f"**{item.get('name', 'Unknown')}**\n\n"

                        # Add a brief formatted excerpt
                        if item_details:
                            # Get a brief formatted version (first 200 chars)
                            formatted_item = format_dnd_data(
                                item_details, item_type)
                            brief_format = formatted_item.split("\n\n")[0]
                            if len(brief_format) > 200:
                                brief_format = brief_format[:197] + "..."

                            formatted_content += f"{brief_format}\n\n"
            else:
                formatted_content += "## No Matching Information Found\n\n"
                formatted_content += "Could not find specific information to verify this statement in the D&D 5e API.\n\n"
                formatted_content += f"Search terms used: *{', '.join(search_terms)}*\n\n"

            response_data["content"] = formatted_content

        # Prepare the final response with all attributions
        return source_tracker.prepare_mcp_response(response_data, attribution_map)

    @app.tool()
    @track_tool_usage(ToolCategory.CONTEXT)
    def check_api_health() -> Dict[str, Any]:
        """Check the health and status of the D&D 5e API.

        This tool verifies that the D&D 5e API is operational and provides information
        about available endpoints and resources. It's useful for diagnosing issues or
        understanding what data is available.

        The health check includes:
        1. Verifying the base API endpoint is accessible
        2. Checking key endpoints (spells, monsters, classes)
        3. Reporting on available categories and their status
        4. Providing counts of available resources

        Returns:
            A dictionary containing API status information, available endpoints,
            resource counts, and source attribution to the D&D 5e API.
        """
        logger.debug("Checking API health")

        # Clear previous tool usages for this request
        source_tracker.tool_tracker.clear()

        # Check base API endpoint
        try:
            base_response = requests.get(
                f"{BASE_URL}", timeout=REQUEST_TIMEOUT)
            base_status = base_response.status_code == 200
            base_data = base_response.json() if base_status else {}
        except Exception as e:
            logger.error(f"Error checking base API: {e}")
            base_status = False
            base_data = {}

        # Create attribution for the base API check
        base_attr_id = attribution_manager.add_attribution(
            attribution=SourceAttribution(
                source="D&D 5e API",
                api_endpoint=f"{BASE_URL}",
                confidence=ConfidenceLevel.HIGH,
                relevance_score=100.0,
                tool_used="check_api_health",
                metadata={
                    "status": base_status
                }
            )
        )

        if not base_status:
            error_response = {
                "status": "error",
                "message": "D&D 5e API is not responding",
                "details": "The base API endpoint could not be reached. Please try again later."
            }

            # Prepare response with attribution for MCP
            return source_tracker.prepare_mcp_response(
                error_response,
                {"status": base_attr_id, "message": base_attr_id,
                    "details": base_attr_id}
            )

        # Check key endpoints
        endpoints_status = {}
        endpoints_attr_ids = {}

        key_endpoints = ["spells", "monsters", "classes"]
        for endpoint in key_endpoints:
            try:
                endpoint_response = requests.get(
                    f"{BASE_URL}/{endpoint}", timeout=REQUEST_TIMEOUT)
                endpoint_status = endpoint_response.status_code == 200
                endpoint_data = endpoint_response.json() if endpoint_status else {}
                count = endpoint_data.get("count", 0) if endpoint_status else 0
                endpoints_status[endpoint] = {
                    "status": endpoint_status,
                    "count": count
                }

                # Create attribution for this endpoint check
                endpoint_attr_id = attribution_manager.add_attribution(
                    attribution=SourceAttribution(
                        source="D&D 5e API",
                        api_endpoint=f"{BASE_URL}/{endpoint}",
                        confidence=ConfidenceLevel.HIGH,
                        relevance_score=90.0,
                        tool_used="check_api_health",
                        metadata={
                            "status": endpoint_status,
                            "count": count
                        }
                    )
                )
                endpoints_attr_ids[endpoint] = endpoint_attr_id

            except Exception as e:
                logger.error(f"Error checking {endpoint} endpoint: {e}")
                endpoints_status[endpoint] = {
                    "status": False,
                    "error": str(e)
                }

                # Create attribution for this endpoint error
                endpoint_attr_id = attribution_manager.add_attribution(
                    attribution=SourceAttribution(
                        source="D&D 5e API",
                        api_endpoint=f"{BASE_URL}/{endpoint}",
                        confidence=ConfidenceLevel.LOW,
                        relevance_score=50.0,
                        tool_used="check_api_health",
                        metadata={
                            "status": False,
                            "error": str(e)
                        }
                    )
                )
                endpoints_attr_ids[endpoint] = endpoint_attr_id

        # Create the health check result
        health_check = {
            "status": "healthy" if base_status and all(endpoint["status"] for endpoint in endpoints_status.values()) else "degraded",
            "base_api": {
                "status": "online" if base_status else "offline",
                "available_categories": list(base_data.keys()) if base_status else []
            },
            "key_endpoints": endpoints_status,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        }

        # Create attribution for the overall health check
        health_attr_id = attribution_manager.add_attribution(
            attribution=SourceAttribution(
                source="D&D 5e API",
                api_endpoint=f"{BASE_URL}",
                confidence=ConfidenceLevel.HIGH,
                relevance_score=95.0,
                tool_used="check_api_health",
                metadata={
                    "status": health_check["status"],
                    "timestamp": health_check["timestamp"]
                }
            )
        )

        # Create attribution map
        attribution_map = {
            "status": health_attr_id,
            "base_api": base_attr_id,
            "timestamp": health_attr_id
        }

        # Add attributions for key endpoints
        for endpoint in key_endpoints:
            attribution_map[f"key_endpoints.{endpoint}"] = endpoints_attr_ids[endpoint]

        # Format the health check result using our template system if enabled
        if TEMPLATES_ENABLED:
            formatted_content = f"# D&D 5e API Health Check\n\n"
            formatted_content += f"**Status:** {health_check['status'].upper()}\n"
            formatted_content += f"**Timestamp:** {health_check['timestamp']}\n\n"

            formatted_content += "## Base API\n\n"
            formatted_content += f"**Status:** {health_check['base_api']['status']}\n"

            if health_check['base_api']['available_categories']:
                formatted_content += f"**Available Categories:** {len(health_check['base_api']['available_categories'])}\n\n"
                formatted_content += "Categories:\n"
                for category in sorted(health_check['base_api']['available_categories']):
                    formatted_content += f"- {category}\n"
            else:
                formatted_content += "No categories available.\n"

            formatted_content += "\n## Key Endpoints\n\n"

            for endpoint, status in health_check['key_endpoints'].items():
                formatted_content += f"### {endpoint.title()}\n\n"
                formatted_content += f"**Status:** {status['status']}\n"

                if 'count' in status:
                    formatted_content += f"**Available Items:** {status['count']}\n"

                if 'error' in status:
                    formatted_content += f"**Error:** {status['error']}\n"

                formatted_content += "\n"

            health_check["content"] = formatted_content

        # Prepare the final response with all attributions
        return source_tracker.prepare_mcp_response(health_check, attribution_map)

    @app.tool()
    def generate_treasure_hoard(challenge_rating: float, is_final_treasure: bool = False, treasure_type: str = "hoard") -> Dict[str, Any]:
        """Generate D&D 5e treasure based on challenge rating and context.

        This tool creates appropriate treasure for encounters or dungeons following the
        Dungeon Master's Guide treasure tables. It uses official D&D 5e API data for
        equipment and magic items to ensure accuracy.

        The treasure is balanced according to the challenge rating provided, with higher
        CR values resulting in more valuable treasure. Final treasure (such as at the end
        of a dungeon) can be made more significant by setting is_final_treasure to True.

        Args:
            challenge_rating: The challenge rating to base treasure on (0.25 to 30)
            is_final_treasure: Whether this is a climactic treasure (increases value)
            treasure_type: Type of treasure to generate ("individual" or "hoard")

        Returns:
            A dictionary containing generated treasure including coins, equipment items, and magic items
            with source attribution to the D&D 5e API.
        """
        logger.debug(
            f"Generating {treasure_type} treasure for CR {challenge_rating}, final: {is_final_treasure}")

        # Validate inputs
        if challenge_rating < 0 or challenge_rating > 30:
            return {
                "error": "Challenge rating must be between 0 and 30",
                "message": "Please provide a valid challenge rating",
                "source": "D&D 5e API"
            }

        if treasure_type not in ["individual", "hoard"]:
            return {
                "error": "Invalid treasure type",
                "message": "Treasure type must be 'individual' or 'hoard'",
                "source": "D&D 5e API"
            }

        # Determine treasure table based on CR
        if challenge_rating <= 4:
            cr_tier = "0-4"
        elif challenge_rating <= 10:
            cr_tier = "5-10"
        elif challenge_rating <= 16:
            cr_tier = "11-16"
        else:
            cr_tier = "17+"

        # Generate coins based on DMG tables
        coins = _generate_coins_from_dmg(cr_tier, treasure_type)

        # Get equipment from API
        equipment_items = _get_equipment_for_treasure(
            cr_tier, treasure_type, cache)

        # Get magic items from API for hoards
        magic_items = []
        if treasure_type == "hoard":
            magic_items = _get_magic_items_for_treasure(
                cr_tier, is_final_treasure, cache)

        # Apply final treasure bonus if applicable
        if is_final_treasure:
            coins = _apply_final_treasure_bonus(coins)

        # Calculate total value
        total_value = _calculate_total_value(
            coins, equipment_items, magic_items)

        return {
            "challenge_rating": challenge_rating,
            "treasure_type": treasure_type,
            "cr_tier": cr_tier,
            "is_final_treasure": is_final_treasure,
            "coins": coins,
            "equipment_items": equipment_items,
            "magic_items": magic_items,
            "total_value_gp": total_value,
            "source": "D&D 5e API"
        }

    def _generate_coins_from_dmg(cr_tier: str, treasure_type: str) -> Dict[str, int]:
        """Generate coins based on DMG treasure tables."""
        import random

        coins = {"cp": 0, "sp": 0, "gp": 0, "pp": 0}

        # DMG Individual Treasure Tables (p.136)
        if treasure_type == "individual":
            if cr_tier == "0-4":
                roll = random.randint(1, 100)
                if roll <= 30:
                    coins["cp"] = random.randint(5, 30)
                elif roll <= 60:
                    coins["sp"] = random.randint(4, 24)
                elif roll <= 70:
                    coins["ep"] = random.randint(3, 18)
                elif roll <= 95:
                    coins["gp"] = random.randint(3, 18)
                else:
                    coins["pp"] = random.randint(1, 6)

            elif cr_tier == "5-10":
                roll = random.randint(1, 100)
                if roll <= 30:
                    coins["cp"] = random.randint(4, 24) * 100
                    coins["sp"] = random.randint(6, 36) * 10
                elif roll <= 60:
                    coins["sp"] = random.randint(2, 12) * 100
                    coins["gp"] = random.randint(2, 12) * 10
                elif roll <= 70:
                    coins["ep"] = random.randint(2, 12) * 10
                    coins["gp"] = random.randint(2, 12) * 10
                elif roll <= 95:
                    coins["gp"] = random.randint(4, 24) * 10
                else:
                    coins["gp"] = random.randint(2, 12) * 10
                    coins["pp"] = random.randint(3, 18)

            elif cr_tier == "11-16":
                roll = random.randint(1, 100)
                if roll <= 20:
                    coins["sp"] = random.randint(4, 24) * 100
                    coins["gp"] = random.randint(1, 6) * 100
                elif roll <= 35:
                    coins["ep"] = random.randint(1, 6) * 100
                    coins["gp"] = random.randint(1, 6) * 100
                elif roll <= 75:
                    coins["gp"] = random.randint(2, 12) * 100
                    coins["pp"] = random.randint(1, 6) * 10
                else:
                    coins["gp"] = random.randint(2, 12) * 100
                    coins["pp"] = random.randint(2, 12) * 10

            else:  # cr_tier == "17+"
                roll = random.randint(1, 100)
                if roll <= 15:
                    coins["ep"] = random.randint(2, 12) * 1000
                    coins["gp"] = random.randint(8, 48) * 100
                elif roll <= 55:
                    coins["gp"] = random.randint(1, 6) * 1000
                    coins["pp"] = random.randint(1, 6) * 100
                else:
                    coins["gp"] = random.randint(1, 6) * 1000
                    coins["pp"] = random.randint(2, 12) * 100

        # DMG Treasure Hoard Tables (p.137-139)
        else:  # treasure_type == "hoard"
            if cr_tier == "0-4":
                coins["cp"] = random.randint(6, 36) * 100
                coins["sp"] = random.randint(3, 18) * 100
                coins["gp"] = random.randint(2, 12) * 10

            elif cr_tier == "5-10":
                coins["cp"] = random.randint(2, 12) * 100
                coins["sp"] = random.randint(2, 12) * 1000
                coins["gp"] = random.randint(6, 36) * 100
                coins["pp"] = random.randint(3, 18) * 10

            elif cr_tier == "11-16":
                coins["gp"] = random.randint(4, 24) * 1000
                coins["pp"] = random.randint(5, 30) * 100

            else:  # cr_tier == "17+"
                coins["gp"] = random.randint(12, 72) * 1000
                coins["pp"] = random.randint(8, 48) * 1000

        return coins

    def _get_equipment_for_treasure(cr_tier: str, treasure_type: str, cache: APICache) -> List[Dict[str, Any]]:
        """Get equipment items from the D&D 5e API based on CR tier."""
        import random

        # Get all equipment from API
        equipment_list = _get_category_items("equipment", cache)
        if "error" in equipment_list:
            return []

        # Number of items to include
        num_items = 0
        if treasure_type == "individual":
            num_items = random.randint(0, 2)
        else:  # hoard
            if cr_tier == "0-4":
                num_items = random.randint(2, 5)
            elif cr_tier == "5-10":
                num_items = random.randint(2, 6)
            elif cr_tier == "11-16":
                num_items = random.randint(1, 4)
            else:  # 17+
                num_items = random.randint(1, 3)

        # Value ranges by CR tier (in gp)
        value_ranges = {
            "0-4": (1, 50),
            "5-10": (10, 250),
            "11-16": (50, 750),
            "17+": (100, 2500)
        }

        min_value, max_value = value_ranges[cr_tier]

        # Filter equipment by value
        valuable_items = []
        for item in equipment_list.get("items", []):
            item_index = item["index"]
            item_details = _get_item_details("equipment", item_index, cache)

            if "error" in item_details or not isinstance(item_details, dict):
                continue

            # Check if item has cost
            if "cost" in item_details:
                cost = item_details["cost"]
                value_in_gp = _convert_currency(
                    cost["quantity"], cost["unit"], "gp")

                # Check if value is in appropriate range
                if min_value <= value_in_gp <= max_value:
                    valuable_items.append({
                        "name": item_details["name"],
                        "value": f"{cost['quantity']} {cost['unit']}",
                        "value_in_gp": value_in_gp,
                        "description": _get_description(item_details),
                        "uri": f"resource://dnd/item/equipment/{item_index}"
                    })

        # Select random items
        selected_items = []
        if valuable_items:
            # Ensure we don't try to select more items than are available
            num_items = min(num_items, len(valuable_items))
            selected_items = random.sample(valuable_items, num_items)

        return selected_items

    def _get_magic_items_for_treasure(cr_tier: str, is_final_treasure: bool, cache: APICache) -> List[Dict[str, Any]]:
        """Get magic items from the D&D 5e API based on CR tier."""
        import random

        # Get all magic items from API
        magic_items_list = _get_category_items("magic-items", cache)
        if "error" in magic_items_list:
            return []

        # Number of magic items by CR tier
        num_items_range = {
            "0-4": (0, 2),
            "5-10": (1, 3),
            "11-16": (1, 4),
            "17+": (2, 6)
        }

        min_items, max_items = num_items_range[cr_tier]
        if is_final_treasure:
            max_items += 1

        num_items = random.randint(min_items, max_items)

        # Rarity weights by CR tier
        rarity_weights = {
            # Common, Uncommon, Rare, Very Rare, Legendary
            "0-4": [70, 25, 5, 0, 0],
            "5-10": [20, 50, 25, 5, 0],
            "11-16": [5, 25, 45, 20, 5],
            "17+": [0, 10, 30, 40, 20]
        }

        # Group items by rarity
        items_by_rarity = {
            "Common": [],
            "Uncommon": [],
            "Rare": [],
            "Very Rare": [],
            "Legendary": []
        }

        # Categorize all magic items by rarity
        for item in magic_items_list.get("items", []):
            item_index = item["index"]
            item_details = _get_item_details("magic-items", item_index, cache)

            if "error" in item_details or not isinstance(item_details, dict):
                continue

            rarity = item_details.get("rarity", {}).get("name", "Unknown")
            if rarity in items_by_rarity:
                items_by_rarity[rarity].append(item_details)

        # Select magic items based on appropriate rarity for the tier
        selected_items = []
        for _ in range(num_items):
            # Choose rarity based on tier weights
            weights = rarity_weights[cr_tier]
            rarity_roll = random.randint(1, 100)

            chosen_rarity = "Common"  # Default
            if rarity_roll <= weights[0]:
                chosen_rarity = "Common"
            elif rarity_roll <= weights[0] + weights[1]:
                chosen_rarity = "Uncommon"
            elif rarity_roll <= weights[0] + weights[1] + weights[2]:
                chosen_rarity = "Rare"
            elif rarity_roll <= weights[0] + weights[1] + weights[2] + weights[3]:
                chosen_rarity = "Very Rare"
            else:
                chosen_rarity = "Legendary"

            # If no items of chosen rarity, pick next lower rarity
            available_rarities = [r for r in ["Common", "Uncommon", "Rare", "Very Rare", "Legendary"]
                                  if items_by_rarity[r]]
            if not items_by_rarity[chosen_rarity] and available_rarities:
                # Find closest available rarity
                if chosen_rarity == "Legendary" and "Very Rare" in available_rarities:
                    chosen_rarity = "Very Rare"
                elif chosen_rarity == "Very Rare" and "Rare" in available_rarities:
                    chosen_rarity = "Rare"
                elif chosen_rarity == "Rare" and "Uncommon" in available_rarities:
                    chosen_rarity = "Uncommon"
                elif chosen_rarity == "Uncommon" and "Common" in available_rarities:
                    chosen_rarity = "Common"
                else:
                    chosen_rarity = available_rarities[0]

            # Select a random item of the chosen rarity
            if items_by_rarity[chosen_rarity]:
                item_details = random.choice(items_by_rarity[chosen_rarity])

                # Extract better description
                description = _get_magic_item_description(item_details)

                selected_items.append({
                    "name": item_details.get("name", "Unknown Magic Item"),
                    "rarity": chosen_rarity,
                    "description": description,
                    "uri": f"resource://dnd/item/magic-items/{item_details.get('index', '')}"
                })

        return selected_items

    def _get_magic_item_description(item_details: Dict[str, Any]) -> str:
        """Extract a useful description from magic item details."""
        description = ""

        # Try to get the item type
        item_type = ""
        if "equipment_category" in item_details:
            item_type = item_details["equipment_category"].get("name", "")

        # Get the rarity and attunement info
        rarity = item_details.get("rarity", {}).get("name", "")
        requires_attunement = item_details.get("requires_attunement", False)
        attunement_text = ", requires attunement" if requires_attunement else ""

        # Start with basic info
        description = f"{item_type}, {rarity.lower()}{attunement_text}"

        # Add a snippet of the actual description if available
        if "desc" in item_details:
            if isinstance(item_details["desc"], list) and item_details["desc"]:
                first_para = item_details["desc"][0]
                if len(first_para) > 100:
                    description += f": {first_para[:100]}..."
                else:
                    description += f": {first_para}"
            elif isinstance(item_details["desc"], str):
                if len(item_details["desc"]) > 100:
                    description += f": {item_details['desc'][:100]}..."
                else:
                    description += f": {item_details['desc']}"

        return description

    # Helper functions
    def _get_category_items(category: str, cache: APICache) -> Dict[str, Any]:
        """Get all items in a category, using cache if available."""
        cache_key = f"dnd_items_{category}"
        cached_data = cache.get(cache_key)

        if cached_data:
            # Add source attribution if not already present
            if isinstance(cached_data, dict) and "source" not in cached_data:
                cached_data["source"] = "D&D 5e API"
            return cached_data

        try:
            response = requests.get(f"{BASE_URL}/{category}")
            if response.status_code != 200:
                return {
                    "error": f"Category '{category}' not found or API request failed",
                    "status_code": response.status_code,
                    "message": "Please use only valid D&D 5e API categories",
                    "source": "D&D 5e API"
                }

            data = response.json()

            # Transform to resource format
            items = []
            for item in data.get("results", []):
                items.append({
                    "name": item["name"],
                    "index": item["index"],
                    "description": f"Details about {item['name']}",
                    "uri": f"resource://dnd/item/{category}/{item['index']}",
                    "source": "D&D 5e API"
                })

            result = {
                "category": category,
                "items": items,
                "count": len(items),
                "source": "D&D 5e API"
            }

            # Cache the result
            cache.set(cache_key, result)
            return result

        except Exception as e:
            logger.exception(f"Error fetching category {category}: {e}")
            return {
                "error": f"Failed to fetch category items: {str(e)}",
                "message": "API request failed, please try again with valid parameters",
                "source": "D&D 5e API"
            }

    def _get_item_details(category: str, index: str, cache: APICache) -> Dict[str, Any]:
        """Get detailed information about a specific item, using cache if available."""
        cache_key = f"dnd_item_{category}_{index}"
        cached_data = cache.get(cache_key)

        if cached_data:
            # Add source attribution if not already present
            if isinstance(cached_data, dict) and "source" not in cached_data:
                cached_data["source"] = "D&D 5e API"
            return cached_data

        try:
            response = requests.get(f"{BASE_URL}/{category}/{index}")
            if response.status_code != 200:
                return {
                    "error": f"Item '{index}' not found in category '{category}' or API request failed",
                    "status_code": response.status_code,
                    "message": "Please use only valid D&D 5e API endpoints and parameters",
                    "source": "D&D 5e API"
                }

            data = response.json()

            # Add source attribution
            data["source"] = "D&D 5e API"

            # Cache the result
            cache.set(cache_key, data)
            return data

        except Exception as e:
            logger.exception(f"Error fetching item {category}/{index}: {e}")
            return {
                "error": f"Failed to fetch item details: {str(e)}",
                "message": "API request failed, please try again with valid parameters",
                "source": "D&D 5e API"
            }

    def _convert_currency(amount: float, from_unit: str, to_unit: str) -> float:
        """Convert currency between different units (gp, sp, cp)."""
        # Conversion rates
        rates = {
            "cp": 0.01,  # 1 cp = 0.01 gp
            "sp": 0.1,   # 1 sp = 0.1 gp
            "gp": 1.0,   # 1 gp = 1 gp
            "pp": 10.0   # 1 pp = 10 gp
        }

        # Convert to gp first
        gp_value = amount * rates.get(from_unit.lower(), 1.0)

        # Convert from gp to target unit
        target_rate = rates.get(to_unit.lower(), 1.0)
        if target_rate == 0:
            return 0

        return gp_value / target_rate

    def _get_description(item: Dict[str, Any]) -> str:
        """Extract description from an item, handling different formats."""
        desc = item.get("desc", "")

        # Handle list of descriptions
        if isinstance(desc, list):
            if desc:
                return desc[0][:100] + "..." if len(desc[0]) > 100 else desc[0]
        # Handle string description
        if isinstance(desc, str):
            return desc[:100] + "..." if len(desc) > 100 else desc

        return "No description available"

    def _apply_final_treasure_bonus(coins: Dict[str, int]) -> Dict[str, int]:
        """Apply bonus to coins for final treasure."""
        import random

        # Bonus multiplier between 1.5 and 2.5
        multiplier = 1.5 + (random.random() * 1.0)

        # Apply multiplier to each coin type
        for coin_type in coins:
            coins[coin_type] = int(coins[coin_type] * multiplier)

        return coins

    def _calculate_total_value(coins: Dict[str, int], items: List[Dict[str, Any]],
                               magic_items: List[Dict[str, Any]]) -> float:
        """Calculate the total value of the treasure in gold pieces."""
        total_value = 0.0

        # Add coin values
        coin_values = {
            "cp": 0.01,
            "sp": 0.1,
            "gp": 1.0,
            "pp": 10.0
        }

        for coin_type, amount in coins.items():
            total_value += amount * coin_values.get(coin_type, 0)

        # Add item values
        for item in items:
            total_value += item.get("value_in_gp", 0)

        # Magic items are harder to value, use rarity as a guide
        rarity_values = {
            "Common": 50,
            "Uncommon": 500,
            "Rare": 5000,
            "Very Rare": 50000,
            "Legendary": 200000,
            "Unknown": 100
        }

        for item in magic_items:
            rarity = item.get("rarity", "Unknown")
            total_value += rarity_values.get(rarity, 100)

        return round(total_value, 2)

    print("D&D API tools registered successfully", file=sys.stderr)


def register_campaign_tools(app, supabase_client):
    """Register campaign database tools with the FastMCP app.

    Args:
        app: The FastMCP app instance
        supabase_client: The SupabaseClient instance for database access
    """
    print("Registering Campaign tools...", file=sys.stderr)

    # =========================================================================
    # CHARACTER TOOLS
    # =========================================================================

    @app.tool()
    def get_party_characters(party_name: str = None) -> Dict[str, Any]:
        """Get all characters in the campaign, optionally filtered by party.

        Returns character names, classes, races, and levels for quick reference.
        Use get_character_details for full character information.

        Args:
            party_name: Optional party name to filter characters

        Returns:
            Formatted list of party characters with basic stats.
        """
        logger.debug(f"Getting party characters: {party_name}")

        try:
            # Get party ID if name provided
            party_id = None
            if party_name:
                parties = supabase_client.get("parties",
                                              filters={"name": f"ilike.{party_name}"})
                if parties:
                    party_id = parties[0]["id"]

            characters = supabase_client.get_characters(party_id)

            return {
                "characters": characters,
                "count": len(characters),
                "content": format_character_list(characters),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting characters: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_character_details(character_name: str) -> Dict[str, Any]:
        """Get full details for a specific character.

        Includes ability scores, combat stats, spellcasting info, and class features.

        Args:
            character_name: Name of the character to look up

        Returns:
            Detailed character sheet with all available information.
        """
        logger.debug(f"Getting character details: {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            return {
                "character": char,
                "content": format_character_card(char),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting character details: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_character_spells(character_name: str, source_type: str = None) -> Dict[str, Any]:
        """Get all spells available to a character.

        Shows spells organized by source (class, item, feat) and level.

        Args:
            character_name: Name of the character
            source_type: Optional filter for spell source (class, item, feat)

        Returns:
            Formatted spell list organized by source and level.
        """
        logger.debug(f"Getting spells for {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            spells = supabase_client.get_character_spells(char["id"], source_type)

            return {
                "spells": spells,
                "count": len(spells),
                "content": format_character_spells(character_name, spells),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting character spells: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_character_feats(character_name: str) -> Dict[str, Any]:
        """Get all feats a character has.

        Args:
            character_name: Name of the character

        Returns:
            List of feats with descriptions and benefits.
        """
        logger.debug(f"Getting feats for {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            feats = supabase_client.get_character_feats(char["id"])

            return {
                "feats": feats,
                "count": len(feats),
                "content": format_character_feats(character_name, feats),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting character feats: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_character_forms(character_name: str) -> Dict[str, Any]:
        """Get transformation forms available to a character.

        Useful for druids, shapechangers, or characters with polymorph abilities.

        Args:
            character_name: Name of the character

        Returns:
            List of available forms with stats and notes.
        """
        logger.debug(f"Getting forms for {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            forms = supabase_client.get_character_forms(char["id"])

            return {
                "forms": forms,
                "count": len(forms),
                "content": format_character_forms(character_name, forms),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting character forms: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_character_companions(character_name: str) -> Dict[str, Any]:
        """Get companions (familiars, animal companions, etc.) for a character.

        Args:
            character_name: Name of the character

        Returns:
            List of companions with stats and current HP.
        """
        logger.debug(f"Getting companions for {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            companions = supabase_client.get_character_companions(char["id"])

            return {
                "companions": companions,
                "count": len(companions),
                "content": format_character_companions(character_name, companions),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting character companions: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def update_character(character_name: str,
                        level: int = None,
                        class_summary: str = None,
                        hp_current: int = None,
                        hp_max: int = None,
                        notes: str = None) -> Dict[str, Any]:
        """Update character information.

        Use for leveling up, changing HP, or updating notes.

        Args:
            character_name: Name of the character to update
            level: New character level
            class_summary: Updated class summary (e.g., "Bard 10 / Sorcerer 3")
            hp_current: Current hit points
            hp_max: Maximum hit points
            notes: Additional notes

        Returns:
            Updated character information.
        """
        logger.debug(f"Updating character: {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            # Build update data
            updates = {}
            if level is not None:
                updates["level"] = level
            if class_summary is not None:
                updates["class_summary"] = class_summary

            # HP updates go into dndbeyond_json
            json_updates = {}
            if hp_current is not None or hp_max is not None:
                current_hp = char.get("dndbeyond_json", {}).get("hit_points", {})
                json_updates["hit_points"] = {
                    "current": hp_current if hp_current is not None else current_hp.get("current"),
                    "max": hp_max if hp_max is not None else current_hp.get("max")
                }

            if updates:
                supabase_client.update_character(char["id"], updates)
            if json_updates:
                supabase_client.update_character_json(char["id"], json_updates)

            # Get updated character
            updated = supabase_client.get_character(char["id"])

            return {
                "character": updated,
                "content": format_character_card(updated),
                "message": f"Updated {character_name}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error updating character: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    # =========================================================================
    # INVENTORY TOOLS
    # =========================================================================

    @app.tool()
    def get_inventory(location_name: str = None) -> Dict[str, Any]:
        """Get inventory items, optionally filtered by storage location.

        Shows items organized by type with quantity, rarity, and magic status.

        Args:
            location_name: Optional location to filter (e.g., "Bag of Holding", "Vraath Keep")

        Returns:
            Formatted inventory list grouped by item type.
        """
        logger.debug(f"Getting inventory: {location_name}")

        try:
            items = supabase_client.get_inventory(location_name=location_name)

            return {
                "items": items,
                "count": len(items),
                "content": format_inventory_list(items, location_name),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting inventory: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def search_inventory(query: str) -> Dict[str, Any]:
        """Search for items across all storage locations.

        Args:
            query: Search term to match against item names

        Returns:
            Matching items with their locations.
        """
        logger.debug(f"Searching inventory: {query}")

        try:
            items = supabase_client.search_inventory(query)

            return {
                "items": items,
                "count": len(items),
                "content": format_inventory_search_results(items, query),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error searching inventory: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_magic_items(location_name: str = None) -> Dict[str, Any]:
        """Get all magic items, optionally filtered by location.

        Args:
            location_name: Optional location to filter

        Returns:
            List of magic items with rarity.
        """
        logger.debug(f"Getting magic items: {location_name}")

        try:
            # Get location ID if name provided
            location_id = None
            if location_name:
                loc = supabase_client.get_storage_location_by_name(location_name)
                if loc:
                    location_id = loc["id"]

            items = supabase_client.get_magic_items(location_id)

            return {
                "items": items,
                "count": len(items),
                "content": format_inventory_list(items, location_name or "All Locations"),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting magic items: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def add_item(location_name: str,
                item_name: str,
                quantity: int = 1,
                is_magic: bool = False,
                rarity: str = None,
                item_type: str = None,
                description: str = None,
                notes: str = None,
                reason: str = None) -> Dict[str, Any]:
        """Add an item to inventory.

        Creates a ledger entry for transaction history.

        Args:
            location_name: Storage location name (e.g., "Bag of Holding")
            item_name: Name of the item
            quantity: Number of items (default 1)
            is_magic: Whether the item is magical
            rarity: Item rarity (common, uncommon, rare, very_rare, legendary)
            item_type: Item category (weapon, armor, potion, scroll, etc.)
            description: Item description
            notes: Additional notes
            reason: Reason for adding (e.g., "Looted from dragon hoard")

        Returns:
            Added item details.
        """
        logger.debug(f"Adding item: {item_name} to {location_name}")

        try:
            loc = supabase_client.get_storage_location_by_name(location_name)
            if not loc:
                return {"error": f"Location '{location_name}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.add_item(
                storage_location_id=loc["id"],
                item_name=item_name,
                quantity=quantity,
                is_magic=is_magic,
                rarity=rarity,
                item_type=item_type,
                item_description=description,
                notes=notes,
                reason=reason
            )

            return {
                "item": result,
                "content": format_inventory_transaction(result, "added"),
                "message": f"Added {quantity}x {item_name} to {location_name}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error adding item: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def remove_item(location_name: str,
                   item_name: str,
                   quantity: int = None,
                   reason: str = None) -> Dict[str, Any]:
        """Remove an item from inventory.

        If quantity not specified, removes all of that item.
        Creates a ledger entry for transaction history.

        Args:
            location_name: Storage location name
            item_name: Name of the item to remove
            quantity: Number to remove (default: all)
            reason: Reason for removal (e.g., "Used in combat", "Sold to merchant")

        Returns:
            Result of the removal operation.
        """
        logger.debug(f"Removing item: {item_name} from {location_name}")

        try:
            loc = supabase_client.get_storage_location_by_name(location_name)
            if not loc:
                return {"error": f"Location '{location_name}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.remove_item(
                storage_location_id=loc["id"],
                item_name=item_name,
                quantity=quantity,
                reason=reason
            )

            if result is None:
                return {"error": f"Item '{item_name}' not found in {location_name}",
                        "source": "Campaign Database"}

            return {
                "result": result,
                "content": format_inventory_transaction(result, "removed"),
                "message": f"Removed {item_name} from {location_name}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error removing item: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def transfer_item(from_location: str,
                     to_location: str,
                     item_name: str,
                     quantity: int = None,
                     reason: str = None) -> Dict[str, Any]:
        """Transfer an item between storage locations.

        Args:
            from_location: Source location name
            to_location: Destination location name
            item_name: Name of the item to transfer
            quantity: Number to transfer (default: all)
            reason: Reason for transfer

        Returns:
            Transfer result.
        """
        logger.debug(f"Transferring {item_name} from {from_location} to {to_location}")

        try:
            from_loc = supabase_client.get_storage_location_by_name(from_location)
            to_loc = supabase_client.get_storage_location_by_name(to_location)

            if not from_loc:
                return {"error": f"Location '{from_location}' not found",
                        "source": "Campaign Database"}
            if not to_loc:
                return {"error": f"Location '{to_location}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.transfer_item(
                from_location_id=from_loc["id"],
                to_location_id=to_loc["id"],
                item_name=item_name,
                quantity=quantity,
                reason=reason
            )

            if result.get("error"):
                return {"error": result["error"], "source": "Campaign Database"}

            return {
                "result": result,
                "content": format_inventory_transaction(result, "transferred"),
                "message": f"Transferred {item_name} from {from_location} to {to_location}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error transferring item: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_storage_locations() -> Dict[str, Any]:
        """Get all storage locations for the party.

        Returns:
            List of storage locations with types and descriptions.
        """
        logger.debug("Getting storage locations")

        try:
            locations = supabase_client.get_storage_locations()

            return {
                "locations": locations,
                "count": len(locations),
                "content": format_storage_locations(locations),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting storage locations: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    # =========================================================================
    # CURRENCY TOOLS
    # =========================================================================

    @app.tool()
    def get_party_wealth(location_name: str = None) -> Dict[str, Any]:
        """Get party's currency, either total or by location.

        Args:
            location_name: Optional specific location to check

        Returns:
            Currency breakdown by denomination.
        """
        logger.debug(f"Getting party wealth: {location_name}")

        try:
            if location_name:
                currency = supabase_client.get_currency(location_name=location_name)
                content = format_currency_by_location(currency)
            else:
                # Get total wealth view
                wealth = supabase_client.get_total_wealth()
                content = format_wealth_summary(wealth)

            return {
                "currency": currency if location_name else wealth,
                "content": content,
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting party wealth: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_currency_by_location() -> Dict[str, Any]:
        """Get currency breakdown for each storage location.

        Returns:
            Currency at each location with totals.
        """
        logger.debug("Getting currency by location")

        try:
            currency = supabase_client.get_currency()

            return {
                "currency": currency,
                "count": len(currency),
                "content": format_currency_by_location(currency),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting currency by location: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def add_currency(location_name: str,
                    copper: int = 0,
                    silver: int = 0,
                    electrum: int = 0,
                    gold: int = 0,
                    platinum: int = 0,
                    reason: str = None) -> Dict[str, Any]:
        """Add currency to a storage location.

        Args:
            location_name: Storage location name
            copper: Copper pieces to add
            silver: Silver pieces to add
            electrum: Electrum pieces to add
            gold: Gold pieces to add
            platinum: Platinum pieces to add
            reason: Reason for adding (e.g., "Sold gems", "Quest reward")

        Returns:
            Updated currency balance.
        """
        logger.debug(f"Adding currency to {location_name}")

        try:
            loc = supabase_client.get_storage_location_by_name(location_name)
            if not loc:
                return {"error": f"Location '{location_name}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.add_currency(
                storage_location_id=loc["id"],
                copper=copper,
                silver=silver,
                electrum=electrum,
                gold=gold,
                platinum=platinum,
                reason=reason
            )

            return {
                "currency": result,
                "content": format_currency_transaction(result, "added"),
                "message": f"Added currency to {location_name}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error adding currency: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def remove_currency(location_name: str,
                       copper: int = 0,
                       silver: int = 0,
                       electrum: int = 0,
                       gold: int = 0,
                       platinum: int = 0,
                       reason: str = None) -> Dict[str, Any]:
        """Remove currency from a storage location.

        Args:
            location_name: Storage location name
            copper: Copper pieces to remove
            silver: Silver pieces to remove
            electrum: Electrum pieces to remove
            gold: Gold pieces to remove
            platinum: Platinum pieces to remove
            reason: Reason for removal (e.g., "Purchased items", "Paid for services")

        Returns:
            Updated currency balance.
        """
        logger.debug(f"Removing currency from {location_name}")

        try:
            loc = supabase_client.get_storage_location_by_name(location_name)
            if not loc:
                return {"error": f"Location '{location_name}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.remove_currency(
                storage_location_id=loc["id"],
                copper=copper,
                silver=silver,
                electrum=electrum,
                gold=gold,
                platinum=platinum,
                reason=reason
            )

            if result.get("error"):
                return {"error": result["error"], "source": "Campaign Database"}

            return {
                "currency": result,
                "content": format_currency_transaction(result, "removed"),
                "message": f"Removed currency from {location_name}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error removing currency: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def transfer_currency(from_location: str,
                         to_location: str,
                         copper: int = 0,
                         silver: int = 0,
                         electrum: int = 0,
                         gold: int = 0,
                         platinum: int = 0,
                         reason: str = None) -> Dict[str, Any]:
        """Transfer currency between storage locations.

        Args:
            from_location: Source location name
            to_location: Destination location name
            copper: Copper pieces to transfer
            silver: Silver pieces to transfer
            electrum: Electrum pieces to transfer
            gold: Gold pieces to transfer
            platinum: Platinum pieces to transfer
            reason: Reason for transfer

        Returns:
            Transfer result.
        """
        logger.debug(f"Transferring currency from {from_location} to {to_location}")

        try:
            from_loc = supabase_client.get_storage_location_by_name(from_location)
            to_loc = supabase_client.get_storage_location_by_name(to_location)

            if not from_loc:
                return {"error": f"Location '{from_location}' not found",
                        "source": "Campaign Database"}
            if not to_loc:
                return {"error": f"Location '{to_location}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.transfer_currency(
                from_location_id=from_loc["id"],
                to_location_id=to_loc["id"],
                copper=copper,
                silver=silver,
                electrum=electrum,
                gold=gold,
                platinum=platinum,
                reason=reason
            )

            return {
                "result": result,
                "content": format_currency_transaction(result, "transferred"),
                "message": f"Transferred currency from {from_location} to {to_location}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error transferring currency: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    # =========================================================================
    # DIARY TOOLS
    # =========================================================================

    @app.tool()
    def get_diary_entries(limit: int = 10, month_year: str = None) -> Dict[str, Any]:
        """Get campaign diary entries.

        Args:
            limit: Maximum number of entries to return (default 10)
            month_year: Optional filter by month (e.g., "March 2025")

        Returns:
            List of diary entries with summaries.
        """
        logger.debug(f"Getting diary entries: limit={limit}, month={month_year}")

        try:
            entries = supabase_client.get_diary_entries(limit=limit, month_year=month_year)

            return {
                "entries": entries,
                "count": len(entries),
                "content": format_diary_list(entries),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting diary entries: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def get_diary_entry(entry_id: str) -> Dict[str, Any]:
        """Get a specific diary entry by ID.

        Args:
            entry_id: UUID of the diary entry

        Returns:
            Full diary entry content.
        """
        logger.debug(f"Getting diary entry: {entry_id}")

        try:
            entry = supabase_client.get_diary_entry(entry_id)
            if not entry:
                return {"error": f"Entry '{entry_id}' not found",
                        "source": "Campaign Database"}

            return {
                "entry": entry,
                "content": format_diary_entry(entry),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error getting diary entry: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def add_diary_entry(content: str,
                       title: str = None,
                       session_date: str = None,
                       in_game_date: str = None,
                       locations: str = None,
                       npcs: str = None,
                       quests: str = None,
                       loot: str = None) -> Dict[str, Any]:
        """Add a new diary entry to the campaign log.

        Args:
            content: Main diary content/summary
            title: Entry title (e.g., "The Battle at Vraath Keep")
            session_date: Real-world session date (YYYY-MM-DD)
            in_game_date: In-game date
            locations: Comma-separated locations visited
            npcs: Comma-separated NPCs encountered
            quests: Comma-separated quest updates
            loot: Loot summary (JSON string or plain text)

        Returns:
            Created diary entry.
        """
        logger.debug(f"Adding diary entry: {title}")

        try:
            # Get the first party (assuming single party for now)
            parties = supabase_client.get("parties", limit=1)
            if not parties:
                return {"error": "No party found in database",
                        "source": "Campaign Database"}

            party_id = parties[0]["id"]

            # Parse month_year from session_date if provided
            month_year = None
            if session_date:
                try:
                    date_obj = datetime.strptime(session_date, "%Y-%m-%d")
                    month_year = date_obj.strftime("%B %Y")
                except ValueError:
                    pass

            # Parse comma-separated lists
            locations_list = [l.strip() for l in locations.split(",")] if locations else None
            npcs_list = [n.strip() for n in npcs.split(",")] if npcs else None
            quests_list = [q.strip() for q in quests.split(",")] if quests else None

            # Parse loot (could be JSON or plain text)
            loot_data = None
            if loot:
                try:
                    import json
                    loot_data = json.loads(loot)
                except (json.JSONDecodeError, ValueError):
                    loot_data = {"notes": loot}

            result = supabase_client.add_diary_entry(
                party_id=party_id,
                content=content,
                title=title,
                session_date=session_date,
                month_year=month_year,
                in_game_date=in_game_date,
                locations_visited=locations_list,
                npcs_encountered=npcs_list,
                quests_updated=quests_list,
                loot_summary=loot_data
            )

            return {
                "entry": result,
                "content": format_diary_entry(result),
                "message": f"Added diary entry: {title or 'Untitled'}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error adding diary entry: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def update_diary_entry(entry_id: str,
                          content: str = None,
                          title: str = None,
                          locations: str = None,
                          npcs: str = None,
                          quests: str = None) -> Dict[str, Any]:
        """Update an existing diary entry.

        Args:
            entry_id: UUID of the entry to update
            content: New content (replaces existing)
            title: New title
            locations: Comma-separated locations (replaces existing)
            npcs: Comma-separated NPCs (replaces existing)
            quests: Comma-separated quests (replaces existing)

        Returns:
            Updated diary entry.
        """
        logger.debug(f"Updating diary entry: {entry_id}")

        try:
            updates = {}
            if content is not None:
                updates["content"] = content
            if title is not None:
                updates["title"] = title
            if locations is not None:
                updates["locations_visited"] = [l.strip() for l in locations.split(",")]
            if npcs is not None:
                updates["npcs_encountered"] = [n.strip() for n in npcs.split(",")]
            if quests is not None:
                updates["quests_updated"] = [q.strip() for q in quests.split(",")]

            result = supabase_client.update_diary_entry(entry_id, updates)
            if not result:
                return {"error": f"Entry '{entry_id}' not found",
                        "source": "Campaign Database"}

            return {
                "entry": result,
                "content": format_diary_entry(result),
                "message": f"Updated diary entry: {result.get('title', entry_id)}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error updating diary entry: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def delete_diary_entry(entry_id: str) -> Dict[str, Any]:
        """Delete a diary entry.

        Args:
            entry_id: UUID of the entry to delete

        Returns:
            Confirmation of deletion.
        """
        logger.debug(f"Deleting diary entry: {entry_id}")

        try:
            success = supabase_client.delete_diary_entry(entry_id)

            if success:
                return {
                    "deleted": True,
                    "entry_id": entry_id,
                    "message": "Diary entry deleted successfully",
                    "source": "Campaign Database"
                }
            else:
                return {
                    "error": f"Entry '{entry_id}' not found or could not be deleted",
                    "source": "Campaign Database"
                }
        except Exception as e:
            logger.error(f"Error deleting diary entry: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    # =========================================================================
    # SPELL MANAGEMENT TOOLS
    # =========================================================================

    @app.tool()
    def add_character_spell(character_name: str,
                           spell_name: str,
                           spell_level: int,
                           source_type: str,
                           source_name: str,
                           charges: int = None,
                           notes: str = None) -> Dict[str, Any]:
        """Add a spell to a character's spell list.

        Args:
            character_name: Name of the character
            spell_name: Name of the spell
            spell_level: Spell level (0 for cantrips)
            source_type: Source type (class, item, feat, racial)
            source_name: Source name (e.g., "Staff of Power", "Bard")
            charges: Required charges if from an item
            notes: Additional notes

        Returns:
            Added spell details.
        """
        logger.debug(f"Adding spell {spell_name} to {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            result = supabase_client.add_character_spell(
                character_id=char["id"],
                spell_name=spell_name,
                spell_level=spell_level,
                source_type=source_type,
                source_name=source_name,
                charges_required=charges,
                notes=notes
            )

            return {
                "spell": result,
                "message": f"Added {spell_name} to {character_name}'s spell list",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error adding spell: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def remove_character_spell(character_name: str, spell_name: str) -> Dict[str, Any]:
        """Remove a spell from a character's spell list.

        Args:
            character_name: Name of the character
            spell_name: Name of the spell to remove

        Returns:
            Confirmation of removal.
        """
        logger.debug(f"Removing spell {spell_name} from {character_name}")

        try:
            char = supabase_client.get_character_by_name(character_name)
            if not char:
                return {"error": f"Character '{character_name}' not found",
                        "source": "Campaign Database"}

            success = supabase_client.remove_character_spell(char["id"], spell_name)

            if success:
                return {
                    "removed": True,
                    "spell_name": spell_name,
                    "message": f"Removed {spell_name} from {character_name}'s spell list",
                    "source": "Campaign Database"
                }
            else:
                return {"error": f"Spell '{spell_name}' not found on {character_name}",
                        "source": "Campaign Database"}
        except Exception as e:
            logger.error(f"Error removing spell: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    # =========================================================================
    # COMBINED LOOKUP TOOL (D&D API + Campaign)
    # =========================================================================

    @app.tool()
    def lookup_spell(spell_name: str, character_name: str = None) -> Dict[str, Any]:
        """Look up spell information from D&D 5e API and check if a character knows it.

        This tool combines the D&D 5e API spell data with campaign character spell lists.

        Args:
            spell_name: Name of the spell to look up
            character_name: Optional character to check if they know this spell

        Returns:
            Spell details from D&D API plus campaign character spell access info.
        """
        logger.debug(f"Looking up spell: {spell_name}, character: {character_name}")

        try:
            # Get spell from D&D API (using existing function)
            from src.core.api_helpers import API_BASE_URL
            import requests

            spell_index = spell_name.lower().replace(" ", "-").replace("'", "")
            url = f"{API_BASE_URL}/spells/{spell_index}"

            response = requests.get(url, timeout=REQUEST_TIMEOUT)

            spell_data = None
            if response.status_code == 200:
                spell_data = response.json()

            # Check character spell access if character specified
            character_access = None
            if character_name:
                char = supabase_client.get_character_by_name(character_name)
                if char:
                    spells = supabase_client.get_character_spells(char["id"])
                    for spell in spells:
                        if spell.get("spell_name", "").lower() == spell_name.lower():
                            character_access = {
                                "has_spell": True,
                                "source_type": spell.get("source_type"),
                                "source_name": spell.get("source_name"),
                                "charges_required": spell.get("charges_required"),
                                "notes": spell.get("notes")
                            }
                            break
                    if not character_access:
                        character_access = {"has_spell": False}

            result = {
                "spell_name": spell_name,
                "source": "D&D 5e API + Campaign Database"
            }

            if spell_data:
                result["spell_data"] = spell_data
                result["found_in_api"] = True
            else:
                result["found_in_api"] = False
                result["message"] = f"Spell '{spell_name}' not found in D&D 5e API"

            if character_access:
                result["character_access"] = character_access
                result["character_name"] = character_name

            return result
        except Exception as e:
            logger.error(f"Error looking up spell: {e}")
            return {"error": str(e), "source": "D&D 5e API + Campaign Database"}

    # =========================================================================
    # UTILITY TOOLS
    # =========================================================================

    @app.tool()
    def campaign_health_check() -> Dict[str, Any]:
        """Check the health of the campaign database connection.

        Returns:
            Connection status and basic stats.
        """
        logger.debug("Checking campaign database health")

        try:
            health = supabase_client.health_check()

            return {
                "status": health.get("status", "unknown"),
                "connected": health.get("connected", False),
                "message": "Campaign database is healthy" if health.get("connected") else "Database connection failed",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error checking campaign health: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def create_inventory_snapshot(note: str = None) -> Dict[str, Any]:
        """Create a complete snapshot of all inventory, currency, and ledgers.

        Saves a JSON file to the snapshots directory with full inventory state.
        Use this to create historical records before major changes.

        Args:
            note: Optional note to include in the snapshot (e.g., "Before dragon fight")

        Returns:
            Snapshot summary and file path.
        """
        import json
        import os

        logger.debug("Creating inventory snapshot")

        try:
            # Get the snapshot data
            snapshot = supabase_client.create_inventory_snapshot()

            # Add the note if provided
            if note:
                snapshot["note"] = note

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"inventory_snapshot_{timestamp}.json"

            # Get the snapshots directory (relative to the server file)
            snapshots_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "snapshots")
            os.makedirs(snapshots_dir, exist_ok=True)

            filepath = os.path.join(snapshots_dir, filename)

            # Write the snapshot
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, indent=2, default=str)

            # Build summary
            totals = snapshot.get("totals", {})
            summary_lines = [
                "# Inventory Snapshot Created",
                "",
                f"**File:** `{filename}`",
                f"**Timestamp:** {snapshot.get('snapshot_timestamp', 'Unknown')}",
            ]

            if note:
                summary_lines.append(f"**Note:** {note}")

            summary_lines.extend([
                "",
                "## Summary",
                f"- **Total Items:** {totals.get('total_items', 0)}",
                f"- **Magic Items:** {totals.get('magic_items', 0)}",
                f"- **Storage Locations:** {totals.get('total_locations', 0)}",
                f"- **Inventory Transactions:** {totals.get('inventory_transactions', 0)}",
                f"- **Currency Transactions:** {totals.get('currency_transactions', 0)}",
            ])

            wealth = totals.get("wealth", {})
            if wealth:
                summary_lines.extend([
                    "",
                    "## Total Wealth",
                    f"- **Gold Value:** {wealth.get('total_gp_value', 0):,.2f} gp",
                ])

            return {
                "filename": filename,
                "filepath": filepath,
                "timestamp": snapshot.get("snapshot_timestamp"),
                "totals": totals,
                "content": "\n".join(summary_lines),
                "message": f"Snapshot saved to {filename}",
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error creating snapshot: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    @app.tool()
    def list_inventory_snapshots() -> Dict[str, Any]:
        """List all available inventory snapshots.

        Returns:
            List of snapshot files with timestamps.
        """
        import os

        logger.debug("Listing inventory snapshots")

        try:
            snapshots_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "snapshots")

            if not os.path.exists(snapshots_dir):
                return {
                    "snapshots": [],
                    "count": 0,
                    "content": "No snapshots directory found.",
                    "source": "Campaign Database"
                }

            files = []
            for f in os.listdir(snapshots_dir):
                if f.endswith('.json') and f.startswith('inventory_snapshot_'):
                    filepath = os.path.join(snapshots_dir, f)
                    stat = os.stat(filepath)
                    files.append({
                        "filename": f,
                        "size_kb": round(stat.st_size / 1024, 2),
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })

            # Sort by modified date descending
            files.sort(key=lambda x: x["modified"], reverse=True)

            # Format output
            lines = ["# Inventory Snapshots", ""]
            if files:
                lines.append("| Filename | Size | Created |")
                lines.append("|----------|------|---------|")
                for f in files:
                    lines.append(f"| {f['filename']} | {f['size_kb']} KB | {f['modified']} |")
            else:
                lines.append("*No snapshots found.*")

            return {
                "snapshots": files,
                "count": len(files),
                "content": "\n".join(lines),
                "source": "Campaign Database"
            }
        except Exception as e:
            logger.error(f"Error listing snapshots: {e}")
            return {"error": str(e), "source": "Campaign Database"}

    print("Campaign tools registered successfully", file=sys.stderr)
