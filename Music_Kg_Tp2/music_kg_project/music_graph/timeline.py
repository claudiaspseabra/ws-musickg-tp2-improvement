"""
music_graph/timeline.py

Timeline and genre-evolution queries.
"""
import logging
from typing import List, Dict
from rdflib import Namespace
from rdflib.namespace import RDF, RDFS

from music_graph.rdf_store import store
from music_graph.sparql_queries import _PREFIXES, _round

log = logging.getLogger(__name__)
MUSIC = Namespace("http://musickg.org/ontology#")


def _as_int(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _local_graph():
    return getattr(store, "_graph", None)


def _get_audio_features(graph, track):
    feature_node = graph.value(track, MUSIC.hasAudioFeatures)
    if not feature_node:
        return {}
    return {
        "energy": _as_float(graph.value(feature_node, MUSIC.energy)),
        "danceability": _as_float(graph.value(feature_node, MUSIC.danceability)),
        "valence": _as_float(graph.value(feature_node, MUSIC.valence)),
    }


def _get_label(graph, subject) -> str | None:
    value = graph.value(subject, RDFS.label)
    return str(value) if value is not None else None


def _fallback_timeline_data(start_year: int, end_year: int) -> List[Dict]:
    graph = _local_graph()
    if not graph:
        return []

    years: dict[int, dict] = {}
    for album, _, year_value in graph.triples((None, MUSIC.releaseYear, None)):
        year = _as_int(year_value, None)
        if year is None or year < start_year or year > end_year:
            continue

        row = years.setdefault(
            year,
            {
                "tracks": set(),
                "artists": set(),
                "genres": {},
                "features": {"energy": [], "danceability": []},
                "top_tracks": [],
            },
        )

        for track in graph.objects(album, MUSIC.hasTrack):
            row["tracks"].add(track)

            artist = graph.value(track, MUSIC.performedBy)
            if artist:
                row["artists"].add(artist)

            genre = graph.value(track, MUSIC.inGenre)
            if genre:
                label = _get_label(graph, genre) or str(genre).rstrip("/").split("/")[-1]
                row["genres"][label] = row["genres"].get(label, 0) + 1

            features = _get_audio_features(graph, track)
            for key in ("energy", "danceability"):
                if features.get(key) is not None:
                    row["features"][key].append(features[key])

            name = graph.value(track, MUSIC.trackName)
            popularity = _as_int(graph.value(track, MUSIC.popularity), 0)
            artist_name = graph.value(artist, MUSIC.artistName) if artist else None
            if name:
                row["top_tracks"].append(
                    {
                        "name": str(name),
                        "artist": str(artist_name) if artist_name else "Unknown",
                        "popularity": popularity,
                    }
                )

    timeline = []
    for year in sorted(years):
        row = years[year]
        top_genre = None
        if row["genres"]:
            top_genre = max(row["genres"].items(), key=lambda item: item[1])[0]

        energy_values = row["features"]["energy"]
        dance_values = row["features"]["danceability"]
        top_tracks = sorted(
            row["top_tracks"],
            key=lambda track: track.get("popularity", 0),
            reverse=True,
        )[:3]

        timeline.append(
            {
                "year": year,
                "track_count": len(row["tracks"]),
                "artist_count": len(row["artists"]),
                "top_genre": top_genre,
                "avg_energy": round(sum(energy_values) / len(energy_values), 4) if energy_values else None,
                "avg_danceability": round(sum(dance_values) / len(dance_values), 4) if dance_values else None,
                "top_tracks": top_tracks,
            }
        )
    return timeline


def _fallback_genre_evolution(genre_name: str) -> List[Dict]:
    graph = _local_graph()
    if not graph:
        return []

    target = genre_name.strip().lower()
    genre_nodes = [
        genre
        for genre in graph.subjects(RDF.type, MUSIC.Genre)
        if (_get_label(graph, genre) or str(genre).rstrip("/").split("/")[-1]).lower() == target
    ]
    if not genre_nodes:
        return []

    decades: dict[int, dict] = {}
    for genre in genre_nodes:
        for track in graph.subjects(MUSIC.inGenre, genre):
            album = graph.value(predicate=MUSIC.hasTrack, object=track)
            year = _as_int(graph.value(album, MUSIC.releaseYear) if album else None, None)
            if year is None or year < 1950 or year > 2024:
                continue

            decade = (year // 10) * 10
            row = decades.setdefault(
                decade,
                {
                    "tracks": set(),
                    "energy": [],
                    "danceability": [],
                    "valence": [],
                },
            )
            row["tracks"].add(track)
            features = _get_audio_features(graph, track)
            for key in ("energy", "danceability", "valence"):
                if features.get(key) is not None:
                    row[key].append(features[key])

    result = []
    for decade in sorted(decades):
        row = decades[decade]
        result.append(
            {
                "decade": decade,
                "track_count": len(row["tracks"]),
                "avg_energy": round(sum(row["energy"]) / len(row["energy"]), 4) if row["energy"] else None,
                "avg_danceability": round(sum(row["danceability"]) / len(row["danceability"]), 4) if row["danceability"] else None,
                "avg_valence": round(sum(row["valence"]) / len(row["valence"]), 4) if row["valence"] else None,
            }
        )
    return result


def get_timeline_data(start_year: int = 1950, end_year: int = 2024) -> List[Dict]:
    """
    Per-year aggregate: track count, artist count, top genre,
    avg audio features, top tracks by popularity.
    """
    if not store.using_graphdb:
        return _fallback_timeline_data(start_year, end_year)

    # Step 1 — per-year aggregates
    agg_q = _PREFIXES + f"""
    SELECT ?year
           (COUNT(DISTINCT ?track)  AS ?trackCount)
           (COUNT(DISTINCT ?artist) AS ?artistCount)
           (AVG(?energy)            AS ?avgEnergy)
           (AVG(?dance)             AS ?avgDance)
    WHERE {{
        ?album music:releaseYear ?year ;
               music:hasTrack ?track .
        ?track music:performedBy ?artist .
        OPTIONAL {{
            ?track music:hasAudioFeatures ?af .
            ?af music:energy ?energy ;
                music:danceability ?dance .
        }}
        FILTER (?year >= {start_year} && ?year <= {end_year})
    }}
    GROUP BY ?year
    ORDER BY ?year
    """
    agg_rows = store.execute_sparql(agg_q)

    # Step 2 — top genre per year
    genre_q = _PREFIXES + f"""
    SELECT ?year ?genreLabel (COUNT(?track) AS ?cnt) WHERE {{
        ?album music:releaseYear ?year ;
               music:hasTrack ?track .
        ?track music:inGenre ?g .
        ?g rdfs:label ?genreLabel .
        FILTER (?year >= {start_year} && ?year <= {end_year})
    }}
    GROUP BY ?year ?genreLabel
    ORDER BY ?year DESC(?cnt)
    """
    genre_rows = store.execute_sparql(genre_q)

    # Build top-genre map (first result per year is highest count due to ORDER BY)
    top_genre_map: Dict[int, str] = {}
    for r in genre_rows:
        y = int(r["year"]) if r.get("year") is not None else None
        if y and y not in top_genre_map:
            top_genre_map[y] = str(r["genreLabel"])

    # Step 3 — top 3 tracks per year
    top_tracks_q = _PREFIXES + f"""
    SELECT ?year ?trackName ?artistName ?popularity WHERE {{
        ?album music:releaseYear ?year ;
               music:hasTrack ?track .
        ?track music:trackName ?trackName ;
               music:performedBy ?artist .
        ?artist music:artistName ?artistName .
        OPTIONAL {{ ?track music:popularity ?popularity }}
        FILTER (?year >= {start_year} && ?year <= {end_year})
    }}
    ORDER BY ?year DESC(?popularity)
    """
    track_rows = store.execute_sparql(top_tracks_q)

    top_tracks_map: Dict[int, list] = {}
    for r in track_rows:
        y = int(r["year"]) if r.get("year") is not None else None
        if y is None:
            continue
        lst = top_tracks_map.setdefault(y, [])
        if len(lst) < 3:
            lst.append({
                "name":       str(r["trackName"]),
                "artist":     str(r["artistName"]),
                "popularity": r.get("popularity", 0),
            })

    # Assemble result
    timeline = []
    for r in agg_rows:
        y = int(r["year"]) if r.get("year") is not None else None
        if y is None:
            continue
        timeline.append({
            "year":          y,
            "track_count":   r.get("trackCount", 0),
            "artist_count":  r.get("artistCount", 0),
            "top_genre":     top_genre_map.get(y),
            "avg_energy":    _round(r.get("avgEnergy")),
            "avg_danceability": _round(r.get("avgDance")),
            "top_tracks":    top_tracks_map.get(y, []),
        })
    return timeline


def get_genre_evolution(genre_name: str) -> List[Dict]:
    """
    How a genre's audio features changed by decade.
    Returns [{decade, avg_energy, avg_danceability, avg_valence, track_count}]
    """
    if not store.using_graphdb:
        return _fallback_genre_evolution(genre_name)

    safe_genre = genre_name.replace('"', '\\"')

    query = _PREFIXES + f"""
    SELECT ?decade
           (COUNT(DISTINCT ?track)  AS ?trackCount)
           (AVG(?energy)            AS ?avgEnergy)
           (AVG(?dance)             AS ?avgDance)
           (AVG(?valence)           AS ?avgValence)
    WHERE {{
        ?g a music:Genre ;
           rdfs:label "{safe_genre}" .
        ?track music:inGenre ?g .
        ?album music:hasTrack ?track ;
               music:releaseYear ?year .
        BIND (FLOOR(?year / 10) * 10 AS ?decade)
        OPTIONAL {{
            ?track music:hasAudioFeatures ?af .
            ?af music:energy ?energy ;
                music:danceability ?dance ;
                music:valence ?valence .
        }}
        FILTER (?year >= 1950 && ?year <= 2024)
    }}
    GROUP BY ?decade
    ORDER BY ?decade
    """

    rows = store.execute_sparql(query)
    return [
        {
            "decade":          int(r["decade"]) if r.get("decade") is not None else None,
            "track_count":     r.get("trackCount", 0),
            "avg_energy":      _round(r.get("avgEnergy")),
            "avg_danceability": _round(r.get("avgDance")),
            "avg_valence":     _round(r.get("avgValence")),
        }
        for r in rows
        if r.get("decade") is not None
    ]