import requests
import os
import logging
import re
from pathlib import Path

def fetch_save_locations(game_title, windows_games_dir=""):
    """
    Fetch save game locations from PCGamingWiki by scraping wikitext.
    """
    try:
        # Step 1: Find the page title
        page_title = _find_page_title(game_title)
        if not page_title:
            logging.debug(f"[Wiki] No page title found for {game_title}")
            return []

        # Step 2: Get the wikitext
        wikitext = _get_wikitext(page_title)
        if not wikitext:
            logging.debug(f"[Wiki] No wikitext found for {page_title}")
            return []

        # Step 3: Parse save locations
        return _parse_save_locations(wikitext, game_title, windows_games_dir)
    except Exception as e:
        logging.error(f"PCGamingWiki error: {e}")
        return []

def _find_page_title(game_title):
    url = "https://www.pcgamingwiki.com/w/api.php"
    
    # Try exact match first
    params = {
        "action": "query",
        "titles": game_title,
        "format": "json"
    }
    try:
        r = requests.get(url, params=params, timeout=3)
        if r.status_code == 200:
            data = r.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id in pages:
                if page_id != "-1":
                    return pages[page_id].get("title")
        
        # Try search if exact match fails
        params = {
            "action": "query",
            "list": "search",
            "srsearch": game_title,
            "format": "json"
        }
        r = requests.get(url, params=params, timeout=3)
        if r.status_code == 200:
            data = r.json()
            search_results = data.get("query", {}).get("search", [])
            if search_results:
                return search_results[0].get("title")
    except Exception:
        pass
    return None

def _get_wikitext(page_title):
    url = "https://www.pcgamingwiki.com/w/api.php"
    params = {
        "action": "parse",
        "page": page_title,
        "prop": "wikitext",
        "format": "json"
    }
    try:
        r = requests.get(url, params=params, timeout=3)
        if r.status_code == 200:
            data = r.json()
            return data.get("parse", {}).get("wikitext", {}).get("*", "")
    except Exception:
        pass
    return None

def _parse_save_locations(wikitext, game_title, windows_games_dir):
    suggestions = []
    seen = set()

    for line in wikitext.splitlines():
        # Must contain Windows save template
        if "Game data/saves" not in line:
            continue
        if "|Windows|" not in line:
            continue

        logging.debug(f"[Wiki] Found Windows save line: {line.strip()}")

        # Extract everything after |Windows|
        try:
            after = line.split("|Windows|", 1)[1]
        except IndexError:
            continue

        # Remove the trailing }} of the outer template — strip from the right
        # Strategy: remove only the LAST }}
        if after.endswith("}}"):
            after = after[:-2]
        after = after.strip()

        # Split multiple paths by pipe |
        # BUT we must not split inside {{p|x}}
        paths = _safe_split_paths(after)

        for raw in paths:
            raw = raw.strip()
            if not raw:
                continue

            lower = raw.lower()
            # Skip non-Windows platforms and user-specific IDs
            if any(s in lower for s in [
                "steam", "linux", "wine",
                "{{p|uid}}", "{{p|hkcu}}",
                "{{p|osxhome}}", "{{p|xdg",
                "{{p|linux"
            ]):
                continue

            expanded = _expand_wiki_path(raw, game_title, windows_games_dir)
            if not expanded:
                continue

            if expanded.lower() in seen:
                continue
            seen.add(expanded.lower())

            suggestions.append({
                "raw_path": raw,
                "expanded_path": expanded,
                "path_type": _get_path_type(expanded, windows_games_dir),
                "exists": os.path.exists(expanded)
            })

    return suggestions

def _safe_split_paths(s):
    """
    Split a path string on | but NOT inside {{ }}.
    e.g. "{{p|x}}\\foo | {{p|y}}\\bar"
    → ["{{p|x}}\\foo", "{{p|y}}\\bar"]
    """
    parts = []
    depth = 0
    current = []
    i = 0
    while i < len(s):
        c = s[i]
        if s[i:i+2] == "{{":
            depth += 1
            current.append("{{")
            i += 2
            continue
        if s[i:i+2] == "}}":
            depth -= 1
            current.append("}}")
            i += 2
            continue
        if c == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
            i += 1
            continue
        current.append(c)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return [p for p in parts if p]

def _get_path_type(expanded_path, windows_games_dir):
    path_lower = expanded_path.lower()
    
    if "appdata\\roaming" in path_lower:
        return "AppData (Roaming)"
    elif "appdata\\local\\" in path_lower:
        return "AppData (Local)"
    elif "appdata\\locallow" in path_lower:
        return "AppData (LocalLow)"
    elif "documents" in path_lower:
        return "Documents"
    elif "programdata" in path_lower:
        return "ProgramData"
    elif windows_games_dir and windows_games_dir.lower() in path_lower:
        return "Game Folder"
    else:
        return "Other"

def _expand_wiki_path(path, game_title, windows_games_dir):
    logging.debug(f"[Wiki] Raw path: {path}")
    expanded = path

    # Map of EXACT wikitext templates → real paths
    subs = [
        ("{{p|userprofile}}", os.environ.get("USERPROFILE", "")),
        ("{{p|appdata}}", os.environ.get("APPDATA", "")),
        ("{{p|localappdata}}", os.environ.get("LOCALAPPDATA", "")),
        ("{{p|programdata}}", os.environ.get("PROGRAMDATA", "")),
        ("{{p|public}}", os.environ.get("PUBLIC", "")),
        ("{{p|programfiles}}", os.environ.get("PROGRAMFILES", "")),
        ("{{p|programfiles(x86)}}", os.environ.get("PROGRAMFILES(X86)", "")),
        ("{{p|game}}", os.path.join(windows_games_dir, game_title) if windows_games_dir else ""),
    ]

    for template, value in subs:
        if not value:
            if template in expanded.lower():
                # Unknown/empty variable → skip
                return None
            continue
        # Case-insensitive replace
        idx = expanded.lower().find(template.lower())
        while idx != -1:
            expanded = (expanded[:idx]
                       + value
                       + expanded[idx+len(template):])
            idx = expanded.lower().find(template.lower())

    # If any {{p| remains → unrecognized, skip
    if "{{p|" in expanded.lower():
        logging.debug(f"[Wiki] Unresolved template: {path}")
        return None

    # Strip wildcard filenames e.g. \*.dat
    expanded = re.sub(r'[\\/]\*\.[a-zA-Z0-9]+$', '', expanded)
    
    # Strip bare filenames with extension at end
    # only if it looks like a file not a folder
    # (has extension and no trailing slash)
    if re.search(r'\.[a-zA-Z0-9]{2,4}$', expanded):
        expanded = os.path.dirname(expanded)

    # Normalize — NO resolve() as it uses cwd
    expanded = os.path.normpath(expanded)

    logging.debug(f"[Wiki] Expanded: {expanded!r}")
    return expanded
