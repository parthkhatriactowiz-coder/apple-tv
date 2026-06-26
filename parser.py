"""
Monarch JSON Extractor
======================
Reads monarch_1.json (S1 episode details) and monarch_2.json (full page layout)
and extracts all fields into a clean, structured output JSON.

Designed to work across multiple Apple TV show pages — no hardcoded show IDs,
shelf indexes, or episode counts.

monarch_2 shelf types (matched by ID substring, not position):
  uts.marker.EpisodeList   -> Episode grid (EpisodeLockup rows, all seasons)
  uts.col.Trailers.*       -> Trailers
  uts.col.BonusContent.*   -> Bonus clips
  uts.col.CastAndCrew.*    -> Cast & Crew
  uts.marker.About         -> Show info (title, genres, synopsis)
  uts.marker.Info          -> Technical info (content advisory, audio, subtitles)
"""

import json
import datetime


def safe_get(data, *keys, fallback=None):
    """Walk a chain of dict keys safely; return fallback if any key is missing."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return fallback
        current = current.get(key)
        if current is None:
            return fallback
    return current


def ms_to_year(ms):
    """Unix timestamp in milliseconds -> 4-digit year string, or ''."""
    if ms is None:
        return ""
    try:
        return str(
            datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).year
        )
    except (OSError, OverflowError, ValueError):
        return ""


def ms_to_date(ms):
    """Unix timestamp in milliseconds -> 'YYYY-MM-DD' string, or ''."""
    if ms is None:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            ms / 1000, datetime.timezone.utc
        ).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def secs_to_duration(seconds):
    """Integer seconds -> '49 min' or '1h 2m' string, or ''."""
    if seconds is None:
        return ""
    mins = seconds // 60
    hours = mins // 60
    if hours > 0:
        return f"{hours}h {mins % 60}m"
    return f"{mins} min"


def split_comma(text):
    """Split a simple comma-separated string into a trimmed list (no empties)."""
    if not text:
        return []
    result = []
    for piece in text.split(","):
        piece = piece.strip()
        if piece:
            result.append(piece)
    return result


def split_language(text):
    """
    Split audio/subtitle strings where entries are delimited by '), '.
    Each entry contains commas internally (e.g. 'English (AD, Dolby Atmos, AAC)'),
    so a plain comma-split would break them apart.
    """
    if not text:
        return []
    pieces = text.split("), ")
    result = []
    for i in range(len(pieces)):
        piece = pieces[i].strip()
        if not piece:
            continue
        # Re-attach the ')' that split() consumed — all pieces except the last lost it
        if i < len(pieces) - 1:
            piece = piece + ")"
        result.append(piece)
    return result


def get_page(monarch_2):
    """
    Return the show page data object from monarch_2.

    Searches by intent.$kind = 'ShowPageIntent' instead of a fixed index,
    so it works regardless of how many intent objects come before it.
    """
    for item in monarch_2.get("data", []):
        if item.get("intent", {}).get("$kind") == "ShowPageIntent":
            return item["data"]
    raise ValueError(
        "ShowPageIntent not found in monarch_2 — unexpected file structure."
    )


def find_shelf(shelves, id_substring):
    """
    Return the first shelf whose 'id' contains id_substring, or None.

    Shelf IDs look like 'uts.marker.EpisodeList' or 'uts.col.Trailers.umc.cmc.XXXX'.
    Matching by substring works for both fixed markers and show-specific IDs.
    """
    for shelf in shelves:
        if id_substring in shelf.get("id", ""):
            return shelf
    return None


def extract_series_fields(monarch_1, monarch_2):
    """Return a dict of all top-level series fields."""
    page = get_page(monarch_2)
    shelves = page["shelves"]

    shelf_episodes = find_shelf(shelves, "uts.marker.EpisodeList")
    shelf_about = find_shelf(shelves, "uts.marker.About")
    shelf_info = find_shelf(shelves, "uts.marker.Info")

    # Show title, synopsis, genres — About shelf has exactly one item
    about = shelf_about["items"][0]

    # Content advisory, audio languages, subtitles — Info shelf
    s0 = shelf_info["items"][0].get("items", [])  # content advisory row
    s1 = shelf_info["items"][1].get("items", [])  # audio / subtitle row

    audio_raw = s1[1].get("info", "") if len(s1) > 1 else ""
    # Strip invisible Unicode bidi-isolate chars Apple TV injects around "Dolby 5.1"
    audio_clean = audio_raw.replace("\u2068", "").replace("\u2069", "")

    # Release year: use the earliest episode release date from monarch_1
    # (avoids depending on any hardcoded playable key, which changes per show)
    ep_dates = []
    for ep in monarch_1["data"]["episodes"]:
        if ep.get("releaseDate"):
            ep_dates.append(ep["releaseDate"])
    release_year = ms_to_year(min(ep_dates)) if ep_dates else ""

    seasons_list = safe_get(shelf_episodes, "header", "seasons", fallback=[])

    return {
        "series_id": safe_get(shelf_episodes, "header", "id", fallback=""),
        "series_url": page.get("canonicalURL", ""),
        "title": about.get("title", ""),
        "is_new_series": False,
        "ranking": "",
        "synopsis": about.get("description", ""),
        "genres": about.get("genres", []),
        "imdb_rating": "",
        "release_year": release_year,
        "total_seasons_count": len(seasons_list),
        "content_advisory": split_comma(s0[2].get("info", "") if len(s0) > 2 else ""),
        "audio_languages": split_language(audio_clean),
        "subtitles": split_language(s1[2].get("info", "") if len(s1) > 2 else ""),
        "studio": safe_get(page, "channel", "title", fallback=""),
        "seasons_list": seasons_list,  # passed through to assemble_output
    }


# Subtitle values that identify crew roles rather than actor character names.
# Add more here if other shows have different role labels (e.g. "Co-Producer").
PRODUCER_SUBTITLES = {"Executive Producer", "Producer", "Co-Executive Producer"}


def extract_cast_and_crew(shelves):
    """
    Split the CastAndCrew shelf into two separate lists:
      - cast_list:      actors (subtitle = character name)
      - producers_list: crew  (subtitle = role like "Executive Producer")

    Each entry is a dict: {"name": "...", "designation": "..."}
    Returns two lists: cast_list, producers_list
    """
    shelf = find_shelf(shelves, "uts.col.CastAndCrew.")
    if not shelf:
        return [], []

    cast_list = []
    producers_list = []
    seen_names = set()

    for item in shelf.get("items", []):
        name = item.get("title", "").strip()
        subtitle = item.get("subtitle", "").strip()

        if not name or name in seen_names:
            continue
        seen_names.add(name)

        entry = {"name": name, "designation": subtitle}

        if subtitle in PRODUCER_SUBTITLES:
            producers_list.append(entry)
        else:
            cast_list.append(entry)

    return cast_list, producers_list


def extract_trailers_and_bonus(shelves):
    """
    Return a combined list of trailers (shelf Trailers) and bonus clips (shelf BonusContent).

    Trailers:  title/URL from item.contextAction; thumbnail/duration from playlistItems.
    Bonus:     title/URL from item.contextAction; thumbnail from item.artwork.template;
               duration from item.playAction.contentDescriptor.items[0].playable.canonicalMetadata.duration
    """
    seen_urls = set()
    results = []

    # ── Trailers ──
    shelf_trailers = find_shelf(shelves, "uts.col.Trailers.")
    if shelf_trailers:
        trailer_items = shelf_trailers.get("items", [])
        playlist_items = shelf_trailers.get("playlistItems", [])

        for i in range(len(trailer_items)):
            item = trailer_items[i]
            ca = item.get("contextAction", {})
            url = ca.get("url", "")

            if url in seen_urls:
                continue
            seen_urls.add(url)

            playlist = (
                playlist_items[i].get("playlist", {}) if i < len(playlist_items) else {}
            )
            duration_secs = safe_get(playlist, "tabData", "duration")
            duration_str = f"{duration_secs}s" if duration_secs is not None else ""

            results.append(
                {
                    "title": ca.get("title", ""),
                    "video_stream_url": url,
                    "thumbnail_url": safe_get(
                        playlist, "lockup", "artwork", "template", fallback=""
                    ),
                    "content_rating": "",
                    "duration": duration_str,
                }
            )

    # ── Bonus clips ──
    shelf_bonus = find_shelf(shelves, "uts.col.BonusContent.")
    if shelf_bonus:
        for item in shelf_bonus.get("items", []):
            ca = item.get("contextAction", {})
            url = ca.get("url", "")

            if url in seen_urls:
                continue
            seen_urls.add(url)

            cd_items = safe_get(
                item, "playAction", "contentDescriptor", "items", fallback=[]
            )
            duration_secs = (
                safe_get(cd_items[0], "playable", "canonicalMetadata", "duration")
                if cd_items
                else None
            )
            duration_str = f"{duration_secs}s" if duration_secs is not None else ""

            results.append(
                {
                    "title": ca.get("title", ""),
                    "video_stream_url": url,
                    "thumbnail_url": safe_get(item, "artwork", "template", fallback=""),
                    "content_rating": "",
                    "duration": duration_str,
                }
            )

    return results


def build_m2_episode_lookup(shelves):
    """
    Return a dict {episodeIndex: item} for all EpisodeLockup rows in the EpisodeList shelf.
    episodeIndex is a 0-based global counter across all seasons.
    """
    shelf = find_shelf(shelves, "uts.marker.EpisodeList")
    if not shelf:
        return {}

    lookup = {}
    for item in shelf.get("items", []):
        if item.get("$kind") == "EpisodeLockup" and "episodeIndex" in item:
            lookup[item["episodeIndex"]] = item
    return lookup


def extract_season_episodes(season_number, season_start_index, monarch_1, m2_ep_lookup):
    """
    Build the episode list for one season.

    season_number:      1-based (1, 2, 3 ...)
    season_start_index: the episodeIndex in monarch_2 where this season begins.
                        Calculated as the sum of all previous seasons' episode counts.

    Season 1: monarch_1 is the primary source (has release dates, exact durations,
              thumbnails). monarch_2 fills in any missing fields.
    Season 2+: monarch_2 is the only source (monarch_1 only covers season 1).
    """
    episodes = []
    seen_numbers = set()

    if season_number == 1:
        # Season 1 — use monarch_1 as primary, monarch_2 to fill gaps
        for ep in monarch_1["data"]["episodes"]:
            num = ep.get("episodeNumber")
            if num in seen_numbers:
                continue
            seen_numbers.add(num)

            rating_obj = ep.get("rating", {})
            thumbnail = safe_get(ep, "images", "contentImage", "url", fallback="")
            url = ep.get("url", "")
            duration = secs_to_duration(ep.get("duration"))

            # Fill gaps from monarch_2 where it has this episode (ep6-10, index 5-9)
            m2_ep = m2_ep_lookup.get(ep.get("episodeIndex"))
            if m2_ep:
                if not thumbnail:
                    thumbnail = safe_get(m2_ep, "artwork", "template", fallback="")
                if not url:
                    url = safe_get(m2_ep, "segue", "url", fallback="")
                if not duration:
                    duration = m2_ep.get("metadata", "")

            episodes.append(
                {
                    "episode_number": num,
                    "episode_title": ep.get("title", ""),
                    "episode_url": url,
                    "thumbnail_url": thumbnail,
                    "synopsis": ep.get("description", ""),
                    "content_rating": (
                        rating_obj.get("displayName", "")
                        if isinstance(rating_obj, dict)
                        else ""
                    ),
                    "duration": duration,
                    "release_date": ms_to_date(ep.get("releaseDate")),
                }
            )

    else:
        # Season 2+ — monarch_2 only
        for ep_index in m2_ep_lookup:
            ep = m2_ep_lookup[ep_index]
            num = ep_index - season_start_index + 1

            if num in seen_numbers:
                continue
            seen_numbers.add(num)

            episodes.append(
                {
                    "episode_number": num,
                    "episode_title": ep.get("title", ""),
                    "episode_url": safe_get(ep, "segue", "url", fallback=""),
                    "thumbnail_url": safe_get(ep, "artwork", "template", fallback=""),
                    "synopsis": ep.get("description", ""),
                    "content_rating": "",
                    "duration": ep.get("metadata", ""),
                    "release_date": "",
                }
            )

    episodes.sort(key=lambda e: e["episode_number"])
    return episodes


def assemble_output(monarch_1, monarch_2):
    """Put all extracted pieces together into the final output dictionary."""
    page = get_page(monarch_2)
    shelves = page["shelves"]
    m2_ep_lookup = build_m2_episode_lookup(shelves)

    # Extract all series-level fields (title, synopsis, genres, etc.)
    series = extract_series_fields(monarch_1, monarch_2)
    seasons_list = series.pop("seasons_list")  # remove internal key before output

    # Build seasons with episodes
    # season_start_index tracks the cumulative episodeIndex offset:
    #   S1 starts at 0, S2 at S1.episodeCount, S3 at S1+S2.episodeCount, etc.
    seasons = []
    season_start_index = 0

    for s in seasons_list:
        season_number = s.get("seasonNumber")
        ep_count = s.get("episodeCount", 0)

        # For season 2+, slice only the episodes that belong to this season
        if season_number == 1:
            season_lookup = m2_ep_lookup
        else:
            next_index = season_start_index + ep_count
            season_lookup = {}
            for idx in m2_ep_lookup:
                if season_start_index <= idx < next_index:
                    season_lookup[idx] = m2_ep_lookup[idx]

        episodes = extract_season_episodes(
            season_number=season_number,
            season_start_index=season_start_index,
            monarch_1=monarch_1,
            m2_ep_lookup=season_lookup,
        )

        seasons.append(
            {
                "season_label": s.get("title", f"Season {season_number}"),
                "total_episodes_count": ep_count,
                "episodes": episodes,
            }
        )

        season_start_index += ep_count

    # Extract cast and producers as two separate lists
    cast_list, producers_list = extract_cast_and_crew(shelves)

    # Build and return the final output dict
    output = {
        "series_id": series["series_id"],
        "series_url": series["series_url"],
        "title": series["title"],
        "is_new_series": series["is_new_series"],
        "ranking": series["ranking"],
        "synopsis": series["synopsis"],
        "genres": series["genres"],
        "imdb_rating": series["imdb_rating"],
        "release_year": series["release_year"],
        "total_seasons_count": series["total_seasons_count"],
        "content_advisory": series["content_advisory"],
        "audio_languages": series["audio_languages"],
        "subtitles": series["subtitles"],
        "creators_and_cast": {
            "cast_and_crew": cast_list,
            "producers": producers_list,
            "studio": series["studio"],
        },
        "trailers_and_bonus": extract_trailers_and_bonus(shelves),
        "seasons": seasons,
    }
    return output


def main():
    BASE = r"C:\Users\parth.khatri\Desktop\github\apple-tv"
    monarch_1 = json.load(open(f"{BASE}\\monarch_1.json", encoding="utf-8"))
    monarch_2 = json.load(open(f"{BASE}\\monarch_2.json", encoding="utf-8"))
    output = assemble_output(monarch_1, monarch_2)
    json.dump(
        output,
        open(f"{BASE}\\monarch_output.json", "w", encoding="utf-8"),
        indent=2,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
