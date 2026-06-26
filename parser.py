"""
Monarch JSON Extractor
======================
Reads two source JSON files and extracts all required fields into a clean,
structured output JSON.

monarch_1.json  --> Season 1 episode details: descriptions, release dates,
                    durations (in seconds), thumbnails.

monarch_2.json  --> Full page layout (shelves). Holds series-level info,
                    season metadata, trailers, bonus content, cast & crew,
                    and partial episode data for both seasons.

How the shelves in monarch_2 are laid out:
  shelves[0]  → Canonical header (series ID, canonical URL)
  shelves[1]  → Episode grid (EpisodeLockup rows for both seasons)
  shelves[2]  → Official trailers
  shelves[3]  → Bonus clips
  shelves[4]  → Related content  (not used)
  shelves[5]  → Cast & Crew (24 PersonLockup items)
  shelves[6]  → How to watch   (not used)
  shelves[7]  → About / show info (title, genres, synopsis)
  shelves[8]  → Technical info (rating, languages, subtitles)
"""

import json
import datetime


def safe_get(data, *keys, fallback=None):
    """
    Safely walk a chain of dictionary keys without crashing.

    Normally if you write  d["a"]["b"]["c"]  and "b" is missing, Python
    raises a KeyError.  This function returns `fallback` (default: None)
    instead of crashing.

    Example:
        safe_get(d, "a", "b", "c")   # same as d["a"]["b"]["c"] but safe
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return fallback
        current = current.get(key)
        if current is None:
            return fallback
    return current


def split_comma_string_to_list(text):
    """
    Convert a simple comma-separated string into a clean Python list.

    Use this for fields where each entry does NOT contain commas itself,
    such as content_advisory: "Language, Violence, Horror".

    Steps:
      1. Split on every comma.
      2. Strip leading/trailing whitespace from each piece.
      3. Discard any empty pieces (e.g. from a trailing comma).

    Example:
        "Language, Violence, " → ["Language", "Violence"]
    """
    if not text:
        return []

    result = []
    # Split on commas to get individual pieces
    pieces = text.split(",")
    for piece in pieces:
        clean_piece = piece.strip()  # remove surrounding spaces
        if clean_piece:  # skip empty strings
            result.append(clean_piece)
    return result


def split_language_string_to_list(text):
    """
    Convert an audio-language or subtitle string into a clean Python list.

    This is different from split_comma_string_to_list because each language
    entry CONTAINS commas inside its parentheses. For example:

        "English (AD, Dolby Atmos, Dolby 5.1, AAC), French (Canada) (AD, ...)"

    A plain comma split would shatter "Dolby Atmos, Dolby 5.1, AAC" into
    separate pieces.

    The correct delimiter here is "), " — every entry ends with a closing
    parenthesis and is followed by a comma+space before the next entry.

    Strategy:
      1. Split on "), " (the boundary between entries).
      2. Re-attach ")" to every piece except the last one (which already
         ends with its own closing paren).
      3. Strip whitespace and skip empty pieces.

    Example:
        "English (CC, SDH), Arabic (SDH), Bulgarian (SDH)"
        → ["English (CC, SDH)", "Arabic (SDH)", "Bulgarian (SDH)"]
    """
    if not text:
        return []

    pieces = text.split("), ")

    result = []
    for i in range(len(pieces)):
        piece = pieces[i].strip()
        if not piece:
            continue


        if i < len(pieces) - 1:
            piece = piece + ")"

        result.append(piece)

    return result


def milliseconds_to_year(timestamp_ms):
    """
    Convert a Unix timestamp in milliseconds to a 4-digit year string.

    Apple TV stores dates as milliseconds since the Unix epoch (Jan 1, 1970).
    Python's datetime functions expect seconds, so we divide by 1000 first.

    Returns "" if the timestamp is None or invalid.
    """
    if timestamp_ms is None:
        return ""
    try:
        timestamp_seconds = timestamp_ms / 1000
        year = datetime.datetime.utcfromtimestamp(timestamp_seconds).year
        return str(year)
    except (OSError, OverflowError, ValueError):
        return ""


def milliseconds_to_date_string(timestamp_ms):
    """
    Convert a Unix timestamp in milliseconds to a "YYYY-MM-DD" date string.
    """
    if timestamp_ms is None:
        return ""
    try:
        timestamp_seconds = timestamp_ms / 1000
        dt = datetime.datetime.utcfromtimestamp(timestamp_seconds)
        return dt.strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def seconds_to_duration_string(seconds):
    """
    Convert an integer number of seconds into a human-readable duration string.
    """
    if seconds is None:
        return ""
    minutes = seconds // 60
    hours = minutes // 60
    remaining_mins = minutes % 60
    if hours > 0:
        return f"{hours}h {remaining_mins}m"
    return f"{minutes} min"


def load_json_file(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)
    return data


def write_json_file(data, output_path):
    with open(output_path, "w", encoding="utf-8") as out_file:
        json.dump(data, out_file, indent=2, ensure_ascii=False)


def get_shelves(monarch_2):
    """
    Return the list of shelf objects from monarch_2.

    The full path is: monarch_2["data"][1]["data"]["shelves"]
    We extract this once here so every other function can call get_shelves()
    instead of repeating the long chain.
    """
    return monarch_2["data"][1]["data"]["shelves"]


def get_page_object(monarch_2):
    """
    Return the top-level page object from monarch_2.

    This is used to access canonicalURL, channel, and other page-level fields.
    """
    return monarch_2["data"][1]["data"]


def extract_series_id(shelves):
    """
    Extract the series' unique internal ID.

    Location: shelves[1] → header → id
    The value looks like "ShelfHeader#20070".

    shelves[1] is the episode grid shelf. Its header contains the ID that
    Apple TV uses to identify this show's episode list.
    """
    shelf_episodes = shelves[1]
    series_id = safe_get(shelf_episodes, "header", "id", fallback="")
    return series_id


def extract_series_url(monarch_2):
    """
    Extract the canonical (clean, permanent) URL for the show's page.

    Location: monarch_2["data"][1]["data"] → canonicalURL
    """
    page = get_page_object(monarch_2)
    return page.get("canonicalURL", "")


def extract_show_info(shelves):
    """
    Extract the show's title, synopsis, and genres from shelves[7].

    shelves[7] is the "About" shelf. It has exactly one item that contains
    the show's display title, long description, and genre tags.

    Returns a dict with keys: title, synopsis, genres
    """
    shelf_about = shelves[7]
    # There is exactly one item in this shelf
    about_item = shelf_about["items"][0]

    title = about_item.get("title", "")
    synopsis = about_item.get("description", "")
    genres = about_item.get("genres", [])  # already a plain list in the source

    return {
        "title": title,
        "synopsis": synopsis,
        "genres": genres,
    }


def extract_seasons_metadata(shelves):
    """
    Extract the list of seasons and total season count from shelves[1].

    The header of the episode shelf contains a "seasons" array. Each entry has:
      - seasonNumber  (1, 2, ...)
      - title         ("Season 1", "Season 2", ...)
      - episodeCount  (total number of episodes in that season)

    Returns a tuple: (seasons_list, total_seasons_count)
      - seasons_list is the raw list from the JSON (used later to build output)
      - total_seasons_count is just len(seasons_list)
    """
    shelf_episodes = shelves[1]
    seasons_list = safe_get(shelf_episodes, "header", "seasons", fallback=[])
    total_seasons_count = len(seasons_list)
    return seasons_list, total_seasons_count


def extract_technical_info(shelves):
    """
    Extract content advisory, audio languages, and subtitle strings from shelves[8].

    shelves[8] is the "Info" shelf. Its structure:
      items[0] → sub-items:
        [0] release year string
        [1] content rating display name (e.g. "U/A 16+")
        [2] content advisory string    ← we want this
        [3] countries of origin
      items[1] → sub-items:
        [0] primary audio language short form
        [1] full audio languages string  ← we want this
        [2] full subtitles string        ← we want this

    Returns a dict with keys: content_advisory, audio_languages, subtitles
    All three are returned as comma-separated strings; the caller can split them.
    """
    shelf_tech = shelves[8]
    tech_items = shelf_tech.get("items", [])

    # Safely get the first and second top-level item from shelf 8
    item_0 = tech_items[0] if len(tech_items) > 0 else {}
    item_1 = tech_items[1] if len(tech_items) > 1 else {}

    sub_items_0 = item_0.get("items", [])
    sub_items_1 = item_1.get("items", [])

    # Content advisory is at sub_items_0[2]
    content_advisory_str = (
        sub_items_0[2].get("info", "") if len(sub_items_0) > 2 else ""
    )

    # Audio languages is at sub_items_1[1]
    audio_languages_raw = sub_items_1[1].get("info", "") if len(sub_items_1) > 1 else ""
    audio_languages_str = audio_languages_raw.replace("\u2068", "").replace("\u2069", "")


    # Subtitles is at sub_items_1[2]
    subtitles_str = sub_items_1[2].get("info", "") if len(sub_items_1) > 2 else ""

    return {
        "content_advisory": content_advisory_str,
        "audio_languages": audio_languages_str,
        "subtitles": subtitles_str,
    }


def extract_release_year(monarch_1):
    """
    Extract the show's release year from monarch_1's playables dictionary.

    The specific playable we use is keyed by "tvs.sbd.4000:A0019601003:978645c3".
    Its "canonicalMetadata.releaseDate" is a Unix timestamp in milliseconds.
    We convert it to a 4-digit year string.

    Returns "" if the key or timestamp is missing.
    """
    playables = monarch_1["data"]["playables"]

    # This specific playable holds the show's canonical release date
    playable_key = "tvs.sbd.4000:A0019601003:978645c3"
    playable_entry = playables.get(playable_key, {})

    timestamp_ms = safe_get(
        playable_entry, "canonicalMetadata", "releaseDate", fallback=None
    )
    return milliseconds_to_year(timestamp_ms)


def extract_studio(monarch_2):
    """
    Extract the studio / channel name from monarch_2's page object.

    Location: monarch_2["data"][1]["data"] → channel → title
    Expected value: "Apple TV"
    """
    page = get_page_object(monarch_2)
    return safe_get(page, "channel", "title", fallback="")


def extract_cast_and_crew(shelves):
    """
    Extract all cast and crew member names from shelves[5].

    shelves[5] is the Cast & Crew shelf. It contains 24 PersonLockup items.
    Each item has a "title" key with the person's name.

    We loop through all items and build a list of names.
    Duplicates are filtered out using a seen_names set (preserves order).

    Returns a list of name strings, e.g.:
      ["Kurt Russell", "Wyatt Russell", "Anna Sawai", ...]
    """
    shelf_cast = shelves[5]
    cast_items = shelf_cast.get("items", [])

    names = []
    seen_names = set()  # tracks names already added to avoid duplicates

    for item in cast_items:
        name = item.get("title", "").strip()
        # Only add this name if it's non-empty and not already in the list
        if name and name not in seen_names:
            seen_names.add(name)
            names.append(name)

    return names


def build_trailer_entry(title, video_stream_url, thumbnail_url, duration_secs):
    """
    Build a single trailer/bonus dictionary in the output format.

    This is a small helper to avoid repeating the same dict structure
    in both the trailers loop and the bonus loop.

    duration_secs can be an integer (seconds) or None.
    """
    if duration_secs is not None:
        duration_str = str(duration_secs) + "s"
    else:
        duration_str = ""

    return {
        "title": title,
        "video_stream_url": video_stream_url,
        "thumbnail_url": thumbnail_url,
        "content_rating": "",  # not available in source data
        "duration": duration_str,
    }


def extract_trailers(shelves, seen_video_urls):
    """
    Extract official trailers from shelves[2].

    Each trailer item has two parallel locations:
      - shelf_trailers["items"][i]
          contextAction.title → trailer title
          contextAction.url   → video stream URL
      - shelf_trailers["playlistItems"][i]  (same index i)
          playlist.lockup.artwork.template  → thumbnail URL
          playlist.tabData.duration         → duration in seconds (integer)

    seen_video_urls is a set passed in from the caller. We add URLs to it
    as we process them so the bonus function can skip duplicates.

    Returns a list of trailer dicts.
    """
    shelf_trailers = shelves[2]
    trailer_items = shelf_trailers.get("items", [])
    playlist_items = shelf_trailers.get("playlistItems", [])

    trailers = []

    for i in range(len(trailer_items)):
        trailer_item = trailer_items[i]

        # Title and URL come from the contextAction sub-object
        context_action = trailer_item.get("contextAction", {})
        trailer_title = context_action.get("title", "")
        video_stream_url = context_action.get("url", "")

        # Skip if we have already added this URL
        if video_stream_url in seen_video_urls:
            continue
        seen_video_urls.add(video_stream_url)

        # Thumbnail and duration come from the matching playlistItems entry
        if i < len(playlist_items):
            playlist_entry = playlist_items[i].get("playlist", {})
            thumbnail_url = safe_get(
                playlist_entry, "lockup", "artwork", "template", fallback=""
            )
            duration_secs = safe_get(
                playlist_entry, "tabData", "duration", fallback=None
            )
        else:
            thumbnail_url = ""
            duration_secs = None

        entry = build_trailer_entry(
            trailer_title, video_stream_url, thumbnail_url, duration_secs
        )
        trailers.append(entry)

    return trailers


def extract_bonus_content(shelves, seen_video_urls):
    """
    Extract bonus clips from shelves[3].

    Bonus items have a slightly different structure from trailers:
      - contextAction.title / contextAction.url  → title and stream URL  (same as trailers)
      - artwork.template                          → thumbnail URL  (directly on the item)
      - playAction.contentDescriptor.items[0]
          .playable.canonicalMetadata.duration    → duration in seconds

    seen_video_urls is the same set passed from the caller (shared with trailers)
    so that videos appearing in both shelves are not duplicated.

    Returns a list of bonus clip dicts.
    """
    shelf_bonus = shelves[3]
    bonus_items = shelf_bonus.get("items", [])

    bonus_clips = []

    for bonus_item in bonus_items:
        context_action = bonus_item.get("contextAction", {})
        bonus_title = context_action.get("title", "")
        video_stream_url = context_action.get("url", "")

        # Skip duplicates
        if video_stream_url in seen_video_urls:
            continue
        seen_video_urls.add(video_stream_url)

        # Thumbnail is directly under artwork (not inside playlist like trailers)
        thumbnail_url = safe_get(bonus_item, "artwork", "template", fallback="")

        # Duration is buried inside the playAction → contentDescriptor chain
        play_action = bonus_item.get("playAction", {})
        cd_items = safe_get(play_action, "contentDescriptor", "items", fallback=[])
        duration_secs = None
        if cd_items:
            duration_secs = safe_get(
                cd_items[0], "playable", "canonicalMetadata", "duration", fallback=None
            )

        entry = build_trailer_entry(
            bonus_title, video_stream_url, thumbnail_url, duration_secs
        )
        bonus_clips.append(entry)

    return bonus_clips


def extract_trailers_and_bonus(shelves):
    """
    Combine trailers (shelf 2) and bonus clips (shelf 3) into a single list.

    We use a shared seen_video_urls set across both calls so a video that
    appears in both shelves is only included once in the final output.

    Returns a combined list: trailers first, then bonus clips.
    """
    seen_video_urls = set()  # shared across both shelf extractions

    trailers = extract_trailers(shelves, seen_video_urls)
    bonus_clips = extract_bonus_content(shelves, seen_video_urls)

    return trailers + bonus_clips


def build_m2_episode_lookup(shelves):
    """
    Build a dictionary that lets us quickly find any episode's data from monarch_2.

    We loop through shelves[1] (the episode grid) and collect every item
    whose "$kind" is "EpisodeLockup". We key each one by its episodeIndex
    (a 0-based integer: 0–9 = Season 1, 10–19 = Season 2).

    Returns a dict like: { 5: {...ep6 data...}, 6: {...ep7 data...}, ... }

    monarch_2 only has episodeIndexes 5–15 (S1 ep6–10 and all of S2).
    Episodes 0–4 (S1 ep1–5) exist only in monarch_1.
    """
    shelf_episodes = shelves[1]
    episode_items = shelf_episodes.get("items", [])

    m2_ep_lookup = {}

    for item in episode_items:
        # The episode grid also contains pagination rows — skip those
        if item.get("$kind") != "EpisodeLockup":
            continue

        ep_index = item.get("episodeIndex")
        if ep_index is not None:
            m2_ep_lookup[ep_index] = item

    return m2_ep_lookup


def build_episode_entry(
    episode_number,
    title,
    url,
    thumbnail_url,
    synopsis,
    content_rating,
    duration,
    release_date,
):
    """
    Build a single episode dictionary in the output format.

    This helper exists so both Season 1 and Season 2 loops produce
    episode dicts with exactly the same keys in the same order.
    """
    return {
        "episode_number": episode_number,
        "episode_title": title,
        "episode_url": url,
        "thumbnail_url": thumbnail_url,
        "synopsis": synopsis,
        "content_rating": content_rating,
        "duration": duration,
        "release_date": release_date,
    }


def extract_season1_episodes(monarch_1, m2_ep_lookup):
    """
    Build the list of Season 1 episode dicts.

    monarch_1 is the primary source for Season 1 (10 episodes, index 0–9).
    It provides: title, URL, synopsis, releaseDate (ms), duration (seconds),
    thumbnail, and content_rating.

    monarch_2 provides supplementary data for S1 ep6–10 (episodeIndex 5–9):
    thumbnail template, URL, and a pre-formatted duration string.
    We use monarch_2 data only when monarch_1's value is empty.

    Returns a list of 10 episode dicts, sorted by episode_number.
    """
    m1_episodes = monarch_1["data"]["episodes"]

    season1_episodes = []
    seen_episode_numbers = set()  # prevents accidentally adding duplicates

    for m1_ep in m1_episodes:
        ep_number = m1_ep.get("episodeNumber")  # 1-based: 1, 2, 3 …
        ep_index = m1_ep.get("episodeIndex")  # 0-based: 0, 1, 2 …

        # Guard: skip if we somehow already added this episode number
        if ep_number in seen_episode_numbers:
            continue
        seen_episode_numbers.add(ep_number)

        # ── Primary fields from monarch_1 ──
        ep_title = m1_ep.get("title", "")
        ep_url = m1_ep.get("url", "")
        ep_synopsis = m1_ep.get("description", "")

        # Content rating: monarch_1 stores this as a dict; we want displayName
        rating_obj = m1_ep.get("rating", {})
        ep_content_rating = (
            rating_obj.get("displayName", "") if isinstance(rating_obj, dict) else ""
        )

        # Release date: stored as milliseconds, convert to "YYYY-MM-DD"
        ep_release_date = milliseconds_to_date_string(m1_ep.get("releaseDate"))

        # Duration: stored as seconds (integer), convert to "X min" string
        ep_duration = seconds_to_duration_string(m1_ep.get("duration"))

        # Thumbnail: path is images → contentImage → url
        ep_thumbnail = safe_get(m1_ep, "images", "contentImage", "url", fallback="")

        # ── Supplement with monarch_2 if this episode is available there ──
        # monarch_2 has S1 episodes for indexes 5–9 (ep6–10)
        m2_ep = m2_ep_lookup.get(ep_index)

        if m2_ep is not None:
            # Fill in thumbnail if monarch_1 didn't provide one
            if not ep_thumbnail:
                ep_thumbnail = safe_get(m2_ep, "artwork", "template", fallback="")

            # Fill in URL if monarch_1 didn't provide one
            if not ep_url:
                ep_url = safe_get(m2_ep, "segue", "url", fallback="")

            # Fill in duration if monarch_1 didn't provide one
            if not ep_duration:
                ep_duration = m2_ep.get("metadata", "")

        episode_entry = build_episode_entry(
            episode_number=ep_number,
            title=ep_title,
            url=ep_url,
            thumbnail_url=ep_thumbnail,
            synopsis=ep_synopsis,
            content_rating=ep_content_rating,
            duration=ep_duration,
            release_date=ep_release_date,
        )
        season1_episodes.append(episode_entry)

    # Sort by episode number so they appear in the correct order
    season1_episodes.sort(key=lambda ep: ep["episode_number"])
    return season1_episodes


def extract_season2_episodes(m2_ep_lookup):
    """
    Build the list of Season 2 episode dicts.

    monarch_1 has no Season 2 data. monarch_2 is the only source.

    Season 2 episodes have episodeIndex values starting at 10:
      episodeIndex 10 → Season 2, Episode 1
      episodeIndex 11 → Season 2, Episode 2
      ... and so on.

    We convert from the global 0-based index to a 1-based season-specific
    episode number: ep_number = ep_index - 10 + 1

    Returns a list of episode dicts, sorted by episode_number.
    """
    SEASON_2_START_INDEX = 10  # episodeIndex where Season 2 begins

    season2_episodes = []
    seen_episode_numbers = set()

    for ep_index, m2_ep in m2_ep_lookup.items():
        # Only process Season 2 entries
        if ep_index < SEASON_2_START_INDEX:
            continue

        # Convert global index to season-specific episode number
        ep_number = ep_index - SEASON_2_START_INDEX + 1

        if ep_number in seen_episode_numbers:
            continue
        seen_episode_numbers.add(ep_number)

        # All fields for Season 2 come from monarch_2
        ep_title = m2_ep.get("title", "")
        ep_url = safe_get(m2_ep, "segue", "url", fallback="")
        ep_thumbnail = safe_get(m2_ep, "artwork", "template", fallback="")
        ep_synopsis = m2_ep.get("description", "")
        ep_duration = m2_ep.get("metadata", "")  # already a string like "45 min"

        episode_entry = build_episode_entry(
            episode_number=ep_number,
            title=ep_title,
            url=ep_url,
            thumbnail_url=ep_thumbnail,
            synopsis=ep_synopsis,
            content_rating="",  # not available in monarch_2 for Season 2
            duration=ep_duration,
            release_date="",  # not available in monarch_2 for Season 2
        )
        season2_episodes.append(episode_entry)

    season2_episodes.sort(key=lambda ep: ep["episode_number"])
    return season2_episodes


def build_seasons_output(seasons_list, season1_episodes, season2_episodes):
    """
    Build the final "seasons" list for the output JSON.

    seasons_list is the raw list from monarch_2's episode shelf header.
    Each entry has: seasonNumber, title ("Season 1"), episodeCount.

    We match each entry to the correct episodes list and wrap them together.

    Returns a list of season dicts, one per season.
    """
    seasons_output = []

    for season_info in seasons_list:
        season_number = season_info.get("seasonNumber")
        season_label = season_info.get("title", f"Season {season_number}")
        episode_count = season_info.get("episodeCount", 0)

        # Pick the matching episodes list
        if season_number == 1:
            episodes_for_season = season1_episodes
        elif season_number == 2:
            episodes_for_season = season2_episodes
        else:
            episodes_for_season = []

        seasons_output.append(
            {
                "season_label": season_label,
                "total_episodes_count": episode_count,
                "episodes": episodes_for_season,
            }
        )

    return seasons_output


def assemble_output(monarch_1, monarch_2):
    """
    Orchestrate all extraction steps and return the final output dictionary.

    This is the main function that calls all the helpers above in order:
      1. Get shelf shortcuts
      2. Extract each group of fields
      3. Convert comma-separated strings to lists
      4. Assemble into the final dict

    Returns the complete output dict ready to be written to JSON.
    """
    shelves = get_shelves(monarch_2)

    m2_ep_lookup = build_m2_episode_lookup(shelves)

    series_id = extract_series_id(shelves)
    series_url = extract_series_url(monarch_2)
    show_info = extract_show_info(shelves)
    seasons_list, total_seasons_count = extract_seasons_metadata(shelves)
    release_year = extract_release_year(monarch_1)
    studio = extract_studio(monarch_2)

    tech_info = extract_technical_info(shelves)

    content_advisory_list = split_comma_string_to_list(tech_info["content_advisory"])
    audio_languages_list = split_language_string_to_list(tech_info["audio_languages"])
    subtitles_list = split_language_string_to_list(tech_info["subtitles"])

    cast_and_crew_list = extract_cast_and_crew(shelves)

    trailers_and_bonus = extract_trailers_and_bonus(shelves)

    season1_episodes = extract_season1_episodes(monarch_1, m2_ep_lookup)
    season2_episodes = extract_season2_episodes(m2_ep_lookup)

    seasons_output = build_seasons_output(
        seasons_list, season1_episodes, season2_episodes
    )

    output = {
        # Series level
        "series_id": series_id,
        "series_url": series_url,
        "title": show_info["title"],
        "is_new_series": False,
        "ranking": "",  
        "synopsis": show_info["synopsis"],
        "genres": show_info["genres"],
        "imdb_rating": "",  
        "release_year": release_year,
        "total_seasons_count": total_seasons_count,
        "content_advisory": content_advisory_list,
        "audio_languages": audio_languages_list,
        "subtitles": subtitles_list,
        "creators_and_cast": {
            "cast_and_crew": cast_and_crew_list, 
            "studio": studio,
        },
        "trailers_and_bonus": trailers_and_bonus,
        "seasons": seasons_output,
    }

    return output


def main():

    monarch_1_path = r"C:\Users\parth.khatri\Desktop\github\apple-tv\monarch_1.json"
    monarch_2_path = r"C:\Users\parth.khatri\Desktop\github\apple-tv\monarch_2.json"
    output_path = r"C:\Users\parth.khatri\Desktop\github\apple-tv\monarch_output.json"

    monarch_1 = load_json_file(monarch_1_path)
    monarch_2 = load_json_file(monarch_2_path)

    output = assemble_output(monarch_1, monarch_2)
    write_json_file(output, output_path)


if __name__ == "__main__":
    main()
