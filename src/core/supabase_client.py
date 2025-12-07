"""
Supabase client for campaign database access.
Provides full CRUD operations with caching support.

Follows patterns from api_helpers.py and cache.py.
"""

import requests
import hashlib
import os
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

# Import cache - will be injected at initialization
# from src.core.cache import APICache


class SupabaseClient:
    """
    Client for Supabase PostgREST API.

    Provides:
    - GET operations with caching
    - POST/PATCH/DELETE operations (no caching, invalidates related cache)
    - Convenience methods for common queries
    - Full CRUD for all campaign tables
    """

    def __init__(self,
                 api_url: str,
                 api_key: str,
                 cache: Any,  # APICache instance
                 cache_prefix: str = "campaign",
                 timeout: int = 10):
        """
        Initialize the Supabase client.

        Args:
            api_url: Supabase REST API URL (e.g., https://xxx.supabase.co/rest/v1)
            api_key: Supabase API key (anon or service_role)
            cache: APICache instance for caching responses
            cache_prefix: Prefix for cache keys
            timeout: Request timeout in seconds
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.cache = cache
        self.cache_prefix = cache_prefix
        self.timeout = timeout
        self.headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"  # Return data on insert/update
        }

    # =========================================================================
    # CACHE HELPERS
    # =========================================================================

    def _cache_key(self, table: str, query_hash: str = "") -> str:
        """Generate a cache key for a query."""
        return f"{self.cache_prefix}_{table}_{query_hash}"

    def _hash_query(self, params: Dict) -> str:
        """Create a hash of query parameters for cache key."""
        param_str = str(sorted(params.items()))
        return hashlib.md5(param_str.encode()).hexdigest()[:12]

    def invalidate_table_cache(self, table: str):
        """
        Invalidate all cache entries for a table.
        Called after write operations.
        """
        # Clear all cache entries starting with this table's prefix
        prefix = f"{self.cache_prefix}_{table}_"
        if hasattr(self.cache, 'clear_prefix'):
            self.cache.clear_prefix(prefix)
        else:
            # Fallback: clear entire cache (less efficient but works)
            # In practice, we'll enhance the cache class to support prefix clearing
            pass

    def invalidate_related_caches(self, table: str):
        """
        Invalidate caches for related tables/views.
        E.g., updating inventory_current should also invalidate v_inventory.
        """
        related = {
            "inventory_current": ["v_inventory", "inventory_ledger"],
            "inventory_ledger": ["v_inventory_history"],
            "currency_current": ["v_currency_by_location", "v_total_wealth"],
            "currency_ledger": ["v_currency_history"],
            "characters": ["v_characters", "character_spells", "character_feats",
                          "character_forms", "character_companions"],
            "character_spells": ["v_character_spells"],
            "character_feats": ["v_character_feats"],
            "character_forms": ["v_character_forms"],
            "character_companions": ["v_character_companions"],
            "storage_locations": ["v_inventory", "v_currency_by_location"],
            "diary_entries": [],
        }

        tables_to_invalidate = [table] + related.get(table, [])
        for t in tables_to_invalidate:
            self.invalidate_table_cache(t)

    # =========================================================================
    # CORE HTTP METHODS
    # =========================================================================

    def get(self,
            table: str,
            select: str = "*",
            filters: Dict[str, str] = None,
            order: str = None,
            limit: int = None,
            offset: int = None,
            use_cache: bool = True) -> List[Dict]:
        """
        Fetch data from a Supabase table or view.

        Args:
            table: Table or view name (e.g., "characters", "v_inventory")
            select: Columns to select (PostgREST syntax, default "*")
            filters: Filter conditions as {"column": "operator.value"}
                     e.g., {"name": "eq.Nico Olaf", "level": "gte.10"}
            order: Order clause (e.g., "name.asc", "created_at.desc")
            limit: Maximum rows to return
            offset: Number of rows to skip
            use_cache: Whether to use/update cache (default True)

        Returns:
            List of matching rows as dictionaries
        """
        # Build query parameters
        params = {"select": select}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        if offset:
            params["offset"] = str(offset)

        # Check cache
        cache_key = self._cache_key(table, self._hash_query(params))
        if use_cache and self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached

        # Build URL with query string
        query_parts = [f"{k}={v}" for k, v in params.items()]
        url = f"{self.api_url}/{table}?{'&'.join(query_parts)}"

        # Make request
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()

        # Cache result
        if use_cache and self.cache:
            self.cache.set(cache_key, data)

        return data

    def get_by_id(self, table: str, id: str, use_cache: bool = True) -> Optional[Dict]:
        """
        Fetch a single row by UUID.

        Args:
            table: Table name
            id: UUID of the row
            use_cache: Whether to use cache

        Returns:
            Row as dictionary, or None if not found
        """
        results = self.get(table, filters={"id": f"eq.{id}"}, use_cache=use_cache)
        return results[0] if results else None

    def insert(self, table: str, data: Union[Dict, List[Dict]]) -> List[Dict]:
        """
        Insert one or more rows into a table.

        Args:
            table: Table name
            data: Single row dict or list of row dicts

        Returns:
            List of inserted rows (with generated IDs, timestamps, etc.)
        """
        url = f"{self.api_url}/{table}"

        # Ensure data is a list
        if isinstance(data, dict):
            data = [data]

        response = requests.post(url, headers=self.headers, json=data, timeout=self.timeout)
        response.raise_for_status()

        # Invalidate related caches
        self.invalidate_related_caches(table)

        return response.json()

    def update(self,
               table: str,
               data: Dict,
               filters: Dict[str, str]) -> List[Dict]:
        """
        Update rows matching filters.

        Args:
            table: Table name
            data: Fields to update
            filters: Filter conditions to match rows

        Returns:
            List of updated rows
        """
        # Build URL with filters
        filter_parts = [f"{k}={v}" for k, v in filters.items()]
        url = f"{self.api_url}/{table}?{'&'.join(filter_parts)}"

        response = requests.patch(url, headers=self.headers, json=data, timeout=self.timeout)
        response.raise_for_status()

        # Invalidate related caches
        self.invalidate_related_caches(table)

        return response.json()

    def update_by_id(self, table: str, id: str, data: Dict) -> Optional[Dict]:
        """
        Update a single row by UUID.

        Args:
            table: Table name
            id: UUID of the row
            data: Fields to update

        Returns:
            Updated row, or None if not found
        """
        results = self.update(table, data, {"id": f"eq.{id}"})
        return results[0] if results else None

    def delete(self, table: str, filters: Dict[str, str]) -> List[Dict]:
        """
        Delete rows matching filters.

        Args:
            table: Table name
            filters: Filter conditions to match rows

        Returns:
            List of deleted rows
        """
        # Build URL with filters
        filter_parts = [f"{k}={v}" for k, v in filters.items()]
        url = f"{self.api_url}/{table}?{'&'.join(filter_parts)}"

        response = requests.delete(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()

        # Invalidate related caches
        self.invalidate_related_caches(table)

        return response.json()

    def delete_by_id(self, table: str, id: str) -> Optional[Dict]:
        """
        Delete a single row by UUID.

        Args:
            table: Table name
            id: UUID of the row

        Returns:
            Deleted row, or None if not found
        """
        results = self.delete(table, {"id": f"eq.{id}"})
        return results[0] if results else None

    # =========================================================================
    # CHARACTER OPERATIONS
    # =========================================================================

    def get_characters(self, party_id: str = None) -> List[Dict]:
        """Get all characters, optionally filtered by party."""
        filters = {"party_id": f"eq.{party_id}"} if party_id else None
        return self.get("v_characters", filters=filters, order="name")

    def get_character(self, character_id: str) -> Optional[Dict]:
        """Get a single character by ID."""
        return self.get_by_id("characters", character_id)

    def get_character_by_name(self, name: str) -> Optional[Dict]:
        """Get a character by name (case-insensitive)."""
        results = self.get("characters", filters={"name": f"ilike.{name}"})
        return results[0] if results else None

    def update_character(self, character_id: str, data: Dict) -> Optional[Dict]:
        """Update character fields."""
        return self.update_by_id("characters", character_id, data)

    def update_character_json(self, character_id: str, json_updates: Dict) -> Optional[Dict]:
        """
        Update specific fields in character's dndbeyond_json.
        Merges with existing JSON data.
        """
        char = self.get_character(character_id)
        if not char:
            return None

        current_json = char.get('dndbeyond_json', {}) or {}
        # Deep merge would be better, but shallow merge works for top-level updates
        updated_json = {**current_json, **json_updates}

        return self.update_by_id("characters", character_id, {"dndbeyond_json": updated_json})

    # =========================================================================
    # CHARACTER SPELLS
    # =========================================================================

    def get_character_spells(self, character_id: str, source_type: str = None) -> List[Dict]:
        """Get spells for a character, optionally filtered by source type."""
        filters = {"character_id": f"eq.{character_id}"}
        if source_type:
            filters["source_type"] = f"eq.{source_type}"
        return self.get("v_character_spells", filters=filters,
                       order="source_type,spell_level,spell_name")

    def add_character_spell(self,
                           character_id: str,
                           spell_name: str,
                           spell_level: int,
                           source_type: str,
                           source_name: str,
                           charges_required: int = None,
                           notes: str = None) -> Dict:
        """Add a spell to a character's spell list."""
        data = {
            "character_id": character_id,
            "spell_name": spell_name,
            "spell_level": spell_level,
            "source_type": source_type,
            "source_name": source_name
        }
        if charges_required is not None:
            data["charges_required"] = charges_required
        if notes:
            data["notes"] = notes

        results = self.insert("character_spells", data)
        return results[0] if results else None

    def remove_character_spell(self, character_id: str, spell_name: str) -> bool:
        """Remove a spell from a character."""
        results = self.delete("character_spells", {
            "character_id": f"eq.{character_id}",
            "spell_name": f"eq.{spell_name}"
        })
        return len(results) > 0

    # =========================================================================
    # CHARACTER FEATS
    # =========================================================================

    def get_character_feats(self, character_id: str) -> List[Dict]:
        """Get feats for a character."""
        return self.get("v_character_feats",
                       filters={"character_id": f"eq.{character_id}"},
                       order="feat_name")

    def add_character_feat(self,
                          character_id: str,
                          feat_name: str,
                          description: str = None,
                          benefits: Dict = None) -> Dict:
        """Add a feat to a character."""
        data = {
            "character_id": character_id,
            "feat_name": feat_name
        }
        if description:
            data["description"] = description
        if benefits:
            data["benefits"] = benefits

        results = self.insert("character_feats", data)
        return results[0] if results else None

    def remove_character_feat(self, character_id: str, feat_name: str) -> bool:
        """Remove a feat from a character."""
        results = self.delete("character_feats", {
            "character_id": f"eq.{character_id}",
            "feat_name": f"eq.{feat_name}"
        })
        return len(results) > 0

    # =========================================================================
    # CHARACTER FORMS
    # =========================================================================

    def get_character_forms(self, character_id: str) -> List[Dict]:
        """Get transformation forms for a character."""
        return self.get("v_character_forms",
                       filters={"character_id": f"eq.{character_id}"},
                       order="form_name")

    def add_character_form(self,
                          character_id: str,
                          form_name: str,
                          form_type: str,
                          creature_type: str = None,
                          challenge_rating: str = None,
                          source_spell: str = None,
                          notes: str = None,
                          stats: Dict = None) -> Dict:
        """Add a transformation form to a character."""
        data = {
            "character_id": character_id,
            "form_name": form_name,
            "form_type": form_type
        }
        if creature_type:
            data["creature_type"] = creature_type
        if challenge_rating:
            data["challenge_rating"] = challenge_rating
        if source_spell:
            data["source_spell"] = source_spell
        if notes:
            data["notes"] = notes
        if stats:
            data["stats"] = stats

        results = self.insert("character_forms", data)
        return results[0] if results else None

    def remove_character_form(self, character_id: str, form_name: str) -> bool:
        """Remove a form from a character."""
        results = self.delete("character_forms", {
            "character_id": f"eq.{character_id}",
            "form_name": f"eq.{form_name}"
        })
        return len(results) > 0

    # =========================================================================
    # CHARACTER COMPANIONS
    # =========================================================================

    def get_character_companions(self, character_id: str) -> List[Dict]:
        """Get companions for a character."""
        return self.get("v_character_companions",
                       filters={"character_id": f"eq.{character_id}"},
                       order="companion_name")

    def add_character_companion(self,
                               character_id: str,
                               companion_name: str,
                               creature_type: str,
                               companion_type: str,
                               challenge_rating: str = None,
                               hit_points_max: int = None,
                               armor_class: int = None,
                               notes: str = None,
                               stats: Dict = None) -> Dict:
        """Add a companion to a character."""
        data = {
            "character_id": character_id,
            "companion_name": companion_name,
            "creature_type": creature_type,
            "companion_type": companion_type
        }
        if challenge_rating:
            data["challenge_rating"] = challenge_rating
        if hit_points_max:
            data["hit_points_max"] = hit_points_max
            data["hit_points_current"] = hit_points_max  # Start at max
        if armor_class:
            data["armor_class"] = armor_class
        if notes:
            data["notes"] = notes
        if stats:
            data["stats"] = stats

        results = self.insert("character_companions", data)
        return results[0] if results else None

    def update_companion_hp(self, companion_id: str, current_hp: int) -> Optional[Dict]:
        """Update a companion's current HP."""
        return self.update_by_id("character_companions", companion_id,
                                {"hit_points_current": current_hp})

    def remove_character_companion(self, character_id: str, companion_name: str) -> bool:
        """Remove a companion from a character."""
        results = self.delete("character_companions", {
            "character_id": f"eq.{character_id}",
            "companion_name": f"eq.{companion_name}"
        })
        return len(results) > 0

    # =========================================================================
    # STORAGE LOCATIONS
    # =========================================================================

    def get_storage_locations(self, party_id: str = None) -> List[Dict]:
        """Get all storage locations."""
        filters = {"party_id": f"eq.{party_id}"} if party_id else None
        return self.get("storage_locations", filters=filters, order="name")

    def get_storage_location(self, location_id: str) -> Optional[Dict]:
        """Get a storage location by ID."""
        return self.get_by_id("storage_locations", location_id)

    def get_storage_location_by_name(self, name: str) -> Optional[Dict]:
        """Get a storage location by name (case-insensitive)."""
        results = self.get("storage_locations", filters={"name": f"ilike.{name}"})
        return results[0] if results else None

    # =========================================================================
    # INVENTORY OPERATIONS
    # =========================================================================

    def get_inventory(self, location_name: str = None, location_id: str = None) -> List[Dict]:
        """Get inventory items, optionally filtered by location."""
        filters = {}
        if location_name:
            filters["location_name"] = f"eq.{location_name}"
        if location_id:
            filters["storage_location_id"] = f"eq.{location_id}"
        return self.get("v_inventory", filters=filters or None, order="item_type,item_name")

    def search_inventory(self, query: str) -> List[Dict]:
        """Search inventory by item name (case-insensitive)."""
        return self.get("v_inventory",
                       filters={"item_name": f"ilike.*{query}*"},
                       order="item_name")

    def get_magic_items(self, location_id: str = None) -> List[Dict]:
        """Get all magic items, optionally filtered by location."""
        filters = {"is_magic": "eq.true"}
        if location_id:
            filters["storage_location_id"] = f"eq.{location_id}"
        return self.get("v_inventory", filters=filters, order="rarity.desc,item_name")

    def add_item(self,
                storage_location_id: str,
                item_name: str,
                quantity: int = 1,
                is_magic: bool = False,
                rarity: str = None,
                item_type: str = None,
                item_description: str = None,
                requires_attunement: bool = False,
                notes: str = None,
                reason: str = None) -> Dict:
        """
        Add an item to inventory.
        Also creates a ledger entry for tracking.
        """
        # Insert into inventory_current
        item_data = {
            "storage_location_id": storage_location_id,
            "item_name": item_name,
            "quantity": quantity,
            "is_magic": is_magic
        }
        if rarity:
            item_data["rarity"] = rarity
        if item_type:
            item_data["item_type"] = item_type
        if item_description:
            item_data["item_description"] = item_description
        if requires_attunement:
            item_data["requires_attunement"] = requires_attunement
        if notes:
            item_data["notes"] = notes

        result = self.insert("inventory_current", item_data)

        # Create ledger entry
        ledger_data = {
            "storage_location_id": storage_location_id,
            "transaction_type": "add",
            "item_name": item_name,
            "quantity": quantity,
            "is_magic": is_magic,
            "rarity": rarity,
            "item_type": item_type,
            "reason": reason or "Added to inventory"
        }
        self.insert("inventory_ledger", ledger_data)

        return result[0] if result else None

    def remove_item(self,
                   storage_location_id: str,
                   item_name: str,
                   quantity: int = None,
                   reason: str = None) -> Optional[Dict]:
        """
        Remove an item from inventory (reduce quantity or delete).
        Creates a ledger entry for tracking.
        """
        # Get current item
        items = self.get("inventory_current", filters={
            "storage_location_id": f"eq.{storage_location_id}",
            "item_name": f"eq.{item_name}"
        })

        if not items:
            return None

        item = items[0]
        current_qty = item.get("quantity", 1)
        remove_qty = quantity if quantity else current_qty

        # Create ledger entry
        ledger_data = {
            "storage_location_id": storage_location_id,
            "transaction_type": "remove",
            "item_name": item_name,
            "quantity": remove_qty,
            "is_magic": item.get("is_magic", False),
            "rarity": item.get("rarity"),
            "item_type": item.get("item_type"),
            "reason": reason or "Removed from inventory"
        }
        self.insert("inventory_ledger", ledger_data)

        if remove_qty >= current_qty:
            # Delete the item entirely
            self.delete("inventory_current", {"id": f"eq.{item['id']}"})
            return {"deleted": True, "item": item}
        else:
            # Reduce quantity
            new_qty = current_qty - remove_qty
            updated = self.update_by_id("inventory_current", item['id'], {"quantity": new_qty})
            return updated

    def update_item_quantity(self,
                            storage_location_id: str,
                            item_name: str,
                            new_quantity: int,
                            reason: str = None) -> Optional[Dict]:
        """Update an item's quantity directly."""
        items = self.get("inventory_current", filters={
            "storage_location_id": f"eq.{storage_location_id}",
            "item_name": f"eq.{item_name}"
        })

        if not items:
            return None

        item = items[0]
        old_qty = item.get("quantity", 1)
        diff = new_quantity - old_qty

        # Create ledger entry
        ledger_data = {
            "storage_location_id": storage_location_id,
            "transaction_type": "add" if diff > 0 else "remove",
            "item_name": item_name,
            "quantity": abs(diff),
            "is_magic": item.get("is_magic", False),
            "rarity": item.get("rarity"),
            "item_type": item.get("item_type"),
            "reason": reason or f"Quantity adjusted from {old_qty} to {new_quantity}"
        }
        self.insert("inventory_ledger", ledger_data)

        return self.update_by_id("inventory_current", item['id'], {"quantity": new_quantity})

    def transfer_item(self,
                     from_location_id: str,
                     to_location_id: str,
                     item_name: str,
                     quantity: int = None,
                     reason: str = None) -> Dict:
        """
        Transfer an item between storage locations.
        Creates linked ledger entries in both locations.
        """
        # Get source item
        source_items = self.get("inventory_current", filters={
            "storage_location_id": f"eq.{from_location_id}",
            "item_name": f"eq.{item_name}"
        })

        if not source_items:
            return {"error": f"Item '{item_name}' not found in source location"}

        source_item = source_items[0]
        transfer_qty = quantity if quantity else source_item.get("quantity", 1)

        if transfer_qty > source_item.get("quantity", 1):
            return {"error": f"Cannot transfer {transfer_qty}, only {source_item['quantity']} available"}

        # Create ledger entries
        transfer_out = {
            "storage_location_id": from_location_id,
            "transaction_type": "transfer_out",
            "item_name": item_name,
            "quantity": transfer_qty,
            "is_magic": source_item.get("is_magic", False),
            "rarity": source_item.get("rarity"),
            "item_type": source_item.get("item_type"),
            "transfer_location_id": to_location_id,
            "reason": reason or "Transferred to another location"
        }
        self.insert("inventory_ledger", transfer_out)

        transfer_in = {
            "storage_location_id": to_location_id,
            "transaction_type": "transfer_in",
            "item_name": item_name,
            "quantity": transfer_qty,
            "is_magic": source_item.get("is_magic", False),
            "rarity": source_item.get("rarity"),
            "item_type": source_item.get("item_type"),
            "transfer_location_id": from_location_id,
            "reason": reason or "Transferred from another location"
        }
        self.insert("inventory_ledger", transfer_in)

        # Update source inventory
        remaining = source_item["quantity"] - transfer_qty
        if remaining <= 0:
            self.delete_by_id("inventory_current", source_item["id"])
        else:
            self.update_by_id("inventory_current", source_item["id"], {"quantity": remaining})

        # Update or create destination inventory
        dest_items = self.get("inventory_current", filters={
            "storage_location_id": f"eq.{to_location_id}",
            "item_name": f"eq.{item_name}"
        })

        if dest_items:
            # Add to existing
            new_qty = dest_items[0]["quantity"] + transfer_qty
            self.update_by_id("inventory_current", dest_items[0]["id"], {"quantity": new_qty})
        else:
            # Create new entry
            new_item = {
                "storage_location_id": to_location_id,
                "item_name": item_name,
                "quantity": transfer_qty,
                "is_magic": source_item.get("is_magic", False),
                "rarity": source_item.get("rarity"),
                "item_type": source_item.get("item_type"),
                "item_description": source_item.get("item_description"),
                "requires_attunement": source_item.get("requires_attunement", False),
                "notes": source_item.get("notes")
            }
            self.insert("inventory_current", new_item)

        return {"success": True, "transferred": transfer_qty, "item": item_name}

    # =========================================================================
    # CURRENCY OPERATIONS
    # =========================================================================

    def get_currency(self, location_name: str = None, location_id: str = None) -> List[Dict]:
        """Get currency by location."""
        filters = {}
        if location_name:
            filters["location_name"] = f"eq.{location_name}"
        if location_id:
            filters["storage_location_id"] = f"eq.{location_id}"
        return self.get("v_currency_by_location", filters=filters or None, order="location_name")

    def get_total_wealth(self, party_id: str = None) -> Dict:
        """Get party's total wealth."""
        filters = {"party_id": f"eq.{party_id}"} if party_id else None
        results = self.get("v_total_wealth", filters=filters)
        return results[0] if results else {}

    def add_currency(self,
                    storage_location_id: str,
                    copper: int = 0,
                    silver: int = 0,
                    electrum: int = 0,
                    gold: int = 0,
                    platinum: int = 0,
                    reason: str = None) -> Dict:
        """
        Add currency to a location.
        Updates current balance and creates ledger entry.
        """
        # Get current balance
        current = self.get("currency_current",
                          filters={"storage_location_id": f"eq.{storage_location_id}"})

        if current:
            # Update existing
            new_balance = {
                "copper": current[0].get("copper", 0) + copper,
                "silver": current[0].get("silver", 0) + silver,
                "electrum": current[0].get("electrum", 0) + electrum,
                "gold": current[0].get("gold", 0) + gold,
                "platinum": current[0].get("platinum", 0) + platinum
            }
            self.update_by_id("currency_current", current[0]["id"], new_balance)
        else:
            # Create new entry
            new_balance = {
                "storage_location_id": storage_location_id,
                "copper": copper,
                "silver": silver,
                "electrum": electrum,
                "gold": gold,
                "platinum": platinum
            }
            self.insert("currency_current", new_balance)

        # Create ledger entry
        ledger_data = {
            "storage_location_id": storage_location_id,
            "transaction_type": "add",
            "copper": copper,
            "silver": silver,
            "electrum": electrum,
            "gold": gold,
            "platinum": platinum,
            "reason": reason or "Currency added"
        }
        self.insert("currency_ledger", ledger_data)

        return self.get("currency_current",
                       filters={"storage_location_id": f"eq.{storage_location_id}"})[0]

    def remove_currency(self,
                       storage_location_id: str,
                       copper: int = 0,
                       silver: int = 0,
                       electrum: int = 0,
                       gold: int = 0,
                       platinum: int = 0,
                       reason: str = None) -> Dict:
        """
        Remove currency from a location.
        Updates current balance and creates ledger entry.
        """
        # Get current balance
        current = self.get("currency_current",
                          filters={"storage_location_id": f"eq.{storage_location_id}"})

        if not current:
            return {"error": "No currency record found for this location"}

        # Calculate new balance (don't go negative)
        new_balance = {
            "copper": max(0, current[0].get("copper", 0) - copper),
            "silver": max(0, current[0].get("silver", 0) - silver),
            "electrum": max(0, current[0].get("electrum", 0) - electrum),
            "gold": max(0, current[0].get("gold", 0) - gold),
            "platinum": max(0, current[0].get("platinum", 0) - platinum)
        }
        self.update_by_id("currency_current", current[0]["id"], new_balance)

        # Create ledger entry
        ledger_data = {
            "storage_location_id": storage_location_id,
            "transaction_type": "remove",
            "copper": copper,
            "silver": silver,
            "electrum": electrum,
            "gold": gold,
            "platinum": platinum,
            "reason": reason or "Currency removed"
        }
        self.insert("currency_ledger", ledger_data)

        return self.get("currency_current",
                       filters={"storage_location_id": f"eq.{storage_location_id}"})[0]

    def transfer_currency(self,
                         from_location_id: str,
                         to_location_id: str,
                         copper: int = 0,
                         silver: int = 0,
                         electrum: int = 0,
                         gold: int = 0,
                         platinum: int = 0,
                         reason: str = None) -> Dict:
        """Transfer currency between locations."""
        # Remove from source
        self.remove_currency(from_location_id, copper, silver, electrum, gold, platinum,
                            reason=f"Transfer to another location: {reason or ''}")

        # Add to destination
        self.add_currency(to_location_id, copper, silver, electrum, gold, platinum,
                         reason=f"Transfer from another location: {reason or ''}")

        return {"success": True, "transferred": {"cp": copper, "sp": silver,
                                                  "ep": electrum, "gp": gold, "pp": platinum}}

    # =========================================================================
    # DIARY ENTRIES
    # =========================================================================

    def get_diary_entries(self,
                         party_id: str = None,
                         limit: int = None,
                         month_year: str = None) -> List[Dict]:
        """Get diary entries, optionally filtered."""
        filters = {}
        if party_id:
            filters["party_id"] = f"eq.{party_id}"
        if month_year:
            filters["month_year"] = f"eq.{month_year}"
        return self.get("diary_entries",
                       filters=filters or None,
                       order="session_date.desc,entry_order.desc",
                       limit=limit)

    def get_diary_entry(self, entry_id: str) -> Optional[Dict]:
        """Get a single diary entry by ID."""
        return self.get_by_id("diary_entries", entry_id)

    def add_diary_entry(self,
                       party_id: str,
                       content: str,
                       title: str = None,
                       session_date: str = None,
                       month_year: str = None,
                       in_game_date: str = None,
                       locations_visited: List[str] = None,
                       npcs_encountered: List[str] = None,
                       quests_updated: List[str] = None,
                       loot_summary: Dict = None) -> Dict:
        """Add a new diary entry."""
        data = {
            "party_id": party_id,
            "content": content
        }
        if title:
            data["title"] = title
        if session_date:
            data["session_date"] = session_date
        if month_year:
            data["month_year"] = month_year
        if in_game_date:
            data["in_game_date"] = in_game_date
        if locations_visited:
            data["locations_visited"] = locations_visited
        if npcs_encountered:
            data["npcs_encountered"] = npcs_encountered
        if quests_updated:
            data["quests_updated"] = quests_updated
        if loot_summary:
            data["loot_summary"] = loot_summary

        results = self.insert("diary_entries", data)
        return results[0] if results else None

    def update_diary_entry(self, entry_id: str, data: Dict) -> Optional[Dict]:
        """Update a diary entry."""
        return self.update_by_id("diary_entries", entry_id, data)

    def delete_diary_entry(self, entry_id: str) -> bool:
        """Delete a diary entry."""
        result = self.delete_by_id("diary_entries", entry_id)
        return result is not None

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    def health_check(self) -> Dict:
        """Check if the Supabase connection is working."""
        try:
            # Try to fetch parties (should always exist)
            parties = self.get("parties", limit=1, use_cache=False)
            return {
                "status": "healthy",
                "connected": True,
                "party_found": len(parties) > 0
            }
        except Exception as e:
            return {
                "status": "error",
                "connected": False,
                "error": str(e)
            }

    def clear_all_cache(self):
        """Clear all campaign-related cache entries."""
        if self.cache:
            self.cache.clear()

    def create_inventory_snapshot(self) -> Dict:
        """
        Create a complete snapshot of all inventory and currency data.

        Returns a dictionary containing:
        - All inventory items by location
        - All currency by location
        - Complete inventory ledger history
        - Complete currency ledger history
        - Character information
        - Storage locations
        - Snapshot metadata (timestamp, totals)
        """
        snapshot = {
            "snapshot_timestamp": datetime.now().isoformat(),
            "snapshot_type": "full_inventory",
            "party": None,
            "characters": [],
            "storage_locations": [],
            "inventory_by_location": {},
            "currency_by_location": {},
            "inventory_ledger": [],
            "currency_ledger": [],
            "totals": {}
        }

        try:
            # Get party info
            parties = self.get("parties", limit=1, use_cache=False)
            if parties:
                snapshot["party"] = parties[0]

            # Get all characters
            characters = self.get("v_characters", use_cache=False)
            snapshot["characters"] = characters

            # Get all storage locations
            locations = self.get("storage_locations", order="name", use_cache=False)
            snapshot["storage_locations"] = locations

            # Get inventory for each location
            all_inventory = self.get("v_inventory", order="location_name,item_name", use_cache=False)

            # Group inventory by location
            for item in all_inventory:
                loc_name = item.get("location_name", "Unknown")
                if loc_name not in snapshot["inventory_by_location"]:
                    snapshot["inventory_by_location"][loc_name] = []
                snapshot["inventory_by_location"][loc_name].append(item)

            # Get currency for each location
            all_currency = self.get("v_currency_by_location", use_cache=False)
            for curr in all_currency:
                loc_name = curr.get("location_name", "Unknown")
                snapshot["currency_by_location"][loc_name] = curr

            # Get total wealth
            total_wealth = self.get("v_total_wealth", use_cache=False)
            if total_wealth:
                snapshot["totals"]["wealth"] = total_wealth[0]

            # Get complete inventory ledger
            inventory_ledger = self.get("inventory_ledger",
                                        order="created_at.desc",
                                        use_cache=False)
            snapshot["inventory_ledger"] = inventory_ledger

            # Get complete currency ledger
            currency_ledger = self.get("currency_ledger",
                                       order="created_at.desc",
                                       use_cache=False)
            snapshot["currency_ledger"] = currency_ledger

            # Calculate totals
            snapshot["totals"]["total_items"] = len(all_inventory)
            snapshot["totals"]["total_locations"] = len(locations)
            snapshot["totals"]["inventory_transactions"] = len(inventory_ledger)
            snapshot["totals"]["currency_transactions"] = len(currency_ledger)

            # Count magic items
            magic_items = [i for i in all_inventory if i.get("is_magic")]
            snapshot["totals"]["magic_items"] = len(magic_items)

        except Exception as e:
            snapshot["error"] = str(e)

        return snapshot
