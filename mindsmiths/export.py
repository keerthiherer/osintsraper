"""CSV and Excel exports of stored leads."""
from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd


def _social_map(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s.get("platform", ""): s for s in record.get("socials") or []}


def _followers_label(social: dict[str, Any] | None) -> str:
    if not social:
        return ""
    if social.get("followers") is not None and social.get("followers_verified"):
        return str(int(social["followers"]))
    if social.get("followers") is not None:
        return f"~{int(social['followers']):,} (Needs manual verification)"
    return "Needs manual verification"


def _last_active(social: dict[str, Any] | None) -> str:
    if not social:
        return ""
    if social.get("last_active") and social.get("activity_verified"):
        return str(social["last_active"])
    return "Unknown"


def lead_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        socials = _social_map(record)
        instagram = socials.get("instagram")
        facebook = socials.get("facebook")
        linkedin = socials.get("linkedin")
        rows.append({
            "Business Name": record.get("name", ""),
            "Category": record.get("category", ""),
            "Address": record.get("address", ""),
            "City": record.get("city", ""),
            "Locality": record.get("locality", ""),
            "Phone": record.get("phone", ""),
            "Phone Source": record.get("phone_source", ""),
            "Email": record.get("email", ""),
            "Email Source": record.get("email_source", ""),
            "Website": record.get("website", ""),
            "Website Source": record.get("website_source", ""),
            "Website Status": record.get("website_status", "Unknown"),
            "HTTP Status": record.get("website_http_status") or "",
            "Website Issues": record.get("website_issues", ""),
            "Google Rating": record.get("rating") if record.get("rating") is not None else "",
            "Review Count": record.get("review_count") if record.get("review_count") is not None else "",
            "Instagram URL": instagram.get("url", "") if instagram else "",
            "Instagram Followers": _followers_label(instagram),
            "Instagram Last Active": _last_active(instagram),
            "Facebook URL": facebook.get("url", "") if facebook else "",
            "Facebook Followers": _followers_label(facebook),
            "Facebook Last Active": _last_active(facebook),
            "LinkedIn URL": linkedin.get("url", "") if linkedin else "",
            "LinkedIn Followers": _followers_label(linkedin),
            "LinkedIn Last Active": _last_active(linkedin),
            "Contact Page": record.get("contact_page", ""),
            "Enquiry Form": record.get("form_url", ""),
            "Google Maps / Listing URL": record.get("listing_url", ""),
            "Opening Hours": record.get("opening_hours", ""),
            "Lead Score": record.get("score", 0),
            "Priority": record.get("priority", ""),
            "Qualification Notes": record.get("qualification_notes", ""),
            "Sales Status": record.get("status", "new"),
            "User Notes": record.get("notes", ""),
            "Source": record.get("source", ""),
            "Collected At": record.get("collected_at", ""),
        })
    return rows


def to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(lead_rows(records))


def export_csv(records: list[dict[str, Any]]) -> bytes:
    df = to_dataframe(records)
    return df.to_csv(index=False).encode("utf-8-sig")


def export_excel(records: list[dict[str, Any]]) -> bytes:
    df = to_dataframe(records)
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Leads")
        sheet = writer.sheets["Leads"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            letter = column[0].column_letter
            width = max(len(str(cell.value or "")) for cell in column[:50])
            sheet.column_dimensions[letter].width = min(max(width + 2, 10), 48)
    return buffer.getvalue()

