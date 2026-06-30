import os
import argparse
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD

# Namespaces
MUSIC = Namespace("http://musickg.org/data/")
SPIN = Namespace("http://spinrdf.org/spin#")
SP = Namespace("http://spinrdf.org/sp#")

DEFAULT_OUTPUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spin_rules.ttl")

def add_construct_rule(graph: Graph, owner_class: URIRef, rule_uri: URIRef, label: str, construct_text: str):
    graph.add((owner_class, SPIN.rule, rule_uri))
    graph.add((rule_uri, RDF.type, SPIN.Rule))
    graph.add((rule_uri, RDF.type, SP.Construct))
    graph.add((rule_uri, RDFS.label, Literal(label)))
    graph.add((rule_uri, SP.text, Literal(construct_text.strip())))

def build_spin_rules() -> Graph:
    graph = Graph()
    graph.bind("music", MUSIC)
    graph.bind("spin", SPIN)
    graph.bind("sp", SP)

    # Rule 1: High Energy Track Classification
    add_construct_rule(
        graph,
        MUSIC.Track,
        MUSIC.ClassifyHighEnergyTrackRule,
        "Classify High Energy Tracks",
        """
        PREFIX music: <http://musickg.org/data/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
            ?this a music:HighEnergyTrack .
        }
        WHERE {
            ?this a music:Track ;
                  music:energy ?e .
            FILTER (xsd:float(?e) > 0.8)
        }
        """
    )

    # Rule 2: Trending Artist Classification
    add_construct_rule(
        graph,
        MUSIC.Artist,
        MUSIC.ClassifyTrendingArtistRule,
        "Classify Trending Artists based on track popularity average",
        """
        PREFIX music: <http://musickg.org/data/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
            ?this a music:TrendingArtist .
        }
        WHERE {
            SELECT ?this WHERE {
                ?this a music:Artist .
                ?this music:performedBy ?this ;
                       music:popularity ?pop .
            }
            GROUP BY ?this
            HAVING (AVG(xsd:float(?pop)) >= 75.0)
        }
        """
    )

    # Rule 3: Popular Track Classification
    add_construct_rule(
        graph,
        MUSIC.Track,
        MUSIC.ClassifyPopularTrackRule,
        "Classify popular tracks",
        """
        PREFIX music: <http://musickg.org/data/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
            ?this a music:PopularTrack .
        }
        WHERE {
            ?this music:popularity ?popularity .
            FILTER (xsd:integer(?popularity) >= 70)
        }
        """
    )

    # Rule 4: Release Era Classification for Albums
    add_construct_rule(
        graph,
        MUSIC.Album,
        MUSIC.ClassifyReleaseEraRule,
        "Classify release eras",
        """
        PREFIX music: <http://musickg.org/data/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        CONSTRUCT {
            ?this a music:ClassicAlbum . 
        }
        WHERE {
            ?this a music:Album ;
                  music:releaseYear ?year .
            BIND(xsd:integer(?year) AS ?releaseYear)
            BIND(
                IF(?releaseYear >= 2010, music:ModernAlbum,
                  IF(?releaseYear < 2000, music:ClassicAlbum, music:TransitionAlbum)
                ) AS ?albumClass
            )
        }
        """
    )

    return graph

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    graph = build_spin_rules()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    graph.serialize(destination=args.output, format="turtle")
    print(f"SPIN rules successfully generated at: {args.output} ({len(graph)} triples)")

if __name__ == "__main__":
    main()
