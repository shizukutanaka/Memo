#!/usr/bin/env python3
"""Advanced search functionality for memos."""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import logging


class SearchFilter:
    """Represents a search filter."""

    def __init__(self, field: str, operator: str, value: any):
        self.field = field
        self.operator = operator
        self.value = value

    def matches(self, memo: Dict) -> bool:
        """Check if memo matches this filter."""
        memo_value = memo.get(self.field)

        if self.operator == 'eq':
            return memo_value == self.value
        elif self.operator == 'ne':
            return memo_value != self.value
        elif self.operator == 'contains':
            return self.value.lower() in str(memo_value).lower()
        elif self.operator == 'not_contains':
            return self.value.lower() not in str(memo_value).lower()
        elif self.operator == 'regex':
            return bool(re.search(self.value, str(memo_value), re.IGNORECASE))
        elif self.operator == 'gt':
            return memo_value > self.value
        elif self.operator == 'lt':
            return memo_value < self.value
        elif self.operator == 'gte':
            return memo_value >= self.value
        elif self.operator == 'lte':
            return memo_value <= self.value
        elif self.operator == 'in':
            return memo_value in self.value
        elif self.operator == 'not_in':
            return memo_value not in self.value

        return False


class SearchQuery:
    """Represents a complex search query."""

    def __init__(self):
        self.filters: List[SearchFilter] = []
        self.text_query: Optional[str] = None
        self.fuzzy_threshold: float = 0.6
        self.sort_by: Optional[str] = None
        self.sort_order: str = 'desc'  # asc or desc
        self.limit: Optional[int] = None

    def add_filter(self, field: str, operator: str, value: any):
        """Add a filter to the query."""
        self.filters.append(SearchFilter(field, operator, value))
        return self

    def set_text_query(self, query: str, fuzzy: bool = False):
        """Set text search query."""
        self.text_query = query
        if fuzzy:
            self.fuzzy_threshold = 0.6
        return self

    def set_sort(self, field: str, order: str = 'desc'):
        """Set sort criteria."""
        self.sort_by = field
        self.sort_order = order
        return self

    def set_limit(self, limit: int):
        """Set result limit."""
        self.limit = limit
        return self

    def matches(self, memo: Dict) -> bool:
        """Check if memo matches all filters."""
        for filter_obj in self.filters:
            if not filter_obj.matches(memo):
                return False
        return True


class AdvancedSearch:
    """Advanced search engine for memos."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def search(self, memos: List[Dict], query: SearchQuery) -> List[Dict]:
        """Execute search query."""
        # Apply filters
        results = [memo for memo in memos if query.matches(memo)]

        # Apply text query if present
        if query.text_query:
            results = self._text_search(results, query.text_query, query.fuzzy_threshold)

        # Sort results
        if query.sort_by:
            results = self._sort_results(results, query.sort_by, query.sort_order)

        # Apply limit
        if query.limit:
            results = results[:query.limit]

        return results

    def _text_search(self, memos: List[Dict], query: str, fuzzy_threshold: float) -> List[Dict]:
        """Perform text search with optional fuzzy matching."""
        query_lower = query.lower()
        results = []

        for memo in memos:
            text = memo.get('text', '').lower()
            tags = ' '.join(memo.get('tags', [])).lower()
            category = memo.get('category', '').lower()

            # Exact match
            if query_lower in text or query_lower in tags or query_lower in category:
                results.append(memo)
            # Fuzzy match
            elif fuzzy_threshold > 0:
                score = self._fuzzy_score(query_lower, text)
                if score >= fuzzy_threshold:
                    results.append(memo)

        return results

    def _fuzzy_score(self, query: str, text: str) -> float:
        """Calculate fuzzy match score."""
        # Simple word-based fuzzy matching
        query_words = set(query.split())
        text_words = set(text.split())

        if not query_words:
            return 0.0

        matches = query_words & text_words
        return len(matches) / len(query_words)

    def _sort_results(self, memos: List[Dict], sort_by: str, order: str) -> List[Dict]:
        """Sort results."""
        reverse = (order == 'desc')

        try:
            return sorted(memos, key=lambda m: m.get(sort_by, ''), reverse=reverse)
        except Exception as e:
            self.logger.error(f"Failed to sort by {sort_by}: {e}")
            return memos

    def search_by_date_range(self, memos: List[Dict], start_date: datetime, end_date: datetime) -> List[Dict]:
        """Search memos within date range."""
        results = []
        for memo in memos:
            try:
                memo_date = datetime.fromisoformat(memo['timestamp'])
                if start_date <= memo_date <= end_date:
                    results.append(memo)
            except (KeyError, ValueError):
                continue
        return results

    def search_by_tags(self, memos: List[Dict], tags: List[str], match_all: bool = False) -> List[Dict]:
        """Search memos by tags."""
        results = []
        tags_lower = [t.lower() for t in tags]

        for memo in memos:
            memo_tags = [t.lower() for t in memo.get('tags', [])]

            if match_all:
                # All tags must be present
                if all(tag in memo_tags for tag in tags_lower):
                    results.append(memo)
            else:
                # Any tag matches
                if any(tag in memo_tags for tag in tags_lower):
                    results.append(memo)

        return results

    def search_recent(self, memos: List[Dict], hours: int = 24) -> List[Dict]:
        """Search memos from recent hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        return self.search_by_date_range(memos, cutoff, datetime.now())

    def search_by_pattern(self, memos: List[Dict], pattern: str, field: str = 'text') -> List[Dict]:
        """Search using regex pattern."""
        results = []
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            for memo in memos:
                if field in memo and regex.search(str(memo[field])):
                    results.append(memo)
        except re.error as e:
            self.logger.error(f"Invalid regex pattern: {e}")
        return results

    def aggregate(self, memos: List[Dict], group_by: str) -> Dict:
        """Aggregate memos by field."""
        groups = {}
        for memo in memos:
            key = memo.get(group_by, 'unknown')
            if isinstance(key, list):
                # Handle list fields like tags
                for item in key:
                    if item not in groups:
                        groups[item] = []
                    groups[item].append(memo)
            else:
                if key not in groups:
                    groups[key] = []
                groups[key].append(memo)
        return groups

    def build_query_from_text(self, query_text: str) -> SearchQuery:
        """Parse natural language query into SearchQuery."""
        query = SearchQuery()

        # Parse filters from text
        # Example: "tag:work category:development after:2025-01-01"

        # Tag filter
        tag_matches = re.findall(r'tag:(\w+)', query_text, re.IGNORECASE)
        if tag_matches:
            query.add_filter('tags', 'in', tag_matches)

        # Category filter
        cat_match = re.search(r'category:(\w+)', query_text, re.IGNORECASE)
        if cat_match:
            query.add_filter('category', 'eq', cat_match.group(1))

        # Status filter
        status_match = re.search(r'status:(\w+)', query_text, re.IGNORECASE)
        if status_match:
            query.add_filter('status', 'eq', status_match.group(1))

        # Date filters
        after_match = re.search(r'after:([\d-]+)', query_text, re.IGNORECASE)
        if after_match:
            try:
                date = datetime.fromisoformat(after_match.group(1))
                query.add_filter('timestamp', 'gte', date.isoformat())
            except ValueError:
                pass

        before_match = re.search(r'before:([\d-]+)', query_text, re.IGNORECASE)
        if before_match:
            try:
                date = datetime.fromisoformat(before_match.group(1))
                query.add_filter('timestamp', 'lte', date.isoformat())
            except ValueError:
                pass

        # Remove filter syntax from text query
        clean_text = re.sub(r'\w+:\S+', '', query_text).strip()
        if clean_text:
            query.set_text_query(clean_text)

        return query
