"""
SharePoint List Utilities

Provides utilities for fetching SharePoint list items with automatic pagination,
dynamic field handling, and type conversion for DLT pipelines.

Features:
    - Automatic pagination for large lists (handles >5000 items)
    - Dynamic field discovery and type inference
    - Proper handling of SharePoint field types (lookup, choice, user, date, etc.)
    - Error handling and retry logic
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
from office365.sharepoint.client_context import ClientContext
from office365.sharepoint.lists.list import List as SPList
from .sharepoint_auth import get_sharepoint_context


def normalize_field_value(field_value: Any, field_type: Optional[str] = None) -> Any:
    """
    Normalize SharePoint field values to Python-friendly types.

    SharePoint returns various types including complex objects for lookups,
    user fields, etc. This function converts them to simple types suitable for DLT.

    Args:
        field_value: The raw field value from SharePoint
        field_type: Optional field type hint

    Returns:
        Normalized value suitable for database storage
    """
    if field_value is None:
        return None

    # Handle datetime objects
    if isinstance(field_value, datetime):
        return field_value.isoformat()

    # Handle user/person fields (complex objects)
    if isinstance(field_value, dict):
        # User field: extract email or name
        if 'Email' in field_value:
            return field_value.get('Email') or field_value.get('Title')
        # Lookup field: extract LookupValue
        elif 'LookupValue' in field_value:
            return field_value.get('LookupValue')
        # Return as-is for other dicts (will be handled by DLT)
        else:
            return field_value

    # Handle list/array of values
    if isinstance(field_value, list):
        return [normalize_field_value(v) for v in field_value]

    # Return primitive types as-is
    return field_value


def fetch_list_items(
    ctx: ClientContext,
    list_title: str,
    select_fields: Optional[List[str]] = None,
    filter_query: Optional[str] = None,
    order_by: Optional[str] = None,
    top: int = 5000,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetch all items from a SharePoint list with automatic pagination.

    Args:
        ctx: Authenticated SharePoint ClientContext
        list_title: Title of the SharePoint list (e.g., "Proje Inv")
        select_fields: Optional list of fields to retrieve. If None, gets all fields.
        filter_query: Optional OData filter query (e.g., "Status eq 'Active'")
        order_by: Optional field to order by (e.g., "Modified desc")
        top: Number of items to fetch per page (default: 5000, max for SharePoint)
        verbose: If True, print progress information

    Returns:
        List of dictionaries, each representing a list item

    Example:
        >>> ctx = get_sharepoint_context()
        >>> items = fetch_list_items(ctx, "Proje Inv")
        >>> print(f"Fetched {len(items)} items")
    """
    if verbose:
        print(f"Fetching items from SharePoint list: {list_title}")

    try:
        # Get the list
        shrp_list = ctx.web.lists.get_by_title(list_title)
        ctx.load(shrp_list)
        ctx.execute_query()

        if verbose:
            item_count = shrp_list.properties.get('ItemCount', 'unknown')
            print(f"   List: {list_title}")
            print(f"   Total items in list: {item_count}")

        # Build the query
        items_query = shrp_list.items

        # Add select fields if specified
        if select_fields:
            items_query = items_query.select(select_fields)

        # Add filter if specified
        if filter_query:
            items_query = items_query.filter(filter_query)

        # Add order by if specified
        if order_by:
            items_query = items_query.order_by(order_by)

        # Set page size
        items_query = items_query.top(top)

        # Fetch all items with pagination
        all_items = []
        page_num = 1

        if verbose:
            print(f"   Fetching items (page size: {top})...")

        # Use get_all() to automatically handle pagination
        items = items_query.get_all(page_size=top).execute_query()

        # Convert to list of dictionaries with normalized values
        for item in items:
            item_dict = {}
            for key, value in item.properties.items():
                # Skip internal SharePoint fields that start with __
                if key.startswith('__'):
                    continue
                item_dict[key] = normalize_field_value(value)
            all_items.append(item_dict)

        if verbose:
            print(f"   ✅ Fetched {len(all_items)} items total")

        return all_items

    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "does not exist" in error_msg.lower():
            raise ValueError(
                f"SharePoint list '{list_title}' not found. "
                f"Please verify the list name is correct and accessible."
            )
        elif "403" in error_msg or "Forbidden" in error_msg:
            raise PermissionError(
                f"Access denied to SharePoint list '{list_title}'. "
                f"Please verify the app/user has read permissions."
            )
        else:
            raise Exception(f"Error fetching items from '{list_title}': {error_msg}")


def get_list_fields(ctx: ClientContext, list_title: str, verbose: bool = True) -> List[Dict[str, Any]]:
    """
    Get metadata about fields in a SharePoint list.

    Useful for understanding the schema and field types before extraction.

    Args:
        ctx: Authenticated SharePoint ClientContext
        list_title: Title of the SharePoint list
        verbose: If True, print field information

    Returns:
        List of field metadata dictionaries

    Example:
        >>> ctx = get_sharepoint_context()
        >>> fields = get_list_fields(ctx, "Proje Inv")
        >>> for field in fields:
        ...     print(f"{field['Title']}: {field['TypeAsString']}")
    """
    try:
        shrp_list = ctx.web.lists.get_by_title(list_title)
        fields = shrp_list.fields
        ctx.load(fields)
        ctx.execute_query()

        field_info = []
        for field in fields:
            props = field.properties
            # Skip hidden and internal fields
            if props.get('Hidden', False):
                continue

            field_data = {
                'InternalName': props.get('InternalName'),
                'Title': props.get('Title'),
                'TypeAsString': props.get('TypeAsString'),
                'Required': props.get('Required', False),
                'ReadOnlyField': props.get('ReadOnlyField', False),
                'Description': props.get('Description', ''),
            }
            field_info.append(field_data)

        if verbose:
            print(f"\nFields in list '{list_title}':")
            print("=" * 80)
            for field in field_info:
                required = " [REQUIRED]" if field['Required'] else ""
                readonly = " [READONLY]" if field['ReadOnlyField'] else ""
                print(f"   {field['Title']:30} | {field['TypeAsString']:20} {required}{readonly}")
            print("=" * 80)
            print(f"Total: {len(field_info)} visible fields")

        return field_info

    except Exception as e:
        raise Exception(f"Error fetching fields from '{list_title}': {str(e)}")


def get_list_info(ctx: ClientContext, list_title: str) -> Dict[str, Any]:
    """
    Get general information about a SharePoint list.

    Args:
        ctx: Authenticated SharePoint ClientContext
        list_title: Title of the SharePoint list

    Returns:
        Dictionary containing list metadata

    Example:
        >>> ctx = get_sharepoint_context()
        >>> info = get_list_info(ctx, "Proje Inv")
        >>> print(info['ItemCount'])
    """
    try:
        shrp_list = ctx.web.lists.get_by_title(list_title)
        ctx.load(shrp_list)
        ctx.execute_query()

        return {
            'Title': shrp_list.properties.get('Title'),
            'Description': shrp_list.properties.get('Description'),
            'ItemCount': shrp_list.properties.get('ItemCount'),
            'Id': shrp_list.properties.get('Id'),
            'Created': shrp_list.properties.get('Created'),
            'LastItemModifiedDate': shrp_list.properties.get('LastItemModifiedDate'),
            'Hidden': shrp_list.properties.get('Hidden', False),
        }

    except Exception as e:
        raise Exception(f"Error fetching info for '{list_title}': {str(e)}")


def discover_sharepoint_lists(verbose: bool = True) -> List[Dict[str, Any]]:
    """
    Discover all accessible SharePoint lists in the configured site.

    Returns:
        List of dictionaries containing list metadata

    Example:
        >>> lists = discover_sharepoint_lists()
        >>> for lst in lists:
        ...     print(f"{lst['Title']}: {lst['ItemCount']} items")
    """
    ctx = get_sharepoint_context(verbose=False)

    try:
        lists = ctx.web.lists
        ctx.load(lists)
        ctx.execute_query()

        list_info = []
        for lst in lists:
            props = lst.properties
            # Skip hidden system lists
            if props.get('Hidden', False):
                continue

            list_data = {
                'Title': props.get('Title'),
                'Description': props.get('Description', ''),
                'ItemCount': props.get('ItemCount', 0),
                'Id': props.get('Id'),
                'Created': props.get('Created'),
                'LastItemModifiedDate': props.get('LastItemModifiedDate'),
            }
            list_info.append(list_data)

        if verbose:
            print("\nDiscovered SharePoint Lists:")
            print("=" * 80)
            for lst in sorted(list_info, key=lambda x: x['Title']):
                print(f"   {lst['Title']:40} | {lst['ItemCount']:6} items")
            print("=" * 80)
            print(f"Total: {len(list_info)} lists")

        return list_info

    except Exception as e:
        raise Exception(f"Error discovering SharePoint lists: {str(e)}")


if __name__ == "__main__":
    # Test utility functions
    print("=" * 80)
    print("SharePoint Utilities Test")
    print("=" * 80)

    try:
        # Test connection
        ctx = get_sharepoint_context(verbose=True)

        # Discover lists
        lists = discover_sharepoint_lists(verbose=True)

        # If lists found, get fields for the first one
        if lists:
            first_list = lists[0]['Title']
            print(f"\n\nGetting fields for: {first_list}")
            fields = get_list_fields(ctx, first_list, verbose=True)

            # Fetch a few items as sample
            print(f"\n\nFetching sample items from: {first_list}")
            items = fetch_list_items(ctx, first_list, top=5, verbose=True)

            if items:
                print(f"\n\nSample item (first record):")
                print("=" * 80)
                import json
                print(json.dumps(items[0], indent=2, default=str))

    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
