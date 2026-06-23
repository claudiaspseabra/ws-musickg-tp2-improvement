"""
Optional DBpedia/Wikidata enrichment for the Music Knowledge Graph.

This module is intentionally independent from Django startup and the normal RDF
generation path. It reads local RDF, follows existing DBpedia owl:sameAs links
for a small controlled subset of artists/genres, and writes enrichment triples
to a separate Turtle file.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD
from SPARQLWrapper import JSON, SPARQLWrapper

from music_graph.rdf_store import store

BASE = Namespace("http://musickg.org/")
MUSIC = Namespace("http://musickg.org/ontology#")
SCHEMA = Namespace("http://schema.org/")
DBPEDIA_RESOURCE = "http://dbpedia.org/resource/"
WIKIDATA_ENTITY = "http://www.wikidata.org/entity/"
DBPEDIA_ENDPOINT = "https://dbpedia.org/sparql"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    local_uri: URIRef
    dbpedia_uri: URIRef
    kind: str
    label: str


@dataclass
class EnrichmentStats:
    candidates_seen: int = 0
    queried: int = 0
    enriched_resources: int = 0
    triples_added: int = 0
    failures: int = 0


def guess_rdf_format(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".ttl", ".turtle"}:
        return "turtle"
    if suffix in {".nt", ".ntriples"}:
        return "nt"
    if suffix in {".rdf", ".xml", ".owl"}:
        return "xml"
    return "xml"


def bind_prefixes(graph: Graph) -> None:
    graph.bind("base", BASE)
    graph.bind("music", MUSIC)
    graph.bind("schema", SCHEMA)
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("xsd", XSD)


def resource_label(graph: Graph, subject: URIRef) -> str:
    for predicate in (MUSIC.artistName, RDFS.label):
        value = graph.value(subject, predicate)
        if value:
            return str(value)
    return str(subject).rstrip("/").split("/")[-1].replace("_", " ")


def is_dbpedia_resource(uri: URIRef) -> bool:
    return str(uri).startswith(DBPEDIA_RESOURCE)


def collect_candidates(graph: Graph, limit: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[URIRef] = set()

    for cls, kind in ((MUSIC.Artist, "artist"), (MUSIC.Genre, "genre")):
        for subject in graph.subjects(RDF.type, cls):
            if subject in seen:
                continue
            dbpedia_uri = next(
                (
                    same_as
                    for same_as in graph.objects(subject, OWL.sameAs)
                    if isinstance(same_as, URIRef) and is_dbpedia_resource(same_as)
                ),
                None,
            )
            if not dbpedia_uri:
                continue
            seen.add(subject)
            candidates.append(
                Candidate(
                    local_uri=subject,
                    dbpedia_uri=dbpedia_uri,
                    kind=kind,
                    label=resource_label(graph, subject),
                )
            )
            if len(candidates) >= limit:
                return candidates

    return candidates


def sparql_literal(uri: URIRef) -> str:
    return f"<{str(uri)}>"


def build_dbpedia_query(dbpedia_uri: URIRef) -> str:
    resource = sparql_literal(dbpedia_uri)
    return f"""
PREFIX dbo: <http://dbpedia.org/ontology/>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?abstract ?origin ?homepage ?wikidata WHERE {{
  VALUES ?resource {{ {resource} }}
  OPTIONAL {{
    ?resource dbo:abstract ?abstract .
    FILTER(langMatches(lang(?abstract), "EN"))
  }}
  OPTIONAL {{ ?resource dbo:birthPlace ?origin . }}
  OPTIONAL {{ ?resource dbo:hometown ?origin . }}
  OPTIONAL {{ ?resource dbo:origin ?origin . }}
  OPTIONAL {{ ?resource foaf:homepage ?homepage . }}
  OPTIONAL {{
    ?resource owl:sameAs ?wikidata .
    FILTER(STRSTARTS(STR(?wikidata), "{WIKIDATA_ENTITY}"))
  }}
}}
LIMIT 1
"""


def first_binding_value(binding: dict, key: str) -> str | None:
    value = binding.get(key)
    if not value:
        return None
    return value.get("value")


def uri_or_literal(value: str):
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return URIRef(value)
    return Literal(value)


def add_enrichment_triples(
    graph: Graph,
    candidate: Candidate,
    binding: dict,
) -> int:
    before = len(graph)
    abstract = first_binding_value(binding, "abstract")
    origin = first_binding_value(binding, "origin")
    homepage = first_binding_value(binding, "homepage")
    wikidata = first_binding_value(binding, "wikidata")

    if abstract:
        graph.add((candidate.local_uri, MUSIC.dbpediaAbstract, Literal(abstract, lang="en")))
    if origin:
        graph.add((candidate.local_uri, MUSIC.originPlace, uri_or_literal(origin)))
    if homepage:
        graph.add((candidate.local_uri, MUSIC.officialWebsite, URIRef(homepage)))
    if wikidata:
        wikidata_uri = URIRef(wikidata)
        graph.add((candidate.local_uri, MUSIC.wikidataEntity, wikidata_uri))
        graph.add((candidate.local_uri, OWL.sameAs, wikidata_uri))

    return len(graph) - before


def query_dbpedia(candidate: Candidate, timeout: int) -> dict | None:
    wrapper = SPARQLWrapper(DBPEDIA_ENDPOINT)
    wrapper.setQuery(build_dbpedia_query(candidate.dbpedia_uri))
    wrapper.setReturnFormat(JSON)
    wrapper.setTimeout(timeout)

    results = wrapper.query().convert()
    bindings = results.get("results", {}).get("bindings", [])
    return bindings[0] if bindings else None


def enrich(
    input_path: str,
    output_path: str,
    limit: int,
    timeout: int,
    enriched_output_path: str | None = None,
) -> EnrichmentStats:
    source = Graph()
    bind_prefixes(source)
    rdf_format = guess_rdf_format(input_path)
    source.parse(input_path, format=rdf_format)

    candidates = collect_candidates(source, limit)
    enrichment = Graph()
    bind_prefixes(enrichment)
    stats = EnrichmentStats(candidates_seen=len(candidates))

    for candidate in candidates:
        stats.queried += 1
        try:
            binding = query_dbpedia(candidate, timeout)
        except Exception as exc:  # Endpoint/network failures must not abort the run.
            stats.failures += 1
            log.warning(
                "Skipping %s <%s>: %s",
                candidate.kind,
                candidate.dbpedia_uri,
                exc,
            )
            continue

        if not binding:
            continue

        added = add_enrichment_triples(enrichment, candidate, binding)
        if added:
            stats.enriched_resources += 1
            stats.triples_added += added

            abstract = first_binding_value(binding, "abstract")

            if abstract:
                safe_abstract = abstract.replace("" , "").replace('\\', '')

                update_query = f"""
                PREFIX music: <http://musickg.org/ontology#>
                INSERT DATA {{
                    <{candidate.local_uri}> music:dbpediaAbstract "{safe_abstract}"@en .
                }}
                """
                store.execute_sparql_update(update_query)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    enrichment.serialize(destination=output_path, format="turtle")

    if enriched_output_path:
        combined = Graph()
        bind_prefixes(combined)
        for triple in source:
            combined.add(triple)
        for triple in enrichment:
            combined.add(triple)
        os.makedirs(os.path.dirname(enriched_output_path) or ".", exist_ok=True)
        combined.serialize(destination=enriched_output_path, format="turtle")

    return stats


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return parsed


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich local Music KG artist/genre resources from DBpedia."
    )
    parser.add_argument(
        "--input",
        default="music_kg_project/data/facts_only.nt",
        help="Input RDF file, usually facts_only.nt or music_kg_integrated.rdf.",
    )
    parser.add_argument(
        "--output",
        default="music_kg_project/data/enrichment.ttl",
        help="Output Turtle enrichment file.",
    )
    parser.add_argument(
        "--limit",
        type=positive_int,
        default=20,
        help="Maximum number of local artist/genre resources to query.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_int,
        default=10,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "--enriched-output",
        default=None,
        help="Optional Turtle output containing input graph plus enrichment triples.",
    )
    return parser.parse_args(argv)


def fetch_and_save_dbpedia_data(artist_uri, dbpedia_uri):
    clean_dbpedia_uri = dbpedia_uri.strip("<>")
    clean_artist_uri = artist_uri.strip("<>")

    sparql = SPARQLWrapper("http://dbpedia.org/sparql")

    query = f"""
    PREFIX dbo: <http://dbpedia.org/ontology/>
    SELECT ?abstract WHERE {{
        <{clean_dbpedia_uri}> dbo:abstract ?abstract .
        FILTER (lang(?abstract) = 'en')
    }} LIMIT 1
    """

    sparql.setQuery(query)
    sparql.setReturnFormat(JSON)

    try:
        results = sparql.query().convert()
        bindings = results["results"]["bindings"]

        if bindings:
            abstract_text = bindings[0]["abstract"]["value"]

            safe_abstract = abstract_text.replace('"', "'").replace('\\', '')

            update_query = f"""
            PREFIX music: <http://musickg.org/ontology#>
            INSERT DATA {{
                <{clean_artist_uri}> music:dbpediaAbstract "{safe_abstract}"@en .
            }}
            """
            store.execute_sparql_update(update_query)
            print(f"Success: Enriched {clean_artist_uri} with DBpedia abstract.")
            return True

    except Exception as e:
        print(f"Error fetching DBpedia data for {clean_artist_uri}: {e}")

    return False

def main(argv: Iterable[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)

    stats = enrich(
        input_path=args.input,
        output_path=args.output,
        limit=args.limit,
        timeout=args.timeout,
        enriched_output_path=args.enriched_output,
    )

    print("Linked-data enrichment summary")
    print(f"  candidates: {stats.candidates_seen}")
    print(f"  queried: {stats.queried}")
    print(f"  enriched resources: {stats.enriched_resources}")
    print(f"  triples added: {stats.triples_added}")
    print(f"  failures: {stats.failures}")
    print(f"  output: {args.output}")
    if args.enriched_output:
        print(f"  enriched graph: {args.enriched_output}")


if __name__ == "__main__":
    main()
