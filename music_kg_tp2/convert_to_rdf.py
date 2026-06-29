import os
import logging
import pandas as pd
import argparse
from urllib.parse import quote
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, OWL, XSD

# Namespaces
BASE   = Namespace("http://musickg.org/")
MUSIC  = Namespace("http://musickg.org/data/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

def safe_uri_part(text: str) -> str:
    return quote(str(text).strip().replace(" ", "_"), safe="")

def build_ontology() -> Graph:
    """Creates the formal RDFS/OWL Ontology."""
    g = Graph()
    g.bind("music", MUSIC)
    g.bind("owl", OWL)
    
    # Ontology Metadata
    g.add((MUSIC[""], RDF.type, OWL.Ontology))
    g.add((MUSIC[""], RDFS.label, Literal("Music Knowledge Graph Ontology")))

    # Core Classes
    classes = ["Artist", "Track", "Album", "Genre", "TrendingArtist", "HighEnergyTrack"]
    for cls in classes:
        g.add((MUSIC[cls], RDF.type, OWL.Class))
        
    # Subclasses (Prepared for SPIN later)
    g.add((MUSIC.TrendingArtist, RDFS.subClassOf, MUSIC.Artist))
    g.add((MUSIC.HighEnergyTrack, RDFS.subClassOf, MUSIC.Track))

    # Object Properties & Inverses (Pure OWL Inference)
    # Track -> performedBy -> Artist  <=>  Artist -> performs -> Track
    g.add((MUSIC.performedBy, RDF.type, OWL.ObjectProperty))
    g.add((MUSIC.performedBy, RDFS.domain, MUSIC.Track))
    g.add((MUSIC.performedBy, RDFS.range, MUSIC.Artist))
    
    g.add((MUSIC.performs, RDF.type, OWL.ObjectProperty))
    g.add((MUSIC.performs, OWL.inverseOf, MUSIC.performedBy))

    # Track -> inAlbum -> Album  <=>  Album -> hasTrack -> Track
    g.add((MUSIC.inAlbum, RDF.type, OWL.ObjectProperty))
    g.add((MUSIC.inAlbum, RDFS.domain, MUSIC.Track))
    g.add((MUSIC.inAlbum, RDFS.range, MUSIC.Album))

    g.add((MUSIC.hasTrack, RDF.type, OWL.ObjectProperty))
    g.add((MUSIC.hasTrack, OWL.inverseOf, MUSIC.inAlbum))

    # Track -> inGenre -> Genre
    g.add((MUSIC.inGenre, RDF.type, OWL.ObjectProperty))
    g.add((MUSIC.inGenre, RDFS.domain, MUSIC.Track))
    g.add((MUSIC.inGenre, RDFS.range, MUSIC.Genre))

    # Data Properties
    data_props = {
        "trackName": XSD.string, "artistName": XSD.string, "albumName": XSD.string,
        "releaseYear": XSD.integer, "popularity": XSD.integer, 
        "energy": XSD.float, "danceability": XSD.float, "valence": XSD.float, "tempo": XSD.float
    }
    for prop, datatype in data_props.items():
        g.add((MUSIC[prop], RDF.type, OWL.DatatypeProperty))
        g.add((MUSIC[prop], RDFS.range, datatype))

    return g

def load_and_clean(csv_path: str) -> pd.DataFrame:
    log.info(f"Loading raw dataset from: {csv_path}...")
    df = pd.read_csv(csv_path, encoding="utf-8")
    cols_to_keep = [
        "track_id", "track_name", "track_artist", "track_popularity",
        "track_album_name", "track_album_release_date", "playlist_genre",
        "energy", "danceability", "valence", "tempo"
    ]
    df = df[[c for c in cols_to_keep if c in df.columns]]
    df = df.rename(columns={"track_artist": "artist_name", "track_album_name": "album_name", "playlist_genre": "genre"})
    return df.dropna(subset=["artist_name", "track_name", "track_id"])

def convert_to_rdf(df: pd.DataFrame) -> Graph:
    g = Graph()
    g.bind("music", MUSIC)

    log.info("Materializing semantic statements (Facts)...")
    for row in df.itertuples(index=False):
        a_uri   = BASE[f"artist/{safe_uri_part(row.artist_name)}"]
        t_uri   = BASE[f"track/{safe_uri_part(row.track_id)}"]
        g_uri   = BASE[f"genre/{safe_uri_part(row.genre)}"]
        alb_uri = BASE[f"album/{safe_uri_part(row.artist_name)}_{safe_uri_part(row.album_name)}"]

        # Type declarations
        g.add((a_uri, RDF.type, MUSIC.Artist))
        g.add((t_uri, RDF.type, MUSIC.Track))
        g.add((alb_uri, RDF.type, MUSIC.Album))
        g.add((g_uri, RDF.type, MUSIC.Genre))

        # Properties
        g.add((t_uri, MUSIC.trackName, Literal(row.track_name, datatype=XSD.string)))
        g.add((t_uri, MUSIC.performedBy, a_uri))
        g.add((t_uri, MUSIC.inGenre, g_uri))
        g.add((t_uri, MUSIC.inAlbum, alb_uri))

        g.add((a_uri, MUSIC.artistName, Literal(row.artist_name, datatype=XSD.string)))
        g.add((g_uri, MUSIC.label, Literal(row.genre, datatype=XSD.string)))
        g.add((alb_uri, MUSIC.albumName, Literal(row.album_name, datatype=XSD.string)))

        release_date = str(row.track_album_release_date)
        if len(release_date) >= 4 and release_date[:4].isdigit():
            g.add((alb_uri, MUSIC.releaseYear, Literal(int(release_date[:4]), datatype=XSD.integer)))

        if pd.notna(row.track_popularity):
            g.add((t_uri, MUSIC.popularity, Literal(int(row.track_popularity), datatype=XSD.integer)))
        if pd.notna(row.energy):
            g.add((t_uri, MUSIC.energy, Literal(float(row.energy), datatype=XSD.float)))
        if pd.notna(row.danceability):
            g.add((t_uri, MUSIC.danceability, Literal(float(row.danceability), datatype=XSD.float)))
        if pd.notna(row.valence):
            g.add((t_uri, MUSIC.valence, Literal(float(row.valence), datatype=XSD.float)))
        if pd.notna(row.tempo):
            g.add((t_uri, MUSIC.tempo, Literal(float(row.tempo), datatype=XSD.float)))

    return g

def main(csv_path: str, data_dir: str) -> None:
    df = load_and_clean(csv_path)
    facts_graph = convert_to_rdf(df)
    onto_graph = build_ontology()

    # Integrated Graph (Ontology + Facts)
    combined_graph = Graph()
    combined_graph += facts_graph
    combined_graph += onto_graph

    os.makedirs(data_dir, exist_ok=True)
    
    # 1. Facts only (for clean separation)
    facts_graph.serialize(destination=os.path.join(data_dir, "facts_only.nt"), format="nt")
    
    # 2. Ontology only (for Protégé and GraphDB schema import)
    onto_graph.serialize(destination=os.path.join(data_dir, "ontology.ttl"), format="turtle")
    
    # 3. Combined Graph (for the Django app auto-load functionality)
    combined_graph.serialize(destination=os.path.join(data_dir, "music_kg.nt"), format="nt")
    
    log.info("Files generated successfully: 'facts_only.nt', 'ontology.ttl', 'music_kg.nt'")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="spotify_songs.csv")
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    main(args.csv, args.data_dir)
