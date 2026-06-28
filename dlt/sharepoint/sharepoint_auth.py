"""
SharePoint Authentication Module

Provides authentication utilities for SharePoint Online using Azure AD credentials.
Supports both client credentials (app-only) and user credentials authentication.

Authentication Methods:
    1. Client Credentials (App-Only): Using Azure AD App Registration
       - Requires: TENANT_ID, CLIENT_ID, CLIENT_SECRET
       - Best for: Automated pipelines, service accounts

    2. User Credentials: Using username and password
       - Requires: USERNAME, PASSWORD
       - Best for: User context operations (may require MFA handling)

Environment Variables:
    SHAREPOINT__SITE_URL: SharePoint site URL (e.g., https://firmaxit.sharepoint.com/sites/ProjectInventory)
    SHAREPOINT__TENANT_ID: Azure AD tenant ID
    SHAREPOINT__CLIENT_ID: Azure AD application (client) ID
    SHAREPOINT__CLIENT_SECRET: Azure AD client secret
    SHAREPOINT__USERNAME: SharePoint user email (optional, for user auth)
    SHAREPOINT__PASSWORD: SharePoint user password (optional, for user auth)
"""

import os
from typing import Optional
from office365.runtime.auth.client_credential import ClientCredential
from office365.runtime.auth.user_credential import UserCredential
from office365.sharepoint.client_context import ClientContext


class SharePointAuthError(Exception):
    """Raised when SharePoint authentication fails."""
    pass


def get_sharepoint_credentials():
    """
    Get SharePoint credentials from environment variables.

    Returns:
        dict: Dictionary containing SharePoint credentials

    Raises:
        SharePointAuthError: If required credentials are missing
    """
    site_url = os.getenv("SHAREPOINT__SITE_URL", "").strip('"')
    tenant_id = os.getenv("SHAREPOINT__TENANT_ID", "").strip('"')
    client_id = os.getenv("SHAREPOINT__CLIENT_ID", "").strip('"')
    client_secret = os.getenv("SHAREPOINT__CLIENT_SECRET", "").strip('"')
    username = os.getenv("SHAREPOINT__USERNAME", "").strip('"')
    password = os.getenv("SHAREPOINT__PASSWORD", "").strip('"')

    if not site_url:
        raise SharePointAuthError(
            "SHAREPOINT__SITE_URL is required. "
            "Example: https://firmaxit.sharepoint.com/sites/ProjectInventory"
        )

    # Check if we have client credentials OR user credentials
    has_client_creds = all([tenant_id, client_id, client_secret])
    has_user_creds = all([username, password])

    if not (has_client_creds or has_user_creds):
        raise SharePointAuthError(
            "Authentication credentials missing. Provide either:\n"
            "1. Client Credentials: SHAREPOINT__TENANT_ID, SHAREPOINT__CLIENT_ID, SHAREPOINT__CLIENT_SECRET\n"
            "2. User Credentials: SHAREPOINT__USERNAME, SHAREPOINT__PASSWORD"
        )

    return {
        "site_url": site_url,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret": client_secret,
        "username": username,
        "password": password,
        "has_client_creds": has_client_creds,
        "has_user_creds": has_user_creds,
    }


def get_sharepoint_context(verbose: bool = True) -> ClientContext:
    """
    Create and return an authenticated SharePoint ClientContext.

    This function attempts authentication in the following order:
    1. Client Credentials (Azure AD App) - Preferred for automation
    2. User Credentials (Username/Password) - Fallback option

    Args:
        verbose: If True, print authentication method being used

    Returns:
        ClientContext: Authenticated SharePoint client context

    Raises:
        SharePointAuthError: If authentication fails or credentials are invalid

    Example:
        >>> ctx = get_sharepoint_context()
        >>> web = ctx.web
        >>> ctx.load(web)
        >>> ctx.execute_query()
        >>> print(web.properties['Title'])
    """
    try:
        creds = get_sharepoint_credentials()
        site_url = creds["site_url"]

        # Try Client Credentials first (preferred for automation)
        if creds["has_client_creds"]:
            if verbose:
                print(f"Authenticating with Client Credentials (App-Only)...")
                print(f"   Site URL: {site_url}")
                print(f"   Tenant ID: {creds['tenant_id'][:8]}...")
                print(f"   Client ID: {creds['client_id'][:8]}...")

            try:
                client_credentials = ClientCredential(
                    creds['client_id'],
                    creds['client_secret']
                )
                ctx = ClientContext(site_url).with_credentials(client_credentials)

                # Test the connection
                if verbose:
                    print("   Testing connection...")
                web = ctx.web
                ctx.load(web)
                ctx.execute_query()

                if verbose:
                    print(f"   ✅ Successfully authenticated to: {web.properties.get('Title', 'SharePoint Site')}")

                return ctx

            except Exception as e:
                error_msg = str(e)
                if "401" in error_msg or "Unauthorized" in error_msg:
                    raise SharePointAuthError(
                        f"Client Credentials authentication failed (401 Unauthorized).\n"
                        f"This may be due to:\n"
                        f"1. Invalid CLIENT_ID or CLIENT_SECRET\n"
                        f"2. App not registered in SharePoint (use /_layouts/15/appregnew.aspx)\n"
                        f"3. App permissions not granted (use /_layouts/15/appinv.aspx)\n"
                        f"4. SharePoint Online may require certificate-based authentication\n"
                        f"Original error: {error_msg}"
                    )
                else:
                    raise SharePointAuthError(
                        f"Client Credentials authentication failed: {error_msg}"
                    )

        # Fallback to User Credentials
        elif creds["has_user_creds"]:
            if verbose:
                print(f"Authenticating with User Credentials...")
                print(f"   Site URL: {site_url}")
                print(f"   Username: {creds['username']}")

            try:
                user_credentials = UserCredential(
                    creds['username'],
                    creds['password']
                )
                ctx = ClientContext(site_url).with_credentials(user_credentials)

                # Test the connection
                if verbose:
                    print("   Testing connection...")
                web = ctx.web
                ctx.load(web)
                ctx.execute_query()

                if verbose:
                    print(f"   ✅ Successfully authenticated to: {web.properties.get('Title', 'SharePoint Site')}")

                return ctx

            except Exception as e:
                error_msg = str(e)
                if "401" in error_msg or "Unauthorized" in error_msg:
                    raise SharePointAuthError(
                        f"User Credentials authentication failed (401 Unauthorized).\n"
                        f"This may be due to:\n"
                        f"1. Invalid username or password\n"
                        f"2. MFA/2FA is enabled (consider using Client Credentials instead)\n"
                        f"3. Account is locked or disabled\n"
                        f"Original error: {error_msg}"
                    )
                else:
                    raise SharePointAuthError(
                        f"User Credentials authentication failed: {error_msg}"
                    )

        else:
            raise SharePointAuthError("No valid authentication credentials found")

    except SharePointAuthError:
        raise
    except Exception as e:
        raise SharePointAuthError(f"Unexpected error during authentication: {str(e)}")


def test_sharepoint_connection():
    """
    Test SharePoint connection and print site information.

    This is a diagnostic function to verify credentials and connectivity.
    """
    print("=" * 80)
    print("SharePoint Connection Test")
    print("=" * 80)

    try:
        ctx = get_sharepoint_context(verbose=True)

        # Get site information
        web = ctx.web
        ctx.load(web)
        ctx.execute_query()

        print("\n" + "=" * 80)
        print("Site Information:")
        print("=" * 80)
        print(f"   Title: {web.properties.get('Title', 'N/A')}")
        print(f"   URL: {web.properties.get('Url', 'N/A')}")
        print(f"   Description: {web.properties.get('Description', 'N/A')}")
        print(f"   Server Relative URL: {web.properties.get('ServerRelativeUrl', 'N/A')}")

        # List available lists
        print("\n" + "=" * 80)
        print("Available Lists:")
        print("=" * 80)

        lists = ctx.web.lists
        ctx.load(lists)
        ctx.execute_query()

        for lst in lists:
            item_count = lst.properties.get('ItemCount', 0)
            hidden = lst.properties.get('Hidden', False)
            if not hidden:  # Only show visible lists
                print(f"   - {lst.properties['Title']} ({item_count} items)")

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
        print("=" * 80)
        return False


if __name__ == "__main__":
    # Run connection test when executed directly
    test_sharepoint_connection()
