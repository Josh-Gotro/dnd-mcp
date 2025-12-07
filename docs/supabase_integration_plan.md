# Supabase Integration Plan - COMPLETED

## Overview

This document outlines the integration of the Brutte Squadde campaign database (Supabase) with the existing D&D 5e MCP server. The integration follows existing patterns for caching, attribution, and tool registration.

**Status: IMPLEMENTED**

---

## Current Architecture Summary

The dnd-mcp server currently:

1. **Fetches data** from the D&D 5e API (`https://www.dnd5eapi.co/api`)
2. **Caches responses** using `APICache` (TTL-based, persistent to disk)
3. **Tracks attribution** via `SourceAttribution` and `AttributionManager`
4. **Enhances queries** with synonyms, fuzzy matching, and category prioritization
5. **Formats responses** using type-specific templates (monster, spell, equipment)
6. **Registers tools** via FastMCP `@app.tool()` decorator

---

## Integration Goals (ACHIEVED)

| Goal | Status |
|------|--------|
| **Seamless UX** | ✅ Users query campaign data the same way they query D&D 5e data |
| **Unified Caching** | ✅ Supabase data uses the same cache system with cache invalidation |
| **Source Attribution** | ✅ Clear distinction between "D&D 5e API" and "Campaign Database" |
| **Smart Search** | ✅ Query enhancement recognizes campaign-specific terms |
| **Consistent Formatting** | ✅ Character cards, inventory lists match existing template style |
| **Full CRUD** | ✅ Add, update, delete operations for all campaign data |

---

## Files Created

### 1. `src/core/supabase_client.py` (IMPLEMENTED)

Full Supabase PostgREST client with:
- GET operations with caching
- POST/PATCH/DELETE operations with cache invalidation
- Related table cache invalidation (e.g., updating inventory invalidates v_inventory)
- Convenience methods for all campaign operations

**Key Features:**
- Character CRUD: `get_characters`, `update_character`, `update_character_json`
- Spell management: `add_character_spell`, `remove_character_spell`
- Feat management: `add_character_feat`, `remove_character_feat`
- Form management: `add_character_form`, `remove_character_form`
- Companion management: `add_character_companion`, `update_companion_hp`
- Inventory CRUD with ledger: `add_item`, `remove_item`, `transfer_item`
- Currency CRUD with ledger: `add_currency`, `remove_currency`, `transfer_currency`
- Diary CRUD: `add_diary_entry`, `update_diary_entry`, `delete_diary_entry`

---

### 2. `src/templates/campaign.py` (IMPLEMENTED)

Templates for formatting campaign data:

- `format_character_card` - Full character sheet display
- `format_character_list` - Party roster table
- `format_character_spells` - Spells grouped by source and level
- `format_character_feats` - Feats with benefits
- `format_character_forms` - Transformation forms (Wild Shape, Polymorph, etc.)
- `format_character_companions` - Familiars and animal companions
- `format_inventory_list` - Items grouped by type
- `format_inventory_search_results` - Search results with locations
- `format_currency_by_location` - Currency table by storage location
- `format_wealth_summary` - Total party wealth
- `format_storage_locations` - All storage locations
- `format_diary_entry` - Single diary entry
- `format_diary_list` - Diary entries grouped by month
- `format_currency_transaction` - Transaction result
- `format_inventory_transaction` - Inventory change result

---

### 3. `src/core/tools.py` - Campaign Tools (IMPLEMENTED)

Added `register_campaign_tools()` function with 30+ tools:

#### Character Tools
| Tool | Description |
|------|-------------|
| `get_party_characters` | List all party members |
| `get_character_details` | Full character sheet |
| `get_character_spells` | Spell list by source |
| `get_character_feats` | Character feats |
| `get_character_forms` | Transformation forms |
| `get_character_companions` | Familiars/companions |
| `update_character` | Update level, HP, class |

#### Inventory Tools
| Tool | Description |
|------|-------------|
| `get_inventory` | List items by location |
| `search_inventory` | Search items by name |
| `get_magic_items` | List all magic items |
| `add_item` | Add item with ledger entry |
| `remove_item` | Remove item with ledger entry |
| `transfer_item` | Move item between locations |
| `get_storage_locations` | List all storage locations |

#### Currency Tools
| Tool | Description |
|------|-------------|
| `get_party_wealth` | Total wealth summary |
| `get_currency_by_location` | Currency at each location |
| `add_currency` | Add currency with ledger |
| `remove_currency` | Remove currency with ledger |
| `transfer_currency` | Move currency between locations |

#### Diary Tools
| Tool | Description |
|------|-------------|
| `get_diary_entries` | List recent entries |
| `get_diary_entry` | Single entry by ID |
| `add_diary_entry` | Create new entry |
| `update_diary_entry` | Edit existing entry |
| `delete_diary_entry` | Delete entry |

#### Spell Management Tools
| Tool | Description |
|------|-------------|
| `add_character_spell` | Add spell from any source |
| `remove_character_spell` | Remove spell |
| `lookup_spell` | D&D API + character access check |

#### Utility Tools
| Tool | Description |
|------|-------------|
| `campaign_health_check` | Verify database connection |

---

### 4. `dnd_mcp_server.py` (UPDATED)

Modified to:
1. Import `SupabaseClient`
2. Check for `SUPABASE_URL` and `SUPABASE_KEY` environment variables
3. Initialize Supabase client with shared cache
4. Verify connection with health check
5. Register campaign tools if connected

---

### 5. `src/query_enhancement/category_prioritization.py` (UPDATED)

Added campaign-specific keywords:

```python
"campaign_characters": [
    "character", "party", "party member", "character sheet", "level up",
    "hit points", "hp", "armor class", "ac", "ability scores", "stats",
    "nico", "brutte", "squadde", "companion", "familiar", "animal companion"
],
"campaign_inventory": [
    "inventory", "items", "loot", "treasure", "bag of holding", "storage",
    "equipment", "gear", "what do we have", "where is", "find item",
    "magic items", "potions", "scrolls", "weapons", "armor"
],
"campaign_currency": [
    "gold", "silver", "copper", "platinum", "electrum", "money", "coins",
    "wealth", "currency", "gp", "sp", "cp", "pp", "ep", "how much",
    "treasure", "pay", "buy", "sell", "spend"
],
"campaign_spells": [
    "my spells", "known spells", "spell list", "can i cast", "do i have",
    "staff of power", "cli lyre", "spell access", "item spells"
],
"campaign_diary": [
    "diary", "journal", "session", "session notes", "what happened",
    "last session", "campaign log", "adventure", "quest", "npcs",
    "locations visited", "recap"
]
```

---

## Configuration

### Environment Variables

Required in environment or `.env`:

```env
# D&D 5e API (existing)
DND_API_BASE_URL=https://www.dnd5eapi.co/api

# Supabase Campaign Database (required for campaign tools)
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co/rest/v1
SUPABASE_KEY=your_api_key_here
```

If `SUPABASE_URL` and `SUPABASE_KEY` are not set, the server will start without campaign tools and display a message about the missing configuration.

---

## Tool Categories

### D&D 5e API Tools (Existing)

| Tool | Description |
|------|-------------|
| `search_all_categories` | Search D&D 5e API |
| `verify_with_api` | Verify D&D rules statements |
| `filter_spells_by_level` | Filter spells by level/school |
| `find_monsters_by_challenge_rating` | Filter monsters by CR |
| `generate_treasure_hoard` | Generate random treasure |
| `search_equipment_by_cost` | Find affordable equipment |
| `get_class_starting_equipment` | Starting gear for class |
| `check_api_health` | API status check |

### Campaign Database Tools (New)

30+ tools for full CRUD operations on:
- Characters and character details
- Spells, feats, forms, companions
- Inventory with transaction history
- Currency with transaction history
- Diary entries

---

## Example Usage

### Read Operations

```
"What spells does Nico have?"
→ Uses get_character_spells, returns from Campaign Database

"Show me the party inventory"
→ Uses get_inventory, returns all items

"How much gold do we have?"
→ Uses get_party_wealth, returns wealth summary

"What is Fireball?"
→ Uses D&D 5e API search_all_categories

"Can Nico cast Fireball?"
→ Uses lookup_spell (D&D API + Campaign DB)
```

### Write Operations

```
"Add 100 gold to the Bag of Holding"
→ Uses add_currency with ledger entry

"Move the Staff of Power to Vraath Keep"
→ Uses transfer_item with source/destination ledger entries

"Add a new diary entry for today's session"
→ Uses add_diary_entry

"Remove 3 healing potions from Nico's inventory"
→ Uses remove_item with ledger entry

"Level up Nico to 14"
→ Uses update_character
```

---

## Caching Behavior

### Read Operations
- All GET requests are cached using the shared `APICache`
- Cache key format: `campaign_{table}_{query_hash}`
- Default TTL: 24 hours (same as D&D 5e API data)

### Write Operations
- POST/PATCH/DELETE operations bypass cache
- Automatically invalidate related caches:
  - `inventory_current` → `v_inventory`, `inventory_ledger`
  - `currency_current` → `v_currency_by_location`, `v_total_wealth`
  - `characters` → `v_characters` and all character detail tables
  - etc.

---

## Ledger Tracking

All inventory and currency changes create ledger entries for transaction history:

### Inventory Ledger
- `add` - Item added to inventory
- `remove` - Item removed from inventory
- `transfer_in` - Item received from another location
- `transfer_out` - Item sent to another location

### Currency Ledger
- `add` - Currency added
- `remove` - Currency removed
- Transfer operations create paired add/remove entries

---

## Testing

### Test Each Tool Category

1. **Character Tools**
   - Get party characters
   - Get character details for "Nico Olaf"
   - Get character spells/feats/forms/companions

2. **Inventory Tools**
   - Get inventory for "Bag of Holding"
   - Search for "potion"
   - Add/remove/transfer items

3. **Currency Tools**
   - Get total wealth
   - Get currency by location
   - Add/remove/transfer currency

4. **Diary Tools**
   - Get recent entries
   - Add new entry
   - Update/delete entry

5. **Combined Lookup**
   - Look up "Fireball" for "Nico Olaf"
   - Verify spell access is correctly reported

---

## Future Enhancements

1. **Supabase Realtime** - Subscribe to changes for live cache invalidation
2. **Bulk Operations** - Add multiple items at once
3. **Undo/Rollback** - Reverse recent transactions using ledger
4. **Quest Tracking** - Dedicated quest management tools
5. **NPC Database** - Track encountered NPCs
6. **Session Planning** - Encounter and adventure management

---

## Resolved Questions

1. **Caching TTL:** Using same 24-hour TTL as D&D 5e data. Cache invalidation on writes handles freshness.

2. **Write Operations:** ✅ Fully implemented - add, remove, update, transfer operations with ledger tracking.

3. **Real-time Updates:** Not implemented yet. Cache invalidation on write operations handles most use cases.

4. **Additional Tools:** Implemented comprehensive tool set covering all common operations.

5. **Naming:** Used descriptive names following existing patterns (`get_*`, `add_*`, `remove_*`, `transfer_*`).
