{
    # --- Series Level Data ---
    "series_id":  "data[1].data.shelves[1].header.id",   # monarch_2 json  Unique alphabetic alphanumeric identifier
    "series_url": "data[1].data.canonicalURL",  # Full target path URL monarch_2 json
    "title": "data[1].data.shelves[7].items[0].title",  # Title of the show from the monarch_2 json
    "is_new_series": bool,  # True/False flag for tags like "NEW SERIES"
    "ranking": str,  # make it empty Category ranking information (e.g., "#1 in...")
    "synopsis": "data[1].data.shelves[7].items[0].description",  # monarch_2 json Series overview narrative
    "genres": "data[1].data.shelves[7].items[0].genres",  # monarch_2 json Dynamic list of associated genre tags
    "imdb_rating": str,  # Score string representation
    "release_year": "data.playables.tvs.sbd.4000:A0019601003:978645c3.canonicalMetadata.releaseDate",  # Production/Release calendar year
    "total_seasons_count": "data[1].data.shelves[1].header.seasons[0].seasonNumber",  # monarch_2 json Summary metadata label of available seasons
    # --- Technical & Compliance Specifications ---
    "content_advisory": "data[1].data.shelves[8].items[0].items[2].info", #from monarch_2 json  
    "audio_languages": "data[1].data.shelves[8].items[1].items[1].info",  # from monarch_2 json 
    "subtitles": "data[1].data.shelves[8].items[1].items[2].info", # from monarch_2 json
    # --- Creative Production Credits ---
    "creators_and_cast": {
        "cast_and_crew": "data[1].data.shelves[5].items[0].title",  # from monarch_2 json List of directors' full names
        "studio": "data[1].data.channel.title",  # from monarch_2 json Distribution or production studio name
    },
    # --- Promotional & Media Links ---
    "trailers_and_bonus": list[
        {
            "title": "data[1].data.shelves[2].items[0].contextAction.title   and  data[1].data.shelves[3].items[0].contextAction.title",  # from monarch_2 json iterate thru all trailers and bonus content after the and keyword its the bonus content
            "video_stream_url": "data[1].data.shelves[2].items[0].contextAction.url and data[1].data.shelves[3].items[0].contextAction.url",  # Actionable URL to play video stream from monarch_2 json iterate thru all trailers and bonus content after the and keyword its the bonus content
            "thumbnail_url": "data[1].data.shelves[2].playlistItems[0].playlist.lockup.artwork.template  and data[1].data.shelves[3].items[0].artwork.template",  # Direct image hosting link for cover item from monarch_2 json iterate thru all trailers and bonus content after the and keyword its the bonus content
            "content_rating": str,  # Age rating tag specific to clip
            "duration": "data[1].data.shelves[2].playlistItems[0].playlist.tabData.duration and data[1].data.shelves[3].items[0].playAction.contentDescriptor.items[0].playable.canonicalMetadata.duration",  # type: ignore # Runtime string representation from monarch_2 json iterate thru all trailers and bonus content after the and keyword its the bonus content
        }
    ],
    # --- Seasonal Breakdown & Episodic Data ---
    "seasons": list[
        {
            "season_label": "data[1].data.shelves[1].header.seasons[0].title",  # Human-readable selector key (e.g., 'Season 1') iterate thru all seasons properly from monarch_2 json
            "total_episodes_count": "data[1].data.shelves[1].header.seasons[0].episodeCount",  # Total counted episodes within this specific season iterate thru all seasons properly from monarch_2 json
            "episodes": list[
                {
                    "episode_number": "data[1].data.shelves[1].items[14].episodeIndex",  # Chronological ordering counter index
                    "episode_title": "data.episodes[0].title and data[1].data.shelves[1].items[14].title",  # afer and is the monarch_2 json one path Custom episode specific title 
                    "episode_url": "data.episodes[0].url and data[1].data.shelves[1].items[14].segue.url",  # Direct navigation launch or deep play asset URL
                    "thumbnail_url": "data.episodes[0].images.contentImage.url  and  data[1].data.shelves[1].items[10].artwork.template",  # Direct image hosting link for frame thumbnail
                    "synopsis": "data.episodes[0].description and data[1].data.shelves[1].items[10].description",  # Brief plot setup details
                    "content_rating": str,  # Age classification value
                    "duration": "data.episodes[0].duration and data[1].data.shelves[1].items[5].metadata",  # Total tracking watch duration value so the second one after the and pat is in string and the st one is in time stamp format so we need to convert it to string
                    "release_date": "data.episodes[0].releaseDate  ",  # type: ignore # Regional catalog publishing string representation
                    # episode we have two different paths for the episode data so we need to iterate through both of them and get the data from both of them and if one of them is missing we need to get the data from the other one
                }
            ],
        }
    ],
}
