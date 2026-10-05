import os
import re

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from django.test import Client
from django.urls import get_resolver


# ============================================================
# SETTINGS
# ============================================================

HOST = "127.0.0.1"

client = Client(HTTP_HOST=HOST)


# ============================================================
# GET ALL URL PATTERNS
# ============================================================

resolver = get_resolver()


def collect_urls(patterns, prefix=""):
    urls = []

    for pattern in patterns:

        route = str(pattern.pattern)
        full_route = prefix + route

        # Nested URL configuration
        if hasattr(pattern, "url_patterns"):
            urls.extend(
                collect_urls(
                    pattern.url_patterns,
                    full_route
                )
            )
            continue

        # Skip dynamic URLs
        if (
            "<" in full_route
            or ">" in full_route
            or "(?P<" in full_route
            or "\\d" in full_route
            or ".*" in full_route
        ):
            continue

        # Clean route
        path = "/" + full_route.lstrip("/")

        if not path.endswith("/"):
            path += "/"

        urls.append(path)

    return urls


urls = sorted(set(collect_urls(resolver.url_patterns)))


# ============================================================
# TEST
# ============================================================

working = []
redirecting = []
errors = []
skipped = []


for url in urls:

    try:

        response = client.get(
            url,
            follow=False
        )

        status = response.status_code

        if 200 <= status < 300:

            working.append(
                (status, url)
            )

        elif 300 <= status < 400:

            redirecting.append(
                (
                    status,
                    url,
                    response.get("Location")
                )
            )

        else:

            errors.append(
                (
                    status,
                    url
                )
            )

    except Exception as e:

        errors.append(
            (
                "EXCEPTION",
                url,
                str(e)
            )
        )


# ============================================================
# PRINT RESULTS
# ============================================================

print("\n" + "=" * 70)
print("IDDS URL TEST")
print("=" * 70)

print(f"\nTotal static URLs tested: {len(urls)}")


print("\n" + "-" * 70)
print("WORKING URLs")
print("-" * 70)

for status, url in working:
    print(f"OK       {status}   {url}")


print("\n" + "-" * 70)
print("REDIRECTING URLs")
print("-" * 70)

for status, url, location in redirecting:
    print(
        f"REDIRECT {status}   {url}  ->  {location}"
    )


print("\n" + "-" * 70)
print("ERROR URLs")
print("-" * 70)

for item in errors:
    print(
        f"ERROR    {item}"
    )


# ============================================================
# DYNAMIC URLS
# ============================================================

print("\n" + "-" * 70)
print("DYNAMIC / PARAMETERIZED URLs")
print("-" * 70)

for pattern in resolver.url_patterns:

    route = str(pattern.pattern)

    if (
        "<" in route
        or "(?P<" in route
        or "\\d" in route
        or ".*" in route
    ):
        print(f"SKIPPED  /{route}")


# ============================================================
# SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print("Working:      ", len(working))
print("Redirecting:  ", len(redirecting))
print("Errors:       ", len(errors))

print("=" * 70)