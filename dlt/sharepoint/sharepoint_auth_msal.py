"""
SharePoint Authentication Module using MSAL (Microsoft Authentication Library)

This module provides OAuth authentication for SharePoint Online using Azure AD.
It uses MSAL for proper token-based authentication that works with modern SharePoint Online.

Authentication Flow:
    1. Acquire token from Azure AD using client credentials
    2. Use token to authenticate to SharePoint via Microsoft Graph API
    3. Access SharePoint lists through Graph API endpoints

Environment Variables:
    SHAREPOINT__SITE_URL: SharePoint site URL
    SHAREPOINT__TENANT_ID: Azure AD tenant ID
    SHAREPOINT__CLIENT_ID: Azure AD application (client) ID
    SHAREPOINT__CLIENT_SECRET: Azure AD client secret
    SHAREPOINT__SITE_NAME: Site name (extracted from URL if not provided)
"""

import os
import requests
from typing import Optional, Dict, Any, List
import msal


class SharePointAuthError(Exception):
    """Raised when SharePoint authentication fails."""
    pass


def get_sharepoint_credentials():
    """
    Get SharePoint credentials from environment variables.

    Returns:
        dict: Dictionary containing SharePoint credentials
    """
    site_url = os.getenv("SHAREPOINT__SITE_URL", "").strip('"')
    tenant_id = os.getenv("SHAREPOINT__TENANT_ID", "").strip('"')
    client_id = os.getenv("SHAREPOINT__CLIENT_ID", "").strip('"')
    client_secret = os.getenv("SHAREPOINT__CLIENT_SECRET", "").strip('"')

    if not all([site_url, tenant_id, client_id, client_secret]):
        raise SharePointAuthError(
            "Missing required SharePoint credentials. Need:\n"
            "- SHAREPOINT__SITE_URL\n"
            "- SHAREPOINT__TENANT_ID\n"
            "- SHAREPOINT__CLIENT_ID\n"
            "- SHAREPOINT__CLIENT_SECRET"
        )

    # Extract site details from URL
    # Format: https://yourcompany.sharepoint.com/sites/ProjectInventory
    parts = site_url.replace("https://", "").split("/")
    tenant_name = parts[0].split(".")[0]  # e.g. yourcompany
    site_path = "/".join(parts[1:]) if len(parts) > 1 else ""  # sites/ProjectInventory

    return {
        "site_url": site_url,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "tenant_name": tenant_name,
        "site_path": site_path,
    }


def get_access_token(tenant_id: str, client_id: str, client_secret: str, scope: str = None) -> str:
    """
    Get access token using MSAL client credentials flow.

    Args:
        tenant_id: Azure AD tenant ID
        client_id: Application client ID
        client_secret: Application client secret
        scope: Permission scope (default: Graph API)

    Returns:
        Access token string
    """
    if scope is None:
        scope = ["https://graph.microsoft.com/.default"]

    authority = f"https://login.microsoftonline.com/{tenant_id}"

    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )

    result = app.acquire_token_for_client(scopes=scope)

    if "access_token" in result:
        return result["access_token"]
    else:
        error_msg = result.get("error_description", result.get("error", "Unknown error"))
        raise SharePointAuthError(f"Failed to acquire token: {error_msg}")


def get_sharepoint_site_id(tenant_name: str, site_path: str, access_token: str) -> str:
    """
    Get SharePoint site ID using Microsoft Graph API.

    Args:
        tenant_name: SharePoint tenant name (e.g., 'yourcompany')
        site_path: Site path (e.g., 'sites/ProjectInventory')
        access_token: Access token for Graph API

    Returns:
        Site ID string
    """
    # Graph API endpoint to get site by path
    url = f"https://graph.microsoft.com/v1.0/sites/{tenant_name}.sharepoint.com:/{site_path}"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        site_data = response.json()
        return site_data["id"]
    else:
        raise SharePointAuthError(
            f"Failed to get site ID: {response.status_code} - {response.text}"
        )


def get_sharepoint_lists(site_id: str, access_token: str) -> List[Dict[str, Any]]:
    """
    Get all SharePoint lists for a site using Microsoft Graph API.

    Args:
        site_id: SharePoint site ID
        access_token: Access token for Graph API

    Returns:
        List of list metadata dictionaries
    """
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data.get("value", [])
    else:
        raise SharePointAuthError(
            f"Failed to get lists: {response.status_code} - {response.text}"
        )


def get_list_items(site_id: str, list_id: str, access_token: str, select_fields: List[str] = None) -> List[Dict[str, Any]]:
    """
    Get all items from a SharePoint list using Microsoft Graph API.

    Args:
        site_id: SharePoint site ID
        list_id: List ID
        access_token: Access token for Graph API
        select_fields: Optional list of fields to select

    Returns:
        List of item dictionaries
    """
    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    params = {
        "expand": "fields"
    }

    if select_fields:
        params["$select"] = ",".join(select_fields)

    all_items = []
    next_link = url

    while next_link:
        if next_link == url:
            response = requests.get(url, headers=headers, params=params)
        else:
            # For @odata.nextLink, don't send params again
            response = requests.get(next_link, headers=headers)

        if response.status_code == 200:
            data = response.json()
            items = data.get("value", [])

            # Extract fields from each item
            for item in items:
                if "fields" in item:
                    all_items.append(item["fields"])

            # Check for pagination
            next_link = data.get("@odata.nextLink")
        else:
            raise SharePointAuthError(
                f"Failed to get list items: {response.status_code} - {response.text}"
            )

    return all_items


class SharePointClient:
    """
    SharePoint client using Microsoft Graph API.

    This class provides a high-level interface for working with SharePoint lists.
    """

    def __init__(self, verbose: bool = True):
        """Initialize SharePoint client with credentials from environment."""
        self.verbose = verbose
        self.creds = get_sharepoint_credentials()

        if self.verbose:
            print(f"Initializing SharePoint client...")
            print(f"   Site URL: {self.creds['site_url']}")
            print(f"   Tenant: {self.creds['tenant_name']}")

        # Get access token
        if self.verbose:
            print(f"   Acquiring access token...")

        self.access_token = get_access_token(
            tenant_id=self.creds["tenant_id"],
            client_id=self.creds["client_id"],
            client_secret=self.creds["client_secret"]
        )

        if self.verbose:
            print(f"   ✅ Access token acquired")

        # Get site ID
        if self.verbose:
            print(f"   Getting site ID...")

        self.site_id = get_sharepoint_site_id(
            tenant_name=self.creds["tenant_name"],
            site_path=self.creds["site_path"],
            access_token=self.access_token
        )

        if self.verbose:
            print(f"   ✅ Site ID: {self.site_id}")

    def get_lists(self) -> List[Dict[str, Any]]:
        """Get all lists in the SharePoint site."""
        if self.verbose:
            print(f"\nFetching SharePoint lists...")

        lists = get_sharepoint_lists(self.site_id, self.access_token)

        if self.verbose:
            print(f"   Found {len(lists)} lists")

        return lists

    def get_list_by_title(self, list_title: str) -> Optional[Dict[str, Any]]:
        """Get a list by its title."""
        lists = self.get_lists()

        for lst in lists:
            if lst.get("displayName") == list_title or lst.get("name") == list_title:
                return lst

        return None

    def get_list_items(self, list_title: str, select_fields: List[str] = None) -> List[Dict[str, Any]]:
        """
        Get all items from a SharePoint list.

        Args:
            list_title: Title of the list
            select_fields: Optional list of fields to select

        Returns:
            List of item dictionaries
        """
        if self.verbose:
            print(f"\nFetching items from list: {list_title}")

        # Find the list
        list_obj = self.get_list_by_title(list_title)

        if not list_obj:
            raise SharePointAuthError(f"List '{list_title}' not found")

        list_id = list_obj["id"]

        if self.verbose:
            print(f"   List ID: {list_id}")

        # Get items
        items = get_list_items(
            site_id=self.site_id,
            list_id=list_id,
            access_token=self.access_token,
            select_fields=select_fields
        )

        if self.verbose:
            print(f"   ✅ Fetched {len(items)} items")

        return items


def test_sharepoint_connection():
    """Test SharePoint connection and display site information."""
    print("=" * 80)
    print("SharePoint Connection Test (using MSAL + Graph API)")
    print("=" * 80)

    try:
        client = SharePointClient(verbose=True)

        # Get and display lists
        print("\n" + "=" * 80)
        print("Available SharePoint Lists:")
        print("=" * 80)

        lists = client.get_lists()

        for lst in lists:
            list_name = lst.get("displayName", lst.get("name", "Unknown"))
            list_id = lst.get("id", "N/A")
            print(f"   - {list_name} (ID: {list_id})")

        # Try to fetch items from the first list
        if lists:
            first_list = lists[0]
            list_name = first_list.get("displayName", first_list.get("name"))

            print(f"\n" + "=" * 80)
            print(f"Fetching sample items from: {list_name}")
            print("=" * 80)

            items = client.get_list_items(list_name)

            if items:
                print(f"\n   Sample item (first record):")
                print("   " + "-" * 76)
                import json
                print(json.dumps(items[0], indent=4, default=str))

        print("\n" + "=" * 80)
        print("✅ Connection test successful!")
        print("=" * 80)

        return True

    except SharePointAuthError as e:
        print("\n" + "=" * 80)
        print("❌ Connection test failed!")
        print("=" * 80)
        print(f"Error: {e}")
        print("=" * 80)
        return False
    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ Unexpected error!")
        print("=" * 80)
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        print("=" * 80)
        return False


if __name__ == "__main__":
    # Run connection test when executed directly
    test_sharepoint_connection()
