"""
Templates for campaign data formatting.
Formats characters, inventory, currency, spells, and diary entries.

Follows patterns from monster.py, spell.py, equipment.py.
"""

from typing import Dict, Any, List, Optional


# =============================================================================
# CHARACTER FORMATTING
# =============================================================================

def format_character_card(data: Dict[str, Any]) -> str:
    """Format a character as a detailed card."""
    char_name = data.get('name', 'Unknown')
    lines = [
        f"# {char_name}",
        f"*Source: Character Sheet — {char_name}*",
        "",
        f"**Class:** {data.get('class_summary', 'Unknown')}",
        f"**Race:** {data.get('race', 'Unknown')}" +
            (f" ({data.get('subrace')})" if data.get('subrace') else ""),
        f"**Background:** {data.get('background', 'Unknown')}",
        f"**Party:** {data.get('party_name', 'Unknown')}",
        ""
    ]

    json_data = data.get('dndbeyond_json', {}) or {}

    # Ability Scores
    if json_data.get('ability_scores'):
        scores = json_data['ability_scores']
        lines.append("## Ability Scores")
        lines.append("")
        lines.append("| STR | DEX | CON | INT | WIS | CHA |")
        lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|")

        def format_score(key):
            val = scores.get(key, '-')
            if isinstance(val, int):
                mod = (val - 10) // 2
                sign = "+" if mod >= 0 else ""
                return f"{val} ({sign}{mod})"
            return str(val)

        lines.append(f"| {format_score('str')} | {format_score('dex')} | "
                    f"{format_score('con')} | {format_score('int')} | "
                    f"{format_score('wis')} | {format_score('cha')} |")
        lines.append("")

    # Combat Stats
    combat_stats = []
    if json_data.get('armor_class'):
        combat_stats.append(f"**AC:** {json_data['armor_class']}")
    if json_data.get('hit_points'):
        hp = json_data['hit_points']
        current = hp.get('current', hp.get('max', '?'))
        max_hp = hp.get('max', '?')
        combat_stats.append(f"**HP:** {current}/{max_hp}")
    if json_data.get('speed'):
        combat_stats.append(f"**Speed:** {json_data['speed']} ft")
    if json_data.get('initiative'):
        init = json_data['initiative']
        sign = "+" if init >= 0 else ""
        combat_stats.append(f"**Initiative:** {sign}{init}")
    if json_data.get('proficiency_bonus'):
        combat_stats.append(f"**Proficiency:** +{json_data['proficiency_bonus']}")

    if combat_stats:
        lines.append("## Combat")
        lines.append("")
        lines.append(" | ".join(combat_stats))
        lines.append("")

    # Spellcasting
    if json_data.get('spellcasting'):
        sc = json_data['spellcasting']
        lines.append("## Spellcasting")
        lines.append("")
        lines.append(f"**Ability:** {sc.get('ability', '?').upper()} | "
                    f"**Save DC:** {sc.get('save_dc', '?')} | "
                    f"**Attack:** +{sc.get('attack_bonus', '?')}")

        if sc.get('slots'):
            slots = sc['slots']
            slot_parts = [f"**{k}:** {v}" for k, v in sorted(slots.items(), key=lambda x: int(x[0]))]
            lines.append("**Slots:** " + " | ".join(slot_parts))
        lines.append("")

    # Bardic Inspiration / Class Features
    if json_data.get('bardic_inspiration'):
        bi = json_data['bardic_inspiration']
        lines.append(f"**Bardic Inspiration:** {bi.get('die', 'd6')} "
                    f"({bi.get('uses', '?')} uses, {bi.get('recharge', 'long rest')})")
        lines.append("")

    if json_data.get('sorcery_points'):
        lines.append(f"**Sorcery Points:** {json_data['sorcery_points']}")
        lines.append("")

    return "\n".join(lines)


def format_character_list(characters: List[Dict]) -> str:
    """Format a list of characters as a table."""
    if not characters:
        return "No characters found."

    lines = [
        "# Party Characters",
        "*Source: Character Database*",
        "",
        "| Name | Class | Race | Level |",
        "|------|-------|------|-------|"
    ]

    for char in characters:
        name = char.get('name', 'Unknown')
        class_summary = char.get('class_summary', 'Unknown')
        race = char.get('race', 'Unknown')
        level = char.get('level', '?')
        lines.append(f"| {name} | {class_summary} | {race} | {level} |")

    return "\n".join(lines)


# =============================================================================
# SPELL FORMATTING
# =============================================================================

def format_character_spells(character_name: str, spells: List[Dict]) -> str:
    """Format a character's spell list grouped by source and level."""
    if not spells:
        return f"# {character_name}'s Spells\n\n*No spells found.*"

    lines = [f"# {character_name}'s Spells",
             f"*Source: Character Sheet — {character_name}*", ""]

    # Group by source
    by_source = {}
    for spell in spells:
        source_key = spell.get('source_type', 'unknown')
        source_name = spell.get('source_name', 'Unknown')
        source = f"{source_key} ({source_name})"
        if source not in by_source:
            by_source[source] = []
        by_source[source].append(spell)

    for source, source_spells in sorted(by_source.items()):
        lines.append(f"## {source.title()}")
        lines.append("")

        # Group by level within source
        by_level = {}
        for spell in source_spells:
            level = spell.get('spell_level', 0)
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(spell)

        for level in sorted(by_level.keys()):
            level_name = "Cantrips" if level == 0 else f"Level {level}"
            lines.append(f"### {level_name}")

            for spell in sorted(by_level[level], key=lambda x: x.get('spell_name', '')):
                name = spell.get('spell_name', 'Unknown')
                extras = []
                if spell.get('charges_required'):
                    extras.append(f"{spell['charges_required']} charges")
                if spell.get('notes'):
                    extras.append(spell['notes'])
                extra_str = f" *({', '.join(extras)})*" if extras else ""
                lines.append(f"- {name}{extra_str}")

            lines.append("")

    return "\n".join(lines)


# =============================================================================
# FEAT FORMATTING
# =============================================================================

def format_character_feats(character_name: str, feats: List[Dict]) -> str:
    """Format a character's feats."""
    if not feats:
        return f"# {character_name}'s Feats\n\n*No feats found.*"

    lines = [f"# {character_name}'s Feats",
             f"*Source: Character Sheet — {character_name}*", ""]

    for feat in feats:
        lines.append(f"## {feat.get('feat_name', 'Unknown')}")
        lines.append("")

        if feat.get('description'):
            lines.append(feat['description'])
            lines.append("")

        if feat.get('benefits'):
            benefits = feat['benefits']
            if isinstance(benefits, dict):
                lines.append("**Benefits:**")
                for key, value in benefits.items():
                    formatted_key = key.replace('_', ' ').title()
                    if isinstance(value, bool):
                        value = "Yes" if value else "No"
                    elif isinstance(value, list):
                        value = ", ".join(str(v) for v in value)
                    lines.append(f"- {formatted_key}: {value}")
                lines.append("")

    return "\n".join(lines)


# =============================================================================
# FORM FORMATTING
# =============================================================================

def format_character_forms(character_name: str, forms: List[Dict]) -> str:
    """Format a character's transformation forms."""
    if not forms:
        return f"# {character_name}'s Forms\n\n*No forms found.*"

    lines = [f"# {character_name}'s Forms",
             f"*Source: Character Sheet — {character_name}*", ""]

    for form in forms:
        lines.append(f"## {form.get('form_name', 'Unknown')}")
        lines.append("")

        details = []
        if form.get('form_type'):
            details.append(f"**Type:** {form['form_type'].replace('_', ' ').title()}")
        if form.get('creature_type'):
            details.append(f"**Creature:** {form['creature_type']}")
        if form.get('challenge_rating'):
            details.append(f"**CR:** {form['challenge_rating']}")
        if form.get('source_spell'):
            details.append(f"**Via:** {form['source_spell']}")

        if details:
            lines.append(" | ".join(details))
            lines.append("")

        if form.get('notes'):
            lines.append(f"*{form['notes']}*")
            lines.append("")

        if form.get('stats'):
            stats = form['stats']
            lines.append("**Quick Stats:**")
            stat_items = []
            if stats.get('hp'):
                stat_items.append(f"HP {stats['hp']}")
            if stats.get('ac'):
                stat_items.append(f"AC {stats['ac']}")
            if stats.get('speed'):
                stat_items.append(f"Speed {stats['speed']} ft")
            lines.append(", ".join(stat_items))
            lines.append("")

    return "\n".join(lines)


# =============================================================================
# COMPANION FORMATTING
# =============================================================================

def format_character_companions(character_name: str, companions: List[Dict]) -> str:
    """Format a character's companions."""
    if not companions:
        return f"# {character_name}'s Companions\n\n*No companions found.*"

    lines = [f"# {character_name}'s Companions",
             f"*Source: Character Sheet — {character_name}*", ""]

    for comp in companions:
        lines.append(f"## {comp.get('companion_name', 'Unknown')}")
        lines.append("")

        details = []
        if comp.get('creature_type'):
            details.append(f"**Type:** {comp['creature_type']}")
        if comp.get('companion_type'):
            details.append(f"**Role:** {comp['companion_type'].replace('_', ' ').title()}")
        if comp.get('challenge_rating'):
            details.append(f"**CR:** {comp['challenge_rating']}")

        if details:
            lines.append(" | ".join(details))

        combat = []
        if comp.get('hit_points_max'):
            current = comp.get('hit_points_current', comp['hit_points_max'])
            combat.append(f"**HP:** {current}/{comp['hit_points_max']}")
        if comp.get('armor_class'):
            combat.append(f"**AC:** {comp['armor_class']}")

        if combat:
            lines.append(" | ".join(combat))

        if comp.get('notes'):
            lines.append("")
            lines.append(f"*{comp['notes']}*")

        lines.append("")

    return "\n".join(lines)


# =============================================================================
# INVENTORY FORMATTING
# =============================================================================

def format_inventory_list(items: List[Dict], location_name: str = None) -> str:
    """Format an inventory list grouped by item type."""
    if location_name:
        title = f"# Inventory: {location_name}"
        source_line = f"*Source: Inventory — {location_name}*"
    else:
        title = "# Inventory (All Locations)"
        source_line = "*Source: Inventory — All Locations*"

    if not items:
        return f"{title}\n\n*No items found.*"

    lines = [title, source_line, ""]

    # Check if we need to show location column (when showing all locations)
    show_location = location_name is None

    # Group by item type
    by_type = {}
    for item in items:
        item_type = item.get('item_type', 'Miscellaneous') or 'Miscellaneous'
        if item_type not in by_type:
            by_type[item_type] = []
        by_type[item_type].append(item)

    for item_type in sorted(by_type.keys()):
        lines.append(f"## {item_type}")
        lines.append("")
        if show_location:
            lines.append("| Item | Qty | Location | Rarity | Magic |")
            lines.append("|------|:---:|----------|--------|:-----:|")
        else:
            lines.append("| Item | Qty | Rarity | Magic | Notes |")
            lines.append("|------|:---:|--------|:-----:|-------|")

        for item in sorted(by_type[item_type], key=lambda x: x.get('item_name', '')):
            name = item.get('item_name', 'Unknown')
            qty = item.get('quantity', 1)
            rarity = (item.get('rarity') or '-').replace('_', ' ').title()
            magic = "Yes" if item.get('is_magic') else "-"

            if show_location:
                loc = item.get('location_name', 'Unknown')
                lines.append(f"| {name} | {qty} | {loc} | {rarity} | {magic} |")
            else:
                notes = item.get('notes', '-') or '-'
                # Truncate long notes
                if len(notes) > 40:
                    notes = notes[:37] + "..."
                lines.append(f"| {name} | {qty} | {rarity} | {magic} | {notes} |")

        lines.append("")

    # Summary
    total_items = sum(item.get('quantity', 1) for item in items)
    magic_count = sum(1 for item in items if item.get('is_magic'))
    lines.append(f"**Total:** {len(items)} unique items ({total_items} total), {magic_count} magical")

    return "\n".join(lines)


def format_inventory_search_results(items: List[Dict], query: str) -> str:
    """Format inventory search results."""
    if not items:
        return f"# Search: '{query}'\n\n*No matching items found.*"

    lines = [f"# Search Results: '{query}'", ""]
    lines.append(f"Found {len(items)} matching item(s):")
    lines.append("")

    for item in items:
        name = item.get('item_name', 'Unknown')
        location = item.get('location_name', 'Unknown')
        qty = item.get('quantity', 1)
        rarity = item.get('rarity', '')

        magic_indicator = " [Magic]" if item.get('is_magic') else ""
        rarity_indicator = f" ({rarity.replace('_', ' ').title()})" if rarity else ""

        lines.append(f"- **{name}**{magic_indicator}{rarity_indicator}")
        lines.append(f"  - *Source: Inventory — {location}*")
        lines.append(f"  - Quantity: {qty}")
        if item.get('item_description'):
            desc = item['item_description']
            if len(desc) > 80:
                desc = desc[:77] + "..."
            lines.append(f"  - {desc}")
        lines.append("")

    return "\n".join(lines)


# =============================================================================
# CURRENCY FORMATTING
# =============================================================================

def format_currency_by_location(currency_data: List[Dict]) -> str:
    """Format currency breakdown by location."""
    if not currency_data:
        return "# Party Currency\n\n*No currency records found.*"

    lines = ["# Party Currency", "*Source: Currency Ledger — By Location*", ""]
    lines.append("| Location | CP | SP | EP | GP | PP | Total (GP) |")
    lines.append("|----------|---:|---:|---:|---:|---:|----------:|")

    total_gp = 0
    for loc in currency_data:
        name = loc.get('location_name', 'Unknown')
        cp = loc.get('copper', 0)
        sp = loc.get('silver', 0)
        ep = loc.get('electrum', 0)
        gp = loc.get('gold', 0)
        pp = loc.get('platinum', 0)
        loc_total = float(loc.get('total_gp_value', 0) or 0)
        total_gp += loc_total
        lines.append(f"| {name} | {cp:,} | {sp:,} | {ep:,} | {gp:,} | {pp:,} | {loc_total:,.2f} |")

    lines.append(f"| **TOTAL** | | | | | | **{total_gp:,.2f}** |")
    lines.append("")

    return "\n".join(lines)


def format_wealth_summary(wealth: Dict) -> str:
    """Format total wealth summary."""
    if not wealth:
        return "# Party Wealth\n\n*No wealth data found.*"

    return f"""# Party Wealth: {wealth.get('party_name', 'Unknown')}
*Source: Currency Ledger — Total*

| Denomination | Amount |
|--------------|-------:|
| Platinum | {wealth.get('total_platinum', 0):,} |
| Gold | {wealth.get('total_gold', 0):,} |
| Electrum | {wealth.get('total_electrum', 0):,} |
| Silver | {wealth.get('total_silver', 0):,} |
| Copper | {wealth.get('total_copper', 0):,} |
| **Total GP Value** | **{float(wealth.get('total_gp_value', 0) or 0):,.2f}** |
"""


# =============================================================================
# STORAGE LOCATION FORMATTING
# =============================================================================

def format_storage_locations(locations: List[Dict]) -> str:
    """Format storage locations list."""
    if not locations:
        return "# Storage Locations\n\n*No locations found.*"

    lines = ["# Storage Locations", "*Source: Storage Locations Database*", ""]
    lines.append("| Name | Type | Description |")
    lines.append("|------|------|-------------|")

    for loc in locations:
        name = loc.get('name', 'Unknown')
        loc_type = (loc.get('location_type') or 'other').replace('_', ' ').title()
        desc = loc.get('description', '-') or '-'
        if len(desc) > 50:
            desc = desc[:47] + "..."
        lines.append(f"| {name} | {loc_type} | {desc} |")

    return "\n".join(lines)


# =============================================================================
# DIARY FORMATTING
# =============================================================================

def format_diary_entry(entry: Dict) -> str:
    """Format a single diary entry."""
    lines = []

    title = entry.get('title', 'Untitled Entry')
    lines.append(f"# {title}")
    lines.append("")

    # Source attribution
    source_parts = []
    if entry.get('session_date'):
        source_parts.append(f"Session: {entry['session_date']}")
    if entry.get('in_game_date'):
        source_parts.append(f"In-Game: {entry['in_game_date']}")
    if source_parts:
        lines.append(f"*Source: Campaign Diary — {', '.join(source_parts)}*")
        lines.append("")

    # Content
    if entry.get('content'):
        lines.append(entry['content'])
        lines.append("")

    # Locations
    if entry.get('locations_visited'):
        locs = entry['locations_visited']
        if isinstance(locs, list):
            lines.append(f"**Locations:** {', '.join(locs)}")
        lines.append("")

    # NPCs
    if entry.get('npcs_encountered'):
        npcs = entry['npcs_encountered']
        if isinstance(npcs, list):
            lines.append(f"**NPCs:** {', '.join(npcs)}")
        lines.append("")

    # Quests
    if entry.get('quests_updated'):
        quests = entry['quests_updated']
        if isinstance(quests, list):
            lines.append("**Quest Updates:**")
            for quest in quests:
                lines.append(f"- {quest}")
        lines.append("")

    # Loot
    if entry.get('loot_summary'):
        loot = entry['loot_summary']
        lines.append("**Loot:**")
        if isinstance(loot, dict):
            for key, value in loot.items():
                lines.append(f"- {key}: {value}")
        elif isinstance(loot, list):
            for item in loot:
                lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)


def format_diary_list(entries: List[Dict]) -> str:
    """Format a list of diary entries."""
    if not entries:
        return "# Campaign Diary\n\n*No entries found.*"

    lines = ["# Campaign Diary", ""]

    # Group by month_year if available
    by_month = {}
    for entry in entries:
        month = entry.get('month_year', 'Undated')
        if month not in by_month:
            by_month[month] = []
        by_month[month].append(entry)

    for month, month_entries in by_month.items():
        lines.append(f"## {month}")
        lines.append("")

        for entry in sorted(month_entries,
                           key=lambda x: x.get('session_date', ''),
                           reverse=True):
            title = entry.get('title', 'Untitled')
            date = entry.get('session_date', '')
            in_game = entry.get('in_game_date', '')

            # Build source line
            source_parts = []
            if date:
                source_parts.append(f"Session: {date}")
            if in_game:
                source_parts.append(f"In-Game: {in_game}")
            source_line = f"*Source: Diary — {', '.join(source_parts)}*" if source_parts else ""

            # Preview of content
            content = entry.get('content', '')
            preview = content[:100] + "..." if len(content) > 100 else content
            preview = preview.replace('\n', ' ')

            lines.append(f"### {title}")
            if source_line:
                lines.append(source_line)
            lines.append("")
            lines.append(preview)
            lines.append("")

    return "\n".join(lines)


# =============================================================================
# TRANSACTION FORMATTING
# =============================================================================

def format_currency_transaction(result: Dict, action: str) -> str:
    """Format a currency transaction result."""
    if result.get('error'):
        return f"**Error:** {result['error']}"

    lines = [f"# Currency {action.title()}", ""]

    if result.get('transferred'):
        t = result['transferred']
        amounts = []
        if t.get('pp'):
            amounts.append(f"{t['pp']} PP")
        if t.get('gp'):
            amounts.append(f"{t['gp']} GP")
        if t.get('ep'):
            amounts.append(f"{t['ep']} EP")
        if t.get('sp'):
            amounts.append(f"{t['sp']} SP")
        if t.get('cp'):
            amounts.append(f"{t['cp']} CP")
        lines.append(f"**Amount:** {', '.join(amounts) if amounts else 'None'}")
    else:
        lines.append(f"**New Balance:**")
        lines.append(f"- Platinum: {result.get('platinum', 0):,}")
        lines.append(f"- Gold: {result.get('gold', 0):,}")
        lines.append(f"- Silver: {result.get('silver', 0):,}")
        lines.append(f"- Copper: {result.get('copper', 0):,}")

    return "\n".join(lines)


def format_inventory_transaction(result: Dict, action: str) -> str:
    """Format an inventory transaction result."""
    if result.get('error'):
        return f"**Error:** {result['error']}"

    lines = [f"# Inventory {action.title()}", ""]

    if result.get('deleted'):
        item = result.get('item', {})
        lines.append(f"**Removed:** {item.get('item_name', 'Unknown')} (all {item.get('quantity', 1)})")
    elif result.get('success'):
        lines.append(f"**Transferred:** {result.get('transferred', 0)} x {result.get('item', 'Unknown')}")
    else:
        lines.append(f"**Item:** {result.get('item_name', 'Unknown')}")
        lines.append(f"**Quantity:** {result.get('quantity', 1)}")
        if result.get('is_magic'):
            lines.append(f"**Rarity:** {(result.get('rarity') or 'Unknown').replace('_', ' ').title()}")

    return "\n".join(lines)
