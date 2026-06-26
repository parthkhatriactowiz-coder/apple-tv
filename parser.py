"""
Monarch JSON Extractor
======================
Reads monarch_1.json (S1 episode details) and monarch_2.json (full page layout)
and extracts all fields into a clean, structured output JSON.

Designed to work across multiple Apple TV show pages — no hardcoded show IDs,
shelf indexes, or episode counts.

monarch_2 shelf types (matched by ID substring, not position):
  uts.marker.EpisodeList   → Episode grid (EpisodeLockup rows, all seasons)
  uts.col.Trailers.*       → Trailers
  uts.col.BonusContent.*   → Bonus clips
  uts.col.CastAndCrew.*    → Cast & Crew
  uts.marker.About         → Show info (title, genres, synopsis)
  uts.marker.Info          → Technical info (content advisory, audio, subtitles)
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
    """Unix timestamp in milliseconds → 4-digit year string, or ''."""
    if ms is None:
        return ""
    try:
        return str(
            datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).year
        )
    except (OSError, OverflowError, ValueError):
        return ""


def ms_to_date(ms):
    """Unix timestamp in milliseconds → 'YYYY-MM-DD' string, or ''."""
    if ms is None:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            ms / 1000, datetime.timezone.utc
        ).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def secs_to_duration(seconds):
    """Integer seconds → '49 min' or '1h 2m' string, or ''."""
    if seconds is None:
        return ""
    mins = seconds // 60
    hours = mins // 60
    return f"{hours}h {mins % 60}m" if hours else f"{mins} min"


def split_comma(text):
    """Split a simple comma-separated string into a trimmed list (no empties)."""
    return [p.strip() for p in text.split(",") if p.strip()] if text else []


def split_language(text):
    """
    Split audio/subtitle strings where entries are delimited by '), '.
    Each entry contains commas internally (e.g. 'English (AD, Dolby Atmos, AAC)'),
    so a plain comma-split would break them apart.
    """
    if not text:
        return []
    pieces = text.split("), ")
    # Re-attach the ')' that split() consumed — all pieces except the last lost it
    return [
        (p.strip() + ")" if i < len(pieces) - 1 else p.strip())
        for i, p in enumerate(pieces)
        if p.strip()
    ]


def get_page(monarch_2):
    """
    Return the show page data object from monarch_2.

    monarch_2["data"] is a list of intent objects. We find the one whose
    intent.$kind is "ShowPageIntent" rather than assuming a fixed index,
    so this works regardless of how many intent objects precede it.
    """
    for item in monarch_2.get("data", []):
        if item.get("intent", {}).get("$kind") == "ShowPageIntent":
            return item["data"]
    raise ValueError(
        "ShowPageIntent not found in monarch_2 data — unexpected file structure."
    )


def find_shelf(shelves, id_substring):
    """
    Return the first shelf whose 'id' contains id_substring, or None.

    Shelf IDs have two formats:
      - Fixed markers:  'uts.marker.EpisodeList', 'uts.marker.About', 'uts.marker.Info'
      - Show-specific:  'uts.col.Trailers.umc.cmc.XXXX', 'uts.col.CastAndCrew.umc.cmc.XXXX'

    Matching by substring handles both: 'uts.col.Trailers.' matches any show's
    trailer shelf regardless of the show ID appended to it.
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

    # Show info — About shelf, single item
    about = shelf_about["items"][0]

    # Technical info — Info shelf
    s0 = shelf_info["items"][0].get("items", [])  # content advisory row
    s1 = shelf_info["items"][1].get("items", [])  # audio / subtitle row

    audio_raw = s1[1].get("info", "") if len(s1) > 1 else ""
    # Strip invisible Unicode bidi-isolate chars Apple TV injects around "Dolby 5.1"
    audio_clean = audio_raw.replace("\u2068", "").replace("\u2069", "")

    # Release year: find the earliest episode release date across all episodes in
    # monarch_1. This avoids depending on any specific hardcoded playable key,
    # which changes per show.
    ep_dates = [
        ep.get("releaseDate")
        for ep in monarch_1["data"]["episodes"]
        if ep.get("releaseDate")
    ]
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
        "_seasons_list": seasons_list,
    }


# Subtitle values that identify crew roles rather than actor character names.
# Items whose subtitle matches one of these are routed to the producers list;
# all others are treated as cast (subtitle = character name).
PRODUCER_SUBTITLES = {"Executive Producer", "Producer", "Co-Executive Producer"}


def extract_cast_and_crew(shelves):
    """
    Split the CastAndCrew shelf into two deduplicated lists:
      - cast:      people whose subtitle is a character name (actors)
      - producers: people whose subtitle is a crew role (e.g. "Executive Producer")

    Each entry is a dict with "name" and "designation" so downstream consumers
    know both the person and their role/character without needing to infer it.

    Returns a tuple: (cast_list, producers_list)
    """
    shelf = find_shelf(shelves, "uts.col.CastAndCrew.")
    if not shelf:
        return [], []

    cast = []
    producers = []
    seen = set()

    for item in shelf.get("items", []):
        name = item.get("title", "").strip()
        subtitle = item.get("subtitle", "").strip()

        if not name or name in seen:
            continue
        seen.add(name)

        entry = {"name": name, "designation": subtitle}

        if subtitle in PRODUCER_SUBTITLES:
            producers.append(entry)
        else:
            cast.append(entry)

    return cast, producers


def extract_trailers_and_bonus(shelves):
    """
    Return a combined list of trailers and bonus clips.

    Trailers shelf (uts.col.Trailers.*):
      title/URL from item.contextAction
      thumbnail/duration from parallel playlistItems[i].playlist

    Bonus shelf (uts.col.BonusContent.*):
      title/URL from item.contextAction
      thumbnail from item.artwork.template
      duration from item.playAction.contentDescriptor.items[0].playable.canonicalMetadata.duration
    """
    seen_urls = set()
    results = []

    # ── Trailers ──
    shelf_trailers = find_shelf(shelves, "uts.col.Trailers.")
    if shelf_trailers:
        trailer_items = shelf_trailers.get("items", [])
        playlist_items = shelf_trailers.get("playlistItems", [])

        for i, item in enumerate(trailer_items):
            ca = item.get("contextAction", {})
            url = ca.get("url", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            playlist = (
                playlist_items[i].get("playlist", {}) if i < len(playlist_items) else {}
            )
            duration_secs = safe_get(playlist, "tabData", "duration")

            results.append(
                {
                    "title": ca.get("title", ""),
                    "video_stream_url": url,
                    "thumbnail_url": safe_get(
                        playlist, "lockup", "artwork", "template", fallback=""
                    ),
                    "content_rating": "",
                    "duration": (
                        f"{duration_secs}s" if duration_secs is not None else ""
                    ),
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

            results.append(
                {
                    "title": ca.get("title", ""),
                    "video_stream_url": url,
                    "thumbnail_url": safe_get(item, "artwork", "template", fallback=""),
                    "content_rating": "",
                    "duration": (
                        f"{duration_secs}s" if duration_secs is not None else ""
                    ),
                }
            )

    return results


def build_m2_episode_lookup(shelves):
    """
    Return {episodeIndex: item} for all EpisodeLockup rows in the EpisodeList shelf.
    episodeIndex is a 0-based global counter across all seasons.
    """
    shelf = find_shelf(shelves, "uts.marker.EpisodeList")
    if not shelf:
        return {}
    return {
        item["episodeIndex"]: item
        for item in shelf.get("items", [])
        if item.get("$kind") == "EpisodeLockup" and "episodeIndex" in item
    }


def extract_season_episodes(season_number, season_start_index, monarch_1, m2_ep_lookup):
    """
    Build the episode list for a single season.

    season_number:      1-based (1, 2, 3 ...)
    season_start_index: the episodeIndex in monarch_2 where this season begins.
                        Derived from the sum of all previous seasons' episodeCounts,
                        so it works for any show with any number of seasons.

    Season 1 uses monarch_1 as primary source (rich data: release dates, exact
    durations, thumbnails). monarch_2 fills gaps where monarch_1 is missing fields.

    Season 2+ uses monarch_2 only (monarch_1 never contains later seasons).
    """
    episodes = []
    seen = set()

    if season_number == 1:
        for ep in monarch_1["data"]["episodes"]:
            num = ep.get("episodeNumber")
            if num in seen:
                continue
            seen.add(num)

            rating_obj = ep.get("rating", {})
            thumbnail = safe_get(ep, "images", "contentImage", "url", fallback="")
            url = ep.get("url", "")
            duration = secs_to_duration(ep.get("duration"))

            # Supplement from monarch_2 for episodes it covers
            m2 = m2_ep_lookup.get(ep.get("episodeIndex"))
            if m2:
                thumbnail = thumbnail or safe_get(
                    m2, "artwork", "template", fallback=""
                )
                url = url or safe_get(m2, "segue", "url", fallback="")
                duration = duration or m2.get("metadata", "")

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
        # ── Season 2+: monarch_2 only ──
        # All episodes for this season sit between season_start_index and
        # the next season's start. We just check idx >= season_start_index
        # and convert to a 1-based episode number within the season.
        for idx, ep in m2_ep_lookup.items():
            if idx < season_start_index:
                continue
            # Stop if we've crossed into the next season's index range.
            # We calculate this by checking the global ep index against the
            # next boundary — but since we only call this per-season and
            # assemble_output slices by start index, we filter in assemble_output.
            num = idx - season_start_index + 1
            if num in seen:
                continue
            seen.add(num)

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
    page = get_page(monarch_2)
    shelves = page["shelves"]
    m2_ep_lookup = build_m2_episode_lookup(shelves)

    series = extract_series_fields(monarch_1, monarch_2)
    seasons_list = series.pop("_seasons_list")  # internal key, not in output

    # Build a per-season episode list.
    # season_start_index is the cumulative sum of all previous seasons' episode counts.
    # Example for a 3-season show with 10/8/6 eps:
    #   S1 start = 0,  S2 start = 10,  S3 start = 18
    # This works for any show without hardcoding episode counts.
    seasons = []
    cumulative_index = 0

    for s in seasons_list:
        season_number = s.get("seasonNumber")
        ep_count = s.get("episodeCount", 0)

        # For season 2+, only pass the slice of m2_ep_lookup relevant to this season
        # (from cumulative_index up to cumulative_index + ep_count)
        if season_number == 1:
            season_lookup = m2_ep_lookup
        else:
            next_index = cumulative_index + ep_count
            season_lookup = {
                idx: ep
                for idx, ep in m2_ep_lookup.items()
                if cumulative_index <= idx < next_index
            }

        episodes = extract_season_episodes(
            season_number=season_number,
            season_start_index=cumulative_index,
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

        cumulative_index += ep_count

    cast_list, producers_list = extract_cast_and_crew(shelves)

    return {
        **{
            k: series[k]
            for k in [
                "series_id",
                "series_url",
                "title",
                "is_new_series",
                "ranking",
                "synopsis",
                "genres",
                "imdb_rating",
                "release_year",
                "total_seasons_count",
                "content_advisory",
                "audio_languages",
                "subtitles",
            ]
        },
        "creators_and_cast": {
            "cast_and_crew": cast_list,
            "producers": producers_list,
            "studio": series["studio"],
        },
        "trailers_and_bonus": extract_trailers_and_bonus(shelves),
        "seasons": seasons,
    }


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
