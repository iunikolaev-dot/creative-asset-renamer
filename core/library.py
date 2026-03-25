from __future__ import annotations

import csv
import os
from difflib import get_close_matches


class ValueLibrary:
    def __init__(self, library_dir: str):
        self.library_dir = library_dir
        self.fields: dict[str, dict] = {}
        for csv_file in os.listdir(library_dir):
            if csv_file.endswith(".csv"):
                field_name = csv_file.replace(".csv", "")
                self.fields[field_name] = self._load_field(
                    os.path.join(library_dir, csv_file)
                )

    def _load_field(self, path: str) -> dict:
        """Load CSV into {value: [aliases]} dict + flat lookup."""
        entries: dict[str, list[str]] = {}
        lookup: dict[str, str] = {}  # alias -> canonical value
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                val = row["value"].strip().lower()
                aliases = [
                    a.strip().lower()
                    for a in row.get("aliases", "").split(",")
                    if a.strip()
                ]
                entries[val] = aliases
                lookup[val] = val
                for alias in aliases:
                    lookup[alias] = val
        return {
            "entries": entries,
            "lookup": lookup,
            "values": list(entries.keys()),
        }

    def get_values(self, field_name: str) -> list[str]:
        """Get all canonical values for a field."""
        if field_name not in self.fields:
            return []
        return list(self.fields[field_name]["values"])

    def match(self, field_name: str, ai_suggestion: str) -> dict:
        """Match AI suggestion to library value.
        Returns {value, confidence, matched_via}.
        """
        if field_name not in self.fields:
            return {
                "value": ai_suggestion,
                "confidence": "low",
                "matched_via": "no_library",
            }

        field = self.fields[field_name]
        suggestion = ai_suggestion.strip().lower()
        # Try both spaces and underscores
        suggestion_underscore = suggestion.replace(" ", "_")
        suggestion_space = suggestion.replace("_", " ")

        # 1. Exact match on canonical value
        for s in (suggestion, suggestion_space, suggestion_underscore):
            if s in field["entries"]:
                return {"value": s, "confidence": "high", "matched_via": "exact"}

        # 2. Alias match
        for s in (suggestion, suggestion_space, suggestion_underscore):
            if s in field["lookup"]:
                return {
                    "value": field["lookup"][s],
                    "confidence": "high",
                    "matched_via": f"alias:{s}",
                }

        # 3. Fuzzy match (close string match)
        all_terms = list(field["lookup"].keys())
        close = get_close_matches(suggestion_space, all_terms, n=1, cutoff=0.75)
        if close:
            canonical = field["lookup"][close[0]]
            return {
                "value": canonical,
                "confidence": "medium",
                "matched_via": f"fuzzy:{close[0]}",
            }

        # 4. No match - flag for manual review
        return {
            "value": suggestion_space,
            "confidence": "low",
            "matched_via": "unmatched",
        }

    def add_value(self, field_name: str, value: str, aliases: str = "", description: str = ""):
        """Add a new value to a library CSV file."""
        if field_name not in self.fields:
            return

        value = value.strip().lower()
        if value in self.fields[field_name]["entries"]:
            return  # Already exists

        csv_path = os.path.join(self.library_dir, f"{field_name}.csv")
        with open(csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([value, aliases, description])

        # Reload field
        self.fields[field_name] = self._load_field(csv_path)
