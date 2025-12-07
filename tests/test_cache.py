#!/usr/bin/env python3
"""
Test script for the APICache system.

This script tests the cache functionality including the clear_prefix method.
"""

import os
import sys
import json
import tempfile
import shutil

from src.core.cache import APICache


def test_basic_cache_operations():
    """Test basic cache get/set operations."""
    print("Testing basic cache operations...")

    # Create a non-persistent cache for testing
    cache = APICache(ttl_hours=1, persistent=False)

    # Test set and get
    cache.set("test_key", {"value": 123})
    result = cache.get("test_key")

    assert result is not None, "Cache should return stored value"
    assert result["value"] == 123, "Cache should return correct value"

    # Test cache miss
    missing = cache.get("nonexistent_key")
    assert missing is None, "Cache should return None for missing keys"

    print("Basic cache operations test passed!")


def test_clear_prefix_memory():
    """Test clear_prefix with in-memory cache only."""
    print("Testing clear_prefix (memory only)...")

    cache = APICache(ttl_hours=1, persistent=False)

    # Add items with different prefixes
    cache.set("campaign_v_characters_abc123", {"name": "Nico"})
    cache.set("campaign_v_characters_def456", {"name": "Olaf"})
    cache.set("campaign_v_inventory_abc123", {"item": "Sword"})
    cache.set("dnd5e_monsters_dragon", {"name": "Dragon"})

    assert len(cache) == 4, "Cache should have 4 items"

    # Clear only character-related cache
    cleared = cache.clear_prefix("campaign_v_characters_")

    assert cleared == 2, "Should have cleared 2 items"
    assert len(cache) == 2, "Cache should have 2 items remaining"

    # Verify correct items were cleared
    assert cache.get("campaign_v_characters_abc123") is None, "Character cache should be cleared"
    assert cache.get("campaign_v_characters_def456") is None, "Character cache should be cleared"
    assert cache.get("campaign_v_inventory_abc123") is not None, "Inventory cache should remain"
    assert cache.get("dnd5e_monsters_dragon") is not None, "D&D cache should remain"

    print("clear_prefix (memory only) test passed!")


def test_clear_prefix_no_matches():
    """Test clear_prefix when no keys match."""
    print("Testing clear_prefix with no matches...")

    cache = APICache(ttl_hours=1, persistent=False)

    cache.set("campaign_v_characters_abc123", {"name": "Nico"})

    cleared = cache.clear_prefix("nonexistent_prefix_")

    assert cleared == 0, "Should have cleared 0 items"
    assert len(cache) == 1, "Cache should still have 1 item"

    print("clear_prefix (no matches) test passed!")


def test_clear_prefix_persistent():
    """Test clear_prefix with persistent cache."""
    print("Testing clear_prefix (persistent)...")

    # Create a temporary directory for the cache
    temp_dir = tempfile.mkdtemp()

    try:
        cache = APICache(ttl_hours=1, persistent=True, cache_dir=temp_dir)

        # Add items with different prefixes
        cache.set("campaign_v_characters_abc123", {"name": "Nico"})
        cache.set("campaign_v_characters_def456", {"name": "Olaf"})
        cache.set("campaign_v_inventory_abc123", {"item": "Sword"})

        # Verify files were created
        index_path = os.path.join(temp_dir, "index.json")
        assert os.path.exists(index_path), "Index file should exist"

        with open(index_path, "r") as f:
            index = json.load(f)
        assert len(index) == 3, "Index should have 3 entries"

        # Clear character-related cache
        cleared = cache.clear_prefix("campaign_v_characters_")

        assert cleared == 2, "Should have cleared 2 items"

        # Verify index was updated
        with open(index_path, "r") as f:
            index = json.load(f)
        assert len(index) == 1, "Index should have 1 entry remaining"
        assert "campaign_v_inventory_abc123" in index, "Inventory key should remain in index"

        # Verify pickle files were deleted
        char_file1 = os.path.join(temp_dir, "campaign_v_characters_abc123.pickle")
        char_file2 = os.path.join(temp_dir, "campaign_v_characters_def456.pickle")
        inv_file = os.path.join(temp_dir, "campaign_v_inventory_abc123.pickle")

        assert not os.path.exists(char_file1), "Character pickle file should be deleted"
        assert not os.path.exists(char_file2), "Character pickle file should be deleted"
        assert os.path.exists(inv_file), "Inventory pickle file should remain"

        print("clear_prefix (persistent) test passed!")

    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir)


def test_cache_persistence_reload():
    """Test that cache survives reload after clear_prefix."""
    print("Testing cache persistence after clear_prefix...")

    temp_dir = tempfile.mkdtemp()

    try:
        # Create cache and add items
        cache1 = APICache(ttl_hours=1, persistent=True, cache_dir=temp_dir)
        cache1.set("campaign_v_characters_abc123", {"name": "Nico"})
        cache1.set("campaign_v_inventory_abc123", {"item": "Sword"})

        # Clear some items
        cache1.clear_prefix("campaign_v_characters_")

        # Create a new cache instance (simulating server restart)
        cache2 = APICache(ttl_hours=1, persistent=True, cache_dir=temp_dir)

        # Verify only non-cleared items were reloaded
        assert cache2.get("campaign_v_characters_abc123") is None, "Cleared item should not reload"
        assert cache2.get("campaign_v_inventory_abc123") is not None, "Remaining item should reload"
        assert cache2.get("campaign_v_inventory_abc123")["item"] == "Sword"

        print("Cache persistence after clear_prefix test passed!")

    finally:
        shutil.rmtree(temp_dir)


def run_all_tests():
    """Run all cache tests."""
    print("=" * 60)
    print("Running APICache Tests")
    print("=" * 60)

    test_basic_cache_operations()
    test_clear_prefix_memory()
    test_clear_prefix_no_matches()
    test_clear_prefix_persistent()
    test_cache_persistence_reload()

    print("=" * 60)
    print("All cache tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()
