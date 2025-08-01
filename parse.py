import os
import json
import re
from bs4 import BeautifulSoup
from bs4.element import Tag

html_dir = "."
output = []

def to_anchor_id(text):
    text = text.strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'\s+', '-', text)
    return text

# Inference map: infer cube/module from filename keywords
cube_keywords = {
    "rate": "Rate Cube",
    "audit": "Audit Cube",
    "track": "Track Cube",
    "admin": "Admin Cube",
    "userprofile": "Admin Cube",
    "account": "Admin Cube",
    "invoice": "Audit Cube",
    "dispute": "Audit Cube",
    "carrier": "Admin Cube",
    "simulation": "Rate Cube",
    "ratemaintenance": "Rate Cube",
    "role": "Admin Cube",
    "location": "Admin Cube",
    "index": "Help Center Landing"
}

# Loop through HTML files
for filename in os.listdir(html_dir):
    if filename.endswith(".html"):
        filepath = os.path.join(html_dir, filename)

        with open(filepath, "r", encoding="utf-8") as file:
            soup = BeautifulSoup(file, "html.parser")

        page_title = soup.title.get_text(strip=True) if soup.title else filename.replace(".html", "")
        base_url = f"http://dev.tcube360.com/help/{filename}"
        page_id = filename

        # Infer cube/module name
        cube = None
        for key, value in cube_keywords.items():
            if key in filename.lower():
                cube = value
                break
        if not cube:
            cube = "General"

        # Extract content from each section
        for h2 in soup.find_all("h2"):
            section_title = h2.get_text(strip=True)
            anchor_id = to_anchor_id(section_title)
            full_url = f"{base_url}#{anchor_id}"

            content = []
            for sibling in h2.find_next_siblings():
                if isinstance(sibling, Tag) and sibling.name == "h2":
                    break
                text = sibling.get_text(" ", strip=True)
                if text:
                    content.append(text)

            section_text = " ".join(content).strip()
            section_text = re.sub(r'\s+', ' ', section_text)  # Remove redundant spacing

            if section_text:
                entry = {
                    "cube": cube,
                    "page_title": page_title,
                    "page_id": page_id,
                    "section_title": section_title,
                    "content": section_text,
                    "source_url": full_url
                }

                # Optional: Add preview field for UI (uncomment if needed)
                # entry["preview"] = section_text[:300] + "..." if len(section_text) > 300 else section_text

                output.append(entry)

# Save output
with open("helpdocs.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

# Display confirmation and preview
print("Extraction complete.")
print(f"Parsed {len(output)} help sections from {html_dir}")
print("\n🔍 Sample output:\n")
for item in output[:2]:
    print(json.dumps(item, indent=2, ensure_ascii=False))
